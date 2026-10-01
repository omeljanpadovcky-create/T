"""Multi-Horizon Validation SHADOW for MYSHKA / ASTRA.

Records the same STRICT 4/4 candidates at 5m / 10m / 15m and settles them
from ordinary ASTRA scan prices. It never fetches market data itself, never
changes ENTER/DROP, and never routes orders.
"""
from __future__ import annotations

from collections import defaultdict
import math
import os
import sqlite3
import threading
import time
from typing import Any, Optional

DB_PATH = os.getenv("MULTIHORIZON_DB_PATH", "/data/myshka_multihorizon.sqlite3")
ANALYTICS_DB_PATH = os.getenv("ANALYTICS_DB_PATH", "/data/myshka_analytics.sqlite3")
HORIZONS = tuple(sorted({int(x) for x in os.getenv("MULTIHORIZON_HORIZONS_SEC", "300,600,900").split(",") if x.strip()}))
MAX_SETTLE_DELAY_SEC = max(30, int(os.getenv("MULTIHORIZON_MAX_SETTLE_DELAY_SEC", "90")))
_LOCK = threading.RLock()


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def init() -> dict:
    with _LOCK, _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS mh_outcomes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                side TEXT NOT NULL,
                source_minute INTEGER NOT NULL,
                horizon_sec INTEGER NOT NULL,
                opened_at REAL NOT NULL,
                target_at REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                entry_price REAL NOT NULL,
                exit_price REAL,
                action TEXT,
                reason TEXT,
                tech_score INTEGER NOT NULL,
                edge_pct REAL,
                total_cost_pct REAL,
                basis TEXT,
                rsi REAL,
                volume_ratio REAL,
                directional_5m_pct REAL,
                directional_15m_pct REAL,
                settled_at REAL,
                settle_delay_sec REAL,
                gross_pct REAL,
                net_pct REAL,
                direction_hit INTEGER,
                UNIQUE(pair,side,source_minute,horizon_sec)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_mh_status_target ON mh_outcomes(status,target_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_mh_horizon_status ON mh_outcomes(horizon_sec,status)")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS mh_meta(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        row = con.execute("SELECT value FROM mh_meta WHERE key='post_calibration_v2_started_at'").fetchone()
        if not row:
            first = con.execute("SELECT MIN(opened_at) FROM mh_outcomes").fetchone()
            started = float(first[0]) if first and first[0] is not None else time.time()
            con.execute(
                "INSERT OR IGNORE INTO mh_meta(key,value) VALUES('post_calibration_v2_started_at',?)",
                (str(started),),
            )
    return {
        "enabled": True,
        "mode": "SHADOW",
        "db_path": DB_PATH,
        "horizons_sec": list(HORIZONS),
    }


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _strict_score(sig: dict) -> int:
    direction = str(sig.get("direction") or "WAIT").upper()
    fast, slow = _num(sig.get("ema_fast")), _num(sig.get("ema_slow"))
    rsi, vol = _num(sig.get("rsi")), _num(sig.get("volume_ratio"))
    regime = str(sig.get("structure") or "RANGE").upper()
    if direction not in {"LONG","SHORT"} or None in {fast,slow,rsi,vol}:
        return 0
    if direction == "LONG":
        checks = [fast > slow, regime == "UP", 52 <= rsi <= 72, vol >= 0.60]
    else:
        checks = [fast < slow, regime == "DOWN", 28 <= rsi <= 48, vol >= 0.60]
    return sum(bool(x) for x in checks)


def _market_price(result: dict) -> Optional[float]:
    x = _num((result.get("market") or {}).get("last_price"))
    return x if x is not None and x > 0 else None


def _directional(raw_pct: Any, side: str) -> Optional[float]:
    x = _num(raw_pct)
    if x is None:
        return None
    return x if side == "LONG" else -x


def _record(result: dict, now: float) -> int:
    sig = result.get("signal") or {}
    side = str(result.get("direction") or sig.get("direction") or "WAIT").upper()
    if side not in {"LONG","SHORT"} or _strict_score(sig) != 4:
        return 0
    pair = str(result.get("pair") or "")
    entry = _market_price(result)
    if not pair or entry is None:
        return 0

    edge = result.get("edge") or {}
    ctx = result.get("context") or {}
    source_minute = int(now // 60) * 60
    values_common = {
        "action": str(result.get("action") or ""),
        "reason": str(result.get("reason") or ""),
        "tech_score": 4,
        "edge_pct": _num(edge.get("net_edge_pct")),
        "total_cost_pct": _num(edge.get("total_cost_pct")),
        "basis": str(edge.get("basis") or ""),
        "rsi": _num(sig.get("rsi")),
        "volume_ratio": _num(sig.get("volume_ratio")),
        "directional_5m_pct": _directional(ctx.get("price_change_5m_pct"), side),
        "directional_15m_pct": _directional(ctx.get("price_change_15m_pct"), side),
    }

    made = 0
    with _LOCK, _conn() as con:
        for horizon in HORIZONS:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO mh_outcomes(
                    pair,side,source_minute,horizon_sec,opened_at,target_at,status,entry_price,
                    action,reason,tech_score,edge_pct,total_cost_pct,basis,rsi,volume_ratio,
                    directional_5m_pct,directional_15m_pct
                ) VALUES(?,?,?,?,?,?, 'OPEN', ?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pair, side, source_minute, int(horizon), now, now + int(horizon), entry,
                    values_common["action"], values_common["reason"], values_common["tech_score"],
                    values_common["edge_pct"], values_common["total_cost_pct"], values_common["basis"],
                    values_common["rsi"], values_common["volume_ratio"],
                    values_common["directional_5m_pct"], values_common["directional_15m_pct"],
                ),
            )
            made += int(bool(cur.rowcount))
    return made


def _settle(results: list[dict], now: float) -> dict:
    by_pair = {str(r.get("pair") or ""): r for r in results or [] if r.get("pair")}
    settled = skipped = 0
    with _LOCK, _conn() as con:
        rows = con.execute(
            "SELECT * FROM mh_outcomes WHERE status='OPEN' AND target_at<=? ORDER BY target_at ASC",
            (now,),
        ).fetchall()
        for row in rows:
            delay = max(0.0, now - float(row["target_at"]))
            if delay > MAX_SETTLE_DELAY_SEC:
                con.execute(
                    "UPDATE mh_outcomes SET status='SKIPPED', settled_at=?, settle_delay_sec=? WHERE id=? AND status='OPEN'",
                    (now, delay, int(row["id"])),
                )
                skipped += 1
                continue
            result = by_pair.get(str(row["pair"]))
            if not result:
                continue
            exit_price = _market_price(result)
            if exit_price is None:
                continue
            entry = float(row["entry_price"])
            raw = (exit_price / entry - 1.0) * 100.0
            gross = raw if str(row["side"]) == "LONG" else -raw
            costs = float(row["total_cost_pct"] or 0.0)
            net = gross - costs
            con.execute(
                """
                UPDATE mh_outcomes
                SET status='CLOSED',exit_price=?,settled_at=?,settle_delay_sec=?,
                    gross_pct=?,net_pct=?,direction_hit=?
                WHERE id=? AND status='OPEN'
                """,
                (exit_price, now, delay, gross, net, 1 if gross > 0 else 0, int(row["id"])),
            )
            settled += 1
    return {"settled": settled, "skipped": skipped}


def observe_results(results: list[dict], now: Optional[float] = None) -> dict:
    try:
        init()
        ts = float(now if now is not None else time.time())
        settled = _settle(results or [], ts)
        created = sum(_record(r, ts) for r in (results or []))
        return {"status":"ok","created":created,**settled}
    except Exception as exc:
        return {"status":"error","error":f"{type(exc).__name__}: {exc}","created":0,"settled":0,"skipped":0}


def _metrics(rows: list[dict]) -> dict:
    nets = [float(r["net_pct"]) for r in rows if _num(r.get("net_pct")) is not None]
    gross = [float(r["gross_pct"]) for r in rows if _num(r.get("gross_pct")) is not None]
    n = len(nets)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    pos = sum(wins); neg = abs(sum(losses))
    return {
        "n":n,
        "net_wins":len(wins),
        "net_win_rate_pct":(len(wins)/n*100.0) if n else 0.0,
        "direction_hit_rate_pct":(sum(1 for x in gross if x > 0)/len(gross)*100.0) if gross else 0.0,
        "avg_net_pct":(sum(nets)/n) if n else 0.0,
        "total_net_pct":sum(nets),
        "profit_factor":(pos/neg) if neg > 1e-12 else (999.0 if pos > 0 else 0.0),
    }


def report() -> dict:
    init()
    with _LOCK, _conn() as con:
        closed = [dict(r) for r in con.execute("SELECT * FROM mh_outcomes WHERE status='CLOSED' ORDER BY opened_at").fetchall()]
        open_n = int(con.execute("SELECT COUNT(*) FROM mh_outcomes WHERE status='OPEN'").fetchone()[0])
        skipped = int(con.execute("SELECT COUNT(*) FROM mh_outcomes WHERE status='SKIPPED'").fetchone()[0])
    by_h: dict[str, dict] = {}
    for h in HORIZONS:
        part = [r for r in closed if int(r["horizon_sec"]) == int(h)]
        band = [r for r in part if _num(r.get("edge_pct")) is not None and 0.08 <= float(r["edge_pct"]) < 0.15]
        by_h[str(h)] = {
            "all_strict": _metrics(part),
            "calibration_band_0.08_0.15": _metrics(band),
        }
    return {
        "status":"ok",
        "mode":"SHADOW",
        "shadow_only":True,
        "horizons_sec":list(HORIZONS),
        "open":open_n,
        "skipped":skipped,
        "closed":len(closed),
        "by_horizon":by_h,
        "extra_market_api_calls":False,
        "changes_trading_decisions":False,
    }


def _post_calibration_started_at() -> float:
    init()
    with _LOCK, _conn() as con:
        row = con.execute(
            "SELECT value FROM mh_meta WHERE key='post_calibration_v2_started_at'"
        ).fetchone()
        if row:
            try:
                return float(row["value"])
            except Exception:
                pass
        first = con.execute("SELECT MIN(opened_at) AS first_at FROM mh_outcomes").fetchone()
        started = float(first["first_at"]) if first and first["first_at"] is not None else time.time()
        con.execute(
            "INSERT OR REPLACE INTO mh_meta(key,value) VALUES('post_calibration_v2_started_at',?)",
            (str(started),),
        )
        return started


def _post_analytics_rows(started_at: float) -> list[dict]:
    if not os.path.exists(ANALYTICS_DB_PATH):
        return []
    try:
        con = sqlite3.connect(ANALYTICS_DB_PATH, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                """
                SELECT *
                FROM analytics_trades
                WHERE status='CLOSED'
                  AND mode='STRICT'
                  AND opened_at>=?
                ORDER BY opened_at ASC
                """,
                (float(started_at),),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()
    except Exception:
        return []


def post_calibration_report() -> dict:
    """Strict PAPER + 5/10/15m SHADOW stats since EDGE Calibration V2 began."""
    init()
    started = _post_calibration_started_at()
    paper_rows = _post_analytics_rows(started)
    paper = _metrics(paper_rows)

    with _LOCK, _conn() as con:
        rows = [
            dict(r) for r in con.execute(
                """
                SELECT *
                FROM mh_outcomes
                WHERE status='CLOSED' AND opened_at>=?
                ORDER BY opened_at ASC
                """,
                (float(started),),
            ).fetchall()
        ]
        open_n = int(con.execute(
            "SELECT COUNT(*) FROM mh_outcomes WHERE status='OPEN' AND opened_at>=?",
            (float(started),),
        ).fetchone()[0])
        skipped_n = int(con.execute(
            "SELECT COUNT(*) FROM mh_outcomes WHERE status='SKIPPED' AND opened_at>=?",
            (float(started),),
        ).fetchone()[0])

    by_horizon: dict[str, dict] = {}
    for h in HORIZONS:
        part = [r for r in rows if int(r.get("horizon_sec") or 0) == int(h)]
        band = [
            r for r in part
            if _num(r.get("edge_pct")) is not None
            and 0.08 <= float(r.get("edge_pct") or 0.0) <= 0.15
        ]
        by_horizon[str(h)] = {
            "all_strict": _metrics(part),
            "calibration_band_0.08_0.15": _metrics(band),
        }

    # Ordered point series for the dashboard chart. Keep the payload bounded but
    # preserve one point per CLOSED calibration-band outcome.
    chart_series: dict[str, list[dict]] = {}
    for h in HORIZONS:
        band_rows = [
            r for r in rows
            if int(r.get("horizon_sec") or 0) == int(h)
            and _num(r.get("edge_pct")) is not None
            and 0.08 <= float(r.get("edge_pct") or 0.0) <= 0.15
            and _num(r.get("net_pct")) is not None
        ]
        chart_series[str(h)] = [
            {
                "id": int(r.get("id") or 0),
                "opened_at": float(r.get("opened_at") or 0.0),
                "pair": str(r.get("pair") or ""),
                "side": str(r.get("side") or ""),
                "edge_pct": float(r.get("edge_pct") or 0.0),
                "net_pct": float(r.get("net_pct") or 0.0),
                "gross_pct": float(r.get("gross_pct") or 0.0),
                "direction_hit": bool(r.get("direction_hit")),
            }
            for r in band_rows[-120:]
        ]

    n = int(paper.get("n") or 0)
    return {
        "status": "ok",
        "mode": "POST_CALIBRATION_V2",
        "started_at": started,
        "paper_strict": paper,
        "sample_state": "COLD" if n < 10 else "EARLY" if n < 30 else "USABLE" if n < 100 else "MATURE",
        "edge_band_pct": {"min": 0.08, "max": 0.15},
        "horizons_sec": list(HORIZONS),
        "by_horizon": by_horizon,
        "chart_series": chart_series,
        "multihorizon_open": open_n,
        "multihorizon_skipped": skipped_n,
        "analytics_db_path": ANALYTICS_DB_PATH,
        "multihorizon_db_path": DB_PATH,
        "shadow_horizons_only": True,
        "live_execution": False,
    }


def status() -> dict:
    """Lightweight health/status path; never calls full report()."""
    try:
        init()
        with _LOCK, _conn() as con:
            rows = con.execute(
                "SELECT status,COUNT(*) n FROM mh_outcomes GROUP BY status"
            ).fetchall()
            counts = {str(r["status"]): int(r["n"]) for r in rows}
            meta = con.execute(
                "SELECT value FROM mh_meta WHERE key='post_calibration_v2_started_at'"
            ).fetchone()
        started = None
        if meta:
            try:
                started = float(meta["value"])
            except Exception:
                started = None
        return {
            "enabled":True,
            "mode":"SHADOW",
            "db_path":DB_PATH,
            "horizons_sec":list(HORIZONS),
            "open":counts.get("OPEN",0),
            "closed":counts.get("CLOSED",0),
            "skipped":counts.get("SKIPPED",0),
            "extra_market_api_calls":False,
            "post_calibration_v2_started_at": started,
            "status_source":"lightweight_counts",
        }
    except Exception as exc:
        return {"enabled":True,"mode":"SHADOW","db_path":DB_PATH,"error":f"{type(exc).__name__}: {exc}"}

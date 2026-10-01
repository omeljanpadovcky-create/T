"""MYSHKA / ASTRA — Forward Experiment Lab V1 (SHADOW only).

Forward-only A/B evidence collection. This module never changes ENTER/DROP,
PAPER positions, sizing, JEV, Guard, Evidence Gate, ML, or order routing.

Experiments:
- Binance X-Check AGREE / CONFLICT / NEUTRAL (forward only)
- NEUTRAL exclusion diagnostics
- TECH 3/4 relaxed vs STRICT 4/4
- EDGE bands
- modeled-cost sensitivity
- 5m / 10m / 15m outcomes
- raw sample count + 5-minute pair/side cluster-adjusted sample count

No extra market API calls are made. Settlement uses ordinary ASTRA scan prices.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
from typing import Any, Optional

DB_PATH = os.getenv("FORWARD_EXPERIMENT_DB_PATH", "/data/myshka_forward_experiments.sqlite3")
HORIZONS = tuple(sorted({int(x) for x in os.getenv("FORWARD_EXPERIMENT_HORIZONS_SEC", "300,600,900").split(",") if x.strip()}))
MAX_SETTLE_DELAY_SEC = max(30, int(os.getenv("FORWARD_EXPERIMENT_MAX_SETTLE_DELAY_SEC", "120")))
CLUSTER_SEC = max(60, int(os.getenv("FORWARD_EXPERIMENT_CLUSTER_SEC", "300")))
_LOCK = threading.RLock()
_SEEN_MINUTE: Optional[int] = None
_SEEN_RECORD_KEYS: set[tuple[str, str, int]] = set()


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


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
            CREATE TABLE IF NOT EXISTS experiment_meta(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS forward_outcomes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                side TEXT NOT NULL,
                source_minute INTEGER NOT NULL,
                cluster_bucket INTEGER NOT NULL,
                cluster_key TEXT NOT NULL,
                opened_at REAL NOT NULL,
                target_at REAL NOT NULL,
                horizon_sec INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                entry_price REAL NOT NULL,
                exit_price REAL,
                action TEXT,
                reason TEXT,
                tech_score INTEGER NOT NULL,
                tech_source TEXT,
                edge_pct REAL,
                total_cost_pct REAL,
                edge_basis TEXT,
                xcheck_state TEXT,
                xcheck_score REAL,
                rsi REAL,
                volume_ratio REAL,
                atr_pct REAL,
                structure TEXT,
                momentum_5m_pct REAL,
                momentum_15m_pct REAL,
                oi_change_15m_pct REAL,
                funding_rate REAL,
                long_short_ratio REAL,
                hour_utc INTEGER,
                settled_at REAL,
                settle_delay_sec REAL,
                gross_pct REAL,
                net_pct REAL,
                direction_hit INTEGER,
                UNIQUE(pair,side,source_minute,horizon_sec,tech_score)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_fwd_status_target ON forward_outcomes(status,target_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_fwd_horizon_status ON forward_outcomes(horizon_sec,status)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_fwd_xcheck ON forward_outcomes(xcheck_state,horizon_sec,status)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_fwd_cluster ON forward_outcomes(cluster_key,horizon_sec,status)")
        row = con.execute("SELECT value FROM experiment_meta WHERE key='forward_started_at'").fetchone()
        if not row:
            con.execute(
                "INSERT INTO experiment_meta(key,value) VALUES('forward_started_at',?)",
                (str(time.time()),),
            )
    return status()


def _started_at() -> float:
    with _LOCK, _conn() as con:
        row = con.execute("SELECT value FROM experiment_meta WHERE key='forward_started_at'").fetchone()
        if row:
            try:
                return float(row["value"])
            except Exception:
                pass
        now = time.time()
        con.execute("INSERT OR REPLACE INTO experiment_meta(key,value) VALUES('forward_started_at',?)", (str(now),))
        return now


def _market_price(r: dict) -> Optional[float]:
    m = r.get("market") or {}
    for key in ("last_price", "last", "price", "close"):
        x = _num(m.get(key))
        if x is not None and x > 0:
            return x
    candles = m.get("candles") or r.get("candles") or []
    if candles:
        c = candles[-1]
        x = _num(c.get("close") if isinstance(c, dict) else getattr(c, "close", None))
        if x is not None and x > 0:
            return x
    return None


def _tech_candidate(sig: dict) -> tuple[str, int, str]:
    """Return side/score without changing the production TECH decision.

    This intentionally scores LONG and SHORT independently so a production WAIT
    that satisfies 3/4 conditions can still be observed by the SHADOW lab.
    """
    fast = _num(sig.get("ema_fast"))
    slow = _num(sig.get("ema_slow"))
    rsi = _num(sig.get("rsi"))
    vol = _num(sig.get("volume_ratio"))
    structure = str(sig.get("structure") or "RANGE").upper()
    if None in (fast, slow, rsi, vol):
        return "WAIT", 0, "insufficient_fields"

    long_checks = [fast > slow, structure == "UP", 52 <= rsi <= 72, vol >= 0.60]
    short_checks = [fast < slow, structure == "DOWN", 28 <= rsi <= 48, vol >= 0.60]
    ls, ss = sum(bool(x) for x in long_checks), sum(bool(x) for x in short_checks)

    production = str(sig.get("direction") or "WAIT").upper()
    if production in {"LONG", "SHORT"}:
        score = ls if production == "LONG" else ss
        return production, score, "production_signal"

    best = max(ls, ss)
    if best < 3 or ls == ss:
        return "WAIT", best, "shadow_relaxed"
    return ("LONG" if ls > ss else "SHORT"), best, "shadow_relaxed"


def _context_value(ctx: dict, *keys: str) -> Optional[float]:
    for k in keys:
        x = _num(ctx.get(k))
        if x is not None:
            return x
    return None


def _record(r: dict, now: float) -> int:
    sig = r.get("signal") or {}
    side, score, tech_source = _tech_candidate(sig)
    if side not in {"LONG", "SHORT"} or score < 3:
        return 0

    pair = str(r.get("pair") or "")
    entry = _market_price(r)
    if not pair or entry is None:
        return 0

    edge = r.get("edge") or {}
    ctx = r.get("context") or {}
    bx = r.get("binance_crosscheck") or {}
    state = str(bx.get("state") or "NO_DATA").upper()
    if state == "NOT_APPLICABLE" and tech_source == "shadow_relaxed":
        state = "NO_DATA"

    source_minute = int(now // 60) * 60

    # The DB UNIQUE key already keeps only the first observation per minute.
    # Avoid repeating the same INSERT OR IGNORE transaction every 15s scan.
    global _SEEN_MINUTE
    key = (pair, side, int(score))
    with _LOCK:
        if _SEEN_MINUTE != source_minute:
            _SEEN_MINUTE = source_minute
            _SEEN_RECORD_KEYS.clear()
        if key in _SEEN_RECORD_KEYS:
            return 0

    cluster_bucket = int(now // CLUSTER_SEC) * CLUSTER_SEC
    cluster_key = f"{pair}|{side}|{cluster_bucket}"
    m = r.get("market") or {}
    hour_utc = int(time.gmtime(now).tm_hour)

    common = {
        "action": str(r.get("action") or ""),
        "reason": str(r.get("reason") or ""),
        "tech_score": int(score),
        "tech_source": tech_source,
        "edge_pct": _num(edge.get("net_edge_pct")),
        "total_cost_pct": _num(edge.get("total_cost_pct")),
        "edge_basis": str(edge.get("basis") or ""),
        "xcheck_state": state,
        "xcheck_score": _num(bx.get("score")),
        "rsi": _num(sig.get("rsi")),
        "volume_ratio": _num(sig.get("volume_ratio")),
        "atr_pct": _num(m.get("atr_pct")),
        "structure": str(sig.get("structure") or ""),
        "momentum_5m_pct": _context_value(ctx, "price_change_5m_pct", "momentum_5m_pct"),
        "momentum_15m_pct": _context_value(ctx, "price_change_15m_pct", "momentum_15m_pct"),
        "oi_change_15m_pct": _context_value(ctx, "oi_change_15m_pct", "open_interest_change_15m_pct"),
        "funding_rate": _context_value(ctx, "funding_rate", "funding"),
        "long_short_ratio": _context_value(ctx, "long_short_ratio", "ls_ratio"),
        "hour_utc": hour_utc,
    }

    made = 0
    with _LOCK, _conn() as con:
        for h in HORIZONS:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO forward_outcomes(
                    pair,side,source_minute,cluster_bucket,cluster_key,opened_at,target_at,horizon_sec,status,
                    entry_price,action,reason,tech_score,tech_source,edge_pct,total_cost_pct,edge_basis,
                    xcheck_state,xcheck_score,rsi,volume_ratio,atr_pct,structure,momentum_5m_pct,
                    momentum_15m_pct,oi_change_15m_pct,funding_rate,long_short_ratio,hour_utc
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pair, side, source_minute, cluster_bucket, cluster_key, now, now + int(h), int(h), "OPEN",
                    entry, common["action"], common["reason"], common["tech_score"], common["tech_source"],
                    common["edge_pct"], common["total_cost_pct"], common["edge_basis"],
                    common["xcheck_state"], common["xcheck_score"], common["rsi"], common["volume_ratio"],
                    common["atr_pct"], common["structure"], common["momentum_5m_pct"], common["momentum_15m_pct"],
                    common["oi_change_15m_pct"], common["funding_rate"], common["long_short_ratio"], common["hour_utc"],
                ),
            )
            made += int(bool(cur.rowcount))
    with _LOCK:
        _SEEN_RECORD_KEYS.add(key)
    return made


def _settle(results: list[dict], now: float) -> dict:
    by_pair = {str(r.get("pair") or ""): r for r in (results or []) if r.get("pair")}
    closed = skipped = 0
    with _LOCK, _conn() as con:
        rows = con.execute(
            "SELECT * FROM forward_outcomes WHERE status='OPEN' AND target_at<=? ORDER BY target_at",
            (now,),
        ).fetchall()
        for row in rows:
            delay = max(0.0, now - float(row["target_at"]))
            if delay > MAX_SETTLE_DELAY_SEC:
                con.execute(
                    "UPDATE forward_outcomes SET status='SKIPPED',settled_at=?,settle_delay_sec=? WHERE id=?",
                    (now, delay, int(row["id"])),
                )
                skipped += 1
                continue
            r = by_pair.get(str(row["pair"]))
            if not r:
                continue
            exit_price = _market_price(r)
            if exit_price is None:
                continue
            entry = float(row["entry_price"])
            raw = (exit_price / entry - 1.0) * 100.0
            gross = raw if str(row["side"]) == "LONG" else -raw
            cost = float(row["total_cost_pct"] or 0.0)
            net = gross - cost
            con.execute(
                """
                UPDATE forward_outcomes
                SET status='CLOSED',exit_price=?,settled_at=?,settle_delay_sec=?,
                    gross_pct=?,net_pct=?,direction_hit=?
                WHERE id=? AND status='OPEN'
                """,
                (exit_price, now, delay, gross, net, 1 if gross > 0 else 0, int(row["id"])),
            )
            closed += 1
    return {"closed": closed, "skipped": skipped}


def observe_results(results: list[dict], now: Optional[float] = None) -> dict:
    """Observe normal scan results. Never mutates trade decisions."""
    try:
        init()
        ts = float(now if now is not None else time.time())
        settled = _settle(results or [], ts)
        created = sum(_record(r, ts) for r in (results or []))
        return {"status": "ok", "created": created, **settled}
    except Exception as exc:
        return {
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "created": 0,
            "closed": 0,
            "skipped": 0,
        }


def _pf(vals: list[float]) -> float:
    pos = sum(x for x in vals if x > 0)
    neg = abs(sum(x for x in vals if x <= 0))
    return pos / neg if neg > 1e-12 else (999.0 if pos > 0 else 0.0)


def _metric_core(rows: list[dict], net_override=None) -> dict:
    vals = []
    for r in rows:
        if net_override is None:
            x = _num(r.get("net_pct"))
        else:
            x = net_override(r)
        if x is not None:
            vals.append(float(x))
    n = len(vals)
    wins = sum(1 for x in vals if x > 0)
    return {
        "n": n,
        "win_rate_pct": wins / n * 100.0 if n else 0.0,
        "avg_net_pct": sum(vals) / n if n else 0.0,
        "total_net_pct": sum(vals),
        "profit_factor": _pf(vals),
    }


def _cluster_rows(rows: list[dict]) -> list[dict]:
    """Use the first closed observation in each pair+side+5m cluster."""
    seen = set()
    out = []
    for r in sorted(rows, key=lambda x: (float(x.get("opened_at") or 0), int(x.get("id") or 0))):
        key = str(r.get("cluster_key") or "")
        if not key:
            key = f"{r.get('pair')}|{r.get('side')}|{int(float(r.get('opened_at') or 0)//CLUSTER_SEC)*CLUSTER_SEC}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _metrics(rows: list[dict], net_override=None) -> dict:
    raw = _metric_core(rows, net_override=net_override)
    clustered = _metric_core(_cluster_rows(rows), net_override=net_override)
    return {
        **raw,
        "cluster_n": clustered["n"],
        "cluster_win_rate_pct": clustered["win_rate_pct"],
        "cluster_avg_net_pct": clustered["avg_net_pct"],
        "cluster_profit_factor": clustered["profit_factor"],
    }


def _edge_band(v: Any) -> str:
    x = _num(v)
    if x is None:
        return "NO_EDGE"
    if x < 0.05:
        return "<0.05"
    if x < 0.10:
        return "0.05-0.10"
    if x < 0.20:
        return "0.10-0.20"
    if x < 0.35:
        return "0.20-0.35"
    return ">=0.35"


def _sample_state(cluster_n: int) -> str:
    if cluster_n < 30:
        return "COLD"
    if cluster_n < 50:
        return "WARMING"
    if cluster_n < 150:
        return "MONITOR"
    if cluster_n < 300:
        return "CANDIDATE"
    return "MATURE"


def _horizon_report(rows: list[dict]) -> dict:
    allm = _metrics(rows)

    by_xcheck = {}
    for state in ("AGREE", "CONFLICT", "NEUTRAL", "NO_DATA"):
        by_xcheck[state] = _metrics([r for r in rows if str(r.get("xcheck_state") or "NO_DATA") == state])

    neutral_off = [r for r in rows if str(r.get("xcheck_state") or "NO_DATA") != "NEUTRAL"]
    directional_only = [r for r in rows if str(r.get("xcheck_state") or "") in {"AGREE", "CONFLICT"}]

    by_tech = {
        "TECH_3_OF_4": _metrics([r for r in rows if int(r.get("tech_score") or 0) == 3]),
        "TECH_4_OF_4": _metrics([r for r in rows if int(r.get("tech_score") or 0) == 4]),
    }

    by_edge = {}
    for label in ("<0.05", "0.05-0.10", "0.10-0.20", "0.20-0.35", ">=0.35", "NO_EDGE"):
        by_edge[label] = _metrics([r for r in rows if _edge_band(r.get("edge_pct")) == label])

    cost_sensitivity = {}
    for factor in (0.75, 1.00, 1.25):
        label = f"x{factor:.2f}"
        cost_sensitivity[label] = _metrics(
            rows,
            net_override=lambda r, f=factor: (
                None if _num(r.get("gross_pct")) is None
                else float(r.get("gross_pct") or 0.0) - float(r.get("total_cost_pct") or 0.0) * f
            ),
        )

    return {
        "all": allm,
        "sample_state": _sample_state(int(allm.get("cluster_n") or 0)),
        "by_xcheck": by_xcheck,
        "neutral_exclusion": {
            "NEUTRAL_OFF": _metrics(neutral_off),
            "DIRECTIONAL_ONLY": _metrics(directional_only),
            "NEUTRAL_EXCLUDED": by_xcheck["NEUTRAL"],
        },
        "by_tech": by_tech,
        "by_edge_band": by_edge,
        "cost_sensitivity": cost_sensitivity,
    }


def report() -> dict:
    init()
    started = _started_at()
    with _LOCK, _conn() as con:
        rows = [
            dict(r) for r in con.execute(
                "SELECT * FROM forward_outcomes WHERE status='CLOSED' AND opened_at>=? ORDER BY opened_at,id",
                (started,),
            ).fetchall()
        ]
        counts = {
            str(r["status"]): int(r["n"]) for r in con.execute(
                "SELECT status,COUNT(*) n FROM forward_outcomes WHERE opened_at>=? GROUP BY status",
                (started,),
            ).fetchall()
        }

    by_horizon = {}
    for h in HORIZONS:
        part = [r for r in rows if int(r.get("horizon_sec") or 0) == int(h)]
        by_horizon[str(h)] = _horizon_report(part)

    return {
        "status": "ok",
        "mode": "FORWARD_SHADOW_ONLY",
        "forward_started_at": started,
        "horizons_sec": list(HORIZONS),
        "cluster_sec": CLUSTER_SEC,
        "open": counts.get("OPEN", 0),
        "closed": counts.get("CLOSED", 0),
        "skipped": counts.get("SKIPPED", 0),
        "by_horizon": by_horizon,
        "xcheck_definition": {
            "audit": "DIRECTION_LOGIC_VERIFIED",
            "agree": "Binance crowd direction equals MYSHKA side",
            "conflict": "Binance crowd direction is opposite MYSHKA side",
            "neutral": "absolute averaged long-minus-short share is inside configured neutral band",
            "note": "Forward outcomes are required before treating CONFLICT as a contrarian edge.",
        },
        "experiments": [
            "NEUTRAL_OFF",
            "AGREE_vs_CONFLICT_forward",
            "TECH_3_OF_4_vs_4_OF_4",
            "EDGE_BANDS",
            "COST_SENSITIVITY",
        ],
        "extra_market_api_calls": False,
        "changes_paper_execution": False,
        "changes_trading_decisions": False,
        "live_execution": False,
    }


def recent(limit: int = 100) -> dict:
    init()
    lim = max(1, min(500, int(limit)))
    with _LOCK, _conn() as con:
        rows = [
            dict(r) for r in con.execute(
                "SELECT * FROM forward_outcomes ORDER BY id DESC LIMIT ?",
                (lim,),
            ).fetchall()
        ]
    return {"status": "ok", "items": rows}


def status() -> dict:
    try:
        started = _started_at() if os.path.exists(DB_PATH) else time.time()
        if not os.path.exists(DB_PATH):
            with _LOCK, _conn() as con:
                con.execute("CREATE TABLE IF NOT EXISTS experiment_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                con.execute("INSERT OR IGNORE INTO experiment_meta(key,value) VALUES('forward_started_at',?)", (str(started),))
        return {
            "enabled": True,
            "mode": "FORWARD_SHADOW_ONLY",
            "db_path": DB_PATH,
            "forward_started_at": started,
            "horizons_sec": list(HORIZONS),
            "cluster_sec": CLUSTER_SEC,
            "extra_market_api_calls": False,
            "changes_paper_execution": False,
            "changes_trading_decisions": False,
            "live_execution": False,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "mode": "FORWARD_SHADOW_ONLY",
            "db_path": DB_PATH,
            "error": f"{type(exc).__name__}: {exc}",
        }

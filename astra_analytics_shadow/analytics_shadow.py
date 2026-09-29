"""Persistent SHADOW analytics for MYSHKA / ASTRA.

This module observes paper entries and outcomes. It does not create, approve,
veto, resize, or otherwise change trades. Its job is to connect the entry-time
TECH/EDGE/context features with the eventual paper result so the system can
measure which conditions actually correlate with better or worse outcomes.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
import json
import math
import os
import sqlite3
import threading
import time
from typing import Any, Optional

DB_PATH = os.getenv("ANALYTICS_DB_PATH", "/data/myshka_analytics.sqlite3")
TZ_OFFSET_HOURS = float(os.getenv("ANALYTICS_TZ_OFFSET_HOURS", "3"))
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
            CREATE TABLE IF NOT EXISTS analytics_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                side TEXT NOT NULL,
                regime TEXT,
                mode TEXT NOT NULL,
                tech_score INTEGER NOT NULL,
                opened_at REAL NOT NULL,
                closed_at REAL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                entry_price REAL,
                expected_edge_pct REAL,
                total_cost_pct REAL,
                rsi REAL,
                volume_ratio REAL,
                context_samples INTEGER,
                context_age_sec REAL,
                price_5m_pct REAL,
                price_15m_pct REAL,
                price_30m_pct REAL,
                oi_5m_pct REAL,
                oi_15m_pct REAL,
                oi_30m_pct REAL,
                funding_rate_pct REAL,
                long_short_ratio REAL,
                btc_5m_pct REAL,
                btc_15m_pct REAL,
                btc_30m_pct REAL,
                external_event_count INTEGER,
                gross_pct REAL,
                net_pct REAL,
                direction_hit INTEGER,
                close_note TEXT,
                raw_entry_json TEXT
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_analytics_status_mode ON analytics_trades(status, mode)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_analytics_pair_opened ON analytics_trades(pair, opened_at)")
    return status()


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _strict_tech_score(sig: dict) -> int:
    direction = str(sig.get("direction") or "WAIT").upper()
    fast = _num(sig.get("ema_fast"))
    slow = _num(sig.get("ema_slow"))
    structure = str(sig.get("structure") or "RANGE").upper()
    rsi = _num(sig.get("rsi"))
    volume = _num(sig.get("volume_ratio"))
    if direction not in {"LONG", "SHORT"} or fast is None or slow is None or rsi is None or volume is None:
        return 0
    if direction == "LONG":
        checks = [fast > slow, structure == "UP", 52.0 <= rsi <= 72.0, volume >= 0.60]
    else:
        checks = [fast < slow, structure == "DOWN", 28.0 <= rsi <= 48.0, volume >= 0.60]
    return sum(bool(x) for x in checks)


def _mode(result: dict, score: int) -> str:
    if score == 4:
        return "STRICT"
    training = result.get("training") or {}
    if bool(training.get("active")) or score == 3:
        return "TRAIN"
    return "OTHER"


def record_entry(position: dict, result: dict) -> Optional[int]:
    """Persist entry-time features and return an analytics row id.

    Failure is intentionally non-fatal: analytics must never block a trade.
    """
    try:
        init()
        sig = result.get("signal") or {}
        edge = result.get("edge") or {}
        ctx = result.get("context") or {}
        score = _strict_tech_score(sig)
        mode = _mode(result, score)
        values = (
            str(position.get("pair") or result.get("pair") or ""),
            str(position.get("side") or result.get("direction") or sig.get("direction") or ""),
            str(position.get("regime") or sig.get("structure") or "RANGE"),
            mode,
            int(score),
            float(position.get("opened_at") or time.time()),
            _num(position.get("entry")),
            _num(edge.get("net_edge_pct")),
            _num(edge.get("total_cost_pct")),
            _num(sig.get("rsi")),
            _num(sig.get("volume_ratio")),
            int(ctx.get("samples") or 0),
            _num(ctx.get("age_sec")),
            _num(ctx.get("price_change_5m_pct")),
            _num(ctx.get("price_change_15m_pct")),
            _num(ctx.get("price_change_30m_pct")),
            _num(ctx.get("oi_change_5m_pct")),
            _num(ctx.get("oi_change_15m_pct")),
            _num(ctx.get("oi_change_30m_pct")),
            _num(ctx.get("funding_rate_pct")),
            _num(ctx.get("long_short_ratio")),
            _num(ctx.get("btc_price_change_5m_pct")),
            _num(ctx.get("btc_price_change_15m_pct")),
            _num(ctx.get("btc_price_change_30m_pct")),
            int(ctx.get("external_event_count") or 0),
            json.dumps({"position": position, "result": result}, ensure_ascii=False, separators=(",", ":")),
        )
        with _LOCK, _conn() as con:
            cur = con.execute(
                """
                INSERT INTO analytics_trades(
                    pair,side,regime,mode,tech_score,opened_at,entry_price,
                    expected_edge_pct,total_cost_pct,rsi,volume_ratio,
                    context_samples,context_age_sec,price_5m_pct,price_15m_pct,price_30m_pct,
                    oi_5m_pct,oi_15m_pct,oi_30m_pct,funding_rate_pct,long_short_ratio,
                    btc_5m_pct,btc_15m_pct,btc_30m_pct,external_event_count,raw_entry_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                values,
            )
            return int(cur.lastrowid)
    except Exception:
        return None


def record_close(*, analytics_id: Optional[int], gross_pct: float, net_pct: float,
                 direction_hit: bool, closed_at: Optional[float] = None) -> None:
    if not analytics_id:
        return
    try:
        with _LOCK, _conn() as con:
            con.execute(
                """
                UPDATE analytics_trades
                SET status='CLOSED', closed_at=?, gross_pct=?, net_pct=?, direction_hit=?, close_note=NULL
                WHERE id=? AND status='OPEN'
                """,
                (float(closed_at or time.time()), float(gross_pct), float(net_pct), 1 if direction_hit else 0, int(analytics_id)),
            )
    except Exception:
        pass


def record_skip(*, analytics_id: Optional[int], note: str, closed_at: Optional[float] = None) -> None:
    if not analytics_id:
        return
    try:
        with _LOCK, _conn() as con:
            con.execute(
                "UPDATE analytics_trades SET status='SKIPPED', closed_at=?, close_note=? WHERE id=? AND status='OPEN'",
                (float(closed_at or time.time()), str(note)[:500], int(analytics_id)),
            )
    except Exception:
        pass


def status() -> dict:
    init_needed = not os.path.exists(DB_PATH)
    if init_needed:
        try:
            init()
        except Exception as exc:
            return {"enabled": True, "mode": "SHADOW", "db_path": DB_PATH, "error": f"{type(exc).__name__}: {exc}"}
    try:
        with _LOCK, _conn() as con:
            rows = con.execute("SELECT status,mode,COUNT(*) AS n FROM analytics_trades GROUP BY status,mode").fetchall()
        counts: dict[str, dict[str, int]] = defaultdict(dict)
        for r in rows:
            counts[str(r["status"])][str(r["mode"])] = int(r["n"])
        closed = sum(counts.get("CLOSED", {}).values())
        open_n = sum(counts.get("OPEN", {}).values())
        skipped = sum(counts.get("SKIPPED", {}).values())
        return {
            "enabled": True,
            "mode": "SHADOW",
            "db_path": DB_PATH,
            "closed": closed,
            "open": open_n,
            "skipped": skipped,
            "strict_closed": counts.get("CLOSED", {}).get("STRICT", 0),
            "train_closed": counts.get("CLOSED", {}).get("TRAIN", 0),
            "counts": dict(counts),
        }
    except Exception as exc:
        return {"enabled": True, "mode": "SHADOW", "db_path": DB_PATH, "error": f"{type(exc).__name__}: {exc}"}


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _median(vals: list[float]) -> float:
    if not vals:
        return 0.0
    x = sorted(vals)
    m = len(x) // 2
    return x[m] if len(x) % 2 else (x[m - 1] + x[m]) / 2.0


def _metrics(rows: list[dict]) -> dict:
    nets = [float(r["net_pct"]) for r in rows if r.get("net_pct") is not None]
    gross = [float(r["gross_pct"]) for r in rows if r.get("gross_pct") is not None]
    n = len(nets)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    hit_n = sum(1 for r in rows if int(r.get("direction_hit") or 0) == 1)
    pos_sum = sum(wins)
    neg_abs = abs(sum(losses))
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": (len(wins) / n * 100.0) if n else 0.0,
        "direction_hit_pct": (hit_n / n * 100.0) if n else 0.0,
        "avg_net_pct": _mean(nets),
        "median_net_pct": _median(nets),
        "total_net_pct": sum(nets),
        "avg_gross_pct": _mean(gross),
        "profit_factor": (pos_sum / neg_abs) if neg_abs > 1e-12 else (999.0 if pos_sum > 0 else 0.0),
    }


def _band_edge(r: dict) -> str:
    x = _num(r.get("expected_edge_pct"))
    if x is None:
        return "unknown"
    if x < 0.10:
        return "0.05–0.10%"
    if x < 0.20:
        return "0.10–0.20%"
    if x < 0.35:
        return "0.20–0.35%"
    return ">=0.35%"


def _band_volume(r: dict) -> str:
    x = _num(r.get("volume_ratio"))
    if x is None:
        return "unknown"
    if x < 0.8:
        return "<0.8x"
    if x < 1.2:
        return "0.8–1.2x"
    return ">=1.2x"


def _band_rsi(r: dict) -> str:
    x = _num(r.get("rsi"))
    if x is None:
        return "unknown"
    if x < 35:
        return "<35"
    if x < 45:
        return "35–45"
    if x < 55:
        return "45–55"
    if x < 65:
        return "55–65"
    return ">=65"


def _band_signed(x: Optional[float], threshold: float, unit: str = "%") -> str:
    if x is None:
        return "unknown"
    if x < -threshold:
        return f"<-{threshold:g}{unit}"
    if x > threshold:
        return f">+{threshold:g}{unit}"
    return f"-{threshold:g}…+{threshold:g}{unit}"


def _band_ls(r: dict) -> str:
    x = _num(r.get("long_short_ratio"))
    if x is None:
        return "unknown"
    if x < 0.8:
        return "<0.8"
    if x <= 1.2:
        return "0.8–1.2"
    return ">1.2"


def _alignment(r: dict, field: str) -> str:
    x = _num(r.get(field))
    if x is None:
        return "unknown"
    if abs(x) < 0.05:
        return "FLAT"
    side = str(r.get("side") or "").upper()
    with_trade = (side == "LONG" and x > 0) or (side == "SHORT" and x < 0)
    return "WITH TRADE" if with_trade else "AGAINST TRADE"


def _time_bucket(r: dict) -> str:
    try:
        dt = datetime.fromtimestamp(float(r.get("opened_at") or 0), tz=timezone.utc) + timedelta(hours=TZ_OFFSET_HOURS)
        h = dt.hour
        if h < 6:
            return "00–05"
        if h < 12:
            return "06–11"
        if h < 18:
            return "12–17"
        return "18–23"
    except Exception:
        return "unknown"


def _segments(rows: list[dict], fn) -> list[dict]:
    g: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        g[str(fn(r))].append(r)
    out = []
    for label, part in g.items():
        m = _metrics(part)
        out.append({"label": label, **m})
    out.sort(key=lambda x: (-int(x["n"]), str(x["label"])))
    return out


def _fetch_rows(mode: str) -> list[dict]:
    init()
    mode = str(mode or "STRICT").upper()
    with _LOCK, _conn() as con:
        if mode == "ALL":
            dbrows = con.execute("SELECT * FROM analytics_trades WHERE status='CLOSED' ORDER BY opened_at ASC").fetchall()
        else:
            dbrows = con.execute("SELECT * FROM analytics_trades WHERE status='CLOSED' AND mode=? ORDER BY opened_at ASC", (mode,)).fetchall()
    return [dict(r) for r in dbrows]


def report(mode: str = "STRICT", min_segment_n: int = 3) -> dict:
    rows = _fetch_rows(mode)
    min_n = max(1, min(50, int(min_segment_n)))
    dimensions = {
        "edge_band": _segments(rows, _band_edge),
        "side": _segments(rows, lambda r: str(r.get("side") or "unknown")),
        "pair": _segments(rows, lambda r: str(r.get("pair") or "unknown").replace("/USDT:USDT", "")),
        "volume": _segments(rows, _band_volume),
        "rsi": _segments(rows, _band_rsi),
        "oi15": _segments(rows, lambda r: _band_signed(_num(r.get("oi_15m_pct")), 1.0)),
        "funding": _segments(rows, lambda r: _band_signed(_num(r.get("funding_rate_pct")), 0.005)),
        "long_short": _segments(rows, _band_ls),
        "momentum15": _segments(rows, lambda r: _alignment(r, "price_15m_pct")),
        "btc_momentum15": _segments(rows, lambda r: _alignment(r, "btc_15m_pct")),
        "external_events": _segments(rows, lambda r: "1+ events" if int(r.get("external_event_count") or 0) > 0 else "0 events"),
        "time_local": _segments(rows, _time_bucket),
    }
    eligible = []
    for dim, segs in dimensions.items():
        for s in segs:
            if int(s.get("n") or 0) >= min_n and s.get("label") != "unknown":
                eligible.append({"dimension": dim, **s})
    positive = [x for x in eligible if float(x.get("avg_net_pct") or 0) > 0]
    negative = [x for x in eligible if float(x.get("avg_net_pct") or 0) < 0]
    best = sorted(positive, key=lambda x: (float(x.get("avg_net_pct") or 0), int(x.get("n") or 0)), reverse=True)[:5]
    worst = sorted(negative, key=lambda x: (float(x.get("avg_net_pct") or 0), -int(x.get("n") or 0)))[:5]
    context_n = sum(1 for r in rows if int(r.get("context_samples") or 0) > 0)
    overall = _metrics(rows)
    n = int(overall["n"])
    return {
        "status": "ok",
        "mode": str(mode or "STRICT").upper(),
        "shadow_only": True,
        "started_from_install": True,
        "min_segment_n": min_n,
        "overall": overall,
        "context_coverage_pct": (context_n / n * 100.0) if n else 0.0,
        "sample_state": "COLD" if n < 10 else "EARLY" if n < 30 else "USABLE" if n < 100 else "MATURE",
        "dimensions": dimensions,
        "observations": {"stronger_segments": best, "weaker_segments": worst},
        "note": "SHADOW analytics only. Segments describe historical paper samples and do not change entry rules.",
    }


def recent(limit: int = 50) -> list[dict]:
    init()
    n = max(1, min(500, int(limit)))
    with _LOCK, _conn() as con:
        rows = con.execute("SELECT * FROM analytics_trades ORDER BY opened_at DESC LIMIT ?", (n,)).fetchall()
    return [dict(r) for r in rows]

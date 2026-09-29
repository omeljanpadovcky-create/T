"""Counterfactual Analytics SHADOW for MYSHKA / ASTRA.

Observes rejected LONG/SHORT candidates (EDGE DROP, JEV REJECT, EVIDENCE GATE DROP and ADAPTIVE ML DROP) and checks
what would have happened after the normal 5 minute paper horizon. It never
creates, approves, vetoes, sizes, or routes an order.

Important:
- no extra Bybit calls: outcomes are settled from the normal ASTRA scan results;
- duplicate 15s scans are deduplicated to one candidate per pair/stage/minute;
- stale outcomes (> configured delay after horizon) are skipped, not scored.
"""
from __future__ import annotations

from collections import defaultdict
import json
import math
import os
import sqlite3
import threading
import time
from typing import Any, Optional

DB_PATH = os.getenv("COUNTERFACTUAL_DB_PATH", "/data/myshka_counterfactual.sqlite3")
HORIZON_SEC = max(60, int(os.getenv("COUNTERFACTUAL_HORIZON_SEC", "300")))
MAX_SETTLE_DELAY_SEC = max(30, int(os.getenv("COUNTERFACTUAL_MAX_SETTLE_DELAY_SEC", "90")))
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
            CREATE TABLE IF NOT EXISTS counterfactuals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                side TEXT NOT NULL,
                stage TEXT NOT NULL,
                source_minute INTEGER NOT NULL,
                opened_at REAL NOT NULL,
                target_at REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                entry_price REAL NOT NULL,
                exit_price REAL,
                regime TEXT,
                reason TEXT,
                expected_move_pct REAL,
                expected_edge_pct REAL,
                total_cost_pct REAL,
                rsi REAL,
                volume_ratio REAL,
                jev_confidence REAL,
                context_samples INTEGER,
                price_5m_pct REAL,
                price_15m_pct REAL,
                price_30m_pct REAL,
                oi_15m_pct REAL,
                funding_rate_pct REAL,
                long_short_ratio REAL,
                btc_15m_pct REAL,
                external_event_count INTEGER,
                settled_at REAL,
                settle_delay_sec REAL,
                gross_pct REAL,
                net_pct REAL,
                direction_hit INTEGER,
                raw_json TEXT,
                UNIQUE(pair, side, stage, source_minute)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_cf_status_target ON counterfactuals(status,target_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_cf_stage_status ON counterfactuals(stage,status)")
    return status()


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _candidate_stage(result: dict) -> Optional[str]:
    sig = result.get("signal") or {}
    direction = str(result.get("direction") or sig.get("direction") or "WAIT").upper()
    if direction not in {"LONG", "SHORT"}:
        return None

    action = str(result.get("action") or "").upper()
    if action != "DROP":
        return None

    jev = result.get("jev") or {}
    verdict = str(jev.get("verdict") or "").upper()
    reason = str(result.get("reason") or "").lower()
    edge = result.get("edge") or {}

    if "adaptive_learner" in reason:
        return "ADAPTIVE_ML_DROP"

    if "evidence_gate" in reason:
        return "EVIDENCE_GATE_DROP"

    if verdict == "REJECT" or reason == "jev" or "jev" in reason:
        return "JEV_REJECT"

    if edge:
        passed = bool(edge.get("passed"))
        if (not passed) or reason in {"edge", "strict_edge_buffer"} or "edge" in reason:
            return "EDGE_DROP"

    return None


def _market_price(result: dict) -> Optional[float]:
    m = result.get("market") or {}
    x = _num(m.get("last_price"))
    if x and x > 0:
        return x
    return None


def _record_candidate(result: dict, now: float) -> bool:
    stage = _candidate_stage(result)
    if not stage:
        return False

    sig = result.get("signal") or {}
    side = str(result.get("direction") or sig.get("direction") or "").upper()
    pair = str(result.get("pair") or "")
    entry = _market_price(result)
    if not pair or side not in {"LONG", "SHORT"} or entry is None:
        return False

    edge = result.get("edge") or {}
    jev = result.get("jev") or {}
    ctx = result.get("context") or {}
    source_minute = int(now // 60) * 60
    target_at = now + HORIZON_SEC

    values = (
        pair, side, stage, source_minute, now, target_at, entry,
        str(sig.get("structure") or "RANGE"),
        str(result.get("reason") or jev.get("reason") or sig.get("reason") or "")[:1000],
        _num(edge.get("expected_move_pct")),
        _num(edge.get("net_edge_pct")),
        _num(edge.get("total_cost_pct")),
        _num(sig.get("rsi")),
        _num(sig.get("volume_ratio")),
        _num(jev.get("confidence")),
        int(ctx.get("samples") or 0),
        _num(ctx.get("price_change_5m_pct")),
        _num(ctx.get("price_change_15m_pct")),
        _num(ctx.get("price_change_30m_pct")),
        _num(ctx.get("oi_change_15m_pct")),
        _num(ctx.get("funding_rate_pct")),
        _num(ctx.get("long_short_ratio")),
        _num(ctx.get("btc_price_change_15m_pct")),
        int(ctx.get("external_event_count") or 0),
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
    )

    with _LOCK, _conn() as con:
        cur = con.execute(
            """
            INSERT OR IGNORE INTO counterfactuals(
                pair,side,stage,source_minute,opened_at,target_at,entry_price,
                regime,reason,expected_move_pct,expected_edge_pct,total_cost_pct,
                rsi,volume_ratio,jev_confidence,context_samples,
                price_5m_pct,price_15m_pct,price_30m_pct,oi_15m_pct,
                funding_rate_pct,long_short_ratio,btc_15m_pct,external_event_count,raw_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            values,
        )
        return bool(cur.rowcount)


def _settle_pending(results: list[dict], now: float) -> dict:
    by_pair = {str(r.get("pair") or ""): r for r in results if r.get("pair")}
    settled = 0
    skipped = 0

    with _LOCK, _conn() as con:
        pending = con.execute(
            "SELECT * FROM counterfactuals WHERE status='OPEN' AND target_at<=? ORDER BY target_at ASC",
            (now,),
        ).fetchall()

        for row in pending:
            delay = max(0.0, now - float(row["target_at"]))
            if delay > MAX_SETTLE_DELAY_SEC:
                con.execute(
                    "UPDATE counterfactuals SET status='SKIPPED', settled_at=?, settle_delay_sec=? WHERE id=? AND status='OPEN'",
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
            raw = (exit_price - entry) / entry * 100.0
            gross = raw if str(row["side"]) == "LONG" else -raw
            costs = float(row["total_cost_pct"] or 0.0)
            net = gross - costs
            hit = gross > 0.0

            con.execute(
                """
                UPDATE counterfactuals
                SET status='CLOSED', exit_price=?, settled_at=?, settle_delay_sec=?,
                    gross_pct=?, net_pct=?, direction_hit=?
                WHERE id=? AND status='OPEN'
                """,
                (exit_price, now, delay, gross, net, 1 if hit else 0, int(row["id"])),
            )
            settled += 1

    return {"settled": settled, "skipped": skipped}


def observe_results(results: list[dict], now: Optional[float] = None) -> dict:
    """Observe one normal ASTRA scan. Never raises into the trading engine."""
    try:
        init()
        ts = float(now or time.time())
        settle = _settle_pending(results or [], ts)
        created = 0
        for r in results or []:
            if _record_candidate(r, ts):
                created += 1
        return {"status": "ok", "created": created, **settle}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}", "created": 0, "settled": 0, "skipped": 0}


def status() -> dict:
    try:
        if not os.path.exists(DB_PATH):
            init()
        with _LOCK, _conn() as con:
            rows = con.execute("SELECT status,stage,COUNT(*) AS n FROM counterfactuals GROUP BY status,stage").fetchall()
        counts: dict[str, dict[str, int]] = defaultdict(dict)
        for r in rows:
            counts[str(r["status"])][str(r["stage"])] = int(r["n"])
        return {
            "enabled": True,
            "mode": "SHADOW",
            "db_path": DB_PATH,
            "horizon_sec": HORIZON_SEC,
            "max_settle_delay_sec": MAX_SETTLE_DELAY_SEC,
            "open": sum(counts.get("OPEN", {}).values()),
            "closed": sum(counts.get("CLOSED", {}).values()),
            "skipped": sum(counts.get("SKIPPED", {}).values()),
            "counts": dict(counts),
        }
    except Exception as exc:
        return {"enabled": True, "mode": "SHADOW", "db_path": DB_PATH, "error": f"{type(exc).__name__}: {exc}"}


def _metrics(rows: list[dict]) -> dict:
    nets = [float(r["net_pct"]) for r in rows if r.get("net_pct") is not None]
    n = len(nets)
    winners = [x for x in nets if x > 0]
    losers = [x for x in nets if x <= 0]
    pos_sum = sum(winners)
    neg_abs = abs(sum(losers))
    return {
        "n": n,
        "would_win": len(winners),
        "would_lose": len(losers),
        "false_reject_rate_pct": (len(winners) / n * 100.0) if n else 0.0,
        "correct_reject_rate_pct": (len(losers) / n * 100.0) if n else 0.0,
        "avg_net_pct": (sum(nets) / n) if n else 0.0,
        "total_hypothetical_net_pct": sum(nets),
        "profit_factor": (pos_sum / neg_abs) if neg_abs > 1e-12 else (999.0 if pos_sum > 0 else 0.0),
    }


def _fetch_closed() -> list[dict]:
    init()
    with _LOCK, _conn() as con:
        rows = con.execute("SELECT * FROM counterfactuals WHERE status='CLOSED' ORDER BY opened_at ASC").fetchall()
    return [dict(r) for r in rows]


def report(min_stage_n: int = 3) -> dict:
    rows = _fetch_closed()
    stages = {}
    by_stage: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_stage[str(r.get("stage") or "UNKNOWN")].append(r)
    for stage, part in by_stage.items():
        stages[stage] = _metrics(part)

    overall = _metrics(rows)
    min_n = max(1, int(min_stage_n))
    verdicts = []
    for stage, m in stages.items():
        if int(m.get("n") or 0) < min_n:
            continue
        avg = float(m.get("avg_net_pct") or 0.0)
        if avg > 0:
            conclusion = "FILTER MAY BE TOO STRICT"
        elif avg < 0:
            conclusion = "FILTER IS SAVING LOSSES"
        else:
            conclusion = "NEUTRAL"
        verdicts.append({"stage": stage, "conclusion": conclusion, **m})

    return {
        "status": "ok",
        "mode": "SHADOW",
        "shadow_only": True,
        "overall": overall,
        "stages": stages,
        "verdicts": verdicts,
        "open": status().get("open", 0),
        "skipped": status().get("skipped", 0),
        "sample_state": "COLD" if overall["n"] < 10 else "EARLY" if overall["n"] < 30 else "USABLE" if overall["n"] < 100 else "MATURE",
        "note": "Hypothetical 5m outcomes of rejected candidates. No trading rule is changed.",
    }


def recent(limit: int = 50) -> list[dict]:
    init()
    n = max(1, min(500, int(limit)))
    with _LOCK, _conn() as con:
        rows = con.execute("SELECT * FROM counterfactuals ORDER BY opened_at DESC LIMIT ?", (n,)).fetchall()
    return [dict(r) for r in rows]

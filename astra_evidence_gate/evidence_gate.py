"""MYSHKA / ASTRA Validation Evidence Gate V1.

Active only on PAPER ENTER candidates. It does not create signals and it does
not route live orders. The gate asks a simple question before a STRICT PAPER
entry is opened:

"Do already-settled, comparable candidates show positive net expectancy after
modeled costs?"

Evidence comes from the existing Risk Intelligence 5m outcomes, so blocked
candidates can continue to teach the system without becoming PAPER positions.
"""
from __future__ import annotations

import math
import os
import sqlite3
import threading
import time
from typing import Any, Optional

RISK_DB_PATH = os.getenv("RISK_INTELLIGENCE_DB_PATH", "/data/myshka_risk_intelligence.sqlite3")
ANALYTICS_DB_PATH = os.getenv("ANALYTICS_DB_PATH", "/data/myshka_analytics.sqlite3")
ENABLED = os.getenv("EVIDENCE_GATE_ENABLED", "true").lower() in {"1","true","yes","on"}
MIN_N = max(10, int(os.getenv("EVIDENCE_GATE_MIN_N", "20")))
MIN_AVG_NET_PCT = float(os.getenv("EVIDENCE_GATE_MIN_AVG_NET_PCT", "0.03"))
MIN_PROFIT_FACTOR = float(os.getenv("EVIDENCE_GATE_MIN_PROFIT_FACTOR", "1.10"))
REQUIRE_RECENT_POSITIVE = os.getenv("EVIDENCE_GATE_REQUIRE_RECENT_POSITIVE", "true").lower() in {"1","true","yes","on"}
_THRESHOLDS_RAW = os.getenv("EVIDENCE_GATE_THRESHOLDS", "0.05,0.10,0.15,0.20,0.25,0.30")
THRESHOLDS = tuple(sorted({float(x.strip()) for x in _THRESHOLDS_RAW.split(",") if x.strip()}))
EXPLORATION_ENABLED = os.getenv("EVIDENCE_GATE_EXPLORATION_ENABLED", "true").lower() in {"1","true","yes","on"}
EXPLORATION_MIN_EDGE_PCT = float(os.getenv("EVIDENCE_GATE_EXPLORATION_MIN_EDGE_PCT", "0.10"))
EXPLORATION_COOLDOWN_SEC = max(60, int(os.getenv("EVIDENCE_GATE_EXPLORATION_COOLDOWN_SEC", "600")))
EXPLORATION_MAX_OPEN = max(1, int(os.getenv("EVIDENCE_GATE_EXPLORATION_MAX_OPEN", "1")))
_LOCK = threading.RLock()


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _strict_score(sig: dict) -> int:
    side = str(sig.get("direction") or "WAIT").upper()
    fast, slow = _num(sig.get("ema_fast")), _num(sig.get("ema_slow"))
    rsi, vol = _num(sig.get("rsi")), _num(sig.get("volume_ratio"))
    regime = str(sig.get("structure") or "RANGE").upper()
    if side not in {"LONG","SHORT"} or None in {fast,slow,rsi,vol}:
        return 0
    if side == "LONG":
        checks = [fast > slow, regime == "UP", 52 <= rsi <= 72, vol >= 0.60]
    else:
        checks = [fast < slow, regime == "DOWN", 28 <= rsi <= 48, vol >= 0.60]
    return sum(bool(x) for x in checks)


def _open_strict_positions() -> int:
    if not os.path.exists(ANALYTICS_DB_PATH):
        return 0
    try:
        con = sqlite3.connect(ANALYTICS_DB_PATH, timeout=5)
        try:
            row = con.execute(
                "SELECT COUNT(*) FROM analytics_trades WHERE status='OPEN' AND mode='STRICT'"
            ).fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            con.close()
    except Exception:
        return 0


def _last_exploration_at() -> Optional[float]:
    if not os.path.exists(RISK_DB_PATH):
        return None
    try:
        con = sqlite3.connect(RISK_DB_PATH, timeout=5)
        try:
            row = con.execute(
                """
                SELECT MAX(opened_at)
                FROM risk_candidates
                WHERE LOWER(COALESCE(reason,''))='evidence_gate_warming_exploration'
                """
            ).fetchone()
            return float(row[0]) if row and row[0] is not None else None
        finally:
            con.close()
    except Exception:
        return None


def _exploration_status(now: Optional[float] = None) -> dict:
    ts = float(now or time.time())
    last = _last_exploration_at()
    elapsed = (ts - last) if last is not None else None
    cooldown_left = max(0.0, EXPLORATION_COOLDOWN_SEC - elapsed) if elapsed is not None else 0.0
    open_n = _open_strict_positions()
    return {
        "enabled": EXPLORATION_ENABLED,
        "min_edge_pct": EXPLORATION_MIN_EDGE_PCT,
        "cooldown_sec": EXPLORATION_COOLDOWN_SEC,
        "cooldown_left_sec": round(cooldown_left, 1),
        "max_open": EXPLORATION_MAX_OPEN,
        "open_strict": open_n,
        "last_exploration_at": last,
        "available": bool(
            EXPLORATION_ENABLED
            and cooldown_left <= 0.0
            and open_n < EXPLORATION_MAX_OPEN
        ),
    }


def _rows() -> list[dict]:
    if not os.path.exists(RISK_DB_PATH):
        return []
    try:
        con = sqlite3.connect(RISK_DB_PATH, timeout=10)
        con.row_factory = sqlite3.Row
        try:
            dbrows = con.execute(
                """
                SELECT id,pair,side,opened_at,action,reason,tech_score,edge_pct,
                       jev_verdict,gross_pct,net_pct,total_cost_pct
                FROM risk_candidates
                WHERE status='CLOSED'
                  AND tech_score=4
                  AND UPPER(COALESCE(jev_verdict,''))='APPROVE'
                  AND (
                        UPPER(COALESCE(action,''))='ENTER'
                        OR LOWER(COALESCE(reason,'')) LIKE 'evidence_gate%'
                      )
                  AND edge_pct IS NOT NULL
                  AND net_pct IS NOT NULL
                ORDER BY opened_at ASC, id ASC
                """
            ).fetchall()
            return [dict(r) for r in dbrows]
        finally:
            con.close()
    except Exception:
        return []


def _metrics(rows: list[dict]) -> dict:
    nets = [float(r["net_pct"]) for r in rows if _num(r.get("net_pct")) is not None]
    n = len(nets)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    pos = sum(wins)
    neg = abs(sum(losses))
    pf = (pos / neg) if neg > 1e-12 else (999.0 if pos > 0 else 0.0)
    recent_n = min(n, max(10, n // 2)) if n else 0
    recent = nets[-recent_n:] if recent_n else []
    first = nets[: max(1, n // 2)] if n else []
    second = nets[max(1, n // 2):] if n > 1 else nets
    return {
        "n": n,
        "wins": len(wins),
        "win_rate_pct": (len(wins) / n * 100.0) if n else 0.0,
        "avg_net_pct": (sum(nets) / n) if n else 0.0,
        "total_net_pct": sum(nets),
        "profit_factor": pf,
        "recent_n": recent_n,
        "recent_avg_net_pct": (sum(recent) / len(recent)) if recent else 0.0,
        "first_half_avg_net_pct": (sum(first) / len(first)) if first else 0.0,
        "second_half_avg_net_pct": (sum(second) / len(second)) if second else 0.0,
    }


def _threshold_report(rows: list[dict]) -> list[dict]:
    out = []
    for t in THRESHOLDS:
        q = [r for r in rows if float(r.get("edge_pct") or 0.0) >= t]
        m = _metrics(q)
        stable = (not REQUIRE_RECENT_POSITIVE) or float(m["recent_avg_net_pct"]) > 0.0
        passed = (
            int(m["n"]) >= MIN_N
            and float(m["avg_net_pct"]) >= MIN_AVG_NET_PCT
            and float(m["profit_factor"]) >= MIN_PROFIT_FACTOR
            and stable
        )
        out.append({"threshold_pct": t, "passed": passed, **m})
    return out


def report() -> dict:
    rows = _rows()
    bands = _threshold_report(rows)
    qualified = next((x for x in bands if x["passed"]), None)
    overall = _metrics(rows)
    return {
        "status": "ok",
        "enabled": ENABLED,
        "mode": "PAPER_VALIDATION_GATE",
        "state": "PASS" if qualified else ("WARMING" if overall["n"] < MIN_N else "HOLD"),
        "qualified_threshold_pct": qualified["threshold_pct"] if qualified else None,
        "overall": overall,
        "thresholds": bands,
        "policy": {
            "min_n": MIN_N,
            "min_avg_net_pct": MIN_AVG_NET_PCT,
            "min_profit_factor": MIN_PROFIT_FACTOR,
            "require_recent_positive": REQUIRE_RECENT_POSITIVE,
        },
        "exploration": _exploration_status(),
        "note": "STRICT PAPER validation gate. During WARMING, controlled exploration may pass one high-edge candidate; HOLD remains a hard block.",
    }


def evaluate(result: dict) -> dict:
    if not ENABLED:
        return {"applies": False, "passed": True, "state": "DISABLED", "reason": "evidence_gate_disabled"}

    sig = result.get("signal") or {}
    edge = result.get("edge") or {}
    jev = result.get("jev") or {}
    action = str(result.get("action") or "").upper()

    if action != "ENTER":
        return {"applies": False, "passed": True, "state": "NOT_APPLICABLE", "reason": "not_enter"}
    if _strict_score(sig) != 4:
        return {"applies": False, "passed": True, "state": "NOT_APPLICABLE", "reason": "not_strict_4of4"}
    if not bool(edge.get("passed")):
        return {"applies": False, "passed": True, "state": "NOT_APPLICABLE", "reason": "edge_not_passed"}
    if str(jev.get("verdict") or "").upper() != "APPROVE":
        return {"applies": False, "passed": True, "state": "NOT_APPLICABLE", "reason": "jev_not_approve"}

    edge_pct = _num(edge.get("net_edge_pct"))
    rep = report()
    threshold = rep.get("qualified_threshold_pct")
    if threshold is None:
        overall = rep.get("overall") or {}
        state = str(rep.get("state") or "HOLD").upper()
        exploration = rep.get("exploration") or {}

        # WARMING is a data-collection phase, not a permanent trading freeze.
        # Allow only a high-edge STRICT candidate when the exploration slot is free.
        if state == "WARMING":
            exploration_ok = bool(
                exploration.get("available")
                and edge_pct is not None
                and edge_pct >= EXPLORATION_MIN_EDGE_PCT
            )
            return {
                "applies": True, "passed": exploration_ok,
                "state": "WARMING_EXPLORATION" if exploration_ok else "WARMING",
                "reason": "evidence_gate_warming_exploration" if exploration_ok else (
                    "evidence_gate_warming_edge_too_low"
                    if edge_pct is None or edge_pct < EXPLORATION_MIN_EDGE_PCT
                    else "evidence_gate_warming_exploration_unavailable"
                ),
                "candidate_edge_pct": edge_pct,
                "qualified_threshold_pct": None,
                "evidence_n": int(overall.get("n") or 0),
                "evidence_avg_net_pct": float(overall.get("avg_net_pct") or 0.0),
                "evidence_profit_factor": float(overall.get("profit_factor") or 0.0),
                "recent_avg_net_pct": float(overall.get("recent_avg_net_pct") or 0.0),
                "exploration": exploration,
            }

        # Once enough evidence exists and still no threshold qualifies, HOLD is hard.
        return {
            "applies": True, "passed": False,
            "state": "HOLD",
            "reason": "evidence_gate_no_validated_edge",
            "candidate_edge_pct": edge_pct,
            "qualified_threshold_pct": None,
            "evidence_n": int(overall.get("n") or 0),
            "evidence_avg_net_pct": float(overall.get("avg_net_pct") or 0.0),
            "evidence_profit_factor": float(overall.get("profit_factor") or 0.0),
            "recent_avg_net_pct": float(overall.get("recent_avg_net_pct") or 0.0),
            "exploration": exploration,
        }

    passed = edge_pct is not None and edge_pct >= float(threshold)
    chosen = next((x for x in rep.get("thresholds", []) if float(x.get("threshold_pct")) == float(threshold)), {})
    return {
        "applies": True,
        "passed": bool(passed),
        "state": "PASS" if passed else "HOLD",
        "reason": "evidence_gate_pass" if passed else "evidence_gate_edge_below_validated_threshold",
        "candidate_edge_pct": edge_pct,
        "qualified_threshold_pct": threshold,
        "evidence_n": int(chosen.get("n") or 0),
        "evidence_avg_net_pct": float(chosen.get("avg_net_pct") or 0.0),
        "evidence_profit_factor": float(chosen.get("profit_factor") or 0.0),
        "recent_avg_net_pct": float(chosen.get("recent_avg_net_pct") or 0.0),
    }


def apply_results(results: list[dict]) -> dict:
    """Gate STRICT PAPER ENTERs, with at most one WARMING exploration pass per scan."""
    checked = blocked = passed = exploration_passed = 0
    for r in results or []:
        try:
            g = evaluate(r)

            # Multiple pairs can qualify in the same 15s batch before Analytics records
            # the opened position. Keep exactly one WARMING exploration pass per batch.
            if (
                g.get("passed")
                and str(g.get("reason") or "") == "evidence_gate_warming_exploration"
            ):
                if exploration_passed >= 1:
                    g = dict(g)
                    g["passed"] = False
                    g["state"] = "WARMING"
                    g["reason"] = "evidence_gate_warming_batch_limit"
                else:
                    exploration_passed += 1

            r["evidence_gate"] = g
            if not g.get("applies"):
                continue
            checked += 1
            if g.get("passed"):
                passed += 1
                # Keep a visible trace in Risk Intelligence / Black Box.
                if str(g.get("reason") or "") == "evidence_gate_warming_exploration":
                    r["reason"] = "evidence_gate_warming_exploration"
                continue
            blocked += 1
            r["action"] = "DROP"
            r["reason"] = str(g.get("reason") or "evidence_gate")
            reasons = list(r.get("guard_reasons") or [])
            msg = (
                f"EVIDENCE GATE: {g.get('state')} · n={int(g.get('evidence_n') or 0)} "
                f"· avg={float(g.get('evidence_avg_net_pct') or 0.0):+.3f}% "
                f"· PF={float(g.get('evidence_profit_factor') or 0.0):.2f}"
            )
            if msg not in reasons:
                reasons.append(msg)
            r["guard_reasons"] = reasons
        except Exception as exc:
            # Fail closed for a would-be PAPER ENTER. Validation data should not
            # be converted into a position when the evidence layer itself fails.
            if str(r.get("action") or "").upper() == "ENTER":
                checked += 1
                blocked += 1
                r["evidence_gate"] = {
                    "applies": True, "passed": False, "state": "ERROR",
                    "reason": "evidence_gate_error", "error": f"{type(exc).__name__}: {exc}",
                }
                r["action"] = "DROP"
                r["reason"] = "evidence_gate_error"
    return {
        "status": "ok", "checked": checked, "blocked": blocked, "passed": passed,
        "exploration_passed": exploration_passed, "report": report()
    }


def status() -> dict:
    rep = report()
    return {
        "enabled": rep["enabled"], "mode": rep["mode"], "state": rep["state"],
        "qualified_threshold_pct": rep["qualified_threshold_pct"],
        "evidence_n": int((rep.get("overall") or {}).get("n") or 0),
        "risk_db_path": RISK_DB_PATH,
        "analytics_db_path": ANALYTICS_DB_PATH,
        "policy": rep["policy"],
        "exploration": rep.get("exploration"),
    }

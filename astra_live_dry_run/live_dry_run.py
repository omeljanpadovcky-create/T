"""MYSHKA / ASTRA — LIVE DRY RUN preview.

Builds the exact *would-send* order plan from normal ASTRA scan results.
It NEVER sends an exchange/Freqtrade order and NEVER mutates action/routing.

Safety invariant:
    execution_enabled = False
    create_order_calls = 0
"""
from __future__ import annotations

from collections import deque
import math
import os
import threading
import time
from typing import Any, Optional

_LOCK = threading.RLock()
_RECENT = deque(maxlen=max(20, int(os.getenv("LIVE_DRY_RUN_HISTORY", "200"))))

DEFAULT_NOTIONAL_USDT = float(os.getenv("LIVE_DRY_RUN_NOTIONAL_USDT", "10"))
DEFAULT_LEVERAGE = max(1.0, float(os.getenv("LIVE_DRY_RUN_LEVERAGE", "1")))
DEFAULT_SL_PCT = max(0.05, float(os.getenv("LIVE_DRY_RUN_SL_PCT", "0.60")))
DEFAULT_TP_PCT = max(0.05, float(os.getenv("LIVE_DRY_RUN_TP_PCT", "1.20")))
MAX_NOTIONAL_USDT = max(1.0, float(os.getenv("LIVE_DRY_RUN_MAX_NOTIONAL_USDT", "25")))
MAX_LEVERAGE = max(1.0, float(os.getenv("LIVE_DRY_RUN_MAX_LEVERAGE", "3")))


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _price(r: dict) -> Optional[float]:
    m = r.get("market") or {}
    for key in ("last_price", "last", "price", "close"):
        x = _num(m.get(key))
        if x is not None and x > 0:
            return x
    candles = m.get("candles") or r.get("candles") or []
    if candles:
        c = candles[-1]
        if isinstance(c, dict):
            x = _num(c.get("close"))
            if x is not None and x > 0:
                return x
    return None


def _norm(v: Any) -> str:
    return str(v or "").strip().upper()


def _jev_verdict(r: dict) -> str:
    j = r.get("jev") or {}
    for key in ("verdict", "decision", "state", "action", "result", "label"):
        s = _norm(j.get(key))
        if s:
            if s in {"APPROVED","PASS","PASSED","ENTER","ALLOW","ALLOWED","YES","TRUE"}:
                return "APPROVE"
            if s in {"REJECTED","DROP","BLOCK","BLOCKED","DENY","DENIED","NO","FALSE"}:
                return "REJECT"
            return s
    return "WAIT"


def _gate_state(obj: Any, *, default: str = "NO_DATA") -> str:
    if not isinstance(obj, dict) or not obj:
        return default
    # Explicit pass/fail is authoritative. Some valid gate states (for example
    # WARMING_EXPLORATION) intentionally carry passed=True even though the state
    # name is not literally PASS.
    if obj.get("passed") is True:
        return "PASS"
    if obj.get("passed") is False:
        return "FAIL"
    state = _norm(obj.get("state"))
    if state:
        return state
    return default


def _signal_side(r: dict) -> str:
    sig = r.get("signal") or {}
    side = _norm(r.get("direction") or sig.get("direction"))
    return side if side in {"LONG","SHORT"} else "WAIT"


def _preflight(r: dict) -> dict:
    sig = r.get("signal") or {}
    edge = r.get("edge") or {}
    guard = r.get("guard") or {}
    evidence = r.get("evidence_gate") or {}
    learner = r.get("adaptive_learner") or {}

    side = _signal_side(r)
    jev = _jev_verdict(r)
    action = _norm(r.get("action"))

    # The production scan does not always serialize a separate guard object.
    # If the final production action is still ENTER after the upstream pipeline,
    # missing guard telemetry must not be treated as a synthetic failure.
    if isinstance(guard, dict) and guard:
        guard_state = _gate_state(guard)
        guard_source = "explicit"
    elif action in {"ENTER","LONG","SHORT","BUY","SELL"}:
        guard_state = "IMPLICIT_PRODUCTION_PASS"
        guard_source = "final_action"
    else:
        guard_state = "NO_DATA"
        guard_source = "missing"

    evidence_state = _gate_state(evidence)
    learner_state = _gate_state(learner, default="NOT_APPLICABLE")
    edge_passed = edge.get("passed") is True
    px = _price(r)

    checks = {
        "side_directional": side in {"LONG","SHORT"},
        "market_price_present": px is not None,
        "production_action_enter": action in {"ENTER","LONG","SHORT","BUY","SELL"},
        "edge_passed": edge_passed,
        "jev_approve": jev == "APPROVE",
        "guard_pass": guard_state in {"PASS","APPROVE","READY","IMPLICIT_PRODUCTION_PASS"},
        "evidence_pass": evidence_state in {"PASS","APPROVE","READY","NOT_APPLICABLE"},
        "adaptive_pass": learner_state in {"PASS","APPROVE","READY","NOT_APPLICABLE"},
    }
    blockers = [k for k,v in checks.items() if not v]

    return {
        "checks": checks,
        "blockers": blockers,
        "all_passed": not blockers,
        "side": side,
        "action": action or "WAIT",
        "jev": jev,
        "guard": guard_state,
        "guard_source": guard_source,
        "evidence": evidence_state,
        "adaptive": learner_state,
        "price": px,
        "edge_net_pct": _num(edge.get("net_edge_pct")),
        "total_cost_pct": _num(edge.get("total_cost_pct")),
        "tech_direction": _norm(sig.get("direction") or "WAIT"),
    }


def build_preview(r: dict, now: Optional[float] = None) -> dict:
    ts = float(now if now is not None else time.time())
    pf = _preflight(r)
    pair = str(r.get("pair") or "")
    px = pf["price"]

    notional = min(max(0.0, DEFAULT_NOTIONAL_USDT), MAX_NOTIONAL_USDT)
    lev = min(max(1.0, DEFAULT_LEVERAGE), MAX_LEVERAGE)
    qty = (notional * lev / px) if px and px > 0 else None

    if px and pf["side"] == "LONG":
        sl = px * (1.0 - DEFAULT_SL_PCT / 100.0)
        tp = px * (1.0 + DEFAULT_TP_PCT / 100.0)
    elif px and pf["side"] == "SHORT":
        sl = px * (1.0 + DEFAULT_SL_PCT / 100.0)
        tp = px * (1.0 - DEFAULT_TP_PCT / 100.0)
    else:
        sl = tp = None

    would_send = bool(pf["all_passed"])
    payload = {
        "symbol": pair,
        "side": "buy" if pf["side"] == "LONG" else "sell" if pf["side"] == "SHORT" else None,
        "order_type": "market",
        "amount": qty,
        "notional_usdt": notional,
        "leverage": lev,
        "entry_reference": px,
        "stop_loss": sl,
        "take_profit": tp,
        "reduce_only": False,
    }

    result = {
        "status": "ok",
        "mode": "LIVE_DRY_RUN_ONLY",
        "observed_at": ts,
        "pair": pair,
        "direction": pf["side"],
        "preflight": pf,
        "order_payload": payload,
        "would_send_order": would_send,
        "execution_blocked": True,
        "execution_block_reason": "DRY_RUN_HARD_BLOCK",
        "create_order_called": False,
        "paper_execution_changed": False,
        "trading_decision_changed": False,
        "live_execution": False,
    }
    return result


def observe_results(results: list[dict], now: Optional[float] = None) -> dict:
    ts = float(now if now is not None else time.time())
    created = 0
    with _LOCK:
        for r in results or []:
            p = build_preview(r, ts)
            # keep only directional or potentially interesting rows
            if p["direction"] in {"LONG","SHORT"} or p["preflight"]["action"] != "WAIT":
                _RECENT.appendleft(p)
                created += 1
    return {
        "status": "ok",
        "mode": "LIVE_DRY_RUN_ONLY",
        "observed": created,
        "execution_blocked": True,
        "create_order_calls": 0,
        "live_execution": False,
    }


def recent(limit: int = 50) -> dict:
    lim = max(1, min(200, int(limit)))
    with _LOCK:
        items = list(_RECENT)[:lim]
    return {"status":"ok","mode":"LIVE_DRY_RUN_ONLY","items":items}


def status() -> dict:
    with _LOCK:
        n = len(_RECENT)
    return {
        "enabled": True,
        "mode": "LIVE_DRY_RUN_ONLY",
        "history_items": n,
        "notional_usdt": min(DEFAULT_NOTIONAL_USDT, MAX_NOTIONAL_USDT),
        "leverage": min(DEFAULT_LEVERAGE, MAX_LEVERAGE),
        "sl_pct": DEFAULT_SL_PCT,
        "tp_pct": DEFAULT_TP_PCT,
        "execution_blocked": True,
        "create_order_calls": 0,
        "paper_execution_changed": False,
        "trading_decision_changed": False,
        "live_execution": False,
    }


def init() -> dict:
    return status()

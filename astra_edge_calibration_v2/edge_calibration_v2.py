"""EDGE Calibration V2 for MYSHKA / ASTRA.

Active PAPER-only calibration layer placed after the legacy EDGE calculation
and STRICT +0.05 buffer, but before JEV/Ollama.

Goal:
- stop treating bootstrap ATR magnitude as directional evidence;
- constrain bootstrap ATR candidates to a calibration band observed in the
  user's PAPER/Risk Intelligence data;
- block obviously over-extended bootstrap entries while future data is gathered;
- never create an ENTER, never rescue a DROP, never route live orders.

This module has no network access and makes no market API calls.
"""
from __future__ import annotations

import math
import os
from typing import Any, Optional

ENABLED = os.getenv("EDGE_CALIBRATION_V2_ENABLED", "true").lower() in {"1","true","yes","on"}
MIN_EDGE_PCT = float(os.getenv("EDGE_CALIBRATION_V2_MIN_EDGE_PCT", "0.08"))
MAX_BOOTSTRAP_EDGE_PCT = float(os.getenv("EDGE_CALIBRATION_V2_MAX_BOOTSTRAP_EDGE_PCT", "0.15"))
BOOTSTRAP_MAX_DIR_5M_PCT = float(os.getenv("EDGE_CALIBRATION_V2_BOOTSTRAP_MAX_DIR_5M_PCT", "1.00"))
BOOTSTRAP_MAX_DIR_15M_PCT = float(os.getenv("EDGE_CALIBRATION_V2_BOOTSTRAP_MAX_DIR_15M_PCT", "1.50"))


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _strict_score(signal: Any) -> int:
    direction = str(getattr(signal, "direction", "WAIT") or "WAIT").upper()
    fast = _num(getattr(signal, "ema_fast", None))
    slow = _num(getattr(signal, "ema_slow", None))
    regime = str(getattr(signal, "structure", "RANGE") or "RANGE").upper()
    rsi = _num(getattr(signal, "rsi", None))
    vol = _num(getattr(signal, "volume_ratio", None))
    if direction not in {"LONG","SHORT"} or None in {fast, slow, rsi, vol}:
        return 0
    if direction == "LONG":
        checks = [fast > slow, regime == "UP", 52.0 <= rsi <= 72.0, vol >= 0.60]
    else:
        checks = [fast < slow, regime == "DOWN", 28.0 <= rsi <= 48.0, vol >= 0.60]
    return sum(bool(x) for x in checks)


def _close(c: Any) -> Optional[float]:
    if isinstance(c, dict):
        return _num(c.get("close"))
    return _num(getattr(c, "close", None))


def _directional_momentum(candles: list[Any], direction: str, periods: int) -> Optional[float]:
    closes = [_close(c) for c in (candles or [])]
    closes = [x for x in closes if x is not None and x > 0]
    if len(closes) <= periods:
        return None
    base = closes[-1 - periods]
    last = closes[-1]
    raw = (last / base - 1.0) * 100.0
    return raw if direction == "LONG" else -raw


def apply(*, signal: Any, edge: Any, candles: list[Any],
          atr_pct: Optional[float] = None, atr_median_pct: Optional[float] = None) -> dict:
    if not ENABLED:
        return {"applies": False, "passed": True, "state": "DISABLED", "reason": "edge_calibration_v2_disabled"}

    if _strict_score(signal) != 4:
        return {"applies": False, "passed": True, "state": "NOT_APPLICABLE", "reason": "not_strict_4of4"}
    if edge is None or not bool(getattr(edge, "passed", False)):
        return {"applies": False, "passed": True, "state": "NOT_APPLICABLE", "reason": "edge_not_passed"}

    direction = str(getattr(signal, "direction", "") or "").upper()
    basis = str(getattr(edge, "basis", "") or "")
    edge_pct = _num(getattr(edge, "net_edge_pct", None))
    dir5 = _directional_momentum(candles, direction, 5)
    dir15 = _directional_momentum(candles, direction, 15)

    info = {
        "applies": True,
        "passed": True,
        "state": "PASS",
        "reason": "edge_calibration_v2_pass",
        "basis": basis,
        "candidate_edge_pct": edge_pct,
        "calibration_min_edge_pct": MIN_EDGE_PCT,
        "bootstrap_max_edge_pct": MAX_BOOTSTRAP_EDGE_PCT,
        "directional_momentum_5m_pct": dir5,
        "directional_momentum_15m_pct": dir15,
        "atr_pct": _num(atr_pct),
        "atr_median_pct": _num(atr_median_pct),
        "paper_only": True,
        "live_execution": False,
    }

    # Legacy STRICT +0.05 still runs before this layer. Calibration V2 is stricter:
    # candidates below +0.08% are not used for PAPER calibration entries.
    if edge_pct is None or edge_pct < MIN_EDGE_PCT:
        info.update({"passed": False, "state": "HOLD", "reason": "edge_calibration_v2_below_band"})
        return info

    # bootstrap_atr is volatility-derived. It is not validated directional edge.
    # Keep it only inside the calibration band and avoid chasing an already large move.
    if basis == "bootstrap_atr":
        if edge_pct > MAX_BOOTSTRAP_EDGE_PCT:
            info.update({"passed": False, "state": "HOLD", "reason": "edge_calibration_v2_bootstrap_edge_too_high"})
            return info
        if dir5 is not None and dir5 >= BOOTSTRAP_MAX_DIR_5M_PCT:
            info.update({"passed": False, "state": "HOLD", "reason": "edge_calibration_v2_bootstrap_overextended_5m"})
            return info
        if dir15 is not None and dir15 >= BOOTSTRAP_MAX_DIR_15M_PCT:
            info.update({"passed": False, "state": "HOLD", "reason": "edge_calibration_v2_bootstrap_overextended_15m"})
            return info

    return info


def status() -> dict:
    return {
        "enabled": ENABLED,
        "mode": "PAPER_CALIBRATION",
        "min_edge_pct": MIN_EDGE_PCT,
        "max_bootstrap_edge_pct": MAX_BOOTSTRAP_EDGE_PCT,
        "bootstrap_max_directional_5m_pct": BOOTSTRAP_MAX_DIR_5M_PCT,
        "bootstrap_max_directional_15m_pct": BOOTSTRAP_MAX_DIR_15M_PCT,
        "bootstrap_atr_directional_proof": False,
        "live_execution": False,
        "extra_market_api_calls": False,
    }

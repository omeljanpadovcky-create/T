"""EDGE Calibration V3 for MYSHKA / ASTRA.

PAPER-only monotonic recalibration trained from clustered forward outcomes.

Key design:
- source of truth: Forward Experiment Lab SQLite outcomes;
- only CLOSED 5m STRICT 4/4 observations are used;
- one observation per pair+side+5m cluster to reduce scan autocorrelation;
- target is realized NET after recorded costs;
- isotonic regression is implemented locally with PAVA (no sklearn dependency);
- until minimum clustered support is available, production PAPER candidates HOLD;
- calibration can only reject/HOLD an already-passed legacy EDGE candidate;
- it can never create/rescue ENTER and never enables LIVE execution.
"""
from __future__ import annotations

import math
import os
import sqlite3
import threading
import time
from typing import Any, Optional

ENABLED = os.getenv("EDGE_CALIBRATION_V3_ENABLED", "true").lower() in {"1","true","yes","on"}
DB_PATH = os.getenv("FORWARD_EXPERIMENT_DB_PATH", "/data/myshka_forward_experiments.sqlite3")
HORIZON_SEC = max(60, int(os.getenv("EDGE_CALIBRATION_V3_HORIZON_SEC", "300")))
MIN_CLUSTERS = max(10, int(os.getenv("EDGE_CALIBRATION_V3_MIN_CLUSTERS", "30")))
MIN_BLOCK_SUPPORT = max(3, int(os.getenv("EDGE_CALIBRATION_V3_MIN_BLOCK_SUPPORT", "5")))
MIN_CALIBRATED_NET_PCT = float(os.getenv("EDGE_CALIBRATION_V3_MIN_CALIBRATED_NET_PCT", "0.0"))
EXCLUDE_NEUTRAL_FROM_FIT = os.getenv("EDGE_CALIBRATION_V3_EXCLUDE_NEUTRAL", "true").lower() in {"1","true","yes","on"}
BOOTSTRAP_MAX_DIR_5M_PCT = float(os.getenv("EDGE_CALIBRATION_V3_BOOTSTRAP_MAX_DIR_5M_PCT", "1.00"))
BOOTSTRAP_MAX_DIR_15M_PCT = float(os.getenv("EDGE_CALIBRATION_V3_BOOTSTRAP_MAX_DIR_15M_PCT", "1.50"))
CACHE_SEC = max(5, int(os.getenv("EDGE_CALIBRATION_V3_CACHE_SEC", "30")))

_LOCK = threading.RLock()
_CACHE = {"at": 0.0, "model": None}


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


def _pf(vals: list[float]) -> float:
    pos = sum(x for x in vals if x > 0)
    neg = abs(sum(x for x in vals if x <= 0))
    return pos / neg if neg > 1e-12 else (999.0 if pos > 0 else 0.0)


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 1e-18 or vy <= 1e-18:
        return 0.0
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(vx * vy)


def _pava(points: list[tuple[float, float]]) -> list[dict]:
    """Increasing isotonic regression over (modeled_edge_pct, realized_net_pct)."""
    if not points:
        return []
    ordered = sorted((float(x), float(y)) for x, y in points)
    blocks: list[dict] = []
    for x, y in ordered:
        b = {
            "x_min": x, "x_max": x,
            "sum_y": y, "sum_y2": y * y,
            "weight": 1, "mean": y,
        }
        blocks.append(b)
        while len(blocks) >= 2 and blocks[-2]["mean"] > blocks[-1]["mean"]:
            right = blocks.pop()
            left = blocks.pop()
            w = int(left["weight"]) + int(right["weight"])
            merged = {
                "x_min": left["x_min"],
                "x_max": right["x_max"],
                "sum_y": left["sum_y"] + right["sum_y"],
                "sum_y2": left["sum_y2"] + right["sum_y2"],
                "weight": w,
            }
            merged["mean"] = merged["sum_y"] / w
            blocks.append(merged)

    out = []
    for b in blocks:
        n = int(b["weight"])
        mean = float(b["mean"])
        if n > 1:
            var = max(0.0, (float(b["sum_y2"]) - n * mean * mean) / (n - 1))
            se = math.sqrt(var / n)
        else:
            se = None
        out.append({
            "edge_min_pct": float(b["x_min"]),
            "edge_max_pct": float(b["x_max"]),
            "calibrated_net_pct": mean,
            "support": n,
            "standard_error_pct": se,
        })
    return out


def _cluster_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for r in sorted(rows, key=lambda z: (float(z.get("opened_at") or 0), int(z.get("id") or 0))):
        key = str(r.get("cluster_key") or "")
        if not key:
            bucket = int(float(r.get("opened_at") or 0) // 300) * 300
            key = f"{r.get('pair')}|{r.get('side')}|{bucket}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _load_rows() -> list[dict]:
    if not os.path.exists(DB_PATH):
        return []
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forward_outcomes'"
        ).fetchone()
        if not exists:
            return []
        rows = [
            dict(r) for r in con.execute(
                """
                SELECT id,pair,side,cluster_key,opened_at,edge_pct,net_pct,
                       xcheck_state,tech_score,horizon_sec,status
                FROM forward_outcomes
                WHERE status='CLOSED'
                  AND horizon_sec=?
                  AND tech_score=4
                  AND edge_pct IS NOT NULL
                  AND net_pct IS NOT NULL
                ORDER BY opened_at,id
                """,
                (HORIZON_SEC,),
            ).fetchall()
        ]
    finally:
        con.close()
    return _cluster_rows(rows)


def _build_model(rows: list[dict]) -> dict:
    clustered = _cluster_rows(rows)
    neutral_rows = [r for r in clustered if str(r.get("xcheck_state") or "").upper() == "NEUTRAL"]
    fit_rows = clustered
    if EXCLUDE_NEUTRAL_FROM_FIT:
        fit_rows = [r for r in clustered if str(r.get("xcheck_state") or "").upper() != "NEUTRAL"]

    points = []
    vals = []
    xs = []
    for r in fit_rows:
        x, y = _num(r.get("edge_pct")), _num(r.get("net_pct"))
        if x is None or y is None:
            continue
        points.append((x, y))
        xs.append(x)
        vals.append(y)

    blocks = _pava(points)
    neutral_vals = [float(r["net_pct"]) for r in neutral_rows if _num(r.get("net_pct")) is not None]
    state = "READY" if len(points) >= MIN_CLUSTERS else "WARMING"

    return {
        "state": state,
        "cluster_n": len(points),
        "total_cluster_n": len(clustered),
        "neutral_excluded_n": len(neutral_rows) if EXCLUDE_NEUTRAL_FROM_FIT else 0,
        "raw_avg_net_pct": (sum(vals) / len(vals)) if vals else 0.0,
        "raw_profit_factor": _pf(vals),
        "raw_edge_net_corr": _pearson(xs, vals),
        "blocks": blocks,
        "neutral": {
            "n": len(neutral_vals),
            "avg_net_pct": (sum(neutral_vals) / len(neutral_vals)) if neutral_vals else 0.0,
            "profit_factor": _pf(neutral_vals),
        },
    }


def _model(force: bool = False) -> dict:
    now = time.time()
    with _LOCK:
        cached = _CACHE.get("model")
        if not force and cached is not None and now - float(_CACHE.get("at") or 0) < CACHE_SEC:
            return cached
    try:
        model = _build_model(_load_rows())
    except Exception as exc:
        model = {
            "state": "ERROR", "cluster_n": 0, "total_cluster_n": 0,
            "neutral_excluded_n": 0, "raw_avg_net_pct": 0.0,
            "raw_profit_factor": 0.0, "raw_edge_net_corr": None,
            "blocks": [], "neutral": {"n": 0, "avg_net_pct": 0.0, "profit_factor": 0.0},
            "error": f"{type(exc).__name__}: {exc}",
        }
    with _LOCK:
        _CACHE["at"] = now
        _CACHE["model"] = model
    return model


def _predict(model: dict, edge_pct: float) -> Optional[dict]:
    blocks = list(model.get("blocks") or [])
    if not blocks:
        return None
    x = float(edge_pct)
    for b in blocks:
        if float(b["edge_min_pct"]) <= x <= float(b["edge_max_pct"]):
            return dict(b)
    if x < float(blocks[0]["edge_min_pct"]):
        out = dict(blocks[0]); out["extrapolated"] = True; return out
    out = dict(blocks[-1]); out["extrapolated"] = True; return out


def apply(*, signal: Any, edge: Any, candles: list[Any],
          atr_pct: Optional[float] = None, atr_median_pct: Optional[float] = None) -> dict:
    if not ENABLED:
        return {"applies": False, "passed": True, "state": "DISABLED", "reason": "edge_calibration_v3_disabled"}

    if _strict_score(signal) != 4:
        return {"applies": False, "passed": True, "state": "NOT_APPLICABLE", "reason": "not_strict_4of4"}
    if edge is None or not bool(getattr(edge, "passed", False)):
        return {"applies": False, "passed": True, "state": "NOT_APPLICABLE", "reason": "edge_not_passed"}

    edge_pct = _num(getattr(edge, "net_edge_pct", None))
    direction = str(getattr(signal, "direction", "") or "").upper()
    basis = str(getattr(edge, "basis", "") or "")
    dir5 = _directional_momentum(candles, direction, 5)
    dir15 = _directional_momentum(candles, direction, 15)
    model = _model()

    info = {
        "applies": True,
        "passed": False,
        "state": str(model.get("state") or "WARMING"),
        "reason": "edge_calibration_v3_warming",
        "basis": basis,
        "candidate_edge_pct": edge_pct,
        "cluster_n": int(model.get("cluster_n") or 0),
        "min_clusters": MIN_CLUSTERS,
        "neutral_excluded_n": int(model.get("neutral_excluded_n") or 0),
        "raw_edge_net_corr": model.get("raw_edge_net_corr"),
        "raw_avg_net_pct": model.get("raw_avg_net_pct"),
        "raw_profit_factor": model.get("raw_profit_factor"),
        "paper_only": True,
        "live_execution": False,
        "directional_momentum_5m_pct": dir5,
        "directional_momentum_15m_pct": dir15,
        "atr_pct": _num(atr_pct),
        "atr_median_pct": _num(atr_median_pct),
    }

    if model.get("state") == "ERROR":
        info.update({"state": "HOLD", "reason": "edge_calibration_v3_model_error", "error": model.get("error")})
        return info
    if int(model.get("cluster_n") or 0) < MIN_CLUSTERS:
        info.update({"state": "WARMING", "reason": "edge_calibration_v3_warming"})
        return info
    if edge_pct is None:
        info.update({"state": "HOLD", "reason": "edge_calibration_v3_missing_edge"})
        return info

    pred = _predict(model, edge_pct)
    if pred is None:
        info.update({"state": "HOLD", "reason": "edge_calibration_v3_no_model"})
        return info
    info["isotonic"] = pred
    support = int(pred.get("support") or 0)
    calibrated_net = _num(pred.get("calibrated_net_pct"))
    if support < MIN_BLOCK_SUPPORT:
        info.update({"state": "HOLD", "reason": "edge_calibration_v3_low_support"})
        return info
    if calibrated_net is None or calibrated_net <= MIN_CALIBRATED_NET_PCT:
        info.update({"state": "HOLD", "reason": "edge_calibration_v3_nonpositive_expectancy"})
        return info

    if basis == "bootstrap_atr":
        if dir5 is not None and dir5 >= BOOTSTRAP_MAX_DIR_5M_PCT:
            info.update({"state": "HOLD", "reason": "edge_calibration_v3_bootstrap_overextended_5m"})
            return info
        if dir15 is not None and dir15 >= BOOTSTRAP_MAX_DIR_15M_PCT:
            info.update({"state": "HOLD", "reason": "edge_calibration_v3_bootstrap_overextended_15m"})
            return info

    info.update({"passed": True, "state": "PASS", "reason": "edge_calibration_v3_pass"})
    return info


def report() -> dict:
    m = _model(force=True)
    return {
        "status": "ok" if m.get("state") != "ERROR" else "error",
        "version": 3,
        "mode": "PAPER_ISOTONIC_CLUSTERED",
        "horizon_sec": HORIZON_SEC,
        "min_clusters": MIN_CLUSTERS,
        "min_block_support": MIN_BLOCK_SUPPORT,
        "min_calibrated_net_pct": MIN_CALIBRATED_NET_PCT,
        "exclude_neutral_from_fit": EXCLUDE_NEUTRAL_FROM_FIT,
        **m,
        "notes": [
            "STRICT 4/4 only",
            "one pair+side+5m cluster observation",
            "target is realized NET after recorded costs",
            "PAVA enforces non-decreasing calibrated expectancy",
            "higher modeled EDGE cannot automatically become stronger evidence",
            "calibration can HOLD only; never rescues or creates ENTER",
        ],
        "live_execution": False,
    }


def status() -> dict:
    m = _model()
    return {
        "enabled": ENABLED,
        "version": 3,
        "mode": "PAPER_ISOTONIC_CLUSTERED",
        "state": m.get("state"),
        "cluster_n": int(m.get("cluster_n") or 0),
        "min_clusters": MIN_CLUSTERS,
        "horizon_sec": HORIZON_SEC,
        "blocks": len(m.get("blocks") or []),
        "exclude_neutral_from_fit": EXCLUDE_NEUTRAL_FROM_FIT,
        "raw_edge_net_corr": m.get("raw_edge_net_corr"),
        "paper_only": True,
        "live_execution": False,
        "extra_market_api_calls": False,
    }

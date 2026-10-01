"""MYSHKA / ASTRA Adaptive ML Learner V1.

Controlled self-learning for PAPER validation.

What it does:
- learns a logistic scorer from settled STRICT 4/4 + JEV APPROVE Risk Intelligence outcomes;
- uses walk-forward train/test (older 70% -> newer 30%);
- searches challenger policies over ML probability + minimum EDGE thresholds;
- promotes only policies that are profitable on BOTH train and holdout, have enough samples,
  beat the holdout baseline, and remain positive on recent selected outcomes;
- when READY, it may only turn an existing PAPER ENTER into DROP. It can NEVER rescue a
  DROP, bypass Evidence Gate, create a signal, size an order, or route live execution.

No external API calls. No sklearn/numpy dependency. Pure Python logistic regression.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
from typing import Any, Optional

RISK_DB_PATH = os.getenv("RISK_INTELLIGENCE_DB_PATH", "/data/myshka_risk_intelligence.sqlite3")
DB_PATH = os.getenv("ADAPTIVE_LEARNER_DB_PATH", "/data/myshka_adaptive_learner.sqlite3")
ENABLED = os.getenv("ADAPTIVE_LEARNER_ENABLED", "true").lower() in {"1","true","yes","on"}

MIN_TOTAL = max(30, int(os.getenv("ADAPTIVE_LEARNER_MIN_TOTAL", "60")))
MIN_TRAIN = max(20, int(os.getenv("ADAPTIVE_LEARNER_MIN_TRAIN", "35")))
MIN_TEST = max(10, int(os.getenv("ADAPTIVE_LEARNER_MIN_TEST", "15")))
MIN_SELECTED_TRAIN = max(10, int(os.getenv("ADAPTIVE_LEARNER_MIN_SELECTED_TRAIN", "20")))
MIN_SELECTED_TEST = max(5, int(os.getenv("ADAPTIVE_LEARNER_MIN_SELECTED_TEST", "10")))
MIN_AVG_NET_PCT = float(os.getenv("ADAPTIVE_LEARNER_MIN_AVG_NET_PCT", "0.03"))
MIN_PROFIT_FACTOR = float(os.getenv("ADAPTIVE_LEARNER_MIN_PROFIT_FACTOR", "1.10"))
MIN_DELTA_VS_BASELINE_PCT = float(os.getenv("ADAPTIVE_LEARNER_MIN_DELTA_VS_BASELINE_PCT", "0.05"))
MAX_TEST_LCB95_PCT = float(os.getenv("ADAPTIVE_LEARNER_MIN_TEST_LCB95_PCT", "-0.05"))
CACHE_SEC = max(5, int(os.getenv("ADAPTIVE_LEARNER_CACHE_SEC", "30")))

PROB_THRESHOLDS = tuple(float(x) for x in os.getenv("ADAPTIVE_LEARNER_PROB_THRESHOLDS", "0.55,0.60,0.65,0.70").split(","))
EDGE_THRESHOLDS = tuple(float(x) for x in os.getenv("ADAPTIVE_LEARNER_EDGE_THRESHOLDS", "0.05,0.10,0.15,0.20,0.25,0.30").split(","))

FEATURE_NAMES = (
    "edge_pct", "expected_move_pct", "total_cost_pct", "spread_pct",
    "atr_pct", "rsi", "volume_ratio", "jev_confidence",
    "price_15m_pct", "oi_15m_pct", "funding_rate_pct",
    "long_short_ratio", "btc_15m_pct", "context_samples_log",
    "side_long", "regime_up", "regime_down",
)

_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {"ts": 0.0, "closed_n": -1, "report": None}


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
    fast = _num(sig.get("ema_fast"))
    slow = _num(sig.get("ema_slow"))
    rsi = _num(sig.get("rsi"))
    vol = _num(sig.get("volume_ratio"))
    regime = str(sig.get("structure") or "RANGE").upper()
    if side not in {"LONG","SHORT"} or None in {fast,slow,rsi,vol}:
        return 0
    if side == "LONG":
        checks = [fast > slow, regime == "UP", 52 <= rsi <= 72, vol >= 0.60]
    else:
        checks = [fast < slow, regime == "DOWN", 28 <= rsi <= 48, vol >= 0.60]
    return sum(bool(x) for x in checks)


def _conn(path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    if path == DB_PATH:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    return con


def init() -> dict:
    with _LOCK, _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS learner_snapshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                source_closed_n INTEGER NOT NULL,
                state TEXT NOT NULL,
                champion_json TEXT,
                report_json TEXT NOT NULL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_learner_snapshots_created ON learner_snapshots(created_at DESC)")
    return status()


def _risk_rows() -> list[dict]:
    if not os.path.exists(RISK_DB_PATH):
        return []
    try:
        con = _conn(RISK_DB_PATH)
        try:
            rows = con.execute(
                """
                SELECT id,pair,side,opened_at,regime,tech_score,edge_pct,expected_move_pct,
                       total_cost_pct,spread_pct,atr_pct,rsi,volume_ratio,jev_verdict,
                       jev_confidence,price_15m_pct,oi_15m_pct,funding_rate_pct,
                       long_short_ratio,btc_15m_pct,context_samples,confidence_score,
                       flags_json,net_pct,direction_hit
                FROM risk_candidates
                WHERE status='CLOSED'
                  AND tech_score=4
                  AND UPPER(COALESCE(jev_verdict,''))='APPROVE'
                  AND edge_pct IS NOT NULL
                  AND net_pct IS NOT NULL
                ORDER BY opened_at ASC,id ASC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()
    except Exception:
        return []


def _flag_count(raw: Any) -> int:
    try:
        x = json.loads(raw or "[]") if not isinstance(raw, list) else raw
        return len(x) if isinstance(x, list) else 0
    except Exception:
        return 0


def _features(r: dict) -> list[Optional[float]]:
    side = str(r.get("side") or "").upper()
    regime = str(r.get("regime") or "").upper()
    ctx_n = max(0.0, float(r.get("context_samples") or 0.0))
    return [
        _num(r.get("edge_pct")),
        _num(r.get("expected_move_pct")),
        _num(r.get("total_cost_pct")),
        _num(r.get("spread_pct")),
        _num(r.get("atr_pct")),
        _num(r.get("rsi")),
        _num(r.get("volume_ratio")),
        _num(r.get("jev_confidence")),
        _num(r.get("price_15m_pct")),
        _num(r.get("oi_15m_pct")),
        _num(r.get("funding_rate_pct")),
        _num(r.get("long_short_ratio")),
        _num(r.get("btc_15m_pct")),
        math.log1p(ctx_n),
        1.0 if side == "LONG" else 0.0,
        1.0 if regime == "UP" else 0.0,
        1.0 if regime == "DOWN" else 0.0,
    ]


def _prepare(train_rows: list[dict]) -> tuple[list[list[float]], list[float], list[float]]:
    raw = [_features(r) for r in train_rows]
    means: list[float] = []
    stds: list[float] = []
    for j in range(len(FEATURE_NAMES)):
        vals = [float(x[j]) for x in raw if x[j] is not None]
        mean = sum(vals) / len(vals) if vals else 0.0
        var = sum((v - mean) ** 2 for v in vals) / len(vals) if vals else 0.0
        std = math.sqrt(var)
        means.append(mean)
        stds.append(std if std > 1e-9 else 1.0)

    out: list[list[float]] = []
    for row in raw:
        out.append([
            ((means[j] if row[j] is None else float(row[j])) - means[j]) / stds[j]
            for j in range(len(FEATURE_NAMES))
        ])
    return out, means, stds


def _transform(rows: list[dict], means: list[float], stds: list[float]) -> list[list[float]]:
    out = []
    for r in rows:
        raw = _features(r)
        out.append([
            ((means[j] if raw[j] is None else float(raw[j])) - means[j]) / stds[j]
            for j in range(len(FEATURE_NAMES))
        ])
    return out


def _sigmoid(z: float) -> float:
    z = max(-35.0, min(35.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _fit_logistic(train_rows: list[dict], epochs: int = 450, lr: float = 0.05, l2: float = 0.02) -> Optional[dict]:
    if len(train_rows) < 2:
        return None
    y = [1.0 if float(r.get("net_pct") or 0.0) > 0.0 else 0.0 for r in train_rows]
    if len(set(y)) < 2:
        return None
    x, means, stds = _prepare(train_rows)
    d = len(FEATURE_NAMES)
    w = [0.0] * d
    b = math.log((sum(y) + 1.0) / (len(y) - sum(y) + 1.0))
    n = float(len(y))
    for _ in range(max(50, epochs)):
        gw = [0.0] * d
        gb = 0.0
        for xi, yi in zip(x, y):
            p = _sigmoid(b + sum(a * z for a, z in zip(w, xi)))
            err = p - yi
            gb += err
            for j in range(d):
                gw[j] += err * xi[j]
        b -= lr * (gb / n)
        for j in range(d):
            w[j] -= lr * ((gw[j] / n) + l2 * w[j])
    return {"weights": w, "bias": b, "means": means, "stds": stds, "features": list(FEATURE_NAMES)}


def _predict(model: dict, rows: list[dict]) -> list[float]:
    x = _transform(rows, model["means"], model["stds"])
    w = model["weights"]
    b = float(model["bias"])
    return [_sigmoid(b + sum(a * z for a, z in zip(w, xi))) for xi in x]


def _metrics(rows: list[dict]) -> dict:
    nets = [float(r.get("net_pct") or 0.0) for r in rows]
    n = len(nets)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    pos = sum(wins)
    neg = abs(sum(losses))
    avg = sum(nets) / n if n else 0.0
    var = sum((x - avg) ** 2 for x in nets) / (n - 1) if n > 1 else 0.0
    se = math.sqrt(var / n) if n else 0.0
    return {
        "n": n,
        "wins": len(wins),
        "win_rate_pct": (len(wins) / n * 100.0) if n else 0.0,
        "avg_net_pct": avg,
        "total_net_pct": sum(nets),
        "profit_factor": (pos / neg) if neg > 1e-12 else (999.0 if pos > 0 else 0.0),
        "lcb95_net_pct": avg - 1.96 * se,
    }


def _select(rows: list[dict], probs: list[float], edge_t: float, prob_t: float) -> list[dict]:
    return [
        r for r, p in zip(rows, probs)
        if float(r.get("edge_pct") or 0.0) >= edge_t and float(p) >= prob_t
    ]


def _top_feature_weights(model: dict, limit: int = 8) -> list[dict]:
    pairs = [{"feature": name, "weight": float(w)} for name, w in zip(FEATURE_NAMES, model.get("weights", []))]
    pairs.sort(key=lambda x: abs(x["weight"]), reverse=True)
    return pairs[:max(1, limit)]


def _build_report(rows: list[dict]) -> dict:
    n = len(rows)
    base_all = _metrics(rows)
    if not ENABLED:
        return {"status":"ok","enabled":False,"mode":"SHADOW_CHAMPION_CHALLENGER","state":"DISABLED","source_n":n,"baseline":base_all}
    if n < MIN_TOTAL:
        return {
            "status":"ok","enabled":True,"mode":"SHADOW_CHAMPION_CHALLENGER","state":"WARMING",
            "source_n":n,"need_total":MIN_TOTAL,"baseline":base_all,"champion":None,"challengers":[],
            "note":"Collecting settled STRICT 4/4 + JEV APPROVE outcomes. No PAPER decision is changed yet.",
        }

    split = max(MIN_TRAIN, min(n - MIN_TEST, int(n * 0.70)))
    train = rows[:split]
    test = rows[split:]
    if len(train) < MIN_TRAIN or len(test) < MIN_TEST:
        return {
            "status":"ok","enabled":True,"mode":"SHADOW_CHAMPION_CHALLENGER","state":"WARMING",
            "source_n":n,"train_n":len(train),"test_n":len(test),"baseline":base_all,"champion":None,"challengers":[],
        }

    model = _fit_logistic(train)
    if not model:
        return {
            "status":"ok","enabled":True,"mode":"SHADOW_CHAMPION_CHALLENGER","state":"SEARCHING",
            "source_n":n,"train_n":len(train),"test_n":len(test),"baseline":base_all,"champion":None,"challengers":[],
            "reason":"model_not_trainable",
        }

    p_train = _predict(model, train)
    p_test = _predict(model, test)
    p_all = _predict(model, rows)
    baseline_test = _metrics(test)
    candidates = []

    for edge_t in EDGE_THRESHOLDS:
        for prob_t in PROB_THRESHOLDS:
            s_train = _select(train, p_train, edge_t, prob_t)
            s_test = _select(test, p_test, edge_t, prob_t)
            s_all = _select(rows, p_all, edge_t, prob_t)
            mt = _metrics(s_train)
            mv = _metrics(s_test)
            recent = _metrics(s_all[-min(10, len(s_all)):]) if s_all else _metrics([])
            delta = float(mv["avg_net_pct"]) - float(baseline_test["avg_net_pct"])
            passed = (
                int(mt["n"]) >= MIN_SELECTED_TRAIN
                and int(mv["n"]) >= MIN_SELECTED_TEST
                and float(mt["avg_net_pct"]) >= MIN_AVG_NET_PCT
                and float(mv["avg_net_pct"]) >= MIN_AVG_NET_PCT
                and float(mt["profit_factor"]) >= MIN_PROFIT_FACTOR
                and float(mv["profit_factor"]) >= MIN_PROFIT_FACTOR
                and float(mv["lcb95_net_pct"]) >= MAX_TEST_LCB95_PCT
                and float(recent["avg_net_pct"]) > 0.0
                and delta >= MIN_DELTA_VS_BASELINE_PCT
            )
            score = (
                float(mv["avg_net_pct"])
                + 0.25 * float(mt["avg_net_pct"])
                + 0.10 * float(mv["lcb95_net_pct"])
                + min(0.05, int(mv["n"]) * 0.001)
            )
            candidates.append({
                "edge_threshold_pct": edge_t,
                "ml_probability_threshold": prob_t,
                "train": mt,
                "holdout": mv,
                "recent": recent,
                "delta_vs_holdout_baseline_pct": delta,
                "passed": passed,
                "score": score,
            })

    candidates.sort(key=lambda c: (
        1 if c["passed"] else 0,
        float(c["score"]),
        int(c["holdout"]["n"]),
    ), reverse=True)
    champion = next((c for c in candidates if c["passed"]), None)

    state = "READY_FOR_PAPER_FILTER" if champion else "SEARCHING"
    return {
        "status":"ok","enabled":True,"mode":"SHADOW_CHAMPION_CHALLENGER","state":state,
        "source_n":n,"train_n":len(train),"test_n":len(test),
        "baseline":base_all,"holdout_baseline":baseline_test,
        "champion":champion,
        "challengers":candidates[:10],
        "model":{
            "type":"logistic_regression_l2",
            "features":list(FEATURE_NAMES),
            "top_weights":_top_feature_weights(model),
            "weights":model["weights"],
            "bias":model["bias"],
            "means":model["means"],
            "stds":model["stds"],
        },
        "policy":{
            "min_total":MIN_TOTAL,
            "min_train":MIN_TRAIN,
            "min_test":MIN_TEST,
            "min_selected_train":MIN_SELECTED_TRAIN,
            "min_selected_test":MIN_SELECTED_TEST,
            "min_avg_net_pct":MIN_AVG_NET_PCT,
            "min_profit_factor":MIN_PROFIT_FACTOR,
            "min_delta_vs_baseline_pct":MIN_DELTA_VS_BASELINE_PCT,
            "min_test_lcb95_pct":MAX_TEST_LCB95_PCT,
        },
        "note":"Learner can only add a PAPER filter after Evidence Gate. It never creates/rescues ENTER and never routes live orders.",
    }


def _persist(rep: dict) -> None:
    try:
        init()
        source_n = int(rep.get("source_n") or 0)
        with _LOCK, _conn() as con:
            last = con.execute("SELECT source_closed_n FROM learner_snapshots ORDER BY id DESC LIMIT 1").fetchone()
            if last and int(last["source_closed_n"]) == source_n:
                return
            champ = rep.get("champion")
            con.execute(
                "INSERT INTO learner_snapshots(created_at,source_closed_n,state,champion_json,report_json) VALUES(?,?,?,?,?)",
                (
                    time.time(), source_n, str(rep.get("state") or "UNKNOWN"),
                    json.dumps(champ, ensure_ascii=False, separators=(",",":")) if champ else None,
                    json.dumps(rep, ensure_ascii=False, separators=(",",":"), default=str),
                ),
            )
    except Exception:
        pass


def report(force: bool = False) -> dict:
    try:
        now = time.time()

        # Fast path: do NOT touch the risk DB while the cached model is fresh.
        # The old implementation loaded the full risk table before checking
        # CACHE_SEC, which could block health checks and normal scan workers.
        with _LOCK:
            cached = _CACHE.get("report")
            cached_ts = float(_CACHE.get("ts") or 0.0)
            if not force and cached is not None and now - cached_ts < CACHE_SEC:
                return cached

        rows = _risk_rows()
        n = len(rows)

        # If the DB has no new closed rows, reuse the existing model and only
        # refresh the cache timestamp.
        with _LOCK:
            cached = _CACHE.get("report")
            cached_n = int(_CACHE.get("closed_n") or -1)
            if not force and cached is not None and cached_n == n:
                _CACHE["ts"] = now
                return cached

        rep = _build_report(rows)
        _persist(rep)
        with _LOCK:
            _CACHE.update({"ts":now,"closed_n":n,"report":rep})
        return rep
    except Exception as exc:
        return {
            "status":"error","enabled":ENABLED,"mode":"SHADOW_CHAMPION_CHALLENGER","state":"ERROR",
            "error":f"{type(exc).__name__}: {exc}","champion":None,
        }


def _candidate_row(result: dict) -> dict:
    sig = result.get("signal") or {}
    edge = result.get("edge") or {}
    jev = result.get("jev") or {}
    ctx = result.get("context") or {}
    mkt = result.get("market") or {}
    return {
        "side":str(result.get("direction") or sig.get("direction") or ""),
        "regime":str(sig.get("structure") or "RANGE"),
        "edge_pct":_num(edge.get("net_edge_pct")),
        "expected_move_pct":_num(edge.get("expected_move_pct")),
        "total_cost_pct":_num(edge.get("total_cost_pct")),
        "spread_pct":_num(mkt.get("spread_pct")),
        "atr_pct":_num(mkt.get("atr_pct")),
        "rsi":_num(sig.get("rsi")),
        "volume_ratio":_num(sig.get("volume_ratio")),
        "jev_confidence":_num(jev.get("confidence")),
        "price_15m_pct":_num(ctx.get("price_change_15m_pct")),
        "oi_15m_pct":_num(ctx.get("oi_change_15m_pct")),
        "funding_rate_pct":_num(ctx.get("funding_rate_pct")),
        "long_short_ratio":_num(ctx.get("long_short_ratio")),
        "btc_15m_pct":_num(ctx.get("btc_price_change_15m_pct")),
        "context_samples":int(ctx.get("samples") or 0),
    }


def _predict_one(rep: dict, result: dict) -> Optional[float]:
    model = rep.get("model") or {}
    if not model.get("weights"):
        return None
    row = _candidate_row(result)
    return _predict(model, [row])[0]


def apply_results(results: list[dict]) -> dict:
    """Apply only a promoted learner filter to existing PAPER ENTER candidates."""
    rep = report()
    champion = rep.get("champion")
    ready = str(rep.get("state") or "") == "READY_FOR_PAPER_FILTER" and champion
    checked = blocked = passed = 0

    for r in results or []:
        # Critical invariant: learner NEVER rescues or creates an ENTER.
        if str(r.get("action") or "").upper() != "ENTER":
            r["adaptive_learner"] = {"applies":False,"state":rep.get("state"),"reason":"not_enter"}
            continue
        if not ready:
            r["adaptive_learner"] = {"applies":False,"state":rep.get("state"),"reason":"no_promoted_champion"}
            continue
        try:
            sig = r.get("signal") or {}
            edge = r.get("edge") or {}
            jev = r.get("jev") or {}
            if _strict_score(sig) != 4:
                r["adaptive_learner"] = {"applies":False,"state":"NOT_APPLICABLE","reason":"not_strict_4of4"}
                continue
            if not bool(edge.get("passed")) or str(jev.get("verdict") or "").upper() != "APPROVE":
                r["adaptive_learner"] = {"applies":False,"state":"NOT_APPLICABLE","reason":"prerequisite_not_passed"}
                continue

            p = _predict_one(rep, r)
            edge_pct = _num(edge.get("net_edge_pct"))
            edge_t = float(champion["edge_threshold_pct"])
            prob_t = float(champion["ml_probability_threshold"])
            checked += 1
            ok = p is not None and edge_pct is not None and edge_pct >= edge_t and p >= prob_t
            info = {
                "applies":True,"state":"PASS" if ok else "HOLD",
                "reason":"adaptive_learner_pass" if ok else "adaptive_learner_champion_filter",
                "ml_win_probability":p,
                "required_probability":prob_t,
                "candidate_edge_pct":edge_pct,
                "required_edge_pct":edge_t,
                "source_n":rep.get("source_n"),
                "holdout":champion.get("holdout"),
            }
            r["adaptive_learner"] = info
            if ok:
                passed += 1
            else:
                blocked += 1
                r["action"] = "DROP"
                r["reason"] = "adaptive_learner_champion_filter"
                reasons = list(r.get("guard_reasons") or [])
                msg = f"ADAPTIVE ML: p={float(p or 0):.3f}/{prob_t:.2f} edge={float(edge_pct or 0):+.3f}%/{edge_t:.2f}%"
                if msg not in reasons:
                    reasons.append(msg)
                r["guard_reasons"] = reasons
        except Exception as exc:
            # Fail open: Evidence Gate remains the authoritative safety gate.
            r["adaptive_learner"] = {
                "applies":False,"state":"ERROR","reason":"adaptive_learner_error",
                "error":f"{type(exc).__name__}: {exc}",
            }

    return {"status":"ok","state":rep.get("state"),"checked":checked,"blocked":blocked,"passed":passed,"champion":champion}


def _status_from_snapshot() -> dict:
    """Read only the newest learner snapshot; never rebuild the ML model."""
    if not os.path.exists(DB_PATH):
        return {
            "enabled": ENABLED,
            "mode": "SHADOW_CHAMPION_CHALLENGER",
            "state": "WARMING",
            "source_n": 0,
            "champion": None,
            "status_source": "no_snapshot_db",
        }
    try:
        con = sqlite3.connect(DB_PATH, timeout=0.25)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute(
                "SELECT source_closed_n,state,champion_json FROM learner_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            con.close()
        if not row:
            return {
                "enabled": ENABLED,
                "mode": "SHADOW_CHAMPION_CHALLENGER",
                "state": "WARMING",
                "source_n": 0,
                "champion": None,
                "status_source": "empty_snapshot_db",
            }
        try:
            champ = json.loads(row["champion_json"]) if row["champion_json"] else None
        except Exception:
            champ = None
        return {
            "enabled": ENABLED,
            "mode": "SHADOW_CHAMPION_CHALLENGER",
            "state": str(row["state"] or "UNKNOWN"),
            "source_n": int(row["source_closed_n"] or 0),
            "champion": champ,
            "status_source": "snapshot",
        }
    except Exception as exc:
        return {
            "enabled": ENABLED,
            "mode": "SHADOW_CHAMPION_CHALLENGER",
            "state": "UNKNOWN",
            "source_n": 0,
            "champion": None,
            "status_source": "snapshot_error",
            "status_error": f"{type(exc).__name__}: {exc}",
        }


def status() -> dict:
    """Lightweight health/status path.

    Never calls report() and therefore never scans the risk database or trains
    logistic challengers. Full learner evaluation remains in report()/apply_results().
    """
    with _LOCK:
        rep = _CACHE.get("report")
        cache_ts = float(_CACHE.get("ts") or 0.0)

    if isinstance(rep, dict):
        base = {
            "enabled": bool(rep.get("enabled", ENABLED)),
            "mode": rep.get("mode","SHADOW_CHAMPION_CHALLENGER"),
            "state": rep.get("state","UNKNOWN"),
            "source_n": int(rep.get("source_n") or 0),
            "champion": rep.get("champion"),
            "status_source": "memory_cache",
            "cache_age_sec": max(0.0, time.time() - cache_ts) if cache_ts else None,
        }
    else:
        base = _status_from_snapshot()
        base["cache_age_sec"] = None

    champ = base.get("champion")
    return {
        "enabled": bool(base.get("enabled", ENABLED)),
        "mode": base.get("mode","SHADOW_CHAMPION_CHALLENGER"),
        "state": base.get("state","UNKNOWN"),
        "source_n": int(base.get("source_n") or 0),
        "champion":{
            "edge_threshold_pct":champ.get("edge_threshold_pct"),
            "ml_probability_threshold":champ.get("ml_probability_threshold"),
            "holdout_n":(champ.get("holdout") or {}).get("n"),
            "holdout_avg_net_pct":(champ.get("holdout") or {}).get("avg_net_pct"),
            "holdout_profit_factor":(champ.get("holdout") or {}).get("profit_factor"),
        } if isinstance(champ, dict) else None,
        "status_source": base.get("status_source"),
        "cache_age_sec": base.get("cache_age_sec"),
        "status_error": base.get("status_error"),
        "db_path":DB_PATH,
        "risk_db_path":RISK_DB_PATH,
        "live_execution":False,
    }


def recent_snapshots(limit: int = 20) -> list[dict]:
    init()
    n = max(1, min(100, int(limit)))
    with _LOCK, _conn() as con:
        rows = con.execute(
            "SELECT id,created_at,source_closed_n,state,champion_json FROM learner_snapshots ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
    out = []
    for r in rows:
        try:
            champ = json.loads(r["champion_json"]) if r["champion_json"] else None
        except Exception:
            champ = None
        out.append({
            "id":int(r["id"]),"created_at":float(r["created_at"]),
            "source_closed_n":int(r["source_closed_n"]),"state":str(r["state"]),
            "champion":champ,
        })
    return out

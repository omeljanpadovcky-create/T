"""MYSHKA / ASTRA — RESCUE MATRIX V2.3 JEV SCHEMA (FORWARD SHADOW ONLY).

Goal:
- freeze PAPER/trading decisions;
- analyze JEV APPROVE x TECH 3/4 first;
- derive movement-cluster IDs by pair+side+time-gap (not fixed 5m buckets);
- rank positive and toxic intersections using cluster-aware metrics;
- keep all findings diagnostic only;
- when a cluster first reaches WATCH, freeze a watch start and require NEW
  forward clusters before any confirmation state.

Reads:
- Forward Experiment Lab DB for 5m/10m/15m outcomes.
- Risk/decision blackbox DB only to enrich JEV/regime/Evidence fields.

Never changes ENTER/DROP, PAPER execution, sizing, routing, JEV, Guard,
Evidence Gate, ML, or LIVE.
"""
from __future__ import annotations

from contextlib import contextmanager
from itertools import combinations
from bisect import bisect_left
import hashlib
import json
import math
import os
import sqlite3
import statistics
import time
from typing import Any, Optional

FORWARD_DB_PATH = os.getenv("FORWARD_EXPERIMENT_DB_PATH", "/data/myshka_forward_experiments.sqlite3")
RISK_DB_PATH = os.getenv("RISK_INTELLIGENCE_DB_PATH", "/data/myshka_risk_intelligence.sqlite3")
DB_PATH = os.getenv("RESCUE_MATRIX_DB_PATH", "/data/myshka_rescue_matrix.sqlite3")

MOVEMENT_GAP_SEC = max(60, int(os.getenv("RESCUE_MATRIX_MOVEMENT_GAP_SEC", "180")))
JOIN_TOLERANCE_SEC = max(15, int(os.getenv("RESCUE_MATRIX_JOIN_TOLERANCE_SEC", "90")))
MAX_ROWS = max(500, int(os.getenv("RESCUE_MATRIX_MAX_ROWS", "20000")))
REPORT_CACHE_TTL_SEC = max(2, int(os.getenv("RESCUE_MATRIX_REPORT_CACHE_TTL_SEC", "20")))
_REPORT_CACHE: dict[str, Any] = {"at": 0.0, "value": None}

WATCH_MIN_CN = max(10, int(os.getenv("RESCUE_MATRIX_WATCH_MIN_CN", "30")))
WATCH_CONFIRM_NEW_CN = max(10, int(os.getenv("RESCUE_MATRIX_WATCH_CONFIRM_NEW_CN", "30")))
CANDIDATE_MIN_CN = max(WATCH_MIN_CN, int(os.getenv("RESCUE_MATRIX_CANDIDATE_MIN_CN", "50")))
ROBUST_MIN_CN = max(CANDIDATE_MIN_CN, int(os.getenv("RESCUE_MATRIX_ROBUST_MIN_CN", "100")))
WATCH_MIN_PF = float(os.getenv("RESCUE_MATRIX_WATCH_MIN_PF", "1.10"))
CANDIDATE_MIN_PF = float(os.getenv("RESCUE_MATRIX_CANDIDATE_MIN_PF", "1.20"))

HORIZON_LABELS = {300: "5m", 600: "10m", 900: "15m"}
BASE_DIMS = ("edge_band", "regime", "xcheck", "evidence", "pair", "direction")


def _conn(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    if path == DB_PATH:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    return con


@contextmanager
def _db(path: str):
    con = _conn(path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init() -> dict:
    with _db(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS rescue_meta(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS rescue_watchlist(
                signature TEXT PRIMARY KEY,
                horizon_sec INTEGER NOT NULL,
                dimensions_json TEXT NOT NULL,
                values_json TEXT NOT NULL,
                watch_started_at REAL NOT NULL,
                baseline_cn INTEGER NOT NULL,
                baseline_avg_net_pct REAL NOT NULL,
                baseline_pf REAL NOT NULL,
                state TEXT NOT NULL DEFAULT 'WATCH',
                last_seen_at REAL NOT NULL
            )
        """)
        row = con.execute("SELECT value FROM rescue_meta WHERE key='v2_started_at'").fetchone()
        if not row:
            con.execute(
                "INSERT INTO rescue_meta(key,value) VALUES('v2_started_at',?)",
                (str(time.time()),),
            )
    return {
        "enabled": True,
        "mode": "RESCUE_MATRIX_V2_FORWARD_SHADOW_ONLY",
        "db_path": DB_PATH,
        "forward_db_path": FORWARD_DB_PATH,
        "risk_db_path": RISK_DB_PATH,
        "movement_cluster_gap_sec": MOVEMENT_GAP_SEC,
        "changes_paper_execution": False,
        "changes_trading_decisions": False,
        "live_execution": False,
    }


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _pf(vals: list[float]) -> float:
    pos = sum(x for x in vals if x > 0)
    neg = abs(sum(x for x in vals if x <= 0))
    return pos / neg if neg > 1e-12 else (999.0 if pos > 0 else 0.0)


def _edge_band(v: Any) -> str:
    x = _num(v)
    if x is None:
        return "NO_EDGE"
    if x < 0.05:
        return "<0.05"
    if x < 0.08:
        return "0.05-0.08"
    if x < 0.10:
        return "0.08-0.10"
    if x < 0.12:
        return "0.10-0.12"
    if x < 0.15:
        return "0.12-0.15"
    if x < 0.20:
        return "0.15-0.20"
    if x < 0.35:
        return "0.20-0.35"
    return ">=0.35"


def _normalize_pair(v: Any) -> str:
    s = str(v or "").upper()
    return s.replace("/USDT:USDT", "").replace("USDT:USDT", "").strip()


def _load_forward() -> tuple[list[dict], float]:
    if not os.path.exists(FORWARD_DB_PATH):
        return [], time.time()
    with _db(FORWARD_DB_PATH) as con:
        start_row = con.execute(
            "SELECT value FROM experiment_meta WHERE key='forward_started_at'"
        ).fetchone()
        started = float(start_row["value"]) if start_row else 0.0
        rows = [
            dict(r) for r in con.execute(
                """SELECT * FROM forward_outcomes
                   WHERE status='CLOSED' AND net_pct IS NOT NULL
                     AND opened_at>=?
                   ORDER BY opened_at,id
                   LIMIT ?""",
                (started, MAX_ROWS),
            ).fetchall()
        ]
    return rows, started


def _load_risk_candidates() -> dict[str, list[dict]]:
    if not os.path.exists(RISK_DB_PATH):
        return {}
    try:
        with _db(RISK_DB_PATH) as con:
            rows = [
                dict(r) for r in con.execute(
                    """SELECT * FROM risk_candidates
                       ORDER BY opened_at,id LIMIT ?""",
                    (MAX_ROWS * 2,),
                ).fetchall()
            ]
        grouped: dict[str, list[dict]] = {}
        for r in rows:
            grouped.setdefault(str(r.get("pair") or ""), []).append(r)
        out = {}
        for pair, arr in grouped.items():
            arr.sort(key=lambda x: float(x.get("opened_at") or 0))
            out[pair] = {
                "times": [float(x.get("opened_at") or 0) for x in arr],
                "rows": arr,
            }
        return out
    except Exception:
        return {}


def _load_blackbox() -> dict[str, list[dict]]:
    if not os.path.exists(RISK_DB_PATH):
        return {}
    try:
        with _db(RISK_DB_PATH) as con:
            rows = [
                dict(r) for r in con.execute(
                    """SELECT id,pair,observed_at,direction,tech_score,edge_pct,jev_verdict,
                              action,reason,stage_json,raw_json
                       FROM decision_blackbox
                       ORDER BY observed_at,id LIMIT ?""",
                    (MAX_ROWS * 3,),
                ).fetchall()
            ]
        grouped: dict[str, list[dict]] = {}
        for r in rows:
            try:
                r["stage"] = json.loads(r.get("stage_json") or "{}")
            except Exception:
                r["stage"] = {}
            try:
                r["raw"] = json.loads(r.get("raw_json") or "{}")
            except Exception:
                r["raw"] = {}
            grouped.setdefault(str(r.get("pair") or ""), []).append(r)
        out = {}
        for pair, arr in grouped.items():
            arr.sort(key=lambda x: float(x.get("observed_at") or 0))
            out[pair] = {
                "times": [float(x.get("observed_at") or 0) for x in arr],
                "rows": arr,
            }
        return out
    except Exception:
        return {}


def _nearest(row: dict, by_pair: dict, time_field: str) -> Optional[dict]:
    """Nearest time join using a per-pair binary-search index.

    Only rows inside JOIN_TOLERANCE_SEC are inspected, avoiding the previous
    O(forward_rows × history_rows) full scan.
    """
    pair = str(row.get("pair") or "")
    pack = by_pair.get(pair)
    if not pack:
        return None
    arr = pack.get("rows") or []
    times = pack.get("times") or []
    if not arr or not times:
        return None

    t = float(row.get("opened_at") or 0)
    side = str(row.get("side") or "").upper()
    pos = bisect_left(times, t)
    best = None
    best_dt = 1e99

    i = pos - 1
    while i >= 0:
        dt = t - times[i]
        if dt > JOIN_TOLERANCE_SEC:
            break
        x = arr[i]
        d = str(x.get("direction") or x.get("side") or "").upper()
        if not (side in {"LONG", "SHORT"} and d in {"LONG", "SHORT"} and side != d):
            if dt < best_dt:
                best, best_dt = x, dt
        i -= 1

    i = pos
    while i < len(arr):
        dt = times[i] - t
        if dt > JOIN_TOLERANCE_SEC:
            break
        x = arr[i]
        d = str(x.get("direction") or x.get("side") or "").upper()
        if not (side in {"LONG", "SHORT"} and d in {"LONG", "SHORT"} and side != d):
            if dt < best_dt:
                best, best_dt = x, dt
        i += 1

    return best

def _normalize_jev_value(v: Any) -> str:
    if isinstance(v, bool):
        return "APPROVE" if v else "REJECT"
    s = str(v or "").strip().upper()
    if not s:
        return ""
    if s in {"APPROVE","APPROVED","PASS","PASSED","ENTER","ALLOW","ALLOWED","GO","YES","TRUE"}:
        return "APPROVE"
    if s in {"REJECT","REJECTED","DROP","BLOCK","BLOCKED","DENY","DENIED","NO","FALSE"}:
        return "REJECT"
    if s in {"WAIT","HOLD","NEUTRAL","SKIP","PENDING","NONE","NO_DATA","N/A"}:
        return "WAIT"
    return s


def _extract_jev(obj: Any) -> tuple[str, str, list[str], dict]:
    """Return normalized verdict, source-key, visible keys and compact sample."""
    if not isinstance(obj, dict):
        return "", "", [], {}
    keys = [str(k) for k in obj.keys()]
    sample = {}
    for k in keys[:12]:
        v = obj.get(k)
        if isinstance(v, (str, int, float, bool)) or v is None:
            sample[k] = v
    for key in ("verdict","decision","state","action","result","label","recommendation","approved","passed"):
        if key in obj:
            n = _normalize_jev_value(obj.get(key))
            if n:
                return n, key, keys, sample
    return "", "", keys, sample


def _evidence_state(stage: dict, raw: dict) -> str:
    e = (stage or {}).get("evidence_gate")
    if not isinstance(e, dict):
        e = raw.get("evidence_gate") if isinstance(raw.get("evidence_gate"), dict) else {}
    state = str(e.get("state") or "").upper()
    passed = e.get("passed")
    applies = e.get("applies")
    reason = str(e.get("reason") or "").upper()
    if passed is True or state in {"PASS", "APPROVE", "READY"}:
        return "PASS"
    if state in {"FAIL", "HOLD", "DROP", "REJECT", "BLOCK"}:
        return state
    if passed is False and applies is True:
        return "HOLD"
    if applies is False:
        return "NOT_APPLICABLE"
    if any(x in reason for x in ("HOLD", "DROP", "REJECT", "BLOCK")):
        return "HOLD"
    return "NO_DATA"


def _enrich(rows: list[dict]) -> tuple[list[dict], dict]:
    risks = _load_risk_candidates()
    blackbox = _load_blackbox()
    out = []
    risk_joined = 0
    blackbox_joined = 0

    for base in rows:
        r = dict(base)
        risk = _nearest(r, risks, "opened_at")
        box = _nearest(r, blackbox, "observed_at")
        if risk:
            risk_joined += 1
        if box:
            blackbox_joined += 1

        stage = (box or {}).get("stage") or {}
        raw = (box or {}).get("raw") or {}

        regime = str(
            (risk or {}).get("regime")
            or ((stage.get("context") or {}).get("regime") if isinstance(stage.get("context"), dict) else None)
            or r.get("structure")
            or "UNKNOWN"
        ).upper()

        stage_jev = stage.get("jev") if isinstance(stage.get("jev"), dict) else {}
        raw_jev = raw.get("jev") if isinstance(raw.get("jev"), dict) else {}
        stage_norm, stage_key, stage_keys, stage_sample = _extract_jev(stage_jev)
        raw_norm, raw_key, raw_keys, raw_sample = _extract_jev(raw_jev)

        risk_norm = _normalize_jev_value((risk or {}).get("jev_verdict"))
        box_norm = _normalize_jev_value((box or {}).get("jev_verdict"))
        # Historical direct columns may contain the recorder fallback WAIT even
        # when raw_json has a more specific JEV field. Prefer explicit raw/stage
        # verdicts over a fallback WAIT.
        jev = (
            raw_norm
            or stage_norm
            or (risk_norm if risk_norm not in {"", "WAIT"} else "")
            or (box_norm if box_norm not in {"", "WAIT"} else "")
            or risk_norm
            or box_norm
            or "UNKNOWN"
        )
        evidence = _evidence_state(stage, raw)

        r.update({
            "pair_norm": _normalize_pair(r.get("pair")),
            "direction": str(r.get("side") or "UNKNOWN").upper(),
            "tech": f"{int(r.get('tech_score') or 0)}/4",
            "edge_band": _edge_band(r.get("edge_pct")),
            "regime": regime,
            "jev": jev,
            "xcheck": str(r.get("xcheck_state") or "NO_DATA").upper(),
            "evidence": evidence,
            "jev_source": (
                ("blackbox_raw."+raw_key) if raw_norm
                else ("blackbox_stage."+stage_key) if stage_norm
                else "risk_candidate" if (risk or {}).get("jev_verdict") is not None
                else "blackbox_column" if (box or {}).get("jev_verdict") is not None
                else "missing"
            ),
            "raw_jev_present": bool(raw_jev),
            "stage_jev_present": bool(stage_jev),
            "raw_jev_keys": raw_keys,
            "stage_jev_keys": stage_keys,
            "raw_jev_sample": raw_sample,
            "stage_jev_sample": stage_sample,
        })
        r["pair"] = r["pair_norm"]
        out.append(r)

    total = len(out)
    coverage = {
        "rows": total,
        "risk_joined": risk_joined,
        "blackbox_joined": blackbox_joined,
        "risk_join_pct": risk_joined / total * 100.0 if total else 0.0,
        "blackbox_join_pct": blackbox_joined / total * 100.0 if total else 0.0,
    }
    return out, coverage


def _assign_movement_clusters(rows: list[dict]) -> list[dict]:
    """Assign episode clusters by pair+side and gap from prior candidate.

    This intentionally ignores the legacy fixed cluster_bucket. A candidate that
    crosses a 5-minute wall-clock boundary remains in the same movement episode
    when the time gap is <= MOVEMENT_GAP_SEC.
    """
    grouped: dict[tuple[str, str, int], list[dict]] = {}
    for r in rows:
        key = (
            str(r.get("pair") or ""),
            str(r.get("direction") or ""),
            int(r.get("horizon_sec") or 0),
        )
        grouped.setdefault(key, []).append(r)

    out: list[dict] = []
    for (pair, side, horizon), arr in grouped.items():
        arr.sort(key=lambda x: (float(x.get("opened_at") or 0), int(x.get("id") or 0)))
        episode = 0
        prev_t: Optional[float] = None
        episode_anchor = 0
        for r0 in arr:
            r = dict(r0)
            t = float(r.get("opened_at") or 0)
            if prev_t is None or (t - prev_t) > MOVEMENT_GAP_SEC:
                episode += 1
                episode_anchor = int(t)
            prev_t = t
            raw = f"{pair}|{side}|{horizon}|{episode}|{episode_anchor}"
            r["movement_cluster_id"] = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
            r["movement_episode"] = episode
            out.append(r)
    return out


def _cluster_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for r in sorted(rows, key=lambda x: (float(x.get("opened_at") or 0), int(x.get("id") or 0))):
        k = str(r.get("movement_cluster_id") or "")
        if not k:
            continue
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _rolling_positive_blocks(clustered: list[dict], blocks: int = 3) -> int:
    if len(clustered) < 9:
        return 0
    arr = sorted(clustered, key=lambda x: float(x.get("opened_at") or 0))
    positive = 0
    for i in range(blocks):
        lo = int(len(arr) * i / blocks)
        hi = int(len(arr) * (i + 1) / blocks)
        vals = [float(x["net_pct"]) for x in arr[lo:hi] if _num(x.get("net_pct")) is not None]
        if vals and sum(vals) / len(vals) > 0 and _pf(vals) > 1.0:
            positive += 1
    return positive


def _metrics(rows: list[dict]) -> dict:
    raw_vals = [float(r["net_pct"]) for r in rows if _num(r.get("net_pct")) is not None]
    cl_rows = _cluster_rows(rows)
    vals = [float(r["net_pct"]) for r in cl_rows if _num(r.get("net_pct")) is not None]
    raw_n = len(raw_vals)
    cn = len(vals)
    wins = sum(1 for x in vals if x > 0)

    pair_sums: dict[str, list[float]] = {}
    regime_sums: dict[str, list[float]] = {}
    for r in cl_rows:
        x = _num(r.get("net_pct"))
        if x is None:
            continue
        pair_sums.setdefault(str(r.get("pair") or ""), []).append(float(x))
        regime_sums.setdefault(str(r.get("regime") or "UNKNOWN"), []).append(float(x))

    return {
        "raw_n": raw_n,
        "cn": cn,
        "win_rate_pct": wins / cn * 100.0 if cn else 0.0,
        "avg_net_pct": sum(vals) / cn if cn else 0.0,
        "profit_factor": _pf(vals),
        "total_net_pct": sum(vals),
        "median_net_pct": statistics.median(vals) if vals else 0.0,
        "best_net_pct": max(vals) if vals else 0.0,
        "worst_net_pct": min(vals) if vals else 0.0,
        "positive_pairs": sum(1 for q in pair_sums.values() if sum(q) / len(q) > 0),
        "pair_count": len(pair_sums),
        "positive_regimes": sum(1 for q in regime_sums.values() if sum(q) / len(q) > 0),
        "regime_count": len(regime_sums),
        "rolling_positive_blocks": _rolling_positive_blocks(cl_rows),
    }


def _status_from_metrics(m: dict) -> str:
    cn = int(m.get("cn") or 0)
    avg = float(m.get("avg_net_pct") or 0)
    pf = float(m.get("profit_factor") or 0)
    roll = int(m.get("rolling_positive_blocks") or 0)

    if cn < 10:
        return "NOISE"
    if avg <= 0 or pf <= 1.0:
        return "TOXIC" if avg < 0 else "DISCOVERY"
    if cn < WATCH_MIN_CN:
        return "DISCOVERY"
    if cn < CANDIDATE_MIN_CN or pf < CANDIDATE_MIN_PF:
        return "WATCH"
    if cn < ROBUST_MIN_CN:
        return "CANDIDATE"
    if roll >= 2:
        return "ROBUST_CANDIDATE"
    return "CANDIDATE"


def _signature(horizon: int, dims: tuple[str, ...], vals: tuple[str, ...]) -> str:
    blob = json.dumps([int(horizon), list(dims), list(vals)], separators=(",", ":"), sort_keys=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def _watch_state(horizon: int, dims: tuple[str, ...], vals: tuple[str, ...], rows: list[dict], m: dict) -> dict:
    sig = _signature(horizon, dims, vals)
    now = time.time()
    state = _status_from_metrics(m)

    # Most matrix cells are tiny. Never open SQLite for cells that cannot yet
    # have reached WATCH. This keeps report() analytical instead of write-heavy.
    if int(m.get("cn") or 0) < WATCH_MIN_CN:
        return {
            "signature": sig,
            "watch_state": state,
            "new_cn_since_watch": 0,
            "forward_confirm_avg_net_pct": 0.0,
            "forward_confirm_pf": 0.0,
        }

    with _db(DB_PATH) as con:
        row = con.execute("SELECT * FROM rescue_watchlist WHERE signature=?", (sig,)).fetchone()

        eligible_watch = (
            int(m.get("cn") or 0) >= WATCH_MIN_CN
            and float(m.get("avg_net_pct") or 0) > 0
            and float(m.get("profit_factor") or 0) >= WATCH_MIN_PF
        )

        if row is None and eligible_watch:
            con.execute(
                """INSERT INTO rescue_watchlist(
                     signature,horizon_sec,dimensions_json,values_json,watch_started_at,
                     baseline_cn,baseline_avg_net_pct,baseline_pf,state,last_seen_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    sig, int(horizon), json.dumps(list(dims)), json.dumps(list(vals)),
                    now, int(m["cn"]), float(m["avg_net_pct"]), float(m["profit_factor"]),
                    "WATCH", now,
                ),
            )
            return {
                "signature": sig,
                "watch_state": "WATCH",
                "new_cn_since_watch": 0,
                "forward_confirm_avg_net_pct": 0.0,
                "forward_confirm_pf": 0.0,
            }

        if row is None:
            return {
                "signature": sig,
                "watch_state": state,
                "new_cn_since_watch": 0,
                "forward_confirm_avg_net_pct": 0.0,
                "forward_confirm_pf": 0.0,
            }

        watch_started = float(row["watch_started_at"])
        new_rows = [x for x in rows if float(x.get("opened_at") or 0) > watch_started]
        newm = _metrics(new_rows)
        new_cn = int(newm.get("cn") or 0)
        stored_state = str(row["state"])

        if new_cn >= WATCH_CONFIRM_NEW_CN:
            if float(newm.get("avg_net_pct") or 0) > 0 and float(newm.get("profit_factor") or 0) >= WATCH_MIN_PF:
                stored_state = "FORWARD_CONFIRMED"
            else:
                stored_state = "WATCH_FAILED"

        con.execute(
            "UPDATE rescue_watchlist SET state=?,last_seen_at=? WHERE signature=?",
            (stored_state, now, sig),
        )

        return {
            "signature": sig,
            "watch_state": stored_state,
            "watch_started_at": watch_started,
            "baseline_cn": int(row["baseline_cn"]),
            "new_cn_since_watch": new_cn,
            "required_new_cn": WATCH_CONFIRM_NEW_CN,
            "forward_confirm_avg_net_pct": float(newm.get("avg_net_pct") or 0),
            "forward_confirm_pf": float(newm.get("profit_factor") or 0),
        }


def _group(rows: list[dict], dims: tuple[str, ...], horizon: int) -> list[dict]:
    groups: dict[tuple[str, ...], list[dict]] = {}
    for r in rows:
        key = tuple(str(r.get(d) or "UNKNOWN") for d in dims)
        groups.setdefault(key, []).append(r)

    out = []
    for vals, q in groups.items():
        m = _metrics(q)
        watch = _watch_state(horizon, dims, vals, q, m)
        out.append({
            "level": len(dims),
            "dimensions": list(dims),
            "values": {d: v for d, v in zip(dims, vals)},
            **m,
            "status": _status_from_metrics(m),
            **watch,
        })
    return out


def _count_values(rows: list[dict], field: str) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get(field) or "UNKNOWN")
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _attribution_funnel(rows: list[dict]) -> dict:
    all_n = len(rows)
    jev_approve = [r for r in rows if str(r.get("jev") or "") == "APPROVE"]
    tech3 = [r for r in rows if str(r.get("tech") or "") == "3/4"]
    both = [r for r in jev_approve if str(r.get("tech") or "") == "3/4"]
    return {
        "all_raw_n": all_n,
        "jev_approve_raw_n": len(jev_approve),
        "tech3_raw_n": len(tech3),
        "jev_approve_x_tech3_raw_n": len(both),
        "jev_distribution": _count_values(rows, "jev"),
        "tech_distribution": _count_values(rows, "tech"),
        "jev_source_distribution": _count_values(rows, "jev_source"),
        "risk_joined_rows": sum(1 for r in rows if str(r.get("jev_source") or "") == "risk_candidate"),
        "blackbox_jev_rows": sum(1 for r in rows if str(r.get("jev_source") or "").startswith("blackbox")),
        "missing_jev_rows": sum(1 for r in rows if str(r.get("jev") or "") in {"", "UNKNOWN"}),
        "raw_jev_present_rows": sum(1 for r in rows if bool(r.get("raw_jev_present"))),
        "stage_jev_present_rows": sum(1 for r in rows if bool(r.get("stage_jev_present"))),
        "raw_jev_key_sets": _count_values([
            {"v": ",".join(r.get("raw_jev_keys") or []) or "NONE"} for r in rows
        ], "v"),
        "stage_jev_key_sets": _count_values([
            {"v": ",".join(r.get("stage_jev_keys") or []) or "NONE"} for r in rows
        ], "v"),
        "raw_jev_examples": [
            r.get("raw_jev_sample") for r in rows
            if r.get("raw_jev_sample")
        ][:5],
        "stage_jev_examples": [
            r.get("stage_jev_sample") for r in rows
            if r.get("stage_jev_sample")
        ][:5],
    }


def _rank(rows: list[dict], horizon: int) -> dict:
    # Primary hypothesis exactly as requested:
    # JEV APPROVE x TECH 3/4, then drill through EDGE/regime/XCheck/Evidence,
    # with pair added after the first broad cuts.
    anchor = [
        r for r in rows
        if str(r.get("jev") or "") == "APPROVE"
        and str(r.get("tech") or "") == "3/4"
    ]

    level1: list[dict] = []
    level2: list[dict] = []
    level3: list[dict] = []

    first_dims = ("edge_band", "regime", "xcheck", "evidence")
    for d in first_dims:
        level1.extend(_group(anchor, (d,), horizon))
    for dims in combinations(first_dims, 2):
        level2.extend(_group(anchor, tuple(dims), horizon))
    for dims in combinations(first_dims, 3):
        level3.extend(_group(anchor, tuple(dims), horizon))

    # Add pair only after broad cohort analysis.
    pair_drilldowns = []
    for dims in (
        ("pair", "edge_band"),
        ("pair", "regime"),
        ("pair", "xcheck"),
        ("pair", "evidence"),
        ("pair", "regime", "edge_band"),
        ("pair", "edge_band", "xcheck"),
        ("pair", "regime", "xcheck"),
    ):
        pair_drilldowns.extend(_group(anchor, dims, horizon))

    all_items = level1 + level2 + level3 + pair_drilldowns

    positive = [
        x for x in all_items
        if int(x.get("cn") or 0) >= 5
        and float(x.get("avg_net_pct") or 0) > 0
        and float(x.get("profit_factor") or 0) > 1.0
    ]
    positive.sort(
        key=lambda x: (
            1 if str(x.get("watch_state")) == "FORWARD_CONFIRMED" else 0,
            int(x.get("cn") or 0),
            float(x.get("total_net_pct") or 0),
            float(x.get("profit_factor") or 0),
        ),
        reverse=True,
    )

    toxic = [
        x for x in all_items
        if int(x.get("cn") or 0) >= 5
        and float(x.get("avg_net_pct") or 0) < 0
    ]
    toxic.sort(
        key=lambda x: (
            int(x.get("cn") or 0),
            -float(x.get("total_net_pct") or 0),
            -float(x.get("avg_net_pct") or 0),
        ),
        reverse=True,
    )

    tech_compare = []
    approved = [r for r in rows if str(r.get("jev") or "") == "APPROVE"]
    for tech in ("3/4", "4/4"):
        q = [r for r in approved if str(r.get("tech") or "") == tech]
        tech_compare.append({"tech": tech, **_metrics(q)})

    return {
        "anchor": "JEV_APPROVE_x_TECH_3_OF_4",
        "attribution_funnel": _attribution_funnel(rows),
        "anchor_metrics": _metrics(anchor),
        "tech_3_vs_4": tech_compare,
        "level1": sorted(level1, key=lambda x: int(x.get("cn") or 0), reverse=True),
        "level2": sorted(level2, key=lambda x: int(x.get("cn") or 0), reverse=True)[:100],
        "level3": sorted(level3, key=lambda x: int(x.get("cn") or 0), reverse=True)[:100],
        "pair_drilldowns": sorted(pair_drilldowns, key=lambda x: int(x.get("cn") or 0), reverse=True)[:120],
        "top_positive_clusters": positive[:40],
        "top_toxic_clusters": toxic[:40],
    }


def report() -> dict:
    now = time.time()
    cached = _REPORT_CACHE.get("value")
    if cached is not None and now - float(_REPORT_CACHE.get("at") or 0) < REPORT_CACHE_TTL_SEC:
        return cached

    init()
    raw, started = _load_forward()
    enriched, coverage = _enrich(raw)
    enriched = _assign_movement_clusters(enriched)

    by_horizon = {}
    for horizon in sorted({int(r.get("horizon_sec") or 0) for r in enriched if int(r.get("horizon_sec") or 0) > 0}):
        part = [r for r in enriched if int(r.get("horizon_sec") or 0) == horizon]
        by_horizon[str(horizon)] = {
            "label": HORIZON_LABELS.get(horizon, f"{horizon}s"),
            "overall": _metrics(part),
            "rescue": _rank(part, horizon),
        }

    with _db(DB_PATH) as con:
        watch_counts = {
            str(r["state"]): int(r["n"])
            for r in con.execute(
                "SELECT state,COUNT(*) n FROM rescue_watchlist GROUP BY state"
            ).fetchall()
        }

    result = {
        "status": "ok",
        "mode": "RESCUE_MATRIX_V2_FORWARD_SHADOW_ONLY",
        "forward_started_at": started,
        "movement_cluster_gap_sec": MOVEMENT_GAP_SEC,
        "legacy_fixed_cluster_key_used_for_scoring": False,
        "performance_mode": "BINARY_JOIN_CACHE_JEV_SCHEMA_V2_3",
        "coverage": coverage,
        "by_horizon": by_horizon,
        "watchlist_counts": watch_counts,
        "policy": {
            "paper_frozen": True,
            "primary_anchor": "JEV APPROVE x TECH 3/4",
            "watch_min_cn": WATCH_MIN_CN,
            "watch_min_pf": WATCH_MIN_PF,
            "confirm_with_new_forward_cn": WATCH_CONFIRM_NEW_CN,
            "candidate_min_cn": CANDIDATE_MIN_CN,
            "candidate_min_pf": CANDIDATE_MIN_PF,
            "robust_min_cn": ROBUST_MIN_CN,
            "auto_gate": False,
            "auto_promotion": False,
            "historical_rule_mining_for_activation": False,
        },
        "status_meaning": {
            "NOISE": "cn < 10",
            "DISCOVERY": "interesting but too small",
            "WATCH": "positive cluster reached watch threshold; freeze and collect new forward clusters",
            "FORWARD_CONFIRMED": "WATCH survived the required number of new forward clusters",
            "WATCH_FAILED": "WATCH did not survive new forward confirmation",
            "CANDIDATE": "large positive cohort; still SHADOW only",
            "ROBUST_CANDIDATE": "large cohort with rolling stability; still manual review only",
            "TOXIC": "negative cluster-aware expectancy",
        },
        "changes_paper_execution": False,
        "changes_trading_decisions": False,
        "live_execution": False,
        "note": "No cluster is activated automatically, even with high PF. New forward evidence is mandatory after WATCH.",
    }
    _REPORT_CACHE["at"] = time.time()
    _REPORT_CACHE["value"] = result
    return result


def status() -> dict:
    init()
    with _db(DB_PATH) as con:
        started = con.execute("SELECT value FROM rescue_meta WHERE key='v2_started_at'").fetchone()
        watches = con.execute("SELECT COUNT(*) n FROM rescue_watchlist").fetchone()
    return {
        "enabled": True,
        "mode": "RESCUE_MATRIX_V2_FORWARD_SHADOW_ONLY",
        "db_path": DB_PATH,
        "forward_db_path": FORWARD_DB_PATH,
        "risk_db_path": RISK_DB_PATH,
        "v2_started_at": float(started["value"]) if started else None,
        "movement_cluster_gap_sec": MOVEMENT_GAP_SEC,
        "watchlist_size": int(watches["n"]) if watches else 0,
        "changes_paper_execution": False,
        "changes_trading_decisions": False,
        "live_execution": False,
    }

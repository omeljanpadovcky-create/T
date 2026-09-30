"""MYSHKA / ASTRA final hardening layer.

Diagnostics only. This module never creates, vetoes, sizes or routes trades.

Features:
- versioned config fingerprints
- scan/data-quality integrity checks
- PAPER engine <-> Analytics reconciliation
- optional read-only Bybit/Freqtrade integration snapshot reconciliation
- persistent diagnostic history

No market/exchange HTTP requests are made here. External integration snapshots
must be supplied explicitly by the API/UI when the user requests reconciliation.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import sqlite3
import threading
import time
from typing import Any, Optional

DB_PATH = os.getenv("HARDENING_DB_PATH", "/data/myshka_hardening.sqlite3")
ANALYTICS_DB_PATH = os.getenv("ANALYTICS_DB_PATH", "/data/myshka_analytics.sqlite3")
EXPECTED_UNIVERSE = max(1, int(os.getenv("HARDENING_EXPECTED_UNIVERSE", "15")))
CONTEXT_MAX_AGE_SEC = max(30, int(os.getenv("HARDENING_CONTEXT_MAX_AGE_SEC", "180")))
SUSPICIOUS_SPREAD_PCT = max(0.10, float(os.getenv("HARDENING_SUSPICIOUS_SPREAD_PCT", "1.0")))
_LOCK = threading.RLock()


def _conn(path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    if path == DB_PATH:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    return con


@contextmanager
def _db(path: str = DB_PATH):
    con = _conn(path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def init() -> dict:
    """Initialize Hardening storage without calling status().

    Important: this function must never call status(), because status() itself
    calls init(). The previous init()->status()->init() recursion could hang
    /hardening/status until the HTTP client timed out.
    """
    with _LOCK, _db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS config_versions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                version_label TEXT NOT NULL,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                snapshot_json TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS data_quality_samples(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observed_at REAL NOT NULL,
                result_count INTEGER NOT NULL,
                expected_universe INTEGER NOT NULL,
                ok_count INTEGER NOT NULL,
                total_count INTEGER NOT NULL,
                state TEXT NOT NULL,
                issues_json TEXT NOT NULL,
                checks_json TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS reconciliation_samples(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                observed_at REAL NOT NULL,
                state TEXT NOT NULL,
                issues_json TEXT NOT NULL,
                details_json TEXT NOT NULL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_hardening_dq_time ON data_quality_samples(observed_at DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_hardening_rec_time ON reconciliation_samples(observed_at DESC)")
    return {"status": "ok", "enabled": True, "mode": "DIAGNOSTIC_ONLY", "db_path": DB_PATH}


def _config_snapshot(results: list[dict], hint: Optional[dict]) -> dict:
    hint = dict(hint or {})
    edge_min = None
    for r in results:
        e = r.get("edge") or {}
        if e.get("min_required_net_edge_pct") is not None:
            edge_min = _num(e.get("min_required_net_edge_pct"))
            break
        t = r.get("training") or {}
        if t.get("strict_edge_min_pct") is not None:
            edge_min = _num(t.get("strict_edge_min_pct"))
            break
    snap = {
        "pipeline": "MYSHKA/ASTRA",
        "execution_mode": "PAPER",
        "universe_target": int(hint.get("universe_target") or EXPECTED_UNIVERSE),
        "timeframe": str(hint.get("timeframe") or "1m"),
        "candle_limit": int(hint.get("candle_limit") or 80),
        "scan_interval_sec": int(hint.get("scan_interval_sec") or 15),
        "review_horizon_sec": int(hint.get("review_horizon_sec") or 300),
        "strict_min_net_edge_pct": float(edge_min if edge_min is not None else hint.get("strict_min_net_edge_pct", 0.05)),
        "training_until_trades": hint.get("training_until_trades"),
        "training_min_tech_conditions": hint.get("training_min_tech_conditions"),
        "dynamic_costs": True,
        "private_execution": "READ_ONLY_PAPER",
        "risk_intelligence": "SHADOW",
    }
    for k, v in hint.items():
        if k not in snap and isinstance(v, (str, int, float, bool, type(None))):
            snap[k] = v
    return snap


def _record_config(snapshot: dict, now: float) -> dict:
    raw = _json(snapshot)
    fp = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    with _LOCK, _db() as con:
        row = con.execute("SELECT * FROM config_versions WHERE fingerprint=?", (fp,)).fetchone()
        if row:
            con.execute("UPDATE config_versions SET last_seen=? WHERE id=?", (now, int(row["id"])))
            return {"version": str(row["version_label"]), "fingerprint": fp, "snapshot": snapshot, "new": False}
        n = int(con.execute("SELECT COUNT(*) n FROM config_versions").fetchone()["n"])
        label = f"v1.{n}"
        con.execute(
            "INSERT INTO config_versions(fingerprint,version_label,first_seen,last_seen,snapshot_json) VALUES(?,?,?,?,?)",
            (fp, label, now, now, raw),
        )
        return {"version": label, "fingerprint": fp, "snapshot": snapshot, "new": True}


def _candle_ok(c: dict) -> bool:
    o, h, l, cl = (_num(c.get("open")), _num(c.get("high")), _num(c.get("low")), _num(c.get("close")))
    if None in (o, h, l, cl) or min(o, h, l, cl) <= 0:
        return False
    return h >= max(o, cl) and l <= min(o, cl) and h >= l


def _data_quality(results: list[dict], config: dict, now: Optional[float] = None) -> dict:
    now = float(now or time.time())
    pairs = [str(r.get("pair") or "") for r in results]
    expected = int(config.get("universe_target") or EXPECTED_UNIVERSE)
    candle_limit = int(config.get("candle_limit") or 80)
    checks = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("universe_count", len(results) == expected, f"{len(results)}/{expected}")
    missing_pairs = sum(1 for p in pairs if not p)
    add("pair_names", missing_pairs == 0, f"missing {missing_pairs}")
    dup = len([p for p in pairs if p]) - len(set(p for p in pairs if p))
    add("duplicate_pairs", dup == 0, f"duplicates {dup}")

    bad_price = bad_bidask = bad_spread = bad_candles = stale_ctx = time_drift = invariant = 0
    candle_seen = 0
    timestamp_seen = 0
    for r in results:
        m = r.get("market") or {}
        last = _num(m.get("last_price"))
        bid, ask = _num(m.get("bid")), _num(m.get("ask"))
        spread = _num(m.get("spread_pct"))
        if last is None or last <= 0:
            bad_price += 1
        if bid is not None or ask is not None:
            if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
                bad_bidask += 1
        if spread is not None and (spread < 0 or spread > SUSPICIOUS_SPREAD_PCT):
            bad_spread += 1

        candles = m.get("candles")
        if isinstance(candles, list):
            candle_seen += 1
            if len(candles) != candle_limit or any(not _candle_ok(x or {}) for x in candles):
                bad_candles += 1

        ctx = r.get("context") or {}
        if ctx:
            age = _num(ctx.get("age_sec"))
            latest_ts = _num(ctx.get("latest_ts"))
            if age is not None and age > CONTEXT_MAX_AGE_SEC:
                stale_ctx += 1
            if latest_ts is not None:
                timestamp_seen += 1
                computed_age = now - latest_ts
                if computed_age < -5.0:
                    time_drift += 1
                elif age is not None and abs(computed_age - age) > 10.0:
                    time_drift += 1

        edge = r.get("edge") or {}
        action = str(r.get("action") or "").upper()
        reason = str(r.get("reason") or "")
        if action == "ENTER" and edge and not bool(edge.get("passed")):
            invariant += 1
        if reason == "strict_edge_buffer" and edge and bool(edge.get("passed")):
            invariant += 1

    add("market_prices", bad_price == 0, f"bad {bad_price}")
    add("bid_ask_order", bad_bidask == 0, f"bad {bad_bidask}")
    add("spread_sanity", bad_spread == 0, f"suspicious {bad_spread}")
    add("candle_integrity", candle_seen == 0 or bad_candles == 0,
        "not supplied" if candle_seen == 0 else f"bad {bad_candles}/{candle_seen} · expected {candle_limit}")
    add("context_freshness", stale_ctx == 0, f"stale {stale_ctx}")
    add("timestamp_alignment", time_drift == 0,
        "not supplied" if timestamp_seen == 0 else f"drift {time_drift}/{timestamp_seen}")
    add("decision_invariants", invariant == 0, f"violations {invariant}")

    ok_n = sum(1 for x in checks if x["ok"])
    issues = [x for x in checks if not x["ok"]]
    return {
        "state": "OK" if not issues else "WARN",
        "ok_n": ok_n,
        "total": len(checks),
        "issues": issues,
        "checks": checks,
        "result_count": len(results),
        "expected_universe": expected,
    }


def observe_results(results: list[dict], config_snapshot: Optional[dict] = None, now: Optional[float] = None) -> dict:
    """Observe a normal scan. Never raises into the trading engine."""
    try:
        init()
        ts = float(now or time.time())
        rows = list(results or [])
        snap = _config_snapshot(rows, config_snapshot)
        ver = _record_config(snap, ts)
        dq = _data_quality(rows, snap, ts)
        with _LOCK, _db() as con:
            con.execute(
                """INSERT INTO data_quality_samples(
                    observed_at,result_count,expected_universe,ok_count,total_count,state,issues_json,checks_json
                ) VALUES(?,?,?,?,?,?,?,?)""",
                (
                    ts, dq["result_count"], dq["expected_universe"], dq["ok_n"], dq["total"],
                    dq["state"], _json(dq["issues"]), _json(dq["checks"]),
                ),
            )
            con.execute(
                "DELETE FROM data_quality_samples WHERE id NOT IN (SELECT id FROM data_quality_samples ORDER BY id DESC LIMIT 5000)"
            )
        return {"status": "ok", "config": ver, "data_quality": dq}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def _analytics_open() -> dict:
    if not os.path.exists(ANALYTICS_DB_PATH):
        return {"available": False, "pairs": [], "count": 0, "detail": "analytics DB missing"}
    try:
        with _db(ANALYTICS_DB_PATH) as con:
            rows = con.execute("SELECT pair,side,opened_at FROM analytics_trades WHERE status='OPEN'").fetchall()
        return {"available": True, "pairs": sorted(str(x["pair"]) for x in rows), "count": len(rows)}
    except Exception as exc:
        return {"available": False, "pairs": [], "count": 0, "detail": f"{type(exc).__name__}: {exc}"}


def _integration_reconcile(integrations: Optional[dict]) -> list[dict]:
    if integrations is None:
        return [
            {"name": "bybit_private", "state": "UNVERIFIED", "detail": "manual reconciliation not requested"},
            {"name": "freqtrade_authority", "state": "UNVERIFIED", "detail": "manual reconciliation not requested"},
        ]
    b = integrations.get("bybit_account") or {}
    f = integrations.get("freqtrade") or {}
    out = []

    b_status = str(b.get("status") or "unknown").lower()
    ro = b.get("read_only")
    if ro is None:
        ro = b.get("readOnly")
    b_ok = b_status in {"ok", "active", "configured", "live"}
    if b_ok and ro in (1, True, "1", "true", "True"):
        out.append({"name": "bybit_private", "state": "OK", "detail": "connected · READ ONLY"})
    elif b_ok and ro is None:
        out.append({"name": "bybit_private", "state": "UNVERIFIED", "detail": "connected · read-only flag unavailable"})
    elif b_ok:
        out.append({"name": "bybit_private", "state": "WARN", "detail": "connected but READ ONLY not confirmed"})
    else:
        out.append({"name": "bybit_private", "state": "WARN", "detail": f"status {b_status}"})

    f_status = str(f.get("status") or "unknown").lower()
    dry = f.get("dry_run")
    if dry is None:
        dry = f.get("dryRun")
    if dry is None:
        dry = f.get("dry_run_mode")
    f_ok = f_status in {"ok", "active", "configured", "live"}
    if f_ok and dry in (True, 1, "1", "true", "True"):
        out.append({"name": "freqtrade_authority", "state": "OK", "detail": "connected · DRY RUN"})
    elif f_ok and dry is None:
        out.append({"name": "freqtrade_authority", "state": "UNVERIFIED", "detail": "connected · dry-run flag unavailable"})
    elif f_ok:
        out.append({"name": "freqtrade_authority", "state": "WARN", "detail": "connected but dry-run not confirmed"})
    else:
        out.append({"name": "freqtrade_authority", "state": "WARN", "detail": f"status {f_status}"})
    return out


def reconcile(engine: Optional[dict], runtime: Optional[dict], integrations: Optional[dict] = None,
              now: Optional[float] = None) -> dict:
    ts = float(now or time.time())
    engine = dict(engine or {})
    runtime = dict(runtime or {})
    positions = engine.get("positions") or []
    paper_pairs = sorted(str(x.get("pair") or "") for x in positions if x.get("pair"))
    analytics = _analytics_open()
    checks = []

    checks.append({
        "name": "execution_mode",
        "state": "OK",
        "detail": "PAPER · no live-order routing from hardening layer",
    })

    equity = _num(engine.get("paper_equity"))
    checks.append({
        "name": "paper_equity",
        "state": "OK" if equity is not None and equity > 0 else "WARN",
        "detail": "—" if equity is None else f"{equity:.2f}",
    })

    if analytics["available"]:
        state = "OK" if paper_pairs == analytics["pairs"] else "WARN"
        checks.append({
            "name": "engine_vs_analytics_open",
            "state": state,
            "detail": f"engine {len(paper_pairs)} · analytics {analytics['count']}",
            "engine_pairs": paper_pairs,
            "analytics_pairs": analytics["pairs"],
        })
    else:
        checks.append({"name": "engine_vs_analytics_open", "state": "UNVERIFIED", "detail": analytics.get("detail", "unavailable")})

    checks.extend(_integration_reconcile(integrations))
    checks.append({
        "name": "runtime_controls",
        "state": "OK",
        "detail": f"kill={bool(runtime.get('kill_switch'))} · paused={bool(runtime.get('paused'))} · auto_scan={bool(runtime.get('auto_scan', True))}",
    })

    states = [x["state"] for x in checks]
    state = "WARN" if "WARN" in states else "UNVERIFIED" if "UNVERIFIED" in states else "OK"
    issues = [x for x in checks if x["state"] == "WARN"]
    details = {
        "execution_mode": "PAPER",
        "paper_positions": len(paper_pairs),
        "paper_pairs": paper_pairs,
        "analytics_open": analytics,
        "external_snapshot_supplied": integrations is not None,
        "checks": checks,
    }
    try:
        with _LOCK, _db() as con:
            con.execute(
                "INSERT INTO reconciliation_samples(observed_at,state,issues_json,details_json) VALUES(?,?,?,?)",
                (ts, state, _json(issues), _json(details)),
            )
            con.execute(
                "DELETE FROM reconciliation_samples WHERE id NOT IN (SELECT id FROM reconciliation_samples ORDER BY id DESC LIMIT 1000)"
            )
    except Exception:
        pass
    return {"state": state, "issues": issues, **details}


def _latest_quality() -> Optional[dict]:
    init()
    with _LOCK, _db() as con:
        r = con.execute("SELECT * FROM data_quality_samples ORDER BY observed_at DESC LIMIT 1").fetchone()
    if not r:
        return None
    try:
        issues = json.loads(r["issues_json"] or "[]")
        checks = json.loads(r["checks_json"] or "[]")
    except Exception:
        issues, checks = [], []
    return {
        "observed_at": float(r["observed_at"]), "state": str(r["state"]),
        "ok_n": int(r["ok_count"]), "total": int(r["total_count"]),
        "result_count": int(r["result_count"]), "expected_universe": int(r["expected_universe"]),
        "issues": issues, "checks": checks,
    }


def _config_history(limit: int = 8) -> list[dict]:
    init()
    with _LOCK, _db() as con:
        rows = con.execute("SELECT * FROM config_versions ORDER BY last_seen DESC, id DESC LIMIT ?", (max(1, min(50, int(limit))),)).fetchall()
    out = []
    for r in rows:
        try:
            snap = json.loads(r["snapshot_json"] or "{}")
        except Exception:
            snap = {}
        out.append({
            "version": str(r["version_label"]), "fingerprint": str(r["fingerprint"]),
            "first_seen": float(r["first_seen"]), "last_seen": float(r["last_seen"]), "snapshot": snap,
        })
    return out


def report(engine: Optional[dict] = None, runtime: Optional[dict] = None,
           integrations: Optional[dict] = None, do_reconcile: bool = False) -> dict:
    init()
    configs = _config_history()
    rec = reconcile(engine, runtime, integrations) if do_reconcile else reconcile(engine, runtime, None)
    dq = _latest_quality()
    return {
        "status": "ok",
        "mode": "DIAGNOSTIC_ONLY",
        "data_quality": dq,
        "config_current": configs[0] if configs else None,
        "config_history": configs,
        "reconciliation": rec,
        "scripts": {
            "backup": "BACKUP_ASTRA_DATA.ps1",
            "restore": "RESTORE_ASTRA_DATA.ps1",
            "chaos": "RUN_ASTRA_SAFE_CHAOS_TESTS.ps1",
        },
        "note": "Hardening diagnostics do not change trading decisions or execution.",
    }


def status() -> dict:
    try:
        init()
        with _LOCK, _db() as con:
            cfg = int(con.execute("SELECT COUNT(*) n FROM config_versions").fetchone()["n"])
            dq = int(con.execute("SELECT COUNT(*) n FROM data_quality_samples").fetchone()["n"])
            rc = int(con.execute("SELECT COUNT(*) n FROM reconciliation_samples").fetchone()["n"])
        return {
            "enabled": True, "mode": "DIAGNOSTIC_ONLY", "db_path": DB_PATH,
            "config_versions": cfg, "data_quality_samples": dq, "reconciliation_samples": rc,
        }
    except Exception as exc:
        return {"enabled": True, "mode": "DIAGNOSTIC_ONLY", "db_path": DB_PATH, "error": f"{type(exc).__name__}: {exc}"}

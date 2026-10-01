"""MYSHKA / ASTRA Fast-Track PAPER Canary V1.

Experimental execution lane:
    TECH 3/4 + JEV APPROVE + Binance AGREE -> Freqtrade DRY_RUN

Safety invariants:
- never mutates production action/reason;
- never permits Freqtrade dry_run=false;
- maximum one canary position at a time by default;
- 5-minute pair+side dedupe persisted in SQLite;
- 1x leverage by default, small paper stake;
- stale canary trades are force-exited after the configured hold period;
- no real-money execution path exists in this module.
"""
from __future__ import annotations

from collections import deque
import json
import math
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from . import freqtrade_dryrun_bridge as bridge

MODE = "FASTTRACK_PAPER_CANARY_V1"
ENABLED = str(os.getenv("ASTRA_FASTTRACK_CANARY_ENABLED", "true")).lower() in {"1","true","yes","on"}
STAKE_USDT = max(1.0, float(os.getenv("ASTRA_FASTTRACK_CANARY_STAKE_USDT", "10")))
LEVERAGE = 1.0
MAX_CONCURRENT = max(1, int(os.getenv("ASTRA_FASTTRACK_CANARY_MAX_CONCURRENT", "1")))
HOLD_SEC = max(300, int(os.getenv("ASTRA_FASTTRACK_CANARY_HOLD_SEC", "900")))
CLUSTER_SEC = max(60, int(os.getenv("ASTRA_FASTTRACK_CANARY_CLUSTER_SEC", "300")))
REAPER_SEC = max(15, int(os.getenv("ASTRA_FASTTRACK_CANARY_REAPER_SEC", "60")))
DB_PATH = os.getenv("ASTRA_FASTTRACK_CANARY_DB_PATH", "/data/myshka_fasttrack_canary.sqlite3")
RISK_DB_PATH = os.getenv("RISK_INTELLIGENCE_DB_PATH", "/data/myshka_risk_intelligence.sqlite3")
JEV_BLACKBOX_MAX_AGE_SEC = max(5, int(os.getenv("ASTRA_FASTTRACK_CANARY_JEV_BLACKBOX_MAX_AGE_SEC", "45")))
TAG = "astra_fasttrack_canary"
EXECUTION_MODE = str(os.getenv("ASTRA_FASTTRACK_EXECUTION_MODE", "DRY_RUN")).strip().upper()
if EXECUTION_MODE not in {"DRY_RUN","LIVE"}:
    EXECUTION_MODE = "DRY_RUN"

_LOCK = threading.RLock()
_EXEC_LOCK = threading.Lock()
_EVENTS = deque(maxlen=300)
_EDGE_RECENT = deque(maxlen=100)
_REAPER_STARTED = False
_SHADOW_JEV_CACHE: dict[str, tuple[str, str, dict]] = {}
_STATS = {
    "scan_calls": 0,
    "rows_seen": 0,
    "tech3": 0,
    "jev_approve": 0,
    "jev_direct_hit": 0,
    "jev_blackbox_hit": 0,
    "jev_wait": 0,
    "jev_shadow_hit": 0,
    "jev_shadow_edge_reject": 0,
    "jev_shadow_ai_attempted": 0,
    "shadow_cache_hits": 0,
    "edge_evaluations": 0,
    "edge_passed": 0,
    "edge_rejected": 0,
    "last_edge": None,
    "binance_checked": 0,
    "binance_agree": 0,
    "binance_no_agree": 0,
    "triple_eligible": 0,
    "claimed": 0,
    "sent": 0,
    "blocked": 0,
    "last_scan_at": None,
    "last_pair": None,
    "last_stage": None,
    "last_jev_source": None,
    "execution_mode": EXECUTION_MODE,
}


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


def _db_init() -> None:
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS canary_events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                pair TEXT NOT NULL,
                side TEXT NOT NULL,
                cluster_key TEXT NOT NULL UNIQUE,
                tech_score INTEGER NOT NULL,
                tech_source TEXT,
                jev TEXT,
                xcheck TEXT,
                signal_price REAL,
                send_status TEXT,
                send_http INTEGER,
                response_json TEXT,
                trade_id INTEGER,
                exit_status TEXT,
                exited_at REAL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_canary_created ON canary_events(created_at DESC)")
        con.commit()


def _market_price(r: dict) -> Optional[float]:
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


def _tech_candidate(sig: dict) -> tuple[str, int, str]:
    fast = _num(sig.get("ema_fast"))
    slow = _num(sig.get("ema_slow"))
    rsi = _num(sig.get("rsi"))
    vol = _num(sig.get("volume_ratio"))
    structure = str(sig.get("structure") or "RANGE").upper()
    if None in (fast, slow, rsi, vol):
        return "WAIT", 0, "insufficient_fields"

    long_checks = [fast > slow, structure == "UP", 52 <= rsi <= 72, vol >= 0.60]
    short_checks = [fast < slow, structure == "DOWN", 28 <= rsi <= 48, vol >= 0.60]
    ls = sum(bool(x) for x in long_checks)
    ss = sum(bool(x) for x in short_checks)

    production = str(sig.get("direction") or "WAIT").upper()
    if production in {"LONG", "SHORT"}:
        return production, (ls if production == "LONG" else ss), "production_signal"

    best = max(ls, ss)
    if best < 3 or ls == ss:
        return "WAIT", best, "shadow_relaxed"
    return ("LONG" if ls > ss else "SHORT"), best, "shadow_relaxed"


def _norm_jev(v: Any) -> str:
    if isinstance(v, bool):
        return "APPROVE" if v else "REJECT"
    s = str(v or "").strip().upper()
    if s in {"APPROVE","APPROVED","PASS","PASSED","ENTER","ALLOW","ALLOWED","GO","YES","TRUE"}:
        return "APPROVE"
    if s in {"REJECT","REJECTED","DROP","BLOCK","BLOCKED","DENY","DENIED","NO","FALSE"}:
        return "REJECT"
    if s in {"WAIT","HOLD","NEUTRAL","SKIP","PENDING","NONE","NO_DATA","N/A"}:
        return "WAIT"
    return s


def _extract_jev_obj(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    for key in ("verdict","decision","state","action","result","label","recommendation","approved","passed"):
        if key in obj:
            x = _norm_jev(obj.get(key))
            if x:
                return x
    return ""


def _blackbox_jev(pair: str, side: str, now: float) -> tuple[str, str]:
    """Read a fresh existing JEV decision; never calls Ollama/JEV itself."""
    if not pair or not os.path.exists(RISK_DB_PATH):
        return "WAIT", "missing"
    try:
        con = sqlite3.connect(RISK_DB_PATH, timeout=0.20)
        con.row_factory = sqlite3.Row
        row = con.execute(
            """
            SELECT observed_at,direction,tech_score,jev_verdict,stage_json,raw_json
            FROM decision_blackbox
            WHERE pair=?
              AND observed_at>=?
              AND tech_score=3
            ORDER BY observed_at DESC,id DESC
            LIMIT 8
            """,
            (pair, float(now) - float(JEV_BLACKBOX_MAX_AGE_SEC)),
        ).fetchall()
        con.close()
    except Exception:
        return "WAIT", "db_error"

    want = str(side or "").upper()
    for rr in row:
        d = str(rr["direction"] or "").upper()
        if d in {"LONG","SHORT"} and want in {"LONG","SHORT"} and d != want:
            continue
        try:
            raw = json.loads(rr["raw_json"] or "{}")
        except Exception:
            raw = {}
        try:
            stage = json.loads(rr["stage_json"] or "{}")
        except Exception:
            stage = {}

        raw_j = _extract_jev_obj(raw.get("jev") if isinstance(raw, dict) else None)
        stage_j = _extract_jev_obj(stage.get("jev") if isinstance(stage, dict) else None)
        col_j = _norm_jev(rr["jev_verdict"])

        if raw_j and raw_j != "WAIT":
            return raw_j, "blackbox_raw"
        if stage_j and stage_j != "WAIT":
            return stage_j, "blackbox_stage"
        if col_j and col_j != "WAIT":
            return col_j, "blackbox_column"

    return "WAIT", "blackbox_wait"


def _jev(r: dict, pair: str = "", side: str = "", now: Optional[float] = None) -> tuple[str, str]:
    obj = r.get("jev")
    if isinstance(obj, dict):
        x = _extract_jev_obj(obj)
        if x and x != "WAIT":
            return x, "direct_object"
    for key in ("jev_verdict","jev_decision"):
        if key in r:
            x = _norm_jev(r.get(key))
            if x and x != "WAIT":
                return x, f"direct_{key}"

    # Fallback to the already-recorded decision blackbox. This is read-only and
    # intentionally avoids a second Ollama/JEV call.
    return _blackbox_jev(pair, side, float(now if now is not None else time.time()))


class _AttrMap:
    def __init__(self, data: dict):
        self._data = dict(data or {})
        for k, v in self._data.items():
            setattr(self, k, v)

    def as_dict(self) -> dict:
        return dict(self._data)


def _shadow_jev(r: dict, pair: str, side: str, now: float) -> tuple[str, str]:
    """Run the real JEV only for a Binance-AGREE relaxed TECH3 candidate.

    Production decisions are untouched. The API only supplies economic context;
    this function reconstructs the relaxed signal, computes the normal EDGE,
    then calls the existing JEV coordinator. One result is cached per 5-minute
    pair+side cluster to avoid repeated Ollama calls.
    """
    ctx = r.get("fasttrack_shadow_ctx")
    sig0 = r.get("signal") or {}
    if not isinstance(ctx, dict) or not isinstance(sig0, dict):
        return "WAIT", "shadow_ctx_missing"

    bucket_id = int(float(now) // CLUSTER_SEC) * CLUSTER_SEC
    cache_key = f"{pair}|{side}|{bucket_id}"
    with _LOCK:
        cached = _SHADOW_JEV_CACHE.get(cache_key)
    if cached:
        with _LOCK:
            _STATS["shadow_cache_hits"] = int(_STATS.get("shadow_cache_hits") or 0) + 1
        return cached[0], cached[1]

    try:
        spread = _num(ctx.get("spread_pct"))
        atr = _num(ctx.get("atr_pct"))
        atr_med = _num(ctx.get("atr_pct_median"))
        horizon = int(ctx.get("horizon_sec") or 300)
        if None in (spread, atr, atr_med):
            return "WAIT", "shadow_ctx_incomplete"

        from .stats_store import get_bucket_samples, get_pooled_samples
        from .edge import check_edge
        from .jev import decide as jev_decide

        sig_data = dict(sig0)
        sig_data["direction"] = side
        sig_data["tech_score"] = 3
        sig_data["tech_required"] = 3
        sig_data["training_mode"] = True
        sig_obj = _AttrMap(sig_data)

        hist_bucket = get_bucket_samples(pair, side, str(sig_data.get("structure") or "RANGE"), horizon)
        pooled = get_pooled_samples(horizon)
        edge_obj = check_edge(float(spread), float(atr), float(atr_med), hist_bucket, pooled)

        # EDGE diagnostic V3: count real evaluations (not repeated cached rejects)
        # and expose the economics that led to pass/reject.
        def _edge_attr(*names: str, default: Any = None) -> Any:
            for name in names:
                if hasattr(edge_obj, name):
                    return getattr(edge_obj, name)
            return default

        edge_passed = bool(_edge_attr("passed", default=False)) if edge_obj is not None else False
        edge_diag = {
            "ts": float(now),
            "pair": pair,
            "side": side,
            "cluster_key": cache_key,
            "horizon_sec": int(horizon),
            "spread_pct": float(spread),
            "atr_pct": float(atr),
            "atr_pct_median": float(atr_med),
            "expected_move_pct": _num(_edge_attr("expected_move_pct", "expected_move")),
            "total_cost_pct": _num(_edge_attr("total_cost_pct", "total_cost", "cost_pct")),
            "net_edge_pct": _num(_edge_attr("net_edge_pct", "net_edge")),
            "basis": str(_edge_attr("basis", default="unknown")),
            "samples": int(_edge_attr("n_samples", "samples", "n", default=len(hist_bucket)) or 0),
            "passed": bool(edge_passed),
        }
        with _LOCK:
            _STATS["edge_evaluations"] = int(_STATS.get("edge_evaluations") or 0) + 1
            if edge_passed:
                _STATS["edge_passed"] = int(_STATS.get("edge_passed") or 0) + 1
            else:
                _STATS["edge_rejected"] = int(_STATS.get("edge_rejected") or 0) + 1
            _STATS["last_edge"] = dict(edge_diag)
            _EDGE_RECENT.appendleft(dict(edge_diag))

        if edge_obj is None or not edge_passed:
            verdict, source = "REJECT", "shadow_edge_reject"
            meta = {"ai_attempted": False, "edge_passed": False, "edge_diag": edge_diag}
            with _LOCK:
                _SHADOW_JEV_CACHE[cache_key] = (verdict, source, meta)
            return verdict, source

        decision = jev_decide(
            pair=pair,
            signal=sig_obj,
            edge=edge_obj,
            realized_pnl_today_pct=float(ctx.get("realized_pnl_today_pct") or 0.0),
            realized_pnl_this_week_pct=float(ctx.get("realized_pnl_this_week_pct") or 0.0),
            open_positions_count=int(ctx.get("open_positions_count") or 0),
            kill_switch_engaged=bool(ctx.get("kill_switch_engaged", False)),
        )
        data = decision.as_dict() if hasattr(decision, "as_dict") else {}
        verdict = _norm_jev(data.get("verdict") or getattr(decision, "verdict", "WAIT")) or "WAIT"
        source = "shadow_real_jev"
        meta = {
            "ai_attempted": bool(data.get("ai_attempted")),
            "ai_used": bool(data.get("ai_used")),
            "edge_passed": True,
            "reason": data.get("reason"),
        }
        with _LOCK:
            _SHADOW_JEV_CACHE[cache_key] = (verdict, source, meta)
            # bounded cache
            if len(_SHADOW_JEV_CACHE) > 300:
                for k in list(_SHADOW_JEV_CACHE)[:100]:
                    _SHADOW_JEV_CACHE.pop(k, None)
        return verdict, source
    except Exception as exc:
        with _LOCK:
            _EVENTS.appendleft({
                "event":"shadow_jev_error",
                "pair":pair,
                "side":side,
                "error":f"{type(exc).__name__}: {exc}",
            })
        return "WAIT", "shadow_jev_error"


def _xcheck(r: dict, pair: str, side: str) -> str:
    bx = r.get("binance_crosscheck")
    if isinstance(bx, dict):
        state = str(bx.get("state") or "").upper()
        if state in {"AGREE","CONFLICT","NEUTRAL"}:
            return state

    # For a relaxed 3/4 candidate production may be WAIT, so the normal
    # crosscheck observer can mark it NOT_APPLICABLE. Reuse the existing
    # Binance cache to evaluate the candidate side without changing production.
    try:
        from . import binance_signal_crosscheck as mod
        symbol = mod._symbol(pair)
        mod._queue_refresh(symbol)
        snap = mod._snapshot(symbol)
        cc = mod._consensus(side, snap)
        return str((cc or {}).get("state") or "NO_DATA").upper()
    except Exception:
        return "NO_DATA"


def _claim(pair: str, side: str, tech_score: int, tech_source: str,
           jev: str, xcheck: str, signal_price: float, now: float) -> Optional[str]:
    # Be robust when the DB path changes in tests or after a fresh install.
    _db_init()
    bucket = int(now // CLUSTER_SEC) * CLUSTER_SEC
    key = f"{pair}|{side}|{bucket}"
    with _LOCK, _conn() as con:
        cur = con.execute(
            """
            INSERT OR IGNORE INTO canary_events(
                created_at,pair,side,cluster_key,tech_score,tech_source,jev,xcheck,signal_price,send_status
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (now,pair,side,key,int(tech_score),tech_source,jev,xcheck,float(signal_price),"CLAIMED"),
        )
        con.commit()
        if not cur.rowcount:
            return None
    return key


def _update_event(cluster_key: str, **fields: Any) -> None:
    allowed = {
        "send_status","send_http","response_json","trade_id","exit_status","exited_at"
    }
    vals = [(k, v) for k, v in fields.items() if k in allowed]
    if not vals:
        return
    sql = "UPDATE canary_events SET " + ",".join(f"{k}=?" for k,_ in vals) + " WHERE cluster_key=?"
    args = [v for _,v in vals] + [cluster_key]
    with _LOCK, _conn() as con:
        con.execute(sql, args)
        con.commit()


def _open_trades(token: str) -> list[dict]:
    code, data = bridge._request("/api/v1/status", token=token)
    return data if code == 200 and isinstance(data, list) else []


def _canary_open_count(token: str) -> int:
    n = 0
    for t in _open_trades(token):
        tag = str(t.get("enter_tag") or t.get("entry_tag") or "")
        if tag == TAG and bool(t.get("is_open", True)):
            n += 1
    return n


def _find_canary_trade(token: str, pair: str, side: str) -> Optional[dict]:
    want_short = str(side).lower() == "short"
    matches = []
    for t in _open_trades(token):
        if str(t.get("pair") or "") != pair:
            continue
        tag = str(t.get("enter_tag") or t.get("entry_tag") or "")
        if tag != TAG:
            continue
        if "is_short" in t and bool(t.get("is_short")) != want_short:
            continue
        matches.append(t)
    if not matches:
        return None
    return max(matches, key=lambda x: int(x.get("trade_id") or x.get("id") or 0))


def _remote_dry_run(token: str) -> bool:
    if not bridge._local_dry_run():
        return False
    code, cfg = bridge._request("/api/v1/show_config", token=token)
    return code == 200 and bridge._bool(cfg, "dry_run") is True


def _direct_request(path: str, *, token: str, payload: Optional[dict] = None) -> tuple[int, Any]:
    # This helper exists only for /forceexit, which the production dry-run
    # bridge intentionally does not expose. It is hard-blocked unless BOTH
    # local and remote Freqtrade still confirm dry-run.
    if path != "/api/v1/forceexit":
        return 0, {"error": "blocked_target"}
    if not _remote_dry_run(token):
        return 0, {"error": "hard_block_dry_run_not_confirmed"}

    data = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        bridge.BASE_URL + path,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "MYSHKA-ASTRA-FASTTRACK-CANARY",
        },
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=bridge.TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return int(resp.status), json.loads(body)
            except Exception:
                return int(resp.status), {"raw": body[:4000]}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body[:4000]}
        return int(exc.code), parsed
    except Exception as exc:
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


def _execute(cluster_key: str, pair: str, direction: str, price: float, now: float) -> None:
    side = direction.lower()
    with _EXEC_LOCK:
        if EXECUTION_MODE == "LIVE":
            try:
                from . import freqtrade_live_bridge as live_bridge
            except Exception as exc:
                _update_event(cluster_key, send_status="BLOCKED_LIVE_IMPORT", response_json=json.dumps({"error":str(exc)}))
                return
            result = live_bridge._send(
                pair,
                side,
                stake_usdt=STAKE_USDT,
                leverage=1.0,
                source="fasttrack_lean_live",
                tag="astra_fasttrack_lean_live",
                signal_price=price,
                signal_ts_ms=int(now * 1000),
            )
        else:
            token, auth = bridge._token()
            if not token:
                _update_event(cluster_key, send_status="BLOCKED_AUTH", response_json=json.dumps(auth))
                return
            if not _remote_dry_run(token):
                _update_event(cluster_key, send_status="BLOCKED_NOT_DRYRUN")
                return
            if _canary_open_count(token) >= MAX_CONCURRENT:
                _update_event(cluster_key, send_status="BLOCKED_MAX_CONCURRENT")
                return

            result = bridge._send(
                pair,
                side,
                stake_usdt=STAKE_USDT,
                leverage=LEVERAGE,
                source="fasttrack_canary",
                tag=TAG,
                signal_price=price,
                signal_ts_ms=int(now * 1000),
            )
        with _LOCK:
            if str(result.get("status") or "").lower() == "sent":
                _STATS["sent"] = int(_STATS.get("sent") or 0) + 1
                _STATS["last_stage"] = "SENT"
            else:
                _STATS["blocked"] = int(_STATS.get("blocked") or 0) + 1
                _STATS["last_stage"] = "BLOCKED"
            _STATS["last_pair"] = pair
        _update_event(
            cluster_key,
            send_status=str(result.get("status") or "UNKNOWN").upper(),
            send_http=int(result.get("http_status") or 0),
            response_json=json.dumps(result, ensure_ascii=False, default=str)[:12000],
        )
        with _LOCK:
            _EVENTS.appendleft({
                "cluster_key": cluster_key,
                "pair": pair,
                "side": side,
                "result": result,
            })


def observe_results(results: list[dict], now: Optional[float] = None) -> dict:
    # Ensure schema exists even if observe_results is called before init().
    _db_init()
    ts = float(now if now is not None else time.time())

    with _LOCK:
        _STATS["scan_calls"] = int(_STATS.get("scan_calls") or 0) + 1
        _STATS["rows_seen"] = int(_STATS.get("rows_seen") or 0) + len(results or [])
        _STATS["last_scan_at"] = ts

    if not ENABLED:
        return {"status":"disabled","mode":MODE,"enabled":False,"real_money_execution":False}

    eligible = claimed = 0
    for r in results or []:
        pair = str(r.get("pair") or "")
        sig = r.get("signal") or {}
        direction, score, tech_source = _tech_candidate(sig)

        if direction not in {"LONG","SHORT"} or score != 3:
            continue
        with _LOCK:
            _STATS["tech3"] = int(_STATS.get("tech3") or 0) + 1
            _STATS["last_pair"] = pair
            _STATS["last_stage"] = "TECH3"

        # Low-resource order: Binance first. Only AGREE candidates are allowed
        # to invoke the relaxed shadow JEV / optional Ollama advisory.
        if not pair:
            continue
        bx = _xcheck(r, pair, direction)
        with _LOCK:
            _STATS["binance_checked"] = int(_STATS.get("binance_checked") or 0) + 1
        if bx != "AGREE":
            with _LOCK:
                _STATS["binance_no_agree"] = int(_STATS.get("binance_no_agree") or 0) + 1
            continue
        with _LOCK:
            _STATS["binance_agree"] = int(_STATS.get("binance_agree") or 0) + 1
            _STATS["last_stage"] = "BINANCE_AGREE"

        j, j_source = _jev(r, pair=pair, side=direction, now=ts)
        if j == "WAIT":
            j, j_source = _shadow_jev(r, pair, direction, ts)

        with _LOCK:
            _STATS["last_jev_source"] = j_source
            if j_source.startswith("direct_"):
                _STATS["jev_direct_hit"] = int(_STATS.get("jev_direct_hit") or 0) + 1
            elif j_source.startswith("blackbox_") and j != "WAIT":
                _STATS["jev_blackbox_hit"] = int(_STATS.get("jev_blackbox_hit") or 0) + 1
            elif j_source == "shadow_real_jev":
                _STATS["jev_shadow_hit"] = int(_STATS.get("jev_shadow_hit") or 0) + 1
                bucket_id = int(ts // CLUSTER_SEC) * CLUSTER_SEC
                meta = _SHADOW_JEV_CACHE.get(f"{pair}|{direction}|{bucket_id}", (None,None,{}))[2]
                if bool((meta or {}).get("ai_attempted")):
                    _STATS["jev_shadow_ai_attempted"] = int(_STATS.get("jev_shadow_ai_attempted") or 0) + 1
            elif j_source == "shadow_edge_reject":
                _STATS["jev_shadow_edge_reject"] = int(_STATS.get("jev_shadow_edge_reject") or 0) + 1

        if j != "APPROVE":
            with _LOCK:
                _STATS["jev_wait"] = int(_STATS.get("jev_wait") or 0) + 1
            continue

        with _LOCK:
            _STATS["jev_approve"] = int(_STATS.get("jev_approve") or 0) + 1
            _STATS["last_stage"] = "JEV_APPROVE"

        price = _market_price(r)
        if price is None:
            continue

        eligible += 1
        with _LOCK:
            _STATS["triple_eligible"] = int(_STATS.get("triple_eligible") or 0) + 1
            _STATS["last_stage"] = "TRIPLE"

        key = _claim(pair, direction, score, tech_source, j, bx, price, ts)
        if not key:
            continue
        claimed += 1
        with _LOCK:
            _STATS["claimed"] = int(_STATS.get("claimed") or 0) + 1
            _STATS["last_stage"] = "CLAIMED"

        threading.Thread(
            target=_execute,
            args=(key, pair, direction, price, ts),
            name=f"fasttrack-canary-{pair.replace('/','_')}",
            daemon=True,
        ).start()

    return {
        "status":"ok",
        "mode":MODE,
        "enabled":True,
        "eligible":eligible,
        "claimed":claimed,
        "stake_usdt":STAKE_USDT,
        "leverage":LEVERAGE,
        "real_money_execution":False,
    }


def _parse_open_ms(t: dict) -> Optional[int]:
    for key in ("open_date_timestamp","open_timestamp","open_time_ms"):
        x = _num(t.get(key))
        if x is not None:
            return int(x if x > 10_000_000_000 else x * 1000)
    return None


def _reaper() -> None:
    while True:
        try:
            token, _ = bridge._token()
            if token and _remote_dry_run(token):
                now_ms = int(time.time() * 1000)
                for t in _open_trades(token):
                    tag = str(t.get("enter_tag") or t.get("entry_tag") or "")
                    if tag != TAG or not bool(t.get("is_open", True)):
                        continue
                    opened_ms = _parse_open_ms(t)
                    if opened_ms is None or now_ms - opened_ms < HOLD_SEC * 1000:
                        continue
                    trade_id = t.get("trade_id") or t.get("id")
                    if trade_id is None:
                        continue
                    code, data = _direct_request(
                        "/api/v1/forceexit",
                        token=token,
                        payload={"tradeid": int(trade_id), "ordertype": "market"},
                    )
                    pair = str(t.get("pair") or "")
                    side = "SHORT" if bool(t.get("is_short")) else "LONG"
                    with _LOCK, _conn() as con:
                        con.execute(
                            """
                            UPDATE canary_events
                            SET trade_id=?,exit_status=?,exited_at=?
                            WHERE id=(
                                SELECT id FROM canary_events
                                WHERE pair=? AND side=? AND trade_id IS NULL
                                ORDER BY created_at DESC LIMIT 1
                            )
                            """,
                            (int(trade_id), f"FORCEEXIT_HTTP_{code}", time.time(), pair, side),
                        )
                        con.commit()
                    with _LOCK:
                        _EVENTS.appendleft({
                            "event":"auto_exit",
                            "pair":pair,
                            "side":side,
                            "trade_id":trade_id,
                            "http_status":code,
                            "response":data,
                        })
        except Exception as exc:
            with _LOCK:
                _EVENTS.appendleft({"event":"reaper_error","error":f"{type(exc).__name__}: {exc}"})
        time.sleep(REAPER_SEC)


def init() -> dict:
    global _REAPER_STARTED
    _db_init()
    with _LOCK:
        if not _REAPER_STARTED:
            threading.Thread(target=_reaper, name="fasttrack-canary-reaper", daemon=True).start()
            _REAPER_STARTED = True
    return status()


def recent(limit: int = 50) -> dict:
    lim = max(1, min(200, int(limit)))
    _db_init()
    with _conn() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM canary_events ORDER BY created_at DESC LIMIT ?", (lim,)
        ).fetchall()]
    return {"status":"ok","mode":MODE,"items":rows}


def status() -> dict:
    _db_init()
    counts = {}
    with _conn() as con:
        for r in con.execute("SELECT send_status,COUNT(*) n FROM canary_events GROUP BY send_status").fetchall():
            counts[str(r["send_status"] or "UNKNOWN")] = int(r["n"])
    return {
        "status":"ok",
        "mode":MODE,
        "enabled":ENABLED,
        "filter":"TECH_3_OF_4 + JEV_APPROVE + BINANCE_AGREE",
        "stake_usdt":STAKE_USDT,
        "leverage":LEVERAGE,
        "max_concurrent":MAX_CONCURRENT,
        "hold_sec":HOLD_SEC,
        "cluster_sec":CLUSTER_SEC,
        "reaper_sec":REAPER_SEC,
        "jev_blackbox_max_age_sec":JEV_BLACKBOX_MAX_AGE_SEC,
        "risk_db_path":RISK_DB_PATH,
        "db_path":DB_PATH,
        "event_counts":counts,
        "live_funnel": dict(_STATS),
        "edge_recent": list(_EDGE_RECENT),
        "execution_mode":EXECUTION_MODE,
        "local_dry_run":bridge._local_dry_run(),
        "changes_production_decisions":False,
        "real_money_execution":False,
    }

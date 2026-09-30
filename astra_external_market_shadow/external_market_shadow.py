"""MYSHKA / ASTRA — External Market Shadow V1.

SHADOW ONLY:
- Investing.com technical-consensus cross-check for supported crypto symbols.
- Macro cross-market context from Nasdaq 100, DXY, Gold, WTI and VIX.
- 5m/10m/15m forward outcome tracking with cluster-adjusted metrics.
- Never changes action/reason, never opens/rescues/rejects trades, never routes orders.

The scanner path is non-blocking. Network refresh happens in background workers.
If an external source is unavailable or changes format, the module degrades to NO_DATA.
"""
from __future__ import annotations

import html
import json
import math
import os
import queue
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Optional

DB_PATH = os.getenv("EXTERNAL_MARKET_SHADOW_DB_PATH", "/data/myshka_external_market_shadow.sqlite3")
ENABLED = os.getenv("EXTERNAL_MARKET_SHADOW_ENABLED", "true").lower() in {"1","true","yes","on"}
CACHE_SEC = max(30, int(os.getenv("EXTERNAL_MARKET_SHADOW_CACHE_SEC", "90")))
MAX_AGE_SEC = max(CACHE_SEC, int(os.getenv("EXTERNAL_MARKET_SHADOW_MAX_AGE_SEC", "300")))
HTTP_TIMEOUT_SEC = max(1.0, float(os.getenv("EXTERNAL_MARKET_SHADOW_HTTP_TIMEOUT_SEC", "5")))
HORIZONS = tuple(sorted({int(x.strip()) for x in os.getenv(
    "EXTERNAL_MARKET_SHADOW_HORIZONS_SEC", "300,600,900"
).split(",") if x.strip()}))
CLUSTER_SEC = max(60, int(os.getenv("EXTERNAL_MARKET_SHADOW_CLUSTER_SEC", "300")))
MAX_SETTLE_DELAY_SEC = max(30, int(os.getenv("EXTERNAL_MARKET_SHADOW_MAX_SETTLE_DELAY_SEC", "120")))
WORKER_COUNT = max(1, min(4, int(os.getenv("EXTERNAL_MARKET_SHADOW_WORKERS", "2"))))

INVESTING_BASE = os.getenv("INVESTING_BASE_URL", "https://www.investing.com").rstrip("/")
YAHOO_BASE = os.getenv("MACRO_YAHOO_BASE_URL", "https://query1.finance.yahoo.com").rstrip("/")

SLUGS = {
    "BTC":"bitcoin",
    "ETH":"ethereum",
    "SOL":"solana",
    "XRP":"xrp",
    "ZEC":"zcash",
    "NEAR":"near-protocol",
    "HYPE":"hyperliquid",
    "QNT":"quant",
    "ENA":"ethena",
    "DOGE":"dogecoin",
    "SUI":"sui",
    "WLD":"worldcoin-org",
    "PUMP":"pump-fun",
    "PUMPFUN":"pump-fun",
}

MACRO_SYMBOLS = {
    "NDX":"^NDX",
    "DXY":"DX-Y.NYB",
    "GOLD":"GC=F",
    "WTI":"CL=F",
    "VIX":"^VIX",
}

_LOCK = threading.RLock()
_INV_CACHE: dict[str, dict] = {}
_MACRO_CACHE: dict[str, Any] = {}
_Q: "queue.Queue[tuple[str,str]]" = queue.Queue(maxsize=300)
_QUEUED: set[tuple[str,str]] = set()
_WORKERS_STARTED = False


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


def init() -> dict:
    global _WORKERS_STARTED
    with _LOCK:
        con = _conn()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS external_market_outcomes(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pair TEXT NOT NULL,
                    side TEXT NOT NULL,
                    source_minute INTEGER NOT NULL,
                    cluster_bucket INTEGER NOT NULL,
                    cluster_key TEXT NOT NULL,
                    opened_at REAL NOT NULL,
                    target_at REAL NOT NULL,
                    horizon_sec INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    action TEXT,
                    reason TEXT,
                    tech_score INTEGER,
                    edge_passed INTEGER,
                    edge_pct REAL,
                    total_cost_pct REAL,
                    jev_verdict TEXT,
                    evidence_state TEXT,
                    evidence_passed INTEGER,
                    adaptive_state TEXT,
                    investing_state TEXT,
                    investing_alignment TEXT,
                    investing_score REAL,
                    macro_state TEXT,
                    macro_alignment TEXT,
                    macro_score REAL,
                    combined_state TEXT,
                    settled_at REAL,
                    settle_delay_sec REAL,
                    gross_pct REAL,
                    net_pct REAL,
                    direction_hit INTEGER,
                    UNIQUE(pair,side,source_minute,horizon_sec)
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_ext_status_target ON external_market_outcomes(status,target_at)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_ext_combined ON external_market_outcomes(combined_state,horizon_sec,status)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_ext_pair ON external_market_outcomes(pair,horizon_sec,status)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_ext_cluster ON external_market_outcomes(cluster_key,horizon_sec,status)")
            con.commit()
        finally:
            con.close()

        if ENABLED and not _WORKERS_STARTED:
            for i in range(WORKER_COUNT):
                t = threading.Thread(target=_worker_loop, name=f"external-market-shadow-{i+1}", daemon=True)
                t.start()
            _WORKERS_STARTED = True

    if ENABLED:
        _queue_refresh("macro", "GLOBAL")
    return status()


def _ticker(pair: str) -> str:
    base = str(pair or "").upper().split(":")[0].split("/")[0]
    return base.replace("-", "").replace("_", "")


def _side(r: dict) -> str:
    sig = r.get("signal") or {}
    return str(r.get("direction") or sig.get("direction") or "WAIT").upper()


def _market_price(r: dict) -> Optional[float]:
    m = r.get("market") or {}
    for k in ("last_price","last","price","close"):
        x = _num(m.get(k))
        if x is not None and x > 0:
            return x
    candles = m.get("candles") or r.get("candles") or []
    if candles:
        c = candles[-1]
        x = _num(c.get("close") if isinstance(c, dict) else getattr(c, "close", None))
        if x is not None and x > 0:
            return x
    return None


def _request_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141 Safari/537.36",
            "Accept":"text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language":"en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        raw = resp.read(2_000_000)
    return raw.decode("utf-8", errors="replace")


def _html_to_text(raw: str) -> str:
    s = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw)
    s = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


_SIGNAL_VALUE = {
    "STRONG SELL": -2.0,
    "SELL": -1.0,
    "NEUTRAL": 0.0,
    "BUY": 1.0,
    "STRONG BUY": 2.0,
}
_FRAME_WEIGHT = {"30m":1.0, "1h":1.5, "5h":1.25, "1d":0.5}
_FRAME_PATTERNS = {
    "30m": r"30\s*Min\s+(Strong Sell|Strong Buy|Sell|Neutral|Buy)",
    "1h": r"Hourly\s+(Strong Sell|Strong Buy|Sell|Neutral|Buy)",
    "5h": r"5\s*Hours\s+(Strong Sell|Strong Buy|Sell|Neutral|Buy)",
    "1d": r"Daily\s+(Strong Sell|Strong Buy|Sell|Neutral|Buy)",
}


def _parse_investing_summary(raw: str, ticker: str = "") -> dict:
    text = _html_to_text(raw)
    frames: dict[str,str] = {}
    for key, pat in _FRAME_PATTERNS.items():
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            frames[key] = re.sub(r"\s+", " ", m.group(1)).upper()

    vals = []
    for key, sig in frames.items():
        if sig in _SIGNAL_VALUE:
            vals.append((_SIGNAL_VALUE[sig], _FRAME_WEIGHT[key]))
    if len(vals) < 2:
        return {
            "ticker":ticker,
            "state":"NO_DATA",
            "score":None,
            "frames":frames,
            "reason":"insufficient_investing_frames",
            "source":"investing.com",
        }

    den = sum(w for _, w in vals)
    score = sum(v*w for v, w in vals) / den if den else 0.0
    if score >= 0.50:
        state = "LONG"
    elif score <= -0.50:
        state = "SHORT"
    else:
        state = "NEUTRAL"
    return {
        "ticker":ticker,
        "state":state,
        "score":score,
        "frames":frames,
        "reason":"ok",
        "source":"investing.com",
    }


def _fetch_investing(ticker: str) -> dict:
    now = time.time()
    slug = SLUGS.get(ticker)
    if not slug:
        return {
            "ticker":ticker, "state":"NO_DATA", "score":None, "frames":{},
            "reason":"unsupported_ticker", "source":"investing.com", "fetched_at":now,
        }
    url = f"{INVESTING_BASE}/crypto/{slug}/technical"
    try:
        out = _parse_investing_summary(_request_text(url), ticker=ticker)
        out["url"] = url
        out["fetched_at"] = now
        return out
    except Exception as exc:
        return {
            "ticker":ticker, "state":"NO_DATA", "score":None, "frames":{},
            "reason":f"fetch_error:{type(exc).__name__}", "source":"investing.com",
            "url":url, "fetched_at":now,
        }


def _request_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141 Safari/537.36",
            "Accept":"application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _yahoo_change(symbol: str) -> Optional[float]:
    q = urllib.parse.quote(symbol, safe="")
    url = f"{YAHOO_BASE}/v8/finance/chart/{q}?interval=5m&range=1d"
    data = _request_json(url)
    result = (((data or {}).get("chart") or {}).get("result") or [])
    if not result:
        return None
    quote = (((result[0].get("indicators") or {}).get("quote") or [{}])[0])
    closes = [_num(x) for x in (quote.get("close") or [])]
    vals = [x for x in closes if x is not None and x > 0]
    if len(vals) < 2:
        return None
    prev, last = vals[-2], vals[-1]
    return (last / prev - 1.0) * 100.0 if prev else None


def _macro_vote(name: str, change: Optional[float]) -> float:
    if change is None:
        return 0.0
    thresholds = {"NDX":0.03, "DXY":0.01, "GOLD":0.02, "WTI":0.03, "VIX":0.05}
    if abs(change) < thresholds.get(name, 0.02):
        return 0.0
    sign = 1.0 if change > 0 else -1.0
    if name == "NDX":
        return 2.0 * sign
    if name == "DXY":
        return -1.0 * sign
    if name == "VIX":
        return -2.0 * sign
    if name == "GOLD":
        return -0.5 * sign
    if name == "WTI":
        return -0.5 * sign
    return 0.0


def _fetch_macro() -> dict:
    now = time.time()
    changes: dict[str,Optional[float]] = {}
    errors: dict[str,str] = {}
    for name, symbol in MACRO_SYMBOLS.items():
        try:
            changes[name] = _yahoo_change(symbol)
        except Exception as exc:
            changes[name] = None
            errors[name] = type(exc).__name__

    ok = sum(1 for v in changes.values() if v is not None)
    score = sum(_macro_vote(k, v) for k, v in changes.items())
    if ok < 3:
        state = "NO_DATA"
    elif score >= 1.5:
        state = "RISK_ON"
    elif score <= -1.5:
        state = "RISK_OFF"
    else:
        state = "NEUTRAL"

    return {
        "state":state,
        "score":score,
        "changes_5m_pct":changes,
        "sources_ok":ok,
        "errors":errors,
        "source":"yahoo_finance_chart",
        "fetched_at":now,
    }


def _worker_loop() -> None:
    while True:
        try:
            kind, key = _Q.get(timeout=2.0)
        except queue.Empty:
            continue
        try:
            if kind == "investing":
                snap = _fetch_investing(key)
                with _LOCK:
                    _INV_CACHE[key] = snap
            elif kind == "macro":
                snap = _fetch_macro()
                with _LOCK:
                    _MACRO_CACHE.clear()
                    _MACRO_CACHE.update(snap)
        except Exception:
            pass
        finally:
            with _LOCK:
                _QUEUED.discard((kind,key))
            _Q.task_done()


def _queue_refresh(kind: str, key: str) -> None:
    if not ENABLED:
        return
    now = time.time()
    with _LOCK:
        if kind == "investing":
            cur = _INV_CACHE.get(key) or {}
        else:
            cur = _MACRO_CACHE
        fresh = cur and now - float(cur.get("fetched_at") or 0.0) < CACHE_SEC
        token = (kind,key)
        if fresh or token in _QUEUED:
            return
        _QUEUED.add(token)
    try:
        _Q.put_nowait(token)
    except queue.Full:
        with _LOCK:
            _QUEUED.discard(token)


def _fresh(snapshot: dict) -> Optional[dict]:
    if not snapshot:
        return None
    out = dict(snapshot)
    age = max(0.0, time.time() - float(out.get("fetched_at") or 0.0))
    out["age_sec"] = age
    if age > MAX_AGE_SEC:
        return None
    return out


def _investing_snapshot(ticker: str) -> Optional[dict]:
    with _LOCK:
        return _fresh(_INV_CACHE.get(ticker) or {})


def _macro_snapshot() -> Optional[dict]:
    with _LOCK:
        return _fresh(_MACRO_CACHE)


def _alignment(side: str, state: str, macro: bool = False) -> str:
    side = str(side or "").upper()
    state = str(state or "").upper()
    if side not in {"LONG","SHORT"}:
        return "NOT_APPLICABLE"
    if state in {"NO_DATA",""}:
        return "NO_DATA"
    if state == "NEUTRAL":
        return "NEUTRAL"
    expected = "RISK_ON" if (macro and side == "LONG") else                "RISK_OFF" if (macro and side == "SHORT") else side
    return "AGREE" if state == expected else "CONFLICT"


def _combined(inv_align: str, macro_align: str) -> str:
    vals = [inv_align, macro_align]
    if vals.count("AGREE") == 2:
        return "BOTH_AGREE"
    if vals.count("CONFLICT") == 2:
        return "BOTH_CONFLICT"
    if "AGREE" in vals and "CONFLICT" in vals:
        return "MIXED"
    known = [x for x in vals if x not in {"NO_DATA","NOT_APPLICABLE"}]
    if not known:
        return "NO_DATA"
    if known == ["AGREE"]:
        return "PARTIAL_AGREE"
    if known == ["CONFLICT"]:
        return "PARTIAL_CONFLICT"
    if all(x == "NEUTRAL" for x in known):
        return "NEUTRAL"
    return "PARTIAL"


def _attach(r: dict) -> dict:
    side = _side(r)
    ticker = _ticker(r.get("pair") or "")

    _queue_refresh("macro", "GLOBAL")
    if ticker:
        _queue_refresh("investing", ticker)

    if side not in {"LONG","SHORT"}:
        ext = {
            "investing":{"state":"NOT_APPLICABLE","alignment":"NOT_APPLICABLE"},
            "macro":{"state":"NOT_APPLICABLE","alignment":"NOT_APPLICABLE"},
            "combined_state":"NOT_APPLICABLE",
            "shadow_only":True,
        }
        r["external_market_shadow"] = ext
        return ext

    inv = _investing_snapshot(ticker)
    if not inv:
        inv_view = {"state":"NO_DATA","alignment":"NO_DATA","ticker":ticker,"reason":"cache_warming"}
    else:
        inv_view = dict(inv)
        inv_view["alignment"] = _alignment(side, inv_view.get("state"))

    macro = _macro_snapshot()
    if not macro:
        macro_view = {"state":"NO_DATA","alignment":"NO_DATA","reason":"cache_warming"}
    else:
        macro_view = dict(macro)
        macro_view["alignment"] = _alignment(side, macro_view.get("state"), macro=True)

    ext = {
        "investing":inv_view,
        "macro":macro_view,
        "combined_state":_combined(inv_view.get("alignment","NO_DATA"), macro_view.get("alignment","NO_DATA")),
        "shadow_only":True,
        "changes_trade_decision":False,
    }
    r["external_market_shadow"] = ext
    return ext


def _settle(results: list[dict], now: float) -> dict:
    by_pair = {str(r.get("pair") or ""): r for r in (results or []) if r.get("pair")}
    closed = skipped = 0
    with _LOCK:
        con = _conn()
        try:
            rows = con.execute(
                "SELECT * FROM external_market_outcomes WHERE status='OPEN' AND target_at<=? ORDER BY target_at",
                (now,),
            ).fetchall()
            for row in rows:
                delay = max(0.0, now - float(row["target_at"]))
                if delay > MAX_SETTLE_DELAY_SEC:
                    con.execute(
                        "UPDATE external_market_outcomes SET status='SKIPPED',settled_at=?,settle_delay_sec=? WHERE id=?",
                        (now,delay,int(row["id"])),
                    )
                    skipped += 1
                    continue
                r = by_pair.get(str(row["pair"]))
                if not r:
                    continue
                exit_price = _market_price(r)
                if exit_price is None:
                    continue
                entry = float(row["entry_price"])
                raw = (exit_price / entry - 1.0) * 100.0
                gross = raw if str(row["side"]) == "LONG" else -raw
                cost = float(row["total_cost_pct"] or 0.0)
                net = gross - cost
                con.execute(
                    """
                    UPDATE external_market_outcomes
                    SET status='CLOSED',exit_price=?,settled_at=?,settle_delay_sec=?,
                        gross_pct=?,net_pct=?,direction_hit=?
                    WHERE id=? AND status='OPEN'
                    """,
                    (exit_price,now,delay,gross,net,1 if gross>0 else 0,int(row["id"])),
                )
                closed += 1
            con.commit()
        finally:
            con.close()
    return {"closed":closed,"skipped":skipped}


def _record(r: dict, ext: dict, now: float) -> int:
    side = _side(r)
    if side not in {"LONG","SHORT"}:
        return 0
    pair = str(r.get("pair") or "")
    entry = _market_price(r)
    if not pair or entry is None:
        return 0

    sig = r.get("signal") or {}
    edge = r.get("edge") or {}
    jev = r.get("jev") or {}
    evidence = r.get("evidence_gate") or {}
    adaptive = r.get("adaptive_learner") or {}
    inv = ext.get("investing") or {}
    macro = ext.get("macro") or {}

    source_minute = int(now // 60) * 60
    cluster_bucket = int(now // CLUSTER_SEC) * CLUSTER_SEC
    cluster_key = f"{pair}|{side}|{cluster_bucket}"

    common = (
        str(r.get("action") or ""),
        str(r.get("reason") or ""),
        int(sig.get("tech_score") or 0),
        1 if edge.get("passed") is True else 0,
        _num(edge.get("net_edge_pct")),
        _num(edge.get("total_cost_pct")),
        str(jev.get("verdict") or ""),
        str(evidence.get("state") or ""),
        1 if evidence.get("passed") is True else 0,
        str(adaptive.get("state") or ""),
        str(inv.get("state") or "NO_DATA"),
        str(inv.get("alignment") or "NO_DATA"),
        _num(inv.get("score")),
        str(macro.get("state") or "NO_DATA"),
        str(macro.get("alignment") or "NO_DATA"),
        _num(macro.get("score")),
        str(ext.get("combined_state") or "NO_DATA"),
    )

    made = 0
    with _LOCK:
        con = _conn()
        try:
            for h in HORIZONS:
                cur = con.execute(
                    """
                    INSERT OR IGNORE INTO external_market_outcomes(
                        pair,side,source_minute,cluster_bucket,cluster_key,opened_at,target_at,horizon_sec,status,
                        entry_price,action,reason,tech_score,edge_passed,edge_pct,total_cost_pct,jev_verdict,
                        evidence_state,evidence_passed,adaptive_state,investing_state,investing_alignment,
                        investing_score,macro_state,macro_alignment,macro_score,combined_state
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        pair,side,source_minute,cluster_bucket,cluster_key,now,now+int(h),int(h),"OPEN",entry,
                        *common,
                    ),
                )
                made += int(bool(cur.rowcount))
            con.commit()
        finally:
            con.close()
    return made


def observe_results(results: list[dict], now: Optional[float] = None) -> dict:
    """Attach XCHECK/MACRO shadow fields and record forward outcomes. Never changes action/reason."""
    try:
        init()
        ts = float(now if now is not None else time.time())
        settled = _settle(results or [], ts)
        created = attached = 0
        for r in results or []:
            before_action = r.get("action")
            before_reason = r.get("reason")
            ext = _attach(r)
            attached += 1
            created += _record(r, ext, ts)
            # Safety invariant: this module may annotate only.
            if r.get("action") != before_action or r.get("reason") != before_reason:
                r["action"] = before_action
                r["reason"] = before_reason
                raise RuntimeError("shadow attempted to change trade decision")
        return {"status":"ok","attached":attached,"created":created,**settled}
    except Exception as exc:
        return {
            "status":"error","error":f"{type(exc).__name__}: {exc}",
            "attached":0,"created":0,"closed":0,"skipped":0,
        }


def _pf(vals: list[float]) -> float:
    pos = sum(x for x in vals if x > 0)
    neg = abs(sum(x for x in vals if x <= 0))
    return pos / neg if neg > 1e-12 else (999.0 if pos > 0 else 0.0)


def _cluster_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for r in sorted(rows, key=lambda x: (float(x.get("opened_at") or 0), int(x.get("id") or 0))):
        key = str(r.get("cluster_key") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _metrics(rows: list[dict]) -> dict:
    vals = [float(r["net_pct"]) for r in rows if r.get("net_pct") is not None]
    clustered = _cluster_rows(rows)
    cvals = [float(r["net_pct"]) for r in clustered if r.get("net_pct") is not None]
    return {
        "n":len(vals),
        "win_rate_pct":sum(1 for x in vals if x>0)/len(vals)*100.0 if vals else 0.0,
        "avg_net_pct":sum(vals)/len(vals) if vals else 0.0,
        "profit_factor":_pf(vals),
        "cluster_n":len(cvals),
        "cluster_win_rate_pct":sum(1 for x in cvals if x>0)/len(cvals)*100.0 if cvals else 0.0,
        "cluster_avg_net_pct":sum(cvals)/len(cvals) if cvals else 0.0,
        "cluster_profit_factor":_pf(cvals),
    }


def _research_state(cluster_n: int) -> str:
    if cluster_n < 30:
        return "COLD"
    if cluster_n < 60:
        return "WATCH"
    if cluster_n < 80:
        return "CONFIRMATION_WINDOW"
    return "REVIEW_ONLY"


def _breakdown(rows: list[dict], field: str, values: list[str]) -> dict:
    return {v:_metrics([r for r in rows if str(r.get(field) or "") == v]) for v in values}


def report() -> dict:
    init()
    with _LOCK:
        con = _conn()
        try:
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM external_market_outcomes WHERE status='CLOSED' ORDER BY opened_at,id"
            ).fetchall()]
            counts = {
                str(r["status"]):int(r["n"]) for r in con.execute(
                    "SELECT status,COUNT(*) n FROM external_market_outcomes GROUP BY status"
                ).fetchall()
            }
        finally:
            con.close()

    by_horizon = {}
    for h in HORIZONS:
        part = [r for r in rows if int(r.get("horizon_sec") or 0) == h]
        anchor = [
            r for r in part
            if str(r.get("jev_verdict") or "").upper() == "APPROVE"
            and int(r.get("tech_score") or 0) >= 3
        ]
        anchor_metrics = _metrics(anchor)
        by_pair = {}
        for pair in sorted({str(r.get("pair") or "") for r in anchor if r.get("pair")}):
            by_pair[pair] = _metrics([r for r in anchor if str(r.get("pair")) == pair])

        combo_values = [
            "BOTH_AGREE","BOTH_CONFLICT","MIXED","PARTIAL_AGREE",
            "PARTIAL_CONFLICT","NEUTRAL","PARTIAL","NO_DATA"
        ]
        combo = _breakdown(anchor, "combined_state", combo_values)
        positive = {k:v for k,v in combo.items() if v["cluster_n"] and v["cluster_avg_net_pct"] > 0}
        toxic = {k:v for k,v in combo.items() if v["cluster_n"] and v["cluster_avg_net_pct"] <= 0}

        by_horizon[str(h)] = {
            "all":_metrics(part),
            "anchor_jev_approve_tech3plus":anchor_metrics,
            "research_state":_research_state(int(anchor_metrics.get("cluster_n") or 0)),
            "by_investing_alignment":_breakdown(anchor, "investing_alignment", ["AGREE","CONFLICT","NEUTRAL","NO_DATA"]),
            "by_macro_alignment":_breakdown(anchor, "macro_alignment", ["AGREE","CONFLICT","NEUTRAL","NO_DATA"]),
            "by_combined":combo,
            "by_pair":by_pair,
            "positive_clusters":positive,
            "toxic_clusters":toxic,
        }

    return {
        "status":"ok",
        "mode":"SHADOW_ONLY",
        "horizons_sec":list(HORIZONS),
        "cluster_sec":CLUSTER_SEC,
        "open":counts.get("OPEN",0),
        "closed":counts.get("CLOSED",0),
        "skipped":counts.get("SKIPPED",0),
        "by_horizon":by_horizon,
        "discovery_rule":"cluster_n 30 => WATCH only; require 30-50 new independent clusters before confirmation review",
        "auto_gate_enable":False,
        "changes_paper_execution":False,
        "changes_trading_decisions":False,
        "live_execution":False,
    }


def status() -> dict:
    return {
        "enabled":ENABLED,
        "mode":"SHADOW_ONLY",
        "cache_sec":CACHE_SEC,
        "max_age_sec":MAX_AGE_SEC,
        "horizons_sec":list(HORIZONS),
        "investing_cached_symbols":len(_INV_CACHE),
        "macro_cached":bool(_MACRO_CACHE),
        "queue_size":_Q.qsize(),
        "workers":WORKER_COUNT,
        "db_path":DB_PATH,
        "investing_source":"investing.com technical pages",
        "macro_source":"Yahoo Finance chart data",
        "changes_paper_execution":False,
        "changes_trading_decisions":False,
        "live_execution":False,
    }

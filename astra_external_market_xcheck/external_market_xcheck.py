"""MYSHKA / ASTRA - External Market XCheck V1 (SHADOW only).

Adds two diagnostic layers:
1) Investing.com crypto technical consensus (30m / 1h / 5h / 1d).
2) Cross-market macro context (Nasdaq 100 / DXY / Gold / WTI / VIX) from public Yahoo chart data.

Safety invariants:
- Never changes r["action"] or r["reason"].
- Never creates/rescues/rejects a trade.
- Never routes orders.
- Stores forward-only 5m/10m/15m outcomes for research.
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

DB_PATH = os.getenv("EXTERNAL_XCHECK_DB_PATH", "/data/myshka_external_xcheck.sqlite3")
ENABLED = os.getenv("EXTERNAL_XCHECK_ENABLED", "true").lower() in {"1","true","yes","on"}
INVESTING_ENABLED = os.getenv("INVESTING_XCHECK_ENABLED", "true").lower() in {"1","true","yes","on"}
MACRO_ENABLED = os.getenv("MACRO_CROSSMARKET_ENABLED", "true").lower() in {"1","true","yes","on"}

INVESTING_BASE_URL = os.getenv("INVESTING_BASE_URL", "https://www.investing.com").rstrip("/")
INVESTING_CACHE_SEC = max(60, int(os.getenv("INVESTING_XCHECK_CACHE_SEC", "180")))
INVESTING_MAX_AGE_SEC = max(INVESTING_CACHE_SEC, int(os.getenv("INVESTING_XCHECK_MAX_AGE_SEC", "600")))
HTTP_TIMEOUT_SEC = max(1.0, float(os.getenv("EXTERNAL_XCHECK_HTTP_TIMEOUT_SEC", "5")))
INVESTING_WORKERS = max(1, min(4, int(os.getenv("INVESTING_XCHECK_WORKERS", "2"))))

MACRO_CACHE_SEC = max(60, int(os.getenv("MACRO_CROSSMARKET_CACHE_SEC", "120")))
MACRO_MAX_AGE_SEC = max(MACRO_CACHE_SEC, int(os.getenv("MACRO_CROSSMARKET_MAX_AGE_SEC", "420")))
YAHOO_BASE_URL = os.getenv("YAHOO_CHART_BASE_URL", "https://query1.finance.yahoo.com/v8/finance/chart").rstrip("/")

HORIZONS = tuple(sorted({
    int(x.strip()) for x in os.getenv("EXTERNAL_XCHECK_HORIZONS_SEC", "300,600,900").split(",") if x.strip()
}))
MAX_SETTLE_DELAY_SEC = max(30, int(os.getenv("EXTERNAL_XCHECK_MAX_SETTLE_DELAY_SEC", "120")))
CLUSTER_SEC = max(60, int(os.getenv("EXTERNAL_XCHECK_CLUSTER_SEC", "300")))

INVESTING_SLUGS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "xrp",
    "DOGE": "dogecoin",
    "SUI": "sui",
    "NEAR": "near-protocol",
    "WLD": "worldcoin-org",
    "QNT": "quant",
    "ENA": "ethena",
    "ZEC": "zcash",
    "HYPE": "hyperliquid",
    "PUMPFUN": "pump-fun",
}

MACRO_SYMBOLS = {
    "NASDAQ100": {"yahoo": "NQ=F", "sign": 1.0, "weight": 1.5},
    "DXY": {"yahoo": "DX-Y.NYB", "sign": -1.0, "weight": 1.2},
    "GOLD": {"yahoo": "GC=F", "sign": -1.0, "weight": 0.5},
    "WTI": {"yahoo": "CL=F", "sign": -1.0, "weight": 0.2},
    "VIX": {"yahoo": "^VIX", "sign": -1.0, "weight": 1.5},
}
MACRO_EPS_PCT = max(0.0, float(os.getenv("MACRO_CROSSMARKET_EPS_PCT", "0.03")))
MACRO_SCORE_THRESHOLD = max(0.1, float(os.getenv("MACRO_CROSSMARKET_SCORE_THRESHOLD", "0.70")))
MACRO_BAR_MAX_AGE_SEC = max(300, int(os.getenv("MACRO_CROSSMARKET_BAR_MAX_AGE_SEC", "7200")))

RATING_SCORE = {"STRONG SELL": -2, "SELL": -1, "NEUTRAL": 0, "BUY": 1, "STRONG BUY": 2}
RATING_WEIGHTS = {"30m": 0.35, "1h": 0.35, "5h": 0.20, "1d": 0.10}
INVESTING_DIRECTION_THRESHOLD = max(0.1, float(os.getenv("INVESTING_XCHECK_DIRECTION_THRESHOLD", "0.35")))

_LOCK = threading.RLock()
_INV_CACHE: dict[str, dict] = {}
_INV_Q: "queue.Queue[str]" = queue.Queue(maxsize=200)
_INV_QUEUED: set[str] = set()
_WORKERS_STARTED = False
_MACRO_CACHE: dict[str, Any] = {"fetched_at": 0.0, "assets": {}, "state": "NO_DATA", "score": None}
_MACRO_REFRESHING = False


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
                CREATE TABLE IF NOT EXISTS external_xcheck_outcomes(
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
                    edge_pct REAL,
                    total_cost_pct REAL,
                    investing_state TEXT,
                    investing_direction TEXT,
                    investing_score REAL,
                    macro_state TEXT,
                    macro_regime TEXT,
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
            con.execute("CREATE INDEX IF NOT EXISTS idx_ex_status_target ON external_xcheck_outcomes(status,target_at)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_ex_states ON external_xcheck_outcomes(combined_state,horizon_sec,status)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_ex_pair ON external_xcheck_outcomes(pair,horizon_sec,status)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_ex_cluster ON external_xcheck_outcomes(cluster_key,horizon_sec,status)")
            con.commit()
        finally:
            con.close()

        if ENABLED and INVESTING_ENABLED and not _WORKERS_STARTED:
            for i in range(INVESTING_WORKERS):
                t = threading.Thread(target=_investing_worker, name=f"investing-xcheck-{i+1}", daemon=True)
                t.start()
            _WORKERS_STARTED = True
    return status()


def _base_symbol(pair: str) -> str:
    return str(pair or "").upper().split("/")[0].split(":")[0].replace("-", "").replace("_", "")


def _market_price(r: dict) -> Optional[float]:
    m = r.get("market") or {}
    for key in ("last_price", "last", "price", "close"):
        x = _num(m.get(key))
        if x is not None and x > 0:
            return x
    candles = m.get("candles") or r.get("candles") or []
    if candles:
        c = candles[-1]
        x = _num(c.get("close") if isinstance(c, dict) else getattr(c, "close", None))
        if x is not None and x > 0:
            return x
    return None


def _side(r: dict) -> str:
    sig = r.get("signal") or {}
    return str(r.get("direction") or sig.get("direction") or "WAIT").upper()


def _http_text(url: str, timeout: Optional[float] = None) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MYSHKA-ASTRA/1.0",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout or HTTP_TIMEOUT_SEC) as resp:
        return resp.read().decode("utf-8", "replace")


def _clean_html(raw: str) -> str:
    raw = re.sub(r"(?is)<script\b.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style\b.*?</style>", " ", raw)
    txt = re.sub(r"(?s)<[^>]+>", " ", raw)
    txt = html.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def _rating_after(label: str, text: str) -> Optional[str]:
    rating = r"(Strong Sell|Strong Buy|Sell|Buy|Neutral)"
    m = re.search(re.escape(label) + r"\s*" + rating, text, flags=re.I)
    return m.group(1).upper() if m else None


def _parse_investing_summary(raw_html: str) -> dict:
    text = _clean_html(raw_html)
    summary_pos = text.lower().find("technical summary")
    if summary_pos >= 0:
        text = text[summary_pos:summary_pos + 2500]
    ratings = {
        "30m": _rating_after("30 Min", text),
        "1h": _rating_after("Hourly", text),
        "5h": _rating_after("5 Hours", text),
        "1d": _rating_after("Daily", text),
    }
    present = {k:v for k,v in ratings.items() if v in RATING_SCORE}
    if not present:
        return {"ok": False, "ratings": ratings, "score": None, "direction": "NO_DATA"}
    denom = sum(RATING_WEIGHTS[k] for k in present)
    score = sum(RATING_SCORE[v] * RATING_WEIGHTS[k] for k,v in present.items()) / denom if denom else 0.0
    normalized = score / 2.0
    if normalized > INVESTING_DIRECTION_THRESHOLD:
        direction = "LONG"
    elif normalized < -INVESTING_DIRECTION_THRESHOLD:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"
    return {"ok": True, "ratings": ratings, "score": normalized, "direction": direction}


def _fetch_investing(symbol: str) -> dict:
    now = time.time()
    slug = INVESTING_SLUGS.get(symbol)
    if not slug:
        return {
            "symbol": symbol, "fetched_at": now, "state": "NO_DATA",
            "reason": "unsupported_symbol", "ratings": {}, "score": None, "direction": "NO_DATA",
        }
    url = f"{INVESTING_BASE_URL}/crypto/{slug}/technical"
    try:
        raw = _http_text(url)
        parsed = _parse_investing_summary(raw)
        return {
            "symbol": symbol,
            "slug": slug,
            "url": url,
            "fetched_at": now,
            "state": "READY" if parsed["ok"] else "NO_DATA",
            "reason": "ok" if parsed["ok"] else "technical_summary_not_found",
            "ratings": parsed["ratings"],
            "score": parsed["score"],
            "direction": parsed["direction"],
        }
    except Exception as exc:
        return {
            "symbol": symbol, "slug": slug, "url": url, "fetched_at": now,
            "state": "NO_DATA", "reason": f"{type(exc).__name__}: {exc}",
            "ratings": {}, "score": None, "direction": "NO_DATA",
        }


def _investing_worker() -> None:
    while True:
        try:
            symbol = _INV_Q.get(timeout=2.0)
        except queue.Empty:
            continue
        try:
            snap = _fetch_investing(symbol)
            with _LOCK:
                _INV_CACHE[symbol] = snap
        except Exception:
            pass
        finally:
            with _LOCK:
                _INV_QUEUED.discard(symbol)
            _INV_Q.task_done()


def _queue_investing(symbol: str) -> None:
    if not ENABLED or not INVESTING_ENABLED or not symbol:
        return
    if symbol not in INVESTING_SLUGS:
        return
    now = time.time()
    with _LOCK:
        cur = _INV_CACHE.get(symbol)
        fresh = cur and now - float(cur.get("fetched_at") or 0.0) < INVESTING_CACHE_SEC
        if fresh or symbol in _INV_QUEUED:
            return
        _INV_QUEUED.add(symbol)
    try:
        _INV_Q.put_nowait(symbol)
    except queue.Full:
        with _LOCK:
            _INV_QUEUED.discard(symbol)


def _investing_snapshot(symbol: str) -> Optional[dict]:
    with _LOCK:
        snap = dict(_INV_CACHE.get(symbol) or {})
    if not snap:
        return None
    age = max(0.0, time.time() - float(snap.get("fetched_at") or 0.0))
    snap["age_sec"] = age
    if age > INVESTING_MAX_AGE_SEC:
        return None
    return snap


def _investing_consensus(side: str, snap: Optional[dict], symbol: str) -> dict:
    if symbol not in INVESTING_SLUGS:
        return {
            "state": "NO_DATA", "reason": "unsupported_symbol", "direction": "NO_DATA",
            "score": None, "ratings": {}, "shadow_only": True,
        }
    if not snap or str(snap.get("state")) != "READY":
        return {
            "state": "NO_DATA", "reason": "snapshot_missing_or_not_ready", "direction": "NO_DATA",
            "score": None, "ratings": {}, "shadow_only": True,
        }
    d = str(snap.get("direction") or "NO_DATA").upper()
    if d == "NEUTRAL":
        state = "NEUTRAL"
    elif d == side:
        state = "AGREE"
    elif d in {"LONG","SHORT"}:
        state = "CONFLICT"
    else:
        state = "NO_DATA"
    return {
        "state": state,
        "reason": str(snap.get("reason") or "ok"),
        "direction": d,
        "score": _num(snap.get("score")),
        "ratings": dict(snap.get("ratings") or {}),
        "age_sec": _num(snap.get("age_sec")),
        "slug": snap.get("slug"),
        "shadow_only": True,
    }


def _yahoo_change(symbol: str) -> dict:
    q = urllib.parse.quote(symbol, safe="")
    url = f"{YAHOO_BASE_URL}/{q}?interval=5m&range=1d&includePrePost=true"
    raw = _http_text(url)
    data = json.loads(raw)
    result = (((data or {}).get("chart") or {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        raise RuntimeError("yahoo_result_missing")
    quote = ((((result.get("indicators") or {}).get("quote") or [{}])[0]) or {})
    timestamps = list(result.get("timestamp") or [])
    closes_raw = list(quote.get("close") or [])
    points = []
    for i, x in enumerate(closes_raw):
        if _num(x) is None or float(x) <= 0:
            continue
        ts = float(timestamps[i]) if i < len(timestamps) and _num(timestamps[i]) is not None else None
        points.append((ts, float(x)))
    if len(points) < 2:
        raise RuntimeError("insufficient_5m_bars")
    old_ts, old = points[-2]
    new_ts, new = points[-1]
    if new_ts is not None and time.time() - new_ts > MACRO_BAR_MAX_AGE_SEC:
        raise RuntimeError("stale_5m_bar")
    chg = (new / old - 1.0) * 100.0
    return {"last": new, "change_5m_pct": chg, "points": len(points), "bar_ts": new_ts}


def _fetch_macro() -> dict:
    now = time.time()
    assets = {}
    weighted = 0.0
    weight_total = 0.0
    for name, cfg in MACRO_SYMBOLS.items():
        try:
            row = _yahoo_change(str(cfg["yahoo"]))
            change = float(row["change_5m_pct"])
            if abs(change) <= MACRO_EPS_PCT:
                direction = 0.0
            else:
                direction = 1.0 if change > 0 else -1.0
            contribution = direction * float(cfg["sign"]) * float(cfg["weight"])
            assets[name] = {
                **row,
                "ok": True,
                "risk_contribution": contribution,
                "yahoo_symbol": cfg["yahoo"],
            }
            weighted += contribution
            weight_total += float(cfg["weight"])
        except Exception as exc:
            assets[name] = {
                "ok": False, "change_5m_pct": None, "last": None,
                "risk_contribution": 0.0, "yahoo_symbol": cfg["yahoo"],
                "error": f"{type(exc).__name__}: {exc}",
            }
    ok_n = sum(1 for v in assets.values() if v.get("ok"))
    score = weighted / weight_total if weight_total > 0 else None
    threshold = MACRO_SCORE_THRESHOLD / max(1.0, sum(float(v["weight"]) for v in MACRO_SYMBOLS.values()))
    if ok_n < 2 or score is None:
        state = "NO_DATA"
    elif score > threshold:
        state = "RISK_ON"
    elif score < -threshold:
        state = "RISK_OFF"
    else:
        state = "NEUTRAL"
    return {
        "fetched_at": now,
        "state": state,
        "score": score,
        "assets": assets,
        "sources_ok": ok_n,
    }


def _macro_worker() -> None:
    global _MACRO_REFRESHING
    try:
        snap = _fetch_macro()
        with _LOCK:
            _MACRO_CACHE.clear()
            _MACRO_CACHE.update(snap)
    except Exception:
        pass
    finally:
        with _LOCK:
            _MACRO_REFRESHING = False


def _queue_macro_refresh() -> None:
    global _MACRO_REFRESHING
    if not ENABLED or not MACRO_ENABLED:
        return
    now = time.time()
    with _LOCK:
        fresh = now - float(_MACRO_CACHE.get("fetched_at") or 0.0) < MACRO_CACHE_SEC
        if fresh or _MACRO_REFRESHING:
            return
        _MACRO_REFRESHING = True
    threading.Thread(target=_macro_worker, name="macro-crossmarket", daemon=True).start()


def _macro_snapshot() -> Optional[dict]:
    with _LOCK:
        snap = dict(_MACRO_CACHE)
        snap["assets"] = dict(_MACRO_CACHE.get("assets") or {})
    if not snap.get("fetched_at"):
        return None
    age = max(0.0, time.time() - float(snap.get("fetched_at") or 0.0))
    snap["age_sec"] = age
    if age > MACRO_MAX_AGE_SEC:
        return None
    return snap


def _macro_consensus(side: str, snap: Optional[dict]) -> dict:
    if not snap:
        return {
            "state": "NO_DATA", "regime": "NO_DATA", "score": None,
            "assets": {}, "shadow_only": True,
        }
    regime = str(snap.get("state") or "NO_DATA").upper()
    if regime == "NEUTRAL":
        state = "NEUTRAL"
    elif regime == "RISK_ON":
        state = "AGREE" if side == "LONG" else "CONFLICT"
    elif regime == "RISK_OFF":
        state = "AGREE" if side == "SHORT" else "CONFLICT"
    else:
        state = "NO_DATA"
    return {
        "state": state,
        "regime": regime,
        "score": _num(snap.get("score")),
        "age_sec": _num(snap.get("age_sec")),
        "sources_ok": int(snap.get("sources_ok") or 0),
        "assets": dict(snap.get("assets") or {}),
        "shadow_only": True,
    }


def _combined(inv_state: str, macro_state: str) -> str:
    a = str(inv_state or "NO_DATA").upper()
    b = str(macro_state or "NO_DATA").upper()
    if a == "AGREE" and b == "AGREE":
        return "BOTH_AGREE"
    if a == "CONFLICT" and b == "CONFLICT":
        return "BOTH_CONFLICT"
    if {a,b} == {"AGREE","CONFLICT"}:
        return "MIXED"
    if "AGREE" in {a,b}:
        return "PARTIAL_AGREE"
    if "CONFLICT" in {a,b}:
        return "PARTIAL_CONFLICT"
    if a == "NEUTRAL" or b == "NEUTRAL":
        return "NEUTRAL"
    return "NO_DATA"


def _settle(results: list[dict], now: float) -> dict:
    by_pair = {str(r.get("pair") or ""): r for r in results or [] if r.get("pair")}
    closed = skipped = 0
    with _LOCK, _conn() as con:
        rows = con.execute(
            "SELECT * FROM external_xcheck_outcomes WHERE status='OPEN' AND target_at<=? ORDER BY target_at",
            (now,),
        ).fetchall()
        for row in rows:
            delay = max(0.0, now - float(row["target_at"]))
            if delay > MAX_SETTLE_DELAY_SEC:
                con.execute(
                    "UPDATE external_xcheck_outcomes SET status='SKIPPED',settled_at=?,settle_delay_sec=? WHERE id=?",
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
                UPDATE external_xcheck_outcomes
                SET status='CLOSED',exit_price=?,settled_at=?,settle_delay_sec=?,
                    gross_pct=?,net_pct=?,direction_hit=?
                WHERE id=? AND status='OPEN'
                """,
                (exit_price,now,delay,gross,net,1 if gross>0 else 0,int(row["id"])),
            )
            closed += 1
        con.commit()
    return {"closed":closed,"skipped":skipped}


def observe_results(results: list[dict], now: Optional[float] = None) -> dict:
    """Attach external xchecks and record forward-only outcomes. Never changes action/reason."""
    try:
        init()
        ts = float(now if now is not None else time.time())
        settled = _settle(results or [], ts)
        _queue_macro_refresh()
        macro_snap = _macro_snapshot()
        attached = created = 0
        with _LOCK, _conn() as con:
            for r in results or []:
                side = _side(r)
                if side not in {"LONG","SHORT"}:
                    r["investing_xcheck"] = {"state":"NOT_APPLICABLE","shadow_only":True}
                    r["macro_crossmarket"] = {"state":"NOT_APPLICABLE","shadow_only":True}
                    r["external_xcheck"] = {"state":"NOT_APPLICABLE","shadow_only":True}
                    continue
                pair = str(r.get("pair") or "")
                symbol = _base_symbol(pair)
                _queue_investing(symbol)
                inv = _investing_consensus(side, _investing_snapshot(symbol), symbol)
                macro = _macro_consensus(side, macro_snap)
                combo = _combined(inv.get("state"), macro.get("state"))
                r["investing_xcheck"] = inv
                r["macro_crossmarket"] = macro
                r["external_xcheck"] = {
                    "state": combo,
                    "investing_state": inv.get("state"),
                    "macro_state": macro.get("state"),
                    "shadow_only": True,
                }
                attached += 1
                price = _market_price(r)
                if not pair or price is None:
                    continue
                sig = r.get("signal") or {}
                edge = r.get("edge") or {}
                source_minute = int(ts // 60) * 60
                cluster_bucket = int(ts // CLUSTER_SEC) * CLUSTER_SEC
                cluster_key = f"{pair}|{side}|{cluster_bucket}"
                for h in HORIZONS:
                    cur = con.execute(
                        """
                        INSERT OR IGNORE INTO external_xcheck_outcomes(
                            pair,side,source_minute,cluster_bucket,cluster_key,opened_at,target_at,horizon_sec,status,
                            entry_price,action,reason,tech_score,edge_pct,total_cost_pct,
                            investing_state,investing_direction,investing_score,
                            macro_state,macro_regime,macro_score,combined_state
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            pair,side,source_minute,cluster_bucket,cluster_key,ts,ts+int(h),int(h),"OPEN",
                            price,str(r.get("action") or ""),str(r.get("reason") or ""),
                            int(sig.get("tech_score") or 0),_num(edge.get("net_edge_pct")),_num(edge.get("total_cost_pct")),
                            str(inv.get("state") or "NO_DATA"),str(inv.get("direction") or "NO_DATA"),_num(inv.get("score")),
                            str(macro.get("state") or "NO_DATA"),str(macro.get("regime") or "NO_DATA"),_num(macro.get("score")),
                            combo,
                        ),
                    )
                    created += int(bool(cur.rowcount))
            con.commit()
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
    for r in sorted(rows, key=lambda x:(float(x.get("opened_at") or 0),int(x.get("id") or 0))):
        key = str(r.get("cluster_key") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _metrics(rows: list[dict]) -> dict:
    vals = [float(r["net_pct"]) for r in rows if r.get("net_pct") is not None]
    cl = _cluster_rows(rows)
    cvals = [float(r["net_pct"]) for r in cl if r.get("net_pct") is not None]
    wins = sum(1 for x in vals if x > 0)
    cwins = sum(1 for x in cvals if x > 0)
    return {
        "n":len(vals),
        "win_rate_pct":wins/len(vals)*100.0 if vals else 0.0,
        "avg_net_pct":sum(vals)/len(vals) if vals else 0.0,
        "profit_factor":_pf(vals),
        "cluster_n":len(cvals),
        "cluster_win_rate_pct":cwins/len(cvals)*100.0 if cvals else 0.0,
        "cluster_avg_net_pct":sum(cvals)/len(cvals) if cvals else 0.0,
        "cluster_profit_factor":_pf(cvals),
    }


def _sample_state(cluster_n: int) -> str:
    if cluster_n < 30:
        return "COLD"
    if cluster_n < 50:
        return "WATCH"
    if cluster_n < 150:
        return "CONFIRMING"
    return "MATURE"


def report() -> dict:
    init()
    with _LOCK, _conn() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM external_xcheck_outcomes WHERE status='CLOSED' ORDER BY opened_at,id"
        ).fetchall()]
        counts = {
            str(r["status"]):int(r["n"]) for r in con.execute(
                "SELECT status,COUNT(*) n FROM external_xcheck_outcomes GROUP BY status"
            ).fetchall()
        }
    combined_states = ("BOTH_AGREE","BOTH_CONFLICT","MIXED","PARTIAL_AGREE","PARTIAL_CONFLICT","NEUTRAL","NO_DATA")
    simple_states = ("AGREE","CONFLICT","NEUTRAL","NO_DATA")
    by_horizon = {}
    for h in HORIZONS:
        part = [r for r in rows if int(r.get("horizon_sec") or 0)==int(h)]
        allm = _metrics(part)
        by_pair = {}
        for pair in sorted({str(r.get("pair") or "") for r in part if r.get("pair")}):
            by_pair[pair] = _metrics([r for r in part if str(r.get("pair") or "") == pair])
        by_horizon[str(h)] = {
            "all": allm,
            "sample_state": _sample_state(int(allm.get("cluster_n") or 0)),
            "by_investing": {s:_metrics([r for r in part if str(r.get("investing_state") or "NO_DATA")==s]) for s in simple_states},
            "by_macro": {s:_metrics([r for r in part if str(r.get("macro_state") or "NO_DATA")==s]) for s in simple_states},
            "by_combined": {s:_metrics([r for r in part if str(r.get("combined_state") or "NO_DATA")==s]) for s in combined_states},
            "by_pair": by_pair,
        }
    return {
        "status":"ok",
        "mode":"SHADOW_ONLY_FORWARD_EVALUATION",
        "horizons_sec":list(HORIZONS),
        "cluster_sec":CLUSTER_SEC,
        "open":counts.get("OPEN",0),
        "closed":counts.get("CLOSED",0),
        "skipped":counts.get("SKIPPED",0),
        "by_horizon":by_horizon,
        "research_rule":"WATCH at cluster_n>=30 only; confirm on new independent forward clusters before any gate change.",
        "changes_paper_execution":False,
        "changes_trading_decisions":False,
        "live_execution":False,
    }


def status() -> dict:
    with _LOCK:
        inv_ready = sum(1 for v in _INV_CACHE.values() if str(v.get("state"))=="READY")
        macro = dict(_MACRO_CACHE)
    return {
        "enabled":ENABLED,
        "mode":"SHADOW_ONLY",
        "investing_enabled":INVESTING_ENABLED,
        "investing_supported_symbols":sorted(INVESTING_SLUGS),
        "investing_cache_symbols":len(_INV_CACHE),
        "investing_ready_symbols":inv_ready,
        "investing_queue_size":_INV_Q.qsize(),
        "investing_workers":INVESTING_WORKERS,
        "macro_enabled":MACRO_ENABLED,
        "macro_state":macro.get("state") or "NO_DATA",
        "macro_sources_ok":int(macro.get("sources_ok") or 0),
        "macro_assets":list(MACRO_SYMBOLS),
        "horizons_sec":list(HORIZONS),
        "db_path":DB_PATH,
        "changes_trade_decision":False,
        "changes_paper_execution":False,
        "live_execution":False,
    }

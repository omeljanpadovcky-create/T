"""Background market/context collector for MYSHKA / ASTRA.

Runs independently of the trading scan loop and keeps a rolling, persistent
history that can be attached to STRICT candidates in SHADOW mode.

Sources:
- Bybit linear ticker snapshot every cycle (price, spread, funding, OI, turnover)
- Bybit long/short account ratio on a slower cadence
- Optional RSS feeds for recent crypto headlines
- Optional external events pushed by n8n/APIs through /context/ingest

This module deliberately does NOT make trade decisions. It only collects and
summarises context. The execution pipeline remains TECH -> EDGE -> JEV -> GUARD.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
import html
import json
import os
import re
import sqlite3
import threading
import time
from typing import Any, Optional
from xml.etree import ElementTree as ET

import requests

from .config import CONFIG

BYBIT_PUBLIC_BASE_URL = os.getenv("BYBIT_PUBLIC_BASE_URL", "https://api.bybit.com").rstrip("/")
HTTP_TIMEOUT_SEC = float(os.getenv("BYBIT_HTTP_TIMEOUT_SEC", "8"))

ENABLED = os.getenv("CONTEXT_COLLECTOR_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
INTERVAL_SEC = max(15, int(os.getenv("CONTEXT_COLLECT_INTERVAL_SEC", "60")))
DETAIL_INTERVAL_SEC = max(INTERVAL_SEC, int(os.getenv("CONTEXT_DETAIL_INTERVAL_SEC", "300")))
HISTORY_MINUTES = max(5, min(240, int(os.getenv("CONTEXT_HISTORY_MINUTES", "30"))))
RETENTION_HOURS = max(1, min(168, int(os.getenv("CONTEXT_RETENTION_HOURS", "48"))))
MAX_HEADLINES = max(0, min(50, int(os.getenv("CONTEXT_MAX_HEADLINES", "12"))))
NEWS_LOOKBACK_MINUTES = max(30, min(720, int(os.getenv("CONTEXT_NEWS_LOOKBACK_MINUTES", "180"))))
CONTEXT_DB_PATH = os.getenv("CONTEXT_DB_PATH", "/data/myshka_context.sqlite3")

# Public RSS feeds only. Failures are non-fatal and one broken source must not
# suppress the others. Override/disable with CONTEXT_RSS_URLS.
_DEFAULT_RSS = ",".join([
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
])
RSS_URLS = [x.strip() for x in os.getenv("CONTEXT_RSS_URLS", _DEFAULT_RSS).split(",") if x.strip()]

_EXCLUDED_BASES = {"USDC", "USDE", "DAI", "FDUSD", "TUSD", "PYUSD", "USDP", "EUR", "EURC"}

_LOCK = threading.RLock()
_THREAD: Optional[threading.Thread] = None
_STOP = threading.Event()
_STATUS = {
    "enabled": ENABLED,
    "running": False,
    "last_cycle_at": None,
    "last_success_at": None,
    "last_detail_at": None,
    "last_news_at": None,
    "news_sources_ok": 0,
    "news_sources_failed": 0,
    "last_news_error": None,
    "cycles": 0,
    "pairs": [],
    "last_error": None,
    "db_path": CONTEXT_DB_PATH,
    "history_minutes": HISTORY_MINUTES,
    "interval_sec": INTERVAL_SEC,
    "detail_interval_sec": DETAIL_INTERVAL_SEC,
}
_LONG_SHORT_CACHE: dict[str, dict[str, float]] = {}
_NEWS_CACHE: list[dict[str, Any]] = []


def _db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(CONTEXT_DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(CONTEXT_DB_PATH, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS context_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            pair TEXT NOT NULL,
            source TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    con.execute("CREATE INDEX IF NOT EXISTS idx_context_pair_ts ON context_samples(pair, ts)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_context_source_ts ON context_samples(source, ts)")
    return con


def _write_sample(*, ts: float, pair: str, source: str, kind: str, payload: dict) -> None:
    with _db() as con:
        con.execute(
            "INSERT INTO context_samples(ts,pair,source,kind,payload) VALUES(?,?,?,?,?)",
            (float(ts), str(pair), str(source), str(kind), json.dumps(payload, separators=(",", ":"), ensure_ascii=False)),
        )


def _purge_old(now: Optional[float] = None) -> None:
    cutoff = float(now or time.time()) - RETENTION_HOURS * 3600
    with _db() as con:
        con.execute("DELETE FROM context_samples WHERE ts < ?", (cutoff,))


def _get_json(path: str, params: dict) -> dict:
    r = requests.get(f"{BYBIT_PUBLIC_BASE_URL}{path}", params=params, timeout=HTTP_TIMEOUT_SEC)
    r.raise_for_status()
    data = r.json()
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit {path}: {data.get('retCode')} {data.get('retMsg')}")
    return data


def _pair_from_symbol(symbol: str) -> Optional[str]:
    s = str(symbol or "").upper()
    if not s.endswith("USDT") or len(s) <= 4:
        return None
    base = s[:-4]
    if base in _EXCLUDED_BASES:
        return None
    return f"{base}/USDT:USDT"


def _symbol(pair: str) -> str:
    return pair.split("/")[0].replace("-", "").upper() + "USDT"


def _spread_pct(t: dict) -> Optional[float]:
    try:
        bid = float(t.get("bid1Price") or 0)
        ask = float(t.get("ask1Price") or 0)
        if bid <= 0 or ask <= 0 or ask < bid:
            return None
        mid = (bid + ask) / 2.0
        return ((ask - bid) / mid) * 100 if mid else None
    except Exception:
        return None


def _select_pairs(tickers: list[dict]) -> list[str]:
    ranked: list[tuple[float, str]] = []
    for t in tickers:
        pair = _pair_from_symbol(t.get("symbol"))
        if not pair:
            continue
        try:
            turnover = float(t.get("turnover24h") or 0)
            last = float(t.get("lastPrice") or 0)
        except Exception:
            continue
        spread = _spread_pct(t)
        if last <= 0 or turnover < CONFIG.DYNAMIC_UNIVERSE_MIN_TURNOVER_USDT:
            continue
        if spread is None or spread > CONFIG.MAX_SPREAD_PCT:
            continue
        ranked.append((turnover, pair))
    ranked.sort(key=lambda x: x[0], reverse=True)
    n = int(getattr(CONFIG, "DYNAMIC_UNIVERSE_TOP_N", 15) or 15)
    out = [p for _, p in ranked[:n]]
    return out or list(CONFIG.PAIRS)


def _float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def _collect_long_short(pair: str) -> Optional[dict[str, float]]:
    data = _get_json(
        "/v5/market/account-ratio",
        {"category": "linear", "symbol": _symbol(pair), "period": "5min", "limit": 2},
    )
    rows = data.get("result", {}).get("list", []) or []
    if not rows:
        return None
    row = rows[0]
    buy = _float(row.get("buyRatio"))
    sell = _float(row.get("sellRatio"))
    if buy is None and sell is None:
        return None
    ratio = (buy / sell) if buy is not None and sell not in (None, 0) else None
    return {
        "long_ratio": buy,
        "short_ratio": sell,
        "long_short_ratio": ratio,
        "ratio_ts_ms": _float(row.get("timestamp")),
    }


def _clean_summary(v: Any) -> str:
    raw = html.unescape(str(v or ""))
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:1600]


def _rss_items(url: str) -> list[dict[str, Any]]:
    r = requests.get(url, timeout=max(5.0, HTTP_TIMEOUT_SEC), headers={"User-Agent": "MYSHKA-ASTRA/1.0"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out: list[dict[str, Any]] = []

    # RSS 2.x
    for item in root.findall(".//item")[:30]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        summary = _clean_summary(
            item.findtext("description")
            or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
            or ""
        )
        pub = (item.findtext("pubDate") or "").strip()
        ts = time.time()
        if pub:
            try:
                ts = parsedate_to_datetime(pub).timestamp()
            except Exception:
                pass
        if title:
            out.append({
                "ts": ts, "title": title[:300], "summary": summary,
                "url": link[:1000], "feed": url,
            })

    # Atom fallback.
    if not out:
        for entry in root.findall(".//{*}entry")[:30]:
            title = (entry.findtext("{*}title") or "").strip()
            summary = _clean_summary(entry.findtext("{*}summary") or entry.findtext("{*}content") or "")
            link = ""
            link_node = entry.find("{*}link")
            if link_node is not None:
                link = str(link_node.attrib.get("href") or "").strip()
            pub = (entry.findtext("{*}published") or entry.findtext("{*}updated") or "").strip()
            ts = time.time()
            if pub:
                try:
                    ts = parsedate_to_datetime(pub).timestamp()
                except Exception:
                    try:
                        ts = __import__("datetime").datetime.fromisoformat(pub.replace("Z","+00:00")).timestamp()
                    except Exception:
                        pass
            if title:
                out.append({
                    "ts": ts, "title": title[:300], "summary": summary,
                    "url": link[:1000], "feed": url,
                })
    return out

def _refresh_news(now: float) -> dict:
    global _NEWS_CACHE
    if not RSS_URLS or MAX_HEADLINES <= 0:
        with _LOCK:
            _STATUS["news_sources_ok"] = 0
            _STATUS["news_sources_failed"] = 0
            _STATUS["last_news_error"] = "RSS disabled"
        return {"ok": 0, "failed": 0, "headlines": 0}

    found: list[dict[str, Any]] = []
    ok = 0
    failures: list[str] = []
    for url in RSS_URLS:
        try:
            items = _rss_items(url)
            if items:
                ok += 1
                found.extend(items)
            else:
                failures.append(f"{url}: empty")
        except Exception as exc:
            failures.append(f"{url}: {type(exc).__name__}")

    dedup: dict[str, dict[str, Any]] = {}
    for x in sorted(found, key=lambda z: float(z.get("ts") or 0), reverse=True):
        key = str(x.get("url") or x.get("title") or "")
        if key and key not in dedup:
            dedup[key] = x
    _NEWS_CACHE = list(dedup.values())[:MAX_HEADLINES]

    recent_cutoff = now - NEWS_LOOKBACK_MINUTES * 60
    for x in _NEWS_CACHE:
        if float(x.get("ts") or now) >= recent_cutoff:
            _write_sample(ts=float(x.get("ts") or now), pair="*", source="rss", kind="headline", payload=x)

    with _LOCK:
        _STATUS["news_sources_ok"] = ok
        _STATUS["news_sources_failed"] = len(failures)
        _STATUS["last_news_error"] = "; ".join(failures[:3]) if failures else None
    return {"ok": ok, "failed": len(failures), "headlines": len(_NEWS_CACHE)}

def _collect_once() -> None:
    global _LONG_SHORT_CACHE
    now = time.time()
    raw = _get_json("/v5/market/tickers", {"category": "linear"})
    tickers = raw.get("result", {}).get("list", []) or []
    pairs = _select_pairs(tickers)
    ticker_by_pair = {_pair_from_symbol(t.get("symbol")): t for t in tickers}

    with _LOCK:
        last_detail = float(_STATUS.get("last_detail_at") or 0)
        last_news = float(_STATUS.get("last_news_at") or 0)
    do_detail = now - last_detail >= DETAIL_INTERVAL_SEC
    do_news = now - last_news >= DETAIL_INTERVAL_SEC

    if do_detail:
        fresh: dict[str, dict[str, float]] = {}
        with ThreadPoolExecutor(max_workers=min(6, max(1, len(pairs)))) as pool:
            jobs = {pool.submit(_collect_long_short, pair): pair for pair in pairs}
            for fut in as_completed(jobs):
                pair = jobs[fut]
                try:
                    x = fut.result()
                    if x:
                        fresh[pair] = x
                except Exception:
                    continue
        if fresh:
            _LONG_SHORT_CACHE.update(fresh)
        with _LOCK:
            _STATUS["last_detail_at"] = now

    if do_news:
        try:
            _refresh_news(now)
        finally:
            with _LOCK:
                _STATUS["last_news_at"] = now

    for pair in pairs:
        t = ticker_by_pair.get(pair) or {}
        last = _float(t.get("lastPrice"))
        if last is None or last <= 0:
            continue
        sample = {
            "last_price": last,
            "mark_price": _float(t.get("markPrice")),
            "index_price": _float(t.get("indexPrice")),
            "spread_pct": _spread_pct(t),
            "turnover24h": _float(t.get("turnover24h")),
            "volume24h": _float(t.get("volume24h")),
            "price24h_pct": (_float(t.get("price24hPcnt")) or 0.0) * 100.0,
            "funding_rate_pct": (_float(t.get("fundingRate")) or 0.0) * 100.0,
            "open_interest": _float(t.get("openInterest")),
            "open_interest_value": _float(t.get("openInterestValue")),
            "next_funding_time_ms": _float(t.get("nextFundingTime")),
        }
        if pair in _LONG_SHORT_CACHE:
            sample.update(_LONG_SHORT_CACHE[pair])
        _write_sample(ts=now, pair=pair, source="bybit", kind="market", payload=sample)

    _purge_old(now)
    with _LOCK:
        _STATUS["last_cycle_at"] = now
        _STATUS["last_success_at"] = now
        _STATUS["cycles"] = int(_STATUS.get("cycles") or 0) + 1
        _STATUS["pairs"] = pairs
        _STATUS["last_error"] = None


def _loop() -> None:
    with _LOCK:
        _STATUS["running"] = True
    while not _STOP.is_set():
        started = time.time()
        try:
            _collect_once()
        except Exception as exc:
            with _LOCK:
                _STATUS["last_cycle_at"] = time.time()
                _STATUS["last_error"] = f"{type(exc).__name__}: {exc}"
        elapsed = max(0.0, time.time() - started)
        _STOP.wait(max(1.0, INTERVAL_SEC - elapsed))
    with _LOCK:
        _STATUS["running"] = False


def start() -> dict:
    global _THREAD
    if not ENABLED:
        return status()
    with _LOCK:
        if _THREAD and _THREAD.is_alive():
            return status()
        _STOP.clear()
        try:
            with _db() as _:
                pass
        except Exception as exc:
            _STATUS["last_error"] = f"db init: {type(exc).__name__}: {exc}"
        _THREAD = threading.Thread(target=_loop, name="myshka-context-collector", daemon=True)
        _THREAD.start()
    return status()


def stop() -> None:
    _STOP.set()


def status() -> dict:
    with _LOCK:
        out = dict(_STATUS)
    last = float(out.get("last_success_at") or 0)
    out["age_sec"] = round(max(0.0, time.time() - last), 1) if last else None
    out["rss_feeds"] = len(RSS_URLS)
    out["headline_cache"] = len(_NEWS_CACHE)
    out["news_lookback_minutes"] = NEWS_LOOKBACK_MINUTES
    out["rss_urls"] = list(RSS_URLS)
    return out


def _rows(pair: str, minutes: int) -> list[tuple[float, dict]]:
    cutoff = time.time() - max(1, int(minutes)) * 60
    with _db() as con:
        cur = con.execute(
            "SELECT ts,payload FROM context_samples WHERE pair=? AND source='bybit' AND kind='market' AND ts>=? ORDER BY ts ASC",
            (pair, cutoff),
        )
        out = []
        for ts, payload in cur.fetchall():
            try:
                out.append((float(ts), json.loads(payload)))
            except Exception:
                continue
        return out


def _pct_change(rows: list[tuple[float, dict]], minutes: int) -> Optional[float]:
    if len(rows) < 2:
        return None
    latest_ts, latest = rows[-1]
    latest_price = _float(latest.get("last_price"))
    if not latest_price:
        return None
    target = latest_ts - minutes * 60
    chosen = rows[0]
    for row in rows:
        if row[0] <= target:
            chosen = row
        else:
            break
    old_price = _float(chosen[1].get("last_price"))
    if not old_price:
        return None
    return ((latest_price - old_price) / old_price) * 100.0


def _oi_change(rows: list[tuple[float, dict]], minutes: int) -> Optional[float]:
    if len(rows) < 2:
        return None
    latest_ts, latest = rows[-1]
    latest_oi = _float(latest.get("open_interest"))
    if latest_oi in (None, 0):
        return None
    target = latest_ts - minutes * 60
    chosen = rows[0]
    for row in rows:
        if row[0] <= target:
            chosen = row
        else:
            break
    old_oi = _float(chosen[1].get("open_interest"))
    if old_oi in (None, 0):
        return None
    return ((latest_oi - old_oi) / old_oi) * 100.0


def _recent_external(pair: str, minutes: int, limit: int = 12) -> list[dict]:
    # Headlines/events stay useful longer than 1m market microstructure.
    cutoff = time.time() - max(1, int(minutes), NEWS_LOOKBACK_MINUTES) * 60
    with _db() as con:
        cur = con.execute(
            """
            SELECT ts,pair,source,kind,payload
            FROM context_samples
            WHERE ts>=? AND (pair=? OR pair='*') AND source!='bybit'
            ORDER BY ts DESC LIMIT ?
            """,
            (cutoff, pair, int(limit)),
        )
        out = []
        for ts, p, source, kind, payload in cur.fetchall():
            try:
                body = json.loads(payload)
            except Exception:
                body = {"raw": str(payload)}
            out.append({"ts": ts, "pair": p, "source": source, "kind": kind, "payload": body})
        return out


def snapshot(pair: str, minutes: Optional[int] = None, direction: Optional[str] = None) -> dict:
    mins = max(1, min(240, int(minutes or HISTORY_MINUTES)))
    rows = _rows(pair, mins)
    latest_ts = rows[-1][0] if rows else None
    latest = dict(rows[-1][1]) if rows else {}
    btc_rows = rows if pair.startswith("BTC/") else _rows("BTC/USDT:USDT", mins)
    out = {
        "mode": "SHADOW",
        "collector_running": bool(status().get("running")),
        "pair": pair,
        "direction": direction,
        "window_minutes": mins,
        "samples": len(rows),
        "latest_ts": latest_ts,
        "age_sec": round(max(0.0, time.time() - latest_ts), 1) if latest_ts else None,
        "price_change_5m_pct": _pct_change(rows, 5),
        "price_change_15m_pct": _pct_change(rows, 15),
        "price_change_30m_pct": _pct_change(rows, 30),
        "oi_change_5m_pct": _oi_change(rows, 5),
        "oi_change_15m_pct": _oi_change(rows, 15),
        "oi_change_30m_pct": _oi_change(rows, 30),
        "funding_rate_pct": _float(latest.get("funding_rate_pct")),
        "long_ratio": _float(latest.get("long_ratio")),
        "short_ratio": _float(latest.get("short_ratio")),
        "long_short_ratio": _float(latest.get("long_short_ratio")),
        "spread_pct": _float(latest.get("spread_pct")),
        "turnover24h": _float(latest.get("turnover24h")),
        "btc_price_change_5m_pct": _pct_change(btc_rows, 5),
        "btc_price_change_15m_pct": _pct_change(btc_rows, 15),
        "btc_price_change_30m_pct": _pct_change(btc_rows, 30),
        "external_events": _recent_external(pair, mins, limit=12),
    }
    news_status = status()
    out["external_event_count"] = len(out["external_events"])
    out["news_headline_cache"] = int(news_status.get("headline_cache") or 0)
    out["news_sources_ok"] = int(news_status.get("news_sources_ok") or 0)
    out["news_sources_failed"] = int(news_status.get("news_sources_failed") or 0)
    out["news_last_error"] = news_status.get("last_news_error")
    out["news_lookback_minutes"] = NEWS_LOOKBACK_MINUTES
    out["decision_effect"] = "NONE_SHADOW_ONLY"
    return out


def ingest_external(*, source: str, kind: str, text: str = "", pair: str = "*",
                    sentiment: Optional[str] = None, score: Optional[float] = None,
                    url: str = "", ts: Optional[float] = None, extra: Optional[dict] = None) -> dict:
    now = float(ts or time.time())
    payload = {
        "text": str(text or "")[:4000],
        "sentiment": sentiment,
        "score": score,
        "url": str(url or "")[:1000],
        "extra": extra or {},
    }
    _write_sample(ts=now, pair=pair or "*", source=source or "external", kind=kind or "event", payload=payload)
    return {"status": "ok", "ts": now, "pair": pair or "*", "source": source or "external", "kind": kind or "event"}

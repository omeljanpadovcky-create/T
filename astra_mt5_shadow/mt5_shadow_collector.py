"""MYSHKA / ASTRA - MT5 Shadow Collector V1 (Windows host, READ ONLY).

Runs on the Windows host next to an installed/logged-in MetaTrader 5 terminal.
Exposes a token-protected local HTTP snapshot API for ASTRA running in Docker.

READ-ONLY invariants:
- Uses initialize / terminal_info / account_info / symbols_get / symbol_select /
  symbol_info_tick / copy_rates_from_pos only.
- No order_send, no trade request, no position modification.
- If MT5 is unavailable, returns NO_DATA rather than affecting ASTRA decisions.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

try:
    import MetaTrader5 as mt5
except Exception as exc:
    mt5 = None
    IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    IMPORT_ERROR = None

HOST = os.getenv("MT5_SHADOW_HOST", "0.0.0.0")
PORT = max(1024, min(65535, int(os.getenv("MT5_SHADOW_PORT", "8115"))))
TOKEN = os.getenv("MT5_SHADOW_TOKEN", "")
CACHE_SEC = max(2, int(os.getenv("MT5_SHADOW_CACHE_SEC", "8")))
BARS = max(50, int(os.getenv("MT5_SHADOW_BARS", "120")))
INIT_TIMEOUT_MS = max(1000, int(os.getenv("MT5_SHADOW_INIT_TIMEOUT_MS", "10000")))

_LOCK = threading.RLock()
_CACHE: dict[str, tuple[float, dict]] = {}

DEFAULT_MAP = {
    "BTC":"BTCUSD",
    "ETH":"ETHUSD",
    "SOL":"SOLUSD",
    "XRP":"XRPUSD",
    "DOGE":"DOGEUSD",
    "XAU":"XAUUSD",
    "GOLD":"XAUUSD",
}

try:
    USER_MAP = json.loads(os.getenv("MT5_SHADOW_SYMBOL_MAP_JSON", "{}"))
    if not isinstance(USER_MAP, dict):
        USER_MAP = {}
except Exception:
    USER_MAP = {}

SYMBOL_MAP = {**DEFAULT_MAP, **{str(k).upper():str(v) for k,v in USER_MAP.items()}}

TF_NAMES = ("M5","M15","H1")


def _num(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _normalize_symbol(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _ensure_mt5() -> tuple[bool, str]:
    if mt5 is None:
        return False, f"MetaTrader5_import_failed: {IMPORT_ERROR}"
    try:
        if mt5.initialize(timeout=INIT_TIMEOUT_MS):
            info = mt5.terminal_info()
            if info is not None and bool(getattr(info, "connected", True)):
                return True, "ok"
        return False, f"initialize_failed:{mt5.last_error()}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _all_symbol_names() -> list[str]:
    try:
        rows = mt5.symbols_get()
        return [str(x.name) for x in (rows or []) if getattr(x, "name", None)]
    except Exception:
        return []


def _resolve_symbol(ticker: str) -> Optional[str]:
    ticker = str(ticker or "").upper()
    preferred = SYMBOL_MAP.get(ticker)
    names = _all_symbol_names()
    if preferred:
        if preferred in names:
            return preferred
        pn = _normalize_symbol(preferred)
        exact_norm = [n for n in names if _normalize_symbol(n) == pn]
        if exact_norm:
            return exact_norm[0]

    targets = []
    if ticker in {"XAU","GOLD"}:
        targets = ["XAUUSD","GOLDUSD"]
    else:
        targets = [ticker+"USD", ticker+"USDT"]

    normalized = [(n, _normalize_symbol(n)) for n in names]
    for target in targets:
        exact = [n for n,nn in normalized if nn == target]
        if exact:
            return exact[0]
    for target in targets:
        pref = [n for n,nn in normalized if nn.startswith(target)]
        if pref:
            pref.sort(key=len)
            return pref[0]
    return None


def _ema(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    alpha = 2.0 / (period + 1.0)
    out = sum(values[:period]) / period
    for x in values[period:]:
        out = alpha*x + (1-alpha)*out
    return out


def _rsi(values: list[float], period: int = 14) -> Optional[float]:
    if len(values) <= period:
        return None
    gains = []
    losses = []
    for a,b in zip(values[-(period+1):-1], values[-period:]):
        d = b-a
        gains.append(max(0.0,d))
        losses.append(max(0.0,-d))
    ag = sum(gains)/period
    al = sum(losses)/period
    if al <= 1e-12:
        return 100.0 if ag > 0 else 50.0
    rs = ag/al
    return 100.0 - 100.0/(1.0+rs)


def _tf_value(name: str):
    return {
        "M5":mt5.TIMEFRAME_M5,
        "M15":mt5.TIMEFRAME_M15,
        "H1":mt5.TIMEFRAME_H1,
    }[name]


def _frame(symbol: str, tf_name: str) -> dict:
    rates = mt5.copy_rates_from_pos(symbol, _tf_value(tf_name), 0, BARS)
    if rates is None or len(rates) < 30:
        return {"state":"NO_DATA","reason":"insufficient_bars","bars":0 if rates is None else len(rates)}

    closes = [float(x["close"]) for x in rates if _num(x["close"]) is not None]
    if len(closes) < 30:
        return {"state":"NO_DATA","reason":"insufficient_closes","bars":len(closes)}

    e9 = _ema(closes,9)
    e21 = _ema(closes,21)
    r = _rsi(closes,14)
    mom3 = (closes[-1]/closes[-4]-1.0)*100.0 if len(closes)>=4 and closes[-4] else 0.0

    long_votes = 0
    short_votes = 0
    if e9 is not None and e21 is not None:
        if e9 > e21: long_votes += 1
        elif e9 < e21: short_votes += 1
    if mom3 > 0.02: long_votes += 1
    elif mom3 < -0.02: short_votes += 1
    if r is not None:
        if 52 <= r <= 72: long_votes += 1
        elif 28 <= r <= 48: short_votes += 1

    if long_votes >= 2 and long_votes > short_votes:
        state = "LONG"
    elif short_votes >= 2 and short_votes > long_votes:
        state = "SHORT"
    else:
        state = "NEUTRAL"

    return {
        "state":state,
        "close":closes[-1],
        "ema9":e9,
        "ema21":e21,
        "rsi14":r,
        "momentum_3bar_pct":mom3,
        "long_votes":long_votes,
        "short_votes":short_votes,
        "bars":len(closes),
    }


def _snapshot_uncached(ticker: str) -> dict:
    now = time.time()
    ok, reason = _ensure_mt5()
    if not ok:
        return {"status":"NO_DATA","ticker":ticker,"reason":reason,"ts":now,"read_only":True}

    symbol = _resolve_symbol(ticker)
    if not symbol:
        return {
            "status":"NO_DATA","ticker":ticker,"reason":"symbol_not_found",
            "ts":now,"read_only":True,
        }

    try:
        mt5.symbol_select(symbol, True)
    except Exception:
        pass

    frames = {tf:_frame(symbol,tf) for tf in TF_NAMES}
    weights = {"M5":1.0,"M15":1.5,"H1":1.0}
    score = 0.0
    denom = 0.0
    for tf,row in frames.items():
        st = str(row.get("state") or "NO_DATA")
        if st == "LONG":
            score += weights[tf]
            denom += weights[tf]
        elif st == "SHORT":
            score -= weights[tf]
            denom += weights[tf]
        elif st == "NEUTRAL":
            denom += weights[tf]

    normalized = score/denom if denom else 0.0
    if denom == 0:
        direction = "NO_DATA"
    elif normalized >= 0.35:
        direction = "LONG"
    elif normalized <= -0.35:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    tick = mt5.symbol_info_tick(symbol)
    bid = _num(getattr(tick,"bid",None)) if tick is not None else None
    ask = _num(getattr(tick,"ask",None)) if tick is not None else None
    spread_pct = None
    if bid and ask and (bid+ask)>0:
        mid = (bid+ask)/2.0
        spread_pct = (ask-bid)/mid*100.0 if mid else None

    term = mt5.terminal_info()
    account = mt5.account_info()
    return {
        "status":"READY",
        "ticker":ticker,
        "symbol":symbol,
        "direction":direction,
        "score":normalized,
        "frames":frames,
        "tick":{"bid":bid,"ask":ask,"spread_pct":spread_pct},
        "terminal":{
            "connected":bool(getattr(term,"connected",True)) if term is not None else None,
            "trade_allowed":bool(getattr(term,"trade_allowed",False)) if term is not None else None,
            "server":str(getattr(account,"server","")) if account is not None else "",
            "company":str(getattr(account,"company","")) if account is not None else "",
            "currency":str(getattr(account,"currency","")) if account is not None else "",
        },
        "ts":now,
        "read_only":True,
    }


def snapshot(ticker: str) -> dict:
    ticker = str(ticker or "").strip().upper()
    if not ticker:
        return {"status":"NO_DATA","reason":"ticker_required","read_only":True}
    now = time.time()
    with _LOCK:
        cur = _CACHE.get(ticker)
        if cur and now-cur[0] < CACHE_SEC:
            out = dict(cur[1])
            out["cache_age_sec"] = now-cur[0]
            return out
    out = _snapshot_uncached(ticker)
    with _LOCK:
        _CACHE[ticker] = (now,out)
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "MYSHKA-MT5-SHADOW/1"

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False, separators=(",",":"), default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not TOKEN:
            return False
        return self.headers.get("X-MT5-SHADOW-TOKEN","") == TOKEN

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/health":
            self._json(200,{
                "status":"ok",
                "mt5_imported":mt5 is not None,
                "token_configured":bool(TOKEN),
                "read_only":True,
                "port":PORT,
            })
            return
        if not self._authorized():
            self._json(401,{"status":"unauthorized"})
            return
        if p.path == "/snapshot":
            qs = parse_qs(p.query)
            ticker = (qs.get("ticker") or [""])[0]
            self._json(200,snapshot(ticker))
            return
        self._json(404,{"status":"not_found"})

    def log_message(self, fmt, *args):
        return


def main() -> None:
    if not TOKEN:
        raise SystemExit("MT5_SHADOW_TOKEN is required")
    print(f"MYSHKA MT5 Shadow Collector V1 listening on {HOST}:{PORT}")
    print("READ ONLY: no MT5 trade/order API is used.")
    srv = ThreadingHTTPServer((HOST,PORT),Handler)
    try:
        srv.serve_forever()
    finally:
        try:
            if mt5 is not None:
                mt5.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()

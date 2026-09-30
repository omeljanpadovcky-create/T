"""MYSHKA / ASTRA — LIVE ARMED PREFLIGHT.

Real Freqtrade connectivity + account-state diagnostics, but no financial order
is transmitted. The module may authenticate and perform GET requests only.

It builds the final forceenter payload that a human could review in FreqUI.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

FREQTRADE_BASE_URL = os.getenv("FREQTRADE_BASE_URL", "http://host.docker.internal:8080").rstrip("/")
FREQTRADE_USERNAME = os.getenv("FREQTRADE_USERNAME", "")
FREQTRADE_PASSWORD = os.getenv("FREQTRADE_PASSWORD", "")
TIMEOUT_SEC = max(2, int(os.getenv("LIVE_ARMED_TIMEOUT_SEC", "8")))

DEFAULT_STAKE_USDT = max(1.0, float(os.getenv("LIVE_ARMED_STAKE_USDT", "10")))
DEFAULT_LEVERAGE = max(1.0, float(os.getenv("LIVE_ARMED_LEVERAGE", "1")))
MAX_STAKE_USDT = max(DEFAULT_STAKE_USDT, float(os.getenv("LIVE_ARMED_MAX_STAKE_USDT", "25")))
MAX_LEVERAGE = max(DEFAULT_LEVERAGE, float(os.getenv("LIVE_ARMED_MAX_LEVERAGE", "3")))

_ALLOWED_GETS = {
    "/api/v1/ping",
    "/api/v1/balance",
    "/api/v1/trades",
    "/api/v1/whitelist",
    "/api/v1/count",
}


def _json_request(path: str, *, method: str = "GET", auth: Optional[str] = None,
                  basic: bool = False) -> tuple[int, Any]:
    if method == "GET" and path not in _ALLOWED_GETS:
        raise RuntimeError(f"GET endpoint not allowlisted: {path}")
    if method not in {"GET", "POST"}:
        raise RuntimeError("Only GET and token-login POST are allowed")
    if method == "POST" and path != "/api/v1/token/login":
        raise RuntimeError("Financial/action POST is hard-blocked")

    headers = {"Accept": "application/json", "User-Agent": "MYSHKA-LIVE-ARMED"}
    if auth:
        headers["Authorization"] = f"Bearer {auth}"
    elif basic and FREQTRADE_USERNAME:
        raw = f"{FREQTRADE_USERNAME}:{FREQTRADE_PASSWORD}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")

    req = urllib.request.Request(FREQTRADE_BASE_URL + path, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return int(resp.status), json.loads(body)
            except Exception:
                return int(resp.status), {"raw": body[:2000]}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
        except Exception:
            data = {"raw": body[:2000]}
        return int(e.code), data
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def _token() -> tuple[Optional[str], dict]:
    if not FREQTRADE_USERNAME or not FREQTRADE_PASSWORD:
        return None, {"status": "missing_credentials"}
    code, data = _json_request("/api/v1/token/login", method="POST", basic=True)
    tok = data.get("access_token") if isinstance(data, dict) else None
    return (str(tok) if tok else None), {"status_code": code, "authenticated": bool(tok)}


def _extract_list(data: Any, *keys: str) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys:
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []


def _redact_balance(data: Any) -> dict:
    items = _extract_list(data, "currencies", "balances")
    if not items and isinstance(data, dict):
        return {"available": True, "shape": sorted(data.keys())[:20]}
    slim = []
    for x in items[:30]:
        if not isinstance(x, dict):
            continue
        slim.append({
            "currency": x.get("currency") or x.get("asset"),
            "free": x.get("free"),
            "balance": x.get("balance") or x.get("total"),
        })
    return {"available": True, "items": slim}


def _open_trade_summary(data: Any) -> dict:
    trades = _extract_list(data, "trades")
    open_trades = []
    for t in trades:
        if not isinstance(t, dict):
            continue
        if t.get("is_open") is True or str(t.get("is_open")).lower() == "true":
            open_trades.append({
                "id": t.get("trade_id") or t.get("id"),
                "pair": t.get("pair"),
                "is_short": t.get("is_short"),
                "leverage": t.get("leverage"),
                "stake_amount": t.get("stake_amount"),
            })
    return {"total_returned": len(trades), "open_count": len(open_trades), "open": open_trades[:20]}


def preflight() -> dict:
    started = time.time()
    ping_code, ping = _json_request("/api/v1/ping")
    tok, auth = _token()

    out = {
        "status": "ok",
        "mode": "LIVE_ARMED_MANUAL_CONFIRM_ONLY",
        "freqtrade_base_url": FREQTRADE_BASE_URL,
        "ping": {"status_code": ping_code, "ok": ping_code == 200, "data": ping},
        "auth": auth,
        "execution_enabled": False,
        "forceenter_called": False,
        "financial_post_calls": 0,
        "manual_confirmation_required": True,
    }

    if tok:
        for name, path in (
            ("balance_raw", "/api/v1/balance"),
            ("trades_raw", "/api/v1/trades"),
            ("whitelist_raw", "/api/v1/whitelist"),
            ("count_raw", "/api/v1/count"),
        ):
            code, data = _json_request(path, auth=tok)
            out[name] = {"status_code": code, "data": data}

        out["balance"] = _redact_balance((out.get("balance_raw") or {}).get("data"))
        out["trades"] = _open_trade_summary((out.get("trades_raw") or {}).get("data"))
        wl = _extract_list((out.get("whitelist_raw") or {}).get("data"), "whitelist")
        out["whitelist"] = wl
    else:
        out["balance"] = {"available": False}
        out["trades"] = {"open_count": None}
        out["whitelist"] = []

    out["elapsed_sec"] = round(time.time() - started, 3)
    return out


def build_forceenter_preview(pair: str, side: str, *, stake_usdt: Optional[float] = None,
                             leverage: Optional[float] = None) -> dict:
    p = str(pair or "").strip()
    s = str(side or "").strip().lower()
    if s not in {"long", "short"}:
        raise ValueError("side must be long or short")
    stake = min(MAX_STAKE_USDT, max(1.0, float(stake_usdt or DEFAULT_STAKE_USDT)))
    lev = min(MAX_LEVERAGE, max(1.0, float(leverage or DEFAULT_LEVERAGE)))
    payload = {
        "pair": p,
        "side": s,
        "ordertype": "market",
        "stakeamount": stake,
        "leverage": lev,
        "entry_tag": "myshka_live_armed_manual_review",
    }
    return {
        "status": "ok",
        "mode": "LIVE_ARMED_MANUAL_CONFIRM_ONLY",
        "endpoint_preview": "/api/v1/forceenter",
        "payload": payload,
        "manual_confirmation_required": True,
        "execution_enabled": False,
        "forceenter_called": False,
        "financial_post_calls": 0,
    }


def status() -> dict:
    return {
        "enabled": True,
        "mode": "LIVE_ARMED_MANUAL_CONFIRM_ONLY",
        "freqtrade_base_url": FREQTRADE_BASE_URL,
        "credentials_present": bool(FREQTRADE_USERNAME and FREQTRADE_PASSWORD),
        "default_stake_usdt": DEFAULT_STAKE_USDT,
        "max_stake_usdt": MAX_STAKE_USDT,
        "default_leverage": DEFAULT_LEVERAGE,
        "max_leverage": MAX_LEVERAGE,
        "execution_enabled": False,
        "forceenter_called": False,
        "financial_post_calls": 0,
        "manual_confirmation_required": True,
    }


def init() -> dict:
    return status()

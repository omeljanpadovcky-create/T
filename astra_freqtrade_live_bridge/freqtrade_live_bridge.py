"""MYSHKA / ASTRA -> Freqtrade LIVE execution bridge V1.

This module is LIVE-capable but disabled unless all local and remote live guards pass.

Required local conditions:
- ASTRA_LIVE_EXECUTION=true
- ASTRA_LIVE_CONFIRM=REAL_MONEY_CONFIRMED
- ASTRA_LIVE_KILL_SWITCH=false
- FREQTRADE__DRY_RUN=false
- ASTRA_LIVE_MAX_STAKE_USDT > 0

Required remote Freqtrade conditions before every order:
- authenticated API
- /show_config returns dry_run=false
- pair is whitelisted
- an open-trade slot is available
- no same-pair trade is already open
- cooldown is clear

Signal conditions are inherited from live_dry_run.build_preview(): production ENTER,
EDGE pass, JEV APPROVE, Evidence pass, Adaptive pass/not-applicable, valid side/price.

The installer does NOT turn live mode on and does NOT change Freqtrade dry_run.
"""
from __future__ import annotations

from collections import deque
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

try:
    from .live_dry_run import build_preview
except Exception:
    try:
        from live_dry_run import build_preview
    except Exception:
        from astra_live_dry_run.live_dry_run import build_preview

MODE = "FREQTRADE_LIVE_EXECUTION_BRIDGE_V1"
BASE_URL = os.getenv("FREQTRADE_BASE_URL", "http://freqtrade:8080").rstrip("/")
USERNAME = os.getenv("FREQTRADE_USERNAME", "")
PASSWORD = os.getenv("FREQTRADE_PASSWORD", "")
COOLDOWN_SEC = max(30, int(os.getenv("ASTRA_LIVE_COOLDOWN_SEC", "180")))
MAX_STAKE_USDT = max(0.0, float(os.getenv("ASTRA_LIVE_MAX_STAKE_USDT", "0")))
MAX_LEVERAGE = max(1.0, float(os.getenv("ASTRA_LIVE_MAX_LEVERAGE", "1")))
TIMEOUT_SEC = max(2, int(os.getenv("ASTRA_LIVE_TIMEOUT_SEC", "8")))

_LOCK = threading.RLock()
_LAST_SENT: dict[str, float] = {}
_EVENTS = deque(maxlen=200)
_POST_COUNT = 0


def _env_true(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1","true","yes","on"}


def _local_live_guard() -> dict:
    checks = {
        "live_execution_true": _env_true("ASTRA_LIVE_EXECUTION"),
        "confirm_exact": str(os.getenv("ASTRA_LIVE_CONFIRM", "")).strip().upper() == "REAL_MONEY_CONFIRMED",
        "kill_switch_false": not _env_true("ASTRA_LIVE_KILL_SWITCH"),
        "local_dry_run_false": str(os.getenv("FREQTRADE__DRY_RUN", "")).strip().lower() == "false",
        "max_stake_positive": MAX_STAKE_USDT > 0,
    }
    return {"ok": all(checks.values()), "checks": checks}


def _request(path: str, *, method: str = "GET", token: Optional[str] = None,
             payload: Optional[dict] = None, basic: bool = False) -> tuple[int, Any]:
    global _POST_COUNT

    if method not in {"GET","POST"}:
        raise RuntimeError("unsupported method")
    if method == "POST" and path not in {"/api/v1/token/login","/api/v1/forceenter"}:
        raise RuntimeError("POST target blocked")

    if method == "POST" and path == "/api/v1/forceenter":
        local = _local_live_guard()
        if not local["ok"]:
            raise RuntimeError("hard block: local live guard failed")

    headers = {
        "Accept":"application/json",
        "User-Agent":"MYSHKA-ASTRA-FREQTRADE-LIVE-BRIDGE",
    }
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif basic:
        raw = f"{USERNAME}:{PASSWORD}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")

    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(BASE_URL + path, headers=headers, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if method == "POST" and path == "/api/v1/forceenter":
                with _LOCK:
                    _POST_COUNT += 1
            try:
                return int(resp.status), json.loads(body)
            except Exception:
                return int(resp.status), {"raw":body[:4000]}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw":body[:4000]}
        return int(e.code), parsed
    except Exception as e:
        return 0, {"error":f"{type(e).__name__}: {e}"}


def _token() -> tuple[Optional[str], dict]:
    if not USERNAME or not PASSWORD:
        return None, {"authenticated":False,"reason":"missing_credentials"}
    code, data = _request("/api/v1/token/login", method="POST", basic=True)
    token = data.get("access_token") if isinstance(data, dict) else None
    return (str(token) if token else None), {
        "authenticated":bool(token),
        "status_code":code,
    }


def _bool(d: Any, key: str) -> Optional[bool]:
    if not isinstance(d, dict) or key not in d:
        return None
    v = d.get(key)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        if v.lower() == "true":
            return True
        if v.lower() == "false":
            return False
    return None


def _runtime_guard(pair: str, side: str) -> dict:
    local = _local_live_guard()
    checks: dict[str,bool] = dict(local["checks"])
    checks.update({
        "credentials_present":bool(USERNAME and PASSWORD),
        "pair_present":bool(pair),
        "side_valid":side in {"long","short"},
    })
    detail: dict[str,Any] = {}

    if not local["ok"]:
        return {"ok":False,"checks":checks,"detail":detail,"token":None}

    token, auth = _token()
    detail["auth"] = auth
    checks["authenticated"] = bool(token)
    if not token:
        return {"ok":False,"checks":checks,"detail":detail,"token":None}

    code, cfg = _request("/api/v1/show_config", token=token)
    remote_dry = _bool(cfg, "dry_run")
    detail["show_config_http"] = code
    detail["remote_dry_run"] = remote_dry
    detail["trading_mode"] = cfg.get("trading_mode") if isinstance(cfg, dict) else None
    checks["show_config_200"] = code == 200
    checks["remote_dry_run_false"] = remote_dry is False

    code, wl = _request("/api/v1/whitelist", token=token)
    pairs = wl.get("whitelist") if isinstance(wl, dict) else []
    pairs = pairs or []
    detail["whitelist_http"] = code
    detail["whitelist"] = pairs
    checks["pair_whitelisted"] = code == 200 and pair in pairs

    code, count = _request("/api/v1/count", token=token)
    current = count.get("current") if isinstance(count, dict) else None
    maximum = count.get("max") if isinstance(count, dict) else None
    detail["count_http"] = code
    detail["count"] = count
    checks["trade_slot_available"] = (
        code == 200 and isinstance(current, int) and isinstance(maximum, int) and current < maximum
    )

    code, status_data = _request("/api/v1/status", token=token)
    open_trades = status_data if isinstance(status_data, list) else []
    same_pair_open = any(
        isinstance(t, dict) and t.get("pair") == pair and bool(t.get("is_open", True))
        for t in open_trades
    )
    detail["status_http"] = code
    detail["same_pair_open"] = same_pair_open
    checks["same_pair_not_open"] = code == 200 and not same_pair_open

    key = f"{pair}|{side}"
    with _LOCK:
        last = _LAST_SENT.get(key, 0.0)
    remaining = max(0.0, COOLDOWN_SEC - (time.time() - last))
    detail["cooldown_remaining_sec"] = round(remaining, 1)
    checks["cooldown_clear"] = remaining <= 0

    return {
        "ok":all(checks.values()),
        "checks":checks,
        "detail":detail,
        "token":token,
    }


def _record(event: dict) -> None:
    with _LOCK:
        _EVENTS.appendleft(event)
    try:
        with open("/data/astra_freqtrade_live_bridge.jsonl","a",encoding="utf-8") as fh:
            fh.write(json.dumps(event,ensure_ascii=False,separators=(",",":")) + "\n")
    except Exception:
        pass


def _send(pair: str, side: str, *, stake_usdt: float, leverage: float,
          source: str, tag: str) -> dict:
    pair = str(pair or "").strip()
    side = str(side or "").strip().lower()

    if MAX_STAKE_USDT <= 0:
        out = {
            "status":"blocked","mode":MODE,"reason":"ASTRA_LIVE_MAX_STAKE_USDT must be > 0",
            "pair":pair,"side":side,"source":source,"real_money_execution":False,
        }
        _record(out)
        return out

    stake = min(MAX_STAKE_USDT, max(0.01, float(stake_usdt)))
    lev = min(MAX_LEVERAGE, max(1.0, float(leverage)))

    guard = _runtime_guard(pair, side)
    if not guard["ok"]:
        out = {
            "status":"blocked",
            "mode":MODE,
            "pair":pair,
            "side":side,
            "source":source,
            "guard":{k:v for k,v in guard.items() if k != "token"},
            "real_money_execution":False,
        }
        _record(out)
        return out

    payload = {
        "pair":pair,
        "side":side,
        "ordertype":"market",
        "stakeamount":stake,
        "leverage":lev,
        "entry_tag":tag,
    }

    code, data = _request(
        "/api/v1/forceenter",
        method="POST",
        token=guard["token"],
        payload=payload,
    )

    sent = 200 <= code < 300
    if sent:
        with _LOCK:
            _LAST_SENT[f"{pair}|{side}"] = time.time()

    out = {
        "status":"sent" if sent else "error",
        "mode":MODE,
        "pair":pair,
        "side":side,
        "source":source,
        "payload":payload,
        "http_status":code,
        "response":data,
        "live_confirmed_local":True,
        "remote_dry_run":guard["detail"].get("remote_dry_run"),
        "real_money_execution":sent,
    }
    _record(out)
    return out


def preflight(pair: str, side: str) -> dict:
    side = str(side or "").strip().lower()
    g = _runtime_guard(str(pair or "").strip(), side)
    return {
        "status":"ok" if g["ok"] else "blocked",
        "mode":MODE,
        "guard":{k:v for k,v in g.items() if k != "token"},
        "real_money_execution":False,
    }


def observe_results(results: list[dict]) -> dict:
    local = _local_live_guard()
    if not local["ok"]:
        return {
            "status":"disabled",
            "mode":MODE,
            "local_guard":local,
            "sent":0,
            "blocked":0,
            "real_money_execution":False,
        }

    sent = []
    blocked = []
    for r in results or []:
        action_before = r.get("action")
        reason_before = r.get("reason")
        preview = build_preview(r)

        # Never mutate the signal path.
        if r.get("action") != action_before or r.get("reason") != reason_before:
            raise RuntimeError("live bridge must not mutate action/reason")

        if not preview.get("would_send_order"):
            continue

        pair = str(preview.get("pair") or "")
        direction = str(preview.get("direction") or "").upper()
        side = "long" if direction == "LONG" else "short" if direction == "SHORT" else ""
        payload = preview.get("order_payload") or {}
        if not side:
            continue

        result = _send(
            pair,
            side,
            stake_usdt=float(payload.get("notional_usdt") or MAX_STAKE_USDT),
            leverage=float(payload.get("leverage") or 1.0),
            source="astra_scan",
            tag="astra_gated_live",
        )
        (sent if result.get("status") == "sent" else blocked).append(result)

    return {
        "status":"ok",
        "mode":MODE,
        "sent":len(sent),
        "blocked":len(blocked),
        "real_money_execution":bool(sent),
    }


def recent(limit: int = 50) -> dict:
    lim = max(1,min(200,int(limit)))
    with _LOCK:
        items = list(_EVENTS)[:lim]
    return {"status":"ok","mode":MODE,"items":items}


def status() -> dict:
    with _LOCK:
        posts = _POST_COUNT
        events = len(_EVENTS)
    local = _local_live_guard()
    return {
        "status":"ok",
        "mode":MODE,
        "local_live_enabled":local["ok"],
        "local_checks":local["checks"],
        "base_url":BASE_URL,
        "credentials_present":bool(USERNAME and PASSWORD),
        "cooldown_sec":COOLDOWN_SEC,
        "max_stake_usdt":MAX_STAKE_USDT,
        "max_leverage":MAX_LEVERAGE,
        "forceenter_post_count":posts,
        "events":events,
        "installer_changes_dry_run":False,
        "requires_remote_dry_run_false":True,
    }


def init() -> dict:
    return status()

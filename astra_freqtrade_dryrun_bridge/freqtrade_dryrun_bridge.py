"""ASTRA -> Freqtrade DRY-RUN execution bridge.

This module may POST /forceenter only after BOTH sides confirm dry-run:
1) ASTRA environment FREQTRADE__DRY_RUN=true
2) Freqtrade /show_config reports dry_run=true

It never enables or permits real-money execution.
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

from .live_dry_run import build_preview
from .execution_slippage_audit import start_audit as slippage_start_audit

MODE = "FREQTRADE_DRYRUN_EXECUTION_BRIDGE_V1"
BASE_URL = os.getenv("FREQTRADE_BASE_URL", "http://freqtrade:8080").rstrip("/")
USERNAME = os.getenv("FREQTRADE_USERNAME", "")
PASSWORD = os.getenv("FREQTRADE_PASSWORD", "")
AUTO_ENABLED = str(os.getenv("ASTRA_FREQTRADE_DRYRUN_AUTO", "true")).lower() == "true"
COOLDOWN_SEC = max(30, int(os.getenv("ASTRA_FREQTRADE_DRYRUN_COOLDOWN_SEC", "180")))
MAX_STAKE_USDT = max(1.0, float(os.getenv("ASTRA_FREQTRADE_DRYRUN_MAX_STAKE_USDT", "25")))
MAX_LEVERAGE = max(1.0, float(os.getenv("ASTRA_FREQTRADE_DRYRUN_MAX_LEVERAGE", "3")))
TIMEOUT_SEC = max(2, int(os.getenv("ASTRA_FREQTRADE_DRYRUN_TIMEOUT_SEC", "8")))

_LOCK = threading.RLock()
_LAST_SENT: dict[str, float] = {}
_EVENTS = deque(maxlen=200)
_POST_COUNT = 0


def _local_dry_run() -> bool:
    return str(os.getenv("FREQTRADE__DRY_RUN", "")).strip().lower() == "true"


def _request(path: str, *, method: str = "GET", token: Optional[str] = None,
             payload: Optional[dict] = None, basic: bool = False) -> tuple[int, Any]:
    global _POST_COUNT

    if method not in {"GET", "POST"}:
        raise RuntimeError("unsupported method")

    # Only auth login and DRY-RUN forceenter are permitted POST targets.
    if method == "POST" and path not in {"/api/v1/token/login", "/api/v1/forceenter"}:
        raise RuntimeError("POST target blocked")

    if method == "POST" and path == "/api/v1/forceenter" and not _local_dry_run():
        raise RuntimeError("hard block: local dry_run is not true")

    headers = {
        "Accept": "application/json",
        "User-Agent": "MYSHKA-ASTRA-FREQTRADE-DRYRUN-BRIDGE",
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
                return int(resp.status), {"raw": body[:4000]}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body[:4000]}
        return int(e.code), parsed
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def _token() -> tuple[Optional[str], dict]:
    if not USERNAME or not PASSWORD:
        return None, {"authenticated": False, "reason": "missing_credentials"}
    code, data = _request("/api/v1/token/login", method="POST", basic=True)
    token = data.get("access_token") if isinstance(data, dict) else None
    return (str(token) if token else None), {
        "authenticated": bool(token),
        "status_code": code,
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
    checks: dict[str, bool] = {
        "local_dry_run_true": _local_dry_run(),
        "credentials_present": bool(USERNAME and PASSWORD),
        "pair_present": bool(pair),
        "side_valid": side in {"long", "short"},
    }
    detail: dict[str, Any] = {}

    token, auth = _token()
    detail["auth"] = auth
    checks["authenticated"] = bool(token)

    if not token:
        return {"ok": False, "checks": checks, "detail": detail, "token": None}

    code, cfg = _request("/api/v1/show_config", token=token)
    remote_dry = _bool(cfg, "dry_run")
    detail["show_config_http"] = code
    detail["remote_dry_run"] = remote_dry
    detail["trading_mode"] = cfg.get("trading_mode") if isinstance(cfg, dict) else None
    checks["show_config_200"] = code == 200
    checks["remote_dry_run_true"] = remote_dry is True

    code, wl = _request("/api/v1/whitelist", token=token)
    pairs = []
    if isinstance(wl, dict):
        pairs = wl.get("whitelist") or []
    detail["whitelist_http"] = code
    detail["whitelist"] = pairs
    checks["pair_whitelisted"] = pair in pairs

    code, count = _request("/api/v1/count", token=token)
    detail["count_http"] = code
    detail["count"] = count
    current = count.get("current") if isinstance(count, dict) else None
    maximum = count.get("max") if isinstance(count, dict) else None
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
        "ok": all(checks.values()),
        "checks": checks,
        "detail": detail,
        "token": token,
    }


def _record(event: dict) -> None:
    with _LOCK:
        _EVENTS.appendleft(event)
    try:
        with open("/data/astra_freqtrade_dryrun_bridge.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass


def _send(pair: str, side: str, *, stake_usdt: float, leverage: float,
          source: str, tag: str, signal_price: Optional[float] = None,
          signal_ts_ms: Optional[int] = None) -> dict:
    pair = str(pair or "").strip()
    side = str(side or "").strip().lower()
    stake = min(MAX_STAKE_USDT, max(1.0, float(stake_usdt)))
    lev = min(MAX_LEVERAGE, max(1.0, float(leverage)))

    guard = _runtime_guard(pair, side)
    if not guard["ok"]:
        out = {
            "status": "blocked",
            "mode": MODE,
            "pair": pair,
            "side": side,
            "source": source,
            "guard": {k: v for k, v in guard.items() if k != "token"},
            "real_money_execution": False,
        }
        _record(out)
        return out

    payload = {
        "pair": pair,
        "side": side,
        "ordertype": "market",
        "stakeamount": stake,
        "leverage": lev,
        "entry_tag": tag,
    }

    send_ts_ms = int(time.time() * 1000)
    code, data = _request(
        "/api/v1/forceenter",
        method="POST",
        token=guard["token"],
        payload=payload,
    )

    audit = {"status": "not_started"}
    if 200 <= code < 300:
        with _LOCK:
            _LAST_SENT[f"{pair}|{side}"] = time.time()
        audit = slippage_start_audit(
            fetch_open_trades=lambda: _request("/api/v1/status", token=guard["token"]),
            pair=pair,
            side=side,
            signal_price=signal_price,
            signal_ts_ms=signal_ts_ms,
            send_ts_ms=send_ts_ms,
            source=source,
            execution_mode="DRY_RUN",
            stake_usdt=stake,
        )

    out = {
        "status": "sent" if 200 <= code < 300 else "error",
        "mode": MODE,
        "pair": pair,
        "side": side,
        "source": source,
        "payload": payload,
        "http_status": code,
        "response": data,
        "dry_run_confirmed_local": True,
        "dry_run_confirmed_remote": guard["detail"].get("remote_dry_run") is True,
        "slippage_audit": audit,
        "real_money_execution": False,
    }
    _record(out)
    return out


def smoke(pair: str, side: str, confirm: str,
          stake_usdt: float = 10.0, leverage: float = 1.0) -> dict:
    if str(confirm or "").strip().upper() != "DRYRUN":
        return {
            "status": "blocked",
            "mode": MODE,
            "reason": "confirm must equal DRYRUN",
            "real_money_execution": False,
        }
    return _send(
        pair,
        side,
        stake_usdt=stake_usdt,
        leverage=leverage,
        source="manual_smoke",
        tag="astra_dryrun_smoke",
    )


def observe_results(results: list[dict]) -> dict:
    if not AUTO_ENABLED:
        return {
            "status": "disabled",
            "mode": MODE,
            "auto_enabled": False,
            "real_money_execution": False,
        }

    sent = []
    blocked = []
    for r in results or []:
        preview = build_preview(r)
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
            stake_usdt=float(payload.get("notional_usdt") or 10.0),
            leverage=float(payload.get("leverage") or 1.0),
            source="astra_scan",
            tag="astra_gated_dryrun",
            signal_price=payload.get("entry_reference"),
            signal_ts_ms=int(float(preview.get("observed_at") or time.time()) * 1000),
        )
        (sent if result.get("status") == "sent" else blocked).append(result)

    return {
        "status": "ok",
        "mode": MODE,
        "auto_enabled": True,
        "sent": len(sent),
        "blocked": len(blocked),
        "real_money_execution": False,
    }


def recent(limit: int = 50) -> dict:
    lim = max(1, min(200, int(limit)))
    with _LOCK:
        items = list(_EVENTS)[:lim]
    return {"status": "ok", "mode": MODE, "items": items}


def status() -> dict:
    with _LOCK:
        posts = _POST_COUNT
        events = len(_EVENTS)
    return {
        "status": "ok",
        "mode": MODE,
        "auto_enabled": AUTO_ENABLED,
        "base_url": BASE_URL,
        "local_dry_run": _local_dry_run(),
        "credentials_present": bool(USERNAME and PASSWORD),
        "cooldown_sec": COOLDOWN_SEC,
        "max_stake_usdt": MAX_STAKE_USDT,
        "max_leverage": MAX_LEVERAGE,
        "forceenter_post_count": posts,
        "events": events,
        "real_money_execution": False,
    }


def init() -> dict:
    return status()

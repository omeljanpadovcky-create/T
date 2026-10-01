"""MYSHKA / ASTRA execution slippage audit.

Designed to sit behind the ASTRA -> Freqtrade bridge.
It never sends orders itself and never changes trading decisions.

In DRY_RUN it validates the measurement pipeline using Freqtrade simulated fills.
In LIVE the same calculation can be fed real Freqtrade open_rate values.
"""
from __future__ import annotations

from collections import deque
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

LOG_PATH = os.getenv("ASTRA_SLIPPAGE_AUDIT_PATH", "/data/astra_slippage_audit.jsonl")
ALERT_BPS = max(0.0, float(os.getenv("ASTRA_SLIPPAGE_ALERT_BPS", "20")))
ALERT_COOLDOWN_SEC = max(5, int(os.getenv("ASTRA_SLIPPAGE_ALERT_COOLDOWN_SEC", "30")))
POLL_SEC = max(0.1, float(os.getenv("ASTRA_SLIPPAGE_POLL_SEC", "0.25")))
POLL_TIMEOUT_SEC = max(2.0, float(os.getenv("ASTRA_SLIPPAGE_POLL_TIMEOUT_SEC", "6")))

_EVENTS = deque(maxlen=500)
_LOCK = threading.RLock()
_LAST_ALERT: dict[str, float] = {}


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except Exception:
        return None


def _side_matches(trade: dict, side: str) -> bool:
    want_short = str(side).lower() == "short"
    if "is_short" in trade:
        return bool(trade.get("is_short")) == want_short
    d = str(
        trade.get("trade_direction")
        or trade.get("direction")
        or trade.get("side")
        or ""
    ).lower()
    if d:
        return d == ("short" if want_short else "long")
    return True


def _trade_time_ms(trade: dict) -> Optional[int]:
    for key in ("open_date_timestamp", "open_timestamp", "open_time_ms"):
        x = _num(trade.get(key))
        if x is not None:
            return int(x if x > 10_000_000_000 else x * 1000)
    return None


def _telegram(text: str) -> dict:
    token = str(os.getenv("TELEGRAM_BOT_TOKEN", "") or "").strip()
    chat_id = str(os.getenv("TELEGRAM_CHAT_ID", "") or "").strip()
    if not token or not chat_id:
        return {"status": "disabled", "reason": "telegram_not_configured"}
    body = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return {"status": "sent", "http_status": int(resp.status)}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def _record(item: dict) -> None:
    with _LOCK:
        _EVENTS.appendleft(dict(item))
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        pass


def _alert_if_needed(item: dict) -> None:
    slip = _num(item.get("slippage_bps"))
    if slip is None or slip < ALERT_BPS:
        return
    pair = str(item.get("pair") or "")
    now = time.time()
    with _LOCK:
        last = float(_LAST_ALERT.get(pair, 0.0))
        if now - last < ALERT_COOLDOWN_SEC:
            return
        _LAST_ALERT[pair] = now

    mode = str(item.get("execution_mode") or "UNKNOWN")
    text = (
        "ASTRA SLIPPAGE ALERT\n"
        f"Mode: {mode}\n"
        f"Pair: {pair}\n"
        f"Side: {item.get('side')}\n"
        f"Signal: {item.get('signal_price')}\n"
        f"Exec: {item.get('exec_price')}\n"
        f"Slippage: {float(slip):+.2f} bps ({float(item.get('slippage_pct') or 0):+.4f}%)\n"
        f"Signal->send: {item.get('engine_latency_ms')} ms\n"
        f"Send->fill: {item.get('exchange_latency_ms')} ms\n"
        f"Source: {item.get('source')}"
    )
    tg = _telegram(text)
    item["telegram_alert"] = tg


def _audit_worker(
    *,
    fetch_open_trades: Callable[[], tuple[int, Any]],
    pair: str,
    side: str,
    signal_price: float,
    signal_ts_ms: int,
    send_ts_ms: int,
    source: str,
    execution_mode: str,
    stake_usdt: Optional[float],
) -> None:
    deadline = time.time() + POLL_TIMEOUT_SEC
    found = None
    last_http = 0
    while time.time() < deadline:
        code, data = fetch_open_trades()
        last_http = int(code or 0)
        trades = data if isinstance(data, list) else (
            data.get("trades") if isinstance(data, dict) and isinstance(data.get("trades"), list) else []
        )
        candidates = [
            t for t in trades
            if isinstance(t, dict)
            and str(t.get("pair") or "") == pair
            and _side_matches(t, side)
        ]
        if candidates:
            found = max(
                candidates,
                key=lambda t: int(t.get("trade_id") or t.get("id") or 0),
            )
            break
        time.sleep(POLL_SEC)

    observed_ms = int(time.time() * 1000)
    if not found:
        item = {
            "status": "fill_not_observed",
            "pair": pair,
            "side": side,
            "signal_price": signal_price,
            "signal_ts_ms": signal_ts_ms,
            "send_ts_ms": send_ts_ms,
            "observed_ts_ms": observed_ms,
            "source": source,
            "execution_mode": execution_mode,
            "stake_usdt": stake_usdt,
            "last_http_status": last_http,
            "real_money_execution": execution_mode.upper() == "LIVE",
        }
        _record(item)
        return

    exec_price = _num(found.get("open_rate"))
    requested = _num(found.get("open_rate_requested"))
    if exec_price is None or exec_price <= 0:
        item = {
            "status": "invalid_fill_price",
            "pair": pair,
            "side": side,
            "trade_id": found.get("trade_id") or found.get("id"),
            "signal_price": signal_price,
            "open_rate_requested": requested,
            "raw_trade": found,
            "source": source,
            "execution_mode": execution_mode,
        }
        _record(item)
        return

    adverse_abs = (exec_price - signal_price) if side.lower() == "long" else (signal_price - exec_price)
    slip_pct = adverse_abs / signal_price * 100.0
    slip_bps = slip_pct * 100.0
    fill_ts_ms = _trade_time_ms(found) or observed_ms

    item = {
        "status": "recorded",
        "pair": pair,
        "side": side,
        "trade_id": found.get("trade_id") or found.get("id"),
        "signal_price": signal_price,
        "open_rate_requested": requested,
        "exec_price": exec_price,
        "slippage_abs": adverse_abs,
        "slippage_pct": slip_pct,
        "slippage_bps": slip_bps,
        "signal_ts_ms": int(signal_ts_ms),
        "send_ts_ms": int(send_ts_ms),
        "fill_ts_ms": int(fill_ts_ms),
        "observed_ts_ms": observed_ms,
        "engine_latency_ms": max(0, int(send_ts_ms - signal_ts_ms)),
        "exchange_latency_ms": max(0, int(fill_ts_ms - send_ts_ms)),
        "fill_observed_latency_ms": max(0, int(observed_ms - send_ts_ms)),
        "source": source,
        "execution_mode": execution_mode,
        "stake_usdt": stake_usdt,
        "simulated_fill": execution_mode.upper() == "DRY_RUN",
        "real_money_execution": execution_mode.upper() == "LIVE",
    }
    _alert_if_needed(item)
    _record(item)


def start_audit(
    *,
    fetch_open_trades: Callable[[], tuple[int, Any]],
    pair: str,
    side: str,
    signal_price: Optional[float],
    signal_ts_ms: Optional[int],
    send_ts_ms: int,
    source: str,
    execution_mode: str,
    stake_usdt: Optional[float] = None,
) -> dict:
    px = _num(signal_price)
    if px is None or px <= 0:
        return {"status": "skipped", "reason": "signal_price_missing"}
    sig_ms = int(signal_ts_ms or send_ts_ms)
    t = threading.Thread(
        target=_audit_worker,
        kwargs={
            "fetch_open_trades": fetch_open_trades,
            "pair": str(pair),
            "side": str(side),
            "signal_price": float(px),
            "signal_ts_ms": sig_ms,
            "send_ts_ms": int(send_ts_ms),
            "source": str(source),
            "execution_mode": str(execution_mode),
            "stake_usdt": _num(stake_usdt),
        },
        name=f"slippage-audit-{str(pair).replace('/', '_')}",
        daemon=True,
    )
    t.start()
    return {"status": "started", "execution_mode": execution_mode}


def recent(limit: int = 50) -> dict:
    lim = max(1, min(500, int(limit)))
    with _LOCK:
        items = list(_EVENTS)[:lim]
    return {"status": "ok", "items": items, "alert_bps": ALERT_BPS}


def status() -> dict:
    with _LOCK:
        n = len(_EVENTS)
    return {
        "status": "ok",
        "mode": "FREQTRADE_EXECUTION_SLIPPAGE_AUDIT_V1",
        "events": n,
        "alert_bps": ALERT_BPS,
        "alert_cooldown_sec": ALERT_COOLDOWN_SEC,
        "log_path": LOG_PATH,
        "changes_trading_decisions": False,
        "sends_orders": False,
    }

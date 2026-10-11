#!/usr/bin/env python3
"""BTC/USDT public-market paper simulation. No credentials, orders, or brokerage API."""
import datetime as dt
import json
import os
import pathlib
import urllib.request
import time

STATE = pathlib.Path("data/btc-paper.json")
NOW = dt.datetime.now(dt.timezone.utc)
STAKE, PAYOUT = 10.0, 0.92

def fetch_candles():
    # Kraken public OHLC; no keys. XBTUSDT is Bitcoin against USDT.
    url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSDT&interval=1"
    req = urllib.request.Request(url, headers={"User-Agent": "CryptoMyshkaPaperResearch/1.1"})
    payload = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                payload = json.load(response)
            if payload.get("error"):
                raise RuntimeError("Kraken API: " + ", ".join(payload["error"]))
            break
        except (OSError, ValueError, RuntimeError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    if payload.get("error"):
        raise RuntimeError("Kraken API: " + ", ".join(payload["error"]))
    result = payload.get("result", {})
    pair_keys = [key for key in result if key != "last"]
    if not pair_keys:
        raise RuntimeError("Kraken returned no BTC/USDT pair")
    rows = result[pair_keys[0]]
    if not isinstance(rows, list) or len(rows) < 40:
        raise RuntimeError("Insufficient Kraken BTC/USDT candles")
    return [{"open": int(c[0]) * 1000,
             "close_time": int(c[0]) * 1000 + 59999,
             "close": float(c[4])} for c in rows]

def ema(values, n):
    value = values[0]
    k = 2 / (n + 1)
    for v in values[1:]:
        value = v * k + value * (1 - k)
    return value

def rsi(values):
    changes = [b - a for a, b in zip(values[:-1], values[1:])][-14:]
    gains = sum(max(0, x) for x in changes) / 14
    losses = sum(max(0, -x) for x in changes) / 14
    return 50.0 if gains == losses == 0 else (100.0 if losses == 0 else 100 - 100 / (1 + gains / losses))

def historical_validation(closed):
    """Causal walk-forward check: signals use only candles available at decision time.
    Outcome is the next CLOSED minute, never the same candle. Research only.
    """
    samples = []
    for i in range(60, len(closed) - 1):
        history = [c["close"] for c in closed[:i + 1]]
        fast = ema(history[-40:], 9)
        slow = ema(history[-60:], 21)
        strength = rsi(history)
        direction = "UP" if fast > slow and 55 <= strength <= 70 else (
            "DOWN" if fast < slow and 30 <= strength <= 45 else "STOP")
        if direction == "STOP":
            continue
        current, following = closed[i], closed[i + 1]
        if following["open"] - current["open"] != 60000:
            continue
        start, end = current["close"], following["close"]
        result = "TIE" if start == end else (
            "WIN" if (end > start if direction == "UP" else end < start) else "LOSS")
        samples.append(result)
    wins = samples.count("WIN")
    losses = samples.count("LOSS")
    ties = samples.count("TIE")
    decided = wins + losses
    return {
        "method": "walk_forward_next_closed_m1_proxy",
        "market": "Kraken BTC/USDT (not Pocket Option OTC)",
        "lookahead_guard": "signal uses candles through t; result uses t+1",
        "window_closed_candles": len(closed),
        "signals": len(samples),
        "wins": wins, "losses": losses, "ties": ties,
        "win_rate_pct": round(100 * wins / decided, 2) if decided else None,
        "break_even_win_rate_pct": round(100 / (1 + PAYOUT), 2),
        "hypothetical_pnl_usdt": round(wins * STAKE * PAYOUT - losses * STAKE, 2),
        "sufficient_sample": decided >= 100,
        "warning": "Short historical sample, proxy prices, no fees/slippage or executable fills; not a prediction or proven edge."
    }


def main():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(STATE.read_text()) if STATE.exists() else {}
    except (ValueError, OSError):
        state = {}
    state.setdefault("trades", [])
    state.setdefault("pending", None)
    state["market"] = "BTCUSDT"
    state["source"] = "Kraken public XBT/USDT M1 candles, not Pocket Option OTC"
    state["mode"] = "paper_only"
    state["checked_at"] = NOW.isoformat()
    try:
        candles = fetch_candles()
        now_ms = int(NOW.timestamp() * 1000)
        closed = [c for c in candles if c["close_time"] < now_ms - 1000]
        if len(closed) < 35:
            raise RuntimeError("Not enough closed candles")
        latest = closed[-1]
        state["backtest"] = historical_validation(closed)
        pending = state["pending"]
        if pending:
            # Settle against first *available closed minute* at/after expiry,
            # not a broker fill. If historical candle is missing, retain pending.
            settle = next((c for c in closed if c["close_time"] >= pending["due_ms"]), None)
            if settle:
                exit_price = settle["close"]
                tie = exit_price == pending["entry"]
                win = exit_price > pending["entry"] if pending["direction"] == "UP" else exit_price < pending["entry"]
                pending.update(exit=exit_price, settled_at=NOW.isoformat(),
                               outcome="TIE" if tie else ("WIN" if win else "LOSS"),
                               pnl=0 if tie else (STAKE * PAYOUT if win else -STAKE),
                               exit_candle_ms=settle["open"])
                state["trades"].insert(0, pending)
                state["trades"] = state["trades"][:250]
                state["pending"] = None
        values = [c["close"] for c in closed]
        fast, slow, strength = ema(values[-40:], 9), ema(values[-60:], 21), rsi(values)
        direction = "UP" if fast > slow and 55 <= strength <= 70 else "DOWN" if fast < slow and 30 <= strength <= 45 else "STOP"
        state["insights"] = {"ema9": round(fast, 2), "ema21": round(slow, 2),
                             "rsi14": round(strength, 2), "direction": direction,
                             "last_closed_candle_ms": latest["open"]}
        # Scheduled runner cannot execute at exact expiry. Entry is a closed
        # candle price proxy; never describe it as an executable quote.
        if state["pending"] is None and direction != "STOP" and state.get("last_entry_candle") != latest["open"]:
            state["pending"] = {"direction": direction, "entry": latest["close"],
                                "entry_candle_ms": latest["open"], "due_ms": latest["close_time"] + 60000,
                                "recorded_at": NOW.isoformat(), "pair": "BTCUSDT",
                                "note": "Entry/exit use closed-candle proxy prices, not executable prices"}
            state["last_entry_candle"] = latest["open"]
        state["status"] = "ok"
        state.pop("error", None)
    except Exception as exc:
        state["status"] = "error"
        state["error"] = str(exc)[:250]
        # Never fabricate prices or settle trades on API failure.
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    print("BTC paper run:", state["status"], "trades:", len(state["trades"]), "pending:", bool(state["pending"]), "error:", state.get("error", ""))

if __name__ == "__main__":
    main()

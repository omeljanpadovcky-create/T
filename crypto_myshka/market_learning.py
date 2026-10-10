#!/usr/bin/env python3
"""Read-only Bybit 15m research. No orders, secrets or claims of model fine-tuning.

Scheduled invocations persist *prospective* predictions before the next bar exists,
then score each prediction using a later confirmed closed candle. Backtest train and
chronologically later holdout are kept separate. No trade returns are asserted.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import pathlib
import time
import urllib.parse
import urllib.request
from collections import defaultdict

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
START_MS = int(dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
STEP = 15 * 60 * 1000
API = "https://api.bybit.com/v5/market/kline"
STATE_FILE = pathlib.Path("crypto_myshka/data/market_learning.json")
ASSUMED_ROUND_TRIP_COST_PCT = 0.14  # illustration, not measured fees/spread/funding
USER_AGENT = "CryptoMyshka-Bybit-ReadOnly-Research/1.0"


def utc_iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def request_bars(symbol, start, end):
    query = urllib.parse.urlencode({
        "category": "linear", "symbol": symbol, "interval": "15",
        "start": start, "end": end, "limit": 1000,
    })
    request = urllib.request.Request(API + "?" + query, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json"
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.load(response)
            if payload.get("retCode") != 0 or payload.get("result", {}).get("symbol") != symbol:
                raise ValueError("Bybit rejected bar request")
            result = []
            for row in payload.get("result", {}).get("list", []):
                bar = [int(row[0])] + [float(row[k]) for k in range(1, 6)]
                t, op, hi, lo, cl, vol = bar
                if (start <= t <= end and all(math.isfinite(x) for x in bar)
                        and lo > 0 and vol >= 0 and lo <= min(op, cl) <= hi
                        and lo <= max(op, cl) <= hi):
                    result.append(bar)
            return sorted(result)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_history(symbol, start, last_closed_start):
    if symbol not in SYMBOLS:
        raise ValueError("symbol is not supported")
    found = {}
    cursor = start
    while cursor <= last_closed_start:
        end = min(last_closed_start, cursor + (1000 - 1) * STEP)
        for bar in request_bars(symbol, cursor, end):
            found[bar[0]] = bar
        cursor = end + STEP
        time.sleep(0.09)
    return [found[k] for k in sorted(found)]


def ema(values, period):
    alpha = 2 / (period + 1)
    out = []
    val = None
    for price in values:
        val = price if val is None else alpha * price + (1 - alpha) * val
        out.append(val)
    return out


def predictions(rows):
    """Predict using only rows through i; never look at the target bar."""
    close = [b[4] for b in rows]
    fast, slow = ema(close, 9), ema(close, 21)
    output = [None] * len(rows)
    for i in range(28, len(rows)):
        if rows[i][0] - rows[i - 28][0] != 28 * STEP:
            continue
        tr = 0.0
        gain = 0.0
        loss = 0.0
        for j in range(i - 13, i + 1):
            before = close[j - 1]
            tr += max(rows[j][2] - rows[j][3],
                      abs(rows[j][2] - before), abs(rows[j][3] - before))
            difference = close[j] - before
            gain += max(0.0, difference)
            loss += max(0.0, -difference)
        atr = tr / 14
        if not atr:
            continue
        rsi = 50.0 if gain == loss == 0 else 100.0 if not loss else 100 - 100 / (1 + gain / loss)
        def sign(change, cutoff):
            return 1 if change > cutoff else -1 if change < -cutoff else 0
        components = (
            sign(fast[i] - slow[i], atr * 0.1),
            sign(close[i] - close[i - 3], atr * 0.25),
            sign(rsi - 50, 5),
            sign(close[i] - rows[i][1], atr * 0.12),
        )
        nonzero = sum(x != 0 for x in components)
        score = sum(components)
        direction = "UP" if nonzero >= 3 and score >= 3 else (
            "DOWN" if nonzero >= 3 and score <= -3 else "STOP")
        regime = "trend" if abs(fast[i] - slow[i]) > atr * 0.35 else "range"
        output[i] = {"direction": direction, "pattern": direction + "_" + regime,
                     "score": score, "rsi": round(rsi, 1)}
    return output


def score_direction(direction, next_bar):
    # Paper proxy: enter at next open, exit at next close; no broker fill assumed.
    move = 100 * (next_bar[4] / next_bar[1] - 1)
    signed = move if direction == "UP" else -move
    return {"direction_hit": signed > 0,
            "paper_net_pct": round(signed - ASSUMED_ROUND_TRIP_COST_PCT, 5),
            "move_pct": round(move, 5)}


def blank():
    return {"count": 0, "direction_hits": 0, "positive_net": 0, "net_sum": 0.0}


def record(stats, obs):
    stats["count"] += 1
    stats["direction_hits"] += int(obs["direction_hit"])
    stats["positive_net"] += int(obs["paper_net_pct"] > 0)
    stats["net_sum"] += obs["paper_net_pct"]


def describe(stats):
    n = stats["count"]
    return {
        "observations": n,
        "directional_accuracy_pct": round(100 * stats["direction_hits"] / n, 2) if n else None,
        "positive_net_pct": round(100 * stats["positive_net"] / n, 2) if n else None,
        "avg_paper_net_pct": round(stats["net_sum"] / n, 5) if n else None,
    }


def summarize(rows):
    """Fixed 70/30 chronological split. Later 30% never tunes the rules."""
    votes = predictions(rows)
    index = int(len(rows) * 0.7)
    subsets = {}
    distributions = {}
    for phase, begin, end in (("train", 28, index), ("holdout", index, len(rows) - 1)):
        totals = blank()
        by_pattern = defaultdict(blank)
        always_up = blank()
        skipped = 0
        for i in range(begin, end):
            if rows[i + 1][0] - rows[i][0] != STEP:
                continue
            record(always_up, score_direction("UP", rows[i + 1]))
            voted = votes[i]
            if not voted or voted["direction"] == "STOP":
                skipped += 1
                continue
            obs = score_direction(voted["direction"], rows[i + 1])
            record(totals, obs)
            record(by_pattern[voted["pattern"]], obs)
        subsets[phase] = {
            **describe(totals), "stop_count": skipped,
            "always_up_baseline": describe(always_up),
            "by_pattern": {key: describe(val) for key, val in sorted(by_pattern.items())}
        }
        distributions[phase] = {key: describe(val) for key, val in by_pattern.items()}
    approved = []
    # An explicit conservative gate, not fitted by repeatedly peeking at holdout.
    for pattern, train in distributions["train"].items():
        check = distributions["holdout"].get(pattern, {})
        if (train["observations"] >= 50 and check.get("observations", 0) >= 25
                and train["avg_paper_net_pct"] > 0 and check["avg_paper_net_pct"] > 0
                and train["directional_accuracy_pct"] > 51
                and check["directional_accuracy_pct"] > 51):
            approved.append(pattern)
    return {"candles": len(rows), "first_closed_at": utc_iso(rows[0][0] + STEP),
            "last_closed_at": utc_iso(rows[-1][0] + STEP),
            "train": subsets["train"], "holdout": subsets["holdout"],
            "approved_patterns": approved}


def load_state(path):
    if not path.exists():
        return {"version": 1, "symbols": {}, "forward_predictions": []}
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict) or obj.get("version") != 1:
        raise ValueError("Unsupported state schema, not overwriting")
    if not isinstance(obj.get("forward_predictions"), list) or not isinstance(obj.get("symbols"), dict):
        raise ValueError("State schema corrupt, not overwriting")
    return obj


def run(path=STATE_FILE, now=None, fetcher=fetch_history):
    now_ms = int(now if now is not None else time.time() * 1000)
    last_closed_start = ((now_ms - 3000) // STEP) * STEP - STEP
    if last_closed_start < START_MS + 200 * STEP:
        raise ValueError("Too early for research")
    state = load_state(path)
    today = utc_iso(now_ms)
    updates = {}
    for symbol in SYMBOLS:
        saved = state["symbols"].get(symbol, {})
        # History is backfilled once from 2026-01-01. Later runs only read 150
        # recent candles. Rebuild never pretends to re-fit on new held-out data.
        bootstrapping = not saved.get("backtest")
        start = START_MS if bootstrapping else max(START_MS, last_closed_start - 160 * STEP)
        bars = fetcher(symbol, start, last_closed_start)
        if len(bars) < (200 if bootstrapping else 35):
            raise ValueError("Insufficient verified Bybit candles for " + symbol)
        if bars[-1][0] != last_closed_start:
            raise ValueError("Latest expected close missing for " + symbol)
        # Evaluate predictions previously committed by earlier invocations only.
        for prior in state["forward_predictions"]:
            if (prior.get("symbol") != symbol or prior.get("evaluated_at") or
                    prior.get("target_candle_start", 0) > last_closed_start):
                continue
            target = next((bar for bar in bars if bar[0] == prior["target_candle_start"]), None)
            if target and prior["signal"] in ("UP", "DOWN"):
                prior["outcome"] = score_direction(prior["signal"], target)
                prior["evaluated_at"] = utc_iso(target[0] + STEP)
            elif target:
                prior["outcome"] = {"reason": "STOP; no direction predicted"}
                prior["evaluated_at"] = utc_iso(target[0] + STEP)
        # Make today's forward prediction without ever using the next candle.
        current_vote = predictions(bars)[-1]
        if not current_vote:
            raise ValueError("Insufficient continuous recent history for " + symbol)
        bt = summarize(bars) if bootstrapping else saved["backtest"]
        approved = set(bt["approved_patterns"])
        recent = [p for p in state["forward_predictions"]
                  if p.get("symbol") == symbol and p.get("evaluated_at")
                  and p.get("outcome", {}).get("direction_hit") is not None]
        # Halt weak patterns based on newly observed results; does not retrain weights.
        for pattern in list(approved):
            tail = [p for p in recent if p.get("pattern") == pattern][-30:]
            if len(tail) >= 30:
                if sum(int(p["outcome"]["direction_hit"]) for p in tail) < 16 or sum(
                        p["outcome"]["paper_net_pct"] for p in tail) <= 0:
                    approved.remove(pattern)
        raw = current_vote["direction"]
        gated = raw if current_vote["pattern"] in approved else "STOP"
        key = f"{symbol}:{last_closed_start}"
        if not any(p.get("id") == key for p in state["forward_predictions"]):
            state["forward_predictions"].append({
                "id": key, "symbol": symbol, "candle_closed_at": utc_iso(last_closed_start + STEP),
                "target_candle_start": last_closed_start + STEP,
                "signal": gated, "ungated_heuristic": raw,
                "pattern": current_vote["pattern"], "evaluated_at": None,
                "outcome": None,
            })
        finished = [p for p in state["forward_predictions"] if p.get("symbol") == symbol
                    and p.get("evaluated_at") and p.get("signal") in ("UP", "DOWN")]
        stats = blank()
        for entry in finished:
            record(stats, entry["outcome"])
        updates[symbol] = {
            "backtest": bt,
            "latest_bar_closed_at": utc_iso(last_closed_start + STEP),
            "latest_close": bars[-1][4],
            "latest_heuristic": raw,
            "latest_research_signal": gated,
            "pattern": current_vote["pattern"],
            "forward_observed": describe(stats),
            "forward_settled": len(finished),
            "forward_stop_count": sum(1 for p in state["forward_predictions"] if
                                      p.get("symbol") == symbol and p.get("signal") == "STOP"),
        }
    state["symbols"] = updates
    state["version"] = 1
    state["updated_at"] = today
    state["interval_minutes"] = 15
    state["history_requested_since"] = "2026-01-01T00:00:00Z"
    state["market"] = "Bybit V5 linear public candles"
    state["mode"] = "read_only_research"
    state["orders_enabled"] = False
    state["ai_weights_trained"] = False
    state["round_trip_cost_assumed_pct"] = ASSUMED_ROUND_TRIP_COST_PCT
    state["note"] = ("Historical 70/30 chronological test and future outcomes are different. "
                     "Paper net assumes ideal next open and next close and estimated costs. "
                     "Not an executable trade or a verified edge.")
    # Retain recent prospective records, preserving any unresolved ones.
    state["forward_predictions"] = ([
        p for p in state["forward_predictions"] if not p.get("evaluated_at")
    ] + [p for p in state["forward_predictions"] if p.get("evaluated_at")][-1500:])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return state


if __name__ == "__main__":
    report = run()
    for name, row in report["symbols"].items():
        print(name, "closed", row["latest_bar_closed_at"], "rule", row["latest_heuristic"],
              "gated", row["latest_research_signal"], "forward", row["forward_observed"])

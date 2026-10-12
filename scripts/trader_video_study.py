#!/usr/bin/env python3
"""Auditable, video-inspired *candidate* strategies on public Kraken spot 5m bars.

These are NOT an extraction of a private trader's exact method. Videos provide
qualitative hypotheses only; no private video is uploaded. No Pocket Option OTC
prices, copied trader orders, executable signals or real trading.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import pathlib
import random
import statistics
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "trader-video-study.json"
BAR_HISTORY = ROOT / "data" / "jev-laya-history.json"
PAIRS = {"BTC/USDT": "XBTUSDT", "ETH/USDT": "ETHUSDT", "SOL/USDT": "SOLUSDT"}
STEP = 300  # seconds; never confuse Kraken 5m with Pocket Option OTC
PAYOUT = 0.92  # hypothetical, not a confirmed Pocket Option quote
STAKE = 10.0
RULES = ("pullback_follow", "breakout_follow")
MAX_EVENTS = 600
WINDOW = 720  # Kraken public OHLC max; older history may be in daily snapshot


def load_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def fetch_closed(pair, now):
    req = urllib.request.Request(
        "https://api.kraken.com/0/public/OHLC?pair=" + PAIRS[pair] + "&interval=5",
        headers={"User-Agent": "CryptoMyshka-VideoStudy-ReadOnly/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        payload = json.load(response)
    if payload.get("error"):
        raise RuntimeError("Kraken API error: " + str(payload["error"])[:140])
    result = payload.get("result", {})
    rows = next((x for k, x in result.items() if k != "last"), [])
    out = []
    for row in rows:
        try:
            timestamp = int(row[0])
            o, h, l, c, volume = (float(row[k]) for k in (1, 2, 3, 4, 6))
        except (IndexError, ValueError, TypeError):
            continue
        if (timestamp % STEP == 0 and timestamp + STEP <= now - 2
                and all(math.isfinite(x) for x in (o, h, l, c, volume))
                and l > 0 and volume >= 0 and l <= min(o, c) <= max(o, c) <= h):
            out.append([timestamp, o, h, l, c, volume])
    final = [x for _, x in sorted({r[0]: r for r in out}.items())]
    if len(final) < 80 or (now - (final[-1][0] + STEP)) > 2 * STEP:
        raise RuntimeError("Too few fresh closed candles from Kraken")
    return final


def merged_bars(snapshot, fresh):
    data = {}
    for row in (snapshot if isinstance(snapshot, list) else []) + fresh:
        if (isinstance(row, list) and len(row) == 6
                and isinstance(row[0], int) and row[0] % STEP == 0):
            data[row[0]] = row
    return [data[k] for k in sorted(data)]


def indicator(rows, i):
    """Past-only technical features. Any edit to bars after i must not change these."""
    if i < 35 or i >= len(rows) or rows[i][0] - rows[i - 35][0] != 35 * STEP:
        return None
    closes = [bar[4] for bar in rows[i - 35:i + 1]]
    def ema(length):
        alpha = 2 / (length + 1)
        value = closes[0]
        for close in closes[1:]:
            value += alpha * (close - value)
        return value
    movements = [closes[k] - closes[k - 1] for k in range(-14, 0)]
    gains = sum(max(x, 0) for x in movements)
    losses = sum(max(-x, 0) for x in movements)
    rsi = (50.0 if gains == losses == 0 else
           100.0 if losses == 0 else 100.0 - 100.0 / (1.0 + gains / losses))
    return {"ema9": ema(9), "ema21": ema(21), "rsi": rsi,
            "recent_red": sum(rows[j][4] < rows[j][1] for j in range(i - 4, i)),
            "recent_green": sum(rows[j][4] > rows[j][1] for j in range(i - 4, i)),
            "prior_high": max(rows[j][2] for j in range(i - 7, i)),
            "prior_low": min(rows[j][3] for j in range(i - 7, i))}


def hypothesize(rows, i, rule):
    """Return BUY/SELL/STOP with a verifiable reason, not a confidence percentage."""
    info = indicator(rows, i)
    if not info:
        return "STOP", "Недостатньо безперервних закритих свічок"
    candle = rows[i]
    up = candle[4] > candle[1]
    down = candle[4] < candle[1]
    if rule == "pullback_follow":
        # Hypothesis: short pullback in established trend, followed by a confirmation candle.
        if info["ema9"] > info["ema21"] and info["recent_red"] >= 2 and up and 47 <= info["rsi"] <= 73 and candle[4] > info["ema9"]:
            return "BUY", "EMA9 > EMA21, відкат і зелена свічка підтвердження"
        if info["ema9"] < info["ema21"] and info["recent_green"] >= 2 and down and 27 <= info["rsi"] <= 53 and candle[4] < info["ema9"]:
            return "SELL", "EMA9 < EMA21, відкат і червона свічка підтвердження"
    elif rule == "breakout_follow":
        # Hypothesis: close breaks a previously known seven-candle range.
        if info["ema9"] > info["ema21"] and up and candle[4] > info["prior_high"] and 51 <= info["rsi"] <= 76:
            return "BUY", "Пробій максимуму попередніх 7 свічок у висхідному тренді"
        if info["ema9"] < info["ema21"] and down and candle[4] < info["prior_low"] and 24 <= info["rsi"] <= 49:
            return "SELL", "Пробій мінімуму попередніх 7 свічок у спадному тренді"
    else:
        raise ValueError("Unknown pre-registered strategy " + str(rule))
    return "STOP", "Фільтри кандидата не дали узгодженого входу"


def result_for(direction, base_close, next_close):
    if direction == "STOP":
        return "SKIP"
    if next_close == base_close:
        return "TIE"
    correct = (next_close > base_close) if direction == "BUY" else (next_close < base_close)
    return "WIN" if correct else "LOSS"


def score(rows):
    """This retrospective check uses only the final chronological 20% of observations.

    The rules are fixed BEFORE testing; no parameters or rule are selected from
    these scores. Forward results are separately tracked below.
    """
    if len(rows) < 120:
        return {rule: stat([]) for rule in RULES}
    start = max(50, int(len(rows) * 0.8))
    entries = {rule: [] for rule in RULES}
    for i in range(start, len(rows) - 1):
        if rows[i + 1][0] != rows[i][0] + STEP:
            continue
        for rule in RULES:
            direction, _ = hypothesize(rows, i, rule)
            if direction != "STOP":
                entries[rule].append(result_for(direction, rows[i][4], rows[i + 1][4]))
    return {rule: stat(entries[rule]) for rule in RULES}


def stat(outcomes):
    w = outcomes.count("WIN")
    l = outcomes.count("LOSS")
    t = outcomes.count("TIE")
    sample = w + l
    if sample:
        p = w / sample
        z = 1.96
        denominator = 1 + z*z/sample
        lower = (p + z*z/(2*sample) - z * math.sqrt((p*(1-p)+z*z/(4*sample))/sample))/denominator
    else:
        lower = None
    # Theoretical payout on a separate Kraken price feed is NOT realised broker P&L.
    return {"wins": w, "losses": l, "ties": t, "count": len(outcomes),
            "win_rate": round(w/sample, 4) if sample else None,
            "lower_95pct_wilson": round(lower, 4) if lower is not None else None,
            "illustrative_usd": round(w*STAKE*PAYOUT-l*STAKE, 2),
            "not_real_returns": True,
            "passes_research_gate": sample >= 100 and lower is not None and lower > 1/(1+PAYOUT)}


def report(now, fetcher=fetch_closed, previous=None, snapshot=None):
    if previous is None:
        previous = load_json(OUT, {"events": []})
    if snapshot is None:
        snapshot = load_json(BAR_HISTORY, {"assets": {}})
    rows_by_pair = {}
    errors = {}
    checks = {}
    retro = {rule: [] for rule in RULES}
    for pair in PAIRS:
        try:
            fresh = fetcher(pair, now)
            rows = merged_bars(snapshot.get("assets", {}).get(pair, []), fresh)
            if rows[-1][0] != fresh[-1][0]:
                raise RuntimeError("Newest candle mismatch")
        except (RuntimeError, OSError, KeyError, IndexError, TypeError, ValueError) as error:
            errors[pair] = str(error)[:180]
            continue
        rows_by_pair[pair] = rows
        recent_score = score(rows)
        for rule in RULES:
            retro[rule].append(recent_score[rule])
    previous_events = previous.get("events", [])
    if not isinstance(previous_events, list):
        previous_events = []
    events = [dict(e) for e in previous_events if isinstance(e, dict) and
              e.get("direction") in ("BUY", "SELL") and e.get("status") in ("OPEN", "WIN", "LOSS", "TIE")]
    # Settle ONLY previously persisted prospective predictions, and ONLY by
    # a subsequently finished candle bearing precisely the next timestamp.
    for event in events:
        if event["status"] != "OPEN":
            continue
        pair = event.get("pair")
        bars = rows_by_pair.get(pair)
        if not bars:
            continue
        next_bar = next((r for r in bars if r[0] == event.get("next_bar_start")), None)
        if not next_bar:
            continue
        settled = result_for(event["direction"], event["base_close"], next_bar[4])
        event.update(status=settled, settled_at=dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
                     observed_next_close=next_bar[4], broker_verified=False)
    # Generate one *prospective* decision from each most-recent fully closed bar.
    # Never backfill skipped runs with hindsight decisions.
    seen = {e.get("id") for e in events}
    newest = {}
    for pair, rows in rows_by_pair.items():
        current = rows[-1]
        pair_status = {}
        for rule in RULES:
            direction, reason = hypothesize(rows, len(rows) - 1, rule)
            pair_status[rule] = {"direction": direction, "reason": reason,
                                 "closed_candle_start": current[0],
                                 "paper_only": True}
            if direction == "STOP":
                continue
            key = pair + ":" + rule + ":" + str(current[0])
            if key not in seen:
                events.insert(0, {"id": key, "pair": pair, "strategy": rule,
                                  "direction": direction, "reason": reason,
                                  "candle_start": current[0],
                                  "next_bar_start": current[0] + STEP,
                                  "base_close": current[4], "created_at": dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
                                  "source": "Kraken public 5m", "mode": "forward_paper_research",
                                  "status": "OPEN", "broker_verified": False})
                seen.add(key)
        newest[pair] = pair_status
    events.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    events = events[:MAX_EVENTS]
    prospective = {}
    historical = {}
    for rule in RULES:
        prospective[rule] = stat([e["status"] for e in events if
                                  e.get("strategy") == rule and e["status"] in ("WIN", "LOSS", "TIE")])
        values = retro[rule]
        w, l, t = (sum(s[key] for s in values) for key in ("wins", "losses", "ties"))
        historical[rule] = stat(["WIN"]*w + ["LOSS"]*l + ["TIE"]*t)
    return {"version": 1, "updated_at": dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(),
            "origin": "two supplied trader videos; qualitative inspiration, NOT extracted transaction records",
            "video_labels_verified": False, "copied_trader_trades": 0,
            "price_source": "Kraken public spot 5m; NOT Pocket Option OTC",
            "not_pocket_option": True, "real_orders": False, "stake_usd": STAKE,
            "hypothetical_payout": PAYOUT, "break_even_win_rate": round(1/(1+PAYOUT), 4),
            "scan_every": "30 minutes best-effort GitHub Actions; NOT nonstop",
            "strategies": {
                "pullback_follow": "Trend EMA9/21 + recent counter-move + confirming close",
                "breakout_follow": "EMA trend + 7-bar close breakout + RSI filter",
            },
            "source_errors": errors, "last_prospective_checks": newest,
            "retrospective_final_20pct": historical,
            "forward_results": prospective,
            "events": events}


def write(result):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def self_test():
    rng = random.Random(21)
    data = []
    value = 100
    for i in range(500):
        change = rng.uniform(-.001, .001) + (.00015 if i%29 < 18 else -.0002)
        new_value = value * (1+change)
        data.append([i*STEP, value, max(value,new_value)*1.0002,
                     min(value,new_value)*.9998, new_value, 1+rng.random()])
        value = new_value
    assert indicator(data, 80) is not None
    altered = [r[:] for r in data]
    altered[81][4] *= 2
    for rule in RULES:
        assert hypothesize(data, 80, rule) == hypothesize(altered, 80, rule), "Look-ahead detected"
    assert result_for("BUY", 100, 99) == "LOSS"
    assert result_for("SELL", 100, 99) == "WIN"
    assert result_for("SELL", 100, 100) == "TIE"
    now = 500*STEP+3
    def fetcher(pair, _now):
        return data
    r1 = report(now, fetcher=fetcher, previous={"events": []},
                snapshot={"assets": {}})
    assert r1["real_orders"] is False
    assert set(r1["strategies"]) == set(RULES)
    assert all(e["status"] == "OPEN" for e in r1["events"])
    r2 = report(now, fetcher=fetcher, previous=r1, snapshot={"assets": {}})
    assert len(r2["events"]) == len(r1["events"]), "Duplicate forward signals"
    assert not any(e.get("broker_verified") for e in r2["events"])
    # A separately registered prospective event settles only if the exact
    # next timestamp is among subsequently closed candles.
    e = {"id": "test", "pair": "BTC/USDT", "strategy": RULES[0], "direction": "BUY",
         "status": "OPEN", "candle_start": data[-2][0],
         "next_bar_start": data[-1][0], "base_close": data[-2][4],
         "created_at": "2026-01-01T00:00:00+00:00"}
    settled = report(now, fetcher=fetcher, previous={"events": [e]}, snapshot={"assets": {}})
    assert any(x.get("id") == "test" and x["status"] in ("WIN", "LOSS", "TIE")
               for x in settled["events"])
    print("PASS video hypotheses: past-only, STOP, dedup, exact-next-bar forward settlement, no real orders")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    opts = parser.parse_args()
    if opts.self_test:
        self_test()
    else:
        write(report(int(dt.datetime.now(dt.timezone.utc).timestamp())))

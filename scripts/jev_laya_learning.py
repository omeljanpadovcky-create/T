#!/usr/bin/env python3
"""JEV/Laya research data builder and lightweight supervised baseline.

Public Kraken OHLC only. Never Pocket Option OTC, never broker execution.
Laya checkpoint fine-tuning is a SEPARATE optional step; this script does not
mislabel its small softmax baseline as a fine-tuned Laya checkpoint.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import pathlib
import random
import statistics
import urllib.request
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data/jev-laya-history.json"
REPORT = ROOT / "data/jev-laya-research.json"
MODEL = ROOT / "data/jev-laya-baseline-model.json"
BUILD = ROOT / "build/jev-laya"
STEP = 300
MAX_BARS_PER_ASSET = 12000  # accumulated by daily runs; Kraken returns only recent candles
ASSETS = {"BTC/USDT": "XBTUSDT", "ETH/USDT": "ETHUSDT", "SOL/USDT": "SOLUSDT"}
FEATURES = ("ema_gap", "momentum_3", "momentum_12", "rsi", "volatility", "volume_ratio")
LABELS = ("UP", "DOWN", "STOP")
PAYOUT = 0.92
STAKE = 10
# Fixed without observing the holdout; confidence is NOT calibrated by this baseline.
CONFIDENCE_GATE = 0.66
MARGIN_GATE = 0.12


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def collect_kraken(pair, now):
    query = "https://api.kraken.com/0/public/OHLC?pair=" + ASSETS[pair] + "&interval=5"
    req = urllib.request.Request(query, headers={"User-Agent": "CryptoMyshka-Laya-Research/1.0"})
    with urllib.request.urlopen(req, timeout=25) as handle:
        payload = json.load(handle)
    if payload.get("error"):
        raise RuntimeError("Kraken rejected " + pair + ": " + str(payload["error"])[:160])
    rows = payload.get("result", {})
    candles = next((value for key, value in rows.items() if key != "last"), [])
    result = []
    for raw in candles:
        if len(raw) < 7:
            continue
        try:
            t = int(raw[0])
            op, hi, lo, cl, vol = (float(raw[k]) for k in (1, 2, 3, 4, 6))
        except (ValueError, TypeError, IndexError):
            continue
        if not (t > 0 and t % STEP == 0 and t + STEP <= now - 2
                and all(math.isfinite(x) for x in (op, hi, lo, cl, vol))
                and lo > 0 and vol >= 0 and lo <= min(op, cl) <= max(op, cl) <= hi):
            continue
        result.append([t, op, hi, lo, cl, vol])
    if len(result) < 120:
        raise RuntimeError("Not enough closed 5m candles for " + pair)
    result = sorted({row[0]: row for row in result}.values())
    if now - (result[-1][0] + STEP) > 2 * STEP:
        raise RuntimeError("Kraken 5m candles are stale for " + pair)
    return result


def merge_history(existing, new):
    merged = {}
    for row in existing + new:
        if isinstance(row, list) and len(row) == 6:
            t = row[0]
            if type(t) is int and t > 0 and t % STEP == 0:
                merged[t] = row
    return [merged[t] for t in sorted(merged)][-MAX_BARS_PER_ASSET:]


def ema(series, period, i):
    # Restrict the observed sample to the last 100 closed bars (strict causality).
    values = series[max(0, i - 99): i + 1]
    result = values[0]
    alpha = 2 / (period + 1)
    for v in values[1:]:
        result += alpha * (v - result)
    return result


def features_at(rows, i):
    """Only indices <= i may be accessed; next candle is never used here."""
    if i < 40 or i >= len(rows) or rows[i][0] - rows[i - 40][0] != 40 * STEP:
        return None
    closes = [r[4] for r in rows[:i + 1]]
    recent = closes[-21:]
    diffs = [b - a for a, b in zip(recent[:-1], recent[1:])][-14:]
    gain = sum(max(v, 0) for v in diffs)
    loss = sum(max(-v, 0) for v in diffs)
    rsi = 50. if gain == loss == 0 else 100. if loss == 0 else 100 - 100 / (1 + gain / loss)
    momentum3 = (closes[-1] / closes[-4] - 1) * 1000
    momentum12 = (closes[-1] / closes[-13] - 1) * 1000
    deltas = [(closes[j] / closes[j - 1] - 1) * 10000
              for j in range(len(closes) - 19, len(closes))]
    volatility = statistics.pstdev(deltas)
    past_volumes = [float(r[5]) for r in rows[i - 20:i]]
    volume_ratio = rows[i][5] / max(1.e-9, statistics.mean(past_volumes))
    vector = ((ema(closes, 9, i) / ema(closes, 21, i) - 1) * 1000,
              momentum3, momentum12, (rsi - 50) / 25,
              volatility / 20, min(5., volume_ratio) - 1)
    if not all(math.isfinite(x) for x in vector):
        return None
    return [round(max(-8., min(8., x)), 5) for x in vector], rsi


def build_examples(rows, pair):
    examples = []
    for i in range(40, len(rows) - 1):
        result = features_at(rows, i)
        if result is None or rows[i + 1][0] - rows[i][0] != STEP:
            continue
        feature, rsi = result
        # Future next CLOSED candle appears ONLY in label and evaluation fields.
        delta = (rows[i + 1][4] / rows[i][4] - 1) * 10000
        if not math.isfinite(delta):
            continue
        # "STOP" is an explicitly defined future small-movement class,
        # NOT an oracle "don't trade" action or a realised tie at Pocket Option.
        label = "STOP" if abs(delta) < 2 else "UP" if delta > 0 else "DOWN"
        desc = (f"Public Kraken {pair} 5-minute candles. Previous data ONLY. "
                f"EMA9/EMA21 gap {feature[0]:+.3f} per mille; "
                f"3-bar momentum {feature[1]:+.3f} per mille; "
                f"12-bar momentum {feature[2]:+.3f} per mille; "
                f"RSI14 {rsi:.1f}; past-return volatility {feature[4]:.3f}; "
                f"volume ratio {feature[5] + 1:.2f}. "
                "Classify the following closed candle; abstain if movement is small.")
        examples.append({"pair": pair, "bar_start": rows[i][0], "feature": feature,
                         "state": desc, "direction": label, "future_bps": round(delta, 6)})
    return examples


def chrono_split(cases, embargo=25):
    """All samples are sorted by time within each pair; purge overlapping lookbacks."""
    cases = sorted(cases, key=lambda r: r["bar_start"])
    n = len(cases)
    if n < 150:
        return [], [], []
    train_end = int(n * .65)
    val_end = int(n * .81)
    return (cases[:train_end],
            cases[train_end + embargo:val_end],
            cases[val_end + embargo:])


def normalise(rows):
    count = len(rows)
    means = [sum(r["feature"][j] for r in rows) / count for j in range(len(FEATURES))]
    devs = [max(.15, math.sqrt(sum((r["feature"][j] - means[j]) ** 2 for r in rows) / count))
            for j in range(len(FEATURES))]
    return means, devs


def vector(row, means, devs):
    return [1.] + [max(-5., min(5., (v - m) / s)) for v, m, s in
                   zip(row["feature"], means, devs)]


def probs(x, weights):
    scores = [sum(w * v for w, v in zip(row, x)) for row in weights]
    top = max(scores)
    exps = [math.exp(min(50., v - top)) for v in scores]
    total = sum(exps)
    return [v / total for v in exps]


def learn(train):
    """Deterministic multinomial logistic BASELINE (NOT Laya weights)."""
    means, devs = normalise(train)
    weights = [[0.0] * (len(FEATURES) + 1) for _ in LABELS]
    rng = random.Random(27)
    data = [(vector(row, means, devs), LABELS.index(row["direction"])) for row in train]
    prior = Counter(label for _, label in data)
    balance = [min(2.0, len(data) / max(1, len(LABELS) * prior[k])) for k in range(3)]
    for epoch in range(100):
        rng.shuffle(data)
        lr = .040 / (1 + epoch * .018)
        for x, label in data:
            predictions = probs(x, weights)
            for cls in range(len(LABELS)):
                err = (predictions[cls] - (cls == label)) * balance[label]
                for j in range(len(x)):
                    regular = .0004 * weights[cls][j] if j > 0 else 0.0
                    weights[cls][j] -= lr * (err * x[j] + regular)
    return {"weights": weights, "means": means, "devs": devs,
            "classes": list(LABELS), "features": list(FEATURES),
            "trained_cases": len(train), "not_laya_checkpoint": True}


def choose(row, model):
    values = probs(vector(row, model["means"], model["devs"]), model["weights"])
    order = sorted(range(len(LABELS)), key=lambda k: values[k], reverse=True)
    if values[order[0]] < CONFIDENCE_GATE or values[order[0]] - values[order[1]] < MARGIN_GATE:
        return "STOP"
    return LABELS[order[0]]


def wilson_lower(successes, total):
    if not total:
        return None
    p = successes / total
    z = 1.96
    denominator = 1 + z * z / total
    return (p + z*z/(2*total) - z * math.sqrt((p*(1-p)+z*z/(4*total))/total))/denominator


def evaluate(cases, model):
    confusion = {x: Counter() for x in LABELS}
    wins = losses = ties = skipped = matching = 0
    for row in cases:
        predicted = choose(row, model)
        true = row["direction"]
        confusion[true][predicted] += 1
        matching += predicted == true
        if predicted == "STOP":
            skipped += 1
            continue
        movement = row["future_bps"]
        if movement == 0:
            ties += 1
        elif (predicted == "UP" and movement > 0) or (predicted == "DOWN" and movement < 0):
            wins += 1
        else:
            losses += 1
    decided = wins + losses
    lower = wilson_lower(wins, decided)
    return {"examples": len(cases), "classification_accuracy": round(matching / len(cases), 4) if cases else None,
            "predicted_trades": wins + losses + ties, "wins": wins, "losses": losses,
            "ties": ties, "stops": skipped,
            "win_rate_excluding_ties": round(wins / decided, 4) if decided else None,
            "win_rate_wilson_lower_95pct": round(lower, 4) if lower is not None else None,
            "hypothetical_pnl_usdt": round(wins*STAKE*PAYOUT - losses*STAKE, 2),
            "classes": {key: dict(val) for key, val in confusion.items()},
            "label_definition": "UP/DOWN if next close changes >=2 bps; STOP if abs change <2 bps",
            "assumed_binary_payout": PAYOUT, "hypothetical_stake": STAKE}


def write_laya_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        csvfile = csv.writer(handle)
        csvfile.writerow(("state", "direction"))
        for row in rows:
            csvfile.writerow((row["state"], row["direction"]))


def run(now, fetch_fn=collect_kraken):
    HISTORY.parent.mkdir(exist_ok=True, parents=True)
    BUILD.mkdir(exist_ok=True, parents=True)
    previous = read_json(HISTORY, {"version": 1, "source": "Kraken public OHLC 5m", "assets": {}})
    history = {}
    errors = {}
    all_train, all_val, all_test = [], [], []
    pair_samples = {}
    for pair in ASSETS:
        old = previous.get("assets", {}).get(pair, [])
        try:
            new = fetch_fn(pair, now)
            history[pair] = merge_history(old, new)
        except Exception as exc:
            errors[pair] = str(exc)[:180]
            # Do not train on stale old data as if it was a fresh live market.
            continue
        examples = build_examples(history[pair], pair)
        train, valid, test = chrono_split(examples)
        if not train or not valid or not test:
            errors[pair] = "Too few contiguous labeled candles"
            continue
        all_train.extend(train)
        all_val.extend(valid)
        all_test.extend(test)
        pair_samples[pair] = {"candles": len(history[pair]), "train": len(train),
                              "calibration": len(valid), "test": len(test),
                              "last_closed_bar": history[pair][-1][0]}
    if len(all_train) < 200 or len(all_test) < 60:
        raise RuntimeError("Too little valid market data to train and evaluate.")
    model = learn(all_train)
    calibration = evaluate(all_val, model)
    holdout = evaluate(all_test, model)
    decided = holdout["wins"] + holdout["losses"]
    lower = holdout["win_rate_wilson_lower_95pct"]
    break_even = 1/(1+PAYOUT)
    # Never silently enable trading. This is a quality gate for RESEARCH ONLY.
    evidence = decided >= 100 and lower is not None and lower > break_even
    candidate = {}
    for pair, rows in history.items():
        result = features_at(rows, len(rows) - 1)
        if result:
            latest = {"feature": result[0]}
            candidate[pair] = {"direction_research_only": choose(latest, model),
                               "last_closed_bar": rows[-1][0]}
    iso = dt.datetime.fromtimestamp(now, tz=dt.timezone.utc).isoformat()
    report = {"version": 1, "trained_at": iso, "source": "Kraken public spot 5m",
              "not_pocket_option": True, "not_pocket_otc": True,
              "real_orders": False, "automated_broker_copy": False,
              "model": "multinomial_logistic_baseline_not_laya",
              "laya_status": "labeled_dataset_prepared; checkpoint_not_trained",
              "features": list(FEATURES), "pair_samples": pair_samples, "source_errors": errors,
              "calibration_check": calibration, "chronological_purged_holdout": holdout,
              "break_even_win_rate": round(break_even, 4),
              "research_quality_gate_passed": evidence,
              "latest_research_classification": candidate,
              "limitations": ["Backtest uses closed 5m Kraken prices, no executable Pocket Option prices.",
                              "STOP is a small-future-movement label and is not an actionable optimal policy.",
                              "Confidence softmax is not calibrated; selection thresholds pre-fixed.",
                              "Overlapping sequences and nonstationary markets make small holdouts unreliable.",
                              "No brokerage execution; no real investment recommendation."]}
    write_laya_csv(BUILD / "train.csv", all_train)
    write_laya_csv(BUILD / "validation.csv", all_val)
    write_laya_csv(BUILD / "test.csv", all_test)
    MODEL.write_text(json.dumps({"version": 1, "trained_at": iso, "source": report["source"],
                                 "model": model, "real_orders": False,
                                 "laya_checkpoint": False}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    HISTORY.write_text(json.dumps({"version": 1, "source": report["source"],
                                   "updated_at": iso, "assets": history}, ensure_ascii=False)+"\n",
                       encoding="utf-8")
    print(json.dumps({"train": len(all_train), "validation": len(all_val), "test": len(all_test),
                      "holdout_win_rate": holdout["win_rate_excluding_ties"],
                      "holdout_trades": holdout["predicted_trades"],
                      "quality_gate": evidence, "source_errors": errors}, ensure_ascii=False))
    return report


def self_test():
    rng = random.Random(18)
    series = []
    price = 100.
    for i in range(690):
        price *= 1 + (0.00011 if (i//37)%2 else -0.00006) + rng.uniform(-.00035, .00035)
        vol = 30 + rng.random()*20
        series.append([i*STEP, price*1.0001, price*1.0005, price*.9995, price, vol])
    f = features_at(series, 100)
    assert f and len(f[0]) == len(FEATURES)
    changed = [row[:] for row in series]
    changed[101][4] *= 1.08
    assert features_at(series, 100) == features_at(changed, 100), "Future candle leaked into features"
    examples = build_examples(series, "BTC/USDT")
    tr, vl, te = chrono_split(examples)
    assert len(tr)>200 and len(vl)>40 and len(te)>40
    assert tr[-1]["bar_start"] < vl[0]["bar_start"] < vl[-1]["bar_start"] < te[0]["bar_start"]
    assert vl[0]["bar_start"] - tr[-1]["bar_start"] >= 25*STEP
    model = learn(tr)
    metric = evaluate(te, model)
    assert metric["wins"] + metric["losses"] + metric["ties"] + metric["stops"] == len(te)
    assert all(math.isfinite(v) for w in model["weights"] for v in w)
    assert choose({"feature": f[0]}, model) in LABELS
    print("PASS: chronological split, no lookahead, model weights, paper-only evaluation")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        run(int(dt.datetime.now(dt.timezone.utc).timestamp()))

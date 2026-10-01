"""MYSHKA / ASTRA fast-track candidate analysis.

Read-only diagnostic. Joins Forward Experiment Lab with Risk Intelligence
using pair + side + source_minute and evaluates:
    TECH 3/4 + JEV APPROVE + Binance X-Check AGREE

No trading decisions are changed. No orders are sent.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from statistics import median

FWD_DB = "/data/myshka_forward_experiments.sqlite3"
RISK_DB = "/data/myshka_risk_intelligence.sqlite3"
HORIZONS = (300, 600, 900)
CLUSTER_SEC = 300


def pf(vals):
    pos = sum(v for v in vals if v > 0)
    neg = abs(sum(v for v in vals if v <= 0))
    return pos / neg if neg > 1e-12 else (999.0 if pos > 0 else 0.0)


def metrics(rows):
    vals = [float(r["net_pct"]) for r in rows if r["net_pct"] is not None]
    gross = [float(r["gross_pct"]) for r in rows if r["gross_pct"] is not None]
    n = len(vals)
    return {
        "n": n,
        "win_rate_pct": (sum(v > 0 for v in vals) / n * 100.0) if n else 0.0,
        "avg_net_pct": (sum(vals) / n) if n else 0.0,
        "median_net_pct": median(vals) if vals else 0.0,
        "profit_factor": pf(vals),
        "avg_gross_pct": (sum(gross) / len(gross)) if gross else 0.0,
    }


def clustered(rows):
    seen = set()
    out = []
    for r in sorted(rows, key=lambda z: (float(z["opened_at"]), int(z["fwd_id"]))):
        key = str(r["cluster_key"] or "")
        if not key:
            bucket = int(float(r["opened_at"]) // CLUSTER_SEC) * CLUSTER_SEC
            key = f'{r["pair"]}|{r["side"]}|{bucket}'
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def with_cluster_metrics(rows):
    raw = metrics(rows)
    cr = clustered(rows)
    cm = metrics(cr)
    return {
        **raw,
        "cluster_n": cm["n"],
        "cluster_win_rate_pct": cm["win_rate_pct"],
        "cluster_avg_net_pct": cm["avg_net_pct"],
        "cluster_median_net_pct": cm["median_net_pct"],
        "cluster_profit_factor": cm["profit_factor"],
    }


def main():
    con = sqlite3.connect(FWD_DB, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ? AS riskdb", (RISK_DB,))
    try:
        rows = [
            dict(r) for r in con.execute(
                """
                SELECT
                    f.id AS fwd_id,
                    f.pair, f.side, f.source_minute, f.cluster_key,
                    f.opened_at, f.horizon_sec,
                    f.tech_score, f.tech_source,
                    f.xcheck_state, f.edge_pct, f.total_cost_pct,
                    f.structure, f.rsi, f.volume_ratio, f.atr_pct,
                    f.gross_pct, f.net_pct,
                    r.jev_verdict, r.jev_confidence,
                    r.regime AS risk_regime,
                    r.expected_move_pct,
                    r.spread_pct
                FROM forward_outcomes f
                JOIN riskdb.risk_candidates r
                  ON r.pair = f.pair
                 AND UPPER(r.side) = UPPER(f.side)
                 AND r.source_minute = f.source_minute
                WHERE f.status='CLOSED'
                  AND f.tech_score=3
                  AND UPPER(COALESCE(r.jev_verdict,''))='APPROVE'
                  AND UPPER(COALESCE(f.xcheck_state,''))='AGREE'
                  AND f.net_pct IS NOT NULL
                ORDER BY f.opened_at, f.id
                """
            ).fetchall()
        ]
    finally:
        con.close()

    report = {
        "status": "ok",
        "mode": "READ_ONLY_FASTTRACK",
        "filter": "TECH_3_OF_4 + JEV_APPROVE + BINANCE_AGREE",
        "joined_rows": len(rows),
        "by_horizon": {},
        "pair_breakdown_5m": {},
        "side_breakdown_5m": {},
        "regime_breakdown_5m": {},
        "decision_hint": "DIAGNOSTIC_ONLY",
        "changes_trading_decisions": False,
        "sends_orders": False,
        "live_execution": False,
    }

    for h in HORIZONS:
        part = [r for r in rows if int(r["horizon_sec"]) == h]
        report["by_horizon"][str(h)] = with_cluster_metrics(part)

    p5 = [r for r in rows if int(r["horizon_sec"]) == 300]
    for field, outkey in (
        ("pair", "pair_breakdown_5m"),
        ("side", "side_breakdown_5m"),
        ("structure", "regime_breakdown_5m"),
    ):
        groups = defaultdict(list)
        for r in p5:
            groups[str(r[field] or "UNKNOWN")].append(r)
        items = sorted(
            ((k, with_cluster_metrics(v)) for k, v in groups.items()),
            key=lambda kv: (kv[1]["cluster_n"], kv[1]["cluster_avg_net_pct"]),
            reverse=True,
        )
        report[outkey] = {k: m for k, m in items}

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

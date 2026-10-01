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
                  AND f.tech_score IN (3,4)
                  AND f.net_pct IS NOT NULL
                ORDER BY f.opened_at, f.id
                """
            ).fetchall()
        ]
    finally:
        con.close()

    filters = {
        "TECH3": lambda r: int(r["tech_score"] or 0) == 3,
        "TECH3_JEV_APPROVE": lambda r: (
            int(r["tech_score"] or 0) == 3
            and str(r["jev_verdict"] or "").upper() == "APPROVE"
        ),
        "TECH3_BINANCE_AGREE": lambda r: (
            int(r["tech_score"] or 0) == 3
            and str(r["xcheck_state"] or "").upper() == "AGREE"
        ),
        "TRIPLE": lambda r: (
            int(r["tech_score"] or 0) == 3
            and str(r["jev_verdict"] or "").upper() == "APPROVE"
            and str(r["xcheck_state"] or "").upper() == "AGREE"
        ),
        "STRICT4": lambda r: int(r["tech_score"] or 0) == 4,
    }

    report = {
        "status": "ok",
        "mode": "READ_ONLY_FASTTRACK_FUNNEL",
        "joined_rows": len(rows),
        "funnel": {},
        "by_horizon": {},
        "pair_breakdown_5m": {},
        "side_breakdown_5m": {},
        "regime_breakdown_5m": {},
        "paper_canary_eligible": False,
        "paper_canary_reason": "",
        "changes_trading_decisions": False,
        "sends_orders": False,
        "live_execution": False,
    }

    for name, predicate in filters.items():
        report["funnel"][name] = {}
        selected = [r for r in rows if predicate(r)]
        for h in HORIZONS:
            part = [r for r in selected if int(r["horizon_sec"]) == h]
            report["funnel"][name][str(h)] = with_cluster_metrics(part)

    # Backward-compatible main view = triple intersection.
    report["by_horizon"] = report["funnel"]["TRIPLE"]

    h5 = report["funnel"]["TRIPLE"]["300"]
    h10 = report["funnel"]["TRIPLE"]["600"]
    h15 = report["funnel"]["TRIPLE"]["900"]
    enough = int(h5["cluster_n"]) >= 30
    positive = float(h5["cluster_avg_net_pct"]) > 0 and float(h5["cluster_profit_factor"]) > 1.10
    persistence = (
        int(h10["cluster_n"]) >= 15
        and int(h15["cluster_n"]) >= 15
        and float(h10["cluster_avg_net_pct"]) >= 0
        and float(h15["cluster_avg_net_pct"]) >= 0
    )
    report["paper_canary_eligible"] = bool(enough and positive and persistence)
    if not enough:
        report["paper_canary_reason"] = "TRIPLE_5M_CLUSTER_N_BELOW_30"
    elif not positive:
        report["paper_canary_reason"] = "TRIPLE_5M_EXPECTANCY_NOT_POSITIVE"
    elif not persistence:
        report["paper_canary_reason"] = "TRIPLE_10M_15M_NOT_PERSISTENT"
    else:
        report["paper_canary_reason"] = "RETROSPECTIVE_GATE_PASSED_FORWARD_PAPER_REQUIRED"

    p5 = [
        r for r in rows
        if int(r["horizon_sec"]) == 300
        and filters["TRIPLE"](r)
    ]
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

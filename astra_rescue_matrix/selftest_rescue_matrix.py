from __future__ import annotations
import json
import os
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path


def run():
    root = Path(tempfile.gettempdir()) / ("myshka_rescue_v2_test_" + uuid.uuid4().hex)
    root.mkdir(parents=True, exist_ok=True)
    forward = root / "forward.sqlite3"
    risk = root / "risk.sqlite3"
    rescue = root / "rescue.sqlite3"

    os.environ["FORWARD_EXPERIMENT_DB_PATH"] = str(forward)
    os.environ["RISK_INTELLIGENCE_DB_PATH"] = str(risk)
    os.environ["RESCUE_MATRIX_DB_PATH"] = str(rescue)
    os.environ["RESCUE_MATRIX_MOVEMENT_GAP_SEC"] = "180"
    os.environ["RESCUE_MATRIX_WATCH_MIN_CN"] = "30"
    os.environ["RESCUE_MATRIX_WATCH_CONFIRM_NEW_CN"] = "30"

    from . import rescue_matrix as rm

    # Forward Lab DB skeleton
    con = sqlite3.connect(forward)
    con.execute("CREATE TABLE experiment_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    start = time.time() - 7200
    con.execute("INSERT INTO experiment_meta(key,value) VALUES('forward_started_at',?)", (str(start),))
    con.execute("""
        CREATE TABLE forward_outcomes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            side TEXT NOT NULL,
            source_minute INTEGER NOT NULL,
            cluster_bucket INTEGER NOT NULL,
            cluster_key TEXT NOT NULL,
            opened_at REAL NOT NULL,
            target_at REAL NOT NULL,
            horizon_sec INTEGER NOT NULL,
            status TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            action TEXT,
            reason TEXT,
            tech_score INTEGER NOT NULL,
            tech_source TEXT,
            edge_pct REAL,
            total_cost_pct REAL,
            edge_basis TEXT,
            xcheck_state TEXT,
            xcheck_score REAL,
            rsi REAL,
            volume_ratio REAL,
            atr_pct REAL,
            structure TEXT,
            momentum_5m_pct REAL,
            momentum_15m_pct REAL,
            oi_change_15m_pct REAL,
            funding_rate REAL,
            long_short_ratio REAL,
            hour_utc INTEGER,
            settled_at REAL,
            settle_delay_sec REAL,
            gross_pct REAL,
            net_pct REAL,
            direction_hit INTEGER
        )
    """)

    # Risk / blackbox DB skeleton
    rc = sqlite3.connect(risk)
    rc.execute("""
        CREATE TABLE risk_candidates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT,side TEXT,opened_at REAL,status TEXT,net_pct REAL,
            tech_score INTEGER,edge_pct REAL,regime TEXT,jev_verdict TEXT
        )
    """)
    rc.execute("""
        CREATE TABLE decision_blackbox(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT,observed_at REAL,direction TEXT,stage_json TEXT,raw_json TEXT
        )
    """)

    def add_event(idx, pair, side, opened_at, tech, edge, regime, jev, xcheck, evidence, net5, net10, net15):
        # Deliberately use wall-clock buckets; two events around a boundary can still
        # belong to one movement episode in V2.
        bucket = int(opened_at // 300) * 300
        for horizon, net in ((300, net5), (600, net10), (900, net15)):
            con.execute(
                """INSERT INTO forward_outcomes(
                    pair,side,source_minute,cluster_bucket,cluster_key,opened_at,target_at,horizon_sec,status,
                    entry_price,exit_price,action,reason,tech_score,tech_source,edge_pct,total_cost_pct,
                    edge_basis,xcheck_state,xcheck_score,rsi,volume_ratio,atr_pct,structure,momentum_5m_pct,
                    momentum_15m_pct,oi_change_15m_pct,funding_rate,long_short_ratio,hour_utc,settled_at,
                    settle_delay_sec,gross_pct,net_pct,direction_hit
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    pair, side, int(opened_at // 60) * 60, bucket, f"{pair}|{side}|{bucket}",
                    opened_at, opened_at + horizon, horizon, "CLOSED", 100.0, 100.1,
                    "DROP", "shadow", tech, "shadow_relaxed", edge, 0.10, "test",
                    xcheck, 0.0, 55.0, 1.2, 0.4, regime, 0.1, 0.2, 0.0, 0.0, 1.0,
                    12, opened_at + horizon, 0.0, net + 0.10, net, 1 if net > 0 else 0,
                ),
            )

        rc.execute(
            """INSERT INTO risk_candidates(pair,side,opened_at,status,net_pct,tech_score,edge_pct,regime,jev_verdict)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (pair, side, opened_at, "CLOSED", net5, tech, edge, regime, jev),
        )
        stage = {"evidence_gate": {"applies": True, "passed": evidence == "PASS", "state": evidence}}
        raw = {"binance_crosscheck": {"state": xcheck}}
        rc.execute(
            "INSERT INTO decision_blackbox(pair,observed_at,direction,stage_json,raw_json) VALUES(?,?,?,?,?)",
            (pair, opened_at + 1, side, json.dumps(stage), json.dumps(raw)),
        )

    # 36 positive JEV APPROVE + TECH 3/4 independent movement clusters.
    # Each cluster also gets a duplicate 60s later -> raw_n > cn.
    t0 = start + 120
    for i in range(36):
        base = t0 + i * 600
        edge = 0.09 if i % 2 == 0 else 0.11
        xcheck = "CONFLICT" if i % 3 else "AGREE"
        regime = "TREND" if i % 2 == 0 else "BREAKOUT"
        pair = "BTC/USDT:USDT" if i % 2 == 0 else "ETH/USDT:USDT"
        add_event(i, pair, "LONG", base, 3, edge, regime, "APPROVE", xcheck, "PASS", 0.22, 0.10, 0.04)
        add_event(i, pair, "LONG", base + 60, 3, edge, regime, "APPROVE", xcheck, "PASS", 0.18, 0.06, 0.01)

    # Toxic comparison cohort: TECH 4/4.
    for i in range(12):
        base = t0 + i * 650 + 30
        add_event(
            100 + i, "XRP/USDT:USDT", "SHORT", base, 4, 0.24, "CHOP",
            "APPROVE", "NEUTRAL", "HOLD", -0.30, -0.25, -0.20
        )

    con.commit()
    rc.commit()
    con.close()
    rc.close()

    rm.init()
    rep = rm.report()

    assert rep["status"] == "ok", rep
    assert rep["mode"] == "RESCUE_MATRIX_V2_FORWARD_SHADOW_ONLY", rep
    assert rep["changes_paper_execution"] is False
    assert rep["changes_trading_decisions"] is False
    assert rep["live_execution"] is False
    assert rep["legacy_fixed_cluster_key_used_for_scoring"] is False

    h5 = rep["by_horizon"]["300"]
    assert h5["rescue"]["anchor"] == "JEV_APPROVE_x_TECH_3_OF_4"
    anchor = h5["rescue"]["anchor_metrics"]
    assert anchor["raw_n"] > anchor["cn"], anchor
    assert anchor["cn"] >= 30, anchor
    assert anchor["avg_net_pct"] > 0, anchor
    assert anchor["profit_factor"] > 1, anchor

    positives = h5["rescue"]["top_positive_clusters"]
    assert positives, h5
    assert any(x["watch_state"] == "WATCH" for x in positives), positives[:10]

    tech = {x["tech"]: x for x in h5["rescue"]["tech_3_vs_4"]}
    assert tech["3/4"]["avg_net_pct"] > tech["4/4"]["avg_net_pct"], tech

    # Verify movement clustering is not the legacy fixed bucket logic:
    # observations 60s apart should collapse when <= 180s gap.
    assert rep["movement_cluster_gap_sec"] == 180
    assert anchor["raw_n"] >= anchor["cn"] * 2 - 2, anchor

    print("RESCUE_MATRIX_V2_SELFTEST_OK")
    print("5m_anchor_raw_n=", anchor["raw_n"], "5m_anchor_cn=", anchor["cn"])
    print("5m_anchor_avg_net=", round(anchor["avg_net_pct"], 4))
    print("5m_anchor_pf=", round(anchor["profit_factor"], 3))
    print("positive_clusters=", len(positives))
    print("watchlist_counts=", rep["watchlist_counts"])
    print("paper_changed=", rep["changes_paper_execution"])
    print("live_execution=", rep["live_execution"])


if __name__ == "__main__":
    run()

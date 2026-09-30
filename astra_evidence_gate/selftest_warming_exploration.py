from pathlib import Path
import importlib
import os
import sqlite3
import sys
import tempfile
import time
import uuid


def make_risk(path):
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE risk_candidates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT, side TEXT, opened_at REAL, action TEXT, reason TEXT,
            tech_score INTEGER, edge_pct REAL, jev_verdict TEXT,
            gross_pct REAL, net_pct REAL, total_cost_pct REAL, status TEXT
        )
        """
    )
    return con


def make_analytics(path):
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE analytics_trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT, mode TEXT
        )
        """
    )
    return con


def candidate(edge=0.108, pair="QNT/USDT:USDT"):
    return {
        "pair": pair,
        "action": "ENTER",
        "reason": "astra_guard",
        "direction": "LONG",
        "signal": {
            "direction": "LONG", "structure": "UP",
            "ema_fast": 101.0, "ema_slow": 100.0,
            "rsi": 60.0, "volume_ratio": 1.2,
        },
        "edge": {
            "passed": True,
            "net_edge_pct": edge,
            "total_cost_pct": 0.18,
        },
        "jev": {"verdict": "APPROVE", "confidence": 0.8},
        "guard_reasons": [],
    }


def add_closed(con, i, net=-0.25, edge=0.12):
    con.execute(
        """
        INSERT INTO risk_candidates(
            pair,side,opened_at,action,reason,tech_score,edge_pct,jev_verdict,
            gross_pct,net_pct,total_cost_pct,status
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "BTC/USDT:USDT", "LONG", 1000+i, "ENTER",
            "evidence_gate_warming_exploration", 4, edge, "APPROVE",
            net + 0.18, net, 0.18, "CLOSED",
        ),
    )


def run():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    tmp = Path(tempfile.gettempdir()) / ("myshka_warming_exploration_" + uuid.uuid4().hex)
    tmp.mkdir()
    risk = tmp / "risk.sqlite3"
    analytics = tmp / "analytics.sqlite3"

    rc = make_risk(risk); rc.commit(); rc.close()
    ac = make_analytics(analytics); ac.commit(); ac.close()

    os.environ["RISK_INTELLIGENCE_DB_PATH"] = str(risk)
    os.environ["ANALYTICS_DB_PATH"] = str(analytics)
    os.environ["EVIDENCE_GATE_MIN_N"] = "20"
    os.environ["EVIDENCE_GATE_EXPLORATION_ENABLED"] = "true"
    os.environ["EVIDENCE_GATE_EXPLORATION_MIN_EDGE_PCT"] = "0.08"
    os.environ["EVIDENCE_GATE_CALIBRATION_MAX_EDGE_PCT"] = "0.15"
    os.environ["EVIDENCE_GATE_EXPLORATION_COOLDOWN_SEC"] = "600"
    os.environ["EVIDENCE_GATE_EXPLORATION_MAX_OPEN"] = "1"

    import evidence_gate as eg
    importlib.reload(eg)

    rep = eg.report()
    assert rep["state"] == "WARMING", rep
    assert rep["exploration"]["available"] is True, rep

    # One high-edge exploration is allowed per batch.
    a = candidate(0.098, "QNT/USDT:USDT")
    b = candidate(0.14, "XRP/USDT:USDT")
    out = eg.apply_results([a, b])
    assert a["action"] == "ENTER", (a, out)
    assert a["reason"] == "evidence_gate_warming_exploration", a
    assert b["action"] == "DROP", (b, out)
    assert b["reason"] == "evidence_gate_warming_batch_limit", b
    assert out["exploration_passed"] == 1, out

    # Low edge stays blocked while warming.
    low = candidate(0.079)
    eg.apply_results([low])
    assert low["action"] == "DROP", low
    assert low["reason"] == "evidence_gate_warming_edge_too_low", low

    # Above-band edge also stays blocked while warming.
    high = candidate(0.151)
    eg.apply_results([high])
    assert high["action"] == "DROP", high
    assert high["reason"] == "evidence_gate_warming_edge_too_high", high

    # Persist a recent exploration as Risk Intelligence would after the scan.
    rc = sqlite3.connect(risk)
    rc.execute(
        """
        INSERT INTO risk_candidates(
            pair,side,opened_at,action,reason,tech_score,edge_pct,jev_verdict,
            gross_pct,net_pct,total_cost_pct,status
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "QNT/USDT:USDT","LONG",time.time(),"ENTER",
            "evidence_gate_warming_exploration",4,0.098,"APPROVE",
            None,None,0.18,"OPEN",
        ),
    )
    rc.commit(); rc.close()

    importlib.reload(eg)
    cool = candidate(0.12)
    eg.apply_results([cool])
    assert cool["action"] == "DROP", cool
    assert cool["reason"] == "evidence_gate_warming_exploration_unavailable", cool

    # An already-open STRICT Analytics position also blocks exploration.
    rc = sqlite3.connect(risk)
    rc.execute("DELETE FROM risk_candidates WHERE status='OPEN'")
    rc.commit(); rc.close()
    ac = sqlite3.connect(analytics)
    ac.execute("INSERT INTO analytics_trades(status,mode) VALUES('OPEN','STRICT')")
    ac.commit(); ac.close()

    importlib.reload(eg)
    open_block = candidate(0.12)
    eg.apply_results([open_block])
    assert open_block["action"] == "DROP", open_block

    # HOLD after enough negative evidence is a hard block even with high EDGE.
    ac = sqlite3.connect(analytics)
    ac.execute("DELETE FROM analytics_trades")
    ac.commit(); ac.close()
    rc = sqlite3.connect(risk)
    rc.execute("DELETE FROM risk_candidates")
    for i in range(20):
        add_closed(rc, i, net=-0.25, edge=0.20)
    rc.commit(); rc.close()

    importlib.reload(eg)
    hold_rep = eg.report()
    assert hold_rep["state"] == "HOLD", hold_rep
    hold = candidate(0.12)
    eg.apply_results([hold])
    assert hold["action"] == "DROP", hold
    assert hold["reason"] == "evidence_gate_no_validated_edge", hold

    print("WARMING_EXPLORATION_V1_SELFTEST_OK")
    print("warming_first_action=", a["action"])
    print("warming_second_action=", b["action"])
    print("low_edge_action=", low["action"])
    print("high_edge_action=", high["action"])
    print("cooldown_action=", cool["action"])
    print("hold_action=", hold["action"])


if __name__ == "__main__":
    run()

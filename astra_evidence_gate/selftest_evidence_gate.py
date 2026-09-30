from pathlib import Path
import importlib
import os
import sqlite3
import sys
import tempfile
import uuid


def build_db(path):
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE risk_candidates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT,
            side TEXT,
            opened_at REAL,
            action TEXT,
            reason TEXT,
            tech_score INTEGER,
            edge_pct REAL,
            jev_verdict TEXT,
            gross_pct REAL,
            net_pct REAL,
            total_cost_pct REAL,
            status TEXT
        )
        """
    )
    return con


def add(con, edge, net, opened, action="ENTER", reason=""):
    con.execute(
        """INSERT INTO risk_candidates(
            pair,side,opened_at,action,reason,tech_score,edge_pct,jev_verdict,
            gross_pct,net_pct,total_cost_pct,status
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("BTC/USDT:USDT","LONG",opened,action,reason,4,edge,"APPROVE",net+0.15,net,0.15,"CLOSED"),
    )


def candidate(edge):
    return {
        "pair":"BTC/USDT:USDT",
        "action":"ENTER",
        "reason":"astra_guard",
        "direction":"LONG",
        "signal":{
            "direction":"LONG","structure":"UP","ema_fast":101,"ema_slow":100,
            "rsi":60,"volume_ratio":1.2,
        },
        "edge":{"passed":True,"net_edge_pct":edge,"total_cost_pct":0.15},
        "jev":{"verdict":"APPROVE","confidence":0.8},
        "guard_reasons":[],
    }


def run():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    tmp = Path(tempfile.gettempdir()) / ("myshka_evidence_gate_" + uuid.uuid4().hex)
    tmp.mkdir()
    db = tmp / "risk.sqlite3"

    os.environ["RISK_INTELLIGENCE_DB_PATH"] = str(db)
    os.environ["EVIDENCE_GATE_MIN_N"] = "20"
    os.environ["EVIDENCE_GATE_MIN_AVG_NET_PCT"] = "0.03"
    os.environ["EVIDENCE_GATE_MIN_PROFIT_FACTOR"] = "1.10"
    os.environ["EVIDENCE_GATE_REQUIRE_RECENT_POSITIVE"] = "true"

    con = build_db(db)
    con.commit(); con.close()

    import evidence_gate as eg
    importlib.reload(eg)

    # No evidence -> controlled WARMING exploration inside 0.08-0.15.
    r = candidate(0.12)
    out = eg.apply_results([r])
    assert r["action"] == "ENTER", (r, out)
    assert r["reason"] == "evidence_gate_warming_exploration", r
    assert out["passed"] == 1, out

    below = candidate(0.07)
    eg.apply_results([below])
    assert below["action"] == "DROP", below

    above = candidate(0.16)
    eg.apply_results([above])
    assert above["action"] == "DROP", above

    # Low edge history is deliberately bad.
    con = sqlite3.connect(db)
    for i in range(20):
        add(con, 0.07, -0.20, 1000 + i)
    # Higher edge history is positive and stable.
    for i in range(24):
        add(con, 0.12, 0.18 if i % 3 else 0.07, 2000 + i)
    con.commit(); con.close()

    importlib.reload(eg)
    rep = eg.report()
    q = rep["qualified_threshold_pct"]
    assert q is not None and q >= 0.08, rep

    low = candidate(0.07)
    high = candidate(0.14)
    too_high = candidate(0.16)
    a = eg.apply_results([low, high, too_high])
    assert low["action"] == "DROP", (low, rep)
    assert high["action"] == "ENTER", (high, rep)
    assert too_high["action"] == "DROP", (too_high, rep)
    assert a["blocked"] == 2 and a["passed"] == 1, a

    print("EVIDENCE_GATE_V1_SELFTEST_OK")
    print("qualified_threshold_pct=", q)
    print("overall_n=", rep["overall"]["n"])
    print("low_edge_action=", low["action"])
    print("high_edge_action=", high["action"])\n    print("above_band_action=", too_high["action"])


if __name__ == "__main__":
    run()

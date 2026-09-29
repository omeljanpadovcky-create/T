from pathlib import Path
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import uuid


def make_db(path):
    con = sqlite3.connect(path)
    con.execute(
        """
        CREATE TABLE risk_candidates(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT, side TEXT, opened_at REAL, regime TEXT, tech_score INTEGER,
            edge_pct REAL, expected_move_pct REAL, total_cost_pct REAL,
            spread_pct REAL, atr_pct REAL, rsi REAL, volume_ratio REAL,
            jev_verdict TEXT, jev_confidence REAL, price_15m_pct REAL,
            oi_15m_pct REAL, funding_rate_pct REAL, long_short_ratio REAL,
            btc_15m_pct REAL, context_samples INTEGER, confidence_score REAL,
            flags_json TEXT, net_pct REAL, direction_hit INTEGER, status TEXT
        )
        """
    )
    return con


def add(con, i, good):
    if good:
        edge = 0.20
        net = 0.28 if i % 4 else 0.12
        row = ("BTC/USDT:USDT","LONG",1000+i,"UP",4,edge,0.55,0.10,0.02,0.30,61,1.8,
               "APPROVE",0.90,0.35,0.40,0.002,1.02,0.25,45,80,"[]",net,1,"CLOSED")
    else:
        edge = 0.06
        net = -0.26 if i % 3 else -0.12
        row = ("ETH/USDT:USDT","SHORT",1000+i,"DOWN",4,edge,0.15,0.12,0.05,0.20,39,0.7,
               "APPROVE",0.55,-0.10,-0.20,0.008,1.25,0.18,12,35,'["BTC_AGAINST"]',net,0,"CLOSED")
    con.execute(
        """INSERT INTO risk_candidates(
            pair,side,opened_at,regime,tech_score,edge_pct,expected_move_pct,total_cost_pct,
            spread_pct,atr_pct,rsi,volume_ratio,jev_verdict,jev_confidence,price_15m_pct,
            oi_15m_pct,funding_rate_pct,long_short_ratio,btc_15m_pct,context_samples,
            confidence_score,flags_json,net_pct,direction_hit,status
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row
    )


def result(good=True, action="ENTER"):
    if good:
        return {
            "pair":"BTC/USDT:USDT","action":action,"reason":"astra_guard","direction":"LONG",
            "signal":{"direction":"LONG","structure":"UP","ema_fast":101,"ema_slow":100,"rsi":61,"volume_ratio":1.8},
            "edge":{"passed":True,"net_edge_pct":0.20,"expected_move_pct":0.55,"total_cost_pct":0.10},
            "jev":{"verdict":"APPROVE","confidence":0.90},
            "context":{"samples":45,"price_change_15m_pct":0.35,"oi_change_15m_pct":0.40,
                       "funding_rate_pct":0.002,"long_short_ratio":1.02,"btc_price_change_15m_pct":0.25},
            "market":{"spread_pct":0.02,"atr_pct":0.30},
        }
    return {
        "pair":"ETH/USDT:USDT","action":action,"reason":"astra_guard","direction":"SHORT",
        "signal":{"direction":"SHORT","structure":"DOWN","ema_fast":99,"ema_slow":100,"rsi":39,"volume_ratio":0.7},
        "edge":{"passed":True,"net_edge_pct":0.06,"expected_move_pct":0.15,"total_cost_pct":0.12},
        "jev":{"verdict":"APPROVE","confidence":0.55},
        "context":{"samples":12,"price_change_15m_pct":-0.10,"oi_change_15m_pct":-0.20,
                   "funding_rate_pct":0.008,"long_short_ratio":1.25,"btc_price_change_15m_pct":0.18},
        "market":{"spread_pct":0.05,"atr_pct":0.20},
    }


def run():
    root = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    tmp = Path(tempfile.gettempdir()) / ("myshka_adaptive_" + uuid.uuid4().hex)
    tmp.mkdir()
    risk = tmp / "risk.sqlite3"
    learner = tmp / "learner.sqlite3"

    os.environ["RISK_INTELLIGENCE_DB_PATH"] = str(risk)
    os.environ["ADAPTIVE_LEARNER_DB_PATH"] = str(learner)
    os.environ["ADAPTIVE_LEARNER_MIN_TOTAL"] = "60"
    os.environ["ADAPTIVE_LEARNER_MIN_TRAIN"] = "35"
    os.environ["ADAPTIVE_LEARNER_MIN_TEST"] = "15"
    os.environ["ADAPTIVE_LEARNER_MIN_SELECTED_TRAIN"] = "20"
    os.environ["ADAPTIVE_LEARNER_MIN_SELECTED_TEST"] = "10"

    con = make_db(risk)
    # 120 chronological samples, repeating pattern in train and holdout.
    for i in range(120):
        add(con, i, good=(i % 3 == 0))
    con.commit(); con.close()

    import adaptive_learner as al
    importlib.reload(al)

    rep = al.report(force=True)
    assert rep["state"] == "READY_FOR_PAPER_FILTER", rep
    assert rep["champion"] is not None, rep
    assert rep["champion"]["holdout"]["avg_net_pct"] > 0, rep
    assert rep["champion"]["holdout"]["profit_factor"] > 1.0, rep

    good = result(True)
    bad = result(False)
    already_drop = result(True, action="DROP")
    out = al.apply_results([good,bad,already_drop])

    assert good["action"] == "ENTER", (good, rep)
    assert bad["action"] == "DROP", (bad, rep)
    assert already_drop["action"] == "DROP", already_drop
    assert out["passed"] >= 1 and out["blocked"] >= 1, out

    print("ADAPTIVE_ML_LEARNER_V1_SELFTEST_OK")
    print("state=", rep["state"])
    print("source_n=", rep["source_n"])
    print("champion_edge=", rep["champion"]["edge_threshold_pct"])
    print("champion_probability=", rep["champion"]["ml_probability_threshold"])
    print("holdout_n=", rep["champion"]["holdout"]["n"])
    print("holdout_avg_net=", round(rep["champion"]["holdout"]["avg_net_pct"], 4))
    print("good_action=", good["action"])
    print("bad_action=", bad["action"])
    print("drop_stayed_drop=", already_drop["action"])


if __name__ == "__main__":
    run()

from pathlib import Path
import importlib
import os
import tempfile
import time
import uuid


def result(price: float, side: str = "LONG") -> dict:
    return {
        "pair":"BTC/USDT:USDT",
        "direction":side,
        "signal":{"direction":side,"tech_score":4},
        "market":{"last_price":price},
        "edge":{"passed":True,"net_edge_pct":0.14,"total_cost_pct":0.18},
        "jev":{"verdict":"APPROVE"},
        "evidence_gate":{"state":"PASS","passed":True},
        "adaptive_learner":{"state":"PASS","applies":True},
        "external_market_shadow":{"combined_state":"BOTH_AGREE","shadow_only":True},
        "action":"ENTER",
        "reason":"test_enter",
    }


def run():
    tmp = Path(tempfile.gettempdir()) / ("myshka_mt5_shadow_" + uuid.uuid4().hex)
    tmp.mkdir()
    os.environ["MT5_SHADOW_DB_PATH"] = str(tmp / "mt5.sqlite3")
    os.environ["MT5_SHADOW_TOKEN"] = "test-token"
    os.environ["MT5_SHADOW_HORIZONS_SEC"] = "300,600,900"

    import mt5_shadow_agent as m
    importlib.reload(m)
    m.init()

    snap = {
        "status":"READY",
        "ticker":"BTC",
        "symbol":"BTCUSD",
        "direction":"LONG",
        "score":0.71,
        "frames":{
            "M5":{"state":"LONG"},
            "M15":{"state":"LONG"},
            "H1":{"state":"NEUTRAL"},
        },
        "tick":{"bid":100.0,"ask":100.1,"spread_pct":0.10},
        "terminal":{"connected":True,"company":"Libertex Test","server":"Test"},
        "read_only":True,
    }
    m._snapshot = lambda ticker: dict(snap)

    now = 1000.0
    a = result(100.0, "LONG")
    action_before = a["action"]
    reason_before = a["reason"]

    o1 = m.observe_results([a], now=now)
    assert o1["created"] == 3, o1
    assert a["mt5_shadow"]["alignment"] == "AGREE", a
    assert a["mt5_shadow"]["stack_state"] == "MT5_AGREE+EXT_BOTH_AGREE", a
    assert a["action"] == action_before and a["reason"] == reason_before, a

    b = result(101.0, "LONG")
    o2 = m.observe_results([b], now=1300.0)
    assert o2["closed"] == 1, o2

    rep = m.report()
    x = rep["by_horizon"]["300"]["by_mt5_alignment"]["AGREE"]
    assert x["n"] == 1, rep
    assert x["avg_net_pct"] > 0.8, x
    assert rep["changes_trading_decisions"] is False, rep
    assert rep["live_execution"] is False, rep

    snap["direction"] = "SHORT"
    c = result(100.0, "LONG")
    m._snapshot = lambda ticker: dict(snap)
    m._attach(c)
    assert c["mt5_shadow"]["alignment"] == "CONFLICT", c

    print("MT5_SHADOW_AGENT_V1_SELFTEST_OK")
    print("agree=", a["mt5_shadow"]["alignment"])
    print("stack=", a["mt5_shadow"]["stack_state"])
    print("conflict=", c["mt5_shadow"]["alignment"])
    print("action_unchanged=", a["action"] == action_before)
    print("live_execution=", rep["live_execution"])


if __name__ == "__main__":
    run()

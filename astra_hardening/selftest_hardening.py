from pathlib import Path
import importlib
import os
import sqlite3
import sys
import tempfile
import traceback
import uuid

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))


def candle(p=100.0):
    return {"open":p, "high":p+1, "low":p-1, "close":p+0.2, "volume":10}


def result(pair, *, price=100.0, age=5, passed=False, reason="strict_edge_buffer", bid=99.9, ask=100.1):
    return {
        "pair": pair,
        "action": "DROP",
        "reason": reason,
        "direction": "LONG",
        "signal": {"direction":"LONG","structure":"UP","ema_fast":101,"ema_slow":100,"rsi":60,"volume_ratio":1.0},
        "edge": {"passed":passed,"net_edge_pct":-0.1,"total_cost_pct":0.2,"min_required_net_edge_pct":0.05},
        "context": {"samples":40,"age_sec":age},
        "market": {
            "last_price":price,"bid":bid,"ask":ask,"spread_pct":0.02,
            "candles":[candle() for _ in range(80)],
        },
    }


def run():
    t = Path(tempfile.gettempdir()) / ("myshka_hardening_test_" + uuid.uuid4().hex)
    t.mkdir(parents=True, exist_ok=False)
    os.environ["HARDENING_DB_PATH"] = str(t / "hardening.sqlite3")
    os.environ["ANALYTICS_DB_PATH"] = str(t / "analytics.sqlite3")

    con = sqlite3.connect(os.environ["ANALYTICS_DB_PATH"])
    con.execute("CREATE TABLE analytics_trades(id INTEGER PRIMARY KEY,pair TEXT,side TEXT,status TEXT,opened_at REAL)")
    con.commit(); con.close()

    import system_hardening as h
    importlib.reload(h)
    h.init()

    good = [result(f"P{i}/USDT:USDT") for i in range(15)]
    a = h.observe_results(good, {"universe_target":15,"candle_limit":80,"strict_min_net_edge_pct":0.05}, now=1000)
    assert a["status"] == "ok", a
    assert a["data_quality"]["state"] == "OK", a
    assert a["config"]["version"] == "v1.0", a

    # Same config must not create a new version.
    b = h.observe_results(good, {"universe_target":15,"candle_limit":80,"strict_min_net_edge_pct":0.05}, now=1015)
    assert b["config"]["version"] == "v1.0" and not b["config"]["new"], b

    # Changed strict threshold gets a new config version.
    c = h.observe_results(good, {"universe_target":15,"candle_limit":80,"strict_min_net_edge_pct":0.10}, now=1030)
    assert c["config"]["version"] == "v1.1", c

    # SAFE chaos simulations: duplicate pair, missing price, bad bid/ask,
    # stale context and old strict payload semantics.
    bad = list(good)
    bad[0] = result("P1/USDT:USDT", price=0, age=999, passed=True, reason="strict_edge_buffer", bid=101, ask=100)
    d = h.observe_results(bad, {"universe_target":15,"candle_limit":80,"strict_min_net_edge_pct":0.05}, now=1045)
    assert d["data_quality"]["state"] == "WARN", d
    issue_names = {x["name"] for x in d["data_quality"]["issues"]}
    for expected in {"duplicate_pairs","market_prices","bid_ask_order","context_freshness","decision_invariants"}:
        assert expected in issue_names, (expected, issue_names)

    engine={"paper_equity":999.0,"positions":[]}
    runtime={"kill_switch":False,"paused":False,"auto_scan":True}
    rep=h.report(engine,runtime)
    assert rep["status"]=="ok"
    assert rep["config_current"]["version"] in {"v1.0","v1.1","v1.2"}

    ext={
        "bybit_account":{"status":"ok","read_only":1},
        "freqtrade":{"status":"ok","dry_run":True},
    }
    rec=h.reconcile(engine,runtime,ext,now=1100)
    assert rec["state"]=="OK", rec

    print("ASTRA_HARDENING_SELFTEST_OK")
    print("data_quality_good=", a["data_quality"]["ok_n"], "/", a["data_quality"]["total"])
    print("chaos_detected=", sorted(issue_names))
    print("config_versions=", len(rep["config_history"]))
    print("reconciliation=", rec["state"])


try:
    run()
except Exception as exc:
    print("ASTRA_HARDENING_SELFTEST_FAIL")
    print(f"{type(exc).__name__}: {exc}")
    traceback.print_exc(file=sys.stdout)
    sys.exit(1)

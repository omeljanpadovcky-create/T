from pathlib import Path
import importlib
import os
import sqlite3
import sys
import tempfile
import time
import traceback
import uuid

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))


def run():
    t = Path(tempfile.gettempdir()) / ("myshka_quality_v2_" + uuid.uuid4().hex)
    t.mkdir(parents=True, exist_ok=False)
    os.environ["RISK_INTELLIGENCE_DB_PATH"] = str(t / "risk.sqlite3")
    os.environ["ANALYTICS_DB_PATH"] = str(t / "analytics.sqlite3")
    os.environ["COUNTERFACTUAL_DB_PATH"] = str(t / "counterfactual.sqlite3")

    # Minimal companion DBs for watchdog integrity checks.
    con = sqlite3.connect(os.environ["ANALYTICS_DB_PATH"])
    con.execute("CREATE TABLE analytics_trades(id INTEGER PRIMARY KEY, status TEXT, opened_at REAL)")
    con.commit(); con.close()
    con = sqlite3.connect(os.environ["COUNTERFACTUAL_DB_PATH"])
    con.execute("CREATE TABLE counterfactuals(id INTEGER PRIMARY KEY, status TEXT, target_at REAL)")
    con.commit(); con.close()

    import risk_intelligence_shadow as ri
    importlib.reload(ri)

    history = [
        {"pair":"BTC/USDT:USDT","side":"LONG","regime":"UP","mode":"STRICT","status":"CLOSED",
         "net_pct":-0.20,"expected_edge_pct":0.08,"btc_15m_pct":-0.20,"oi_15m_pct":-0.70,
         "funding_rate_pct":0.025,"long_short_ratio":1.30,"opened_at":100+i}
        for i in range(6)
    ]
    ri._analytics_rows = lambda where="", params=(): history
    ri._open_analytics_rows = lambda: []

    base = time.time() - 300
    r = {
        "pair":"BTC/USDT:USDT","direction":"LONG","action":"DROP","reason":"strict_edge_buffer",
        "signal":{"direction":"LONG","structure":"UP","ema_fast":101,"ema_slow":100,"rsi":60,"volume_ratio":1.1,"reason":"all LONG conditions met"},
        "edge":{"passed":False,"reason":"strict_edge_buffer","net_edge_pct":0.08,"expected_move_pct":0.30,"total_cost_pct":0.20,"min_required_net_edge_pct":0.05},
        "jev":{"verdict":"WAIT","confidence":0.5,"reason":"strict_edge_buffer"},
        "context":{"samples":40,"price_change_15m_pct":0.20,"oi_change_15m_pct":-0.70,"funding_rate_pct":0.025,"long_short_ratio":1.35,"btc_price_change_15m_pct":-0.20},
        "market":{"last_price":100.0,"spread_pct":0.01,"atr_pct":0.20,"atr_pct_median":0.08},
    }
    a = ri.observe_results([r], now=base)
    assert a["status"] == "ok" and a["created"] == 1 and a["blackbox"] == 1, a

    r2 = dict(r); r2["market"] = dict(r["market"]); r2["market"]["last_price"] = 99.0
    b = ri.observe_results([r2], now=base+300)
    assert b["status"] == "ok" and b["closed"] >= 1 and b["blackbox"] == 1, b

    q = ri.quality_report()
    assert q["status"] == "ok"
    assert isinstance(q["guard_effectiveness"], list) and q["guard_effectiveness"], q
    assert len(q["confidence_calibration"]) == 5
    assert "promotion_gate" in q and "drift" in q and "watchdog" in q
    assert q["watchdog"]["total"] == 7, q["watchdog"]

    rp = ri.replay(limit=5)
    assert rp["status"] == "ok" and rp["items"], rp
    latest = rp["items"][0]
    assert "stages" in latest and "tech" in latest["stages"] and "edge" in latest["stages"]
    assert "risk_intelligence" in latest["stages"] and "final" in latest["stages"]

    print("RISK_QUALITY_V2_SELFTEST_OK")
    print("matrix_guards=", len(q["guard_effectiveness"]))
    print("confidence_bins=", len(q["confidence_calibration"]))
    print("watchdog=", str(q["watchdog"]["ok_n"]) + "/" + str(q["watchdog"]["total"]))
    print("replay_items=", len(rp["items"]))


try:
    run()
except Exception as exc:
    print("RISK_QUALITY_V2_SELFTEST_FAIL")
    print(f"{type(exc).__name__}: {exc}")
    traceback.print_exc(file=sys.stdout)
    sys.exit(1)

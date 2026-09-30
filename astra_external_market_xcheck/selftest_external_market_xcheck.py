from pathlib import Path
import importlib
import os
import tempfile
import time
import uuid


def result(price, side="SHORT"):
    return {
        "pair":"BTC/USDT:USDT",
        "direction":side,
        "signal":{"direction":side,"tech_score":4},
        "market":{"last_price":price},
        "edge":{"net_edge_pct":0.12,"total_cost_pct":0.18},
        "action":"ENTER",
        "reason":"test",
    }


def run():
    tmp = Path(tempfile.gettempdir()) / ("myshka_external_xcheck_" + uuid.uuid4().hex)
    tmp.mkdir()
    os.environ["EXTERNAL_XCHECK_DB_PATH"] = str(tmp / "external.sqlite3")
    os.environ["EXTERNAL_XCHECK_ENABLED"] = "false"
    os.environ["INVESTING_XCHECK_ENABLED"] = "false"
    os.environ["MACRO_CROSSMARKET_ENABLED"] = "false"
    os.environ["EXTERNAL_XCHECK_HORIZONS_SEC"] = "300,600,900"

    import external_market_xcheck as ex
    importlib.reload(ex)
    ex.init()

    parsed = ex._parse_investing_summary(
        "<html><body>BTC/USD technical summary "
        "30 Min Strong Sell Hourly Strong Sell 5 Hours Sell Daily Buy Weekly Buy Monthly Neutral"
        "</body></html>"
    )
    assert parsed["ok"] is True, parsed
    assert parsed["direction"] == "SHORT", parsed

    now = time.time()
    ex._INV_CACHE["BTC"] = {
        "symbol":"BTC","slug":"bitcoin","fetched_at":now,"state":"READY","reason":"ok",
        "direction":"SHORT","score":-0.8,
        "ratings":{"30m":"STRONG SELL","1h":"STRONG SELL","5h":"SELL","1d":"BUY"},
    }
    ex._MACRO_CACHE.clear()
    ex._MACRO_CACHE.update({
        "fetched_at":now,"state":"RISK_OFF","score":-0.5,"sources_ok":5,
        "assets":{"NASDAQ100":{"ok":True,"change_5m_pct":-0.2}},
    })

    a = result(100.0, "SHORT")
    out1 = ex.observe_results([a], now=1000.0)
    assert a["investing_xcheck"]["state"] == "AGREE", a
    assert a["macro_crossmarket"]["state"] == "AGREE", a
    assert a["external_xcheck"]["state"] == "BOTH_AGREE", a
    assert a["action"] == "ENTER" and a["reason"] == "test", a
    assert out1["created"] == 3, out1

    b = result(99.0, "SHORT")
    out2 = ex.observe_results([b], now=1300.0)
    assert out2["closed"] == 1, out2

    rep = ex.report()
    m = rep["by_horizon"]["300"]["by_combined"]["BOTH_AGREE"]
    assert m["n"] == 1, rep
    assert 0.80 < m["avg_net_pct"] < 0.84, m
    assert rep["changes_trading_decisions"] is False, rep
    assert rep["live_execution"] is False, rep

    print("EXTERNAL_MARKET_XCHECK_V1_SELFTEST_OK")
    print("investing_direction=", parsed["direction"])
    print("combined=", a["external_xcheck"]["state"])
    print("forward_5m_n=", m["n"])
    print("forward_5m_avg_net_pct=", round(m["avg_net_pct"], 4))


if __name__ == "__main__":
    run()

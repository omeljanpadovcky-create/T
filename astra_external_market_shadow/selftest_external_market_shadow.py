from pathlib import Path
import importlib
import os
import tempfile
import time
import uuid


def result(price: float, side: str = "SHORT") -> dict:
    return {
        "pair":"BTC/USDT:USDT",
        "direction":side,
        "signal":{"direction":side,"tech_score":4},
        "market":{"last_price":price},
        "edge":{"passed":True,"net_edge_pct":0.12,"total_cost_pct":0.20},
        "jev":{"verdict":"APPROVE"},
        "evidence_gate":{"state":"PASS","passed":True},
        "adaptive_learner":{"state":"PASS"},
        "action":"ENTER",
        "reason":"test_enter",
    }


def run() -> None:
    tmp = Path(tempfile.gettempdir()) / ("myshka_external_market_" + uuid.uuid4().hex)
    tmp.mkdir()
    os.environ["EXTERNAL_MARKET_SHADOW_DB_PATH"] = str(tmp / "ext.sqlite3")
    os.environ["EXTERNAL_MARKET_SHADOW_ENABLED"] = "false"
    os.environ["EXTERNAL_MARKET_SHADOW_HORIZONS_SEC"] = "300,600,900"

    import external_market_shadow as ext
    importlib.reload(ext)
    ext.init()

    raw = """
    BTC/USD technical summary
    30 Min Strong Sell Hourly Sell 5 Hours Strong Sell Daily Neutral
    """
    parsed = ext._parse_investing_summary(raw, ticker="BTC")
    assert parsed["state"] == "SHORT", parsed

    now = time.time()
    ext._INV_CACHE["BTC"] = {
        "ticker":"BTC",
        "state":"SHORT",
        "score":-1.35,
        "frames":{"30m":"STRONG SELL","1h":"SELL","5h":"STRONG SELL","1d":"NEUTRAL"},
        "reason":"ok",
        "source":"investing.com",
        "fetched_at":now,
    }
    ext._MACRO_CACHE.update({
        "state":"RISK_OFF",
        "score":-3.0,
        "changes_5m_pct":{"NDX":-0.20,"DXY":0.05,"GOLD":0.03,"WTI":0.04,"VIX":0.50},
        "sources_ok":5,
        "source":"test",
        "fetched_at":now,
    })

    a = result(100.0, "SHORT")
    action_before = a["action"]
    reason_before = a["reason"]
    out1 = ext.observe_results([a], now=1000.0)
    assert out1["created"] == 3, out1
    assert a["action"] == action_before and a["reason"] == reason_before, a
    assert a["external_market_shadow"]["investing"]["alignment"] == "AGREE", a
    assert a["external_market_shadow"]["macro"]["alignment"] == "AGREE", a
    assert a["external_market_shadow"]["combined_state"] == "BOTH_AGREE", a

    # Same side, lower price after 5m => profitable SHORT before costs.
    b = result(99.0, "SHORT")
    out2 = ext.observe_results([b], now=1300.0)
    assert out2["closed"] == 1, out2

    rep = ext.report()
    h = rep["by_horizon"]["300"]
    anchor = h["anchor_jev_approve_tech3plus"]
    both = h["by_combined"]["BOTH_AGREE"]
    assert anchor["n"] == 1, rep
    assert both["n"] == 1, rep
    assert both["avg_net_pct"] > 0.7, rep
    assert rep["auto_gate_enable"] is False, rep
    assert rep["changes_trading_decisions"] is False, rep

    # Explicit conflict check.
    assert ext._alignment("LONG", "SHORT") == "CONFLICT"
    assert ext._alignment("LONG", "RISK_OFF", macro=True) == "CONFLICT"

    print("EXTERNAL_MARKET_SHADOW_V1_SELFTEST_OK")
    print("combined=", a["external_market_shadow"]["combined_state"])
    print("anchor_5m_n=", anchor["n"])
    print("both_agree_5m_avg_net_pct=", round(both["avg_net_pct"], 4))
    print("action_unchanged=", a["action"] == action_before)
    print("auto_gate_enable=", rep["auto_gate_enable"])


if __name__ == "__main__":
    run()

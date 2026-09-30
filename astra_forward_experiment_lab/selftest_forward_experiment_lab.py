import importlib
import os
from pathlib import Path
import tempfile
import uuid


def _result(pair, price, direction="LONG", tech="strict", xstate="AGREE"):
    if direction == "LONG":
        ema_fast, ema_slow, structure, rsi = 101.0, 100.0, "UP", 60.0
    else:
        ema_fast, ema_slow, structure, rsi = 99.0, 100.0, "DOWN", 40.0
    sig_dir = direction if tech == "strict" else "WAIT"
    vol = 1.2 if tech == "strict" else 0.4  # relaxed case: 3/4
    return {
        "pair": pair,
        "direction": sig_dir,
        "action": "DROP",
        "reason": "selftest",
        "signal": {
            "direction": sig_dir,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "structure": structure,
            "rsi": rsi,
            "volume_ratio": vol,
        },
        "market": {"last_price": price, "atr_pct": 0.08},
        "edge": {"net_edge_pct": 0.09, "total_cost_pct": 0.18, "basis": "selftest"},
        "context": {
            "price_change_5m_pct": 0.1,
            "price_change_15m_pct": 0.2,
            "oi_change_15m_pct": 0.05,
            "funding_rate": 0.001,
            "long_short_ratio": 1.1,
        },
        "binance_crosscheck": {"state": xstate, "score": 0.12},
    }


def run():
    root = Path(tempfile.gettempdir()) / ("myshka_forward_lab_test_" + uuid.uuid4().hex)
    root.mkdir(parents=True, exist_ok=True)
    os.environ["FORWARD_EXPERIMENT_DB_PATH"] = str(root / "forward.sqlite3")
    os.environ["FORWARD_EXPERIMENT_MAX_SETTLE_DELAY_SEC"] = "300"

    import forward_experiment_lab as lab
    importlib.reload(lab)

    base = 1_800_000_000.0
    assert lab.init()["enabled"] is True

    r1 = _result("BTC/USDT:USDT", 100.0, "LONG", "strict", "AGREE")
    r2 = _result("ETH/USDT:USDT", 200.0, "SHORT", "relaxed", "NO_DATA")
    o1 = lab.observe_results([r1, r2], now=base)
    assert o1["status"] == "ok", o1
    assert o1["created"] == 6, o1

    # 5m settlement
    s1 = _result("BTC/USDT:USDT", 101.0, "LONG", "strict", "AGREE")
    s2 = _result("ETH/USDT:USDT", 198.0, "SHORT", "relaxed", "NO_DATA")
    o2 = lab.observe_results([s1, s2], now=base + 300)
    assert o2["closed"] >= 2, o2

    # 10m settlement
    o3 = lab.observe_results([s1, s2], now=base + 600)
    assert o3["closed"] >= 2, o3

    # 15m settlement
    o4 = lab.observe_results([s1, s2], now=base + 900)
    assert o4["closed"] >= 2, o4

    rep = lab.report()
    assert rep["status"] == "ok", rep
    assert rep["mode"] == "FORWARD_SHADOW_ONLY"
    assert rep["changes_paper_execution"] is False
    assert rep["xcheck_definition"]["audit"] == "DIRECTION_LOGIC_VERIFIED"

    h5 = rep["by_horizon"]["300"]
    assert h5["all"]["n"] >= 2, h5
    assert h5["by_tech"]["TECH_4_OF_4"]["n"] >= 1, h5
    assert h5["by_tech"]["TECH_3_OF_4"]["n"] >= 1, h5
    assert h5["by_xcheck"]["AGREE"]["n"] >= 1, h5
    assert h5["all"]["cluster_n"] >= 2, h5

    print("FORWARD_EXPERIMENT_LAB_SELFTEST_OK")
    print("created=", o1["created"])
    print("5m_n=", h5["all"]["n"], "5m_cluster_n=", h5["all"]["cluster_n"])
    print("5m_avg_net=", round(h5["all"]["avg_net_pct"], 6))


if __name__ == "__main__":
    run()

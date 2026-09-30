from pathlib import Path
import importlib
import os
import tempfile
import uuid


def strict(price, action="DROP"):
    return {
        "pair":"QNT/USDT:USDT",
        "action":action,
        "reason":"test",
        "direction":"LONG",
        "signal":{"direction":"LONG","structure":"UP","ema_fast":101,"ema_slow":100,"rsi":60,"volume_ratio":1.2},
        "edge":{"net_edge_pct":0.10,"total_cost_pct":0.20,"basis":"shrunk_bucket"},
        "context":{"price_change_5m_pct":0.0,"price_change_15m_pct":0.0},
        "market":{"last_price":price},
    }


def wait(price):
    return {
        "pair":"QNT/USDT:USDT",
        "action":"WAIT",
        "direction":"WAIT",
        "signal":{"direction":"WAIT","structure":"RANGE","ema_fast":100,"ema_slow":100,"rsi":50,"volume_ratio":0.2},
        "market":{"last_price":price},
    }


def run():
    tmp = Path(tempfile.gettempdir()) / ("myshka_mh_" + uuid.uuid4().hex)
    tmp.mkdir()
    os.environ["MULTIHORIZON_DB_PATH"] = str(tmp / "mh.sqlite3")
    os.environ["MULTIHORIZON_HORIZONS_SEC"] = "300,600,900"
    import multihorizon_shadow as mh
    importlib.reload(mh)

    a = mh.observe_results([strict(100.0)], now=1000.0)
    assert a["created"] == 3, a
    mh.observe_results([wait(101.0)], now=1300.0)
    mh.observe_results([wait(102.0)], now=1600.0)
    mh.observe_results([wait(103.0)], now=1900.0)

    rep = mh.report()
    assert rep["by_horizon"]["300"]["all_strict"]["n"] == 1, rep
    assert rep["by_horizon"]["600"]["all_strict"]["n"] == 1, rep
    assert rep["by_horizon"]["900"]["all_strict"]["n"] == 1, rep
    assert rep["by_horizon"]["300"]["all_strict"]["avg_net_pct"] > 0, rep
    assert rep["by_horizon"]["900"]["all_strict"]["avg_net_pct"] > rep["by_horizon"]["300"]["all_strict"]["avg_net_pct"], rep

    print("MULTIHORIZON_SHADOW_V1_SELFTEST_OK")
    print(rep["by_horizon"])


if __name__ == "__main__":
    run()

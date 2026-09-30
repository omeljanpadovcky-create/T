from pathlib import Path
import importlib
import os
import tempfile
import time
import uuid


def result(price, side="LONG"):
    return {
        "pair":"QNT/USDT:USDT",
        "direction":side,
        "signal":{"direction":side},
        "market":{"last_price":price},
        "action":"DROP",
        "reason":"test",
    }


def run():
    tmp = Path(tempfile.gettempdir()) / ("myshka_binance_crosscheck_" + uuid.uuid4().hex)
    tmp.mkdir()
    os.environ["BINANCE_CROSSCHECK_DB_PATH"] = str(tmp / "cross.sqlite3")
    os.environ["BINANCE_CROSSCHECK_ENABLED"] = "false"
    os.environ["BINANCE_CROSSCHECK_HORIZONS_SEC"] = "300,600,900"

    import binance_signal_crosscheck as bx
    importlib.reload(bx)
    bx.init()

    # Inject a fresh public Binance snapshot. No network in self-test.
    bx._CACHE["QNTUSDT"] = {
        "symbol":"QNTUSDT",
        "fetched_at":time.time(),
        "period":"5m",
        "crowd_direction":"LONG",
        "crowd_score":0.20,
        "global_long":0.58,"global_short":0.42,
        "top_long":0.62,"top_short":0.38,
        "top_position_long":0.60,"top_position_short":0.40,
        "sources_ok":3,
    }

    a = result(100.0, "LONG")
    out1 = bx.observe_results([a], now=1000.0)
    assert a["binance_crosscheck"]["state"] == "AGREE", a
    assert out1["created"] == 3, out1

    b = result(101.0, "LONG")
    out2 = bx.observe_results([b], now=1300.0)
    assert out2["closed"] == 1, out2

    rep = bx.report()
    m = rep["by_horizon"]["300"]["AGREE"]
    assert m["n"] == 1, rep
    assert m["win_rate_pct"] == 100.0, rep
    assert m["avg_gross_pct"] > 0.9, rep

    c = bx._consensus("SHORT", bx._snapshot("QNTUSDT"))
    assert c["state"] == "CONFLICT", c

    print("BINANCE_SIGNAL_CROSSCHECK_V1_SELFTEST_OK")
    print("agree_5m_n=", m["n"])
    print("agree_5m_avg_gross_pct=", round(m["avg_gross_pct"], 4))
    print("short_vs_long_crowd=", c["state"])


if __name__ == "__main__":
    run()

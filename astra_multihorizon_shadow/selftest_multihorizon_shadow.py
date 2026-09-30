from pathlib import Path
import importlib
import os
import sqlite3
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
    mh_db = tmp / "mh.sqlite3"
    analytics_db = tmp / "analytics.sqlite3"
    os.environ["MULTIHORIZON_DB_PATH"] = str(mh_db)
    os.environ["ANALYTICS_DB_PATH"] = str(analytics_db)
    os.environ["MULTIHORIZON_HORIZONS_SEC"] = "300,600,900"

    ac = sqlite3.connect(analytics_db)
    ac.execute(
        """
        CREATE TABLE analytics_trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT, mode TEXT, opened_at REAL,
            gross_pct REAL, net_pct REAL, direction_hit INTEGER
        )
        """
    )
    ac.execute(
        "INSERT INTO analytics_trades(status,mode,opened_at,gross_pct,net_pct,direction_hit) VALUES('CLOSED','STRICT',1000,1.0,0.8,1)"
    )
    ac.commit(); ac.close()
    import multihorizon_shadow as mh
    importlib.reload(mh)

    a = mh.observe_results([strict(100.0)], now=1000.0)
    assert a["created"] == 3, a

    mc = sqlite3.connect(mh_db)
    mc.execute(
        "INSERT OR REPLACE INTO mh_meta(key,value) VALUES('post_calibration_v2_started_at','999')"
    )
    mc.commit(); mc.close()
    mh.observe_results([wait(101.0)], now=1300.0)
    mh.observe_results([wait(102.0)], now=1600.0)
    mh.observe_results([wait(103.0)], now=1900.0)

    rep = mh.report()
    assert rep["by_horizon"]["300"]["all_strict"]["n"] == 1, rep
    assert rep["by_horizon"]["600"]["all_strict"]["n"] == 1, rep
    assert rep["by_horizon"]["900"]["all_strict"]["n"] == 1, rep
    assert rep["by_horizon"]["300"]["all_strict"]["avg_net_pct"] > 0, rep
    assert rep["by_horizon"]["900"]["all_strict"]["avg_net_pct"] > rep["by_horizon"]["300"]["all_strict"]["avg_net_pct"], rep

    post = mh.post_calibration_report()
    assert post["paper_strict"]["n"] == 1, post
    assert post["paper_strict"]["win_rate_pct"] == 100.0, post
    assert post["by_horizon"]["300"]["calibration_band_0.08_0.15"]["n"] == 1, post
    assert post["by_horizon"]["600"]["calibration_band_0.08_0.15"]["n"] == 1, post
    assert post["by_horizon"]["900"]["calibration_band_0.08_0.15"]["n"] == 1, post

    st = mh.status()
    assert "error" not in st, st

    print("MULTIHORIZON_SHADOW_V1_SELFTEST_OK")
    print("POST_CALIBRATION_V2_SELFTEST_OK")
    print(post)


if __name__ == "__main__":
    run()

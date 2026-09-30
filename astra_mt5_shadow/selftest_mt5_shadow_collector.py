import importlib
import os
import time


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeMT5:
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60

    def initialize(self, timeout=10000):
        return True

    def terminal_info(self):
        return Obj(connected=True, trade_allowed=False)

    def account_info(self):
        return Obj(server="Libertex-Demo", company="Libertex", currency="USD")

    def last_error(self):
        return (0, "ok")

    def symbols_get(self):
        return [Obj(name="BTCUSD"),Obj(name="ETHUSD"),Obj(name="XAUUSD")]

    def symbol_select(self, symbol, selected):
        return True

    def symbol_info_tick(self, symbol):
        return Obj(bid=100.0, ask=100.1)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        rows = []
        base = 95.0
        for i in range(max(60,count)):
            px = base + i*0.10
            rows.append({"close":px})
        return rows

    def shutdown(self):
        return None


def run():
    os.environ["MT5_SHADOW_TOKEN"] = "test"
    import mt5_shadow_collector as c
    importlib.reload(c)
    c.mt5 = FakeMT5()
    c.IMPORT_ERROR = None
    c._CACHE.clear()

    out = c.snapshot("BTC")
    assert out["status"] == "READY", out
    assert out["symbol"] == "BTCUSD", out
    assert out["direction"] == "LONG", out
    assert out["read_only"] is True, out
    assert out["terminal"]["company"] == "Libertex", out

    src = open(c.__file__, "r", encoding="utf-8").read()
    forbidden = "order" + "_send"
    assert forbidden not in src, "collector must never contain MT5 trade execution call"

    print("MT5_SHADOW_COLLECTOR_V1_SELFTEST_OK")
    print("symbol=", out["symbol"])
    print("direction=", out["direction"])
    print("company=", out["terminal"]["company"])
    print("read_only=", out["read_only"])
    print("trade_execution_api_present=", False)


if __name__ == "__main__":
    run()

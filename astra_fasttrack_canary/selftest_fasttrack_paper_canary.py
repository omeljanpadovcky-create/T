import os
import sqlite3
import tempfile
import time
try:
    from . import fasttrack_paper_canary as c
except Exception:
    import fasttrack_paper_canary as c


def ok(cond, msg):
    if not cond:
        raise AssertionError(msg)


_test_dir = tempfile.mkdtemp(prefix="myshka_canary_selftest_")
c.DB_PATH = os.path.join(_test_dir, "canary.sqlite3")
c._EVENTS.clear()
c._db_init()

with sqlite3.connect(c.DB_PATH) as _con:
    _tables = {str(r[0]) for r in _con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
ok("canary_events" in _tables, "canary_events schema was not created")

calls = []


def fake_send(pair, side, **kwargs):
    calls.append((pair, side, kwargs))
    return {
        "status": "sent",
        "http_status": 200,
        "real_money_execution": False,
        "dry_run_confirmed_local": True,
        "dry_run_confirmed_remote": True,
    }


c.bridge._send = fake_send
c.bridge._token = lambda: ("tok", {"authenticated": True})
c._remote_dry_run = lambda token: True
c._canary_open_count = lambda token: 0

now = time.time()
good = {
    "pair": "BTC/USDT:USDT",
    "signal": {
        "direction": "WAIT",
        "ema_fast": 101.0,
        "ema_slow": 100.0,
        "structure": "UP",
        "rsi": 58.0,
        "volume_ratio": 0.50,
    },
    "market": {"last_price": 100.0},
    "jev": {"verdict": "APPROVE"},
    "binance_crosscheck": {"state": "AGREE"},
}

r1 = c.observe_results([good], now=now)
time.sleep(0.15)
ok(r1["eligible"] == 1 and r1["claimed"] == 1, "good triple not claimed")
ok(len(calls) == 1, "canary did not send exactly once")
pair, side, kw = calls[0]
ok(pair == "BTC/USDT:USDT" and side == "long", "wrong direction")
ok(float(kw["stake_usdt"]) == 10.0, "wrong default stake")
ok(float(kw["leverage"]) == 1.0, "canary leverage must be 1x")
ok(kw["source"] == "fasttrack_canary", "wrong source tag")

r2 = c.observe_results([good], now=now + 10)
time.sleep(0.10)
ok(r2["eligible"] == 1 and r2["claimed"] == 0, "5m dedupe failed")
ok(len(calls) == 1, "duplicate canary order attempted")

bad = dict(good)
bad["pair"] = "ETH/USDT:USDT"
bad["jev"] = {"verdict": "REJECT"}
r3 = c.observe_results([bad], now=now)
time.sleep(0.10)
ok(r3["eligible"] == 0, "JEV reject entered canary")
ok(len(calls) == 1, "bad candidate sent an order")

st = c.status()
ok(st["real_money_execution"] is False, "unsafe real-money flag")
ok(st["leverage"] == 1.0, "status leverage not 1x")
ok(st["max_concurrent"] == 1, "default max concurrent must be 1")

print("[OK] FastTrack PAPER Canary self-test passed")
print("[OK] TECH3 + JEV APPROVE + Binance AGREE gate verified")
print("[OK] 5m dedupe verified")
print("[OK] 10 USDT / 1x / max 1 canary defaults verified")
print("[OK] real_money_execution=False verified")

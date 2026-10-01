from pathlib import Path
import tempfile
import time
import execution_slippage_audit as audit


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


tmp = tempfile.NamedTemporaryFile(prefix="slip_", suffix=".jsonl", delete=False)
tmp.close()
audit.LOG_PATH = tmp.name
audit._EVENTS.clear()
audit._telegram = lambda text: {"status": "mocked"}

send_ms = int(time.time() * 1000)
trade = {
    "trade_id": 7,
    "pair": "BTC/USDT:USDT",
    "is_short": False,
    "open_rate": 100.20,
    "open_rate_requested": 100.00,
    "open_date_timestamp": send_ms + 80,
}

def fetch():
    return 200, [trade]

audit._audit_worker(
    fetch_open_trades=fetch,
    pair="BTC/USDT:USDT",
    side="long",
    signal_price=100.00,
    signal_ts_ms=send_ms - 40,
    send_ts_ms=send_ms,
    source="selftest",
    execution_mode="DRY_RUN",
    stake_usdt=10.0,
)

items = audit.recent(5)["items"]
assert_true(len(items) == 1, "audit event missing")
x = items[0]
assert_true(x["status"] == "recorded", "audit status not recorded")
assert_true(abs(float(x["slippage_bps"]) - 20.0) < 1e-6, "slippage bps math wrong")
assert_true(int(x["engine_latency_ms"]) == 40, "engine latency wrong")
assert_true(int(x["exchange_latency_ms"]) == 80, "exchange latency wrong")
assert_true(x["simulated_fill"] is True, "dry-run marker missing")
assert_true(x["real_money_execution"] is False, "unsafe live marker")

print("[OK] execution slippage audit self-test passed")
print("[OK] direction-aware slippage / engine latency / exchange latency verified")
print("[OK] DRY_RUN marker verified")

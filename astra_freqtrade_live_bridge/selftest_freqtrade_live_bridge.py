import importlib
import os
import time


def good_result():
    return {
        "pair":"BTC/USDT:USDT",
        "action":"ENTER",
        "reason":"test_enter",
        "direction":"LONG",
        "signal":{"direction":"LONG"},
        "market":{"last_price":100.0},
        "edge":{"passed":True,"net_edge_pct":0.12,"total_cost_pct":0.08},
        "jev":{"verdict":"APPROVE"},
        "guard":{"passed":True},
        "evidence_gate":{"passed":True},
        "adaptive_learner":{"applies":False,"state":"NOT_APPLICABLE"},
    }


def run():
    os.environ["ASTRA_LIVE_EXECUTION"] = "true"
    os.environ["ASTRA_LIVE_CONFIRM"] = "REAL_MONEY_CONFIRMED"
    os.environ["ASTRA_LIVE_KILL_SWITCH"] = "false"
    os.environ["FREQTRADE__DRY_RUN"] = "false"
    os.environ["ASTRA_LIVE_MAX_STAKE_USDT"] = "10"
    os.environ["ASTRA_LIVE_MAX_LEVERAGE"] = "1"
    os.environ["FREQTRADE_USERNAME"] = "dummy"
    os.environ["FREQTRADE_PASSWORD"] = "dummy"

    from . import freqtrade_live_bridge as m
    importlib.reload(m)

    calls = []

    def fake_request(path, *, method="GET", token=None, payload=None, basic=False):
        calls.append((path, method, payload))
        if path == "/api/v1/token/login":
            return 200, {"access_token":"TEST"}
        if path == "/api/v1/show_config":
            return 200, {"dry_run":False,"trading_mode":"futures"}
        if path == "/api/v1/whitelist":
            return 200, {"whitelist":["BTC/USDT:USDT","ETH/USDT:USDT","SOL/USDT:USDT"]}
        if path == "/api/v1/count":
            return 200, {"current":0,"max":3}
        if path == "/api/v1/status":
            return 200, []
        if path == "/api/v1/forceenter":
            return 201, {"trade_id":123,"pair":"BTC/USDT:USDT","is_open":True}
        raise AssertionError(path)

    m._request = fake_request
    r = good_result()
    action_before = r["action"]
    reason_before = r["reason"]

    out = m.observe_results([r])
    assert out["sent"] == 1, out
    assert out["real_money_execution"] is True, out
    assert r["action"] == action_before and r["reason"] == reason_before, r
    assert any(p == "/api/v1/forceenter" and meth == "POST" for p,meth,_ in calls), calls

    # Remote dry-run=true must block.
    m._LAST_SENT.clear()
    def remote_dry_request(path, *, method="GET", token=None, payload=None, basic=False):
        if path == "/api/v1/token/login":
            return 200, {"access_token":"TEST"}
        if path == "/api/v1/show_config":
            return 200, {"dry_run":True}
        if path == "/api/v1/whitelist":
            return 200, {"whitelist":["BTC/USDT:USDT"]}
        if path == "/api/v1/count":
            return 200, {"current":0,"max":3}
        if path == "/api/v1/status":
            return 200, []
        if path == "/api/v1/forceenter":
            raise AssertionError("forceenter must not be reached when remote dry_run=true")
        return 404, {}

    m._request = remote_dry_request
    blocked = m._send("BTC/USDT:USDT","long",stake_usdt=10,leverage=1,source="test",tag="test")
    assert blocked["status"] == "blocked", blocked
    assert blocked["guard"]["checks"]["remote_dry_run_false"] is False, blocked

    # Local dry-run=true must disable live path before network/order.
    os.environ["FREQTRADE__DRY_RUN"] = "true"
    disabled = m.observe_results([good_result()])
    assert disabled["status"] == "disabled", disabled
    assert disabled["sent"] == 0, disabled

    # Kill switch must disable.
    os.environ["FREQTRADE__DRY_RUN"] = "false"
    os.environ["ASTRA_LIVE_KILL_SWITCH"] = "true"
    killed = m.observe_results([good_result()])
    assert killed["status"] == "disabled", killed

    print("FREQTRADE_LIVE_BRIDGE_V1_SELFTEST_OK")
    print("mock_live_send=", out["sent"])
    print("remote_dry_run_true_blocked=", blocked["status"])
    print("local_dry_run_true_disabled=", disabled["status"])
    print("kill_switch_disabled=", killed["status"])
    print("real_exchange_calls=0")


if __name__ == "__main__":
    run()

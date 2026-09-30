from . import freqtrade_dryrun_bridge as m

def run():
    assert m.MODE == "FREQTRADE_DRYRUN_EXECUTION_BRIDGE_V1"
    assert m.status()["real_money_execution"] is False
    bad = m.smoke("BTC/USDT:USDT", "long", confirm="NO")
    assert bad["status"] == "blocked"
    assert bad["real_money_execution"] is False

    old = m.os.environ.get("FREQTRADE__DRY_RUN")
    m.os.environ["FREQTRADE__DRY_RUN"] = "false"
    try:
        try:
            m._request("/api/v1/forceenter", method="POST", payload={})
            raise AssertionError("forceenter should be blocked when dry_run=false")
        except RuntimeError:
            pass
    finally:
        if old is None:
            m.os.environ.pop("FREQTRADE__DRY_RUN", None)
        else:
            m.os.environ["FREQTRADE__DRY_RUN"] = old

    print("FREQTRADE_DRYRUN_BRIDGE_SELFTEST_OK")
    print("real_money_execution=", m.status()["real_money_execution"])
    print("manual_confirm_guard=PASS")
    print("local_dry_run_hard_block=PASS")

if __name__ == "__main__":
    run()

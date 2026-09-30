from . import live_armed_preflight as m

def run():
    p=m.build_forceenter_preview("BTC/USDT:USDT","long",stake_usdt=10,leverage=1)
    assert p["endpoint_preview"]=="/api/v1/forceenter", p
    assert p["execution_enabled"] is False, p
    assert p["forceenter_called"] is False, p
    assert p["financial_post_calls"]==0, p
    assert p["manual_confirmation_required"] is True, p
    try:
        m._json_request("/api/v1/forceenter", method="POST")
        raise AssertionError("forceenter POST was not blocked")
    except RuntimeError:
        pass
    print("LIVE_ARMED_PREFLIGHT_SELFTEST_OK")
    print("execution_enabled=",p["execution_enabled"])
    print("forceenter_called=",p["forceenter_called"])
    print("financial_post_calls=",p["financial_post_calls"])
    print("manual_confirmation_required=",p["manual_confirmation_required"])

if __name__=="__main__":
    run()

from . import live_dry_run as m

def run():
    good = {
        "pair":"BTC/USDT:USDT",
        "action":"ENTER",
        "direction":"LONG",
        "signal":{"direction":"LONG"},
        "market":{"last_price":100.0},
        "edge":{"passed":True,"net_edge_pct":0.12,"total_cost_pct":0.08},
        "jev":{"verdict":"APPROVE"},
        "guard":{"passed":True},
        "evidence_gate":{"passed":True},
        "adaptive_learner":{"applies":False,"state":"NOT_APPLICABLE"},
    }
    p=m.build_preview(good, now=1234.0)
    assert p["would_send_order"] is True, p
    assert p["execution_blocked"] is True, p
    assert p["create_order_called"] is False, p
    assert p["live_execution"] is False, p
    assert p["order_payload"]["side"]=="buy", p
    assert p["order_payload"]["stop_loss"] < 100 < p["order_payload"]["take_profit"], p

    bad=dict(good)
    bad["jev"]={"verdict":"WAIT"}
    q=m.build_preview(bad, now=1234.0)
    assert q["would_send_order"] is False, q
    assert "jev_approve" in q["preflight"]["blockers"], q

    obs=m.observe_results([good,bad], now=1234.0)
    assert obs["create_order_calls"]==0, obs
    assert obs["live_execution"] is False, obs

    print("LIVE_DRY_RUN_SELFTEST_OK")
    print("would_send_good=",p["would_send_order"])
    print("would_send_wait=",q["would_send_order"])
    print("execution_blocked=",p["execution_blocked"])
    print("create_order_calls=",obs["create_order_calls"])
    print("live_execution=",obs["live_execution"])

if __name__=="__main__":
    run()

from pathlib import Path
import importlib
import os
import sqlite3
import sys
import tempfile

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))

if len(sys.argv) < 2:
    raise SystemExit("usage: selftest_risk_intelligence.py <ASTRA_PROJECT_DIR>")

app = Path(sys.argv[1]).resolve()
if not (app / "analytics_shadow.py").exists():
    raise SystemExit(f"analytics_shadow.py not found in {app}")

# Put the real ASTRA project on sys.path so the self-test uses the exact
# installed Analytics V2 schema instead of a hand-written imitation.
sys.path.insert(0, str(app))

with tempfile.TemporaryDirectory() as td:
    t = Path(td)
    os.environ["RISK_INTELLIGENCE_DB_PATH"] = str(t / "risk.sqlite3")
    os.environ["ANALYTICS_DB_PATH"] = str(t / "analytics.sqlite3")

    import analytics_shadow
    importlib.reload(analytics_shadow)
    analytics_shadow.init()

    con = sqlite3.connect(os.environ["ANALYTICS_DB_PATH"])
    rows = [
        ("QNT/USDT:USDT","LONG","UP","STRICT",4,100.0,"CLOSED",-0.30,0.08,-0.20,-0.60,0.025,1.30),
        ("QNT/USDT:USDT","LONG","UP","STRICT",4,200.0,"CLOSED",-0.20,0.12,-0.15,-0.40,0.020,1.25),
        ("QNT/USDT:USDT","LONG","UP","STRICT",4,300.0,"CLOSED",-0.10,0.18,-0.10,-0.30,0.018,1.22),
        ("QNT/USDT:USDT","LONG","UP","STRICT",4,400.0,"CLOSED",-0.05,0.22,-0.05,-0.20,0.015,1.20),
        ("QNT/USDT:USDT","LONG","UP","STRICT",4,500.0,"CLOSED",-0.15,0.25,-0.12,-0.50,0.022,1.28),
    ]
    con.executemany(
        """
        INSERT INTO analytics_trades(
            pair,side,regime,mode,tech_score,opened_at,status,net_pct,
            expected_edge_pct,btc_15m_pct,oi_15m_pct,funding_rate_pct,long_short_ratio
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    con.commit()
    con.close()

    import risk_intelligence_shadow as ri
    importlib.reload(ri)

    st = ri.init()
    assert st.get("enabled") is True, st

    r = {
        "pair": "QNT/USDT:USDT",
        "direction": "LONG",
        "action": "DROP",
        "reason": "edge",
        "signal": {
            "direction": "LONG", "structure": "UP",
            "ema_fast": 101.0, "ema_slow": 100.0,
            "rsi": 60.0, "volume_ratio": 1.10,
        },
        "edge": {
            "net_edge_pct": 0.08, "expected_move_pct": 0.30,
            "total_cost_pct": 0.22, "passed": False,
        },
        "jev": {"verdict": "WAIT", "confidence": 0.50},
        "context": {
            "samples": 40,
            "price_change_15m_pct": 0.20,
            "oi_change_15m_pct": -0.70,
            "funding_rate_pct": 0.025,
            "long_short_ratio": 1.35,
            "btc_price_change_15m_pct": -0.20,
        },
        "market": {
            "last_price": 100.0,
            "spread_pct": 0.010,
            "atr_pct": 0.20,
            "atr_pct_median": 0.08,
        },
    }

    a = ri.observe_results([r], now=1000.0)
    assert a["status"] == "ok", a
    assert a["created"] == 1, a

    r2 = dict(r)
    r2["market"] = dict(r["market"])
    r2["market"]["last_price"] = 101.0
    b = ri.observe_results([r2], now=1300.0)
    assert b["status"] == "ok", b
    assert b["closed"] >= 1, b

    report = ri.report()
    assert report["status"] == "ok", report
    assert report["overall"]["n"] >= 1, report
    assert "0.05" in report["ab_edge"], report["ab_edge"]
    assert report["latest"] is not None, report
    assert 0 <= float(report["latest"]["confidence_score"]) <= 100, report["latest"]
    assert isinstance(report["flags"], list), type(report["flags"])
    assert report["latest"]["pair_hist_n"] >= 5, report["latest"]
    assert "PAIR_COOLDOWN" in report["latest"].get("flags", []), report["latest"].get("flags")
    assert "BTC_AGAINST" in report["latest"].get("flags", []), report["latest"].get("flags")
    assert "OI_PRICE_DIVERGENCE" in report["latest"].get("flags", []), report["latest"].get("flags")
    assert "FUNDING_EXTREME" in report["latest"].get("flags", []), report["latest"].get("flags")
    assert "VOLATILITY_SHOCK" in report["latest"].get("flags", []), report["latest"].get("flags")

    print("RISK_INTELLIGENCE_SELFTEST_OK")
    print("closed=", report["overall"]["n"])
    print("confidence=", report["latest"].get("confidence_score"))
    print("flags=", report["latest"].get("flags"))

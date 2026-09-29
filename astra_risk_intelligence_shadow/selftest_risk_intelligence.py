from pathlib import Path
import importlib
import os
import sqlite3
import sys
import tempfile
import traceback

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))

if len(sys.argv) < 2:
    raise SystemExit("usage: selftest_risk_intelligence.py <ASTRA_PROJECT_DIR>")

app = Path(sys.argv[1]).resolve()
if not (app / "analytics_shadow.py").exists():
    raise SystemExit(f"analytics_shadow.py not found in {app}")
sys.path.insert(0, str(app))


def run() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        t = Path(td)
        os.environ["RISK_INTELLIGENCE_DB_PATH"] = str(t / "risk.sqlite3")
        os.environ["ANALYTICS_DB_PATH"] = str(t / "analytics.sqlite3")

        # 1) Compatibility check against the exact installed Analytics V2 module.
        import analytics_shadow
        importlib.reload(analytics_shadow)
        analytics_shadow.init()
        con = sqlite3.connect(os.environ["ANALYTICS_DB_PATH"])
        cols = {row[1] for row in con.execute("PRAGMA table_info(analytics_trades)").fetchall()}
        con.close()
        required = {
            "pair","side","regime","mode","status","net_pct","expected_edge_pct",
            "btc_15m_pct","oi_15m_pct","funding_rate_pct","long_short_ratio","opened_at"
        }
        missing = sorted(required - cols)
        assert not missing, f"Analytics V2 schema missing columns: {missing}"

        # 2) Risk logic uses deterministic in-memory history. This avoids making
        # the unit test depend on SQL fixture details while still testing the
        # real Risk Intelligence SQLite lifecycle and 5m settlement.
        import risk_intelligence_shadow as ri
        importlib.reload(ri)

        history = [
            {"pair":"QNT/USDT:USDT","side":"LONG","regime":"UP","mode":"STRICT","status":"CLOSED","net_pct":-0.30,"expected_edge_pct":0.08,"btc_15m_pct":-0.20,"oi_15m_pct":-0.60,"funding_rate_pct":0.025,"long_short_ratio":1.30,"opened_at":100.0},
            {"pair":"QNT/USDT:USDT","side":"LONG","regime":"UP","mode":"STRICT","status":"CLOSED","net_pct":-0.20,"expected_edge_pct":0.12,"btc_15m_pct":-0.15,"oi_15m_pct":-0.40,"funding_rate_pct":0.020,"long_short_ratio":1.25,"opened_at":200.0},
            {"pair":"QNT/USDT:USDT","side":"LONG","regime":"UP","mode":"STRICT","status":"CLOSED","net_pct":-0.10,"expected_edge_pct":0.18,"btc_15m_pct":-0.10,"oi_15m_pct":-0.30,"funding_rate_pct":0.018,"long_short_ratio":1.22,"opened_at":300.0},
            {"pair":"QNT/USDT:USDT","side":"LONG","regime":"UP","mode":"STRICT","status":"CLOSED","net_pct":-0.05,"expected_edge_pct":0.22,"btc_15m_pct":-0.05,"oi_15m_pct":-0.20,"funding_rate_pct":0.015,"long_short_ratio":1.20,"opened_at":400.0},
            {"pair":"QNT/USDT:USDT","side":"LONG","regime":"UP","mode":"STRICT","status":"CLOSED","net_pct":-0.15,"expected_edge_pct":0.25,"btc_15m_pct":-0.12,"oi_15m_pct":-0.50,"funding_rate_pct":0.022,"long_short_ratio":1.28,"opened_at":500.0},
        ]
        ri._analytics_rows = lambda where="", params=(): history
        ri._open_analytics_rows = lambda: []

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
        latest = report["latest"]
        assert 0 <= float(latest["confidence_score"]) <= 100, latest

        flags = set(latest.get("flags") or [])
        expected = {
            "PAIR_COOLDOWN","BTC_AGAINST","OI_PRICE_DIVERGENCE",
            "FUNDING_EXTREME","VOLATILITY_SHOCK"
        }
        missing_flags = sorted(expected - flags)
        assert not missing_flags, f"Expected guard flags missing: {missing_flags}; got={sorted(flags)}"

        print("RISK_INTELLIGENCE_SELFTEST_OK")
        print("analytics_schema=OK")
        print("closed=", report["overall"]["n"])
        print("confidence=", latest.get("confidence_score"))
        print("flags=", sorted(flags))


try:
    run()
except Exception as exc:
    print("RISK_INTELLIGENCE_SELFTEST_FAIL")
    print(f"{type(exc).__name__}: {exc}")
    traceback.print_exc(file=sys.stdout)
    sys.exit(1)

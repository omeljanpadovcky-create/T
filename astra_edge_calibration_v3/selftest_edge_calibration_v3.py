import os

os.environ["EDGE_CALIBRATION_V3_MIN_CLUSTERS"] = "30"
os.environ["EDGE_CALIBRATION_V3_MIN_BLOCK_SUPPORT"] = "5"
os.environ["EDGE_CALIBRATION_V3_EXCLUDE_NEUTRAL"] = "true"

import edge_calibration_v3 as v3


def row(i, edge, net, state="AGREE"):
    return {
        "id": i + 1,
        "pair": "BTC/USDT:USDT" if i % 2 == 0 else "ETH/USDT:USDT",
        "side": "LONG" if i % 3 else "SHORT",
        "cluster_key": f"p{i}|s{i}|{i*300}",
        "opened_at": i * 300.0,
        "edge_pct": float(edge),
        "net_pct": float(net),
        "xcheck_state": state,
        "tech_score": 4,
        "horizon_sec": 300,
        "status": "CLOSED",
    }


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


rows = [row(i, 0.05 + i * 0.005, 0.20 - (0.05 + i * 0.005) * 1.2) for i in range(40)]
m = v3._build_model(rows)
assert_true(m["state"] == "READY", "40 clustered points should be READY")
assert_true(m["cluster_n"] == 40, "cluster count mismatch")
assert_true((m["raw_edge_net_corr"] or 0) < -0.9, "anti-correlation diagnostic missing")
assert_true(len(m["blocks"]) == 1, "PAVA should pool fully anti-correlated points")
assert_true(m["blocks"][0]["support"] == 40, "pooled support mismatch")

rows2 = []
for i in range(40):
    edge = 0.04 + i * 0.004
    net = -0.03 + edge * 0.8
    rows2.append(row(i, edge, net))
m2 = v3._build_model(rows2)
assert_true(m2["state"] == "READY", "monotonic sample should be READY")
means = [b["calibrated_net_pct"] for b in m2["blocks"]]
assert_true(all(means[i] <= means[i+1] + 1e-12 for i in range(len(means)-1)), "isotonic means not monotone")

rows3 = [row(i, 0.08 + i * 0.001, 0.05, "AGREE") for i in range(35)]
rows3 += [row(100+i, 0.09 + i * 0.001, -0.50, "NEUTRAL") for i in range(10)]
m3 = v3._build_model(rows3)
assert_true(m3["cluster_n"] == 35, "NEUTRAL should be excluded from active fit")
assert_true(m3["neutral_excluded_n"] == 10, "neutral excluded counter mismatch")
assert_true(m3["neutral"]["avg_net_pct"] < 0, "neutral diagnostic should retain toxic sample")

m4 = v3._build_model([row(i, 0.08 + i * 0.001, 0.02) for i in range(12)])
assert_true(m4["state"] == "WARMING", "small sample must not become READY")

p = v3._predict(m2, 999.0)
assert_true(p is not None and p.get("extrapolated") is True, "high-edge extrapolation flag missing")
assert_true(p["calibrated_net_pct"] == m2["blocks"][-1]["calibrated_net_pct"], "extrapolation must stay flat")

print("[OK] EDGE Calibration V3 self-test passed")
print("[OK] anti-correlated EDGE is pooled instead of rewarded")
print("[OK] clustered support / neutral exclusion / warming rules verified")

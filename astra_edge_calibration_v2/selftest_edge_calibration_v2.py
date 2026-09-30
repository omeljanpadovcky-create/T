from dataclasses import dataclass
import importlib
import os


@dataclass
class Sig:
    direction: str = "LONG"
    structure: str = "UP"
    ema_fast: float = 101.0
    ema_slow: float = 100.0
    rsi: float = 60.0
    volume_ratio: float = 1.2


@dataclass
class Edge:
    passed: bool = True
    net_edge_pct: float = 0.10
    basis: str = "bootstrap_atr"


def candles(step=0.0005, n=80):
    p = 100.0
    out = []
    for _ in range(n):
        p *= (1.0 + step)
        out.append({"close": p})
    return out


def run():
    os.environ["EDGE_CALIBRATION_V2_ENABLED"] = "true"
    os.environ["EDGE_CALIBRATION_V2_MIN_EDGE_PCT"] = "0.08"
    os.environ["EDGE_CALIBRATION_V2_MAX_EDGE_PCT"] = "0.15"
    import edge_calibration_v2 as m
    importlib.reload(m)

    sig = Sig()

    low = m.apply(signal=sig, edge=Edge(net_edge_pct=0.079), candles=candles(), atr_pct=0.5, atr_median_pct=0.5)
    assert not low["passed"] and low["reason"] == "edge_calibration_v2_below_band", low

    good = m.apply(signal=sig, edge=Edge(net_edge_pct=0.098), candles=candles(), atr_pct=0.5, atr_median_pct=0.5)
    assert good["passed"], good

    high = m.apply(signal=sig, edge=Edge(net_edge_pct=0.151), candles=candles(), atr_pct=0.5, atr_median_pct=0.5)
    assert not high["passed"] and high["reason"] == "edge_calibration_v2_above_band", high

    hot = m.apply(signal=sig, edge=Edge(net_edge_pct=0.12), candles=candles(step=0.003), atr_pct=0.8, atr_median_pct=0.6)
    assert not hot["passed"] and "overextended" in hot["reason"], hot

    shrunk = Edge(net_edge_pct=0.12, basis="shrunk_bucket")
    shrunk_hot = m.apply(signal=sig, edge=shrunk, candles=candles(step=0.003), atr_pct=0.8, atr_median_pct=0.6)
    assert shrunk_hot["passed"], shrunk_hot

    print("EDGE_CALIBRATION_V2_SELFTEST_OK")
    print("low=", low["reason"])
    print("good=", good["reason"])
    print("high=", high["reason"])
    print("bootstrap_hot=", hot["reason"])
    print("shrunk_hot=", shrunk_hot["reason"])


if __name__ == "__main__":
    run()

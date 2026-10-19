"""Unit tests for the OTC paper engine; all data is synthetic and test-only."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from crypto_myshka import otc_signal_engine as engine


def candles(count=20, *, latest_age=0, trend=1.0):
    now = time.time() - latest_age
    out = []
    for i in range(count):
        close = 100 + i * trend
        out.append({
            "time": now - (count - 1 - i) * 1.0,
            "open": close - 0.1,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
        })
    return out


class EngineTests(unittest.TestCase):
    def test_valid_candles_are_sorted_and_accepted(self):
        rows = candles()
        got = engine.validate_candles(rows)
        self.assertEqual(len(got), 20)
        self.assertLess(got[0]["time"], got[-1]["time"])

    def test_rejects_stale_data(self):
        with self.assertRaises(engine.FeedError):
            engine.validate_candles(candles(latest_age=200))

    def test_rejects_too_few_candles(self):
        with self.assertRaises(engine.FeedError):
            engine.validate_candles(candles(count=19))

    def test_rejects_synthetic_source_label(self):
        signal = {
            "symbol": "TEST", "candle_time": time.time(), "direction": "UP",
            "entry_price": 100.0, "created_at": "2026-01-01T00:00:00+00:00",
        }
        with self.assertRaises(engine.FeedError):
            engine.record_signal(signal, "synthetic")

    def test_duplicate_recording_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(engine, "DB_PATH", Path(folder) / "test.db"):
            signal = {
                "symbol": "TEST", "candle_time": time.time(), "direction": "UP",
                "entry_price": 100.0, "created_at": "2026-01-01T00:00:00+00:00",
            }
            engine.record_signal(signal, "verified-test-adapter")
            engine.record_signal(signal, "verified-test-adapter")
            rows = engine.history(20)
            self.assertEqual(len(rows), 3)
            self.assertEqual({r["horizon_seconds"] for r in rows}, {15, 30, 60})

    def test_settlement_requires_same_fresh_source(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(engine, "DB_PATH", Path(folder) / "test.db"):
            signal = {
                "symbol": "TEST", "candle_time": time.time() - 2, "direction": "UP",
                "entry_price": 100.0, "created_at": "2026-01-01T00:00:00+00:00",
            }
            engine.record_signal(signal, "feed-a")
            # Make rows due without sleeping.
            with engine._connect() as conn:
                conn.execute("UPDATE otc_signals SET due_at=?", (time.time() - 1,))
            settled = engine.settle_due(lambda symbol: (101.0, "feed-b", time.time()))
            self.assertEqual(settled, 0)
            self.assertTrue(all(row["outcome"] is None for row in engine.history(10)))


if __name__ == "__main__":
    unittest.main(verbosity=2)

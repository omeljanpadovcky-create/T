"""Contract tests: no invented prices, no crypto/forex mixing, no auto-trade."""
import unittest
from datetime import datetime, timezone

from crypto_myshka.pair_reports import build, instrument


class PairReportsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 9, 20, 30, tzinfo=timezone.utc)

    def test_no_live_evidence_is_not_a_forecast(self):
        data = build({"observations": []}, self.now)
        self.assertEqual(data["status"], "waiting_for_readable_live_chart")
        self.assertEqual(data["reports"], [])
        self.assertFalse(data["automatic_trading"])

    def test_ambiguous_asset_is_skipped(self):
        snapshot = {"observations": [{
            "observed_at": "2026-10-09T20:29:00+00:00",
            "observation": {"asset": "AUD CNY or BTC maybe", "confidence": "high"},
        }]}
        self.assertEqual(build(snapshot, self.now)["reports"], [])

    def test_otc_pair_not_treated_as_crypto(self):
        row = {
            "observed_at": "2026-10-09T20:29:00+00:00",
            "channel_id": "nikolas",
            "channel_name": "НИКОЛАС | ТРЕЙДЕР",
            "url": "https://www.youtube.com/watch?v=12345678901",
            "observation": {
                "asset": "AUD/CNY OTC", "confidence": "medium",
                "action": "commentary", "visual_evidence": "Candles visible.",
                "chart": {
                    "trend": "downtrend", "volatility": "normal",
                    "volume": "unknown", "sentiment": "bearish",
                    "support_levels": ["1.84200", "made-up-level"],
                    "resistance_levels": ["1.84400"],
                    "price_action": "Visible lower highs",
                    "trend_reason": "Visible lower highs and red candles",
                },
            },
        }
        result = build({"observations": [row]}, self.now)
        self.assertEqual(len(result["reports"]), 1)
        card = result["reports"][0]
        self.assertEqual(card["pair"], "AUD/CNY OTC")
        self.assertIn("OTC", card["instrument_type"])
        self.assertEqual(card["support_levels"], ["1.84200"])
        self.assertEqual(card["resistance_levels"], ["1.84400"])
        self.assertEqual(card["jev"]["what_to_do"], "WAIT / OBSERVE")
        self.assertEqual(card["volume"], "unknown")
        self.assertFalse(card["independently_verified"])

    def test_stale_frames_do_not_generate_reports(self):
        row = {
            "observed_at": "2026-10-09T17:00:00+00:00",
            "observation": {"asset": "BTC/USDT", "chart": {"trend": "uptrend"}},
        }
        self.assertEqual(build({"observations": [row]}, self.now)["reports"], [])

    def test_forex_and_crypto_remain_separate(self):
        template = {"channel_id": "x", "observed_at": "2026-10-09T20:29:00Z"}
        records = [
            dict(template, observation={"asset": "AUD/CNY OTC"}),
            dict(template, observation={"asset": "BTC/USDT"}),
            dict(template, observation={"asset": "AUD/JPY"}),
        ]
        data = build({"observations": records}, self.now)
        self.assertEqual({x["pair"] for x in data["reports"]},
                         {"AUD/CNY OTC", "BTC/USDT", "AUD/JPY"})


if __name__ == "__main__":
    unittest.main()

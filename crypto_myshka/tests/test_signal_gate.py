"""Conservative JEV signal gate: false positives are blocked, never traded."""
import unittest
from copy import deepcopy
from datetime import datetime, timezone, timedelta

from crypto_myshka.signal_gate import evaluate
from crypto_myshka.pair_reports import build


class SignalGateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
        stamp = self.now.isoformat()
        self.verified = {
            "pair": "BTC/USDT",
            "instrument_type": "Криптовалюта",
            "observed_at": stamp,
            "trend": "uptrend",
            "sentiment": "bullish",
            "volume": "normal",
            "confidence": "medium",
            "jev": {"status": "model", "why": "Декілька ознак підтверджені"},
            "verification": {
                "price_feeds": [
                    {"provider": "exchange_a", "verified": True, "checked_at": stamp},
                    {"provider": "exchange_b", "verified": True, "checked_at": stamp},
                ],
                "price_consistent": True,
                "indicators": {"rsi": True, "ema": True, "structure": True},
                "conflicting_sources": False,
                "out_of_sample_results": 50,
                "expected_move_pct": 0.4,
                "round_trip_cost_pct": 0.12,
                "slippage_pct": 0.02,
            },
        }

    def test_missing_evidence_fails_closed(self):
        x = evaluate({"pair": "BTC/USDT"}, self.now)
        self.assertEqual(x["decision"], "NO_SIGNAL")
        self.assertGreater(len(x["reasons"]), 5)
        self.assertFalse(x["automatic_trading"])

    def test_youtube_channels_are_not_independent_price_feeds(self):
        report = deepcopy(self.verified)
        report["sources_count"] = 12
        report["verification"]["price_feeds"] = [
            {"provider": "youtube", "verified": True, "checked_at": self.now.isoformat()},
            {"provider": "stream", "verified": True, "checked_at": self.now.isoformat()},
        ]
        x = evaluate(report, self.now)
        self.assertEqual(x["decision"], "NO_SIGNAL")
        self.assertEqual(x["verified_price_feeds"], 0)

    def test_duplicate_provider_does_not_count_twice(self):
        report = deepcopy(self.verified)
        report["verification"]["price_feeds"][1]["provider"] = "exchange_a"
        self.assertEqual(evaluate(report, self.now)["decision"], "NO_SIGNAL")

    def test_otc_always_blocked(self):
        report = deepcopy(self.verified)
        report["pair"] = "CHF/JPY OTC"
        report["instrument_type"] = "OTC (брокерські котирування)"
        self.assertEqual(evaluate(report, self.now)["decision"], "NO_SIGNAL")

    def test_stale_frames_and_stale_feed_fail(self):
        report = deepcopy(self.verified)
        report["observed_at"] = (self.now - timedelta(minutes=3)).isoformat()
        self.assertEqual(evaluate(report, self.now)["decision"], "NO_SIGNAL")
        report["observed_at"] = self.now.isoformat()
        report["verification"]["price_feeds"][0]["checked_at"] = (self.now - timedelta(minutes=3)).isoformat()
        self.assertEqual(evaluate(report, self.now)["decision"], "NO_SIGNAL")

    def test_missing_indicator_and_source_conflict_fail(self):
        report = deepcopy(self.verified)
        report["verification"]["indicators"]["ema"] = False
        self.assertEqual(evaluate(report, self.now)["decision"], "NO_SIGNAL")
        report["verification"]["indicators"]["ema"] = True
        report["verification"]["conflicting_sources"] = True
        self.assertEqual(evaluate(report, self.now)["decision"], "NO_SIGNAL")

    def test_jev_not_configured_or_low_confidence_fails(self):
        report = deepcopy(self.verified)
        report["jev"] = {"status": "not_configured"}
        self.assertEqual(evaluate(report, self.now)["decision"], "NO_SIGNAL")
        report["jev"] = {"status": "model"}
        report["confidence"] = "low"
        self.assertEqual(evaluate(report, self.now)["decision"], "NO_SIGNAL")

    def test_weak_edge_or_insufficient_validation_fails(self):
        report = deepcopy(self.verified)
        report["verification"]["expected_move_pct"] = 0.16
        self.assertEqual(evaluate(report, self.now)["decision"], "NO_SIGNAL")
        report["verification"]["expected_move_pct"] = 0.4
        report["verification"]["out_of_sample_results"] = 10
        self.assertEqual(evaluate(report, self.now)["decision"], "NO_SIGNAL")

    def test_nan_or_boolean_edge_cannot_bypass_gate(self):
        for invalid in (float("nan"), float("inf"), True, None, "bad"):
            report = deepcopy(self.verified)
            report["verification"]["expected_move_pct"] = invalid
            self.assertEqual(evaluate(report, self.now)["decision"], "NO_SIGNAL")

    def test_complete_evidence_only_allows_human_review(self):
        x = evaluate(self.verified, self.now)
        self.assertEqual(x["decision"], "REVIEW_ONLY")
        self.assertTrue(x["eligible_for_human_review"])
        self.assertFalse(x["automatic_trading"])

    def test_live_screenshot_card_is_no_signal_even_with_model(self):
        row = {
            "observed_at": self.now.isoformat(),
            "channel_id": "nikolas",
            "channel_name": "YouTube LIVE",
            "observation": {
                "asset": "BTC/USDT", "confidence": "medium",
                "chart": {"trend": "uptrend", "sentiment": "bullish", "volume": "normal"},
                "jev": {"status": "model", "why": "Видно висхідні свічки"},
            },
        }
        result = build({"observations": [row]}, self.now)
        self.assertEqual(result["reports"][0]["signal_decision"], "NO_SIGNAL")
        self.assertFalse(result["reports"][0]["signal_gate"]["automatic_trading"])


if __name__ == "__main__":
    unittest.main()

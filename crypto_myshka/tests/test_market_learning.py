"""Offline invariants for public Bybit market learning. Never opens an order."""
import json
import tempfile
import unittest
from pathlib import Path
from crypto_myshka import market_learning as ml


class MarketLearningTests(unittest.TestCase):
    def test_signal_cannot_see_next_bar(self):
        data = [[ml.START_MS + i * ml.STEP, 100 + i, 102 + i,
                 99 + i, 101 + i, 2.0] for i in range(80)]
        original = ml.predictions(data)[-2]
        data[-1][4] = 100000
        self.assertEqual(original, ml.predictions(data)[-2])

    def test_prospective_outcome_only_after_target_close(self):
        bars = [[ml.START_MS + i * ml.STEP, 100 + i * .3,
                 102 + i * .3, 99 + i * .3, 101 + i * .3, 50.0]
                for i in range(350)]
        def fake(symbol, start, end):
            return [bar for bar in bars if start <= bar[0] <= end]
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "learning.json"
            first_now = ml.START_MS + 300 * ml.STEP + 4000
            first = ml.run(path=target, now=first_now, fetcher=fake)
            self.assertEqual(len(first["forward_predictions"]), 3)
            self.assertTrue(all(p["evaluated_at"] is None
                                for p in first["forward_predictions"]))
            again = ml.run(path=target, now=first_now, fetcher=fake)
            self.assertEqual(len(again["forward_predictions"]), 3)
            later = ml.run(path=target, now=first_now + ml.STEP, fetcher=fake)
            self.assertEqual(len(later["forward_predictions"]), 6)
            settled = [p for p in later["forward_predictions"] if p["evaluated_at"]]
            self.assertEqual(len(settled), 3)
            self.assertTrue(all(p["outcome"] is not None for p in settled))
            self.assertFalse(later["orders_enabled"])
            self.assertFalse(later["ai_weights_trained"])

    def test_calibration_keeps_chronological_holdout(self):
        bars = [[ml.START_MS + i * ml.STEP, 100 + i * .3,
                 102 + i * .3, 99 + i * .3, 101 + i * .3, 50]
                for i in range(350)]
        a = ml.summarize(bars)
        self.assertIn("train", a)
        self.assertIn("holdout", a)
        self.assertEqual(a["candles"], 350)
        self.assertGreater(a["holdout"]["always_up_baseline"]["observations"], 0)

    def test_cost_proxy_does_not_fake_profit(self):
        next_bar = [ml.START_MS, 100, 101, 99, 100.05, 1]
        result = ml.score_direction("UP", next_bar)
        self.assertTrue(result["direction_hit"])
        self.assertLess(result["paper_net_pct"], 0)


if __name__ == "__main__":
    unittest.main()

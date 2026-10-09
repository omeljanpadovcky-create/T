"""JEV pair output must remain bounded, structured and non-executing."""
import json
import unittest
from unittest.mock import patch
from crypto_myshka import pair_jev


class PairJevTests(unittest.TestCase):
    def test_missing_asset_never_calls_provider(self):
        with patch.object(pair_jev.requests, "post") as post:
            x = pair_jev.analyze({"asset": None})
        self.assertEqual(x["status"], "missing_instrument")
        post.assert_not_called()

    def test_no_chart_information_prevents_hallucinated_report(self):
        x = pair_jev.analyze({"asset": "AUD/CNY OTC", "chart": {"trend": "unknown"}})
        self.assertEqual(x["status"], "insufficient_visible_evidence")

    def test_judgement_is_wait_only_for_unverified_frame(self):
        x = pair_jev.parse_response(json.dumps({
            "why": "На кадрі кілька нижчих максимумів, але часовий ряд неповний.",
            "key_levels": "Потрібна незалежна перевірка.",
            "watch_next": "Подивитися наступні свічки.",
            "what_to_do": "BUY NOW",
            "confidence": "high"
        }))
        self.assertEqual(x["what_to_do"], "WAIT / OBSERVE")
        self.assertEqual(x["confidence"], "low")
        self.assertEqual(x["engine"], "separate_ai_explainer")


if __name__ == "__main__":
    unittest.main()

"""Content collection is context only: it must never imply live monitoring."""
import unittest

from crypto_myshka.youtube_analysts import classify
from crypto_myshka.jev_analyzer import related_youtube_context


class YouTubeContentTests(unittest.TestCase):
    def test_extracts_otc_pair_and_indicators(self):
        row = classify(
            "AUD/CNY OTC trading RSI M1 strategy",
            "",
            "Ведучий пояснює EMA і підтримку графіка.",
        )
        self.assertIn("AUD/CNY OTC", row["mentioned_instruments"])
        self.assertIn("M1", row["mentioned_timeframes"])
        self.assertIn("RSI", row["mentioned_indicators"])
        self.assertTrue(row["otc_flag"])
        self.assertEqual(row["direction_claim"], "НЕВІДОМО")

    def test_jev_uses_only_relevant_non_demo_video_text(self):
        row = {
            "channels": [{
                "name": "Trader",
                "confirmed": True,
                "videos": [
                    {"id":"abc", "title":"BTC trading RSI",
                     "url":"https://www.youtube.com/watch?v=abcdefghijk",
                     "analysis":{"mentioned_instruments":["BTC/USDT"],
                                 "mentioned_indicators":["RSI"],
                                 "content_excerpt":"Трейдер говорить про RSI"}},
                    {"id":"def", "title":"BTC VIP example",
                     "sample_only": True, "url":"https://www.youtube.com/watch?v=abcdefghijk"},
                ],
            }]
        }
        context=related_youtube_context({"assets":["BTC"],"title":"Bitcoin outlook"},row)
        self.assertEqual(len(context),1)
        self.assertFalse(context[0]["verified_market_data"])
        self.assertEqual(context[0]["source_type"],"published_youtube_text_only")

    def test_no_topic_match_means_no_video_context(self):
        row={"channels":[{"confirmed":True,"videos":[{"title":"BTC trades"}]}]}
        self.assertEqual(related_youtube_context({"assets":["SOL"]},row), [])


if __name__=="__main__":
    unittest.main()

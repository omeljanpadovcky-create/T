from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from crypto_myshka import jev_analyzer, news_engine, telegram_archive


class CryptoMyshkaInvariantTests(unittest.TestCase):
    def test_preserve_jev_analysis_across_news_refresh(self):
        old = [{
            "id": "evt1",
            "title": "Same title",
            "jev_ai": {"short_conclusion": "ready"},
            "analysis_engine": "free/test",
            "analysis_level": "llm",
        }]
        fresh = [{"id": "evt1", "title": "Same title"}]
        merged = news_engine.preserve_jev_analysis(fresh, old)
        self.assertEqual(merged[0]["jev_ai"]["short_conclusion"], "ready")
        self.assertEqual(merged[0]["analysis_level"], "llm")

    def test_archive_merge_never_drops_existing_posts(self):
        existing = {
            "https://t.me/it_statti/1": {
                "channel": "it_statti", "post_id": 1,
                "url": "https://t.me/it_statti/1"
            }
        }
        telegram_archive.merge_rows([
            {
                "channel": "it_statti", "post_id": 2,
                "url": "https://t.me/it_statti/2"
            }
        ], existing)
        self.assertEqual(set(existing), {
            "https://t.me/it_statti/1",
            "https://t.me/it_statti/2",
        })

    def test_malformed_json_never_becomes_raw_ui_text(self):
        broken = '{"what_happened":"ok","why_it_matters":"cut'
        out = jev_analyzer.extract_json(broken)
        self.assertTrue(out.get("_format_fallback"))
        for key in ("short_conclusion", "what_happened", "why_it_matters"):
            value = str(out.get(key, "")).strip()
            self.assertFalse(value.startswith("{"))

    def test_keyword_matching_does_not_match_substrings(self):
        self.assertFalse(news_engine.has_keyword("OpenAI researchers discuss safety", "sec"))
        self.assertTrue(news_engine.has_keyword("SEC approves a crypto ETF", "sec"))

    def test_off_topic_items_are_not_crypto_relevant(self):
        assets, topics, *_ = news_engine.detect("The Pope comments on AI art")
        self.assertFalse(news_engine.crypto_relevant("The Pope comments on AI art", assets, topics))
        assets, topics, *_ = news_engine.detect("SEC approves a Bitcoin ETF")
        self.assertTrue(news_engine.crypto_relevant("SEC approves a Bitcoin ETF", assets, topics))

    def test_fallback_analysis_is_structured_and_retryable(self):
        event={
            "title":"Test crypto event",
            "summary":"Bitcoin market event",
            "assets":["BTC"],
            "jev_take":"Needs confirmation",
            "watch_for":"Volume and source confirmation",
            "confidence_label":"Поки одне джерело",
        }
        out=jev_analyzer.fallback_analysis(event,"temporary failure")
        self.assertTrue(out.get("_cross_source_fallback"))
        self.assertTrue(out.get("_retry_llm"))
        self.assertIn("short_conclusion",out)
        self.assertFalse(str(out["short_conclusion"]).startswith("{"))

    def test_current_json_has_no_duplicate_primary_ids(self):
        root = Path(__file__).resolve().parents[1] / "data"
        for name, key in (("feed.json", "items"), ("news.json", "items")):
            data = json.loads((root / name).read_text(encoding="utf-8"))
            ids = [x.get("id") for x in data.get(key, []) if x.get("id")]
            self.assertEqual(len(ids), len(set(ids)), f"duplicate ids in {name}")

        archive = json.loads((root / "telegram_archive.json").read_text(encoding="utf-8"))
        keys = [
            (x.get("channel"), x.get("post_id"))
            for x in archive.get("posts", [])
            if x.get("channel") and x.get("post_id") is not None
        ]
        self.assertEqual(len(keys), len(set(keys)), "duplicate Telegram posts")


if __name__ == "__main__":
    unittest.main()

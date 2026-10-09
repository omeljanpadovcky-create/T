import os
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from crypto_myshka import youtube_archive as arc
from crypto_myshka import video_jev


class VideoArchiveTests(unittest.TestCase):
    def test_seed_ignores_example_only_and_keeps_real_video(self):
        existing = {}
        seed = {"channels":[{"id":"nikolas","videos":[
            {"id":"g5sXQlvCPVo","title":"Promo fake", "sample_only":True}
        ]}, {"id":"backstage","videos":[
            {"id":"Z4HMrRpKcV4","title":"BTC market commentary"}
        ]}]}
        self.assertEqual(arc.seed_older_records(existing,seed),1)
        self.assertEqual(set(existing),{"Z4HMrRpKcV4"})
        self.assertFalse(existing["Z4HMrRpKcV4"]["video_reviewed"])

    def test_backfill_preserves_old_video_and_is_idempotent(self):
        calls = []
        def fake_fetch(channel,section,start,count):
            calls.append((channel["id"],section,start,count))
            if channel["id"]=="nikolas" and section=="videos":
                return [{"id":"g5sXQlvCPVo","title":"Trading strategies"}] if start==1 else [
                    {"id":"L31S4DgpEIo","title":"An older trade lesson"}
                ]
            return []
        sample={"videos":[],"progress":{}}
        with patch.object(arc,"CHANNELS", [arc.CHANNELS[0]]):
            first=arc.build(sample,{},fetcher=fake_fetch,include_enrichment=False)
            second=arc.build(first,{},fetcher=fake_fetch,include_enrichment=False)
        self.assertEqual(first["video_count"],2)
        self.assertEqual(second["video_count"],2)
        self.assertFalse(any(x["video_reviewed"] for x in second["videos"]))
        self.assertEqual(len({x["id"] for x in second["videos"]}),2)
        self.assertIn(("nikolas","videos",1,arc.RECENT_COUNT),calls)

    def test_partial_youtube_outage_keeps_archive_records_and_progress(self):
        entry=arc.make_entry("Z4HMrRpKcV4",arc.CHANNELS[1],"videos","OLD")
        previous={"videos":[entry],"progress":{"backstage:videos":{"next_start":250}}}
        def error(*_args):raise RuntimeError("YouTube blocked")
        with patch.object(arc,"CHANNELS",[arc.CHANNELS[1]]):
            out=arc.build(previous,{},fetcher=error,include_enrichment=False)
        self.assertEqual(out["video_count"],1)
        self.assertEqual(out["progress"]["backstage:videos"]["next_start"],250)
        self.assertGreater(len(out["errors"]),0)

    def test_full_available_caption_text_extracts_instruments_without_claiming_verified_orders(self):
        data={"status":"available","full_text":"У ролику AUD/CNY OTC на M1 з RSI і EMA. " * 4}
        info=arc.facts_from_text("Trader lesson","",data)
        self.assertIn("AUD/CNY OTC",info["mentioned_instruments"])
        self.assertIn("M1",info["mentioned_timeframes"])
        self.assertIn("RSI",info["mentioned_indicators"])
        self.assertFalse(info["executed_trades_verified"])
        self.assertFalse(info["verified_chart_patterns"])

    def test_video_jev_requires_subtitles_and_refuses_fabricated_signals(self):
        sample={"title":"Trade","description":"","subtitles":"no","instruments":[],"indicators":[]}
        with patch.object(video_jev.requests,"post") as post:
            status=video_jev.summarize(**sample)
        self.assertEqual(status["status"],"insufficient_captions")
        post.assert_not_called()

    def test_video_jev_never_uses_a_paid_model_by_default(self):
        payload={"title":"Trading video","description":"","subtitles":"A"*110,
                 "instruments":[],"indicators":[]}
        with patch.object(video_jev,"API_KEY","test"),patch.object(video_jev,"MODEL","not-free"):
            answer=video_jev.summarize(**payload)
        self.assertEqual(answer["status"],"not_configured")

    def test_has_no_unverified_fifth_channel(self):
        self.assertTrue(all(ch.get("confirmed") for ch in arc.CHANNELS))
        self.assertNotIn("nikolai",[ch["id"] for ch in arc.CHANNELS])


if __name__=="__main__":
    unittest.main()

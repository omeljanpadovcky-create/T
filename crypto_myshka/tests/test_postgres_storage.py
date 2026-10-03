from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone

from crypto_myshka import storage


@unittest.skipUnless(os.getenv("DATABASE_URL"), "DATABASE_URL not configured")
class PostgresStorageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(storage.ensure_schema())

    def test_schema_and_all_persistence_paths(self):
        now=datetime.now(timezone.utc).isoformat()

        feed={
            "generated_at":now,
            "market":{"symbols":["BTC"],"prices":{"bitcoin":{"usd":1}}},
            "items":[{
                "id":"test-material-1",
                "source":"test",
                "mode":"portfolio",
                "risk":50,
                "knowledge":False,
                "title":"Storage integration material",
                "summary":"postgres integration test",
                "url":"https://example.invalid/material-1",
                "published_at":now,
            }],
        }
        self.assertEqual(storage.sync_feed(feed),1)

        news={
            "items":[{
                "id":"test-news-1",
                "title":"Storage integration news",
                "summary":"postgres integration test",
                "url":"https://example.invalid/news-1",
                "published_at":now,
                "impact":2,
                "source_count":2,
                "analysis_engine":"test",
                "analysis_level":"llm",
                "jev_ai":{
                    "what_happened":"test",
                    "why_it_matters":"test",
                    "market_effect":"neutral",
                    "bull_case":"test",
                    "bear_case":"test",
                    "watch_next":"test",
                    "confidence":"середня",
                    "short_conclusion":"test",
                },
            }],
        }
        self.assertEqual(storage.sync_news(news),1)

        archive={
            "posts":[{
                "id":"test-post-1",
                "channel":"test_channel",
                "post_id":999999001,
                "text":"postgres integration telegram post",
                "url":"https://t.me/test_channel/999999001",
                "published_at":now,
            }],
        }
        self.assertEqual(storage.sync_archive(archive),1)

        state={"initialized":True,"seen":["test-news-1"],"telegram_ready":True}
        self.assertTrue(storage.save_notification_state(state))
        self.assertEqual(storage.load_notification_state({}),state)

        self.assertEqual(storage.mark_notification_delivered(["test-news-1"]),1)
        self.assertIn("test-news-1",storage.delivered_notification_ids(["test-news-1"]))

        import psycopg
        with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
            with conn.cursor() as cur:
                checks=[
                    ("SELECT count(*) FROM materials WHERE id='test-material-1'",1),
                    ("SELECT count(*) FROM news_events WHERE id='test-news-1'",1),
                    ("SELECT count(*) FROM jev_analyses WHERE event_id='test-news-1'",1),
                    ("SELECT count(*) FROM telegram_posts WHERE channel='test_channel' AND post_id=999999001",1),
                    ("SELECT count(*) FROM market_snapshots",1),
                    ("SELECT count(*) FROM notification_deliveries WHERE item_id='test-news-1'",1),
                ]
                for sql,minimum in checks:
                    cur.execute(sql)
                    self.assertGreaterEqual(cur.fetchone()[0],minimum)


if __name__=="__main__":
    unittest.main()

"""Ground JEV news analysis in real Gemini video notes only."""
import unittest
from unittest.mock import patch
from crypto_myshka import jev_analyzer as jev


class VideoContextTests(unittest.TestCase):
    def test_verified_video_analysis_evidence_is_not_verified_trade(self):
        archive = {"videos": [
            {
                "id": "abcdefghijk", "channel_name": "Trader ABC",
                "title": "ETH/USDT trading lesson",
                "url": "https://www.youtube.com/watch?v=abcdefghijk",
                "upload_date": "20261009",
                "analysis": {"mentioned_instruments": []},
                "gemini": {
                    "status": "gemini_video_summary",
                    "model": "gemini-2.5-flash",
                    "pairs": ["ETH/USDT"], "indicators": ["RSI"],
                    "summary": "Trader described RSI overbought zones",
                    "strategy": "Looked at the chart and considered RSI",
                    "risk": "Short expiry is not sufficient evidence",
                    "moments": [{"timestamp": "00:32", "observation": "RSI indicator shown"}],
                },
            }, {
                "id": "lkjihgfedcb", "channel_name": "Old",
                "title": "ETH/USDT clickbait",
                "analysis": {"mentioned_instruments": ["ETH/USDT"]},
                "gemini": {"status": "unavailable"},
            }
        ]}
        with patch.object(jev, "load", return_value=archive):
            notes = jev.relevant_archive_video_notes({"assets": ["ETH"]})
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["analysis_coverage"], "video_frames_and_audio")
        self.assertFalse(notes[0]["verified_market_quotes"])
        self.assertFalse(notes[0]["trades_verified"])
        self.assertIn("ETH/USDT", notes[0]["mentioned_instruments"])
        self.assertEqual(notes[0]["observed_video_moments"][0]["timestamp"], "00:32")

    def test_no_title_only_fake_analysis(self):
        with patch.object(jev, "load", return_value={"videos": [
            {"title": "BTC 100 percent", "analysis": {
                "mentioned_instruments": ["BTC/USDT"]},
             "gemini": {"status": "not_configured"}, "jev": {"status": "not_analyzed"}}
        ]}):
            notes = jev.relevant_archive_video_notes({"assets": ["BTC"]})
        self.assertEqual(notes, [])

    def test_supports_subtitle_model_when_gemini_unavailable(self):
        archive = {"videos": [{
            "channel_name": "Trader", "analysis": {"mentioned_instruments": ["BTC/USDT"]},
            "gemini": {"status": "unavailable"},
            "jev": {"status": "model_summary", "summary": "RSI mentioned in the transcript",
                    "strategy": "Explain RSI", "risk": "Unverified claims"}
        }]}
        with patch.object(jev, "load", return_value=archive):
            notes = jev.relevant_archive_video_notes({"assets": ["BTC"]})
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["analysis_coverage"], "subtitle_text_only")

    def test_asset_symbol_boundaries(self):
        with patch.object(jev, "load", return_value={"videos": [{
            "analysis": {"mentioned_instruments": ["BETH/USDT"]},
            "gemini": {"status": "gemini_video_summary", "summary": "Test"}
        }]}):
            self.assertFalse(jev.relevant_archive_video_notes({"assets": ["ETH"]}))


if __name__ == "__main__":
    unittest.main()

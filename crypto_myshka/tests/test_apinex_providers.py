"""Mocked APInex contract: secrets are server-only and optional paid calls are opt-in."""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))


class APInexProviderTests(unittest.TestCase):
    def test_key_alone_does_not_enable_scheduled_paid_vision(self):
        with patch.dict(os.environ, {
            "APINEX_API_KEY": "private-example", "LIVE_APINEX_ENABLED": "false",
            "OPENAI_API_KEY": "", "MYSHKA_OLLAMA_URL": "",
        }):
            import live_monitor
            importlib.reload(live_monitor)
            self.assertFalse(live_monitor.USE_APINEX)
            self.assertFalse(live_monitor.AI_AVAILABLE)

    def test_enabled_apinex_vision_sends_image_not_secret_to_response(self):
        with patch.dict(os.environ, {
            "APINEX_API_KEY": "private-example", "LIVE_APINEX_ENABLED": "true",
            "OPENAI_API_KEY": "", "MYSHKA_OLLAMA_URL": "",
            "LIVE_APINEX_VISION_MODEL": "gemini-3.8-flash",
        }):
            import live_monitor
            importlib.reload(live_monitor)
            with tempfile.TemporaryDirectory() as folder:
                img = Path(folder) / "screenshot.jpg"
                img.write_bytes(b"fake-jpeg-for-mocked-test")
                fake = Mock()
                fake.status_code = 200
                fake.json.return_value = {"choices": [{
                    "message": {"content": json.dumps({
                        "action": "commentary", "asset": "CHF/JPY OTC",
                        "confidence": "low", "visual_evidence": "Visible M1 candles",
                        "chart": {"trend": "downtrend", "sentiment": "bearish",
                                  "support_levels": [], "resistance_levels": [],
                                  "volume": "unknown"},
                    })}
                }]}
                fake.raise_for_status.return_value = None
                with patch.object(live_monitor.requests, "post", return_value=fake) as post:
                    observed = live_monitor.vision(img, "")
                args, kwargs = post.call_args
                self.assertEqual(args[0], "https://api.apinex.bond/v1/chat/completions")
                self.assertEqual(kwargs["headers"]["Authorization"], "Bearer private-example")
                self.assertEqual(kwargs["json"]["model"], "gemini-3.8-flash")
                text_parts = kwargs["json"]["messages"][1]["content"]
                self.assertTrue(text_parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
                self.assertEqual(observed["asset"], "CHF/JPY OTC")
                self.assertEqual(observed["chart"]["trend"], "downtrend")
                self.assertNotIn("private-example", json.dumps(observed))

    def test_jev_explanation_uses_free_apinex_text_model_with_rate_guard(self):
        with patch.dict(os.environ, {
            "APINEX_API_KEY": "private-example", "LIVE_APINEX_ENABLED": "true",
            "OPENAI_API_KEY": "", "MYSHKA_OLLAMA_URL": "",
            "JEV_APINEX_TEXT_MODEL": "free/deepseek-v4.1-flash",
        }):
            import pair_jev
            importlib.reload(pair_jev)
            data = {"asset": "AUD/CNY OTC",
                    "chart": {"trend": "downtrend", "trend_reason": "Нижчі максимуми"},
                    "visual_evidence": "Свічки на кадрі"}
            fake = Mock()
            fake.raise_for_status.return_value = None
            fake.json.return_value = {"choices": [{"message": {
                "content": json.dumps({
                    "why": "Ознаки зниження на кадрі",
                    "key_levels": "Рівні не підтверджено",
                    "watch_next": "Потрібні незалежні котирування",
                    "what_to_do": "BUY NOW",
                    "confidence": "medium",
                })
            }}]}
            with patch.object(pair_jev.requests, "post", return_value=fake) as post:
                result = pair_jev.analyze(data)
            self.assertEqual(result["provider"], "apinex")
            self.assertEqual(result["what_to_do"], "WAIT / OBSERVE")
            self.assertEqual(result["engine"], "separate_ai_explainer")
            args, kwargs = post.call_args
            self.assertEqual(args[0], "https://api.apinex.bond/v1/chat/completions")
            self.assertEqual(kwargs["json"]["model"], "free/deepseek-v4.1-flash")


if __name__ == "__main__":
    unittest.main()

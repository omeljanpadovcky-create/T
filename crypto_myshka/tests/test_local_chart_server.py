"""Offline tests for local-only vision endpoint. Never contacts Ollama."""
import base64
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from crypto_myshka import local_chart_server as chart


class LocalChartServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), chart.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, data):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        conn.request("POST", "/api/chart-analysis", body=json.dumps(data),
                     headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        status = response.status
        payload = json.loads(response.read())
        conn.close()
        return status, payload

    def test_png_is_sent_to_local_vision_model(self):
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nexample").decode("ascii")
        with patch.object(chart, "api_post", return_value={"message": {"content": "ВГОРУ"}}) as mock:
            status, data = self.request({"image": png})
        self.assertEqual(status, 200)
        self.assertEqual("ВГОРУ", data["analysis"])
        self.assertEqual(data["source"], "local_ollama")
        self.assertEqual(mock.call_args.args[0], "/api/chat")
        self.assertEqual(mock.call_args.args[1]["messages"][1]["images"], [png])

    def test_ambiguous_model_output_becomes_unclear(self):
        png = base64.b64encode(bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"example").decode("ascii")
        with patch.object(chart, "api_post", return_value={"message": {"content": "Купуйте негайно!"}}):
            status, data = self.request({"image": png})
        self.assertEqual(status, 200)
        self.assertEqual(data["direction"], "НЕВИЗНАЧЕНО")

    def test_demo_buy_one_minute_requires_readable_chart_and_timeframe(self):
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nexample").decode("ascii")
        model_answer = {
            "direction": "ВГОРУ", "readable": True,
            "chart_timeframe": "unknown", "test_expiry_seconds": 60,
            "evidence": "Видно вищі локальні мінімуми на останніх свічках."
        }
        with patch.object(chart, "api_post", return_value={
            "message": {"content": json.dumps(model_answer, ensure_ascii=False)}
        }) as mocked:
            status, result = self.request({"image": png, "chart_timeframe": "1m"})
        self.assertEqual(status, 200)
        self.assertEqual(result["action"], "BUY")
        self.assertEqual(result["test_expiry_seconds"], 60)
        self.assertEqual(result["chart_timeframe"], "1m")
        self.assertEqual(result["timeframe_source"], "user")
        self.assertFalse(result["signal_validated"])
        self.assertFalse(result["expiry_validated"])
        self.assertEqual(mocked.call_args.args[1]["format"], "json")
        self.assertIn("1m", mocked.call_args.args[1]["messages"][1]["content"])

    def test_demo_sell_five_minutes(self):
        decision = chart.parse_jev_result(json.dumps({
            "direction": "ВНИЗ", "readable": True,
            "chart_timeframe": "5m", "test_expiry_seconds": 300,
            "evidence": "Свічки показують нижчі максимуми й мінімуми."
        }, ensure_ascii=False))
        self.assertEqual(decision["action"], "SELL")
        self.assertEqual(decision["test_expiry_seconds"], 300)
        self.assertEqual(decision["timeframe_source"], "model")

    def test_no_expiry_when_timeframe_is_missing(self):
        decision = chart.parse_jev_result(json.dumps({
            "direction": "ВГОРУ", "readable": True,
            "chart_timeframe": "unknown", "test_expiry_seconds": 30,
            "evidence": "Видно підвищення кількох останніх свічок."
        }, ensure_ascii=False))
        self.assertEqual(decision["direction"], "ВГОРУ")
        self.assertEqual(decision["action"], "SKIP")
        self.assertIsNone(decision["test_expiry_seconds"])

    def test_expiry_shorter_than_candle_timeframe_is_rejected(self):
        decision = chart.parse_jev_result(json.dumps({
            "direction": "ВГОРУ", "readable": True,
            "chart_timeframe": "5m", "test_expiry_seconds": 30,
            "evidence": "Видно послідовність вищих мінімумів."
        }, ensure_ascii=False))
        self.assertEqual(decision["action"], "SKIP")

    def test_unreadable_or_invalid_model_output_cannot_create_signal(self):
        for raw in (
            '{"direction":"ВНИЗ","readable":false,"chart_timeframe":"1m","test_expiry_seconds":60}',
            '{"direction":"ВГОРУ","readable":true,"chart_timeframe":"1m","test_expiry_seconds":99}',
            '{"direction":"BUY","readable":true,"chart_timeframe":"1m","test_expiry_seconds":60}',
            'Buy now, guaranteed win!',
            'ВГОРУ',
        ):
            with self.subTest(raw=raw):
                result = chart.parse_jev_result(raw)
                self.assertEqual(result["action"], "SKIP")
                self.assertIsNone(result["test_expiry_seconds"])

    def test_invalid_timeframe_is_rejected(self):
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nexample").decode("ascii")
        status, result = self.request({"image": png, "chart_timeframe": "60m"})
        self.assertEqual(status, 400)
        self.assertIn("таймфрейм", result["error"])

    def test_reject_foreign_origin(self):
        png = base64.b64encode(bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"example").decode("ascii")
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        conn.request("POST", "/api/chart-analysis", body=json.dumps({"image": png}),
                     headers={"Content-Type": "application/json", "Origin": "https://evil.example"})
        response = conn.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        conn.close()

    def test_hidden_repo_file_not_served(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        conn.request("GET", "/crypto_myshka/local_chart_server.py")
        response = conn.getresponse()
        self.assertEqual(response.status, 404)
        response.read()
        conn.close()

    def test_local_app_is_served_and_root_redirects(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        conn.request("GET", "/")
        response = conn.getresponse()
        self.assertEqual(response.status, 302)
        self.assertEqual(response.getheader("Location"), "/myshka-app.html#analysis")
        response.read()
        conn.request("GET", "/myshka-app.html")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertIn(b"Crypto Myshka", response.read())
        conn.close()

    def test_health_reports_model_readiness(self):
        from io import BytesIO
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, *_): return b'{"models":[{"name":"qwen2.5vl:3b"}]}'
        with patch.object(chart.urllib.request, "urlopen", return_value=FakeResponse()):
            conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
            conn.request("GET", "/api/chart-health")
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            result = json.loads(response.read())
            self.assertTrue(result["ready"])
            self.assertTrue(result["installed"])
            conn.close()

    def test_direction_down_only(self):
        png = base64.b64encode(bytes([137, 80, 78, 71, 13, 10, 26, 10]) + b"example").decode("ascii")
        with patch.object(chart, "api_post", return_value={"message": {"content": "ВНИЗ"}}):
            status, result = self.request({"image": png})
        self.assertEqual(status, 200)
        self.assertEqual(result["direction"], "ВНИЗ")

    def test_reject_nonimage(self):
        status, data = self.request({"image": base64.b64encode(b"not a chart").decode("ascii")})
        self.assertEqual(status, 400)
        self.assertIn("JPG", data["error"])

    def test_missing_model_is_not_fake_analysis(self):
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nexample").decode("ascii")
        import urllib.error
        with patch.object(chart, "api_post", side_effect=urllib.error.HTTPError("local", 404, "not found", {}, None)):
            status, data = self.request({"image": png})
        self.assertEqual(status, 503)
        self.assertIn("ollama pull", data["error"])


if __name__ == "__main__":
    unittest.main()

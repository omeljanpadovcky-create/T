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
        with patch.object(chart, "api_post", return_value={"message": {"content": "Ціна зростає, але даних мало."}}) as mock:
            status, data = self.request({"image": png})
        self.assertEqual(status, 200)
        self.assertIn("Ціна зростає", data["analysis"])
        self.assertEqual(data["source"], "local_ollama")
        self.assertEqual(mock.call_args.args[0], "/api/chat")
        self.assertEqual(mock.call_args.args[1]["messages"][1]["images"], [png])

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

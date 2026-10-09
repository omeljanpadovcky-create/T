#!/usr/bin/env python3
"""Local-only Fast Analysis server for Crypto Myshka.

Run from the repository: python crypto_myshka/local_chart_server.py
Open http://127.0.0.1:8765/myshka-app.html#analysis
Requires Ollama and a vision-capable model, e.g. ollama pull qwen2.5vl:3b.
No orders, Telegram sends, or cloud image uploads.
"""
import base64
import json
import os
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = int(os.environ.get("MYSHKA_AI_PORT", "8765"))
MODEL = os.environ.get("MYSHKA_VISION_MODEL", "qwen2.5vl:3b")
OLLAMA = os.environ.get("MYSHKA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MAX_BYTES = 8 * 1024 * 1024
SYSTEM = """Ти JEV — обережний аналітик скріншотів торгових графіків.
Пиши українською, конкретно та стисло. Спочатку прочитай, якщо видно, назву
інструмента, таймфрейм і останню ціну. Якщо не видно — напиши «не видно».
Опиши останні свічки, структуру ціни, напрямок і показники на зображенні.
Вказуй приблизні рівні підтримки/опору ЛИШЕ коли числа читаються на графіку.
Поясни два можливі сценарії з умовами підтвердження і ризики.
Відділяй спостереження від гіпотез; не вигадуй обсяги, точні ціни чи winrate.
Зображення може бути застарілим, OTC-ціни не верифіковані.
Не обіцяй прогнозу наступної свічки, не наказуй купувати/продавати,
не вказуй розмір ставки. Жодних угод не відкривай."""


def api_post(path, payload, timeout=100):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA + path, data=body, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def has_image_signature(raw):
    return (raw.startswith(b"\x89PNG\r\n\x1a\n") or
            raw.startswith(b"\xff\xd8\xff") or
            (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP"))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def json_response(self, status, value):
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/chart-health":
            try:
                req = urllib.request.Request(OLLAMA + "/api/tags")
                with urllib.request.urlopen(req, timeout=3) as response:
                    tags = json.load(response)
                names = [m.get("name", "") for m in tags.get("models", [])]
                self.json_response(200, {"ready": MODEL in names, "model": MODEL,
                                         "ollama": True, "installed": MODEL in names})
            except Exception:
                self.json_response(200, {"ready": False, "model": MODEL,
                                         "ollama": False, "installed": False})
            return
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/chart-analysis":
            return self.json_response(404, {"error": "Unknown API route"})
        length = int(self.headers.get("Content-Length", "0"))
        if length < 1 or length > MAX_BYTES * 1.45:
            return self.json_response(413, {"error": "Фото завелике (до 8 МБ)."})
        try:
            data = json.loads(self.rfile.read(length))
            image64 = data.get("image", "")
            if not isinstance(image64, str) or len(image64) > MAX_BYTES * 1.4:
                return self.json_response(400, {"error": "Неправильний формат фото."})
            raw = base64.b64decode(image64, validate=True)
            if not raw or len(raw) > MAX_BYTES or not has_image_signature(raw):
                return self.json_response(400, {"error": "Потрібен JPG, PNG або WebP до 8 МБ."})
        except (ValueError, TypeError, json.JSONDecodeError):
            return self.json_response(400, {"error": "Не вдалося прочитати фото."})
        try:
            result = api_post("/api/chat", {
                "model": MODEL, "stream": False,
                "options": {"temperature": 0.1, "num_predict": 850},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": "Проаналізуй саме цей скріншот, не вигадуй прихованих даних.",
                     "images": [image64]}
                ]
            })
            analysis = (result.get("message") or {}).get("content", "").strip()
            if not analysis:
                return self.json_response(502, {"error": "JEV не повернув текст аналізу."})
            return self.json_response(200, {"analysis": analysis, "model": MODEL,
                                            "source": "local_ollama", "verified_quotes": False})
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return self.json_response(503, {"error": "Модель " + MODEL +
                    " не знайдена. Виконай: ollama pull " + MODEL})
            return self.json_response(502, {"error": "Ollama повернула HTTP " + str(exc.code)})
        except (urllib.error.URLError, TimeoutError, OSError):
            return self.json_response(503, {"error": "Ollama недоступна. Запусти ollama serve та перевір модель " + MODEL})

    def log_message(self, fmt, *args):
        print("[Myshka AI] " + fmt % args)


if __name__ == "__main__":
    print("Crypto Myshka AI — локально: http://127.0.0.1:%s/myshka-app.html#analysis" % PORT)
    print("Ollama:", OLLAMA, "| Модель:", MODEL, "| Фото не передаються в хмару")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

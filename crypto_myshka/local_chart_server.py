#!/usr/bin/env python3
"""Local-only Fast Analysis server for Crypto Myshka.

Run from the repository: python crypto_myshka/local_chart_server.py
Open http://127.0.0.1:18765/myshka-app.html#analysis
Requires Ollama and a vision-capable model, e.g. ollama pull qwen2.5vl:3b.
No orders, Telegram sends, or cloud image uploads.
"""
import base64
import json
import os
import urllib.error
import urllib.request
import webbrowser
from urllib.parse import unquote, urlsplit
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = int(os.environ.get("MYSHKA_AI_PORT", "18765"))
MODEL = os.environ.get("MYSHKA_VISION_MODEL", "qwen2.5vl:3b")
OLLAMA = os.environ.get("MYSHKA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
if urlsplit(OLLAMA).hostname not in ("localhost", "127.0.0.1", "::1"):
    raise SystemExit("Для захисту фото Ollama повинна працювати лише на localhost.")
MAX_BYTES = 8 * 1024 * 1024
ALLOWED_TIMEFRAMES = {"auto", "15s", "30s", "1m", "5m"}
TIMEFRAME_SECONDS = {"15s": 15, "30s": 30, "1m": 60, "5m": 300}
EXPIRIES = {30, 60, 300}
SYSTEM = """Ти JEV — локальний дослідник скріншотів графіків для ДЕМО-ТЕСТІВ.
Не обіцяй результату угоди. Ти не бачиш майбутніх свічок і не маєш незалежних OTC-котирувань.
Розрізняй:
- chart_timeframe: тривалість ОДНІЄЇ СВІЧКИ на графіку;
- expiry: час ДО ЗАКРИТТЯ угоди після натискання BUY/SELL.
Напис 00:01:00 біля кнопок BUY/SELL — це expiry, НЕ chart_timeframe.
Поверни тільки JSON з ключами:
"direction": "ВГОРУ" | "ВНИЗ" | "НЕВИЗНАЧЕНО" (видимий рух, НЕ майбутня ціна);
"readable": true | false (чи справді видно достатньо свічок та їхню структуру);
"chart_timeframe": "15s" | "30s" | "1m" | "5m" | "unknown";
"test_expiry_seconds": 30 | 60 | 300 | null;
"evidence": коротке конкретне пояснення українською, лише видимі факти (до 180 символів).
Якщо графік закритий меню, кадр не показує свічок, рух змішаний або таймфрейм невідомий —
вкажи direction НЕВИЗНАЧЕНО, readable false, test_expiry_seconds null.
Якщо таймфрейм надіслано явно користувачем, використай його, не вигадуй інший.
Якщо таймфрейм auto, визначай його лише за видимим маркуванням ГРАФІКА.
Демо-експірація — тільки гіпотеза для перевірки, а не оптимальний чи доведений час.
Не вказуй відсотків точності, ставок, прибутку чи інструкцій торгувати.
Для суперечливих ситуацій обирай НЕВИЗНАЧЕНО і null.
"""


def parse_jev_result(content, requested_timeframe="auto"):
    """Convert untrusted model text to a strictly bounded DEMO hypothesis."""
    result = {
        "direction": "НЕВИЗНАЧЕНО", "action": "SKIP", "test_expiry_seconds": None,
        "chart_timeframe": "unknown", "timeframe_source": "unknown",
        "reason": "Не вистачає перевірених даних для демо-гіпотези.",
        "signal_validated": False, "expiry_validated": False,
    }
    if not isinstance(content, str):
        return result
    raw = content.strip()
    try:
        # Ollama JSON mode normally returns plain JSON. Some models wrap it in fences.
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        obj = json.loads(raw)
    except (ValueError, TypeError):
        # Backward-compatible direction-only answers are observations, never trade signals.
        token = raw.upper().strip().strip(".! ")
        if token in ("ВГОРУ", "ВНИЗ", "НЕВИЗНАЧЕНО"):
            result["direction"] = token
            result["reason"] = "Лише видимий напрямок; таймфрейм і час угоди не підтверджено."
        return result
    if not isinstance(obj, dict):
        return result
    direction = obj.get("direction")
    if direction not in ("ВГОРУ", "ВНИЗ", "НЕВИЗНАЧЕНО"):
        return result
    if obj.get("readable") is not True:
        return result
    result["direction"] = direction
    reason = obj.get("evidence")
    if isinstance(reason, str) and reason.strip():
        result["reason"] = reason.strip()[:180]
    manual = requested_timeframe in TIMEFRAME_SECONDS
    model_tf = obj.get("chart_timeframe")
    tf = requested_timeframe if manual else model_tf if model_tf in TIMEFRAME_SECONDS else "unknown"
    result["chart_timeframe"] = tf
    result["timeframe_source"] = "user" if manual else "model" if tf != "unknown" else "unknown"
    expiry = obj.get("test_expiry_seconds")
    # No fabricated 30s recommendation on a 1m or 5m candle.
    if (direction != "НЕВИЗНАЧЕНО" and tf in TIMEFRAME_SECONDS
            and type(expiry) is int and expiry in EXPIRIES
            and expiry >= TIMEFRAME_SECONDS[tf]
            and isinstance(reason, str) and len(reason.strip()) >= 12):
        result["action"] = "BUY" if direction == "ВГОРУ" else "SELL"
        result["test_expiry_seconds"] = expiry
    return result


def api_post(path, payload, timeout=180):
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
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

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
        requested = unquote(self.path.split("?")[0])
        if ".." in requested.split("/") or chr(92) in requested:
            self.send_error(404, "Not found")
            return
        if requested == "/":
            self.send_response(302)
            self.send_header("Location", "/myshka-app.html#analysis")
            self.end_headers()
            return
        # Never expose repository secrets, source files, .env, or local journals.
        allowed = (requested in ("/myshka-app.html", "/myshka.webmanifest", "/myshka-sw.js")
                   or (requested.startswith("/app/") and requested.endswith((".js", ".css", ".svg", ".png", ".webp")))
                   or (requested.startswith("/crypto_myshka/data/") and requested.endswith(".json")))
        if requested != "/api/chart-health" and not allowed:
            self.send_error(404, "Not found")
            return
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
        origin = self.headers.get("Origin")
        if origin and origin not in ("http://127.0.0.1:" + str(PORT), "http://localhost:" + str(PORT)):
            return self.json_response(403, {"error": "Лише локальний застосунок може надсилати фото."})
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self.json_response(415, {"error": "Потрібен application/json."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            return self.json_response(400, {"error": "Неправильний розмір запиту."})
        if length < 1 or length > MAX_BYTES * 1.45:
            return self.json_response(413, {"error": "Фото завелике (до 8 МБ)."})
        try:
            data = json.loads(self.rfile.read(length))
            image64 = data.get("image", "")
            timeframe = data.get("chart_timeframe", "auto")
            if timeframe not in ALLOWED_TIMEFRAMES:
                return self.json_response(400, {"error": "Невідомий таймфрейм свічок."})
            if not isinstance(image64, str) or len(image64) > MAX_BYTES * 1.4:
                return self.json_response(400, {"error": "Неправильний формат фото."})
            raw = base64.b64decode(image64, validate=True)
            if not raw or len(raw) > MAX_BYTES or not has_image_signature(raw):
                return self.json_response(400, {"error": "Потрібен JPG, PNG або WebP до 8 МБ."})
        except (ValueError, TypeError, json.JSONDecodeError):
            return self.json_response(400, {"error": "Не вдалося прочитати фото."})
        try:
            user_prompt = (
                "Оціни тільки видимі свічки. Вказаний користувачем таймфрейм свічок: "
                + timeframe + ". Якщо auto — бери лише підпис на самому графіку. "
                "Вибери тестовий час закриття 30, 60 або 300 секунд лише коли "
                "структура графіка зрозуміла; інакше null. Не плутай із таймером угоди."
            )
            result = api_post("/api/chat", {
                "model": MODEL, "stream": False, "format": "json",
                "options": {"temperature": 0, "num_predict": 230},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": user_prompt, "images": [image64]}
                ]
            })
            analysis = (result.get("message") or {}).get("content", "")
            if not isinstance(analysis, str) or not analysis.strip():
                return self.json_response(502, {"error": "JEV не повернув текст аналізу."})
            decision = parse_jev_result(analysis, timeframe)
            return self.json_response(200, {
                "analysis": decision["direction"], **decision,
                "model": MODEL, "source": "local_ollama",
                "verified_quotes": False, "mode": "demo_hypothesis"
            })
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return self.json_response(503, {"error": "Модель " + MODEL +
                    " не знайдена. Виконай: ollama pull " + MODEL})
            return self.json_response(502, {"error": "Ollama повернула HTTP " + str(exc.code)})
        except TimeoutError:
            return self.json_response(504, {"error": "Ollama не встигла завершити аналіз. Спробуй ще раз або вибери меншу vision-модель."})
        except (urllib.error.URLError, OSError):
            return self.json_response(503, {"error": "Ollama недоступна. Запусти ollama serve та перевір модель " + MODEL})

    def log_message(self, fmt, *args):
        print("[Myshka AI] " + fmt % args)


if __name__ == "__main__":
    print("Crypto Myshka AI — локально: http://127.0.0.1:%s/myshka-app.html#analysis" % PORT)
    print("Ollama:", OLLAMA, "| Модель:", MODEL, "| Фото не передаються в хмару")
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        raise SystemExit("Port %s is busy. Close the old Myshka server or change MYSHKA_AI_PORT. (%s)" % (PORT, exc))
    webbrowser.open("http://127.0.0.1:%s/myshka-app.html#analysis" % PORT)
    server.serve_forever()

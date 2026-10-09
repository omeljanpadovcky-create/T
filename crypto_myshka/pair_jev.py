"""Optional separate JEV AI explainer for observed LIVE instrument cards.

No market data or verified trade outcomes are fed to this model. This is
secondary explanation of already OCR/vision-extracted screenshot context,
NOT a confirmation of a live price or a profitable trade.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

import requests

OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
APINEX_KEY = os.getenv("APINEX_API_KEY", "").strip()
APINEX_ENABLED = os.getenv("LIVE_APINEX_ENABLED", "").strip().lower() in {"1", "true", "yes"}
APINEX_MODEL = os.getenv("JEV_APINEX_TEXT_MODEL", "free/deepseek-v4.1-flash").strip()
OLLAMA_URL = os.getenv("MYSHKA_OLLAMA_URL", "").strip().rstrip("/")
OPENAI_MODEL = os.getenv("JEV_PAIR_MODEL", "gpt-4.1-mini")
OLLAMA_MODEL = os.getenv("MYSHKA_JEV_MODEL") or os.getenv("MYSHKA_OLLAMA_MODEL", "qwen2.5vl:3b")
MIN_INTERVAL = max(180, int(os.getenv("JEV_PAIR_MIN_INTERVAL_SECONDS", "300")))
_cached: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()

PROMPT = """Ти JEV — незалежний агент-пояснювач аналізу трейдингового LIVE-кадру.
Отримуєш ЛИШЕ витягнуті з кадру дані. Це НЕ підтверджені ринкові ціни.
Поясни логіку з прив'язкою до фактичних видимих ознак і те, що НЕ можна знати.
НЕ вигадуй свічки, котирування, обсяг, таймфрейм, рівні, стопи, точки входу,
прибутковість, прогнози або факт виконаної угоди.
Розділяй криптовалюти, форекс і брокерські OTC пари.
Якщо доказів мало, поясни чому й чого бракує.
Поверни тільки JSON:
{"why":"чому саме такий попередній тренд за кадром",
"key_levels":"що видно, а що не підтверджено",
"watch_next":"що перевірити перед будь-яким рішенням",
"what_to_do":"WAIT / OBSERVE",
"confidence":"low|medium"}
Без фінансових обіцянок і без наказів робити ставку. Українською.
"""


def safe_text(value: object, n: int = 480) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:n]


def parse_response(value: object) -> dict:
    if not isinstance(value, str):
        raise ValueError("JEV did not return text")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("JEV did not return JSON object")
    result = {key: safe_text(parsed.get(key), 500) for key in ("why", "key_levels", "watch_next")}
    if not result["why"]:
        raise ValueError("JEV reasoning is empty")
    result.update(
        engine="separate_ai_explainer",
        status="model",
        what_to_do="WAIT / OBSERVE",
        confidence="medium" if parsed.get("confidence") == "medium" else "low",
    )
    return result


def provider() -> str | None:
    if APINEX_KEY and APINEX_ENABLED:
        return "apinex"
    if OPENAI_KEY:
        return "openai"
    if OLLAMA_URL:
        return "ollama"
    return None


def analyze(obs: dict) -> dict:
    if not isinstance(obs, dict) or not obs.get("asset"):
        return {"status": "missing_instrument", "engine": "none"}
    chart = obs.get("chart")
    chart = chart if isinstance(chart, dict) else {}
    if all(chart.get(x) in (None, "unknown", [], "") for x in ("trend", "price_action", "trend_reason", "support_levels", "resistance_levels")):
        return {"status": "insufficient_visible_evidence", "engine": "none"}
    active = provider()
    if not active:
        return {"status": "not_configured", "engine": "none"}

    # Keep the original frame extraction inputs as untrusted contextual claims.
    context = {
        "instrument_visible": safe_text(obs.get("asset"), 60),
        "chart": chart,
        "visual_evidence": safe_text(obs.get("visual_evidence"), 500),
        "speaker_claim_unverified": safe_text(obs.get("speaker_claim"), 150),
        "independent_price_verification": False,
    }
    key = safe_text(obs.get("asset"), 60).upper()
    with _lock:
        cache = _cached.get(key)
        if cache and time.monotonic() - cache[0] < MIN_INTERVAL:
            return dict(cache[1], cached=True)

    try:
        if active == "ollama":
            if not (OLLAMA_URL.startswith("http://127.0.0.1:") or OLLAMA_URL.startswith("http://localhost:")):
                raise ValueError("Local Ollama must be on loopback")
            r = requests.post(
                OLLAMA_URL + "/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": PROMPT + "\n" + json.dumps(context, ensure_ascii=False),
                      "stream": False, "format": "json"},
                timeout=55,
            )
            r.raise_for_status()
            explanation = parse_response(r.json().get("response"))
        else:
            endpoint = ("https://api.apinex.bond/v1/chat/completions"
                        if active == "apinex" else "https://api.openai.com/v1/chat/completions")
            model = APINEX_MODEL if active == "apinex" else OPENAI_MODEL
            secret = APINEX_KEY if active == "apinex" else OPENAI_KEY
            r = requests.post(
                endpoint,
                headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
                json={"model": model, "temperature": 0.1, "max_tokens": 480,
                      "response_format": {"type": "json_object"},
                      "messages": [
                          {"role": "system", "content": PROMPT},
                          {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                      ]},
                timeout=40,
            )
            r.raise_for_status()
            explanation = parse_response(r.json()["choices"][0]["message"]["content"])
        explanation["provider"] = active
        with _lock:
            _cached[key] = (time.monotonic(), explanation)
        return explanation
    except Exception as exc:
        return {"status": "model_unavailable", "engine": "none", "error": type(exc).__name__}

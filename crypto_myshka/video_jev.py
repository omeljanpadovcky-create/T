"""Optional JEV reasoning for available YouTube subtitle text.

Public video descriptions/captions are sent to the existing JEV provider only
when key configured. Not all videos have captions. Does not watch/copy videos.
"""
from __future__ import annotations
import json
import os
import re
import requests

API_KEY = os.getenv("APINEX_API_KEY", "").strip()
MODEL = os.getenv("YOUTUBE_JEV_MODEL", "free/deepseek-v4.1-flash").strip()
ENABLED = os.getenv("YOUTUBE_JEV_ENABLED", "true").strip().lower() == "true"
ENDPOINT = "https://api.apinex.bond/v1/chat/completions"
SYSTEM = """Ти JEV, помічник Мишки. Читаєш уривок РЕАЛЬНО ДОСТУПНИХ субтитрів відео трейдера.
Видай стислий український конспект саме сказаного у тексті. Відділяй спостереження автора
від фактів. НЕ вигадуй свічки, угоди, прибуток, статистику winrate, котирування,
напрямок майбутньої ціни або таймфрейм, якщо їх не названо у контексті.
Не надавай інструкцій відкривати позиції або робити ставки. Не обіцяй результатів.
Повертай лише JSON із 4 рядковими ключами:
"summary" — коротко зміст, "strategy" — які прийоми/індикатори згадано,
"risk" — що не підтверджено, "takeaway" — нейтральний висновок для навчання.
Немає інформації — так і скажи. Це конспект субтитрів, не візуальний перегляд ролика."""


def extract_json(content: str) -> dict:
    if not isinstance(content, str):
        raise ValueError("AI result is not text")
    raw=content.strip()
    if raw.startswith(chr(96)*3):
        raw=re.sub(r"^"+chr(96)*3+r"(?:json)?\s*|\s*"+chr(96)*3+r"$", "", raw)
    result=json.loads(raw)
    if not isinstance(result,dict):
        raise ValueError("AI result is not an object")
    cleaned={key:re.sub(r"\s+"," ",str(result.get(key) or "")).strip()[:500]
             for key in ("summary","strategy","risk","takeaway")}
    if not cleaned["summary"]:
        raise ValueError("Empty JEV summary")
    return cleaned


def summarize(*, title: str, description: str, subtitles: str, instruments: list,
              indicators: list) -> dict:
    """Call existing APInex account only when explicitly enabled and text exists."""
    if not subtitles or len(subtitles.strip()) < 100:
        return {"status":"insufficient_captions", "reason":"Video subtitle text unavailable or too short"}
    if not API_KEY or not ENABLED:
        return {"status":"not_configured", "reason":"JEV API token missing or YouTube JEV disabled"}
    if not MODEL.startswith("free/"):
        return {"status":"not_configured", "reason":"Only free/ models allowed in automated archive"}
    context={
        "title":str(title)[:220],
        "description_claim":str(description)[:350],
        "mentioned_pairs":list(instruments)[:10],
        "mentioned_indicators":list(indicators)[:10],
        "subtitle_excerpt_from_accessible_track":subtitles[:12000],
        "may_have_unread_remaining_text":len(subtitles)>12000,
        "market_prices_verified":False,
    }
    try:
        res=requests.post(
            ENDPOINT,
            headers={"Authorization":"Bearer "+API_KEY,
                     "Content-Type":"application/json"},
            json={"model":MODEL,"temperature":0.15,"max_tokens":650,
                  "messages":[{"role":"system","content":SYSTEM},
                              {"role":"user","content":json.dumps(context,ensure_ascii=False)}]},
            timeout=28,
        )
        if res.status_code in (401,402,429):
            return {"status":"provider_unavailable","http_status":res.status_code}
        res.raise_for_status()
        body=res.json()
        choices=body.get("choices") or []
        if not choices or not isinstance(choices[0],dict):
            raise ValueError("Missing JEV output choices")
        message=choices[0].get("message") or {}
        content=message.get("content")
        if isinstance(content,list):
            content="\n".join(str(c.get("text") or "") for c in content if isinstance(c,dict))
        out=extract_json(content)
        return {"status":"model_summary", "provider":"APInex", "model":MODEL,
                "based_on":"partial_or_full_available_subtitle_text", **out,
                "market_prices_verified":False, "trades_verified":False}
    except (ValueError, TypeError, requests.RequestException) as exc:
        return {"status":"provider_unavailable","error_type":type(exc).__name__}

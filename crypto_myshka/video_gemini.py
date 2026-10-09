"""Gemini Video Understanding for PUBLIC YouTube URLs, without subtitles.

Gemini processes audio + sampled frames via its official Video Understanding API:
https://ai.google.dev/gemini-api/docs/video-understanding

No user API keys in JavaScript or public JSON. Results are structured model
interpretations, never verified brokerage prices or successful trades.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

import requests

MODEL = os.getenv("YOUTUBE_GEMINI_MODEL", "gemini-2.5-flash").strip()
ENABLED = os.getenv("YOUTUBE_GEMINI_ENABLED", "true").lower().strip() == "true"
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MAX_PER_RUN = max(0, min(3, int(os.getenv("YOUTUBE_GEMINI_MAX_PER_RUN", "1"))))
# Conservative budget vs free-tier 8 hours of YouTube video per day.
DAILY_VIDEO_BUDGET = max(0, min(28800, int(os.getenv("YOUTUBE_GEMINI_DAILY_SECONDS", "21600"))))
UNSIZED_RESERVATION = max(60, int(os.getenv("YOUTUBE_GEMINI_UNKNOWN_VIDEO_SECONDS", "1800")))
VALID_ID = re.compile(r"^[a-zA-Z0-9_-]{11}$")
VALID_MODEL = re.compile(r"^gemini-[a-zA-Z0-9._-]+$")
PROMPT = """Ти Gemini, відеоаналітик для ТрейдМишки (JEV), аналізуєш саме це публічне YouTube-ВІДЕО:
візуальні кадри й звук, а НЕ субтитри або вигаданий переказ за назвою.
Розрізняй ФАКТ, ПОБАЧЕНИЙ У КАДРІ; ТВЕРДЖЕННЯ АВТОРА; НЕВІДОМЕ.
Розбери зміст українською: згадані валютні/крипто пари, індикатори, таймфрейми,
логіку навчального пояснення, можливі візуальні спостереження на графіку.
Не фантазуй про проведені угоди, 100% успішність, реальні суми на рахунку, гарантований
напрямок наступної свічки. Не видавай рекомендацію BUY/SELL чи короткі експірації.
Якщо точний момент або рівень не розбірливий, пиши «невідомо».
Звичайне семплювання відео (~1 кадр/сек.) МОЖЕ пропустити коротку угоду.
Усі числові ринкові ціни й winrate — непідтверджені заяви, якщо немає зовнішніх котирувань.
Поверни тільки JSON:
{
 "summary":"2-4 речення реального змісту",
 "strategy":"що пояснював трейдер і з яких підстав (або не визначено)",
 "risk":"що НЕ підтверджено й які ризики",
 "takeaway":"короткий нейтральний висновок для навчання",
 "pairs":["AUD/CNY OTC"],
 "indicators":["RSI"],
 "timeframes":["M1"],
 "moments":[{"timestamp":"00:12","observation":"Короткий опис лише спостережуваного"}],
 "visual_context":"що модель реально бачила на графіку, без прогнозів",
 "audio_context":"про що говорить автор, якщо є звук"
}
Тільки українська мова. Якщо відео не прочитано, не вигадуй зміст."""


def available() -> bool:
    return bool(API_KEY and ENABLED and VALID_MODEL.fullmatch(MODEL))


def _limited(value: object, max_length: int = 600) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_length]


def _terms(value: object, cap: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for term in value:
        if not isinstance(term, str):
            continue
        item = _limited(term, 45)
        if item and item not in out:
            out.append(item)
        if len(out) >= cap:
            break
    return out


def parse_model_output(body: dict) -> dict:
    candidates = body.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Gemini did not return text candidates")
    parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
    raw = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)).strip()
    if raw.startswith(chr(96)*3):
        raw = re.sub(r"^"+chr(96)*3+r"(?:json)?\s*|\s*"+chr(96)*3+r"$", "", raw)
    result = json.loads(raw)
    if not isinstance(result, dict) or not _limited(result.get("summary")):
        raise ValueError("Gemini summary is empty or malformed")
    output = {k: _limited(result.get(k), 650)
              for k in ("summary", "strategy", "risk", "takeaway", "visual_context", "audio_context")}
    for key in ("pairs", "indicators", "timeframes"):
        output[key] = _terms(result.get(key))
    moments = result.get("moments")
    clean_moments = []
    if isinstance(moments, list):
        for m in moments[:8]:
            if not isinstance(m, dict):
                continue
            timestamp = _limited(m.get("timestamp"), 12)
            observation = _limited(m.get("observation"), 170)
            if re.fullmatch(r"\d{1,3}:\d{2}(?::\d{2})?", timestamp) and observation:
                clean_moments.append({"timestamp": timestamp, "observation": observation})
    output["moments"] = clean_moments
    return output


def analyze_public_youtube(video_id: str, *, title: str = "") -> dict:
    """Official Gemini API, YouTube file_data.file_uri. No subtitle requirement."""
    if not VALID_ID.fullmatch(str(video_id)):
        return {"status": "invalid_video_id"}
    if not available():
        return {"status": "not_configured",
                "reason": "Configure GEMINI_API_KEY as a GitHub Actions secret"}
    url = "https://www.youtube.com/watch?v=" + video_id
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": [
                    {"text": PROMPT + "\nНазва ролика (лише контекст, не доказ): " + _limited(title, 160)},
                    {"file_data": {"file_uri": url}},
                ]}],
                "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
            },
            timeout=115,
        )
        if response.status_code in (400, 401, 402, 403, 404, 429):
            return {"status": "unavailable", "http_status": response.status_code}
        response.raise_for_status()
        result = parse_model_output(response.json())
        return {
            "status": "gemini_video_summary",
            "source_type": "public_youtube_video_audio_and_sampled_frames",
            "provider": "Google Gemini API",
            "model": MODEL,
            "video_id": video_id,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "market_quotes_verified": False,
            "executed_trades_verified": False,
            "frames_may_be_skipped": True,
            **result,
        }
    except (ValueError, TypeError, KeyError, requests.RequestException) as exc:
        return {"status": "unavailable", "error_type": type(exc).__name__}

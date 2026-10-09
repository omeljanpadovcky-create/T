"""CryptoMyshka live broadcast observer — additive, read-only module.

Runs once in GitHub Actions; --watch can keep polling on an always-on machine.
Public LIVE metadata is checked without an AI key. Optional screenshot/audio
analysis needs a configured vision provider and the public stream to be accessible by ffmpeg.

One frame is evidence of an on-screen claim, NEVER proof of an executed fill.
No brokerage integration, order placement, or automatic final trade signals.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from yt_dlp import YoutubeDL
from youtube_analysts import CHANNELS

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "youtube_live.json"
MODEL = os.getenv("LIVE_VISION_MODEL", "gpt-4.1-mini")
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
APINEX_KEY = os.getenv("APINEX_API_KEY", "").strip()
# GitHub scheduled runs must explicitly opt in to APInex chargeable vision calls.
APINEX_ENABLED = os.getenv("LIVE_APINEX_ENABLED", "").strip().lower() in {"1", "true", "yes"}
USE_APINEX = bool(APINEX_KEY and APINEX_ENABLED)
APINEX_MODEL = os.getenv("LIVE_APINEX_VISION_MODEL", "gemini-3.8-flash").strip()
OLLAMA_URL = os.getenv("MYSHKA_OLLAMA_URL", "").strip().rstrip("/")
OLLAMA_MODEL = os.getenv("MYSHKA_OLLAMA_MODEL", "qwen2.5vl:3b").strip()
BROWSER = os.getenv("MYSHKA_YOUTUBE_BROWSER", "").strip().lower()
AI_AVAILABLE = bool(USE_APINEX or API_KEY or OLLAMA_URL)
CAPTURE_INTERVAL = max(15, int(os.getenv("LIVE_CAPTURE_INTERVAL", "300")))
MAX_FRAMES_PER_RUN = max(1, min(5, int(os.getenv("LIVE_MAX_SNAPSHOTS", "3"))))

PROMPT = """Ти незалежний спостерігач публічної LIVE-трансляції трейдера.
Проаналізуй кадр торгової платформи, а також фрагмент озвучування, якщо є.
НЕ вигадуй угоди, пари, суми, час, результати, свічки чи зроблені ставки.
НЕ прирівнюй слова трейдера, демонстраційний баланс і winrate до фактичного результату.
Якщо кадр не показує угоду — action = "unknown".
Якщо бачиш лише кнопку купити/продати — це НЕ доказ натискання.
Розділяй UTC момент спостереження та час угоди у кадрі (може бути минулим).
Відповідь ВИКЛЮЧНО JSON-об'єкт з полями:
{ "action": "claimed_entry|claimed_exit|commentary|unknown",
  "asset": null, "direction": null, "stake": null,
  "expiry": null, "outcome": null, "platform": null,
  "speaker_claim": null, "visual_evidence": "короткий опис фактично видимого",
  "confidence": "low|medium",
  "chart": {
    "trend": "uptrend|downtrend|sideways|unknown",
    "volatility": "high|normal|low|unknown",
    "volume": "high|normal|low|unknown",
    "sentiment": "bullish|bearish|neutral|unknown",
    "support_levels": [],
    "resistance_levels": [],
    "price_action": null,
    "trend_reason": null
  }
}.
Назва інструмента — рівно як видно на екрані: AUD/CNY OTC, AUD/JPY, BTC/USDT.
НЕ називай AUD/CNY OTC криптовалютою. НЕ домислюй рівні чи обсяг.
Підтримка/опір — лише розбірливі числові значення з графіка.
Якщо чогось не видно, поверни unknown/null/порожній список.
Поясни українською, ЧОМУ ти визначив тренд (розпізнані свічки, максимум/мінімум), а не просто напрямок.
Не пропонуй реальну угоду без незалежних цін і часових даних.
Це один кадр; не заявляй winrate або підтверджене закриття ставки.
Без команд купувати чи продавати. Пиши українською.
"""

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def stamp() -> float:
    return time.time()

def load() -> dict:
    try:
        value = json.loads(OUT.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}

def save(value: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)

def ydl_options(flat=False) -> dict:
    result = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "ignoreerrors": True, "socket_timeout": 13, "retries": 0,
        "extract_flat": flat, "noplaylist": not flat,
        "youtube_include_dash_manifest": False,
    }
    if BROWSER in {"chrome", "edge", "firefox", "brave"}:
        result["cookiesfrombrowser"] = (BROWSER,)
    if flat:
        result["playlistend"] = 12
    return result

def get_stream(channel: dict) -> tuple[dict | None, str | None]:
    """Use official public channel URL. A VOD must NEVER be classified as LIVE."""
    handle = channel.get("handle")
    if not handle or not channel.get("confirmed"):
        return None, "Потрібне підтверджене посилання на канал"
    base = "https://www.youtube.com/" + handle
    candidates = []
    errors = []
    try:
        with YoutubeDL(ydl_options(flat=True)) as ydl:
            page = ydl.extract_info(base + "/streams", download=False) or {}
        for entry in page.get("entries") or []:
            if entry and (entry.get("live_status") == "is_live" or entry.get("is_live") is True):
                vid = entry.get("id")
                if vid and re.fullmatch(r"[\w-]{11}", str(vid)):
                    candidates.append("https://www.youtube.com/watch?v=" + vid)
    except Exception as exc:
        errors.append(str(exc)[:200])
    # The /live canonical endpoint redirects to an active stream on many channels.
    candidates.append(base + "/live")
    for url in dict.fromkeys(candidates):
        try:
            with YoutubeDL(ydl_options()) as ydl:
                info = ydl.extract_info(url, download=False) or {}
            if info.get("is_live") is True or info.get("live_status") == "is_live":
                vid = str(info.get("id") or "")
                if not re.fullmatch(r"[\w-]{11}", vid):
                    continue
                return {
                    "video_id": vid,
                    "url": "https://www.youtube.com/watch?v=" + vid,
                    "title": str(info.get("title") or "LIVE")[:240],
                    "live_status": "is_live",
                    "viewer_count": info.get("concurrent_view_count"),
                    "_formats": info.get("formats") or [],
                }, None
        except Exception as exc:
            errors.append(str(exc)[:200])
    # Preserve YouTube's anti-bot failures: they may be followed by a misleading
    # "not currently live" response from another extractor.
    if any("sign in to confirm" in e.lower() or "not a bot" in e.lower()
           or "cookies" in e.lower() for e in errors):
        return None, "youtube_access_blocked: automatic viewer challenged; use a local authenticated session"
    if errors and all("not currently live" in e.lower() or "does not have a streams tab" in e.lower()
                      for e in errors):
        return None, None  # No live listing found; this is not proof of offline status.
    if errors:
        return None, "youtube_lookup_failed: " + errors[-1]
    return None, None

def choose_stream_url(formats: list) -> str | None:
    """Pick a public lower-resolution video source for a single temporary frame."""
    viable = []
    for fmt in formats:
        url = fmt.get("url") or ""
        if not url.startswith("https://"):
            continue
        if fmt.get("vcodec") in (None, "none"):
            continue
        if fmt.get("protocol") in ("m3u8_native", "m3u8", "https", "http"):
            height = int(fmt.get("height") or 720)
            score = abs(height - 480) + (300 if height > 1080 else 0)
            viable.append((score, url))
    return min(viable, default=(None, None))[1]

def ffmpeg_run(args: list, timeout: int) -> bool:
    try:
        ffmpeg_binary = shutil.which("ffmpeg")
        if not ffmpeg_binary:
            import imageio_ffmpeg
            ffmpeg_binary = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [ffmpeg_binary, "-nostdin", "-hide_banner", "-loglevel", "error",
             "-rw_timeout", "12000000", "-y"] + args,
            capture_output=True, timeout=timeout, check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False

def capture(stream_url: str, directory: Path) -> tuple[Path | None, Path | None]:
    image = directory / "current.jpg"
    audio = directory / "voice.wav"
    # Only a single temporary still frame, not a downloaded video archive.
    got_frame = ffmpeg_run(
        ["-i", stream_url, "-frames:v", "1", "-vf", "scale=960:-2", "-q:v", "5", str(image)],
        34,
    ) and image.exists() and image.stat().st_size > 2000
    # Audio is an optional short scratch segment, deleted immediately after analysis.
    got_audio = False
    if got_frame and API_KEY:
        got_audio = ffmpeg_run(
            ["-i", stream_url, "-t", "12", "-vn", "-ac", "1", "-ar", "16000", str(audio)],
            31,
        ) and audio.exists() and audio.stat().st_size > 8000
    return image if got_frame else None, audio if got_audio else None

def transcribe(audio: Path | None) -> str:
    if not API_KEY or not audio:
        return ""
    try:
        with audio.open("rb") as f:
            r = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": "Bearer " + API_KEY},
                files={"file": (audio.name, f, "audio/wav")},
                data={"model": "whisper-1"}, timeout=50,
            )
        r.raise_for_status()
        return str(r.json().get("text") or "")[:1000]
    except Exception:
        return ""

def vision(image: Path, transcript: str) -> dict:
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    if not USE_APINEX and not API_KEY and OLLAMA_URL:
        if not (OLLAMA_URL.startswith("http://127.0.0.1:") or OLLAMA_URL.startswith("http://localhost:")):
            raise ValueError("Local Ollama must use localhost, not a public endpoint")
        response = requests.post(
            OLLAMA_URL + "/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": PROMPT + "\nUTC: " + now(),
                  "images": [encoded], "stream": False, "format": "json"},
            timeout=95,
        )
        response.raise_for_status()
        parsed = json.loads(response.json().get("response") or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("Local vision response not JSON object")
        return normalize_observation(parsed)
    if USE_APINEX:
        endpoint, token, model = "https://api.apinex.bond/v1/chat/completions", APINEX_KEY, APINEX_MODEL
    elif API_KEY:
        endpoint, token, model = "https://api.openai.com/v1/chat/completions", API_KEY, MODEL
    else:
        raise ValueError("No enabled AI provider for frame analysis")
    r = requests.post(
        endpoint,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        json={
            "model": model, "temperature": 0,
            "max_tokens": 420, "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": "UTC спостереження: " + now() +
                     ". Фрагмент слів ведучого (не доказ угоди): " +
                     (transcript or "[недоступний]")},
                    {"type": "image_url", "image_url": {
                        "url": "data:image/jpeg;base64," + encoded, "detail": "high",
                    }},
                ]},
            ],
        }, timeout=60,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(
            item if isinstance(item, str) else str(item.get("text") or "")
            for item in content if isinstance(item, (str, dict))
        )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Vision model returned no text")
    clean = content.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean).strip()
    parsed = json.loads(clean)
    return normalize_observation(parsed)

def normalize_observation(parsed: dict) -> dict:
    if not isinstance(parsed, dict):
        raise ValueError("Vision response is not an object")
    allowed = {"claimed_entry", "claimed_exit", "commentary", "unknown"}
    parsed["action"] = parsed.get("action") if parsed.get("action") in allowed else "unknown"
    parsed["confidence"] = "medium" if parsed.get("confidence") == "medium" else "low"
    for field in ("asset", "direction", "stake", "expiry", "outcome", "platform", "speaker_claim", "visual_evidence"):
        value = parsed.get(field)
        parsed[field] = str(value)[:260] if value is not None else None
    raw_chart = parsed.get("chart")
    raw_chart = raw_chart if isinstance(raw_chart, dict) else {}
    fields = {
        "trend": {"uptrend", "downtrend", "sideways", "unknown"},
        "volatility": {"high", "normal", "low", "unknown"},
        "volume": {"high", "normal", "low", "unknown"},
        "sentiment": {"bullish", "bearish", "neutral", "unknown"},
    }
    chart = {}
    for field, allowed_values in fields.items():
        value = str(raw_chart.get(field) or "").lower()
        chart[field] = value if value in allowed_values else "unknown"
    for field in ("price_action", "trend_reason"):
        value = raw_chart.get(field)
        chart[field] = str(value)[:600] if isinstance(value, str) and value.strip() else None
    for field in ("support_levels", "resistance_levels"):
        raw_levels = raw_chart.get(field)
        chart[field] = [
            str(num) for num in raw_levels[:4]
            if isinstance(num, (str, int, float)) and not isinstance(num, bool)
            and re.fullmatch(r"-?\d{1,10}(?:\.\d{1,9})?", str(num).strip())
        ][:3] if isinstance(raw_levels, list) else []
    parsed["chart"] = chart
    return parsed

def process_once() -> dict:
    previous = load()
    old_streams = {x.get("id"): x for x in previous.get("channels") or []}
    history = list(previous.get("observations") or [])
    channels = []
    count = 0
    for channel in CHANNELS:
        row = {
            "id": channel["id"], "name": channel["name"],
            "handle": channel.get("handle"), "url": channel.get("url"),
            "live_page": "https://www.youtube.com/" + channel["handle"] + "/live" if channel.get("handle") else None,
            "status": "unknown", "live": False,
            "checked_at": now(), "stream": None,
            "last_visual_check": (old_streams.get(channel["id"]) or {}).get("last_visual_check"),
        }
        if not channel.get("confirmed"):
            row["status"] = "source_unverified"
            channels.append(row)
            continue
        stream, err = get_stream(channel)
        if not stream:
            # A blocked extractor or missing stream is NOT proof that the channel is offline.
            row["status"] = ("access_blocked" if err and err.startswith("youtube_access_blocked")
                             else "check_error" if err else "not_detected")
            if err:
                row["error"] = err
            channels.append(row)
            continue
        row.update(status="LIVE", live=True, stream={k: v for k, v in stream.items() if k != "_formats"})
        last = row.get("last_visual_check")
        age = float("inf")
        if last:
            try:
                age = stamp() - datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp()
            except Exception:
                pass
        if count >= MAX_FRAMES_PER_RUN or age < CAPTURE_INTERVAL:
            row["observation_status"] = "next_capture_pending"
            channels.append(row)
            continue
        if not AI_AVAILABLE:
            row["observation_status"] = "requires_AI_provider_activation"
            channels.append(row)
            continue
        src = choose_stream_url(stream.get("_formats") or [])
        if not src:
            row["observation_status"] = "media_unavailable"
            channels.append(row)
            continue
        row["last_visual_check"] = now()  # rate-limit failed captures too
        count += 1
        try:
            with tempfile.TemporaryDirectory(prefix="myshka-live-") as folder:
                frame, audio = capture(src, Path(folder))
                if not frame:
                    row["observation_status"] = "frame_unavailable"
                else:
                    words = transcribe(audio)
                    read = vision(frame, words)
                    from pair_jev import analyze as jev_explain
                    read["jev"] = jev_explain(read)
                    event = {
                        "observed_at": now(),
                        "channel_id": channel["id"],
                        "channel_name": channel["name"],
                        "video_id": stream["video_id"],
                        "url": stream["url"],
                        "claim_only": True,
                        "independently_verified": False,
                        "data_source": "public_live_frame_and_optional_audio",
                        "observation": read,
                    }
                    # Keep observations time-stamped. Never call this an executed trade.
                    history.append(event)
                    row["observation_status"] = "visual_claim_reviewed"
        except Exception as exc:
            row["observation_status"] = "analysis_unavailable"
            row["observation_error"] = str(exc)[:180]
        channels.append(row)

    updated = {
        "version": 1, "updated_at": now(), "mode": "LIVE public streams monitoring",
        "polling": "Every 5 minutes on scheduled GitHub Actions (may be delayed); --watch for persistent host",
        "channels": channels, "observations": history[-100:],
        "live_count": sum(bool(x["live"]) for x in channels),
        "final_signal": "SKIP",
        "auto_trade": False,
        "notice": "Single LIVE screenshots and streamer statements are not independently verified fills or profit statistics.",
        "ai_enabled": AI_AVAILABLE,
        "ai_provider": "apinex" if USE_APINEX else "openai" if API_KEY else ("local_ollama" if OLLAMA_URL else "none"),
    }
    save(updated)
    try:
        from pair_reports import update_from_live
        update_from_live(updated)
    except Exception as exc:
        print("Pair report generation failed:", str(exc)[:200])
    return updated

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="Continuous local monitor on an always-on computer/server")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between checks in --watch")
    args = parser.parse_args()
    while True:
        result = process_once()
        for item in result["channels"]:
            print(f'{item["name"]}: {item["status"]} {item.get("observation_status", "")}')
        print("LIVE", result["live_count"], "AI", result["ai_enabled"], "read-only")
        if not args.watch:
            return
        time.sleep(max(15, args.interval))

if __name__ == "__main__":
    main()

"""Read-only public YouTube educational content extraction for CryptoMyshka.

Public video metadata and available caption snippets are treated as claims,
not verified signals. No broker API, orders, or trading side effects.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from yt_dlp import YoutubeDL

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "data" / "youtube_analysts.json"

# Four specified YouTube channels. Unverified fifth channel removed as requested.
CHANNELS = [
    {"id": "nikolas", "name": "НИКОЛАС | ТРЕЙДЕР", "handle": "@NikolasTradin", "url": "https://www.youtube.com/@NikolasTradin/videos", "confirmed": True},
    {"id": "backstage", "name": "Закулисье Трейдера", "handle": "@artemtraderr", "url": "https://www.youtube.com/@artemtraderr/videos", "confirmed": True},
    {"id": "mark", "name": "Mark Champs Trader", "handle": "@Mark_champs_trader", "url": "https://www.youtube.com/@Mark_champs_trader/videos", "confirmed": True},
    {"id": "alexey", "name": "Алексей Борщев", "handle": "@alexeyborshev1", "url": "https://www.youtube.com/@alexeyborshev1/videos", "confirmed": True},
]

PAIR_RE = re.compile(r"(?<![A-Z0-9])(BTC|ETH|SOL|BNB|XRP|DOGE|ADA|AVAX|LINK)(?:\s*[/_-]\s*(?:USDT|USD))?(?![A-Z0-9])", re.I)
LONG_RE = re.compile(r"\b(long|buy|call|bullish|лонг|купить|покупка|зростанн|рост|вверх)\b", re.I)
SHORT_RE = re.compile(r"\b(short|sell|put|bearish|шорт|продать|продажа|падінн|падени|вниз)\b", re.I)
OTC_RE = re.compile(r"\b(otc|pocket\s*option|quotex|binarn|binary|бинарн|бінарн|экспирац|експіраці)\b", re.I)
PROMO_RE = re.compile(r"\b(100%|без\s*проигрыш|гарантир|гарантов|vip|промокод|реферал|удвой|копитрейдинг|copy\s*trading|winrate)\b", re.I)
TRADING_RE = re.compile(r"(trading|trade|trader|трейд|торгов|strategy|стратег|отс|otc|pocket.?option|option|crypt|крипт|forex|binanc|btc|eth|сигнал|копитрейд|сделк|угод)", re.I)
INSTRUMENT_RE = re.compile(r"(?<![A-Z0-9])(?:BTC|ETH|SOL|XRP|ADA|BNB|DOGE|LINK|AVAX|AUD|CHF|USD|EUR|GBP|JPY|CAD|NZD|AED|IDR|CNY|TRY)\\s*[/_-]\\s*(?:USDT|USDC|USD|BTC|ETH|AUD|CHF|EUR|GBP|JPY|CAD|NZD|AED|IDR|CNY|TRY)\\s*(?:OTC)?(?![A-Z0-9])", re.I)
TIMEFRAME_RE = re.compile(r"(?<![A-Z0-9])(?:M1|M5|M15|M30|H1|H4|D1|1m|5m|15m|1h|4h)(?![A-Z0-9])", re.I)
INDICATOR_RE = re.compile(r"(?i)\\b(?:rsi|ema|sma|macd|stochastic|moving average|bollinger|price action|support|resistance|підтримк|опір|поддержк|сопротивлен|скользящ|середн)\\w*")

VERIFIED_EXAMPLES = {
    "nikolas": ("g5sXQlvCPVo", "I'm Trading LIVE — Watch What Happens | Pocket Option LIVE"),
    "mark": ("L31S4DgpEIo", "ОНЛАЙН СТРИМ. КОПИРОВАНИЕ СДЕЛОК 7.10 ВЕЧЕРНИЙ ЭФИР"),
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()

def caption_excerpt(video: dict) -> str:
    """Read only short public subtitle excerpt, if yt-dlp lists it."""
    tracks = video.get("subtitles") or video.get("automatic_captions") or {}
    for language in ("uk", "ru", "en", "en-US"):
        choices = tracks.get(language) or []
        selected = next((x for x in choices if x.get("ext") == "json3" and x.get("url")), None)
        if not selected:
            continue
        try:
            r = requests.get(selected["url"], timeout=12, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            events = r.json().get("events") or []
            text = normalize(" ".join(
                segment.get("utf8", "") for event in events[:100]
                for segment in event.get("segs", [])
            ))
            return text[:1200]
        except Exception:
            continue
    return ""

def classify(title: str, description: str = "", excerpt: str = "") -> dict:
    # We do not infer trade directions from the shape of a chart in a video title.
    visible = normalize(" ".join((title, description[:1400], excerpt[:1200])))
    marketing = bool(PROMO_RE.search(visible))
    otc = bool(OTC_RE.search(visible))
    pairs = list(dict.fromkeys(x.upper() for x in PAIR_RE.findall(visible)))
    long = bool(LONG_RE.search(visible))
    short = bool(SHORT_RE.search(visible))
    if long and not short:
        direction = "LONG (заява автора)"
    elif short and not long:
        direction = "SHORT (заява автора)"
    else:
        direction = "НЕВІДОМО"
    notes = []
    if otc:
        notes.append("OTC/бінарні опціони: не переносити сигнал на BTC/ETH/SOL")
    if marketing:
        notes.append("Є маркетингові/копітрейдинг-заяви: потрібна незалежна перевірка")
    if not pairs:
        notes.append("У доступному описі немає чіткої криптовалютної пари")
    if not excerpt:
        notes.append("Повний зміст відео не підтверджений субтитрами")
    # Only excerpt, title and description are observed. Do not invent what
    # happened visually during the video or imply that a live trade was checked.
    mentioned_instruments = list(dict.fromkeys(
        re.sub(r"\\s+", "", x.upper()).replace("_", "/").replace("-", "/")
        for x in INSTRUMENT_RE.findall(visible)
    ))[:10]
    timeframes = list(dict.fromkeys(x.upper() for x in TIMEFRAME_RE.findall(visible)))[:6]
    indicators = list(dict.fromkeys(x.upper() for x in INDICATOR_RE.findall(visible)))[:8]
    if mentioned_instruments:
        notes.append("Назви інструментів виявлено у тексті; їхню ціну та угоди не перевірено")
    evidence_excerpt = normalize(excerpt or "")[:350]
    return {
        "mentioned_instruments": mentioned_instruments,
        "mentioned_timeframes": timeframes,
        "mentioned_indicators": indicators,
        "content_excerpt": evidence_excerpt,
        "what_jev_can_use": "Лише підтверджені цитати, згадані пари та індикатори; не копіювати сигнали.",
        "instrument": "OTC / binary" if otc else ("Криптовалюта (згадана)" if pairs else "Не визначено"),
        "pairs": pairs[:5],
        "direction_claim": direction,
        "promotion_flag": marketing,
        "otc_flag": otc,
        "evidence": "метадані + доступні субтитри" if excerpt else "назва та опис (без перевіреного відеотексту)",
        "notes": notes,
        "verdict": "ЛИШЕ КОНТЕКСТ — НЕ ТОРГОВИЙ СИГНАЛ",
    }

def collect(channel: dict) -> dict:
    result = dict(channel, status="unverified", videos=[], reviewed=0)
    if not channel["confirmed"]:
        result["status"] = "need_channel_url"
        return result
    options = {
        "quiet": True, "no_warnings": True, "ignoreerrors": True,
        "extract_flat": True, "skip_download": True, "playlistend": 8,
        "socket_timeout": 17, "retries": 1,
    }
    try:
        with YoutubeDL(options) as ydl:
            playlist = ydl.extract_info(channel["url"], download=False) or {}
        raw = [x for x in (playlist.get("entries") or []) if x]
        ids = []
        for item in raw:
            vid = item.get("id")
            if vid and re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) and vid not in ids:
                ids.append(vid)
        result["status"] = "ok" if ids else "empty_or_unavailable"
        for i, vid in enumerate(ids[:8]):
            item = next((x for x in raw if x.get("id") == vid), {})
            details = {}
            if i < 2:
                try:
                    with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                                    "socket_timeout": 17, "retries": 1}) as ydl:
                        details = ydl.extract_info("https://www.youtube.com/watch?v=" + vid, download=False) or {}
                except Exception:
                    details = {}
            title = normalize(details.get("title") or item.get("title") or "Без назви")
            description = normalize(details.get("description") or item.get("description") or "")
            # Do not attribute unrelated channel or old entertainment videos as trade analysis.
            if not TRADING_RE.search(title):
                continue
            excerpt = caption_excerpt(details) if details else ""
            date = details.get("upload_date") or item.get("upload_date") or ""
            verdict = classify(title, description, excerpt)
            result["videos"].append({
                "id": vid, "title": title,
                "url": "https://www.youtube.com/watch?v=" + vid,
                "upload_date": date if re.fullmatch(r"\d{8}", str(date)) else None,
                "analysis": verdict,
            })
            if details:
                result["reviewed"] += 1
    except Exception as exc:
        result["status"] = "source_unavailable"
        result["error"] = normalize(str(exc))[:180]
    # A verified public video example is safer than inventing a channel catalogue.
    if not result["videos"] and channel["id"] in VERIFIED_EXAMPLES:
        vid, title = VERIFIED_EXAMPLES[channel["id"]]
        result["videos"].append({
            "id": vid, "title": title,
            "url": "https://www.youtube.com/watch?v=" + vid,
            "upload_date": None,
            "analysis": classify(title),
            "sample_only": True,
        })
        result["status"] = "example_only"
    elif not result["videos"] and result["status"] == "ok":
        result["status"] = "no_relevant_videos"
    return result

def main():
    result = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "educational_video_context",
        "channels": [],
        "final_signal": "SKIP",
        "reason": "Відео не є незалежно перевіреними ринковими сигналами. Немає підтвердження котируваннями, часом входу та результатами.",
        "method": "Збір торгових фактів із назв, описів та доступних субтитрів опублікованих відео — не цілодобовий нагляд за LIVE.",
        "automatic_orders": False,
    }
    for channel in CHANNELS:
        row = collect(channel)
        result["channels"].append(row)
        print(f'{channel["name"]}: {row["status"]}, відео: {len(row["videos"])}')
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Saved", OUTPUT)

if __name__ == "__main__":
    main()

"""Read-only per-instrument analysis cards for CryptoMyshka LIVE.

The module never fetches imaginary broker prices or transforms a still frame
into a verified fill. Card facts come solely from timestamped AI observations.
JEV notes are a structured explanation of that limited evidence, not a
separately executed LLM analysis unless the observation explicitly says so.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "data" / "pair_reports.json"

PAIR = re.compile(r"^[A-Z0-9]{2,12}(?:[/_-][A-Z0-9]{2,12})?(?:\s+OTC)?$")
LEVEL = re.compile(r"^-?\d{1,10}(?:\.\d{1,9})?$")
KNOWN_TREND = {"uptrend", "downtrend", "sideways", "unknown"}
KNOWN_VOLATILITY = {"high", "normal", "low", "unknown"}
KNOWN_SENTIMENT = {"bullish", "bearish", "neutral", "unknown"}
KNOWN_VOLUME = {"high", "normal", "low", "unknown"}
KNOWN_CONFIDENCE = {"low", "medium"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def text(value: object, limit: int = 600) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def get_time(value: object) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def instrument(value: object) -> str | None:
    """Preserve the actual instrument: e.g. AUD/CNY OTC is NOT crypto."""
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"\s+", " ", value.strip().upper())
    normalized = normalized.replace("-", "/").replace("_", "/")
    if len(normalized) > 29 or not PAIR.fullmatch(normalized):
        return None
    return normalized


def levels(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    found = []
    for entry in value[:5]:
        if isinstance(entry, bool):
            continue
        number = str(entry).strip()
        if LEVEL.fullmatch(number) and number not in found:
            found.append(number)
    return found[:3]


def enum(value: object, allowed: set[str]) -> str:
    key = text(value, 32).lower()
    return key if key in allowed else "unknown"


def add_jev_notes(chart: dict, limitations: list[str]) -> dict:
    """Honest rule-based JEV scaffold. NEVER present as LLM if no second call."""
    trend = enum(chart.get("trend"), KNOWN_TREND)
    sentiment = enum(chart.get("sentiment"), KNOWN_SENTIMENT)
    supports = levels(chart.get("support_levels"))
    resistances = levels(chart.get("resistance_levels"))
    why = text(chart.get("trend_reason"), 420)
    if not why:
        why = "Наявних перевірених ознак на кадрі замало, щоб пояснити напрямок."
    trend_text = {
        "downtrend": "На доступному кадрі розпізнано спадний рух; це ще не перевірений тренд ринку.",
        "uptrend": "На доступному кадрі розпізнано висхідний рух; потрібне підтвердження послідовністю свічок.",
        "sideways": "На доступному кадрі рух схожий на боковик; напрямок входу не підтверджено.",
        "unknown": "Напрямок не вдалося визначити за кадром.",
    }[trend]
    level_text = (
        "Можливі рівні, прочитані з кадру: "
        + (", ".join("підтримка " + v for v in supports) if supports else "підтримка невідома")
        + "; " + (", ".join("опір " + v for v in resistances) if resistances else "опір невідомий")
        + ". Ці рівні не перевірені котируваннями."
    )
    if trend == "downtrend" and sentiment == "bearish":
        watch = "Шукати незалежне підтвердження рівнів і продавців; без нього краще спостерігати."
    elif trend == "uptrend" and sentiment == "bullish":
        watch = "Шукати підтвердження покупців на наступних свічках і незалежних котируваннях."
    else:
        watch = "Почекати, поки напрямок, рівні й ліквідність стануть зрозумілішими."
    return {
        "engine": "structured_frame_explanation_not_separate_LLM",
        "status": "preliminary",
        "why": why + " " + trend_text,
        "key_levels": level_text,
        "what_to_do": "WAIT / OBSERVE",
        "watch_next": watch,
        "not_verified": limitations,
    }


def build(snapshot: dict, now: datetime | None = None) -> dict:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("current time must be timezone aware")
    current = current.astimezone(timezone.utc)
    cutoff = current - timedelta(hours=2)
    groups: dict[str, list[dict]] = {}
    for row in snapshot.get("observations") or []:
        if not isinstance(row, dict):
            continue
        ts = get_time(row.get("observed_at"))
        if ts is None or ts < cutoff or ts > current + timedelta(minutes=2):
            continue
        obs = row.get("observation")
        if not isinstance(obs, dict):
            continue
        pair = instrument(obs.get("asset"))
        if not pair:
            continue
        groups.setdefault(pair, []).append(row)
    reports = []
    for pair, rows in groups.items():
        rows.sort(key=lambda e: get_time(e.get("observed_at")) or cutoff, reverse=True)
        latest = rows[0]
        seen = latest["observation"]
        chart = seen.get("chart")
        if not isinstance(chart, dict):
            chart = {}
        action = text(seen.get("action"), 40)
        if action not in {"claimed_entry", "claimed_exit", "commentary", "unknown"}:
            action = "unknown"
        market_type = "OTC (брокерські котирування)" if pair.endswith(" OTC") else (
            "Криптовалюта (назва на кадрі, не біржова верифікація)" if
            any(x in pair for x in ("BTC", "ETH", "SOL", "XRP", "USDT", "BNB")) else
            "Форекс/інший інструмент (за назвою на кадрі)"
        )
        trend = enum(chart.get("trend"), KNOWN_TREND)
        confidence = enum(seen.get("confidence"), KNOWN_CONFIDENCE)
        volatility = enum(chart.get("volatility"), KNOWN_VOLATILITY)
        volume = enum(chart.get("volume"), KNOWN_VOLUME)
        sentiment = enum(chart.get("sentiment"), KNOWN_SENTIMENT)
        limitations = [
            "Сигнал і результати трейдера не перевірені незалежними котируваннями",
            "Один або кілька кадрів не відображають повний рух або виконання ордерів",
        ]
        if pair.endswith(" OTC"):
            limitations.append("OTC-котирування можуть відрізнятися між платформами; незалежна ціна не підтверджена")
        if volume == "unknown":
            limitations.append("Дані обсягу на кадрі невідомі")
        if trend == "unknown":
            limitations.append("Тренд за кадром не визначено")
        report = {
            "pair": pair, "instrument_type": market_type,
            "observed_at": latest.get("observed_at"),
            "sources_count": len({x.get("channel_id") for x in rows}),
            "observations_count": len(rows),
            "channel": text(latest.get("channel_name"), 100),
            "video_url": latest.get("url") if str(latest.get("url") or "").startswith("https://www.youtube.com/") else None,
            "confidence": confidence, "trend": trend,
            "volatility": volatility, "volume": volume, "sentiment": sentiment,
            "support_levels": levels(chart.get("support_levels")),
            "resistance_levels": levels(chart.get("resistance_levels")),
            "price_action": text(chart.get("price_action"), 600) or None,
            "trend_reason": text(chart.get("trend_reason"), 420) or None,
            "visual_evidence": text(seen.get("visual_evidence"), 600) or None,
            "claimed_action": action,
            "claimed_direction": text(seen.get("direction"), 40) or None,
            "speaker_claim": text(seen.get("speaker_claim"), 200) or None,
            "limitations": limitations,
            "independently_verified": False,
            "trade_status": "NO_AUTO_TRADE",
            "jev": (
                dict(
                    (seen["jev"] if isinstance(seen.get("jev"), dict) else {}),
                    limitations=limitations,
                ) if isinstance(seen.get("jev"), dict)
                    and seen["jev"].get("status") == "model"
                else add_jev_notes(chart, limitations)
            ),
        }
        reports.append(report)
    reports.sort(key=lambda e: (e["observed_at"], e["pair"]), reverse=True)
    return {
        "version": 1,
        "updated_at": current.isoformat(),
        "source": "youtube_live.json / timestamped screenshot observations",
        "analysis_mode": "limited_single_frame_evidence",
        "status": "observations_available" if reports else "waiting_for_readable_live_chart",
        "reports": reports[:30],
        "independently_verified": False,
        "automatic_trading": False,
        "disclaimer": "Не торгові рекомендації; JEV роз'яснення є структурованою інтерпретацією AI-кадру, а не незалежним LLM-висновком.",
    }


def save_payload(payload: dict) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(OUTPUT)


def update_from_live(snapshot: dict) -> dict:
    payload = build(snapshot)
    save_payload(payload)
    return payload


if __name__ == "__main__":
    src = HERE / "data" / "youtube_live.json"
    snapshot = json.loads(src.read_text(encoding="utf-8"))
    payload = update_from_live(snapshot)
    print(json.dumps({"status": payload["status"], "pairs": len(payload["reports"])}))

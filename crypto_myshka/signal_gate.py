"""Fail-closed JEV review gate. A YouTube frame is never an independent price feed.

The gate cannot execute trades. Passing means a human MAY REVIEW the evidence,
not that the next candle is predictable or an order should be placed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

MIN_INDEPENDENT_PRICE_FEEDS = 2
MIN_OUT_OF_SAMPLE_RESULTS = 30
MAX_AGE_SECONDS = 90
EDGE_SAFETY_MARGIN_PCT = 0.03


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _age_seconds(value, now):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
        return (now - dt.astimezone(timezone.utc)).total_seconds()
    except ValueError:
        return None


def evaluate(report: dict, now: datetime | None = None) -> dict:
    """Explain every failed check; fail closed on missing/ambiguous evidence.

    Independent feed proof is explicit in verification.price_feeds, not in
    number of YouTube channels.  A feed entry needs a verified provider ID and
    fresh checked_at timestamp. Indicators must be separately verified.
    """
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must include timezone")
    current = current.astimezone(timezone.utc)
    reasons = []
    pair = str(report.get("pair") or "").strip().upper()
    if not pair:
        reasons.append("Немає підтвердженої торгової пари")
    if pair.endswith(" OTC") or "OTC" in str(report.get("instrument_type") or "").upper():
        reasons.append("OTC: незалежні біржові котирування не підтверджують ціну брокера")

    age = _age_seconds(report.get("observed_at"), current)
    if age is None or age < -5 or age > MAX_AGE_SECONDS:
        reasons.append("Графік застарілий або час спостереження невідомий")

    verification = report.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    feeds = verification.get("price_feeds")
    feeds = feeds if isinstance(feeds, list) else []
    verified = set()
    for feed in feeds:
        if not isinstance(feed, dict) or feed.get("verified") is not True:
            continue
        provider = str(feed.get("provider") or "").strip().lower()
        if not provider or provider in {"youtube", "screenshot", "stream", "broker_otc"}:
            continue
        feed_age = _age_seconds(feed.get("checked_at"), current)
        if feed_age is not None and -5 <= feed_age <= MAX_AGE_SECONDS:
            verified.add(provider)
    if len(verified) < MIN_INDEPENDENT_PRICE_FEEDS:
        reasons.append("Менше двох незалежних актуальних джерел котирувань")
    if verification.get("price_consistent") is not True:
        reasons.append("Ціни незалежних джерел не звірені між собою")

    indicators = verification.get("indicators")
    indicators = indicators if isinstance(indicators, dict) else {}
    if not all(indicators.get(k) is True for k in ("rsi", "ema", "structure")):
        reasons.append("RSI, EMA та структура ринку не підтверджені")
    trend = str(report.get("trend") or "").lower()
    sentiment = str(report.get("sentiment") or "").lower()
    if (trend, sentiment) not in {("uptrend", "bullish"), ("downtrend", "bearish")}:
        reasons.append("Тренд і ринковий настрій не дають узгодженого напрямку")
    if report.get("volume") in ("unknown", None, ""):
        reasons.append("Немає підтверджених даних про обсяг")
    if report.get("confidence") not in ("medium", "high"):
        reasons.append("Недостатня впевненість у вихідних спостереженнях")
    jev = report.get("jev")
    if not isinstance(jev, dict) or jev.get("status") != "model":
        reasons.append("Немає окремого успішного аналізу JEV")
    if verification.get("conflicting_sources") is not False:
        reasons.append("Суперечності між джерелами не виключені")

    samples = _number(verification.get("out_of_sample_results"))
    if samples is None or samples < MIN_OUT_OF_SAMPLE_RESULTS:
        reasons.append("Менше 30 перевірених результатів поза навчальною вибіркою")
    expected = _number(verification.get("expected_move_pct"))
    fees = _number(verification.get("round_trip_cost_pct"))
    slippage = _number(verification.get("slippage_pct"))
    if (expected is None or fees is None or slippage is None or
            expected <= 0 or fees < 0 or slippage < 0 or
            expected <= fees + slippage + EDGE_SAFETY_MARGIN_PCT):
        reasons.append("Очікуваний рух не доведено вищим за витрати та запас безпеки")

    passed = not reasons
    return {
        "decision": "REVIEW_ONLY" if passed else "NO_SIGNAL",
        "eligible_for_human_review": passed,
        "automatic_trading": False,
        "reasons": reasons,
        "verified_price_feeds": len(verified),
        "required_price_feeds": MIN_INDEPENDENT_PRICE_FEEDS,
        "safety_margin_pct": EDGE_SAFETY_MARGIN_PCT,
        "note": ("Навіть проходження фільтра не гарантує прибутку і не дозволяє "
                 "автоматичну угоду. Рішення потребує перевірки людиною."),
    }

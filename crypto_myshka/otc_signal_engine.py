"""Fail-closed OTC paper-signal engine for Crypto Myshka.

This module does NOT place trades and does not fabricate prices.
A caller must provide candles from a verified, permitted data source.
Expected candle shape: {"time": ISO-8601 or epoch seconds, "open": n,
"high": n, "low": n, "close": n}. All price fields must be finite and positive.

Signals are heuristic research labels, not probabilities or guarantees.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path(os.getenv("MYSHKA_OTC_DB", "crypto_myshka/data/otc_signals.sqlite3"))
HORIZONS_SECONDS = (15, 30, 60)


class FeedError(RuntimeError):
    """Raised when the caller's price feed is missing or invalid."""


def _timestamp(value: Any) -> float:
    if isinstance(value, bool):
        raise FeedError("Invalid candle timestamp")
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        # Accept Unix seconds or milliseconds.
        stamp = float(value)
        return stamp / 1000 if stamp > 10_000_000_000 else stamp
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise FeedError("Timestamp must include a timezone")
            return parsed.timestamp()
        except ValueError as exc:
            raise FeedError("Unparseable candle timestamp") from exc
    raise FeedError("Missing candle timestamp")


def validate_candles(raw: Iterable[dict[str, Any]], *, max_age_seconds: int = 90) -> list[dict[str, float]]:
    if isinstance(raw, (str, bytes, dict)) or raw is None:
        raise FeedError("Feed did not return a candle list")
    candles = []
    now = time.time()
    try:
        items = list(raw)
    except TypeError as exc:
        raise FeedError("Feed did not return iterable candles") from exc
    for item in items:
        if not isinstance(item, dict):
            raise FeedError("Malformed candle")
        stamp = _timestamp(item.get("time", item.get("timestamp")))
        candle = {"time": stamp}
        for key in ("open", "high", "low", "close"):
            value = item.get(key)
            if isinstance(value, bool):
                raise FeedError(f"Invalid {key} value")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise FeedError(f"Missing {key} value") from exc
            if not math.isfinite(number) or number <= 0:
                raise FeedError(f"Invalid {key} value")
            candle[key] = number
        if candle["high"] < max(candle["open"], candle["close"], candle["low"]):
            raise FeedError("Inconsistent candle high")
        if candle["low"] > min(candle["open"], candle["close"], candle["high"]):
            raise FeedError("Inconsistent candle low")
        candles.append(candle)
    candles.sort(key=lambda x: x["time"])
    if len(candles) < 20:
        raise FeedError("Need at least 20 real candles; no signal generated")
    if len({c["time"] for c in candles}) != len(candles):
        raise FeedError("Duplicate candle timestamps")
    age = now - candles[-1]["time"]
    if age < -5 or age > max_age_seconds:
        raise FeedError(f"Stale/future feed ({age:.1f}s); no signal generated")
    if any(candles[i]["time"] <= candles[i - 1]["time"] for i in range(1, len(candles))):
        raise FeedError("Candle timestamps are not increasing")
    return candles


def _ema(values: list[float], period: int) -> float:
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def evaluate(candles: Iterable[dict[str, Any]], symbol: str) -> dict[str, Any]:
    """Return a single research label using only the provided validated candles."""
    bars = validate_candles(candles)
    closes = [bar["close"] for bar in bars]
    fast = _ema(closes[-20:], 5)
    slow = _ema(closes[-20:], 13)
    momentum = (closes[-1] - closes[-4]) / closes[-4] if closes[-4] else 0
    # Require alignment of trend and short momentum; otherwise abstain.
    direction = "UP" if fast > slow and momentum > 0 else "DOWN" if fast < slow and momentum < 0 else "SKIP"
    strength = abs(fast - slow) / closes[-1] if closes[-1] else 0
    if strength < 0.00003:
        direction = "SKIP"
    return {
        "symbol": str(symbol),
        "direction": direction,
        "entry_price": closes[-1],
        "candle_time": bars[-1]["time"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "horizons_seconds": list(HORIZONS_SECONDS),
        "method": "EMA5/EMA13 + 3-candle momentum; heuristic, not probability",
        "candle_count": len(bars),
        "trend_strength": strength,
    }


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS otc_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            candle_time REAL NOT NULL,
            horizon_seconds INTEGER NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('UP','DOWN','SKIP')),
            entry_price REAL NOT NULL,
            created_at TEXT NOT NULL,
            due_at REAL NOT NULL,
            exit_price REAL,
            outcome TEXT CHECK(outcome IN ('WIN','LOSS','FLAT') OR outcome IS NULL),
            source TEXT NOT NULL,
            UNIQUE(symbol, candle_time, horizon_seconds)
        )
    """)
    conn.commit()
    return conn


def record_signal(signal: dict[str, Any], source: str) -> int:
    """Record one result-check row per horizon; duplicate candle rows are ignored."""
    if not source or source.lower() in {"mock", "fake", "sample", "synthetic"}:
        raise FeedError("A named real data source is required")
    with _connect() as conn:
        for horizon in HORIZONS_SECONDS:
            conn.execute(
                """INSERT OR IGNORE INTO otc_signals
                (symbol,candle_time,horizon_seconds,direction,entry_price,created_at,due_at,source)
                VALUES (?,?,?,?,?,?,?,?)""",
                (signal["symbol"], signal["candle_time"], horizon, signal["direction"],
                 signal["entry_price"], signal["created_at"], time.time() + horizon, source),
            )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM otc_signals WHERE symbol=? AND candle_time=? AND horizon_seconds=15",
            (signal["symbol"], signal["candle_time"]),
        ).fetchone()
        return int(row["id"])


def settle_due(get_current_price) -> int:
    """Resolve due paper signals using a fresh source price; callback returns (price, source, timestamp).

    If the callback fails or the source is stale, rows remain pending instead of being guessed.
    """
    now = time.time()
    settled = 0
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM otc_signals
            WHERE outcome IS NULL AND direction IN ('UP','DOWN') AND due_at <= ?""", (now,)
        ).fetchall()
        for row in rows:
            try:
                price, source, stamp = get_current_price(row["symbol"])
                price, stamp = float(price), float(stamp)
                if not math.isfinite(price) or price <= 0 or not source or now - stamp > 10 or stamp > now + 5:
                    continue
                if str(source) != row["source"]:
                    # Entry and exit must use the same quote source.
                    continue
                if row["direction"] == "UP":
                    outcome = "WIN" if price > row["entry_price"] else "LOSS" if price < row["entry_price"] else "FLAT"
                else:
                    outcome = "WIN" if price < row["entry_price"] else "LOSS" if price > row["entry_price"] else "FLAT"
                conn.execute("UPDATE otc_signals SET exit_price=?, outcome=? WHERE id=? AND outcome IS NULL",
                             (price, outcome, row["id"]))
                settled += 1
            except (FeedError, TypeError, ValueError, KeyError, TimeoutError, OSError):
                continue
        conn.commit()
    return settled


def stats() -> dict[str, Any]:
    with _connect() as conn:
        rows = conn.execute("""
            SELECT horizon_seconds,
                   COUNT(*) AS total,
                   SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN outcome='LOSS' THEN 1 ELSE 0 END) AS losses,
                   SUM(CASE WHEN outcome='FLAT' THEN 1 ELSE 0 END) AS flats,
                   SUM(CASE WHEN outcome IS NULL AND direction IN ('UP','DOWN') THEN 1 ELSE 0 END) AS pending
            FROM otc_signals GROUP BY horizon_seconds ORDER BY horizon_seconds
        """).fetchall()
    result = {}
    for row in rows:
        wins, losses = row["wins"] or 0, row["losses"] or 0
        decided = wins + losses
        result[str(row["horizon_seconds"])] = {
            "total": row["total"], "wins": wins, "losses": losses,
            "flats": row["flats"] or 0, "pending": row["pending"] or 0,
            "win_rate_pct": round(100 * wins / decided, 2) if decided else None,
        }
    return result


def history(limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM otc_signals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


def main() -> None:
    # Intentionally does not fetch from an undocumented endpoint. A verified feed
    # adapter must be implemented and explicitly wired in before polling is enabled.
    print(json.dumps({
        "service": "Crypto Myshka OTC paper-signal engine",
        "status": "WAITING_FOR_VERIFIED_FEED_ADAPTER",
        "trading": "DISABLED",
        "required": "Implement a permitted live OTC quote adapter and wire it into the existing Telegram bot.",
        "database": str(DB_PATH),
        "horizons_seconds": list(HORIZONS_SECONDS),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

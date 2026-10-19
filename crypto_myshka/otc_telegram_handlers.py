"""Telegram UI handlers for the OTC paper-signal engine.

Register these handlers on the EXISTING Telegram Application; do not start a
second getUpdates poller with the same bot token. No real trades are placed.
OTC signal generation intentionally remains disabled until a permitted,
verified Pocket Option OTC quote adapter is wired in.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from html import escape
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from crypto_myshka import otc_signal_engine as engine

CALLBACKS = {
    "otc:signal": "signal",
    "otc:history": "history",
    "otc:stats": "stats",
    "otc:status": "status",
}


def _source_status() -> tuple[bool, str]:
    """Fail closed: an environment label alone cannot verify an OTC feed."""
    verified = os.getenv("MYSHKA_OTC_FEED_VERIFIED", "").strip().lower() == "true"
    adapter = os.getenv("MYSHKA_OTC_FEED_ADAPTER", "").strip()
    if not verified or not adapter:
        return False, "НЕ ПІДТВЕРДЖЕНО — OTC-адаптер не підключений"
    # The actual adapter module must be implemented and reviewed separately.
    return False, f"НЕ АКТИВОВАНО — адаптер «{escape(adapter)}» ще не зареєстрований у коді"


def _menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Сигнал", callback_data="otc:signal")],
        [InlineKeyboardButton("🧾 Історія", callback_data="otc:history"),
         InlineKeyboardButton("📊 Статистика", callback_data="otc:stats")],
        [InlineKeyboardButton("🔌 Статус джерела", callback_data="otc:status")],
    ])


async def otc_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "🐭 Crypto Myshka · OTC PAPER\n"
            "Тільки тестові сигнали — без реальних угод.\n"
            "Джерело Pocket Option OTC має бути підтверджене перед генерацією сигналів.",
            reply_markup=_menu(),
        )


async def _show(update: Update, action: str) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    if action == "signal":
        active, status = _source_status()
        if not active:
            text = (
                "⛔ Сигнал не створено.\n"
                "Причина: немає підтвердженого потоку котирувань Pocket Option OTC.\n"
                "Звичайні біржові ціни не видаються за OTC.\n\n"
                f"Статус: {status}"
            )
        else:
            # Deliberately fail closed until a reviewed adapter is actually wired.
            text = "⛔ Адаптер не зареєстрований у коді. Сигнал не створено."
    elif action == "history":
        rows = engine.history(10)
        if not rows:
            text = "🧾 Історія порожня — тестових OTC-сигналів ще немає."
        else:
            lines = ["🧾 Останні тестові записи:"]
            for row in rows:
                stamp = datetime.fromtimestamp(row["candle_time"], timezone.utc).strftime("%m-%d %H:%M:%S UTC")
                outcome = row["outcome"] or "ОЧІКУЄ"
                lines.append(
                    f"#{row['id']} {escape(row['symbol'])} · {row['horizon_seconds']}с · "
                    f"{row['direction']} · {outcome} · {stamp}"
                )
            text = "\n".join(lines)
    elif action == "stats":
        values = engine.stats()
        lines = ["📊 Статистика тестів (це не прогноз і не гарантія):"]
        if not values:
            lines.append("Даних поки немає.")
        for horizon in ("15", "30", "60"):
            s = values.get(horizon)
            if not s:
                lines.append(f"{horizon}с: немає записів")
                continue
            rate = "—" if s["win_rate_pct"] is None else f'{s["win_rate_pct"]:.2f}%'
            lines.append(
                f'{horizon}с: {s["wins"]} WIN / {s["losses"]} LOSS / {s["flats"]} FLAT; '
                f'очікують: {s["pending"]}; win rate: {rate}'
            )
        text = "\n".join(lines)
    else:
        active, status = _source_status()
        text = (
            "🔌 Статус Crypto Myshka OTC\n"
            f"Джерело: {status}\n"
            f"Торгівля: ВИМКНЕНО\n"
            f"Час сервера: {datetime.now(timezone.utc).isoformat()}\n"
            f"База: {engine.DB_PATH}"
        )
    await query.edit_message_text(text, reply_markup=_menu())


async def _signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show(update, "signal")


async def _history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show(update, "history")


async def _stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show(update, "stats")


async def _status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _show(update, "status")


async def _callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query and query.data in CALLBACKS:
        await _show(update, CALLBACKS[query.data])


def register_otc_handlers(application: Application) -> None:
    """Attach OTC commands/menu to an existing python-telegram-bot Application."""
    application.add_handler(CommandHandler("otc", otc_command))
    application.add_handler(CallbackQueryHandler(_callback, pattern=r"^otc:(signal|history|stats|status)$"))

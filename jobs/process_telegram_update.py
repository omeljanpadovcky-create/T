import json
import os
from pathlib import Path

from callbacks import (
    APPLICATIONS_PATH,
    EDITING_PATH,
    STATUSES_PATH,
    handle_callback,
    handle_message,
    load_json,
    save_json,
)

ROOT = Path(__file__).resolve().parent
PROCESSED_PATH = ROOT / "processed_telegram_updates.json"


def main():
    raw = os.environ.get("MYSHKA_TELEGRAM_UPDATE_JSON", "").strip()
    if not raw:
        raise RuntimeError("Missing MYSHKA_TELEGRAM_UPDATE_JSON.")
    update = json.loads(raw)
    update_id = int(update["update_id"])
    processed = set(load_json(PROCESSED_PATH, []))
    if update_id in processed:
        print(f"Telegram update {update_id} already processed; skipping duplicate.")
        return

    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not chat_id or not token:
        raise RuntimeError("Missing Telegram credentials.")

    applications = load_json(APPLICATIONS_PATH, {})
    statuses = load_json(STATUSES_PATH, {})
    editing = load_json(EDITING_PATH, {})

    if update.get("callback_query"):
        handle_callback(update, applications, statuses, chat_id, editing)
    elif update.get("message"):
        handle_message(update, applications, statuses, chat_id, editing)
    else:
        print(f"Telegram update {update_id} has no supported message or callback.")

    processed.add(update_id)
    save_json(STATUSES_PATH, statuses)
    save_json(EDITING_PATH, editing)
    save_json(PROCESSED_PATH, sorted(processed)[-5000:])
    print(f"Telegram webhook update {update_id} processed successfully.")


if __name__ == "__main__":
    main()

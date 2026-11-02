import html
import json
import os
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
APPLICATIONS_PATH = ROOT / "applications.json"
STATUSES_PATH = ROOT / "statuses.json"
OFFSET_PATH = ROOT / "update_offset.json"
EDITING_PATH = ROOT / "editing.json"
TIMEOUT = 20


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def api(method, payload):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    response = requests.post(
        f"https://api.telegram.org/bot{token}/{method}",
        json=payload, timeout=TIMEOUT
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data}")
    return data.get("result")


def safe(value):
    return html.escape(str(value or ""))


def answer_callback(query_id, text):
    if not query_id:
        return
    try:
        api("answerCallbackQuery", {"callback_query_id": query_id, "text": text})
    except requests.RequestException as exc:
        # Telegram expires callback query IDs after a short time. The action itself can still be processed.
        print(f"Could not show callback toast (possibly expired): {exc}")


def job_message(job, state):
    status = {
        "new": "Нова", "confirmed": "Підтверджена",
        "skipped": "Пропущена", "applied": "Подана"
    }.get(state.get("status", "new"), state.get("status", "Нова"))
    return (
        f"🐭 <b>ТРЕЙДМИШКА · {int(job.get('score') or 0)}/100</b>\n"
        f"💼 <b>{safe(job.get('title'))}</b>\n"
        f"🏢 {safe(job.get('company') or 'Компанія не вказана')}\n"
        f"🌍 {safe(job.get('location') or 'Remote')}\n"
        f"📌 {safe(job.get('source'))}\n"
        f"🟢 <b>Статус: {status}</b>"
    )


def cover_letter(job):
    title = job.get("title") or "the role"
    company = job.get("company") or "your team"
    description = (job.get("description") or "").lower()
    skills = []
    for skill in ["Blender", "3D modeling", "low-poly modeling", "game assets",
                  "Photoshop", "illustration", "character design", "environment art"]:
        if skill.lower() in description:
            skills.append(skill)
    skill_line = ", ".join(skills[:4]) if skills else "Blender and visual design"
    return (
        f"Hello {company} team,\n\n"
        f"I would like to apply for the {title} position. "
        "I am a designer from Ukraine with practical experience in visual design and creative projects. "
        f"My work includes {skill_line}. I use Blender and design tools to create clear, detailed visuals.\n\n"
        "I am motivated to learn, follow feedback and improve my work. "
        "I would be happy to show you my portfolio and discuss how I can help your team.\n\n"
        "Thank you for your time.\n"
        "Best regards,\n"
        "Omelyan Padovsky\n"
        "[Portfolio link]"
    )


def handle_callback(update, applications, statuses, allowed_chat, editing):
    query = update.get("callback_query") or {}
    message = query.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    if chat_id != str(allowed_chat):
        answer_callback(query.get("id"), "Немає доступу")
        return False

    parts = str(query.get("data") or "").split("|", 1)
    if len(parts) != 2:
        answer_callback(query.get("id"), "Невідома дія")
        return False
    action, short_id = parts
    job = applications.get(short_id)
    if not job:
        answer_callback(query.get("id"), "Вакансію не знайдено")
        return False
    state = statuses.setdefault(short_id, {"status": "new"})

    if action == "confirm":
        state["status"] = "confirmed"
        answer_callback(query.get("id"), "Вакансію підтверджено")
        keyboard = {"inline_keyboard": [
            [{"text": "🔗 Відкрити вакансію", "url": job["url"]}],
            [
                {"text": "✉️ Чернетка листа", "callback_data": f"letter|{short_id}"},
                {"text": "✏️ Редагувати лист", "callback_data": f"edit|{short_id}"}
            ],
            [{"text": "📨 Позначити поданою", "callback_data": f"applied|{short_id}"}],
            [{"text": "⏭ Пропустити", "callback_data": f"skip|{short_id}"}]
        ]}
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message.get("message_id"),
            "text": job_message(job, state), "parse_mode": "HTML", "reply_markup": keyboard,
            "disable_web_page_preview": True
        })
    elif action == "skip":
        state["status"] = "skipped"
        answer_callback(query.get("id"), "Вакансію пропущено")
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message.get("message_id"),
            "text": job_message(job), "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": []},
            "disable_web_page_preview": True
        })
    elif action == "letter":
        answer_callback(query.get("id"), "Готую чернетку")
        text = "✉️ <b>ЧЕРНЕТКА СУПРОВІДНОГО ЛИСТА</b>\n"
        text += f"Вакансія: <b>{safe(job.get('title'))}</b> · {safe(job.get('company'))}\n\n"
        text += f"<pre>{safe(state.get('custom_cover_letter') or cover_letter(job))}</pre>\n"
        text += "Перевір текст і додай посилання на портфоліо перед відправленням."
        api("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
        state["letter_created"] = True
    elif action == "edit":
        editing["job_id"] = short_id
        answer_callback(query.get("id"), "Надішли свій текст листа в чат")
        api("sendMessage", {
            "chat_id": chat_id,
            "text": "✏️ Надішли нову версію супровідного листа одним повідомленням. Я збережу її для цієї вакансії. Для скасування напиши /cancel."
        })
    elif action == "applied":
        state["status"] = "applied"
        answer_callback(query.get("id"), "Статус оновлено: подано")
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message.get("message_id"),
            "text": job_message(job), "parse_mode": "HTML",
            "disable_web_page_preview": True
        })
    else:
        api("answerCallbackQuery", {"callback_query_id": query.get("id"), "text": "Невідома дія"})
        return False
    return True


def handle_message(update, applications, statuses, allowed_chat, editing):
    message = update.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id", ""))
    if chat_id != str(allowed_chat) or not editing.get("job_id"):
        return False
    text = str(message.get("text") or "").strip()
    if not text:
        return False
    if text.lower() == "/cancel":
        editing.clear()
        api("sendMessage", {"chat_id": chat_id, "text": "Редагування скасовано."})
        return True
    short_id = editing.get("job_id")
    job = applications.get(short_id)
    if not job:
        editing.clear()
        api("sendMessage", {"chat_id": chat_id, "text": "Не знайшов вакансію для цього листа. Почни редагування ще раз із картки вакансії."})
        return True
    state = statuses.setdefault(short_id, {"status": "new"})
    state["custom_cover_letter"] = text[:3500]
    state["letter_created"] = True
    editing.clear()
    api("sendMessage", {
        "chat_id": chat_id,
        "text": f"✅ Твій лист для «{job.get('title', 'вакансії')}» збережено. Натисни «Чернетка листа», щоб переглянути його."
    })
    return True


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub Secret.")

    applications = load_json(APPLICATIONS_PATH, {})
    statuses = load_json(STATUSES_PATH, {})
    editing = load_json(EDITING_PATH, {})
    offset = int(load_json(OFFSET_PATH, 0))
    response = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"offset": offset, "timeout": 0, "allowed_updates": '["callback_query","message"]'},
        timeout=TIMEOUT
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram getUpdates failed: " + str(payload))

    updates = payload.get("result", [])
    processed = 0
    for update in updates:
        try:
            if update.get("callback_query"):
                handle_callback(update, applications, statuses, chat_id, editing)
            elif update.get("message"):
                handle_message(update, applications, statuses, chat_id, editing)
            offset = max(offset, int(update.get("update_id", 0)) + 1)
            save_json(STATUSES_PATH, statuses)
            save_json(EDITING_PATH, editing)
            save_json(OFFSET_PATH, offset)
            processed += 1
        except Exception as exc:
            print(f"Callback {update.get('update_id')} failed: {exc}")
            raise
    print(f"Telegram callback poll complete: {len(updates)} updates received, {processed} processed.")
    

if __name__ == "__main__":
    main()

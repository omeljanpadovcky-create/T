import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from application_generator import generate_application, render_application_text

ROOT = Path(__file__).resolve().parent
APPLICATIONS_PATH = ROOT / "applications.json"
STATUSES_PATH = ROOT / "statuses.json"
OFFSET_PATH = ROOT / "update_offset.json"
EDITING_PATH = ROOT / "editing.json"
PROFILE_PATH = ROOT / "profile.json"
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


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def answer_callback(query_id, text):
    if not query_id:
        return
    try:
        api("answerCallbackQuery", {"callback_query_id": query_id, "text": text})
    except requests.RequestException as exc:
        print(f"Could not show callback toast (possibly expired): {exc}")


def load_profile():
    profile = load_json(PROFILE_PATH, {})
    env_fields = {
        "name": "MYSHKA_CANDIDATE_NAME",
        "portfolio_url": "MYSHKA_PORTFOLIO_URL",
        "portfolio_3d_url": "MYSHKA_PORTFOLIO_3D_URL",
        "portfolio_game_art_url": "MYSHKA_PORTFOLIO_GAME_ART_URL",
        "portfolio_design_url": "MYSHKA_PORTFOLIO_DESIGN_URL",
        "portfolio_illustration_url": "MYSHKA_PORTFOLIO_ILLUSTRATION_URL",
        "cv_url": "MYSHKA_CV_URL",
        "contact_email": "MYSHKA_CONTACT_EMAIL",
        "salary_expectation": "MYSHKA_SALARY_EXPECTATION"
    }
    for field, env_name in env_fields.items():
        value = os.environ.get(env_name, "").strip()
        if value:
            profile[field] = value
    return profile


def status_label(status):
    return {
        "new": "Нова",
        "selected": "Відібрана",
        "awaiting_approval": "Пакет очікує твого підтвердження",
        "approved": "Пакет підтверджено — очікує ручної подачі",
        "submitted_user_confirmed": "Ти підтвердив, що заявку відправлено",
        "skipped": "Пропущена"
    }.get(status, status or "Нова")


def job_message(job, state):
    return (
        f"🐭 ТРЕЙДМИШКА · {int(job.get('score') or 0)}/100\n"
        f"💼 {safe(job.get('title'))}\n"
        f"🏢 {safe(job.get('company') or 'Компанія не вказана')}\n"
        f"🌍 {safe(job.get('location') or 'Remote')}\n"
        f"📌 {safe(job.get('source'))}\n"
        f"📍 Статус: {safe(status_label(state.get('status', 'new')))}\\n"
        f"🧠 Висновок Мишки: {safe(job.get('conclusion_uk') or 'Переглянь опис, вимоги до досвіду та англійської. Остаточне рішення — після перевірки сторінки роботодавця.')}"
    )


def package_keyboard(short_id, job):
    rows = []
    if job.get("url"):
        rows.append([{"text": "🔗 Відкрити вакансію", "url": job["url"]}])
    rows.extend([
        [{"text": "❌ НЕ ПІДХОДИТЬ", "callback_data": f"skip|{short_id}"}],
        [{"text": "✅ ПІДХОДИТЬ", "callback_data": f"confirm|{short_id}"}]
    ])
    return {"inline_keyboard": rows}


def approved_keyboard(short_id, job):
    rows = []
    if job.get("url"):
        rows.append([{"text": "🌐 Відкрити форму роботодавця", "url": job["url"]}])
    rows.append([{"text": "📨 Я ВЖЕ ВІДПРАВИВ ЗАЯВКУ", "callback_data": f"applied|{short_id}"}])
    return {"inline_keyboard": rows}


def send_package(chat_id, short_id, job, package):
    text = re.sub(r"</?b>", "", render_application_text(package))
    chunks = []
    while len(text) > 3800:
        cut = text.rfind("\n", 0, 3800)
        if cut < 1000:
            cut = 3800
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    chunks.append(text)
    for index, chunk in enumerate(chunks):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True
        }
        if index == len(chunks) - 1:
            payload["reply_markup"] = package_keyboard(short_id, job)
        api("sendMessage", payload)


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
    if action == "review" and short_id == "pending":
        pending = []
        for item_id, item in applications.items():
            state = statuses.get(item_id, {})
            status = state.get("status", item.get("status", "new"))
            if status in {"new", "selected"} and item.get("url"):
                pending.append((item_id, item, state))
        answer_callback(query.get("id"), f"Знайдено вакансій: {len(pending)}")
        if not pending:
            api("sendMessage", {"chat_id": chat_id, "text": "🐭 Немає вакансій, які очікують перегляду."})
            return True
        for item_id, item, state in pending[:20]:
            api("sendMessage", {
                "chat_id": chat_id,
                "text": job_message(item, state),
                "reply_markup": package_keyboard(item_id, item),
                "disable_web_page_preview": True
            })
        return True

    job = applications.get(short_id)
    if not job:
        answer_callback(query.get("id"), "Вакансію не знайдено")
        return False

    state = statuses.setdefault(short_id, {
        "status": job.get("status", "new"),
        "package_revision": int(job.get("package_revision", 0) or 0)
    })
    current_status = state.get("status", "new")
    allowed_statuses = {
        "confirm": {"new", "selected"},
        "prepare": {"new", "selected"},
        "skip": {"new", "selected", "awaiting_approval"},
        "edit": {"awaiting_approval"},
        "approve": {"awaiting_approval"},
        "applied": {"approved"},
        "letter": {"new", "selected", "awaiting_approval", "approved"}
    }
    if action in allowed_statuses and current_status not in allowed_statuses[action]:
        answer_callback(query.get("id"), "Ця дія недоступна для поточного статусу")
        return False

    if action == "confirm":
        if state.get("status") in ("skipped", "submitted_user_confirmed"):
            answer_callback(query.get("id"), "Цю вакансію вже закрито")
            return False
        state["status"] = "selected"
        answer_callback(query.get("id"), "Вакансію відібрано. Готую пакет наступним кроком.")
        keyboard = {"inline_keyboard": [
            [{"text": "🔗 Відкрити вакансію", "url": job["url"]}],
            [{"text": "🧾 ПІДГОТУВАТИ ПОВНУ ЗАЯВКУ", "callback_data": f"prepare|{short_id}"}],
            [{"text": "⏭ Пропустити", "callback_data": f"skip|{short_id}"}]
        ]}
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message.get("message_id"),
            "text": job_message(job, state), "reply_markup": keyboard,
            "disable_web_page_preview": True
        })

    elif action == "prepare":
        package = generate_application(job, load_profile())
        revision = int(state.get("package_revision", 0)) + 1
        package["revision"] = revision
        state["package_revision"] = revision
        state["status"] = "awaiting_approval"
        state["prepared_at"] = now_iso()
        state.pop("approved_at", None)
        answer_callback(query.get("id"), "Пакет готовий. Перевір його перед підтвердженням.")
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message.get("message_id"),
            "text": job_message(job, state),
            "reply_markup": {"inline_keyboard": [
                [{"text": "🔗 Відкрити вакансію", "url": job["url"]}]
            ]},
            "disable_web_page_preview": True
        })
        send_package(chat_id, short_id, job, package)

    elif action == "approve":
        if not state.get("package_revision") or state.get("status") != "awaiting_approval":
            answer_callback(query.get("id"), "Спочатку підготуй і перевір пакет")
            return False
        state["status"] = "approved"
        state["approved_at"] = now_iso()
        answer_callback(query.get("id"), "Пакет підтверджено. Тепер відкрий сторінку та подай заявку.")
        api("sendMessage", {
            "chat_id": chat_id,
            "text": (
                "✅ ПАКЕТ ПІДТВЕРДЖЕНО\n\n"
                f"{job.get('title', 'Вакансія')} · {job.get('company', 'Компанія')}\n\n"
                "Тепер відкрий сторінку роботодавця, перенеси перевірені тексти у відповідні поля "
                "та самостійно натисни Submit/Send. Я не надсилаю заявку без окремої інтеграції "
                "з поштою або ATS. Після реального відправлення натисни кнопку нижче."
            ),
            "reply_markup": approved_keyboard(short_id, job),
            "disable_web_page_preview": True
        })

    elif action == "skip":
        state["status"] = "skipped"
        state["skipped_at"] = now_iso()
        answer_callback(query.get("id"), "Вакансію пропущено")
        api("editMessageText", {
            "chat_id": chat_id, "message_id": message.get("message_id"),
            "text": job_message(job, state),
            "reply_markup": {"inline_keyboard": []},
            "disable_web_page_preview": True
        })

    elif action == "letter":
        answer_callback(query.get("id"), "Чернетка листа")
        package = generate_application(job, load_profile())
        text = "COVER LETTER\n\n" + package["cover_letter"]
        api("sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})

    elif action == "edit":
        editing["job_id"] = short_id
        editing["field"] = "cover_letter"
        answer_callback(query.get("id"), "Надішли новий текст Cover Letter")
        api("sendMessage", {
            "chat_id": chat_id,
            "text": (
                "✏️ Надішли нову версію Cover Letter одним повідомленням. "
                "Після редагування попереднє підтвердження буде скасовано. "
                "Для скасування напиши /cancel."
            )
        })

    elif action == "applied":
        if state.get("status") != "approved":
            answer_callback(query.get("id"), "Спочатку потрібно підтвердити пакет")
            return False
        state["status"] = "submitted_user_confirmed"
        state["submitted_at"] = now_iso()
        answer_callback(query.get("id"), "Статус оновлено: ти підтвердив подачу")
        api("sendMessage", {
            "chat_id": chat_id,
            "text": (
                "📨 Заявку позначено як відправлену за твоїм підтвердженням. "
                "Це не автоматична перевірка відповіді роботодавця."
            )
        })

    else:
        answer_callback(query.get("id"), "Невідома дія")
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
        api("sendMessage", {"chat_id": chat_id, "text": "Не знайшов вакансію для цього листа."})
        return True

    state = statuses.setdefault(short_id, {"status": "new"})
    package = generate_application(job, load_profile())
    package["cover_letter"] = text[:3500]
    package["revision"] = int(state.get("package_revision", 0)) + 1
    state["package_revision"] = package["revision"]
    state["status"] = "awaiting_approval"
    state["edited_at"] = now_iso()
    state.pop("approved_at", None)
    editing.clear()
    api("sendMessage", {
        "chat_id": chat_id,
        "text": (
            f"✅ Cover Letter для «{job.get('title', 'вакансії')}» оновлено. "
            f"Версія {package['revision']}. Попереднє підтвердження скасовано."
        )
    })
    send_package(chat_id, short_id, job, package)
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

    # This bot is operated through long polling in GitHub Actions. A leftover
    # webhook would prevent getUpdates from receiving callback queries.
    webhook_response = requests.get(
        f"https://api.telegram.org/bot{token}/getWebhookInfo",
        timeout=TIMEOUT
    )
    webhook_response.raise_for_status()
    webhook_payload = webhook_response.json()
    if not webhook_payload.get("ok"):
        raise RuntimeError("Telegram getWebhookInfo failed: " + str(webhook_payload))
    webhook_info = webhook_payload.get("result", {})
    print(
        "Telegram webhook status: "
        f"configured={bool(webhook_info.get('url'))}, "
        f"pending={int(webhook_info.get('pending_update_count', 0) or 0)}"
    )
    if webhook_info.get("url"):
        api("deleteWebhook", {"drop_pending_updates": False})
        print("Removed the leftover webhook; pending Telegram updates were preserved.")

    response = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={
            "offset": offset,
            "timeout": 20,
            "allowed_updates": json.dumps(["callback_query", "message"])
        },
        timeout=TIMEOUT + 5
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

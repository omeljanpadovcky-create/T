import html
import json
import os
import re
import time
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
TELEGRAM_SEND_INTERVAL = 1.1
TELEGRAM_MAX_RETRIES = 6
_LAST_TELEGRAM_SEND = 0.0


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def api(method, payload):
    global _LAST_TELEGRAM_SEND
    token = os.environ["TELEGRAM_BOT_TOKEN"]

    for attempt in range(TELEGRAM_MAX_RETRIES):
        if method == "sendMessage" and _LAST_TELEGRAM_SEND:
            elapsed = time.monotonic() - _LAST_TELEGRAM_SEND
            if elapsed < TELEGRAM_SEND_INTERVAL:
                time.sleep(TELEGRAM_SEND_INTERVAL - elapsed)

        response = requests.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=payload, timeout=TIMEOUT
        )
        if method == "sendMessage":
            _LAST_TELEGRAM_SEND = time.monotonic()

        try:
            data = response.json()
        except ValueError:
            data = {"description": response.text[:1000]}

        if response.ok and data.get("ok"):
            return data.get("result")

        description = data.get("description") or str(data)
        retry_after = (data.get("parameters") or {}).get("retry_after")
        if response.status_code == 429 and attempt < TELEGRAM_MAX_RETRIES - 1:
            wait_seconds = max(1, min(int(retry_after or (2 ** attempt)), 300))
            print(
                f"Telegram rate limit on {method}; retrying after "
                f"{wait_seconds}s (attempt {attempt + 1}/{TELEGRAM_MAX_RETRIES})."
            )
            time.sleep(wait_seconds + 0.2)
            continue

        raise RuntimeError(
            f"Telegram {method} HTTP {response.status_code}: {description}"
        )

    raise RuntimeError(f"Telegram {method} failed after rate-limit retries.")

def safe(value):
    return html.escape(str(value or ""))


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def answer_callback(query_id, text):
    if os.environ.get("MYSHKA_SKIP_CALLBACK_ACK") == "1" or not query_id:
        return
    try:
        api("answerCallbackQuery", {"callback_query_id": query_id, "text": text})
    except requests.RequestException as exc:
        print(f"Could not show callback toast (possibly expired): {exc}")
    except RuntimeError as exc:
        # Telegram returns HTTP 400 when a button callback has expired.
        # The underlying action can still be handled; a stale toast must not
        # crash the entire polling workflow or block later button presses.
        if "answerCallbackQuery HTTP 400" in str(exc):
            print(f"Callback toast expired; continuing safely: {exc}")
        else:
            raise


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
        "contact_phone": "MYSHKA_PHONE",
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
        "skipped": "Пропущена",
        "saved": "Збережена на потім"
    }.get(status, status or "Нова")


def job_message(job, state):
    return (
        f"🐭 ТРЕЙДМИШКА · {int(job.get('score') or 0)}/100\n"
        f"💼 {safe(job.get('title'))}\n"
        f"🏢 {safe(job.get('company') or 'Компанія не вказана')}\n"
        f"🌍 {safe(job.get('location') or 'Remote')}\n"
        f"📌 {safe(job.get('source'))}\n"
        f"📍 Статус: {safe(status_label(state.get('status', 'new')))}\n"
        f"🧠 Висновок Мишки: {safe(job.get('conclusion_uk') or 'Переглянь опис, вимоги до досвіду та англійської. Остаточне рішення — після перевірки сторінки роботодавця.')}\n"
        f"🔬 Аналіз: {safe(job.get('analysis_uk') or 'Потрібно перевірити вимоги та спосіб подачі.')}"    )


def vacancy_keyboard(short_id, job):
    """Primary vacancy-card actions; later package messages expose approval/submission actions."""
    rows = []
    if job.get("url"):
        rows.append([{"text": "🔗 Відкрити вакансію", "url": job["url"]}])
    rows.extend([
        [{"text": "📝 Підготувати заявку", "callback_data": f"prepare|{short_id}"}],
        [{"text": "✉️ Cover Letter", "callback_data": f"letter|{short_id}"}],
        [
            {"text": "💾 На потім", "callback_data": f"save|{short_id}"},
            {"text": "⏭ Пропустити", "callback_data": f"skip|{short_id}"}
        ],
        [{"text": "📊 Статус", "callback_data": f"status|{short_id}"}]
    ])
    return {"inline_keyboard": rows}


def package_keyboard(short_id, job):
    """Keep refreshed pending-review cards fully actionable, like first-delivery cards."""
    return vacancy_keyboard(short_id, job)


def approved_keyboard(short_id, job):
    rows = []
    if job.get("url"):
        rows.append([{"text": "🌐 Відкрити форму роботодавця", "url": job["url"]}])
    rows.append([{"text": "📨 Я ВЖЕ ВІДПРАВИВ ЗАЯВКУ", "callback_data": f"applied|{short_id}"}])
    return {"inline_keyboard": rows}


def approval_keyboard(short_id, job):
    rows = []
    if job.get("url"):
        rows.append([{"text": "🔗 Відкрити вакансію", "url": job["url"]}])
    rows.extend([
        [{"text": "✏️ ВІДРЕДАГУВАТИ COVER LETTER", "callback_data": f"edit|{short_id}"}],
        [{"text": "✅ ПІДТВЕРДИТИ ПАКЕТ", "callback_data": f"approve|{short_id}"}],
        [{"text": "❌ ВІДМОВИТИСЯ ВІД ВАКАНСІЇ", "callback_data": f"skip|{short_id}"}]
    ])
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
            payload["reply_markup"] = approval_keyboard(short_id, job)
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
        for item_id, item, state in pending:
            api("sendMessage", {
                "chat_id": chat_id,
                "text": job_message(item, state),
                "reply_markup": package_keyboard(item_id, item),
                "disable_web_page_preview": True
            })
        return True

    job = applications.get(short_id)
    if not job:
        answer_callback(query.get("id"), "Ця картка застаріла. Відкрий актуальні вакансії.")
        print(f"Ignoring stale Telegram button for missing vacancy id={short_id}")
        return True

    state = statuses.setdefault(short_id, {
        "status": job.get("status", "new"),
        "package_revision": int(job.get("package_revision", 0) or 0)
    })
    current_status = state.get("status", "new")
    allowed_statuses = {
        "confirm": {"new", "selected"},
        "prepare": {"new", "selected", "saved"},
        "skip": {"new", "selected", "awaiting_approval", "saved"},
        "save": {"new", "selected"},
        "status": {"new", "selected", "awaiting_approval", "approved", "submitted_user_confirmed", "skipped", "saved"},
        "edit": {"awaiting_approval"},
        "approve": {"awaiting_approval"},
        "applied": {"approved"},
        "letter": {"new", "selected", "awaiting_approval", "approved", "saved"}
    }
    if action in allowed_statuses and current_status not in allowed_statuses[action]:
        answer_callback(query.get("id"), "Ця дія недоступна для поточного статусу")
        return False

    elif action == "confirm":
        if state.get("status") in ("skipped", "submitted_user_confirmed"):
            answer_callback(query.get("id"), "Цю вакансію вже закрито")
            return False
        # One tap on «ПІДХОДИТЬ» must immediately generate and show the
        # complete Ukrainian application draft in Telegram. Sending it to
        # the employer still requires the separate approval button below.
        answer_callback(query.get("id"), "Підходить! Мишка готує текст відгуку…")
        try:
            package = generate_application(job, load_profile())
            revision = int(state.get("package_revision", 0)) + 1
            package["revision"] = revision
            state["package_revision"] = revision
            state["status"] = "awaiting_approval"
            state["prepared_at"] = now_iso()
            state.pop("approved_at", None)
            send_package(chat_id, short_id, job, package)
        except Exception as exc:
            state["status"] = "selected"
            state.pop("prepared_at", None)
            state.pop("approved_at", None)
            print(
                f"Application package generation/delivery failed for {short_id}: "
                f"{type(exc).__name__}: {exc}"
            )
            api("sendMessage", {
                "chat_id": chat_id,
                "text": (
                    "⚠️ Не вдалося підготувати текст відгуку. Вакансія залишилася "
                    "відібраною — натисни «ПІДХОДИТЬ» ще раз. "
                    "Роботодавцю нічого не надсилали."
                ),
                "disable_web_page_preview": True
            })

    elif action == "prepare":
        # Acknowledge immediately so Telegram does not show a dead button
        # while the application pack is being generated and delivered.
        answer_callback(query.get("id"), "Отримав запит. Готую пакет заявки…")
        try:
            package = generate_application(job, load_profile())
            revision = int(state.get("package_revision", 0)) + 1
            package["revision"] = revision
            state["package_revision"] = revision
            state["status"] = "awaiting_approval"
            state["prepared_at"] = now_iso()
            state.pop("approved_at", None)
            # Do not edit the old vacancy card here: it may have been
            # replaced/deleted or become non-editable. Deliver the package
            # as a fresh Telegram message so one stale message cannot block it.
            send_package(chat_id, short_id, job, package)
        except Exception as exc:
            # Keep the job retryable. Log the actual failure for diagnostics.
            state["status"] = "selected"
            state.pop("prepared_at", None)
            state.pop("approved_at", None)
            print(
                f"Application package generation/delivery failed for {short_id}: "
                f"{type(exc).__name__}: {exc}"
            )
            try:
                api("sendMessage", {
                    "chat_id": chat_id,
                    "text": (
                        "⚠️ Пакет не вдалося доставити. Вакансію залишив у статусі "
                        "«Підходить». Натисни «ПІДГОТУВАТИ ПОВНУ ЗАЯВКУ» ще раз. "
                        "Заявку роботодавцю не надсилали."
                    ),
                    "disable_web_page_preview": True
                })
            except requests.RequestException as notify_exc:
                print(
                    f"Could not send package failure notice for {short_id}: "
                    f"{type(notify_exc).__name__}: {notify_exc}"
                )

    elif action == "save":
        state["status"] = "saved"
        state["saved_at"] = now_iso()
        answer_callback(query.get("id"), "Збережено на потім")
        api("sendMessage", {
            "chat_id": chat_id,
            "text": f"💾 Збережено: {safe(job.get('title') or 'Вакансія')}"
        })

    elif action == "status":
        answer_callback(query.get("id"), status_label(current_status))
        api("sendMessage", {
            "chat_id": chat_id,
            "text": f"📊 Статус вакансії\n{safe(job.get('title') or 'Вакансія')}\nПоточний статус: {safe(status_label(current_status))}"
        })

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
        api("sendMessage", {"chat_id": chat_id, "text": "Не знайшов вакансію для цього повідомлення."})
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

    try:
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
    except requests.RequestException as exc:
        # GitHub-hosted runners can occasionally lose the TLS connection to
        # Telegram. Keep the saved offset unchanged so the next scheduled run
        # can safely retry instead of failing the entire radar workflow.
        print(f"Temporary Telegram polling network error; will retry next run: {type(exc).__name__}: {exc}")
        return
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

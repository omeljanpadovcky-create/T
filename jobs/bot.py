import hashlib
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SEEN_PATH = ROOT / "seen.json"
APPLICATIONS_PATH = ROOT / "applications.json"
HEADERS = {"User-Agent": "TradeMyshka-JobRadar/2.0", "Accept": "application/json"}
TIMEOUT = 25


def norm(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(as_text(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(as_text(v) for v in value)
    return str(value)


def fetch_json(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"Source unavailable: {urlparse(url).netloc}: {exc}")
        return None


def collect_jobs():
    jobs = []
    sources = [
        ("Arbeitnow", "https://www.arbeitnow.com/api/job-board-api"),
        ("RemoteOK", "https://remoteok.com/api"),
    ]
    for source, url in sources:
        data = fetch_json(url)
        if source == "Arbeitnow" and isinstance(data, dict):
            for item in data.get("data", []):
                jobs.append({
                    "title": item.get("title"), "company": item.get("company_name"),
                    "location": item.get("location"), "url": item.get("url"),
                    "description": item.get("description"), "tags": item.get("tags", []),
                    "source": source, "remote": item.get("remote", False)
                })
        elif source == "RemoteOK" and isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("position"):
                    jobs.append({
                        "title": item.get("position"), "company": item.get("company"),
                        "location": item.get("location") or "Remote — country restrictions not specified",
                        "url": item.get("url"), "description": item.get("description"),
                        "tags": item.get("tags", []), "source": source, "remote": True
                    })

    # Search Remotive separately for the target creative disciplines.
    for query in ["3d", "blender", "game artist", "illustration", "concept artist"]:
        data = fetch_json("https://remotive.com/api/remote-jobs?search=" + requests.utils.quote(query))
        if isinstance(data, dict):
            for item in data.get("jobs", []):
                jobs.append({
                    "title": item.get("title"), "company": item.get("company_name"),
                    "location": item.get("candidate_required_location") or "Remote — country restrictions not specified",
                    "url": item.get("url"), "description": item.get("description"),
                    "tags": [item.get("category", ""), *(item.get("tags") or [])],
                    "source": "Remotive", "remote": True
                })

    data = fetch_json("https://himalayas.app/jobs/api?limit=100")
    if isinstance(data, dict):
        for item in data.get("jobs", []):
            restrictions = item.get("locationRestrictions") or item.get("location") or []
            if isinstance(restrictions, list):
                location = ", ".join(str(x) for x in restrictions) or "Remote — country restrictions not specified"
            else:
                location = str(restrictions) or "Remote — country restrictions not specified"
            jobs.append({
                "title": item.get("title"), "company": item.get("companyName") or item.get("company"),
                "location": location, "url": item.get("applicationLink") or item.get("url"),
                "description": item.get("description"), "tags": item.get("categories", []),
                "source": "Himalayas", "remote": True
            })

    unique = {}
    for job in jobs:
        if job.get("url"):
            unique[job_id(job)] = job
    return list(unique.values())


def score_job(job):
    title = norm(as_text(job.get("title")))
    location = norm(as_text(job.get("location")))
    searchable = norm(" ".join([
        as_text(job.get("title")), as_text(job.get("description")),
        as_text(job.get("tags")), as_text(job.get("location"))
    ]))
    if not title or not job.get("url"):
        return 0, "Missing title or link"
    if any(norm(term) in title for term in CONFIG["exclude_terms"]):
        return 0, "Excluded role"
    title_hits = [term for term in CONFIG["target_titles"] if norm(term) in title]
    if not title_hits and not any(x in title for x in ["3d", "roblox", "prop artist", "environment artist"]):
        return 0, "Not a target role"
    if re.search(r"\b(unpaid|volunteer|commission[- ]only|no salary|equity only)\b", searchable):
        return 0, "Unpaid or volunteer role"
    if re.search(r"\b(english|spoken english)\s*(level|proficiency)?\s*[:\-]?\s*(b2|c1|c2|fluent|native|advanced|upper[- ]intermediate)\b|\b(b2|c1|c2)\s+english\b", searchable):
        return 0, "English requirement above A2/B1"
    if re.search(r"\b(usa|united states|canada|australia)\s+only\b|only\s+(usa|united states|canada|australia)", location):
        return 0, "Outside target geography"

    location_ok = any(norm(term) in location for term in CONFIG["allowed_locations"])
    location_ok = location_ok or bool(job.get("remote"))
    if not location_ok:
        return 0, "Location not confirmed as remote"

    score = 35 if title_hits else 25
    matched = []
    for skill in CONFIG["skills"]:
        if norm(skill) in searchable:
            score += 7
            matched.append(skill)
    if "junior" in title or "entry level" in title or "trainee" in title:
        score += 8
    if "remote" in location or job.get("remote"):
        score += 5
    return min(score, 100), ", ".join(matched[:5]) or "Relevant creative role; verify requirements"


def job_id(job):
    raw = job.get("url") or (str(job.get("title")) + str(job.get("company")))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def send_telegram(message, reply_markup=None):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    payload = {
        "chat_id": chat_id, "text": message, "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload, timeout=TIMEOUT
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError("Telegram API rejected sendMessage: " + str(result))
    return result["result"]


# Main daily scan: new matches become Telegram cards with persistent review actions.
def main():
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub Secret.")

    seen = set(load_json(SEEN_PATH, []))
    applications = load_json(APPLICATIONS_PATH, {})
    jobs = collect_jobs()
    matches = []
    rejection_counts = {}
    eligible_count = 0
    for job in jobs:
        score, reason = score_job(job)
        if score:
            eligible_count += 1
        else:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        key = job_id(job)
        if score >= CONFIG["minimum_score"] and key not in seen:
            matches.append((score, reason, key, job))

    matches.sort(key=lambda item: item[0], reverse=True)
    sent = 0
    for score, reason, key, job in matches[:CONFIG["max_results_per_run"]]:
        short_id = key[:16]
        title = html.escape(as_text(job.get("title")) or "Vacancy")
        company = html.escape(as_text(job.get("company")) or "Company not specified")
        location = html.escape(as_text(job.get("location")) or "Remote")
        source = html.escape(as_text(job.get("source")))
        url = html.escape(as_text(job.get("url")), quote=True)
        eligibility_note = ""
        if "not specified" in norm(location):
            eligibility_note = "\n⚠️ <i>Країна найму не вказана — перевір, чи приймають кандидатів з України.</i>"
        message = (
            f"🐭 <b>ТРЕЙДМИШКА · {score}/100</b>\n"
            f"💼 <b>{title}</b>\n🏢 {company}\n🌍 {location}"
            f"{eligibility_note}\n🔎 {html.escape(reason)}\n"
            f"📌 {source}\n🟡 <b>Статус: Нова</b>"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔗 Відкрити вакансію", "url": as_text(job.get("url"))}],
                [
                    {"text": "✅ Підтвердити", "callback_data": f"confirm|{short_id}"},
                    {"text": "⏭ Пропустити", "callback_data": f"skip|{short_id}"}
                ],
                [
                    {"text": "✉️ Чернетка листа", "callback_data": f"letter|{short_id}"},
                    {"text": "✏️ Редагувати лист", "callback_data": f"edit|{short_id}"}
                ],
                [{"text": "📨 Позначити поданою", "callback_data": f"applied|{short_id}"}]
            ]
        }
        telegram_message = send_telegram(message, keyboard)
        applications[short_id] = {
            "id": short_id, "title": as_text(job.get("title")),
            "company": as_text(job.get("company")), "location": as_text(job.get("location")),
            "url": as_text(job.get("url")), "description": as_text(job.get("description"))[:12000],
            "source": as_text(job.get("source")), "score": score, "reason": reason,
            "status": "new", "message_id": telegram_message.get("message_id"),
            "chat_id": telegram_message.get("chat", {}).get("id")
        }
        seen.add(key)
        save_json(APPLICATIONS_PATH, applications)
        save_json(SEEN_PATH, sorted(seen))
        sent += 1

    if os.getenv("MYSHKA_NOTIFY_EMPTY", "").lower() == "true" and sent == 0:
        send_telegram(
            "🐭 <b>ТРЕЙДМИШКА активна!</b>\n"
            f"Перевірено оголошень: <b>{len(jobs)}</b>.\n"
            "Нових збігів за поточними фільтрами немає. Наступна перевірка відбудеться автоматично."
        )
    print(f"Scanned {len(jobs)} listings; eligible {eligible_count}; sent {sent} new matches; saved {len(applications)} application records.")
    print("Top rejection reasons: " + json.dumps(dict(sorted(rejection_counts.items(), key=lambda item: item[1], reverse=True)[:8]), ensure_ascii=False))


if __name__ == "__main__":
    main()

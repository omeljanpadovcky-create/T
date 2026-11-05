import hashlib
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from application_generator import generate_application, render_application_text

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SEEN_PATH = ROOT / "seen.json"
APPLICATIONS_PATH = ROOT / "applications.json"
HEADERS = {"User-Agent": "TradeMyshka-JobRadar/2.0", "Accept": "application/json"}
TIMEOUT = 25
SOURCE_HEALTH = []


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
        data = response.json()
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        label = parsed.netloc
        if query.get("search"):
            label += " · " + query["search"][0]
        elif query.get("q"):
            label += " · " + query["q"][0]
        SOURCE_HEALTH.append({"source": label, "host": parsed.netloc, "ok": True})
        return data
    except (requests.RequestException, ValueError) as exc:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        label = parsed.netloc
        if query.get("search"):
            label += " · " + query["search"][0]
        elif query.get("q"):
            label += " · " + query["q"][0]
        SOURCE_HEALTH.append({"source": label, "host": parsed.netloc, "ok": False})
        print(f"Source unavailable: {parsed.netloc}: {exc}")
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

    # Search Remotive across the full target role set, not only 3D and illustration.
    for query in [
        "3d", "blender", "game artist", "illustration", "concept artist",
        "shopify", "ecommerce", "e-commerce", "ui ux", "graphic design",
        "digital marketing", "product listing", "content manager"
    ]:
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


def outside_target_geography(text):
    patterns = [
        r"\b(?:usa|u\.s\.|united states|canada|australia)\s+only\b",
        r"\bonly\s+(?:in\s+)?(?:usa|u\.s\.|united states|canada|australia)\b",
        r"\b(?:must|need to|required to)\s+be\s+(?:located|based|resident)\s+in\s+(?:the\s+)?(?:usa|u\.s\.|united states|canada|australia)\b",
        r"\b(?:candidates|applicants|residents)\s+must\s+be\s+(?:located|based|resident)\s+in\s+(?:the\s+)?(?:usa|u\.s\.|united states|canada|australia)\b",
        r"\b(?:us|u\.s\.|canada|australia)\s+(?:based|resident)\s+(?:candidates|applicants)\s+only\b"
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


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
    if outside_target_geography(searchable):
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
    if not response.ok:
        try:
            error = response.json()
        except ValueError:
            error = {"description": response.text[:500]}
        description = error.get("description") or str(error)
        raise RuntimeError(
            f"Telegram sendMessage failed (HTTP {response.status_code}): {description}. "
            "Check that the bot is not blocked and TELEGRAM_CHAT_ID is the private chat ID."
        )
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError("Telegram API rejected sendMessage: " + str(result))
    return result["result"]


def load_profile():
    profile_path = ROOT / "profile.json"
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        profile = {}
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


def application_review_keyboard(short_id, job):
    rows = []
    if job.get("url"):
        rows.append([{"text": "🔗 Відкрити вакансію", "url": job["url"]}])
    rows.extend([
        [{"text": "❌ НЕ ПІДХОДИТЬ", "callback_data": f"skip|{short_id}"}],
        [{"text": "✅ ПІДХОДИТЬ", "callback_data": f"confirm|{short_id}"}]
    ])
    return {"inline_keyboard": rows}


def build_ukrainian_conclusion(job, score, reason=""):
    score = int(score or 0)
    if score >= 80:
        verdict = "Сильний збіг із твоїм профілем: варто уважно розглянути вакансію."
    elif score >= 60:
        verdict = "Є потенційний збіг: перевір основні вимоги та обсяг обов’язків."
    else:
        verdict = "Збіг частковий: перед рішенням особливо уважно перевір вимоги."

    description = norm(as_text(job.get("description")))
    english = ""
    if re.search(r"\b(c1|c2|native|fluent|near[- ]native)\b", description):
        english = " Вимога до англійської може бути вищою за твій поточний рівень A2 — це потрібно уточнити."
    elif re.search(r"\b(b2|upper[- ]intermediate|advanced)\b", description):
        english = " У вакансії згадується англійська B2/Advanced; з рівнем A2 це може бути складно."
    elif re.search(r"\b(b1|intermediate)\b", description):
        english = " У вакансії згадується B1/Intermediate; твій A2 може бути нижчим за вимогу."
    elif re.search(r"\b(a2|elementary|basic english)\b", description):
        english = " Згаданий рівень англійської A2/Basic — це ближче до твого поточного рівня."
    else:
        english = " Рівень англійської не вдалося чітко визначити з опису — перевір його перед подачею."

    match_detail = str(reason or "").strip()
    if match_detail and match_detail != "Relevant creative role; verify requirements":
        return verdict + english + " Збіг за навичками: " + match_detail + "."
    return verdict + english


def send_job_card(job, short_id):
    message = (
        f"🐭 <b>MYSHKA · {int(job.get('score') or 0)}/100</b>\n"
        f"💼 <b>{html.escape(as_text(job.get('title')) or 'Вакансія')}</b>\n"
        f"🏢 {html.escape(as_text(job.get('company')) or 'Компанію не вказано')}\n"
        f"🌍 {html.escape(as_text(job.get('location')) or 'Remote')}\n"
        f"📌 Джерело: {html.escape(as_text(job.get('source')) or 'не вказано')}\n"
        f"🧠 <b>Висновок Мишки:</b> {html.escape(as_text(job.get('conclusion_uk')) or build_ukrainian_conclusion(job, job.get('score'), job.get('reason')))}\n\n"
        "Спочатку відкрий вакансію та переглянь умови. Потім обери, чи підходить вона."
    )
    return send_telegram(message, application_review_keyboard(short_id, job))


def build_daily_report(scanned, eligible, new_matches, sent, source_health, rejection_counts):
    totals = {}
    failures = []
    for check in source_health:
        host = check.get("host") or check.get("source") or "Unknown"
        totals.setdefault(host, {"ok": 0, "total": 0})
        totals[host]["total"] += 1
        if check.get("ok"):
            totals[host]["ok"] += 1
        else:
            failures.append(check.get("source") or host)

    source_line = " · ".join(
        f"{host}: {counts['ok']}/{counts['total']}"
        for host, counts in sorted(totals.items())
    ) or "Джерела не повернули статус"
    top_rejections = sorted(
        rejection_counts.items(), key=lambda item: item[1], reverse=True
    )[:3]
    lines = [
        "🐭 <b>Мишка · щоденний звіт</b>",
        f"🔎 Перевірено вакансій: <b>{scanned}</b>",
        f"🎯 Підійшли фільтрам: <b>{eligible}</b>",
        f"🆕 Нових відповідних: <b>{new_matches}</b>",
        f"📨 Надіслано карток: <b>{sent}</b>",
        f"📦 Залишилося в черзі через ліміт: <b>{max(0, new_matches - sent)}</b>",
        "",
        "<b>Стан джерел:</b>",
        html.escape(source_line)
    ]
    if failures:
        lines.extend(["", "⚠️ <b>Не відповіли:</b> " + html.escape(", ".join(failures))])
    if top_rejections:
        lines.extend([
            "",
            "<b>Основні причини відсіву:</b>",
            *[f"• {html.escape(reason)} — {count}" for reason, count in top_rejections]
        ])
    if not source_health or all(not item.get("ok") for item in source_health):
        lines.extend(["", "🚨 <b>Увага:</b> не вдалося отримати дані з жодного джерела."])
    elif failures:
        lines.extend(["", "ℹ️ Пошук завершився частково: перевірка продовжиться за розкладом."])
    else:
        lines.extend(["", "✅ Усі джерела відповіли."])
    return "\n".join(lines)


# Main daily scan: new matches become reviewable Telegram cards with persistent yes/no actions.
def main():
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub Secret.")

    SOURCE_HEALTH.clear()
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
        stored_job = {
            "id": short_id, "title": as_text(job.get("title")),
            "company": as_text(job.get("company")), "location": as_text(job.get("location")),
            "url": as_text(job.get("url")), "description": as_text(job.get("description"))[:12000],
            "source": as_text(job.get("source")), "score": score, "reason": reason,
            "status": "new", "package_revision": 0,
            "conclusion_uk": build_ukrainian_conclusion(job, score, reason)
        }
        telegram_message = send_job_card(stored_job, short_id)
        stored_job["message_id"] = telegram_message.get("message_id") if telegram_message else None
        applications[short_id] = stored_job
        seen.add(key)
        save_json(APPLICATIONS_PATH, applications)
        save_json(SEEN_PATH, sorted(seen))
        sent += 1

    send_telegram(
        build_daily_report(
            scanned=len(jobs),
            eligible=eligible_count,
            new_matches=len(matches),
            sent=sent,
            source_health=SOURCE_HEALTH,
            rejection_counts=rejection_counts
        ),
        {"inline_keyboard": [[{
            "text": "👀 ПЕРЕГЛЯНУТИ ВАКАНСІЇ",
            "callback_data": "review|pending"
        }]]}
    )
    print(f"Scanned {len(jobs)} listings; eligible {eligible_count}; sent {sent} new matches; saved {len(applications)} application records.")
    print("Top rejection reasons: " + json.dumps(dict(sorted(rejection_counts.items(), key=lambda item: item[1], reverse=True)[:8]), ensure_ascii=False))


if __name__ == "__main__":
    main()

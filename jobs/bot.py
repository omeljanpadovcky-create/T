import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SEEN_PATH = ROOT / "seen.json"
HEADERS = {"User-Agent": "MYSHKA-JOBS/0.3"}
TIMEOUT = 20


def norm(value):
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


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
        ("Remotive", "https://remotive.com/api/remote-jobs?search=3d"),
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
                        "location": item.get("location") or "Remote — country restrictions not specified", "url": item.get("url"),
                        "description": item.get("description"), "tags": item.get("tags", []),
                        "source": source, "remote": True
                    })
        elif source == "Remotive" and isinstance(data, dict):
            for item in data.get("jobs", []):
                jobs.append({
                    "title": item.get("title"), "company": item.get("company_name"),
                    "location": item.get("candidate_required_location") or "Remote — country restrictions not specified",
                    "url": item.get("url"), "description": item.get("description"),
                    "tags": [item.get("category", "")], "source": source, "remote": True
                })
    # Additional remote boards: Jobicy and Himalayas.
    for tag in ["3d", "design", "game-development"]:
        data = fetch_json(f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={tag}")
        if isinstance(data, dict):
            for item in data.get("jobs", []):
                jobs.append({
                    "title": item.get("jobTitle"), "company": item.get("companyName"),
                    "location": item.get("jobGeo") or "Remote — country restrictions not specified",
                    "url": item.get("url"), "description": item.get("jobDescription"),
                    "tags": [item.get("jobIndustry", ""), item.get("jobLevel", ""), tag],
                    "source": "Jobicy", "remote": True
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

    # Remove duplicates returned by multiple sources.
    unique = {}
    for job in jobs:
        unique[job_id(job)] = job
    return list(unique.values())


def as_text(value):
    """Convert inconsistent API fields (strings, lists, dicts, None) safely to text."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(as_text(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(as_text(v) for v in value)
    return str(value)


def score_job(job):
    title = norm(as_text(job.get("title")))
    location = norm(as_text(job.get("location")))
    text = norm(" ".join([
        as_text(job.get("title")), as_text(job.get("description")),
        as_text(job.get("tags")), as_text(job.get("location"))
    ]))
    if not title or not job.get("url"):
        return 0, "Missing title or link"
    if any(term in title for term in CONFIG["exclude_terms"]):
        return 0, "Excluded seniority/type"
    title_hits = [term for term in CONFIG["target_titles"] if norm(term) in title]
    if not title_hits and not any(x in title for x in ["3d", "roblox", "prop artist", "environment artist"]):
        return 0, "Not a target role"

    location_ok = any(term in location for term in CONFIG["allowed_locations"])
    location_ok = location_ok or bool(job.get("remote"))
    if not location_ok:
        return 0, "Location not confirmed as suitable"

    score = 35 if title_hits else 25
    matched = []
    for skill in CONFIG["skills"]:
        if norm(skill) in text:
            score += 7
            matched.append(skill)
    if "junior" in title or "entry level" in title:
        score += 8
    if "remote" in location or job.get("remote"):
        score += 5
    return min(score, 100), ", ".join(matched[:5]) or "Relevant 3D role; verify requirements"


def job_id(job):
    raw = job.get("url") or (str(job.get("title")) + str(job.get("company")))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def send_telegram(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
        timeout=TIMEOUT
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API rejected the message: {payload}")


def main():
    seen = set(json.loads(SEEN_PATH.read_text(encoding="utf-8"))) if SEEN_PATH.exists() else set()
    jobs = collect_jobs()
    matches = []
    for job in jobs:
        score, reason = score_job(job)
        key = job_id(job)
        if score >= CONFIG["minimum_score"] and key not in seen:
            matches.append((score, reason, key, job))

    matches.sort(key=lambda item: item[0], reverse=True)
    sent = 0
    for score, reason, key, job in matches[:CONFIG["max_results_per_run"]]:
        location = job.get("location") or "Remote"
        eligibility_note = ""
        if "not specified" in norm(location):
            eligibility_note = "⚠️ Країни найму не вказані — перевір, чи приймають кандидатів з України.\n"
        message = (
            f"🐭 MYSHKA JOBS — {score}/100\n"
            f"💼 {job.get('title')}\n"
            f"🏢 {job.get('company') or 'Company not specified'}\n"
            f"🌍 {location}\n"
            f"{eligibility_note}"
            f"🔎 {reason}\n"
            f"📌 Джерело: {job.get('source')}\n"
            f"🔗 {job.get('url')}"
        )
        send_telegram(message)
        seen.add(key)
        sent += 1

    if os.getenv("MYSHKA_NOTIFY_EMPTY", "").lower() == "true" and sent == 0:
        send_telegram(
            "🐭 MYSHKA JOBS підключений до Telegram!\n"
            f"Перевірка завершена: переглянуто {len(jobs)} оголошень.\n"
            "Нових вакансій за твоїми фільтрами цього разу не знайдено. "
            "Наступні перевірки надсилатимуть нові збіги автоматично."
        )

    SEEN_PATH.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Scanned {len(jobs)} listings; sent {sent} new matches.")


if __name__ == "__main__":
    main()

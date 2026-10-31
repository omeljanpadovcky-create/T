import json
import os
import re
import hashlib
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SEEN_PATH = ROOT / "seen.json"
HEADERS = {"User-Agent": "MYSHKA-JOBS/0.1 (+https://github.com/omeljanpadovcky-create/T)"}
TIMEOUT = 20


def norm(value):
    return re.sub(r"\\s+", " ", str(value or "")).strip().lower()


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

    data = fetch_json("https://www.arbeitnow.com/api/job-board-api")
    if isinstance(data, dict):
        for item in data.get("data", []):
            jobs.append({
                "title": item.get("title"), "company": item.get("company_name"),
                "location": item.get("location"), "url": item.get("url"),
                "description": item.get("description"), "tags": item.get("tags", []),
                "source": "Arbeitnow", "remote": item.get("remote", False)
            })

    data = fetch_json("https://remoteok.com/api")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("position"):
                jobs.append({
                    "title": item.get("position"), "company": item.get("company"),
                    "location": item.get("location") or "Remote",
                    "url": item.get("url"), "description": item.get("description"),
                    "tags": item.get("tags", []), "source": "RemoteOK", "remote": True
                })

    data = fetch_json("https://remotive.com/api/remote-jobs?search=3d")
    if isinstance(data, dict):
        for item in data.get("jobs", []):
            jobs.append({
                "title": item.get("title"), "company": item.get("company_name"),
                "location": item.get("candidate_required_location") or "Remote",
                "url": item.get("url"), "description": item.get("description"),
                "tags": [item.get("category", "")], "source": "Remotive", "remote": True
            })
    return jobs


def score_job(job):
    title = norm(job.get("title"))
    location = norm(job.get("location"))
    text = norm(" ".join([
        job.get("title", ""), job.get("description", ""),
        " ".join(job.get("tags") or []), job.get("location", "")
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
    score = min(score, 100)
    return score, ", ".join(matched[:5]) or "Relevant 3D role; verify requirements"


def job_id(job):
    raw = job.get("url") or (str(job.get("title")) + str(job.get("company")))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def send_telegram(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=TIMEOUT
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram API rejected the message")


def main():
    seen = set(json.loads(SEEN_PATH.read_text(encoding="utf-8"))) if SEEN_PATH.exists() else set()
    jobs = collect_jobs()
    matches = []
    for job in jobs:
        score, reason = score_job(job)
        key = job_id(job)
        if score >= CONFIG["minimum_score"] and key not in seen:
            matches.append((score, reason, key, job))

    matches.sort(key=lambda x: x[0], reverse=True)
    for score, reason, key, job in matches[:CONFIG["max_results_per_run"]]:
        message = (
            f"🐭 MYSHKA JOBS — {score}/100\\n"
            f"{job.get('title')}\\n"
            f"🏢 {job.get('company') or 'Company not specified'}\\n"
            f"🌍 {job.get('location') or 'Remote'}\\n"
            f"🔎 {reason}\\n"
            f"📌 Source: {job.get('source')}\\n"
            f"{job.get('url')}"
        )
        send_telegram(message)
        seen.add(key)

    SEEN_PATH.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print(f"Scanned {len(jobs)} listings; sent {min(len(matches), CONFIG['max_results_per_run'])} new matches.")


if __name__ == "__main__":
    main()

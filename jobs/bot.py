import hashlib
import json
import html
import os
import re
from html.parser import HTMLParser
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



class VacancyLinkParser(HTMLParser):
    """Extract public vacancy links from DOU and Djinni search result pages."""

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.current = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs)
        href = attrs.get("href", "")
        classes = attrs.get("class", "").lower()
        if self.source == "DOU":
            is_job = "/vacancies/" in href and href.rstrip("/") != "https://jobs.dou.ua/vacancies"
        elif self.source == "Work.ua":
            is_job = re.search(r"/jobs/\d+", href) is not None
        elif self.source == "Robota.ua":
            is_job = re.search(r"/company\d+/vacancy\d+", href) is not None
        elif self.source == "ZipRecruiter":
            is_job = (
                re.search(r"/jobs/[^/?#]+", href) is not None
                or re.search(r"/c/[^/]+/jobs?/", href, re.IGNORECASE) is not None
            )
        else:
            is_job = re.search(r"/jobs/[^/?#]+", href) is not None
            if self.source == "ArtStation":
                is_job = is_job and "/jobs/all" not in href
        if is_job and not self.current:
            self.current = {"url": href, "title": ""}

    def handle_data(self, data):
        if self.current is not None:
            self.current["title"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            item = self.current
            self.current = None
            item["title"] = re.sub(r"\s+", " ", item["title"]).strip()
            if item["title"] and len(item["title"]) > 2:
                self.links.append(item)


class PageTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.in_script = False
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.in_script = True
        elif tag == "style":
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
        elif tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if not self.in_script and not self.in_style:
            value = re.sub(r"\s+", " ", data).strip()
            if value:
                self.parts.append(value)


def absolute_job_url(base, href):
    from urllib.parse import urljoin
    return urljoin(base, href)


def fetch_html(url):
    try:
        response = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MYSHKA-JOB-RADAR/1.0)",
            "Accept": "text/html,application/xhtml+xml"
        }, timeout=TIMEOUT)
        response.raise_for_status()
        parsed = urlparse(url)
        SOURCE_HEALTH.append({"source": parsed.netloc, "host": parsed.netloc, "ok": True})
        return response.text
    except requests.RequestException as exc:
        parsed = urlparse(url)
        SOURCE_HEALTH.append({"source": parsed.netloc, "host": parsed.netloc, "ok": False})
        print(f"Source unavailable: {parsed.netloc}: {exc}")
        return None


def extract_job_details(url, source, fallback_title):
    page = fetch_html(url)
    if not page:
        return None
    text_parser = PageTextParser()
    try:
        text_parser.feed(page)
    except Exception:
        pass
    page_text = " ".join(text_parser.parts)

    structured = {}
    for match in re.finditer(
        r"""<script[^>]*type=["']application/ld\+json["'][^>]*>(.*?)</script>""",
        page, re.IGNORECASE | re.DOTALL
    ):
        try:
            payload = json.loads(html.unescape(match.group(1)))
        except (ValueError, TypeError):
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") in ("JobPosting", ["JobPosting"]):
                structured = candidate
                break
        if structured:
            break

    title = as_text(structured.get("title")) or fallback_title
    company = structured.get("hiringOrganization") or {}
    if isinstance(company, dict):
        company = company.get("name", "")
    location = structured.get("jobLocation") or structured.get("jobLocationType") or ""
    description = as_text(structured.get("description")) or page_text
    remote_text = norm(" ".join([as_text(location), description, page_text[:12000]]))
    remote = bool(re.search(
        r"\b(remote|remotely|work from home|distributed|anywhere|віддален|дистанційн)\b",
        remote_text
    ))
    if str(structured.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        remote = True
    if not location:
        location = "Remote" if remote else "Location not confirmed"
    salary = structured.get("baseSalary") or {}
    if isinstance(salary, dict):
        salary_value = as_text(salary.get("value"))
        salary_currency = as_text(salary.get("currency"))
        if salary_value:
            description += f" Salary: {salary_currency} {salary_value}"
    return {
        "title": title, "company": as_text(company), "location": as_text(location),
        "url": url, "description": description[:16000], "tags": [],
        "source": source, "remote": remote
    }


def collect_artstation_jobs():
    """Collect relevant public vacancies from the ArtStation Jobs board."""
    page = fetch_html("https://www.artstation.com/jobs/all")
    if not page:
        return []
    parser = VacancyLinkParser("ArtStation")
    try:
        parser.feed(page)
    except Exception as exc:
        print(f"ArtStation listing parse warning: {exc}")
        return []
    jobs = []
    seen_urls = set()
    for item in parser.links:
        url = absolute_job_url("https://www.artstation.com/jobs/all", item["url"])
        if url in seen_urls:
            continue
        seen_urls.add(url)
        title = item["title"]
        title_norm = norm(title)
        if not any(norm(target) in title_norm for target in CONFIG["target_titles"]) and not any(
            term in title_norm for term in ("3d", "blender", "illustrat", "concept artist", "environment artist", "prop artist", "game artist")
        ):
            continue
        details = extract_job_details(url, "ArtStation", title)
        if details:
            jobs.append(details)
    print(f"ArtStation: parsed {len(parser.links)} links; inspected {len(jobs)} relevant listings")
    return jobs


def collect_ziprecruiter_jobs():
    """Collect public remote vacancies from ZipRecruiter's public search pages.

    ZipRecruiter does not expose its partner API without credentials, so this uses
    the public HTML search pages. If the site blocks automated requests, the
    source-health report will show the failure and the rest of the radar continues.
    """
    search_terms = [
        "3D Artist", "Blender", "Game Artist", "Game Asset Artist",
        "Character Artist", "Environment Artist", "Prop Artist",
        "3D Modeler", "Concept Artist", "Low Poly Artist"
    ]
    jobs = []
    seen_urls = set()
    base_url = "https://www.ziprecruiter.com/jobs-search"
    for term in search_terms:
        search_url = (
            base_url + "?search=" + requests.utils.quote(term)
            + "&location=Remote"
        )
        page = fetch_html(search_url)
        if not page:
            continue
        if "cf-chl-" in page or "just a moment" in page.lower():
            parsed = urlparse(search_url)
            SOURCE_HEALTH.append({
                "source": "ZipRecruiter · Cloudflare challenge",
                "host": parsed.netloc,
                "ok": False
            })
            print("ZipRecruiter search is protected by a browser challenge; skipping this query.")
            continue
        parser = VacancyLinkParser("ZipRecruiter")
        try:
            parser.feed(page)
        except Exception as exc:
            print(f"ZipRecruiter listing parse warning: {exc}")
            continue
        for item in parser.links:
            url = absolute_job_url(base_url, item["url"])
            if url in seen_urls:
                continue
            seen_urls.add(url)
            title = item["title"]
            title_norm = norm(title)
            if not any(norm(target) in title_norm for target in CONFIG["target_titles"]) and not any(
                term in title_norm for term in (
                    "3d", "blender", "game art", "game asset", "character artist",
                    "environment artist", "prop artist", "illustrat", "concept artist"
                )
            ):
                continue
            details = extract_job_details(url, "ZipRecruiter", title)
            if details:
                details["source"] = "ZipRecruiter"
                if not details.get("location") or details.get("location") == "Location not confirmed":
                    details["location"] = "Remote — verify country restrictions"
                # The search itself is explicitly scoped to Remote; country eligibility
                # is still checked from the full posting text by score_job().
                details["remote"] = True
                jobs.append(details)
            else:
                jobs.append({
                    "title": title,
                    "company": "",
                    "location": "Remote — verify country restrictions",
                    "url": url,
                    "description": "",
                    "tags": [],
                    "source": "ZipRecruiter",
                    "remote": True
                })
    print(f"ZipRecruiter: collected {len(jobs)} public remote listings")
    return jobs


def collect_community_jobs(source, search_terms, base_url, parameter):
    jobs = []
    seen_urls = set()
    for term in search_terms:
        query = requests.utils.quote(term)
        search_url = f"{base_url}?{parameter}={query}"
        page = fetch_html(search_url)
        if not page:
            continue
        parser = VacancyLinkParser(source)
        try:
            parser.feed(page)
        except Exception as exc:
            print(f"{source} listing parse warning: {exc}")
            continue
        for item in parser.links:
            url = absolute_job_url(base_url, item["url"])
            if url in seen_urls:
                continue
            seen_urls.add(url)
            # Avoid spending requests on unrelated listings; title must be in the target family.
            title = item["title"]
            title_norm = norm(title)
            if not any(norm(target) in title_norm for target in CONFIG["target_titles"]) and not any(
                term in title_norm for term in ("3d", "blender", "game art", "game asset", "character artist", "environment artist", "prop artist", "illustrat", "concept artist")
            ):
                continue
            details = extract_job_details(url, source, title)
            if details:
                jobs.append(details)
    return jobs


def collect_path_search_jobs(source, search_terms, url_builder, max_links_per_search=30):
    """Collect public job links from Ukrainian job-board search pages."""
    jobs = []
    seen_urls = set()
    for term in search_terms:
        search_url = url_builder(term)
        page = fetch_html(search_url)
        if not page:
            continue
        parser = VacancyLinkParser(source)
        try:
            parser.feed(page)
        except Exception as exc:
            print(f"{source} listing parse warning: {exc}")
            continue
        inspected = 0
        for item in parser.links:
            url = absolute_job_url(search_url, item["url"])
            if url in seen_urls:
                continue
            seen_urls.add(url)
            title = item["title"]
            title_norm = norm(title)
            if not any(norm(target) in title_norm for target in CONFIG["target_titles"]) and not any(
                term in title_norm for term in (
                    "3d", "blender", "game art", "game asset", "character artist",
                    "environment artist", "prop artist", "illustrat", "concept artist"
                )
            ):
                continue
            details = extract_job_details(url, source, title)
            if details:
                jobs.append(details)
                inspected += 1
            if inspected >= max_links_per_search:
                break
    print(f"{source}: collected {len(jobs)} relevant public listings")
    return jobs


def collect_rss_jobs(url, source):
    """Read a public RSS job feed and preserve its original application links."""
    import xml.etree.ElementTree as ET

    page = fetch_html(url)
    if not page:
        return []
    jobs = []
    try:
        root = ET.fromstring(page)
    except ET.ParseError as exc:
        print(f"{source} RSS parse warning: {exc}")
        return jobs
    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        description = item.findtext("description", "")
        if title and link:
            jobs.append({
                "title": title, "company": "", "location": "Remote — verify country restrictions",
                "url": link, "description": description, "tags": [],
                "source": source, "remote": True
            })
    print(f"{source}: parsed {len(jobs)} RSS entries")
    return jobs


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

    # Search only the agreed 3D / Game Art / character / illustration role families.
    for query in [
        "3d", "blender", "game artist", "game asset", "character artist",
        "environment artist", "prop artist", "technical artist", "3d modeler", "illustration", "concept artist"
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

    # Public RSS source for additional international remote opportunities.
    jobs.extend(collect_rss_jobs(
        "https://weworkremotely.com/remote-jobs.rss", "We Work Remotely"
    ))

    # Ukrainian job boards: search relevant role families and inspect each matching public listing.
    dou_terms = [
        "3D Artist", "Blender", "Game Artist", "Character Artist",
        "Environment Artist", "Prop Artist", "Technical Artist", "3D Modeler", "Concept Artist"
    ]
    djinni_terms = [
        "3D Artist", "Blender", "Game Artist", "Character Artist",
        "Environment Artist", "Prop Artist", "Technical Artist", "3D Modeler", "Concept Artist"
    ]
    jobs.extend(collect_community_jobs(
        "DOU", dou_terms, "https://jobs.dou.ua/vacancies/", "search"
    ))
    jobs.extend(collect_community_jobs(
        "Djinni", djinni_terms, "https://djinni.co/jobs/", "keywords"
    ))

    ukrainian_terms = [
        "3D Artist", "Blender", "Game Artist", "Character Artist",
        "Environment Artist", "Prop Artist", "Technical Artist", "3D Modeler", "Concept Artist",
        "Illustrator"
    ]
    jobs.extend(collect_path_search_jobs(
        "Work.ua",
        ukrainian_terms,
        lambda term: "https://www.work.ua/jobs/?search=" + requests.utils.quote(term)
    ))
    jobs.extend(collect_path_search_jobs(
        "Robota.ua",
        ukrainian_terms,
        lambda term: "https://robota.ua/zapros/" +
        requests.utils.quote(term.lower().replace(" ", "-"), safe="-") + "/ukraine"
    ))
    jobs.extend(collect_ziprecruiter_jobs())
    jobs.extend(collect_artstation_jobs())

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

    score = 40 if title_hits else 25
    matched = []
    for skill in CONFIG["skills"]:
        if norm(skill) in searchable:
            score += 7
            matched.append(skill)
    if "junior" in title or "entry level" in title or "trainee" in title:
        score += 8
    if "remote" in location or job.get("remote"):
        score += 5
    score = min(score, 100)
    minimum_score = int(CONFIG.get("minimum_score", 50))
    if score < minimum_score:
        return 0, f"Below {minimum_score}/100 ({score}/100)"
    return score, ", ".join(matched[:5]) or "Relevant creative role; verify requirements"


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
    rows.append([
        {"text": "✅ Підходить — підготувати відгук", "callback_data": f"confirm|{short_id}"},
        {"text": "❌ Не підходить", "callback_data": f"skip|{short_id}"}
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
    english_match = re.search(r"\b(a1|a2|b1|b2|c1|c2|basic|elementary|intermediate|upper[- ]intermediate|advanced|fluent|native)\b", description)
    candidate_english = str(load_profile().get("english_level") or "").upper()
    english = (
        (
            f" У вакансії згадується англійська ({english_match.group(1).upper()}); "
            + (
                f"у твоєму профілі зазначено {candidate_english}, тому вимогу варто перевірити вручну; "
                if candidate_english and candidate_english != english_match.group(1).upper() else ""
            )
            + "це лише інформація для твого рішення, не причина автоматичного відсіву."
        )
        if english_match else
        " Вимогу до англійської потрібно перевірити вручну; вона не впливає на автоматичний відбір."
    )

    match_detail = str(reason or "").strip()
    if match_detail and match_detail != "Relevant creative role; verify requirements":
        return verdict + english + " Збіг за навичками: " + match_detail + "."
    return verdict + english


def analyze_job_uk(job, profile=None):
    """Create a concise, evidence-based Ukrainian fit and application analysis."""
    profile = profile or load_profile()
    description = as_text(job.get("description"))
    searchable = norm(description)
    profile_skills = profile.get("skills", [])
    matched = [
        skill for skill in profile_skills
        if norm(skill) and norm(skill) in norm(" ".join([
            as_text(job.get("title")), description, as_text(job.get("tags"))
        ]))
    ]
    english_match = re.search(
        r"\b(a1|a2|b1|b2|c1|c2|basic|elementary|intermediate|upper[- ]intermediate|advanced|fluent|native)\b",
        searchable
    )
    english = english_match.group(1).upper() if english_match else "не вказано"
    experience = re.search(
        r"(?:at least|minimum of|\b)(\d+)\+?\s+years?\s+(?:of\s+)?(?:professional\s+)?experience",
        searchable
    )
    experience_note = (
        f"У вимогах згадано {experience.group(1)}+ р. досвіду — перевір, чи приймають практику/стажування."
        if experience else "Жорстку вимогу до років досвіду з опису не визначено."
    )
    recipient = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", description, re.I)
    apply_method = (
        f"Є email для подачі: {recipient.group(0)}."
        if recipient else "Email у тексті не знайдено — готуватиму пакет для форми на сайті."
    )
    skills_note = (
        "Збіг навичок: " + ", ".join(matched[:6]) + "."
        if matched else "Прямого збігу навичок у тексті мало — потрібна ручна перевірка."
    )
    english_note = (
        f"Англійська у вакансії: {english}. Це інформація для твого рішення, не фільтр."
        if english != "не вказано" else
        "Рівень англійської не вказано; це не впливає на відбір."
    )
    return " ".join([skills_note, english_note, experience_note, apply_method])


def send_job_card(job, short_id):
    message = (
        f"🐭 <b>MYSHKA · {int(job.get('score') or 0)}/100</b>\n"
        f"💼 <b>{html.escape(as_text(job.get('title')) or 'Вакансія')}</b>\n"
        f"🏢 {html.escape(as_text(job.get('company')) or 'Компанію не вказано')}\n"
        f"🌍 {html.escape(as_text(job.get('location')) or 'Remote')}\n"
        f"📌 Джерело: {html.escape(as_text(job.get('source')) or 'не вказано')}\n"
        f"🧠 <b>Висновок Мишки:</b> {html.escape(as_text(job.get('conclusion_uk')) or build_ukrainian_conclusion(job, job.get('score'), job.get('reason')))}\n"
        f"🔬 <b>Аналіз:</b> {html.escape(as_text(job.get('analysis_uk')) or analyze_job_uk(job))}\n\n"
        "Переглянь опис вакансії, вимоги та умови подачі за посиланням."
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
        if score >= int(CONFIG.get("minimum_score", 50)):
            eligible_count += 1
        else:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        key = job_id(job)
        # Score is informational only. Deliver every listing with a title and URL.
        if as_text(job.get("title")).strip() and as_text(job.get("url")).strip() and key not in seen:
            matches.append((score, reason, key, job))

    matches.sort(key=lambda item: item[0], reverse=True)
    sent = 0
    for score, reason, key, job in matches:
        short_id = key[:16]
        stored_job = {
            "id": short_id, "title": as_text(job.get("title")),
            "company": as_text(job.get("company")), "location": as_text(job.get("location")),
            "url": as_text(job.get("url")), "description": as_text(job.get("description"))[:12000],
            "source": as_text(job.get("source")), "score": score, "reason": reason,
            "status": "new", "package_revision": 0,
            "conclusion_uk": build_ukrainian_conclusion(job, score, reason),
            "analysis_uk": analyze_job_uk(job)
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

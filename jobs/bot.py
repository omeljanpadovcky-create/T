import hashlib
import json
import html
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from telegram_sources import collect_telegram_channel_jobs

from application_generator import generate_application, render_application_text

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SEEN_PATH = ROOT / "seen.json"
APPLICATIONS_PATH = ROOT / "applications.json"
HEADERS = {"User-Agent": "TradeMyshka-JobRadar/2.0", "Accept": "application/json"}
TIMEOUT = 25
SOURCE_HEALTH = []
COUNTRY_LOCATION_TERMS = (
    "united states", "usa", "us", "u.s.", "canada", "australia", "germany",
    "france", "united kingdom", "uk", "ireland", "netherlands", "poland",
    "india", "singapore", "japan", "spain", "italy", "sweden", "norway",
    "denmark", "finland", "portugal", "switzerland", "austria", "belgium",
    "czech republic", "romania", "brazil", "mexico", "new zealand"
)
GLOBAL_LOCATION_TERMS = (
    "worldwide", "anywhere", "global", "europe", "european union",
    "emea", "ukraine"
)
_LAST_TELEGRAM_SEND = 0.0
TELEGRAM_MAX_RETRIES = 6
TELEGRAM_MIN_INTERVAL = 1.1


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
        elif self.source == "LinkedIn":
            is_job = "/jobs/view/" in href
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
        "salary": (f"{salary_currency} {salary_value}".strip() if isinstance(salary, dict) and salary_value else ""),
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
            term in title_norm for term in ("3d", "blender", "illustrat", "concept artist", "environment artist", "prop artist", "game artist", "photobash", "matte painter", "book cover", "key art", "splash art")
        ):
            continue
        details = extract_job_details(url, "ArtStation", title)
        if details:
            jobs.append(details)
    print(f"ArtStation: parsed {len(parser.links)} links; inspected {len(jobs)} relevant listings")
    return jobs



def collect_linkedin_jobs():
    """Collect public LinkedIn job-search results without logging in or bypassing access controls."""
    search_terms = [
        "3D Artist", "Blender Artist", "3D Character Artist",
        "Game Asset Artist", "Environment Artist", "3D Modeler"
    ]
    jobs = []
    seen_urls = set()
    base_url = "https://www.linkedin.com/jobs/search/"
    for term in search_terms:
        search_url = base_url + "?keywords=" + requests.utils.quote(term) + "&location=Ukraine&f_WT=2"
        page = fetch_html(search_url)
        if not page:
            continue
        if "authwall" in page.lower() or "checkpoint/challenge" in page.lower():
            SOURCE_HEALTH.append({
                "source": "LinkedIn · public search requires sign-in",
                "host": "www.linkedin.com",
                "ok": False
            })
            continue
        parser = VacancyLinkParser("LinkedIn")
        try:
            parser.feed(page)
        except Exception as exc:
            print(f"LinkedIn listing parse warning: {exc}")
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
                    "3d", "blender", "game artist", "game asset",
                    "character artist", "environment artist", "prop artist"
                )
            ):
                continue
            details = extract_job_details(url, "LinkedIn", title)
            if details:
                jobs.append(details)
    print(f"LinkedIn: collected {len(jobs)} public listings")
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
        "3D Modeler", "Concept Artist", "Low Poly Artist",
        "Photobashing", "Matte Painter", "Book Cover", "Key Art", "Splash Art"
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

    # Search the agreed 3D / Game Art / Blender role families only.
    for query in [
        "3d", "blender", "game artist", "game asset", "character artist",
        "environment artist", "prop artist", "technical artist", "3d modeler", "hard surface"
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
        "Environment Artist", "Prop Artist", "Technical Artist", "3D Modeler", "Hard Surface Artist"
    ]
    djinni_terms = [
        "3D Artist", "Blender", "Game Artist", "Character Artist",
        "Environment Artist", "Prop Artist", "Technical Artist", "3D Modeler", "Hard Surface Artist"
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
        "Hard Surface Artist"
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
    # LinkedIn public job search; no login or private-data access.
    jobs.extend(collect_linkedin_jobs())
    # Public Telegram channel posts are vacancy leads; the normal scoring,
    # paid-role, Ukraine eligibility, deduplication and approval flow still applies.
    jobs.extend(collect_telegram_channel_jobs(SOURCE_HEALTH))

    unique = {}
    for job in jobs:
        if job.get("url"):
            unique[job_id(job)] = job
    return list(unique.values())


def outside_target_geography(text):
    countries = (
        r"(?:the united states|united states|u\.s\.a?\.?|usa|us|canada|australia|"
        r"germany|france|united kingdom|uk|ireland|netherlands|poland|india|"
        r"singapore|japan|spain|italy|sweden|norway|denmark|finland|portugal|"
        r"switzerland|austria|belgium|czech republic|romania|brazil|mexico|"
        r"new zealand)"
    )
    patterns = [
        r"\b(?:usa|u\.s\.|united states|canada|australia)\s+only\b",
        r"\bonly\s+(?:in\s+)?(?:usa|u\.s\.|united states|canada|australia)\b",
        rf"\b(?:must|need to|required to|expected to)\s+be\s+(?:located|based|resident)\s+in\s+(?:the\s+)?{countries}\b",
        rf"\b(?:only\s+)?(?:candidates|applicants|residents)\s+(?:must\s+be\s+)?(?:located|based|resident)\s+in\s+(?:the\s+)?{countries}\b",
        rf"\b(?:remote|work from home)\s+(?:role|position|job)?\s*(?:for|in|within)\s+(?:the\s+)?{countries}\s+only\b",
        rf"\b(?:work authorization|right to work)\s+(?:in|for)\s+(?:the\s+)?{countries}\b"
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def country_limited_location(location):
    value = norm(location)
    has_country = any(
        re.search(r"\b" + re.escape(country) + r"\b", value)
        for country in COUNTRY_LOCATION_TERMS
    )
    has_global_scope = any(term in value for term in GLOBAL_LOCATION_TERMS)
    return has_country and not has_global_scope


def score_job(job):
    """Score 3D/Game Art vacancies; uncertain remote/geography is labelled for manual verification."""
    title = norm(as_text(job.get('title')))
    location = norm(as_text(job.get('location')))
    description = norm(as_text(job.get('description')))
    tags = norm(as_text(job.get('tags')))
    searchable = " ".join([title, description, tags, location])

    if not title or not job.get('url'):
        return 0, "Missing title or link"
    if any(norm(term) in title for term in CONFIG['exclude_terms']):
        return 0, "Excluded role"
    if re.search(r'\b(unpaid|volunteer|commission[- ]only|no salary|equity only)\b|без\s+оплат|волонтерств|неоплачув', searchable, re.I):
        return 0, "Unpaid or volunteer role"
    if outside_target_geography(searchable):
        return 0, "Outside target geography"

    remote_ok = bool(re.search(r'\b(remote|remotely|work from home|distributed|віддален|дистанційн)\b', searchable, re.I))
    scope_ok = bool(re.search(r'\b(ukraine|україн[а-яіїєґ]*|lviv|kyiv|dnipro|odesa|kharkiv|vinnytsia|europe|european union|eu|emea|worldwide|anywhere|global)\b', searchable, re.I))
    if country_limited_location(location):
        return 0, "Country-specific location; not confirmed eligible for Ukraine"

    target_patterns = (r'\b3d\b', r'\bblender\b', r'game.?asset', r'game.?artist', r'character artist', r'environment artist', r'prop artist', r'technical artist', r'3d model(?:er|ler)', r'hard.?surface artist', r'texture artist', r'3d generalist', r'3d sculptor', r'weapons artist')
    if not any(re.search(pattern, title, re.I) for pattern in target_patterns):
        return 0, "Not a target 3D or Game Art role"

    title_points = 35
    skill_groups = {
        '3D software': (r'\bblender\b', r'\bmaya\b', r'3ds\s*max', r'zbrush', r'cinema\s*4d'),
        'modeling': (r'3d model', r'modeling', r'modelling', r'sculpt', r'hard.?surface', r'low.?poly'),
        'asset workflow': (r'uv\s*(?:mapping|unwrap)', r'textur', r'substance painter', r'game.?ready', r'pbr'),
    }
    skill_points = 0
    matched_groups = []
    for group, patterns in skill_groups.items():
        if any(re.search(pattern, searchable, re.I) for pattern in patterns):
            skill_points += 10
            matched_groups.append(group)
    skill_points = min(skill_points, 30)

    game_context = bool(re.search(r'game.?dev|game.?asset|game.?art|unreal|unity|game.?ready|real.?time|ігров|геймдев|игров', searchable, re.I))
    game_points = 15 if game_context else 0
    remote_points = 10 if remote_ok else 0
    geography_points = 10 if re.search(r'\b(ukraine|україн[а-яіїєґ]*|lviv|kyiv|dnipro|odesa|kharkiv|vinnytsia|worldwide|anywhere|global)\b', searchable, re.I) else (8 if scope_ok else 5)
    paid_points = 10
    score = min(100, title_points + skill_points + game_points + remote_points + geography_points + paid_points)
    minimum_score = max(80, int(CONFIG.get('minimum_score', 80)))
    if score < minimum_score:
        return 0, f"Below {minimum_score}/100 ({score}/100)"

    reason_parts = ['3D/Game Art role']
    reason_parts.extend(matched_groups)
    if game_context:
        reason_parts.append('game-development context')
    reason_parts.append('remote confirmed' if remote_ok else '⚠️ remote format needs verification')
    reason_parts.append('Ukraine-eligible geography stated' if scope_ok else '⚠️ country eligibility needs verification')
    reason_parts.append('paid status not marked unpaid')
    return score, ", ".join(reason_parts)

def normalize_job_url(value):
    """Normalize tracking/query variants so one vacancy has one stable URL identity."""
    from urllib.parse import urlunparse, urlencode

    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else "https://" + raw)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    # Drop fragments and all query parameters: tracking parameters and source-specific
    # query strings must not make the same vacancy look new.
    return urlunparse((parsed.scheme.lower() or "https", host, path, "", "", ""))


def job_identity_keys(job):
    """Return compatible legacy and stronger fingerprints for vacancy deduplication."""
    keys = set()
    raw_url = str(job.get("url") or "").strip()
    normalized_url = normalize_job_url(raw_url)
    if raw_url:
        # Keep compatibility with hashes already stored by older radar versions.
        keys.add(hashlib.sha256(raw_url.encode("utf-8")).hexdigest())
    if normalized_url:
        keys.add(hashlib.sha256(("url:" + normalized_url).encode("utf-8")).hexdigest())

    title = norm(job.get("title"))
    company = norm(job.get("company"))
    if title and company:
        # Ignore punctuation/spacing differences in title and company.
        title = re.sub(r"[^a-z0-9а-яіїєґ]+", " ", title).strip()
        company = re.sub(r"[^a-z0-9а-яіїєґ]+", " ", company).strip()
        if title and company:
            identity = f"title-company:{title}|{company}"
            keys.add(hashlib.sha256(identity.encode("utf-8")).hexdigest())
    return keys


def job_id(job):
    """Stable primary ID; legacy URL-only behavior retained for old stored references."""
    keys = job_identity_keys(job)
    return sorted(keys)[0] if keys else hashlib.sha256(b"").hexdigest()


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
    global _LAST_TELEGRAM_SEND
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    payload = {
        "chat_id": chat_id, "text": message, "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    for attempt in range(TELEGRAM_MAX_RETRIES):
        elapsed = time.monotonic() - _LAST_TELEGRAM_SEND
        if _LAST_TELEGRAM_SEND and elapsed < TELEGRAM_MIN_INTERVAL:
            time.sleep(TELEGRAM_MIN_INTERVAL - elapsed)
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=TIMEOUT
        )
        _LAST_TELEGRAM_SEND = time.monotonic()
        try:
            result = response.json()
        except ValueError:
            result = {"description": response.text[:500]}

        if response.ok and result.get("ok"):
            return result["result"]

        description = result.get("description") or str(result)
        retry_after = (result.get("parameters") or {}).get("retry_after")
        if response.status_code == 429 and retry_after is not None and attempt < TELEGRAM_MAX_RETRIES - 1:
            wait_seconds = max(1, min(int(retry_after), 300))
            print(f"Telegram rate limit reached; retrying after {wait_seconds}s (attempt {attempt + 1}/{TELEGRAM_MAX_RETRIES}).")
            time.sleep(wait_seconds + 1)
            continue

        raise RuntimeError(
            f"Telegram sendMessage failed (HTTP {response.status_code}): {description}. "
            "Check that the bot is not blocked and TELEGRAM_CHAT_ID is the private chat ID."
        )

    raise RuntimeError("Telegram sendMessage failed after rate-limit retries.")


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
        "contact_phone": "MYSHKA_PHONE",
        "salary_expectation": "MYSHKA_SALARY_EXPECTATION"
    }
    for field, env_name in env_fields.items():
        value = os.environ.get(env_name, "").strip()
        if value:
            profile[field] = value
    return profile


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


def vacancy_salary(job):
    """Return an explicitly advertised salary/rate, never an estimate."""
    for key in ("salary", "salary_text", "salary_range", "compensation"):
        value = as_text(job.get(key)).strip()
        if value:
            return value[:120]
    description = as_text(job.get("description"))
    patterns = (
        r"(?i)(?:salary|compensation|pay|rate|зарплат[аи]?|оплат[аи]?)\s*[:：-]?\s*"
        r"(?:(?:USD|EUR|GBP|UAH|\$|€|£)\s*)?\d[\d,.]*(?:\s*[-–—to]+\s*"
        r"(?:USD|EUR|GBP|UAH|\$|€|£)?\s*\d[\d,.]*)?"
        r"(?:\s*(?:USD|EUR|GBP|UAH|\$|€|£|per\s+(?:hour|month|year)|/\s*(?:hr|hour|mo|month|yr|year)))?",
        r"(?i)(?:USD|EUR|GBP|UAH|\$|€|£)\s*\d[\d,.]*(?:\s*[-–—]\s*"
        r"(?:USD|EUR|GBP|UAH|\$|€|£)?\s*\d[\d,.]*)?"
        r"(?:\s*(?:per\s+(?:hour|month|year)|/\s*(?:hr|hour|mo|month|yr|year)))?"
    )
    for pattern in patterns:
        match = re.search(pattern, description)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip()[:120]
    return "Не вказано"


def summarize_vacancy_description(raw_description):
    """Use APInex AI for a grounded two-sentence summary; fall back locally."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", as_text(raw_description)))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return "Роботодавець не надав опису вакансії. Деталі умов і вимог уточнюйте за посиланням."

    api_key = os.getenv("APINEX_API_KEY", "").strip()
    if api_key:
        try:
            response = requests.post(
                "https://api.apinex.bond/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": os.getenv("APINEX_MODEL", "free/deepseek-v4.1-flash"),
                    "temperature": 0.1,
                    "max_tokens": 180,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Summarize a job vacancy in exactly two concise sentences, "
                                "in Ukrainian. Preserve all important employer-provided facts: "
                                "responsibilities, requirements, skills, experience, work format, "
                                "schedule, contract and benefits. Do not invent or infer facts. "
                                "If a detail is absent, omit it. Output only the two sentences."
                            ),
                        },
                        {"role": "user", "content": text[:12000]},
                    ],
                },
                timeout=25,
            )
            response.raise_for_status()
            data = response.json()
            summary = data["choices"][0]["message"]["content"].strip()
            summary = re.sub(r"\s+", " ", summary)
            if summary and len(re.findall(r"[.!?](?:\s|$)", summary)) >= 2:
                return summary
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            print(f"APInex summary unavailable; using local fallback: {exc}")

    # Local fallback: select two useful source sentences without inventing facts.
    parts = re.split(r"(?<=[.!?])\s+|\s*[•▪●]\s*|\s+[-–—]\s+", text)
    sentences = [re.sub(r"^[-*\s]+", "", p).strip(" ;,") for p in parts]
    sentences = [p for p in sentences if len(p) > 18]
    if not sentences:
        sentences = [text]

    keywords = {
        "responsibilities": ("responsib", " задач", "обов'яз", "обов’яз", "створ", "розроб", "build", "create", "work on", "you will"),
        "requirements": ("require", "вимог", "must", "кандидат", "досвід", "experience", "skills", "навич", "знан"),
        "conditions": ("remote", "віддал", "графік", "schedule", "contract", "full-time", "part-time", "умов", "benefit", "оплач"),
        "compensation": ("salary", "зарплат", "оплат", "usd", "eur", "uah", "$", "€", "£"),
    }

    def score(sentence):
        lower = sentence.lower()
        coverage = sum(any(term in lower for term in terms) for terms in keywords.values())
        return coverage * 100 + min(len(sentence), 500) / 100

    if len(sentences) == 1:
        first = sentences[0].rstrip(".!?")
        return first + ". Детальні вимоги та умови — за посиланням."

    chosen = sorted(sorted(enumerate(sentences), key=lambda item: score(item[1]), reverse=True)[:2])
    result = []
    for _, sentence in chosen:
        sentence = sentence.strip()
        if sentence[-1:] not in ".!?":
            sentence += "."
        result.append(sentence)
    return " ".join(result)


def send_job_card(job, short_id):
    """Send a plain vacancy card with no buttons or application actions."""
    description = summarize_vacancy_description(job.get("description"))
    message = (
        f"🐭 <b>MYSHKA · {int(job.get('score') or 0)}/100</b>\n"
        f"💼 <b>{html.escape(as_text(job.get('title')) or 'Вакансія')}</b>\n"
        f"🏢 {html.escape(as_text(job.get('company')) or 'Компанію не вказано')}\n"
        f"🌍 {html.escape(as_text(job.get('location')) or 'Remote')}\n"
        f"💰 Оплата: <b>{html.escape(vacancy_salary(job))}</b>\n"
        f"📌 Джерело: {html.escape(as_text(job.get('source')) or 'не вказано')}\n"
        f"📝 {html.escape(description or 'Короткий опис не надано')}\n\n"
        f"🔗 <a href=\"{html.escape(as_text(job.get('url')), quote=True)}\">Відкрити вакансію</a>"
    )
    return send_telegram(message)
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
    # Persist only confirmed Telegram deliveries. Keep a separate in-run set
    # so duplicate sources are collapsed without marking unsent jobs as seen.
    applications = load_json(APPLICATIONS_PATH, {})
    # Rebuild the deduplication index only from vacancies whose Telegram
    # delivery was confirmed (message_id). Older button-era code could mark
    # a vacancy as seen before delivery, silently suppressing it forever.
    seen = set()
    for delivered_job in applications.values():
        if isinstance(delivered_job, dict) and delivered_job.get("message_id"):
            seen.update(job_identity_keys(delivered_job))
    scan_seen = set(seen)
    jobs = collect_jobs()
    matches = []
    rejection_counts = {}
    eligible_count = 0
    for job in jobs:
        score, reason = score_job(job)
        minimum_score = max(80, int(CONFIG.get("minimum_score", 80)))
        if score < minimum_score:
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            continue
        eligible_count += 1
        identity_keys = job_identity_keys(job)
        # Deduplicate by normalized URL AND by exact normalized title + company.
        # This also catches reposts mirrored across different job boards.
        if (
            as_text(job.get("title")).strip()
            and as_text(job.get("url")).strip()
            and identity_keys
            and not (identity_keys & scan_seen)
        ):
            primary_key = hashlib.sha256(
                ("myshka:" + "|".join(sorted(identity_keys))).encode("utf-8")
            ).hexdigest()
            matches.append((score, reason, primary_key, identity_keys, job))
            # Prevent duplicate listings within this scan, without persisting
            # them until Telegram confirms the corresponding message.
            scan_seen.update(identity_keys)

    matches.sort(key=lambda item: item[0], reverse=True)
    sent = 0
    for score, reason, key, identity_keys, job in matches:
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
        # send_telegram raises on HTTP/API errors; never mark this vacancy
        # as delivered unless Telegram returned a confirmed message object.
        telegram_message = send_job_card(stored_job, short_id)
        if not telegram_message or not telegram_message.get("message_id"):
            raise RuntimeError(
                f"Telegram did not confirm delivery for vacancy {short_id}; "
                "the vacancy remains unseen and will be retried on the next scan."
            )
        stored_job["message_id"] = telegram_message["message_id"]
        applications[short_id] = stored_job
        seen.update(identity_keys)
        save_json(APPLICATIONS_PATH, applications)
        save_json(SEEN_PATH, sorted(seen))
        sent += 1

    # Keep Telegram quiet between alerts. Warn only if every source failed.
    if not SOURCE_HEALTH or all(not item.get("ok") for item in SOURCE_HEALTH):
        send_telegram("⚠️ <b>MYSHKA JOB RADAR</b>\nНе вдалося отримати дані з жодного джерела. Перевірка повториться за розкладом.")
    print(f"Scanned {len(jobs)} listings; eligible {eligible_count}; sent {sent} new matches; saved {len(applications)} application records.")
    print("Top rejection reasons: " + json.dumps(dict(sorted(rejection_counts.items(), key=lambda item: item[1], reverse=True)[:8]), ensure_ascii=False))


if __name__ == "__main__":
    main()

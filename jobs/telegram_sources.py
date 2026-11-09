"""Public Telegram channel ingestion for MYSHKA JOB RADAR.

Reads only public t.me/s channel previews; it does not bypass Telegram access
controls or use private user sessions. Each post is treated as a lead and still
passes the normal paid/remote/Ukraine-eligibility and role relevance filters.
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "telegram_sources.json"
TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MYSHKA-JOB-RADAR/1.0)",
    "Accept": "text/html,application/xhtml+xml",
}

REMOTE_RE = re.compile(
    r"\b(remote|remotely|work from home|distributed|worldwide|anywhere|"
    r"віддален|дистанційн|удаленн|удалённ)\b", re.I
)
EXPLICITLY_EXCLUDED_SCOPE_RE = re.compile(
    r"\b(?:us|u\\.s\\.?|usa|united states|canada|australia)\\s+only\\b|"
    r"\bonly\\s+(?:in\\s+)?(?:us|u\\.s\\.?|usa|united states|canada|australia)\\b", re.I
)
UKRAINE_SCOPE_RE = re.compile(
    r"\b(ukraine|україн[а-яіїєґ]*|europe|european union|\beu\b|emea|"
    r"worldwide|anywhere|global)\b", re.I
)
TARGET_RE = re.compile(
    r"(3d|blender|game.?art|game.?asset|character artist|environment artist|"
    r"prop artist|technical artist|concept artist|illustrat|2d artist|"
    r"vfx|animator|мат худож|3d.?худож|3d.?модел|геймдев|ігров.*худож)",
    re.I,
)
ROLE_RE = re.compile(
    r"\b(artist|animator|illustrator|modeler|modeller|sculptor|"
    r"3d generalist|3d artist|2d artist|character artist|environment artist|"
    r"prop artist|technical artist|concept artist)\\b", re.I
)
UNPAID_RE = re.compile(
    r"\b(unpaid|volunteer|commission[- ]only|no salary|equity only)\b|"
    r"без\s+оплат|волонтерств|неоплачув", re.I
)
ROLE_TITLE_RE = re.compile(
    r"\b(?:(?:junior|trainee|middle|mid|senior|lead|principal)\s+)?"
    r"(?:(?:3d|2d|blender)\s+)?"
    r"(?:(?:character|environment|prop|game(?:\s+asset)?|technical|concept|level|"
    r"vehicle|hard.surface|texture|vfx|pixel|motion)\s+)?"
    r"(?:artist|animator|illustrator|modeler|modeller|generalist|sculptor)\b",
    re.I,
)
URL_RE = re.compile(r"https?://[^\s<>\])}]+", re.I)


class TelegramPostParser(HTMLParser):
    """Extract individual post cards from Telegram's public web preview."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts = []
        self.current = None
        self.div_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "")
        if tag == "div":
            if self.current is None and "tgme_widget_message_wrap" in classes:
                self.current = {"text": [], "links": [], "post": ""}
                self.div_depth = 1
                return
            if self.current is not None:
                self.div_depth += 1
                if attrs.get("data-post"):
                    self.current["post"] = attrs["data-post"]
        if self.current is not None and tag == "a":
            href = attrs.get("href", "")
            if href:
                self.current["links"].append(href)

    def handle_data(self, data):
        if self.current is not None and data.strip():
            self.current["text"].append(data.strip())

    def handle_endtag(self, tag):
        if tag == "div" and self.current is not None:
            self.div_depth -= 1
            if self.div_depth <= 0:
                post = self.current
                post["text"] = re.sub(r"\s+", " ", " ".join(post["text"])).strip()
                if post["text"]:
                    self.posts.append(post)
                self.current = None
                self.div_depth = 0


def _title_from_text(text):
    # Telegram posts may be digests; extract a role phrase, not the channel heading.
    match = ROLE_TITLE_RE.search(text)
    if match:
        prefix = text[max(0, match.start() - 28):match.start()]
        level = re.search(r"(junior|trainee|middle|mid|senior|lead|principal)\s*$", prefix, re.I)
        title = ((level.group(1) + " ") if level else "") + match.group(0)
        return re.sub(r"\s+", " ", title).strip()[:180]
    lines = [re.sub(r"\s+", " ", x).strip(" •—-\t") for x in text.splitlines()]
    lines = [x for x in lines if x and not re.fullmatch(r"(views?|переглядів?|\d+[кk]?)", x, re.I)]
    for line in lines[:12]:
        if TARGET_RE.search(line) and len(line) <= 180:
            return line[:180]
    for line in lines[:8]:
        if len(line) >= 5 and not line.startswith("#") and len(line) <= 180:
            return line[:180]
    return (text[:180] or "Telegram vacancy").strip()

def _post_url(post, username):
    value = post.get("post", "")
    if "/" in value:
        return "https://t.me/" + value
    return "https://t.me/" + username


def _job_url(post, post_url):
    candidates = list(post.get("links", [])) + URL_RE.findall(post.get("text", ""))
    for candidate in candidates:
        candidate = candidate.rstrip(".,;)")
        host = (urlparse(candidate).hostname or "").lower()
        if host and not (host == "t.me" or host.endswith(".telegram.me") or host.endswith(".telegram.org")):
            return candidate
    return post_url


def normalize_telegram_post(post, username):
    text = post.get("text", "")
    if not text or not TARGET_RE.search(text):
        return None
    if UNPAID_RE.search(text):
        return None

    # Keep uncertain geography as a lead for manual review. Exclude only
    # clearly incompatible country restrictions; a "Remote" post may omit
    # its hiring region, especially in short Telegram vacancy announcements.
    remote_match = REMOTE_RE.search(text)
    if not remote_match:
        return None
    if EXPLICITLY_EXCLUDED_SCOPE_RE.search(text):
        return None
    scope_match = UKRAINE_SCOPE_RE.search(text)
    if not scope_match:
        return None

    title = _title_from_text(text)
    post_url = _post_url(post, username)
    url = _job_url(post, post_url)
    location = "Remote — Ukraine/Europe eligibility stated"
    company_match = re.search(r"(?:company|компанія|студія)\s*[:—-]\s*([^\n|]{2,100})", text, re.I)
    company = company_match.group(1).strip() if company_match else ""

    return {
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "description": text[:12000],
        "tags": ["Telegram", "GameDev", "3D"],
        "relevance": "candidate",
        "source": f"Telegram @{username}",
        "remote": True,
        "source_post_url": post_url,
    }


def collect_telegram_channel_jobs(health=None):
    """Fetch the latest public posts from configured Telegram channels."""
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Telegram source config unavailable: {exc}")
        return []

    jobs = []
    seen_posts = set()
    for username in config.get("channels", []):
        username = str(username).strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9_]{5,64}", username):
            continue
        before = None
        for page_number in range(2):
            url = f"https://t.me/s/{username}"
            params = {"before": before} if before else None
            try:
                response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
                response.raise_for_status()
                html = response.text
            except requests.RequestException as exc:
                print(f"Telegram public channel unavailable @{username}: {type(exc).__name__}: {exc}")
                if health is not None:
                    health.append({"source": f"Telegram @{username}", "host": "t.me", "ok": False})
                break

            parser = TelegramPostParser()
            parser.feed(html)
            if health is not None and page_number == 0:
                health.append({"source": f"Telegram @{username}", "host": "t.me", "ok": True})

            if not parser.posts:
                break
            page_jobs = 0
            post_ids = []
            for post in parser.posts:
                post_key = post.get("post") or (username + "|" + post.get("text", "")[:200])
                if post_key in seen_posts:
                    continue
                seen_posts.add(post_key)
                if post.get("post") and "/" in post["post"]:
                    try:
                        post_ids.append(int(post["post"].rsplit("/", 1)[1]))
                    except ValueError:
                        pass
                job = normalize_telegram_post(post, username)
                if job:
                    jobs.append(job)
                    page_jobs += 1
            print(f"Telegram @{username}: inspected {len(parser.posts)} posts; {page_jobs} vacancy leads")
            if page_number == 0 and post_ids:
                before = min(post_ids)
            else:
                break
    print(f"Telegram public channels: collected {len(jobs)} eligible leads before normal scoring")
    return jobs

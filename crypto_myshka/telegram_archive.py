from __future__ import annotations

import json, re, time, html, hashlib, os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

try:
    from storage import sync_archive
except ImportError:
    from crypto_myshka.storage import sync_archive

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"data"/"telegram_archive.json"
UA={"User-Agent":"Mozilla/5.0 CryptoMyshka/2.1"}
MAX_PAGES_PER_CHANNEL=max(5, min(int(os.getenv("TELEGRAM_ARCHIVE_PAGES","80")), 150))

CHANNELS={
    "telegram_main":"it_statti",
    "telegram_airdrop":"it_statti_crypto",
}

def clean(s:str)->str:
    return re.sub(r"\s+"," ",html.unescape(s or "")).strip()

def parse_page(channel:str, raw:str):
    soup=BeautifulSoup(raw,"html.parser")
    rows=[]
    for w in soup.select(".tgme_widget_message_wrap"):
        msg=w.select_one(".tgme_widget_message")
        body=w.select_one(".tgme_widget_message_text")
        tm=w.select_one("time")
        if not msg:
            continue
        post=msg.get("data-post","")
        if not post or "/" not in post:
            continue
        try:
            post_id=int(post.rsplit("/",1)[1])
        except Exception:
            continue
        text=clean(body.get_text(" ",strip=True)) if body else ""
        rows.append({
            "id":hashlib.sha1(post.encode()).hexdigest()[:14],
            "post_id":post_id,
            "channel":channel,
            "text":text,
            "url":"https://t.me/"+post,
            "published_at":tm.get("datetime") if tm else None,
        })
    return rows

def fetch_page(channel:str, before:int|None=None):
    url=f"https://t.me/s/{channel}"
    if before:
        url += "?"+urlencode({"before":before})
    r=requests.get(url,headers=UA,timeout=25)
    r.raise_for_status()
    return parse_page(channel,r.text)

def load_existing():
    if not OUT.exists():
        return {"version":2,"channels":{},"posts":[]}
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return {"version":2,"channels":{},"posts":[]}

def merge_rows(rows, by_url):
    added=0
    for row in rows:
        url=row.get("url")
        if not url:
            continue
        if url not in by_url:
            added+=1
        by_url[url]=row
    return added

def channel_posts(channel, by_url):
    return [p for p in by_url.values() if p.get("channel")==channel and isinstance(p.get("post_id"),int)]

def crawl_older(channel:str, by_url:dict[str,dict], state:dict):
    existing=channel_posts(channel,by_url)
    before=min((p["post_id"] for p in existing), default=None)
    pages=0
    added=0
    complete=bool(state.get("complete",False))

    # Always refresh the live edge so archive also receives new posts.
    latest=fetch_page(channel)
    pages+=1
    added+=merge_rows(latest,by_url)

    # If we already reached the beginning of the channel, only the live refresh is needed.
    if complete:
        allp=channel_posts(channel,by_url)
        return added,pages,min((p["post_id"] for p in allp),default=None),True

    # Recalculate the oldest known id after live refresh.
    allp=channel_posts(channel,by_url)
    before=min((p["post_id"] for p in allp), default=None)

    # First ever run: latest page is already page 1, continue from its oldest id.
    if before is None and latest:
        before=min(p["post_id"] for p in latest)

    while before and pages < MAX_PAGES_PER_CHANNEL:
        rows=fetch_page(channel,before)
        pages+=1
        if not rows:
            complete=True
            break

        ids=[r["post_id"] for r in rows if isinstance(r.get("post_id"),int)]
        if not ids:
            complete=True
            break

        page_min=min(ids)
        # Telegram sometimes returns the same boundary page. Prevent loops.
        if page_min >= before:
            complete=True
            break

        added+=merge_rows(rows,by_url)
        before=page_min
        time.sleep(0.12)

    allp=channel_posts(channel,by_url)
    earliest=min((p["post_id"] for p in allp), default=None)
    return added,pages,earliest,complete

def main():
    state=load_existing()
    posts=state.get("posts") or []
    by_url={p.get("url"):p for p in posts if p.get("url")}
    old_stats=state.get("channels") or {}
    stats={}

    for source,channel in CHANNELS.items():
        try:
            prev=old_stats.get(source) or {}
            added,pages,earliest,complete=crawl_older(channel,by_url,prev)
            total=len(channel_posts(channel,by_url))
            stats[source]={
                "channel":channel,
                "ok":True,
                "added":added,
                "archived":total,
                "pages_scanned":pages,
                "earliest_post_id_seen":earliest,
                "complete":complete,
            }
        except Exception as e:
            prev=old_stats.get(source) or {}
            stats[source]={
                **prev,
                "channel":channel,
                "ok":False,
                "error":str(e)[:300],
            }

    posts=list(by_url.values())
    posts.sort(key=lambda p:(p.get("published_at") or "",p.get("post_id") or 0),reverse=True)
    payload={
        "version":2,
        "updated_at":datetime.now(timezone.utc).isoformat(),
        "channels":stats,
        "postgres":db_count,
        "post_count":len(posts),
        "complete":all(bool((stats.get(k) or {}).get("complete")) for k in CHANNELS),
        "posts":posts,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    db_count=sync_archive(payload)
    print(json.dumps({
        "post_count":len(posts),
        "complete":payload["complete"],
        "channels":stats,
    },ensure_ascii=False))

if __name__=="__main__":
    main()

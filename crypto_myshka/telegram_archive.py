from __future__ import annotations

import json, re, time, html, hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"data"/"telegram_archive.json"
UA={"User-Agent":"Mozilla/5.0 CryptoMyshka/2.0"}

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
        if not msg: continue
        post=msg.get("data-post","")
        if not post or "/" not in post: continue
        try: post_id=int(post.rsplit("/",1)[1])
        except Exception: continue
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
    if not OUT.exists(): return {"version":1,"channels":{},"posts":[]}
    try: return json.loads(OUT.read_text(encoding="utf-8"))
    except Exception: return {"version":1,"channels":{},"posts":[]}

def crawl_channel(channel:str, existing_by_url:dict[str,dict], max_pages=450):
    all_rows=[]
    before=None
    pages=0
    consecutive_known_pages=0
    min_seen=None
    while pages<max_pages:
        rows=fetch_page(channel,before)
        pages+=1
        if not rows: break

        new_count=0
        ids=[]
        for row in rows:
            ids.append(row["post_id"])
            if row["url"] not in existing_by_url:
                existing_by_url[row["url"]]=row
                all_rows.append(row)
                new_count+=1

        page_min=min(ids) if ids else None
        if page_min is None or page_min==min_seen: break
        min_seen=page_min

        if new_count==0:
            consecutive_known_pages+=1
        else:
            consecutive_known_pages=0

        # Once archive already exists, two fully-known pages mean we've rejoined history.
        if consecutive_known_pages>=2:
            break

        before=page_min
        time.sleep(0.08)

    return all_rows,pages,min_seen

def main():
    state=load_existing()
    posts=state.get("posts") or []
    by_url={p.get("url"):p for p in posts if p.get("url")}
    stats={}

    for source,channel in CHANNELS.items():
        added,pages,earliest=crawl_channel(channel,by_url)
        stats[source]={
            "channel":channel,
            "added":len(added),
            "pages_scanned":pages,
            "earliest_post_id_seen":earliest,
        }

    posts=list(by_url.values())
    posts.sort(key=lambda p:(p.get("published_at") or "",p.get("post_id") or 0),reverse=True)
    payload={
        "version":1,
        "updated_at":datetime.now(timezone.utc).isoformat(),
        "channels":stats,
        "post_count":len(posts),
        "posts":posts,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"post_count":len(posts),"channels":stats},ensure_ascii=False))

if __name__=="__main__":
    main()

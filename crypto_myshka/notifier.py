from __future__ import annotations

import json, os
from pathlib import Path

import requests

try:
    from storage import (
        enabled as db_enabled,
        load_notification_state,
        save_notification_state,
        delivered_notification_ids,
        mark_notification_delivered,
    )
except ImportError:
    from crypto_myshka.storage import (
        enabled as db_enabled,
        load_notification_state,
        save_notification_state,
        delivered_notification_ids,
        mark_notification_delivered,
    )

ROOT=Path(__file__).resolve().parent
FEED=ROOT/"data"/"feed.json"
NEWS=ROOT/"data"/"news.json"
STATE=ROOT/"data"/"notify_state.json"

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","").strip()

def load(path, default):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default

def save(state):
    # Keep JSON as a portable fallback/export, but PostgreSQL becomes the
    # authoritative notification memory when DATABASE_URL is configured.
    STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    if db_enabled():
        save_notification_state(state)

def load_state(default):
    file_state=load(STATE,default)
    if not db_enabled():
        return file_state
    db_state=load_notification_state({})
    if db_state:
        return db_state
    # First PostgreSQL run: migrate the existing JSON state so old items are
    # not re-sent as a giant backlog.
    save_notification_state(file_state)
    return file_state

def label(item):
    risk=item.get("risk")
    if isinstance(risk,(int,float)):
        return "Низький ризик" if risk<45 else "Середній ризик" if risk<70 else "Високий ризик"
    return item.get("impact_label") or "Контекст"

def short(item):
    src=item.get("source","")
    icon={"telegram_main":"📨","telegram_airdrop":"🪂","youtube":"🎬","jev_analysis":"🧠"}.get(src,"🐭")
    title=(item.get("title") or "Новий матеріал").strip()
    if len(title)>115: title=title[:112]+"…"
    extra=""
    if item.get("assets"):
        extra=" · "+", ".join(item["assets"][:4])
    ai=item.get("jev_ai") or {}
    conclusion=(ai.get("short_conclusion") or "").strip()
    if conclusion:
        return f"{icon} {title}\n{label(item)}{extra}\nJEV: {conclusion}\n{item.get('url','')}"
    return f"{icon} {title}\n{label(item)}{extra}\n{item.get('url','')}"

def send(text):
    r=requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id":CHAT_ID,"text":text,"disable_web_page_preview":True},
        timeout=20
    )
    r.raise_for_status()

def main():
    feed=load(FEED,{"items":[]})
    news=load(NEWS,{"items":[]})
    current=[]
    for x in feed.get("items") or []:
        if x.get("source") in {"telegram_main","telegram_airdrop","youtube"}:
            current.append(x)
    for x in news.get("items") or []:
        if int(x.get("impact") or 0)>=2:
            current.append(x)

    ids=[x.get("id") for x in current if x.get("id")]
    state=load_state({"initialized":False,"seen":[],"telegram_ready":False})
    seen=set(state.get("seen") or [])
    if db_enabled():
        seen.update(delivered_notification_ids(ids))

    configured=bool(TOKEN and CHAT_ID)

    if not state.get("initialized"):
        initialized_seen=ids[-3000:]
        if db_enabled():
            mark_notification_delivered(initialized_seen)
        save({
            "initialized":True,
            "seen":initialized_seen,
            "telegram_ready":False
        })
        print(f"Notification state initialized with {len(ids)} existing items; no old spam sent.")
        return

    if configured and not state.get("telegram_ready"):
        try:
            send("🐭 Криптомишка підключена. Нові матеріали ITstatti, ретродропи, YouTube та важливі JEV-події приходитимуть сюди автоматично.")
            state["telegram_ready"]=True
            print("Telegram connection test sent.")
        except Exception as e:
            print(f"Telegram connection test failed: {e}")

    fresh=[x for x in current if x.get("id") and x.get("id") not in seen]
    # oldest first for a readable digest, max 6 to avoid spam
    fresh=list(reversed(fresh[:6]))

    sent_ids=[]
    if fresh and configured:
        body="🐭 Криптомишка: нове\n\n"+"\n\n".join(short(x) for x in fresh)
        send(body)
        sent_ids=[x.get("id") for x in fresh if x.get("id")]
        if db_enabled():
            mark_notification_delivered(sent_ids)
        print(f"Sent {len(fresh)} new items")
    elif fresh:
        print(f"{len(fresh)} new items found, but TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are not configured. Keeping them unseen.")
    else:
        print("No new notification-worthy items.")

    # Mark only successfully delivered items. This prevents a broken Telegram
    # connection from silently losing alerts.
    if sent_ids:
        seen.update(sent_ids)
    save({
        "initialized":True,
        "seen":list(seen)[-5000:],
        "telegram_ready":bool(state.get("telegram_ready"))
    })

if __name__=="__main__":
    main()

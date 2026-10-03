from __future__ import annotations

import json, os
from pathlib import Path

import requests

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
    STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")

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
    state=load(STATE,{"initialized":False,"seen":[],"telegram_ready":False})
    seen=set(state.get("seen") or [])

    configured=bool(TOKEN and CHAT_ID)

    if not state.get("initialized"):
        save({
            "initialized":True,
            "seen":ids[-3000:],
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

    sent=False
    if fresh and configured:
        body="🐭 Криптомишка: нове\n\n"+"\n\n".join(short(x) for x in fresh)
        send(body)
        sent=True
        print(f"Sent {len(fresh)} new items")
    elif fresh:
        print(f"{len(fresh)} new items found, but TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are not configured. Keeping them unseen.")
    else:
        print("No new notification-worthy items.")

    # Never mark fresh items as seen if Telegram is not configured or sending failed.
    if configured:
        seen.update(ids)
    save({
        "initialized":True,
        "seen":list(seen)[-5000:],
        "telegram_ready":bool(state.get("telegram_ready"))
    })

if __name__=="__main__":
    main()

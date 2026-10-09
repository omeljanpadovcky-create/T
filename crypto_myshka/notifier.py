from __future__ import annotations

import json, os, re
from pathlib import Path
from datetime import datetime, timezone, timedelta

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

try:
    from signal_gate import evaluate as evaluate_signal
except ImportError:
    from crypto_myshka.signal_gate import evaluate as evaluate_signal

ROOT=Path(__file__).resolve().parent
FEED=ROOT/"data"/"feed.json"
NEWS=ROOT/"data"/"news.json"
LIVE=ROOT/"data"/"youtube_live.json"
REPORTS=ROOT/"data"/"pair_reports.json"
YOUTUBE_CONTEXT=ROOT/"data"/"youtube_analysts.json"
VIDEO_LIBRARY=ROOT/"data"/"youtube_archive.json"
STATE=ROOT/"data"/"notify_state.json"

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID","").strip()
TEST_ONLY=os.getenv("TELEGRAM_TEST_ONLY","").strip().lower() in {"1","true","yes","on"}

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

def send_items(items, max_chars=3800):
    sent_ids=[]
    group=[]
    size=len("🐭 Криптомишка: нове\n\n")
    for item in items:
        block=short(item)
        extra=len(block)+(2 if group else 0)
        if group and size+extra>max_chars:
            send("🐭 Криптомишка: нове\n\n"+"\n\n".join(short(x) for x in group))
            sent_ids.extend(x.get("id") for x in group if x.get("id"))
            group=[]
            size=len("🐭 Криптомишка: нове\n\n")
        group.append(item)
        size+=extra
    if group:
        send("🐭 Криптомишка: нове\n\n"+"\n\n".join(short(x) for x in group))
        sent_ids.extend(x.get("id") for x in group if x.get("id"))
    return sent_ids


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

    # Append verified LIVE observations and JEV pair reports to the existing
    # Telegram digest; unknown/unverified channels are never advertised.
    live=load(LIVE,{})
    for channel in live.get("channels",[]) or []:
        if not isinstance(channel,dict) or channel.get("live") is not True or channel.get("status") != "LIVE":
            continue
        # Only announce an actual, recently checked video. A channel /videos
        # page or stale status is not confirmation of a current LIVE stream.
        try:
            checked=datetime.fromisoformat(str(channel.get("checked_at") or "").replace("Z","+00:00"))
            if checked.tzinfo is None or not timedelta(0) <= datetime.now(timezone.utc)-checked <= timedelta(minutes=20):
                continue
        except (ValueError, TypeError):
            continue
        stream=channel.get("stream") or {}
        if not isinstance(stream,dict):
            continue
        video_id=str(stream.get("video_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}",video_id):
            continue
        url="https://www.youtube.com/watch?v="+video_id
        name=channel.get("name") or channel.get("handle") or "YouTube"
        current.append({"id":"live:"+str(channel.get("id") or "")+":"+video_id,"source":"youtube",
                        "title":"🔴 LIVE підтверджено: "+name,
                        "url":url,"impact_label":"Трансляція; дії трейдера не перевірені"})
    reports=load(REPORTS,{})
    for report in reports.get("reports",[]) or []:
        if not isinstance(report,dict): continue
        pair=str(report.get("pair") or "").strip()
        observed=str(report.get("observed_at") or "")
        if not pair or not observed or report.get("demo") or report.get("confidence") in ("none","unknown"): continue
        # A report from YouTube alone must NEVER become a Telegram signal.
        # Re-evaluate at send time to reject stale reports, including old JSON.
        if evaluate_signal(report)["decision"] != "REVIEW_ONLY":
            continue
        jev=report.get("jev") or {}
        conclusion=str(jev.get("why") or "").strip()[:450]
        current.append({"id":"jev:"+pair+":"+observed,"source":"jev_analysis",
                        "title":"JEV · на ручну перевірку (НЕ СИГНАЛ): "+pair+" · "+str(report.get("trend") or "невизначено"),
                        "risk":80 if report.get("confidence")=="low" else 60,
                        "jev_ai":{"short_conclusion":(conclusion or "Потрібна перевірка котирувань.")+" Не автоматична угода."},
                        "url":str(report.get("video_url") or report.get("source_url") or "")})

    # Educational content from already published YouTube videos:
    # this is NOT a livestream watch or an independently validated trading signal.
    youtube_context=load(YOUTUBE_CONTEXT,{})
    for channel in youtube_context.get("channels",[]) or []:
        if not isinstance(channel,dict) or not channel.get("confirmed"):
            continue
        for video in (channel.get("videos") or [])[:8]:
            if not isinstance(video,dict) or video.get("sample_only"):
                continue
            vid=str(video.get("id") or "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}",vid):
                continue
            analysis=video.get("analysis") if isinstance(video.get("analysis"),dict) else {}
            pairs=analysis.get("mentioned_instruments") or analysis.get("pairs") or []
            indicators=analysis.get("mentioned_indicators") or []
            description=[]
            if pairs: description.append("Згадані пари: "+", ".join(str(v) for v in pairs[:4]))
            if indicators: description.append("Індикатори: "+", ".join(str(v) for v in indicators[:4]))
            if analysis.get("otc_flag"): description.append("OTC — котирування не підтверджені")
            description.append("Ідея автора, не перевірений прогноз")
            current.append({
                "id":"youtube_content:"+vid,"source":"youtube",
                "title":"Матеріал "+str(channel.get("name") or "YouTube")+": "+str(video.get("title") or "")[:95],
                "url":"https://www.youtube.com/watch?v="+vid,
                "impact_label":"; ".join(description)[:280],
            })

    # Only actually completed AI analyses, not thumbnails/metadata or fake
    # 100% win-rate claims. Send each video once per method via existing dedupe.
    library=load(VIDEO_LIBRARY,{"videos":[]})
    for video in (library.get("videos") or []):
        if not isinstance(video,dict):
            continue
        vid=str(video.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}",vid):
            continue
        vgem=video.get("gemini") or {}
        if isinstance(vgem,dict) and vgem.get("status")=="gemini_video_summary":
            current.append({
                "id":"youtube_gemini_video:"+vid,
                "source":"youtube",
                "title":"✦ Gemini розібрав ВІДЕО: "+str(video.get("title") or "")[:96],
                "url":"https://www.youtube.com/watch?v="+vid,
                "impact_label":"Аналіз кадрів і звуку. Висновки AI, не перевірений сигнал",
                "jev_ai":{"short_conclusion":str(vgem.get("summary") or "")[:285]},
            })
        vjev=video.get("jev") or {}
        if isinstance(vjev,dict) and vjev.get("status")=="model_summary" and not (isinstance(vgem,dict) and vgem.get("status")=="gemini_video_summary"):
            current.append({
                "id":"youtube_jev:"+vid,
                "source":"youtube",
                "title":"🧠 JEV розібрав субтитри: "+str(video.get("title") or "")[:100],
                "url":"https://www.youtube.com/watch?v="+vid,
                "impact_label":"Конспект доступних субтитрів; не підтверджує прибутковість",
                "jev_ai":{"short_conclusion":str(vjev.get("summary") or "")[:285]},
            })

    ids=[x.get("id") for x in current if x.get("id")]
    state=load_state({"initialized":False,"seen":[],"telegram_ready":False})
    seen=set(state.get("seen") or [])
    if db_enabled():
        seen.update(delivered_notification_ids(ids))

    configured=bool(TOKEN and CHAT_ID)

    if TEST_ONLY:
        if not configured:
            raise SystemExit("Telegram test failed: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are not configured.")
        if not state.get("telegram_ready"):
            send("🐭 Криптомишка: тест Telegram — зв’язок працює ✅")
            state["telegram_ready"]=True
            save(state)
            print("Telegram test message sent successfully.")
        else:
            print("Telegram test-only mode: connection was already confirmed.")
        return

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
    # Reserve room for newly completed Gemini video reports; other headlines
    # remain in the queue if this digest reaches six items.
    gemini_fresh=[x for x in fresh if str(x.get("id")).startswith("youtube_gemini_video:")]
    other_fresh=[x for x in fresh if not str(x.get("id")).startswith("youtube_gemini_video:")]
    fresh=list(reversed(gemini_fresh[:3]+other_fresh[:max(0,6-min(3,len(gemini_fresh)))]))

    sent_ids=[]
    if fresh and configured:
        sent_ids=send_items(fresh)
        if db_enabled():
            mark_notification_delivered(sent_ids)
        print(f"Sent {len(sent_ids)} new items")
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

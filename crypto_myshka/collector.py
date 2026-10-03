from __future__ import annotations

import json, re, html, hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "feed.json"
UA = {"User-Agent": "Mozilla/5.0 CryptoMyshka/2.0"}

SOURCES = {
    "telegram_main": "https://t.me/s/it_statti",
    "telegram_airdrop": "https://t.me/s/it_statti_crypto",
    "site": "https://itstatti.in.ua/treidinh.html",
    "youtube": "https://www.youtube.com/@it_statti/videos",
}

def get(url: str) -> str:
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    return r.text

def clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

def classify(text: str) -> tuple[str, int, list[str]]:
    t = text.lower()
    reasons=[]
    if any(k in t for k in ["airdrop","аірдроп","ретродроп","launchpool","лаунчпул","launchpad","токенсейл","testnet","тестнет","ноди","promo","промк"]):
        mode="opportunities"; risk=35
        reasons.append("подія/активність, а не ринкова ставка")
    elif any(k in t for k in ["ф'ючерс","ф’ючерс","long","short","лонг","шорт","стоп","тейк","памп","позиці"]):
        mode="trading"; risk=80
        reasons.append("активна торгівля/позиція")
    elif any(k in t for k in ["портфель","інвест","докуп","купівля","булран","dca"]):
        mode="portfolio"; risk=55
        reasons.append("портфельна/довша теза")
    else:
        mode="speculation"; risk=65
        reasons.append("криптоідея без чіткої портфельної рамки")

    if any(k in t for k in ["x10","х10","x5","х5","+500","+800","мемкоін","memecoin"]):
        risk=min(95,risk+15); reasons.append("агресивний потенціал/волатильність")
    if any(k in t for k in ["1-2%","ризик менедж","стоп-лосс","стоп лосс"]):
        risk=max(20,risk-10); reasons.append("є згадка ризик-менеджменту")
    if any(k in t for k in ["не фінансова порада","не финансовая рекомендация"]):
        reasons.append("автор позначає матеріал як не фінансову пораду")
    return mode,risk,reasons

def telegram(url: str, source: str, limit=20):
    soup=BeautifulSoup(get(url),"html.parser")
    out=[]
    for w in soup.select(".tgme_widget_message_wrap")[-limit:][::-1]:
        msg=w.select_one(".tgme_widget_message")
        body=w.select_one(".tgme_widget_message_text")
        time=w.select_one("time")
        if not msg or not body: continue
        text=clean(body.get_text(" ",strip=True))
        post=msg.get("data-post","")
        link="https://t.me/"+post if post else url.replace("/s/","/")
        mode,risk,reasons=classify(text)
        out.append({
            "id": hashlib.sha1((source+link).encode()).hexdigest()[:14],
            "source":source,"mode":mode,"risk":risk,"reasons":reasons,
            "title": text[:120] + ("…" if len(text)>120 else ""),
            "summary": text[:700],
            "url":link,
            "published_at": time.get("datetime") if time else None
        })
    return out

def site_items(limit=14):
    soup=BeautifulSoup(get(SOURCES["site"]),"html.parser")
    out=[]; seen=set()
    for a in soup.select("a"):
        title=clean(a.get_text(" ",strip=True))
        href=a.get("href")
        if not href or len(title)<18: continue
        url=urljoin(SOURCES["site"],href)
        if "itstatti.in.ua" not in url or url in seen: continue
        seen.add(url)
        if not any(k in title.lower() for k in ["трейд","аналіз","ризик","стоп","ф'ючер","ф’ючер","маржин","плеч","портф","крипт"]):
            continue
        mode,risk,reasons=classify(title)
        out.append({"id":hashlib.sha1(url.encode()).hexdigest()[:14],"source":"site",
                    "mode":mode,"risk":risk,"reasons":reasons,"title":title,
                    "summary":"Матеріал із бази знань ITstatti.","url":url,"published_at":None})
        if len(out)>=limit: break
    return out

def youtube_items(limit=12):
    raw=get(SOURCES["youtube"])
    out=[]; seen=set()
    # YouTube embeds title+videoId repeatedly in page JSON.
    for m in re.finditer(r'"videoId":"([A-Za-z0-9_-]{11})".{0,900}?"title":\{"runs":\[\{"text":"(.*?)"\}', raw):
        vid,title=m.group(1),clean(m.group(2).encode("utf-8").decode("unicode_escape","ignore"))
        if vid in seen or not title: continue
        seen.add(vid)
        url=f"https://www.youtube.com/watch?v={vid}"
        mode,risk,reasons=classify(title)
        out.append({"id":hashlib.sha1(url.encode()).hexdigest()[:14],"source":"youtube",
                    "mode":mode,"risk":risk,"reasons":reasons,"title":title,
                    "summary":"Відео ITstatti — контекст для перевірки тези.","url":url,"published_at":None})
        if len(out)>=limit: break
    return out

def market():
    try:
        data=requests.get("https://api.coingecko.com/api/v3/simple/price",params={
            "ids":"bitcoin,ethereum,optimism","vs_currencies":"usd","include_24hr_change":"true"
        },headers=UA,timeout=20).json()
        return data
    except Exception as e:
        return {"error":str(e)}

def main():
    items=[]; status={}
    for key in ["telegram_main","telegram_airdrop"]:
        try:
            got=telegram(SOURCES[key],key); items+=got; status[key]={"ok":True,"count":len(got),"url":SOURCES[key].replace("/s/","/")}
        except Exception as e: status[key]={"ok":False,"error":str(e),"url":SOURCES[key]}
    try:
        got=site_items(); items+=got; status["site"]={"ok":True,"count":len(got),"url":SOURCES["site"]}
    except Exception as e: status["site"]={"ok":False,"error":str(e),"url":SOURCES["site"]}
    try:
        got=youtube_items(); items+=got; status["youtube"]={"ok":True,"count":len(got),"url":"https://www.youtube.com/@it_statti"}
    except Exception as e: status["youtube"]={"ok":False,"error":str(e),"url":"https://www.youtube.com/@it_statti"}

    payload={
        "version":2,
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "sources":status,
        "market":market(),
        "items":items,
        "disclaimer":"Аналітичний фільтр. Не виконує угоди й не є фінансовою порадою."
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"wrote {len(items)} items -> {OUT}")

if __name__=="__main__":
    main()

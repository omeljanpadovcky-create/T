from __future__ import annotations

import json, re, html, hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from yt_dlp import YoutubeDL

try:
    from storage import sync_feed
except ImportError:
    from crypto_myshka.storage import sync_feed

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "feed.json"
ARCHIVE = ROOT / "data" / "telegram_archive.json"
NEWS = ROOT / "data" / "news.json"
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

    # Safety priority: derivatives/leverage must never be downgraded merely
    # because the same post also contains the words promo/airdrop.
    derivative_terms = [
        "cfd", "perp option", "perp options", "perpetual", "options", "option",
        "опціон", "ф'ючерс", "ф’ючерс", "фючерс", "futures", "future",
        "leverage", "плеч", "margin", "марж", "xauusd", " lot"
    ]
    opportunity_terms = [
        "airdrop","аірдроп","ретродроп","launchpad","токенсейл",
        "testnet","тестнет","ноди","promo","промк"
    ]
    launchpool_terms = ["launchpool","лаунчпул","poolx"]
    trade_required_terms = [
        "spot-трейд", "spot trade", "торговий обсяг", "торгівельний обсяг",
        "торгуємо", "зробити перший", "trade ", "трейд"
    ]
    stable_assets = {"usdt","usdc","dai","fdusd","usde","usds","tusd"}

    if any(k in t for k in derivative_terms):
        mode="trading"; risk=90
        reasons.append("деривативи/плече: потрібна перевірка max loss, margin і ліквідації")

    elif any(k in t for k in launchpool_terms):
        mode="opportunities"
        pool_assets = re.findall(r"(?:пул|pool)\s+([a-z0-9]{2,15})", t)
        nonstable_pools = [x.upper() for x in pool_assets if x not in stable_assets]

        if nonstable_pools:
            risk=55
            reasons.append("Launchpool із кількома пулами: stablecoin-пул має нижчий price risk, токен-пули — вищий")
            reasons.append("ризик ціни застейканого активу: " + ", ".join(nonstable_pools[:4]))
        else:
            risk=35
            reasons.append("Launchpool/staking без плеча; перевірити умови та доступний пул")

        if "apr" in t:
            reasons.append("APR річний і плаваючий; це не гарантований прибуток за період акції")

        if any(k in t for k in trade_required_terms):
            risk=max(risk,55)
            reasons.append("для участі/ліміту може вимагатися торговий обсяг")

    elif any(k in t for k in opportunity_terms):
        mode="opportunities"; risk=35
        reasons.append("подія/активність, а не пряма ринкова ставка")
        if any(k in t for k in trade_required_terms):
            risk=55
            reasons.append("промо вимагає торгівлі/обсягу; винагорода не гарантована")

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

def site_items():
    """Collect the full curated ITstatti trading knowledge base, not a small sample."""
    soup=BeautifulSoup(get(SOURCES["site"]),"html.parser")
    out=[]; seen=set()
    for a in soup.select("a[href]"):
        title=clean(a.get_text(" ",strip=True))
        href=a.get("href")
        if not href or len(title)<8:
            continue
        url=urljoin(SOURCES["site"],href).split("#",1)[0]
        if "itstatti.in.ua" not in url or url in seen:
            continue

        # ITstatti article URLs use a numeric article id in the path
        # (e.g. /15-treidinh/969-demo-rakhunok...). This excludes menu/category links.
        from urllib.parse import urlparse
        path=urlparse(url).path
        if not re.search(r"/\d+[-/]", path):
            continue

        seen.add(url)
        mode,risk,reasons=classify(title)
        reasons.append("матеріал з повної навчальної бази ITstatti")
        out.append({
            "id":hashlib.sha1(url.encode()).hexdigest()[:14],
            "source":"site",
            "mode":mode,
            "risk":risk,
            "reasons":reasons,
            "title":title,
            "summary":"Матеріал із повної бази знань ITstatti. Використовується як методологія/контекст, а не як торговий сигнал.",
            "url":url,
            "published_at":None,
            "knowledge":True
        })
    return out

def youtube_items():
    """Load the whole public channel catalog. Videos are context, not auto-trade signals."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "playlistreverse": False,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(SOURCES["youtube"], download=False) or {}

    out=[]; seen=set()
    for e in info.get("entries") or []:
        if not e: continue
        vid=e.get("id")
        title=clean(e.get("title") or "")
        if not vid or not title or vid in seen: continue
        seen.add(vid)
        url=e.get("webpage_url") or e.get("url") or f"https://www.youtube.com/watch?v={vid}"
        if not str(url).startswith("http"):
            url=f"https://www.youtube.com/watch?v={vid}"
        mode,risk,reasons=classify(title)
        reasons.append("YouTube використовується як контекст/методологія, не як прямий сигнал")
        ts=e.get("timestamp")
        published_at=None
        if ts:
            try:
                published_at=datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            except Exception:
                published_at=None
        out.append({
            "id": hashlib.sha1(("youtube"+vid).encode()).hexdigest()[:14],
            "source": "youtube",
            "mode": mode,
            "risk": risk,
            "reasons": reasons,
            "title": title,
            "summary": "Відео ITstatti. Мишка використовує його як контекст для інвестицій, трейдингу, ризику та криптоможливостей.",
            "url": url,
            "published_at": published_at,
            "video_id": vid,
            "knowledge": True
        })
    return out

COINGECKO = {
    "BTC":"bitcoin","ETH":"ethereum","OP":"optimism","SOL":"solana","PENDLE":"pendle",
    "ARB":"arbitrum","LDO":"lido-dao","ICP":"internet-computer","STG":"stargate-finance",
    "TWT":"trust-wallet-token","ENS":"ethereum-name-service","LTC":"litecoin","XRP":"ripple",
    "BNB":"binancecoin","DOGE":"dogecoin","ADA":"cardano","AVAX":"avalanche-2","LINK":"chainlink"
}

def mentioned_assets(items):
    text=" ".join((x.get("title","")+" "+x.get("summary","")) for x in items[:80]).lower()
    out=["BTC","ETH"]
    aliases={
        "OP":[" optimism "," op "],"SOL":[" solana "," sol "],"PENDLE":["pendle"],
        "ARB":["arbitrum"," arb "],"LDO":["lido"," ldo "],"ICP":["internet computer"," icp "],
        "STG":["stargate"," stg "],"TWT":["trust wallet"," twt "],"ENS":[" ens "],
        "LTC":["litecoin"," ltc "],"XRP":["xrp","ripple"],"BNB":["bnb","binance coin"],
        "DOGE":["dogecoin"," doge "],"ADA":["cardano"," ada "],"AVAX":["avalanche"," avax "],
        "LINK":["chainlink"," link "],
    }
    padded=" "+text+" "
    for sym,keys in aliases.items():
        if any(k in padded for k in keys) and sym not in out:
            out.append(sym)
    return out[:8]

def market(items):
    try:
        syms=mentioned_assets(items)
        ids=[COINGECKO[s] for s in syms if s in COINGECKO]
        data=requests.get("https://api.coingecko.com/api/v3/simple/price",params={
            "ids":",".join(ids),"vs_currencies":"usd","include_24hr_change":"true"
        },headers=UA,timeout=20).json()
        return {"symbols":syms,"prices":data}
    except Exception as e:
        return {"error":str(e),"symbols":["BTC","ETH"],"prices":{}}

def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

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

    archive=read_json(ARCHIVE,{"post_count":0})
    news=read_json(NEWS,{"item_count":0})
    status["telegram_archive"]={
        "ok":bool(archive.get("post_count",0)),
        "count":archive.get("post_count",0),
        "complete":bool(archive.get("complete",False)),
        "updated_at":archive.get("updated_at"),
        "url":"https://t.me/it_statti"
    }
    status["jev_news"]={
        "ok":bool(news.get("item_count",0)),
        "count":news.get("item_count",0),
        "url":"crypto_myshka/data/news.json"
    }

    payload={
        "version":3,
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "sources":status,
        "market":market([x for x in items if not x.get("knowledge")] + (news.get("items") or [])[:80]),
        "items":items,
        "archive_count":archive.get("post_count",0),
        "news_count":news.get("item_count",0),
        "disclaimer":"Аналітичний фільтр. Не виконує угоди й не є фінансовою порадою."
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    db_count=sync_feed(payload)
    print(f"wrote {len(items)} items -> {OUT}; postgres={db_count}")

if __name__=="__main__":
    main()

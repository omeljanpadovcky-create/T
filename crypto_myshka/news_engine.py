from __future__ import annotations

import hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"data"/"news.json"

FEEDS={
    "CoinDesk":"https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph":"https://cointelegraph.com/rss",
    "Decrypt":"https://decrypt.co/feed",
    "The Block":"https://www.theblock.co/rss.xml",
    "Bloomberg Crypto":"https://feeds.bloomberg.com/crypto/news.rss",
    "FT Crypto":"https://www.ft.com/crypto?format=rss",
    "Google News Crypto":"https://news.google.com/rss/search?q=(bitcoin+OR+ethereum+OR+crypto+OR+blockchain+OR+stablecoin+OR+defi+OR+solana+OR+altcoin)+when:1d&hl=en-US&gl=US&ceid=US:en",
}

ASSETS={
    "BTC":["bitcoin"," btc "],
    "ETH":["ethereum"," ether "," eth "],
    "SOL":["solana"," sol "],
    "XRP":["xrp","ripple"],
    "BNB":["bnb","binance coin"],
    "OP":["optimism"," op "],
    "ARB":["arbitrum"," arb "],
    "PENDLE":["pendle"],
    "DOGE":["dogecoin"," doge "],
    "ADA":["cardano"," ada "],
    "AVAX":["avalanche"," avax "],
    "LINK":["chainlink"," link "],
}

TOPICS={
    "macro":["fed","federal reserve","interest rate","inflation","cpi","jobs","unemployment","nfp","dollar","dxy","treasury","yield"],
    "regulation":["sec","cftc","regulation","regulator","law","lawsuit","court","ban","approval","license"],
    "etf":["etf","exchange-traded fund"],
    "exchange":["binance","bybit","okx","coinbase","kraken","exchange"],
    "security":["hack","exploit","breach","stolen","drain","phishing","attack"],
    "defi":["defi","dex","yield","liquidity","lending"],
    "stablecoin":["stablecoin","usdt","usdc","tether","circle"],
    "airdrop":["airdrop","launchpool","launchpad","testnet","token sale"],
    "institutional":["blackrock","fidelity","institution","treasury company","bank","custody"],
}

HIGH=["hack","exploit","breach","sec ","fed ","federal reserve","etf approval","lawsuit","ban ","bankruptcy","liquidat","rate cut","rate hike","cpi","nfp","jobs report"]
MED=["partnership","launch","listing","upgrade","funding","acquisition","stablecoin","institution","treasury","whale"]

def clean(s:str)->str:
    return re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",s or "")).strip()

def published(entry):
    for key in ("published_parsed","updated_parsed"):
        t=getattr(entry,key,None)
        if t:
            try:
                return datetime(*t[:6],tzinfo=timezone.utc).isoformat()
            except Exception: pass
    return None

def canonical_title(title:str)->str:
    t=title.lower()
    t=re.sub(r"[^a-z0-9а-яіїєґ ]+"," ",t)
    stop={"the","a","an","and","or","to","of","for","in","on","as","is","with","after","from"}
    return " ".join(w for w in t.split() if w not in stop)[:180]

def analyze(title:str,summary:str):
    text=" "+(title+" "+summary).lower()+" "
    assets=[sym for sym,keys in ASSETS.items() if any(k in text for k in keys)]
    topics=[topic for topic,keys in TOPICS.items() if any(k in text for k in keys)]
    if any(k in text for k in HIGH):
        impact=3; impact_label="Високий вплив"
    elif any(k in text for k in MED) or len(assets)>=2:
        impact=2; impact_label="Середній вплив"
    else:
        impact=1; impact_label="Низький вплив"

    why=[]
    if "security" in topics: why.append("може вплинути на довіру, ліквідність або безпеку активів")
    if "macro" in topics: why.append("макро може змінити апетит ринку до ризику")
    if "regulation" in topics: why.append("регуляторна новина може змінити доступ/попит на криптоактиви")
    if "etf" in topics or "institutional" in topics: why.append("може вплинути на інституційний попит")
    if "exchange" in topics: why.append("біржові зміни можуть вплинути на ліквідність/доступність")
    if "stablecoin" in topics: why.append("стейблкоїни важливі для ліквідності крипторинку")
    if not why: why.append("контекст для ринку; не є самостійним сигналом на угоду")

    return assets,topics,impact,impact_label,why[:3]

def main():
    items=[]; feed_status={}
    seen_titles=set()
    for source,url in FEEDS.items():
        parsed=feedparser.parse(url)
        feed_status[source]={"url":url,"ok":not bool(getattr(parsed,"bozo",0)),"count":len(parsed.entries)}
        for e in parsed.entries[:80]:
            title=clean(getattr(e,"title",""))
            link=getattr(e,"link","")
            summary=clean(getattr(e,"summary","") or getattr(e,"description",""))
            if not title or not link: continue
            key=canonical_title(title)
            if key in seen_titles: continue
            seen_titles.add(key)
            assets,topics,impact,impact_label,why=analyze(title,summary)
            items.append({
                "id":hashlib.sha1((source+link).encode()).hexdigest()[:14],
                "source":"jev_news",
                "publisher":source,
                "mode":"news",
                "title":title,
                "summary":summary[:650],
                "url":link,
                "published_at":published(e),
                "assets":assets,
                "topics":topics,
                "impact":impact,
                "impact_label":impact_label,
                "reasons":why,
            })

    items.sort(key=lambda x:x.get("published_at") or "",reverse=True)
    payload={
        "version":1,
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "feed_status":feed_status,
        "item_count":len(items),
        "items":items[:250],
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"items":len(payload["items"]),"sources":feed_status},ensure_ascii=False))

if __name__=="__main__":
    main()

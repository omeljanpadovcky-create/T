from __future__ import annotations

import hashlib
import json
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from pathlib import Path

import feedparser

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data" / "news.json"

# Direct publishers are evidence sources. Google News is discovery only.
FEEDS = {
    "CoinDesk": ("https://www.coindesk.com/arc/outboundfeeds/rss/", True),
    "Cointelegraph": ("https://cointelegraph.com/rss", True),
    "Decrypt": ("https://decrypt.co/feed", True),
    "The Block": ("https://www.theblock.co/rss.xml", True),
    "Bloomberg Crypto": ("https://feeds.bloomberg.com/crypto/news.rss", True),
    "FT Crypto": ("https://www.ft.com/crypto?format=rss", True),
    "Google News discovery": (
        "https://news.google.com/rss/search?q=(bitcoin+OR+ethereum+OR+crypto+OR+blockchain+OR+stablecoin+OR+defi+OR+solana+OR+altcoin)+when:1d&hl=en-US&gl=US&ceid=US:en",
        False,
    ),
}

ASSETS = {
    "BTC": ["bitcoin", " btc "],
    "ETH": ["ethereum", " ether ", " eth "],
    "SOL": ["solana", " sol "],
    "XRP": ["xrp", "ripple"],
    "BNB": ["bnb", "binance coin"],
    "OP": ["optimism", " op "],
    "ARB": ["arbitrum", " arb "],
    "PENDLE": ["pendle"],
    "DOGE": ["dogecoin", " doge "],
    "ADA": ["cardano", " ada "],
    "AVAX": ["avalanche", " avax "],
    "LINK": ["chainlink", " link "],
}

TOPICS = {
    "macro": ["fed", "federal reserve", "interest rate", "inflation", "cpi", "jobs", "unemployment", "nfp", "dollar", "dxy", "treasury", "yield"],
    "regulation": ["sec", "cftc", "regulation", "regulator", "law", "lawsuit", "court", "ban", "approval", "license"],
    "etf": ["etf", "exchange-traded fund"],
    "exchange": ["binance", "bybit", "okx", "coinbase", "kraken", "exchange"],
    "security": ["hack", "exploit", "breach", "stolen", "drain", "phishing", "attack"],
    "defi": ["defi", "dex", "yield", "liquidity", "lending"],
    "stablecoin": ["stablecoin", "usdt", "usdc", "tether", "circle"],
    "airdrop": ["airdrop", "launchpool", "launchpad", "testnet", "token sale"],
    "institutional": ["blackrock", "fidelity", "institution", "treasury company", "bank", "custody"],
}

HIGH = [
    "hack", "exploit", "breach", "sec ", "fed ", "federal reserve", "etf approval",
    "lawsuit", "ban ", "bankruptcy", "liquidat", "rate cut", "rate hike", "cpi", "nfp", "jobs report"
]
MED = [
    "partnership", "launch", "listing", "upgrade", "funding", "acquisition",
    "stablecoin", "institution", "treasury", "whale"
]
POS = [
    "approval", "approved", "launch", "partnership", "adoption", "inflow",
    "buy", "buys", "surge", "record high", "upgrade", "integrates", "adds support"
]
NEG = [
    "hack", "exploit", "breach", "lawsuit", "ban", "outflow", "liquidat",
    "bankruptcy", "stolen", "attack", "reject", "rejected", "investigation"
]

STOP = {
    "the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "as", "is",
    "with", "after", "from", "by", "at", "amid", "over", "into", "says", "new",
    "crypto", "bitcoin", "ethereum"
}


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def published(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = getattr(entry, key, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return None


def token_set(text: str) -> set[str]:
    t = re.sub(r"[^a-z0-9а-яіїєґ ]+", " ", (text or "").lower())
    return {w for w in t.split() if len(w) > 2 and w not in STOP}


def similarity(a: dict, b: dict) -> float:
    ta, tb = token_set(a["title"]), token_set(b["title"])
    jacc = len(ta & tb) / max(1, len(ta | tb))
    seq = SequenceMatcher(None, a["title"].lower(), b["title"].lower()).ratio()
    asset_bonus = 0.12 if set(a.get("assets", [])) & set(b.get("assets", [])) else 0
    topic_bonus = 0.08 if set(a.get("topics", [])) & set(b.get("topics", [])) else 0
    return max(jacc, seq * 0.72) + asset_bonus + topic_bonus


def detect(text: str):
    padded = " " + text.lower() + " "
    assets = [sym for sym, keys in ASSETS.items() if any(k in padded for k in keys)]
    topics = [topic for topic, keys in TOPICS.items() if any(k in padded for k in keys)]

    if any(k in padded for k in HIGH):
        impact, impact_label = 3, "Високий вплив"
    elif any(k in padded for k in MED) or len(assets) >= 2:
        impact, impact_label = 2, "Середній вплив"
    else:
        impact, impact_label = 1, "Низький вплив"

    pos = sum(1 for k in POS if k in padded)
    neg = sum(1 for k in NEG if k in padded)
    if pos > neg:
        tone = "Потенційно позитивний"
    elif neg > pos:
        tone = "Потенційно негативний"
    else:
        tone = "Невизначений / змішаний"

    return assets, topics, impact, impact_label, tone


def jev_analysis(assets, topics, impact_label, tone, source_count):
    target = ", ".join(assets[:4]) if assets else "крипторинок"

    if "security" in topics:
        take = f"Інцидент може тиснути на {target}, але спочатку треба підтвердити масштаб втрат і чи зупинені виводи/контракти."
        watch = "Офіційне підтвердження, сума втрат, on-chain рух коштів, відновлення депозитів/виводів."
    elif "macro" in topics:
        take = f"Це макро-фактор для {target}: важлива не сама новина, а реакція ліквідності, долара й прибутковостей."
        watch = "DXY, US 2Y/10Y, реакція BTC після релізу та чи утримується рух через кілька годин."
    elif "regulation" in topics or "etf" in topics:
        take = f"Регуляторний фактор може змінити доступ або попит на {target}; заголовок треба звіряти з офіційним рішенням/файлінгом."
        watch = "Офіційний документ регулятора, дата набуття чинності, ETF flows/обсяги після підтвердження."
    elif "exchange" in topics:
        take = f"Біржова новина може впливати на ліквідність і доступність {target}; важливо відділити операційне оновлення від системного ризику."
        watch = "Офіційний статус біржі, депозити/виводи, резерви, спреди та реакція ціни."
    elif "institutional" in topics:
        take = f"Інституційний інтерес до {target} важливий, якщо це підтверджені покупки/flows, а не лише намір або маркетинг."
        watch = "Фактичні flows/покупки, розмір позиції, повторюваність попиту та реакція обсягу."
    elif "stablecoin" in topics:
        take = "Стейблкоїн-новина важлива через ліквідність ринку; треба дивитися, чи є реальний вплив на випуски, резерви або розрахунки."
        watch = "Mint/burn, резерви, peg, біржові потоки та офіційні заяви емітента."
    elif "airdrop" in topics:
        take = "Це радше можливість/активність, а не торговий сигнал. Ключове — дедлайн, умови, KYC, gas і ризик фішингу."
        watch = "Офіційний домен, дедлайн, eligibility, витрати gas/fees та підтвердження команди."
    else:
        take = f"Новина стосується {target}, але сама по собі ще не дає торгового сигналу. Потрібно дивитися, чи підтверджує її ринок."
        watch = "Друге незалежне джерело, обсяг, реакція ціни й наступні офіційні оновлення."

    if source_count >= 3:
        confidence = "Підтверджено кількома джерелами"
    elif source_count == 2:
        confidence = "Є незалежне підтвердження"
    else:
        confidence = "Поки одне джерело"

    return take, watch, confidence, tone, impact_label


def read_feeds():
    rows = []
    feed_status = {}

    for source, (url, is_direct) in FEEDS.items():
        parsed = feedparser.parse(url)
        feed_status[source] = {
            "url": url,
            "ok": not bool(getattr(parsed, "bozo", 0)),
            "count": len(parsed.entries),
            "role": "evidence" if is_direct else "discovery",
        }

        for e in parsed.entries[:100]:
            title = clean(getattr(e, "title", ""))
            link = getattr(e, "link", "")
            summary = clean(getattr(e, "summary", "") or getattr(e, "description", ""))
            if not title or not link:
                continue
            text = title + " " + summary
            assets, topics, impact, impact_label, tone = detect(text)
            rows.append({
                "id": hashlib.sha1((source + link).encode()).hexdigest()[:14],
                "source": source,
                "direct": is_direct,
                "title": title,
                "summary": summary[:900],
                "url": link,
                "published_at": published(e),
                "assets": assets,
                "topics": topics,
                "impact": impact,
                "impact_label": impact_label,
                "tone": tone,
            })

    return rows, feed_status


def cluster_rows(rows):
    # Direct publishers first. Google discovery can enrich an existing event,
    # but a Google-only item is never presented as "confirmed JEV analysis".
    rows.sort(key=lambda x: (not x["direct"], x.get("published_at") or ""), reverse=False)
    clusters = []

    for row in rows:
        best = None
        best_score = 0.0
        for c in clusters:
            score = similarity(row, c["seed"])
            if score > best_score:
                best, best_score = c, score

        if best is not None and best_score >= 0.52:
            best["rows"].append(row)
        else:
            clusters.append({"seed": row, "rows": [row]})

    return clusters


def build_events(rows):
    events = []
    for cluster in cluster_rows(rows):
        group = cluster["rows"]
        direct = [x for x in group if x["direct"]]
        evidence = direct or group

        # Google-only discovery remains visible only if it has high impact,
        # clearly marked as unconfirmed.
        combined = " ".join((x["title"] + " " + x["summary"]) for x in evidence)
        assets, topics, impact, impact_label, tone = detect(combined)

        publishers = []
        links = []
        for x in evidence:
            if x["source"] not in publishers:
                publishers.append(x["source"])
            links.append({"publisher": x["source"], "url": x["url"]})

        source_count = len(set(publishers))
        take, watch, confidence, tone, impact_label = jev_analysis(
            assets, topics, impact_label, tone, source_count
        )

        if not direct and impact < 3:
            continue

        primary = evidence[0]
        events.append({
            "id": hashlib.sha1(("event:" + "|".join(sorted(x["id"] for x in evidence))).encode()).hexdigest()[:14],
            "source": "jev_analysis",
            "mode": "news",
            "title": primary["title"],
            "summary": primary["summary"][:650],
            "url": primary["url"],
            "published_at": max((x.get("published_at") or "" for x in evidence), default=None),
            "assets": assets,
            "topics": topics,
            "impact": impact,
            "impact_label": impact_label,
            "tone": tone,
            "source_count": source_count,
            "publishers": publishers,
            "links": links[:6],
            "confidence_label": confidence if direct else "Discovery: потребує підтвердження",
            "jev_take": take,
            "watch_for": watch,
            "analysis_basis": "Зведення RSS-сніпетів + крос-перевірка між джерелами; це не повнотекстовий LLM-аналіз статті.",
            "reasons": [
                confidence if direct else "Google News використано лише як радар теми",
                f"Ринковий тон: {tone}",
                watch,
            ],
        })

    events.sort(key=lambda x: (x["impact"], x.get("published_at") or ""), reverse=True)
    return events[:250]


def main():
    rows, feed_status = read_feeds()
    events = build_events(rows)

    payload = {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_mode": "cross-source pre-analysis; not full-text LLM",
        "feed_status": feed_status,
        "raw_item_count": len(rows),
        "item_count": len(events),
        "items": events,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "events": len(events),
        "raw_items": len(rows),
        "sources": feed_status,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

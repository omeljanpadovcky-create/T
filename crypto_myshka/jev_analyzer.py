from __future__ import annotations

import json, os, re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
NEWS = ROOT / "data" / "news.json"
FEED = ROOT / "data" / "feed.json"

TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
MODEL = os.getenv("JEV_MODEL", "openai/gpt-4.1").strip()
ENDPOINT = "https://models.github.ai/inference/chat/completions"

SYSTEM = """Ти JEV — обережний крипто-аналітик у системі Криптомишка.
Твоє завдання: не давати команд 'купуй/продавай', а стисло аналізувати подію.
Відділяй факт від припущення. Не вигадуй відсутні дані.
Якщо джерел мало або дані суперечливі — прямо скажи це.
Пиши українською.
Поверни ТІЛЬКИ валідний JSON з ключами:
what_happened, why_it_matters, market_effect, bull_case, bear_case,
watch_next, confidence, short_conclusion.
Кожне поле — короткий рядок, без markdown.
confidence має бути одним із: "низька", "середня", "висока".
short_conclusion — максимум 2 короткі речення."""

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def related_context(event, feed):
    assets = set(event.get("assets") or [])
    topics = set(event.get("topics") or [])
    live, knowledge = [], []

    for x in feed.get("items") or []:
        blob = (x.get("title","") + " " + x.get("summary","")).lower()
        asset_hit = any(a.lower() in blob for a in assets)
        topic_hit = any(t.lower() in blob for t in topics)
        if not (asset_hit or topic_hit):
            continue
        row = {
            "source": x.get("source"),
            "title": x.get("title"),
            "summary": (x.get("summary") or "")[:500],
            "url": x.get("url"),
        }
        if x.get("knowledge"):
            knowledge.append(row)
        else:
            live.append(row)

    return live[:6], knowledge[:8]

def extract_json(text):
    text=(text or "").strip()
    fence=chr(96)*3
    if text.startswith(fence):
        text=text.replace(fence+"json","",1).replace(fence,"").strip()
    try:
        return json.loads(text)
    except Exception:
        m=re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise
        return json.loads(m.group(0))

def analyze_event(event, feed):
    live, knowledge = related_context(event, feed)
    payload = {
        "event": {
            "title": event.get("title"),
            "summary": event.get("summary"),
            "publishers": event.get("publishers"),
            "source_count": event.get("source_count"),
            "assets": event.get("assets"),
            "topics": event.get("topics"),
            "impact_label": event.get("impact_label"),
            "confidence_label": event.get("confidence_label"),
            "links": event.get("links"),
        },
        "related_itstatti_live": live,
        "related_itstatti_knowledge": knowledge,
        "instruction": "Зроби незалежний аналіз події з урахуванням контексту ITstatti лише як контексту, а не як істини.",
    }

    r = requests.post(
        ENDPOINT,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role":"system","content":SYSTEM},
                {"role":"user","content":json.dumps(payload, ensure_ascii=False)},
            ],
            "temperature": 0.2,
            "max_tokens": 900,
        },
        timeout=60,
    )
    r.raise_for_status()
    data=r.json()
    text=data["choices"][0]["message"]["content"]
    return extract_json(text)

def main():
    news=load(NEWS, {"items":[]})
    feed=load(FEED, {"items":[]})

    if not TOKEN:
        print("GITHUB_TOKEN unavailable; leaving cross-source fallback only.")
        return

    done=0
    errors=0
    items=sorted(
        news.get("items") or [],
        key=lambda x:(int(x.get("impact") or 0), x.get("published_at") or ""),
        reverse=True,
    )

    for event in items:
        if done >= 10:
            break
        if int(event.get("impact") or 0) < 2:
            continue
        try:
            event["jev_ai"] = analyze_event(event, feed)
            event["analysis_engine"] = MODEL
            event["analysis_level"] = "llm"
            done += 1
        except Exception as e:
            event["analysis_error"] = str(e)[:260]
            event["analysis_level"] = "cross_source_fallback"
            errors += 1

    news["jev_model"] = MODEL
    news["jev_analyzed_count"] = done
    news["jev_analysis_errors"] = errors
    save(NEWS, news)
    print(json.dumps({"jev_analyzed":done,"errors":errors,"model":MODEL},ensure_ascii=False))

if __name__=="__main__":
    main()

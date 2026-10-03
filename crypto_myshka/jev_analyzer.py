from __future__ import annotations

import json, os, re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
NEWS = ROOT / "data" / "news.json"
FEED = ROOT / "data" / "feed.json"

# Any OpenAI-compatible endpoint works:
# Ollama:   http://YOUR_HOST:11434/v1/chat/completions
# OpenAI:   https://api.openai.com/v1/chat/completions
# Groq:     https://api.groq.com/openai/v1/chat/completions
ENDPOINT = os.getenv("JEV_API_URL", "").strip()
TOKEN = os.getenv("JEV_API_KEY", "").strip()
MODEL = os.getenv("JEV_MODEL", "").strip() or "qwen2.5:7b"

SYSTEM = """Ти JEV — обережний крипто-аналітик у системі Криптомишка.
Твоє завдання: аналізувати подію, а не копіювати чужий сигнал.
Не давай безумовних команд "купуй/продавай".
Відділяй факт від припущення. Не вигадуй відсутні дані.
ITstatti використовуй як контекст/методологію, а не як істину.
Якщо даних мало або джерела суперечать одне одному — прямо скажи це.
Пиши українською.
Поверни ТІЛЬКИ валідний JSON з ключами:
what_happened, why_it_matters, market_effect, bull_case, bear_case,
watch_next, confidence, short_conclusion.
confidence: "низька", "середня" або "висока".
short_conclusion — максимум 2 короткі речення."""

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def related_context(event, feed):
    assets = {str(a).lower() for a in (event.get("assets") or [])}
    topics = {str(t).lower() for t in (event.get("topics") or [])}
    live, knowledge = [], []

    for x in feed.get("items") or []:
        blob = (" " + x.get("title","") + " " + x.get("summary","") + " ").lower()
        asset_hit = any((" "+a+" ") in blob or a in blob for a in assets)
        topic_hit = any(t in blob for t in topics)
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
            raise ValueError("Model did not return JSON")
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
        "instruction": "Дай незалежний JEV-аналіз події. Не повторюй рекламні або реферальні твердження як факт.",
    }

    headers={"Content-Type":"application/json","Accept":"application/json"}
    if TOKEN:
        headers["Authorization"]=f"Bearer {TOKEN}"

    r=requests.post(
        ENDPOINT,
        headers=headers,
        json={
            "model": MODEL,
            "messages": [
                {"role":"system","content":SYSTEM},
                {"role":"user","content":json.dumps(payload, ensure_ascii=False)},
            ],
            "temperature": 0.2,
            "max_tokens": 900,
        },
        timeout=75,
    )
    r.raise_for_status()
    data=r.json()
    return extract_json(data["choices"][0]["message"]["content"])

def main():
    news=load(NEWS, {"items":[]})
    feed=load(FEED, {"items":[]})

    # No reachable JEV endpoint configured: keep transparent cross-source fallback.
    if not ENDPOINT:
        news["jev_enabled"]=False
        news["jev_status"]="not_configured"
        news["jev_model"]=None
        news["jev_analyzed_count"]=0
        save(NEWS, news)
        print("JEV_API_URL not configured; using cross-source fallback only.")
        return

    done=0
    errors=0
    candidates=sorted(
        news.get("items") or [],
        key=lambda x:(int(x.get("impact") or 0), x.get("published_at") or ""),
        reverse=True,
    )

    # Keep API usage bounded: analyze up to 8 important events per run.
    for event in candidates:
        if done >= 8:
            break
        if int(event.get("impact") or 0) < 2:
            continue
        try:
            event["jev_ai"]=analyze_event(event, feed)
            event["analysis_engine"]=MODEL
            event["analysis_level"]="llm"
            event.pop("analysis_error", None)
            done += 1
        except Exception as e:
            event["analysis_error"]=str(e)[:260]
            event["analysis_level"]="cross_source_fallback"
            errors += 1

    news["jev_enabled"]=True
    news["jev_status"]="ok" if done else "configured_but_no_success"
    news["jev_model"]=MODEL
    news["jev_analyzed_count"]=done
    news["jev_analysis_errors"]=errors
    save(NEWS, news)
    print(json.dumps({
        "jev_enabled":True,
        "jev_analyzed":done,
        "errors":errors,
        "model":MODEL,
        "endpoint":ENDPOINT.split("?")[0],
    },ensure_ascii=False))

if __name__=="__main__":
    main()

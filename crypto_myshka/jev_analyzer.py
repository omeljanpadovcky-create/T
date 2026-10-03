from __future__ import annotations

import json, os, re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
NEWS = ROOT / "data" / "news.json"
FEED = ROOT / "data" / "feed.json"

APINEX_API_KEY = os.getenv("APINEX_API_KEY", "").strip()
APINEX_MODEL = os.getenv("JEV_MODEL", "").strip() or "free/gpt-5.6-luna"
APINEX_ENDPOINT = "https://api.apinex.bond/v1/chat/completions"

# Optional fallbacks.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "").strip() or "gpt-6-luna"
OPENAI_ENDPOINT = "https://api.openai.com/v1/responses"
GENERIC_ENDPOINT = os.getenv("JEV_API_URL", "").strip()
GENERIC_TOKEN = os.getenv("JEV_API_KEY", "").strip()
GENERIC_MODEL = os.getenv("JEV_GENERIC_MODEL", "").strip() or "qwen2.5:7b"

SYSTEM = """Ти JEV — обережний крипто-аналітик у системі Криптомишка.
Ти не копіюєш сигнали, а перевіряєш їх.
Не давай безумовних команд "купуй/продавай".
Відділяй факти від припущень. Не вигадуй відсутні дані.
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

def build_payload(event, feed):
    live, knowledge = related_context(event, feed)
    return {
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

def openai_response_text(data):
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and part.get("text"):
                return part["text"]
    raise ValueError("OpenAI Responses API returned no output_text")

APINEX_FALLBACK_MODELS = [
    APINEX_MODEL,
    "free/deepseek-v4.1-flash",
    "free/gemini-3.8-flash",
]

def analyze_apinex(event, feed):
    payload=build_payload(event, feed)
    last_error=None

    for model in dict.fromkeys(APINEX_FALLBACK_MODELS):
        r=requests.post(
            APINEX_ENDPOINT,
            headers={
                "Authorization": f"Bearer {APINEX_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role":"system","content":SYSTEM},
                    {"role":"user","content":json.dumps(payload, ensure_ascii=False)},
                ],
                "temperature": 0.2,
                "max_tokens": 900,
            },
            timeout=75,
        )

        if r.ok:
            data=r.json()
            result=extract_json(data["choices"][0]["message"]["content"])
            result["_model_used"]=model
            return result

        body=(r.text or "").strip().replace("\n"," ")[:500]
        last_error=f"APInex {r.status_code} for {model}: {body}"

        # Retry another free model only for model/not-found style errors.
        if r.status_code not in (400, 404, 422):
            break

    raise RuntimeError(last_error or "APInex request failed")

def analyze_openai(event, feed):
    payload=build_payload(event, feed)
    r=requests.post(
        OPENAI_ENDPOINT,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "instructions": SYSTEM,
            "input": json.dumps(payload, ensure_ascii=False),
            "max_output_tokens": 900,
            "store": False,
        },
        timeout=75,
    )
    r.raise_for_status()
    return extract_json(openai_response_text(r.json()))

def analyze_generic(event, feed):
    payload=build_payload(event, feed)
    headers={"Content-Type":"application/json","Accept":"application/json"}
    if GENERIC_TOKEN:
        headers["Authorization"]=f"Bearer {GENERIC_TOKEN}"
    r=requests.post(
        GENERIC_ENDPOINT,
        headers=headers,
        json={
            "model": GENERIC_MODEL,
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

    if APINEX_API_KEY:
        provider="apinex"
        model=APINEX_MODEL
        analyze=analyze_apinex
    elif OPENAI_API_KEY:
        provider="openai"
        model=OPENAI_MODEL
        analyze=analyze_openai
    elif GENERIC_ENDPOINT:
        provider="openai_compatible"
        model=GENERIC_MODEL
        analyze=analyze_generic
    else:
        news["jev_enabled"]=False
        news["jev_status"]="not_configured"
        news["jev_provider"]=None
        news["jev_model"]=None
        news["jev_analyzed_count"]=0
        save(NEWS, news)
        print("No JEV cloud provider configured; cross-source fallback remains active.")
        return

    done=0
    errors=0
    candidates=sorted(
        news.get("items") or [],
        key=lambda x:(int(x.get("impact") or 0), x.get("published_at") or ""),
        reverse=True,
    )

    # Analyze only the most important/current events to keep cost bounded.
    for event in candidates:
        if done >= 8:
            break
        if int(event.get("impact") or 0) < 2:
            continue
        try:
            event["jev_ai"]=analyze(event, feed)
            event["analysis_engine"]=(event["jev_ai"].get("_model_used") if isinstance(event.get("jev_ai"),dict) else None) or model
            event["analysis_level"]="llm"
            event.pop("analysis_error", None)
            done += 1
        except Exception as e:
            event["analysis_error"]=str(e)[:260]
            event["analysis_level"]="cross_source_fallback"
            errors += 1

    news["jev_enabled"]=True
    news["jev_status"]="ok" if done else "configured_but_no_success"
    news["jev_provider"]=provider
    news["jev_model"]=model
    news["jev_analyzed_count"]=done
    news["jev_analysis_errors"]=errors
    save(NEWS, news)
    print(json.dumps({
        "provider":provider,
        "jev_analyzed":done,
        "errors":errors,
        "model":model,
    }, ensure_ascii=False))

if __name__=="__main__":
    main()

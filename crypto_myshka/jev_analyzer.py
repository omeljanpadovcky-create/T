from __future__ import annotations

import json, os, re, time, random
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
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass

    # Some free models occasionally answer with useful prose instead of strict JSON.
    # Preserve the analysis rather than dropping the event, but mark confidence low.
    plain=re.sub(r"\s+"," ",text).strip()
    if plain:
        return {
            "what_happened": plain[:420],
            "why_it_matters": "Модель повернула неструктурований висновок; першоджерело треба перевірити вручну.",
            "market_effect": "Невизначено",
            "bull_case": "Потрібне підтвердження даними та реакцією ринку.",
            "bear_case": "Непідтверджений або неповний контекст може дати хибний висновок.",
            "watch_next": "Перевірити першоджерело, додаткове незалежне джерело та реакцію ціни/обсягу.",
            "confidence": "низька",
            "short_conclusion": plain[:260],
            "_format_fallback": True
        }
    raise ValueError("Model returned empty content")

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

# Free tier is 30 RPM per IP. Keep our own ceiling below that.
APINEX_MIN_INTERVAL_SECONDS = 2.25
APINEX_MAX_ATTEMPTS_PER_MODEL = 3
_last_apinex_request_at = 0.0

def apinex_wait_slot():
    global _last_apinex_request_at
    now=time.monotonic()
    wait=APINEX_MIN_INTERVAL_SECONDS-(now-_last_apinex_request_at)
    if wait>0:
        time.sleep(wait)
    _last_apinex_request_at=time.monotonic()

def apinex_retry_delay(response, attempt):
    retry_after=(response.headers.get("retry-after") or "").strip()
    try:
        if retry_after:
            return max(1.0, min(float(retry_after), 30.0))
    except Exception:
        pass
    return min(2 ** attempt, 20) + random.uniform(0.15, 0.85)

def analyze_apinex(event, feed):
    payload=build_payload(event, feed)
    last_error=None

    for model in dict.fromkeys(APINEX_FALLBACK_MODELS):
        if not str(model).startswith("free/"):
            continue

        for attempt in range(APINEX_MAX_ATTEMPTS_PER_MODEL):
            apinex_wait_slot()
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
                content=((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                if "<tool_call>" in content or "<arg_key>" in content:
                    last_error=f"APInex malformed tool-call output for {model}"
                    break
                result=extract_json(content)
                result["_model_used"]=model
                return result

            body=(r.text or "").strip().replace("\n"," ")[:500]
            last_error=f"APInex {r.status_code} for {model}: {body}"

            if r.status_code == 401:
                raise RuntimeError(last_error)
            if r.status_code == 402:
                # This model/request needs allowance. Do not top up automatically:
                # move to the next free model.
                break
            if r.status_code in (400, 404, 422):
                break
            if r.status_code in (429, 502, 503):
                if attempt + 1 < APINEX_MAX_ATTEMPTS_PER_MODEL:
                    time.sleep(apinex_retry_delay(r, attempt + 1))
                    continue
                break
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

    # Analyze a new batch on every run. Already analyzed events are skipped,
    # so the archive is gradually filled instead of re-analyzing the same top 8.
    for event in candidates:
        if done >= 8:
            break
        if int(event.get("impact") or 0) < 2:
            continue
        ai=event.get("jev_ai") or {}
        if ai and not ai.get("_format_fallback"):
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

    analyzed_count=sum(
        1 for x in (news.get("items") or [])
        if x.get("jev_ai") and not (x.get("jev_ai") or {}).get("_format_fallback")
    )
    pending_count=sum(
        1 for x in (news.get("items") or [])
        if int(x.get("impact") or 0) >= 2 and (
            not x.get("jev_ai") or (x.get("jev_ai") or {}).get("_format_fallback")
        )
    )
    news["jev_enabled"]=True
    news["jev_status"]="complete" if pending_count==0 else ("ok" if done else ("degraded" if errors else "idle"))
    news["jev_provider"]=provider
    news["jev_model"]=model
    news["jev_analyzed_count"]=analyzed_count
    news["jev_analyzed_this_run"]=done
    news["jev_pending_count"]=pending_count
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

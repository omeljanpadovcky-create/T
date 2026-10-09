from __future__ import annotations

import json, os, re, time, random
from pathlib import Path

import requests

try:
    from storage import sync_news
except ImportError:
    from crypto_myshka.storage import sync_news

ROOT = Path(__file__).resolve().parent
NEWS = ROOT / "data" / "news.json"
FEED = ROOT / "data" / "feed.json"
ARCHIVE = ROOT / "data" / "telegram_archive.json"
VIDEO_CONTEXT = ROOT / "data" / "youtube_analysts.json"

APINEX_API_KEY = os.getenv("APINEX_API_KEY", "").strip()
APINEX_MODEL = os.getenv("JEV_MODEL", "").strip() or "free/deepseek-v4.1-flash"
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

def related_archive_context(event, archive, limit=6):
    posts=archive.get("posts") or []
    terms={str(a).lower() for a in (event.get("assets") or []) if a}
    terms.update(str(t).lower() for t in (event.get("topics") or []) if t)
    title_tokens=re.findall(r"[a-z0-9а-яіїєґ]{4,}", (event.get("title") or "").lower())
    stop={"with","from","that","this","have","will","after","over","into","crypto","bitcoin","ethereum"}
    terms.update(t for t in title_tokens if t not in stop)

    scored=[]
    for p in posts:
        text=(p.get("text") or "").lower()
        if not text:
            continue
        score=sum(2 if len(t)>5 else 1 for t in terms if t and t in text)
        if score:
            scored.append((score,p.get("published_at") or "",p))
    scored.sort(key=lambda row:(row[0],row[1]),reverse=True)

    out=[]
    seen=set()
    for _,_,p in scored:
        url=p.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({
            "source":p.get("channel") or "telegram_archive",
            "title":(p.get("text") or "")[:150],
            "summary":(p.get("text") or "")[:650],
            "url":url,
            "published_at":p.get("published_at"),
        })
        if len(out)>=limit:
            break
    return out


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

    # Recover complete string fields from JSON that was cut off mid-response.
    keys = [
        "what_happened", "why_it_matters", "market_effect", "bull_case",
        "bear_case", "watch_next", "confidence", "short_conclusion"
    ]
    partial = {}
    for key in keys:
        m = re.search(r'"' + re.escape(key) + r'"\s*:\s*"((?:\\.|[^"\\])*)"', text, flags=re.S)
        if not m:
            continue
        try:
            partial[key] = json.loads('"' + m.group(1) + '"')
        except Exception:
            partial[key] = re.sub(r"\\n", " ", m.group(1)).strip()

    if partial:
        partial.setdefault("what_happened", "Відповідь моделі була обрізана; дивись першоджерело.")
        partial.setdefault("why_it_matters", "Частина AI-відповіді не дійшла повністю, тому висновок потребує перевірки.")
        partial.setdefault("market_effect", "Невизначено")
        partial.setdefault("bull_case", "Потрібне підтвердження даними та реакцією ринку.")
        partial.setdefault("bear_case", "Неповний контекст може дати хибний висновок.")
        partial.setdefault("watch_next", "Перевірити першоджерело, додаткове незалежне джерело та реакцію ціни/обсягу.")
        partial.setdefault("confidence", "низька")
        partial.setdefault("short_conclusion", partial.get("why_it_matters") or partial.get("what_happened"))
        partial["_format_fallback"] = True
        partial["_partial_json_recovered"] = True
        return partial

    # Plain non-JSON fallback. Never expose raw JSON/tool syntax in the UI.
    plain=re.sub(r"\s+"," ",text).strip()
    if plain:
        if plain.startswith("{") or "<tool_call>" in plain or "<arg_key>" in plain:
            plain = "AI-відповідь прийшла у пошкодженому форматі й буде автоматично перезапитана."
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

def related_youtube_context(event, video_data, limit=3):
    """Only use text actually available from public uploaded videos, never
    assume that a streamer performed a trade or that stated winrates are true."""
    names={str(v).lower() for v in (event.get("assets") or []) if v}
    titles=str(event.get("title") or "").lower()
    names.update(re.findall(r"(?i)(?:BTC|ETH|SOL|XRP|ADA|BNB|DOGE|AUD|CHF|USD|EUR|GBP|JPY|AED|IDR|CNY)(?:[/_-][A-Z]{3,5})?", titles))
    aliases={"btc":"bitcoin","eth":"ethereum","sol":"solana"}
    needles=set(names)
    for name in names:
        if name in aliases: needles.add(aliases[name])
    if not needles:
        return []
    matches=[]
    for channel in (video_data.get("channels") or []):
        if not isinstance(channel, dict) or not channel.get("confirmed"): continue
        for video in (channel.get("videos") or []):
            if not isinstance(video,dict) or video.get("sample_only"): continue
            a=video.get("analysis") or {}
            blob=(" "+str(video.get("title") or "")+" "+str(a.get("content_excerpt") or "")+
                  " "+" ".join(a.get("mentioned_instruments") or [])+" ").lower()
            if not any(word in blob for word in needles):
                continue
            matches.append({
                "channel":str(channel.get("name") or "")[:80],
                "title":str(video.get("title") or "")[:160],
                "url":str(video.get("url") or "")[:220],
                "mentioned_instruments":(a.get("mentioned_instruments") or [])[:5],
                "mentioned_indicators":(a.get("mentioned_indicators") or [])[:5],
                "subtitle_excerpt":str(a.get("content_excerpt") or "")[:300],
                "verified_market_data":False,
                "source_type":"published_youtube_text_only",
            })
            if len(matches)>=limit:return matches
    return matches


def build_payload(event, feed, archive=None):
    live, knowledge = related_context(event, feed)
    historical=related_archive_context(event, archive or {"posts":[]})
    video_notes=related_youtube_context(event,load(VIDEO_CONTEXT,{"channels":[]}))
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
        "related_itstatti_archive": historical,
        "related_itstatti_knowledge": knowledge,
        "related_trader_video_notes_unverified": video_notes,
        "instruction": "Дай незалежний JEV-аналіз події. Відеозамітки — лише слова з назви, опису або доступних субтитрів. Не вигадуй кадри, угоди чи підтвердження прибутковості. Не повторюй рекламні та реферальні твердження як факт.",
    }

def apinex_response_text(data):
    choice=(data.get("choices") or [{}])[0] or {}
    msg=choice.get("message") or {}
    content=msg.get("content")
    if isinstance(content,str) and content.strip():
        return content
    if isinstance(content,list):
        parts=[]
        for part in content:
            if isinstance(part,str):
                parts.append(part)
            elif isinstance(part,dict):
                value=part.get("text") or part.get("content") or part.get("output_text")
                if value:
                    parts.append(str(value))
        joined="\n".join(parts).strip()
        if joined:
            return joined
    for key in ("reasoning_content","reasoning","text","output_text"):
        value=msg.get(key) or choice.get(key)
        if isinstance(value,str) and value.strip():
            return value
    return ""


def fallback_analysis(event, error=""):
    target=", ".join((event.get("assets") or [])[:4]) or "крипторинок"
    take=(event.get("jev_take") or event.get("summary") or event.get("title") or "").strip()
    watch=(event.get("watch_for") or "Перевірити першоджерело, незалежне підтвердження та реакцію ціни/обсягу.").strip()
    confidence=(event.get("confidence_label") or "низька").lower()
    if "висок" in confidence:
        confidence="висока"
    elif "серед" in confidence:
        confidence="середня"
    else:
        confidence="низька"
    return {
        "what_happened": (event.get("summary") or event.get("title") or "Подія зафіксована новинним радаром.")[:650],
        "why_it_matters": take[:650] or f"Подія може впливати на {target}, але потребує перевірки.",
        "market_effect": event.get("tone") or "Невизначено",
        "bull_case": "Позитивний сценарій потребує підтвердження незалежними джерелами та реакцією ринку.",
        "bear_case": "Негативний сценарій — заголовок або масштаб події не підтверджуються, а ринкова реакція згасає.",
        "watch_next": watch[:650],
        "confidence": confidence,
        "short_conclusion": (take or "Є подія для перевірки; автоматичний висновок не замінює першоджерело.")[:320],
        "_cross_source_fallback": True,
        "_retry_llm": True,
        "_last_error": str(error)[:220],
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
    "free/gpt-6-luna",
    "free/gemini-3.8-flash",
]

# Free tier is 30 RPM per IP. Keep our own ceiling below that.
APINEX_MIN_INTERVAL_SECONDS = 2.25
APINEX_MAX_ATTEMPTS_PER_MODEL = 1
JEV_MAX_EVENTS = max(1, min(5, int(os.getenv('JEV_MAX_EVENTS', '4'))))
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

def analyze_apinex(event, feed, archive=None):
    payload=build_payload(event, feed, archive)
    last_error=None
    best_fallback=None

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
                    "max_tokens": 1400,
                },
                timeout=25,
            )

            if r.ok:
                data=r.json()
                content=apinex_response_text(data)
                if "<tool_call>" in content or "<arg_key>" in content:
                    last_error=f"APInex malformed tool-call output for {model}"
                    break
                result=extract_json(content)
                result["_model_used"]=model
                if isinstance(result, dict) and result.get("_format_fallback"):
                    # Do not stop on malformed/truncated JSON. Try the next free
                    # model in the same run and keep this only as a last resort.
                    best_fallback = result
                    last_error = f"APInex malformed/truncated JSON for {model}"
                    break
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

    if best_fallback:
        return best_fallback
    raise RuntimeError(last_error or "APInex request failed")

def analyze_openai(event, feed, archive=None):
    payload=build_payload(event, feed, archive)
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

def analyze_generic(event, feed, archive=None):
    payload=build_payload(event, feed, archive)
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
    archive=load(ARCHIVE, {"posts":[]})

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
    attempted=0
    format_fallbacks=0
    errors=0
    error_codes={}
    candidates=sorted(
        news.get("items") or [],
        key=lambda x:(-int(x.get("analysis_retry_count") or 0), int(x.get("impact") or 0), x.get("published_at") or ""),
        reverse=True,
    )

    # Analyze a new batch on every run. Finished events are preserved by
    # news_engine.py, while malformed/failed items are retried without blocking
    # the rest of the queue.
    for event in candidates:
        if attempted >= JEV_MAX_EVENTS:
            break
        if int(event.get("impact") or 0) < 2:
            continue
        ai=event.get("jev_ai") or {}
        if ai and event.get("analysis_level")=="llm" and not ai.get("_format_fallback"):
            continue
        attempted += 1
        event["analysis_retry_count"]=int(event.get("analysis_retry_count") or 0)+1
        event["analysis_last_attempt_at"]=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        try:
            event["jev_ai"]=analyze(event, feed, archive)
            event["analysis_engine"]=(event["jev_ai"].get("_model_used") if isinstance(event.get("jev_ai"),dict) else None) or model
            event.pop("analysis_error", None)
            if isinstance(event.get("jev_ai"), dict) and event["jev_ai"].get("_format_fallback"):
                event["analysis_level"]="format_fallback"
                format_fallbacks += 1
            else:
                event["analysis_level"]="llm"
                done += 1
        except Exception as e:
            event["analysis_error"]=str(e)[:260]
            event["jev_ai"]=fallback_analysis(event, e)
            event["analysis_engine"]="cross_source"
            event["analysis_level"]="cross_source_fallback"
            errors += 1
            match=re.search(r"APInex ([0-9]{3})", str(e))
            code=("http_"+match.group(1)) if match else type(e).__name__
            error_codes[code]=error_codes.get(code, 0)+1

    analyzed_count=sum(
        1 for x in (news.get("items") or [])
        if x.get("analysis_level")=="llm" and x.get("jev_ai")
    )
    coverage_pending_count=sum(
        1 for x in (news.get("items") or [])
        if int(x.get("impact") or 0) >= 2 and not x.get("jev_ai")
    )
    llm_pending_count=sum(
        1 for x in (news.get("items") or [])
        if int(x.get("impact") or 0) >= 2 and x.get("analysis_level")!="llm"
    )
    news["jev_enabled"]=True
    news["jev_status"]="complete" if llm_pending_count==0 else ("ok" if done else "degraded")
    news["jev_provider"]=provider
    news["jev_model"]=model
    news["jev_analyzed_count"]=analyzed_count
    news["jev_analyzed_this_run"]=done
    news["jev_pending_count"]=coverage_pending_count
    news["jev_llm_pending_count"]=llm_pending_count
    news["jev_analysis_errors"]=errors
    news["jev_error_codes"]=error_codes
    news["jev_last_run_at"]=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save(NEWS, news)
    db_count=sync_news(news)
    print(json.dumps({
        "provider":provider,
        "jev_analyzed":done,
        "attempted":attempted,
        "format_fallbacks":format_fallbacks,
        "errors":errors,
        "error_codes":error_codes,
        "model":model,
        "postgres":db_count,
    }, ensure_ascii=False))

if __name__=="__main__":
    main()

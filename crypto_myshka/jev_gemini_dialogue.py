"""Bounded Gemini ↔ JEV research discussion; never an order or market signal."""
from __future__ import annotations
import json, os, pathlib, datetime
import requests

ROOT=pathlib.Path(__file__).resolve().parent
FEED=ROOT/"data"/"jev_video_knowledge.json"
OUT=ROOT/"data"/"jev_research_dialogues.json"
GEMINI_KEY=os.getenv("GEMINI_API_KEY","").strip()
JEV_KEY=os.getenv("APINEX_API_KEY","").strip()
GEMINI_MODEL=os.getenv("YOUTUBE_GEMINI_MODEL","gemini-2.5-flash").strip()
JEV_MODEL=os.getenv("YOUTUBE_JEV_MODEL","free/deepseek-v4.1-flash").strip()
SYSTEM=("Ти незалежний дослідник КриптоМишки. Розглядай відео як заяви автора, "
"не як підтверджені ринкові факти. Став під сумнів обіцянки прибутку. "
"Не давай BUY/SELL, ціну входу, сигнали чи команду відкривати угоду. "
"Відповідай українською, до 850 символів. Не вигадуй джерела.")
def gemini(prompt):
    r=requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
      headers={"x-goog-api-key":GEMINI_KEY},json={"contents":[{"parts":[{"text":SYSTEM+"\n"+prompt}]}],
      "generationConfig":{"temperature":0.2}},timeout=65)
    r.raise_for_status()
    return " ".join(p.get("text","") for p in r.json()["candidates"][0]["content"]["parts"])[:1100]
def jev(prompt):
    r=requests.post("https://api.apinex.bond/v1/chat/completions",
      headers={"Authorization":"Bearer "+JEV_KEY},json={"model":JEV_MODEL,"temperature":0.2,
      "max_tokens":400,"messages":[{"role":"system","content":SYSTEM},{"role":"user","content":prompt}]},timeout=50)
    r.raise_for_status()
    return str(r.json()["choices"][0]["message"]["content"])[:1100]
def run():
    if not (GEMINI_KEY and JEV_KEY and JEV_MODEL.startswith("free/")):
        print("Research dialogue skipped: both provider keys and a free JEV model required");return
    if not FEED.exists():print("Research dialogue skipped: no knowledge feed");return
    feed=json.loads(FEED.read_text(encoding="utf-8"))
    previous=json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"items":[]}
    items=previous.get("items",[])
    known={x.get("video_id") for x in items}
    # Only genuine video/audio Gemini analyses; subtitle-only or metadata do not qualify.
    pending=[x for x in feed.get("items",[]) if x.get("source")=="gemini_video" and x.get("video_id") not in known]
    if not pending:print("Research dialogue: no new Gemini-reviewed videos");return
    item=pending[0]
    context=json.dumps({k:item.get(k) for k in ("url","channel","summary","strategy","risk","pairs","indicators")},ensure_ascii=False)
    try:
        first=jev("JEV, проаналізуй конспект Gemini, назви 2 сумніви та 1 практичний принцип ризик-менеджменту. Дані: "+context[:3500])
        second=gemini("Gemini, відповідай на сумніви JEV, вкажи, що не можна перевірити за відео.\n"+context[:2500]+"\nJEV: "+first)
        final=jev("JEV, підсумуй дискусію для внутрішньої бази знань: корисна ідея, обмеження, що перевірити окремо. НЕ торговий сигнал.\n"+context[:2300]+"\nТвоя критика: "+first+"\nВідповідь Gemini: "+second)
    except (requests.RequestException,KeyError,IndexError,ValueError,TypeError) as exc:
        print("Dialogue provider unavailable:",type(exc).__name__);return
    items.append({"video_id":item["video_id"],"url":item.get("url"),"channel":item.get("channel"),
      "created_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
      "gemini_source":"video/audio summary already reviewed","rounds":[{"agent":"JEV","text":first},
      {"agent":"Gemini","text":second},{"agent":"JEV","text":final}],
      "conclusion":final,"verified_market_signal":False,"trade_permission":False,
      "requires_independent_validation":True})
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({"version":1,"purpose":"Research only; no order execution",
      "items_count":len(items),"items":items},ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8")
    print("Research dialogue completed:",item["video_id"])
if __name__=="__main__":run()

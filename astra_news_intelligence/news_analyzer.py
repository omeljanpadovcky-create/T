"""Ollama crypto-news classifier for MYSHKA / ASTRA. SHADOW only."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib, json, math, os, re, sqlite3, threading, time
from typing import Optional
import requests

ENABLED=os.getenv("NEWS_INTELLIGENCE_ENABLED","true").lower() in {"1","true","yes","on"}
DB_PATH=os.getenv("NEWS_INTELLIGENCE_DB_PATH","/data/myshka_news_intelligence.sqlite3")
CONTEXT_DB_PATH=os.getenv("CONTEXT_DB_PATH","/data/myshka_context.sqlite3")
OLLAMA_BASE=(os.getenv("NEWS_OLLAMA_BASE_URL") or os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_URL") or "http://host.docker.internal:11434").rstrip("/")
PREFERRED_MODEL=os.getenv("NEWS_OLLAMA_MODEL") or os.getenv("OLLAMA_MODEL") or ""
TIMEOUT=max(5.0,float(os.getenv("NEWS_OLLAMA_TIMEOUT_SEC","20")))
POLL_SEC=max(30,int(os.getenv("NEWS_INTELLIGENCE_POLL_SEC","60")))
LOOKBACK_MIN=max(30,min(720,int(os.getenv("NEWS_INTELLIGENCE_LOOKBACK_MIN","180"))))
SOURCE_HOURS=max(1,min(48,int(os.getenv("NEWS_INTELLIGENCE_SOURCE_LOOKBACK_HOURS","12"))))
MAX_BATCH=max(1,min(20,int(os.getenv("NEWS_INTELLIGENCE_MAX_BATCH","6"))))
RETRY_SEC=max(60,int(os.getenv("NEWS_INTELLIGENCE_RETRY_SEC","600")))
THRESHOLD=min(.75,max(.05,float(os.getenv("NEWS_INTELLIGENCE_STATE_THRESHOLD",".15"))))
DECAY_HALF_LIFE_MIN=max(5.0,min(360.0,float(os.getenv("NEWS_INTELLIGENCE_DECAY_HALF_LIFE_MIN","45"))))
DEDUP_JACCARD=max(.40,min(.95,float(os.getenv("NEWS_INTELLIGENCE_DEDUP_JACCARD",".68"))))
DEDUP_WINDOW_MIN=max(30,min(720,int(os.getenv("NEWS_INTELLIGENCE_DEDUP_WINDOW_MIN","360"))))
_LOCK=threading.RLock(); _THREAD=None; _STOP=threading.Event()
_STATUS={"running":False,"last_cycle_at":None,"last_success_at":None,"last_error":None,"last_model":None,"ollama_status":"unknown","ollama_error":None,"cycles":0,"last_deduped":0,"last_universe":[]}

def _num(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def _clamp(v,d=.5):
    x=_num(v); return d if x is None else max(0.0,min(1.0,x))

def _conn(path=DB_PATH):
    os.makedirs(os.path.dirname(path) or ".",exist_ok=True)
    c=sqlite3.connect(path,timeout=10); c.row_factory=sqlite3.Row
    if path==DB_PATH:
        c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=NORMAL")
    return c

@contextmanager
def _db(path=DB_PATH):
    c=_conn(path)
    try: yield c; c.commit()
    except Exception: c.rollback(); raise
    finally:c.close()

def init():
    with _LOCK,_db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS news_analysis(
          id INTEGER PRIMARY KEY AUTOINCREMENT,source_key TEXT UNIQUE NOT NULL,source_ts REAL NOT NULL,
          title TEXT NOT NULL,summary TEXT,url TEXT,feed TEXT,analyzed_at REAL NOT NULL,status TEXT NOT NULL,
          sentiment TEXT,sentiment_score REAL,confidence REAL,importance REAL,scope TEXT,assets_json TEXT,
          reason TEXT,model TEXT,error TEXT)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_news_time ON news_analysis(source_ts DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_news_status ON news_analysis(status,analyzed_at)")
    return {"enabled":ENABLED,"mode":"NEWS_INTELLIGENCE_SHADOW","db_path":DB_PATH}

def _key(p,ts):
    raw=str(p.get("url") or "").strip() or f"{p.get('title','')}|{int(ts)}|{p.get('feed','')}"
    return hashlib.sha256(raw.encode("utf-8",errors="ignore")).hexdigest()

def _source(limit=200):
    if not os.path.exists(CONTEXT_DB_PATH): return []
    cutoff=time.time()-SOURCE_HOURS*3600
    try:
        with _db(CONTEXT_DB_PATH) as c:
            rows=c.execute("SELECT ts,payload FROM context_samples WHERE source='rss' AND kind='headline' AND ts>=? ORDER BY ts DESC LIMIT ?",(cutoff,int(limit))).fetchall()
        out=[]
        for r in rows:
            try:p=json.loads(r["payload"] or "{}")
            except Exception:continue
            title=str(p.get("title") or "").strip()
            if not title:continue
            ts=float(r["ts"])
            out.append({"key":_key(p,ts),"ts":ts,"title":title[:300],"summary":str(p.get("summary") or "")[:1600],"url":str(p.get("url") or "")[:1000],"feed":str(p.get("feed") or "")[:1000]})
        return out
    except Exception:return []


_STOPWORDS={"the","a","an","and","or","to","of","in","on","for","with","as","at","by","from","is","are","was","were","will","after","before","over","amid","says","say","new","crypto"}

def _universe_assets(now=None):
    """Read the latest dynamic universe directly from Context 24/7."""
    if not os.path.exists(CONTEXT_DB_PATH):
        return ["BTC","ETH","SOL"]
    cutoff=float(now or time.time())-30*60
    try:
        with _db(CONTEXT_DB_PATH) as c:
            rows=c.execute(
                """SELECT pair,MAX(ts) latest
                   FROM context_samples
                   WHERE source='bybit' AND kind='market' AND ts>=? AND pair!='*'
                   GROUP BY pair ORDER BY latest DESC LIMIT 15""",
                (cutoff,),
            ).fetchall()
        out=[]
        for r in rows:
            base=str(r["pair"] or "").split("/")[0].split(":")[0].upper()
            if base and base not in out:out.append(base)
        return out or ["BTC","ETH","SOL"]
    except Exception:
        return ["BTC","ETH","SOL"]

def _title_tokens(title):
    words=re.findall(r"[a-z0-9]+",str(title or "").lower())
    return {w for w in words if len(w)>2 and w not in _STOPWORDS}

def _title_similarity(a,b):
    x,y=_title_tokens(a),_title_tokens(b)
    if not x or not y:return 0.0
    return len(x&y)/max(1,len(x|y))

def _dedup_items(items):
    """Collapse syndicated versions of the same story before Ollama analysis."""
    kept=[]; dropped=0
    window=DEDUP_WINDOW_MIN*60
    for item in items:
        dup=None
        for prev in kept:
            if abs(float(item["ts"])-float(prev["ts"]))>window:continue
            if _title_similarity(item["title"],prev["title"])>=DEDUP_JACCARD:
                dup=prev; break
        if dup is None:
            kept.append(item)
        else:
            dropped+=1
            # Keep the richer summary while retaining only one logical event.
            if len(str(item.get("summary") or ""))>len(str(dup.get("summary") or "")):
                dup["summary"]=item.get("summary") or dup.get("summary")
            feeds=set(dup.get("feeds") or [dup.get("feed")])
            feeds.add(item.get("feed"))
            dup["feeds"]=[x for x in feeds if x]
    return kept,dropped

def _model():
    try:
        r=requests.get(OLLAMA_BASE+"/api/tags",timeout=min(10,TIMEOUT)); r.raise_for_status()
        names=[str((x or {}).get("name") or (x or {}).get("model") or "") for x in (r.json().get("models") or [])]
        names=[x for x in names if x]
        if not names:return None,"no models"
        if PREFERRED_MODEL:
            hit=next((x for x in names if x==PREFERRED_MODEL or x.split(":")[0]==PREFERRED_MODEL.split(":")[0]),None)
            if hit:return hit,None
        return next((x for x in names if "qwen" in x.lower()),names[0]),None
    except Exception as e:return None,f"{type(e).__name__}: {e}"

def _extract(s):
    raw=str(s or "").strip()
    if raw.startswith("json"):raw=raw[4:].lstrip()
    try:
        x=json.loads(raw); return x if isinstance(x,dict) else {}
    except Exception:
        a,b=raw.find("{"),raw.rfind("}")
        if a>=0 and b>a:
            try:
                x=json.loads(raw[a:b+1]); return x if isinstance(x,dict) else {}
            except Exception:pass
    return {}

def normalize(obj,text="",allowed_assets=None):
    sent=str(obj.get("sentiment") or "NEUTRAL").upper()
    if sent not in {"BULLISH","BEARISH","NEUTRAL"}:sent="NEUTRAL"
    score=1.0 if sent=="BULLISH" else -1.0 if sent=="BEARISH" else 0.0

    allowed=[str(x).upper() for x in (allowed_assets or _universe_assets()) if str(x).strip()]
    allowed_set=set(allowed)
    raw=obj.get("assets"); raw=[raw] if isinstance(raw,str) else (raw or [])
    aliases={
        "BITCOIN":"BTC","ETHEREUM":"ETH","SOLANA":"SOL","DOGECOIN":"DOGE",
        "RIPPLE":"XRP","CARDANO":"ADA","AVALANCHE":"AVAX","CHAINLINK":"LINK",
        "POLKADOT":"DOT","LITECOIN":"LTC","ARBITRUM":"ARB","APTOS":"APT",
        "MARKET":"MARKET","CRYPTO":"MARKET","ALL":"MARKET"
    }
    assets=[]
    for x in raw:
        u=str(x).upper().strip()
        a=aliases.get(u,u)
        if (a=="MARKET" or a in allowed_set) and a not in assets:assets.append(a)

    up=str(text or "").upper()
    if not assets:
        # First use known project names, then current dynamic symbols.
        for name,sym in aliases.items():
            if sym=="MARKET":continue
            if sym in allowed_set and re.search(r"\b"+re.escape(name)+r"\b",up):
                if sym not in assets:assets.append(sym)
        for sym in allowed:
            if re.search(r"\b"+re.escape(sym)+r"\b",up) and sym not in assets:
                assets.append(sym)
    if not assets:assets=["MARKET"]

    scope=str(obj.get("scope") or "OTHER").upper()
    if scope not in {"ASSET","MARKET","MACRO","REGULATION","SECURITY","OTHER"}:scope="OTHER"
    return {"sentiment":sent,"score":score,"confidence":_clamp(obj.get("confidence")),"importance":_clamp(obj.get("importance")),"scope":scope,"assets":assets[:8],"reason":str(obj.get("reason") or "")[:240]}

def _analyze(item,model):
    universe=_universe_assets()
    allowed=", ".join(universe+["MARKET"])
    prompt="""Classify this crypto news item for a PAPER-only research system.
Return JSON only with: sentiment (BULLISH|BEARISH|NEUTRAL), assets (array using ONLY: """+allowed+"""),
confidence (0..1), importance (0..1), scope (ASSET|MARKET|MACRO|REGULATION|SECURITY|OTHER),
reason (factual, max 160 chars). Do not give trading advice.
If the story affects crypto broadly rather than one current asset, use MARKET.

TITLE:
"""+item["title"]+"\n\nSUMMARY:\n"+item["summary"]
    r=requests.post(OLLAMA_BASE+"/api/generate",json={"model":model,"prompt":prompt,"stream":False,"format":"json"},timeout=TIMEOUT)
    r.raise_for_status(); obj=_extract(r.json().get("response"))
    if not obj:raise RuntimeError("invalid Ollama JSON")
    return normalize(obj,item["title"]+" "+item["summary"],allowed_assets=universe)

def _pending(item,now):
    with _LOCK,_db() as c:r=c.execute("SELECT status,analyzed_at FROM news_analysis WHERE source_key=?",(item["key"],)).fetchone()
    return (not r) or (str(r["status"])!="OK" and now-float(r["analyzed_at"] or 0)>=RETRY_SEC)

def _save(item,status,model="",a=None,error=""):
    a=a or {}; now=time.time()
    with _LOCK,_db() as c:
        c.execute("""INSERT INTO news_analysis(source_key,source_ts,title,summary,url,feed,analyzed_at,status,sentiment,sentiment_score,confidence,importance,scope,assets_json,reason,model,error)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_key) DO UPDATE SET source_ts=excluded.source_ts,title=excluded.title,summary=excluded.summary,url=excluded.url,feed=excluded.feed,analyzed_at=excluded.analyzed_at,status=excluded.status,sentiment=excluded.sentiment,sentiment_score=excluded.sentiment_score,confidence=excluded.confidence,importance=excluded.importance,scope=excluded.scope,assets_json=excluded.assets_json,reason=excluded.reason,model=excluded.model,error=excluded.error""",
        (item["key"],item["ts"],item["title"],item["summary"],item["url"],item["feed"],now,status,a.get("sentiment"),_num(a.get("score")),_num(a.get("confidence")),_num(a.get("importance")),a.get("scope"),json.dumps(a.get("assets") or []),a.get("reason"),model,str(error)[:500]))

def refresh_now(limit=None):
    init(); now=time.time(); model,err=_model()
    if not model:
        with _LOCK:_STATUS.update({"last_cycle_at":now,"last_error":err,"ollama_status":"unavailable","ollama_error":err})
        return {"status":"error","error":err,"analyzed":0}
    raw_items=_source(); items,deduped=_dedup_items(raw_items)
    universe=_universe_assets(now)
    todo=[x for x in items if _pending(x,now)][:max(1,min(MAX_BATCH,int(limit or MAX_BATCH)))]
    ok=bad=0
    for item in reversed(todo):
        try:_save(item,"OK",model,_analyze(item,model)); ok+=1
        except Exception as e:_save(item,"ERROR",model,error=f"{type(e).__name__}: {e}"); bad+=1
    with _LOCK:_STATUS.update({"last_cycle_at":time.time(),"last_success_at":time.time() if ok else _STATUS.get("last_success_at"),"last_error":None if not bad else f"{bad} failed","last_model":model,"ollama_status":"ok","ollama_error":None,"cycles":int(_STATUS.get("cycles") or 0)+1,"last_deduped":deduped,"last_universe":universe})
    return {"status":"ok" if not bad else "partial","model":model,"headlines_seen":len(raw_items),"unique_headlines":len(items),"deduped":deduped,"universe_assets":universe,"pending":len(todo),"analyzed":ok,"failed":bad}

def _loop():
    with _LOCK:_STATUS["running"]=True
    while not _STOP.is_set():
        try:refresh_now()
        except Exception as e:
            with _LOCK:_STATUS.update({"last_cycle_at":time.time(),"last_error":f"{type(e).__name__}: {e}"})
        _STOP.wait(POLL_SEC)
    with _LOCK:_STATUS["running"]=False

def start():
    global _THREAD
    init()
    if not ENABLED:return status()
    with _LOCK:
        if _THREAD and _THREAD.is_alive():return status()
        _STOP.clear(); _THREAD=threading.Thread(target=_loop,name="myshka-news-intelligence",daemon=True); _THREAD.start()
    return status()

def _asset(pair):return str(pair or "").split("/")[0].split(":")[0].upper()

def recent_for_pair(pair,now=None):
    cutoff=float(now or time.time())-LOOKBACK_MIN*60; asset=_asset(pair)
    with _LOCK,_db() as c:rows=[dict(x) for x in c.execute("SELECT * FROM news_analysis WHERE status='OK' AND source_ts>=? ORDER BY source_ts DESC",(cutoff,)).fetchall()]
    out=[]
    for r in rows:
        try:assets=[str(x).upper() for x in json.loads(r.get("assets_json") or "[]")]
        except Exception:assets=[]
        if "MARKET" in assets or asset in assets:r["assets"]=assets; out.append(r)
    return out

def aggregate(pair,now=None):
    ts=float(now or time.time())
    rows=recent_for_pair(pair,ts)
    if not rows:return {"tone":"NO_NEWS","score":0.0,"confidence":0.0,"count":0,"effective_weight":0.0,"ids":[]}
    num=den=conf=0.0
    for r in rows:
        confidence=_clamp(r.get("confidence"))
        importance=_clamp(r.get("importance"))
        age_min=max(0.0,(ts-float(r.get("source_ts") or ts))/60.0)
        decay=0.5**(age_min/DECAY_HALF_LIFE_MIN)
        w=max(.001,confidence*(.35+.65*importance)*decay)
        num+=float(r.get("sentiment_score") or 0)*w
        den+=w
        conf+=confidence*w
    score=num/den if den else 0.0
    tone="BULLISH" if score>THRESHOLD else "BEARISH" if score<-THRESHOLD else "NEUTRAL"
    return {"tone":tone,"score":score,"confidence":conf/den if den else 0.0,"count":len(rows),"effective_weight":den,"ids":[int(r["id"]) for r in rows[:20]]}

def recent(limit=8):
    init()
    with _LOCK,_db() as c:rows=[dict(x) for x in c.execute("SELECT id,source_ts,title,url,sentiment,confidence,importance,scope,assets_json,reason,model FROM news_analysis WHERE status='OK' ORDER BY source_ts DESC LIMIT ?",(max(1,min(30,int(limit))),)).fetchall()]
    for r in rows:
        try:r["assets"]=json.loads(r.pop("assets_json") or "[]")
        except Exception:r["assets"]=[]
    return rows

def report():
    init()
    with _LOCK,_db() as c:counts={str(x["status"]):int(x["n"]) for x in c.execute("SELECT status,COUNT(*) n FROM news_analysis GROUP BY status")}
    universe=_universe_assets()
    current={"MARKET":aggregate("MARKET/USDT:USDT")}
    for asset in universe:
        current[asset]=aggregate(asset+"/USDT:USDT")
    st=status()
    return {"status":"ok","mode":"NEWS_INTELLIGENCE_SHADOW","analysis_ok":counts.get("OK",0),"analysis_error":counts.get("ERROR",0),"lookback_minutes":LOOKBACK_MIN,"decay_half_life_minutes":DECAY_HALF_LIFE_MIN,"dedup_jaccard":DEDUP_JACCARD,"dedup_window_minutes":DEDUP_WINDOW_MIN,"universe_assets":universe,"last_deduped":int(st.get("last_deduped") or 0),"last_universe":st.get("last_universe") or universe,"current":current,"recent_headlines":recent(12),"ollama":st["ollama"],"changes_trading_decisions":False,"live_execution":False}

def status():
    init()
    with _LOCK:out=dict(_STATUS)
    out.update({"enabled":ENABLED,"mode":"NEWS_INTELLIGENCE_SHADOW","db_path":DB_PATH,"context_db_path":CONTEXT_DB_PATH,"ollama":{"base_url":OLLAMA_BASE,"model":out.get("last_model"),"status":out.get("ollama_status") or "unknown","error":out.get("ollama_error")},"lookback_minutes":LOOKBACK_MIN,"decay_half_life_minutes":DECAY_HALF_LIFE_MIN,"dedup_jaccard":DEDUP_JACCARD,"dedup_window_minutes":DEDUP_WINDOW_MIN,"universe_assets":_universe_assets(),"changes_trading_decisions":False,"live_execution":False})
    return out

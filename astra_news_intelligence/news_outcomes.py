"""Forward outcome tracker for News Intelligence SHADOW."""
from __future__ import annotations
from contextlib import contextmanager
import json, math, os, sqlite3, threading, time
from .news_analyzer import aggregate

DB_PATH=os.getenv("NEWS_INTELLIGENCE_DB_PATH","/data/myshka_news_intelligence.sqlite3")
HORIZONS=tuple(sorted({int(x) for x in os.getenv("NEWS_INTELLIGENCE_HORIZONS_SEC","300,600,900").split(",") if x.strip()}))
MAX_DELAY=max(30,int(os.getenv("NEWS_INTELLIGENCE_MAX_SETTLE_DELAY_SEC","120")))
CLUSTER_SEC=max(60,int(os.getenv("NEWS_INTELLIGENCE_CLUSTER_SEC","300")))
_LOCK=threading.RLock()

def _num(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def _conn():
    os.makedirs(os.path.dirname(DB_PATH) or ".",exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=10); c.row_factory=sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=NORMAL")
    return c

@contextmanager
def _db():
    c=_conn()
    try: yield c; c.commit()
    except Exception: c.rollback(); raise
    finally:c.close()

def init():
    with _LOCK,_db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS news_outcomes(
          id INTEGER PRIMARY KEY AUTOINCREMENT,pair TEXT NOT NULL,side TEXT NOT NULL,source_minute INTEGER NOT NULL,
          cluster_key TEXT NOT NULL,opened_at REAL NOT NULL,target_at REAL NOT NULL,horizon_sec INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'OPEN',entry_price REAL NOT NULL,total_cost_pct REAL,news_state TEXT NOT NULL,
          news_score REAL,news_confidence REAL,news_count INTEGER NOT NULL,analysis_ids_json TEXT,settled_at REAL,
          settle_delay_sec REAL,exit_price REAL,gross_pct REAL,net_pct REAL,direction_hit INTEGER,
          UNIQUE(pair,side,source_minute,horizon_sec))""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_news_out_target ON news_outcomes(status,target_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_news_out_state ON news_outcomes(news_state,horizon_sec,status)")
        c.execute("""CREATE TABLE IF NOT EXISTS news_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)""")
        r=c.execute("SELECT value FROM news_meta WHERE key='forward_started_at'").fetchone()
        if not r:c.execute("INSERT INTO news_meta(key,value) VALUES('forward_started_at',?)",(str(time.time()),))
    return {"enabled":True,"mode":"NEWS_INTELLIGENCE_SHADOW","horizons_sec":list(HORIZONS)}

def _started():
    init()
    with _LOCK,_db() as c:
        r=c.execute("SELECT value FROM news_meta WHERE key='forward_started_at'").fetchone()
        return float(r["value"]) if r else time.time()

def _price(r):
    m=r.get("market") or {}
    for k in ("last_price","last","price","close"):
        x=_num(m.get(k))
        if x is not None and x>0:return x
    return None

def _side(r):
    s=r.get("signal") or {}
    return str(r.get("direction") or s.get("direction") or "WAIT").upper()

def _align(side,a):
    tone=str(a.get("tone") or "NO_NEWS")
    if tone=="NO_NEWS":return "NO_NEWS"
    if tone=="NEUTRAL":return "NEUTRAL"
    bullish=tone=="BULLISH"
    return "ALIGNED" if ((side=="LONG" and bullish) or (side=="SHORT" and not bullish)) else "CONFLICT"

def _settle(results,now):
    by_pair={str(r.get("pair") or ""):r for r in results or [] if r.get("pair")}
    closed=skipped=0
    with _LOCK,_db() as c:
        rows=c.execute("SELECT * FROM news_outcomes WHERE status='OPEN' AND target_at<=? ORDER BY target_at",(now,)).fetchall()
        for row in rows:
            delay=max(0.0,now-float(row["target_at"]))
            if delay>MAX_DELAY:
                c.execute("UPDATE news_outcomes SET status='SKIPPED',settled_at=?,settle_delay_sec=? WHERE id=?",(now,delay,int(row["id"]))); skipped+=1; continue
            r=by_pair.get(str(row["pair"])); exitp=_price(r) if r else None
            if exitp is None:continue
            entry=float(row["entry_price"]); raw=(exitp-entry)/entry*100.0
            gross=raw if str(row["side"])=="LONG" else -raw
            net=gross-float(row["total_cost_pct"] or 0.0)
            c.execute("UPDATE news_outcomes SET status='CLOSED',settled_at=?,settle_delay_sec=?,exit_price=?,gross_pct=?,net_pct=?,direction_hit=? WHERE id=? AND status='OPEN'",
              (now,delay,exitp,gross,net,1 if gross>0 else 0,int(row["id"]))); closed+=1
    return {"closed":closed,"skipped":skipped}

def observe_results(results,now=None):
    try:
        init(); ts=float(now or time.time()); settled=_settle(results or [],ts); created=attached=0
        for r in results or []:
            side=_side(r)
            if side not in {"LONG","SHORT"}:
                r["news_intelligence"]={"state":"NOT_APPLICABLE","shadow_only":True}; continue
            pair=str(r.get("pair") or ""); entry=_price(r)
            if not pair or entry is None:continue
            a=aggregate(pair,ts); state=_align(side,a)
            r["news_intelligence"]={"state":state,"market_tone":a.get("tone"),"score":a.get("score"),"confidence":a.get("confidence"),"news_count":a.get("count"),"shadow_only":True}
            attached+=1; edge=r.get("edge") or {}; minute=int(ts//60)*60; bucket=int(ts//CLUSTER_SEC)*CLUSTER_SEC; key=f"{pair}|{side}|{bucket}"
            with _LOCK,_db() as c:
                for h in HORIZONS:
                    cur=c.execute("""INSERT OR IGNORE INTO news_outcomes(pair,side,source_minute,cluster_key,opened_at,target_at,horizon_sec,status,entry_price,total_cost_pct,news_state,news_score,news_confidence,news_count,analysis_ids_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(pair,side,minute,key,ts,ts+int(h),int(h),"OPEN",entry,_num(edge.get("total_cost_pct")),state,_num(a.get("score")),_num(a.get("confidence")),int(a.get("count") or 0),json.dumps(a.get("ids") or [])))
                    created+=int(bool(cur.rowcount))
        return {"status":"ok","attached":attached,"created":created,**settled}
    except Exception as e:return {"status":"error","error":f"{type(e).__name__}: {e}","attached":0,"created":0,"closed":0,"skipped":0}

def _pf(v):
    p=sum(x for x in v if x>0); n=abs(sum(x for x in v if x<=0))
    return p/n if n>1e-12 else (999.0 if p>0 else 0.0)

def _core(rows):
    v=[float(r["net_pct"]) for r in rows if _num(r.get("net_pct")) is not None]; n=len(v); w=sum(1 for x in v if x>0)
    return {"n":n,"win_rate_pct":w/n*100 if n else 0.0,"avg_net_pct":sum(v)/n if n else 0.0,"profit_factor":_pf(v)}

def _clusters(rows):
    seen=set(); out=[]
    for r in sorted(rows,key=lambda x:(float(x.get("opened_at") or 0),int(x.get("id") or 0))):
        k=str(r.get("cluster_key") or "")
        if k in seen:continue
        seen.add(k); out.append(r)
    return out

def _metrics(rows):
    a=_core(rows); b=_core(_clusters(rows))
    return {**a,"cluster_n":b["n"],"cluster_win_rate_pct":b["win_rate_pct"],"cluster_avg_net_pct":b["avg_net_pct"],"cluster_profit_factor":b["profit_factor"]}

def report():
    init(); start=_started()
    with _LOCK,_db() as c:
        rows=[dict(x) for x in c.execute("SELECT * FROM news_outcomes WHERE status='CLOSED' AND opened_at>=? ORDER BY opened_at,id",(start,)).fetchall()]
        counts={str(x["status"]):int(x["n"]) for x in c.execute("SELECT status,COUNT(*) n FROM news_outcomes WHERE opened_at>=? GROUP BY status",(start,))}
    by={}
    for h in HORIZONS:
        part=[r for r in rows if int(r.get("horizon_sec") or 0)==int(h)]
        by[str(h)]={"all":_metrics(part)}
        for state in ("ALIGNED","CONFLICT","NEUTRAL","NO_NEWS"):
            by[str(h)][state]=_metrics([r for r in part if r.get("news_state")==state])
    return {"status":"ok","mode":"NEWS_INTELLIGENCE_SHADOW","forward_started_at":start,"horizons_sec":list(HORIZONS),"open":counts.get("OPEN",0),"closed":counts.get("CLOSED",0),"skipped":counts.get("SKIPPED",0),"by_horizon":by,"changes_paper_execution":False,"changes_trading_decisions":False,"live_execution":False}

def status():
    init()
    return {"enabled":True,"mode":"NEWS_INTELLIGENCE_SHADOW","db_path":DB_PATH,"horizons_sec":list(HORIZONS),"changes_paper_execution":False,"changes_trading_decisions":False,"live_execution":False}

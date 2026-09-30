"""Research controls and live-readiness diagnostics for MYSHKA / ASTRA.

This module is observational only. It cannot create orders, switch execution
mode, alter ENTER/DROP, size positions, or enable LIVE routing.
"""
from __future__ import annotations
from contextlib import contextmanager
import json, math, os, re, sqlite3, time
from urllib.parse import urlparse

NEWS_DB=os.getenv("NEWS_INTELLIGENCE_DB_PATH","/data/myshka_news_intelligence.sqlite3")
CONTEXT_DB=os.getenv("CONTEXT_DB_PATH","/data/myshka_context.sqlite3")
ANALYTICS_DB=os.getenv("ANALYTICS_DB_PATH","/data/myshka_analytics.sqlite3")
HARDENING_DB=os.getenv("HARDENING_DB_PATH","/data/myshka_hardening.sqlite3")

MIN_STRICT=int(os.getenv("LIVE_READINESS_MIN_STRICT","150"))
MIN_PF=float(os.getenv("LIVE_READINESS_MIN_PF","1.20"))
MAX_DQ_AGE=int(os.getenv("LIVE_READINESS_MAX_DQ_AGE_SEC","300"))
RSS_WARN_AGE=int(os.getenv("NEWS_QUALITY_RSS_WARN_AGE_SEC","900"))
RSS_FAIL_AGE=int(os.getenv("NEWS_QUALITY_RSS_FAIL_AGE_SEC","3600"))


def _conn(path):
    c=sqlite3.connect(path,timeout=10)
    c.row_factory=sqlite3.Row
    return c

@contextmanager
def _db(path):
    c=_conn(path)
    try: yield c
    finally: c.close()

def _num(v):
    try:
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def _pf(vals):
    pos=sum(x for x in vals if x>0)
    neg=abs(sum(x for x in vals if x<=0))
    return pos/neg if neg>1e-12 else (999.0 if pos>0 else 0.0)

def _metrics(rows):
    vals=[float(r["net_pct"]) for r in rows if _num(r.get("net_pct")) is not None]
    n=len(vals); wins=sum(1 for x in vals if x>0)
    return {
        "n":n,
        "win_rate_pct":wins/n*100.0 if n else 0.0,
        "avg_net_pct":sum(vals)/n if n else 0.0,
        "profit_factor":_pf(vals),
        "total_net_pct":sum(vals),
    }

def _feed_name(url):
    try:
        host=(urlparse(str(url or "")).hostname or "").lower()
        return host.replace("www.","") or "unknown"
    except Exception:return "unknown"

def _news_rows(hours=12):
    if not os.path.exists(NEWS_DB):return []
    cutoff=time.time()-hours*3600
    with _db(NEWS_DB) as c:
        try:
            rows=c.execute("SELECT * FROM news_analysis WHERE source_ts>=? ORDER BY source_ts DESC",(cutoff,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:return []

def _context_rss_rows(hours=6):
    if not os.path.exists(CONTEXT_DB):return []
    cutoff=time.time()-hours*3600
    out=[]
    with _db(CONTEXT_DB) as c:
        try:
            rows=c.execute("SELECT ts,payload FROM context_samples WHERE source='rss' AND kind='headline' AND ts>=? ORDER BY ts DESC",(cutoff,)).fetchall()
        except Exception:return []
    for r in rows:
        try:p=json.loads(r["payload"] or "{}")
        except Exception:p={}
        out.append({"ts":float(r["ts"]),"payload":p})
    return out

def news_quality_report():
    now=time.time()
    rss=_context_rss_rows(6)
    analyzed=_news_rows(12)
    checks=[]

    latest_rss=max([float(x["ts"]) for x in rss],default=0.0)
    rss_age=(now-latest_rss) if latest_rss else None
    if rss_age is None:
        checks.append({"name":"rss_freshness","state":"FAIL","detail":"no RSS headlines in last 6h"})
    elif rss_age>RSS_FAIL_AGE:
        checks.append({"name":"rss_freshness","state":"FAIL","detail":f"age {rss_age:.0f}s"})
    elif rss_age>RSS_WARN_AGE:
        checks.append({"name":"rss_freshness","state":"WARN","detail":f"age {rss_age:.0f}s"})
    else:
        checks.append({"name":"rss_freshness","state":"OK","detail":f"age {rss_age:.0f}s"})

    ok=sum(1 for r in analyzed if str(r.get("status") or "")=="OK")
    err=sum(1 for r in analyzed if str(r.get("status") or "")=="ERROR")
    total=ok+err
    err_rate=err/total if total else 0.0
    checks.append({
        "name":"ollama_analysis_errors",
        "state":"FAIL" if total>=5 and err_rate>.50 else "WARN" if total>=5 and err_rate>.20 else "OK",
        "detail":f"{err}/{total} · {err_rate*100:.1f}%",
    })

    future=sum(1 for r in analyzed if float(r.get("source_ts") or 0)>now+60)
    checks.append({"name":"future_timestamps","state":"FAIL" if future else "OK","detail":str(future)})

    empty=sum(1 for x in rss if not str((x.get("payload") or {}).get("summary") or "").strip())
    empty_rate=empty/len(rss) if rss else 0.0
    checks.append({
        "name":"empty_summary",
        "state":"WARN" if len(rss)>=5 and empty_rate>.50 else "OK",
        "detail":f"{empty}/{len(rss)} · {empty_rate*100:.1f}%",
    })

    titles=[]
    for x in rss:
        t=re.sub(r"[^a-z0-9]+"," ",str((x.get("payload") or {}).get("title") or "").lower()).strip()
        if t:titles.append(t)
    dup=len(titles)-len(set(titles))
    dup_rate=dup/len(titles) if titles else 0.0
    checks.append({
        "name":"exact_duplicate_storm",
        "state":"WARN" if len(titles)>=10 and dup_rate>.35 else "OK",
        "detail":f"{dup}/{len(titles)} · {dup_rate*100:.1f}%",
    })

    market_only=unknown=0
    universe=set()
    if os.path.exists(CONTEXT_DB):
        with _db(CONTEXT_DB) as c:
            try:
                rows=c.execute("SELECT DISTINCT pair FROM context_samples WHERE source='bybit' AND kind='market' AND ts>=?",(now-1800,)).fetchall()
                universe={str(r["pair"]).split("/")[0].split(":")[0].upper() for r in rows}
            except Exception:universe=set()
    for r in analyzed:
        if str(r.get("status") or "")!="OK":continue
        try:assets=[str(x).upper() for x in json.loads(r.get("assets_json") or "[]")]
        except Exception:assets=[]
        if assets==["MARKET"]:market_only+=1
        if any(a!="MARKET" and universe and a not in universe for a in assets):unknown+=1
    ok_rows=max(1,ok)
    market_rate=market_only/ok_rows
    checks.append({
        "name":"market_label_overuse",
        "state":"WARN" if ok>=10 and market_rate>.80 else "OK",
        "detail":f"{market_only}/{ok} · {market_rate*100:.1f}%",
    })
    checks.append({"name":"unknown_assets","state":"WARN" if unknown else "OK","detail":str(unknown)})

    states=[x["state"] for x in checks]
    state="FAIL" if "FAIL" in states else "WARN" if "WARN" in states else "OK"
    return {
        "status":"ok","mode":"DIAGNOSTIC_ONLY","state":state,"checks":checks,
        "rss_headlines_6h":len(rss),"analysis_ok_12h":ok,"analysis_error_12h":err,
        "fail_open_behavior":"NEWS SHADOW may fail; core ASTRA execution remains independent",
        "changes_trading_decisions":False,"live_execution":False,
    }

def story_report(limit=30):
    rows=_news_rows(72)
    groups={}
    for r in rows:
        sid=str(r.get("story_id") or "UNKNOWN")
        g=groups.setdefault(sid,{"story_id":sid,"count":0,"stages":set(),"events":set(),"sources":set(),"assets":set(),"latest_ts":0.0,"latest_title":""})
        g["count"]+=1
        g["stages"].add(str(r.get("lifecycle_stage") or "UNKNOWN"))
        g["events"].add(str(r.get("event_type") or "OTHER"))
        try:feeds=json.loads(r.get("feeds_json") or "[]")
        except Exception:feeds=[]
        for f in feeds or [r.get("feed")]:
            if f:g["sources"].add(_feed_name(f))
        try:assets=json.loads(r.get("assets_json") or "[]")
        except Exception:assets=[]
        g["assets"].update(str(x) for x in assets)
        ts=float(r.get("source_ts") or 0)
        if ts>=g["latest_ts"]:
            g["latest_ts"]=ts; g["latest_title"]=str(r.get("title") or "")
    out=[]
    for g in groups.values():
        out.append({
            "story_id":g["story_id"],"count":g["count"],"stages":sorted(g["stages"]),
            "event_types":sorted(g["events"]),"sources":sorted(g["sources"]),
            "assets":sorted(g["assets"]),"latest_ts":g["latest_ts"],"latest_title":g["latest_title"],
        })
    out.sort(key=lambda x:x["latest_ts"],reverse=True)
    return {"status":"ok","stories":out[:max(1,min(100,int(limit)))],"story_count_72h":len(out)}

def _strict_rows():
    if not os.path.exists(ANALYTICS_DB):return []
    with _db(ANALYTICS_DB) as c:
        try:
            rows=c.execute("SELECT * FROM analytics_trades WHERE status='CLOSED' AND mode='STRICT' ORDER BY opened_at ASC").fetchall()
            return [dict(r) for r in rows]
        except Exception:return []

def _rolling_blocks(rows):
    n=len(rows)
    if n<90:return []
    size=n//3
    parts=[rows[:size],rows[size:2*size],rows[2*size:]]
    return [_metrics(x) for x in parts]

def _hardening_quality():
    if not os.path.exists(HARDENING_DB):return {"state":"MISSING","age_sec":None}
    with _db(HARDENING_DB) as c:
        try:r=c.execute("SELECT observed_at,state FROM data_quality_samples ORDER BY observed_at DESC LIMIT 1").fetchone()
        except Exception:r=None
    if not r:return {"state":"MISSING","age_sec":None}
    return {"state":str(r["state"]), "age_sec":max(0.0,time.time()-float(r["observed_at"]))}

def live_readiness_report():
    rows=_strict_rows()
    core=_metrics(rows)
    blocks=_rolling_blocks(rows)
    dq=_hardening_quality()
    nq=news_quality_report()

    checks=[
        {"name":"clean_strict_sample","ok":core["n"]>=MIN_STRICT,"detail":f"{core['n']}/{MIN_STRICT}"},
        {"name":"strict_avg_net_positive","ok":core["avg_net_pct"]>0,"detail":f"{core['avg_net_pct']:.4f}%"},
        {"name":"strict_profit_factor","ok":core["profit_factor"]>=MIN_PF,"detail":f"{core['profit_factor']:.2f}/{MIN_PF:.2f}"},
        {"name":"rolling_stability","ok":len(blocks)==3 and all(x["n"]>=30 and x["avg_net_pct"]>0 for x in blocks),
         "detail":" | ".join(f"n={x['n']} avg={x['avg_net_pct']:.3f}%" for x in blocks) if blocks else "need >=90 STRICT"},
        {"name":"hardening_data_quality","ok":dq.get("state")=="OK" and dq.get("age_sec") is not None and dq["age_sec"]<=MAX_DQ_AGE,
         "detail":f"{dq.get('state')} · age {dq.get('age_sec') if dq.get('age_sec') is not None else '—'}s"},
    ]
    blockers=[x for x in checks if not x["ok"]]
    state="ELIGIBLE_FOR_MANUAL_REVIEW" if not blockers else "BLOCKED"
    return {
        "status":"ok",
        "mode":"READ_ONLY_DIAGNOSTIC",
        "state":state,
        "core_strict":core,
        "rolling_blocks":blocks,
        "hardening":dq,
        "news_quality":nq,
        "checks":checks,
        "blockers":blockers,
        "note":"This gate does not enable LIVE and is not a profitability guarantee. It only checks evidence and data-quality thresholds.",
        "can_enable_live":False,
        "changes_trading_decisions":False,
        "live_execution":False,
    }

def status():
    return {
        "enabled":True,"mode":"READ_ONLY_DIAGNOSTIC",
        "min_clean_strict":MIN_STRICT,"min_profit_factor":MIN_PF,
        "max_hardening_age_sec":MAX_DQ_AGE,
        "can_enable_live":False,"changes_trading_decisions":False,"live_execution":False,
    }

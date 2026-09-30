"""MYSHKA / ASTRA — RESCUE MATRIX V1 (SHADOW / diagnostic only).

Finds cluster-aware intersections across:
JEV × TECH × EDGE band × regime × pair × Binance X-Check × Evidence Gate.

Historical data is discovery-only. A separate forward cutoff is created at
installation time for out-of-sample confirmation. This module never changes
ENTER/DROP, PAPER, sizing, execution, or live routing.
"""
from __future__ import annotations

from contextlib import contextmanager
from itertools import combinations
import json
import math
import os
import sqlite3
import time
from typing import Any, Optional

RISK_DB_PATH=os.getenv("RISK_INTELLIGENCE_DB_PATH","/data/myshka_risk_intelligence.sqlite3")
DB_PATH=os.getenv("RESCUE_MATRIX_DB_PATH","/data/myshka_rescue_matrix.sqlite3")
CLUSTER_SEC=max(60,int(os.getenv("RESCUE_MATRIX_CLUSTER_SEC","300")))
JOIN_TOLERANCE_SEC=max(15,int(os.getenv("RESCUE_MATRIX_JOIN_TOLERANCE_SEC","75")))
HIST_MIN_CLUSTER=max(2,int(os.getenv("RESCUE_MATRIX_HIST_MIN_CLUSTER","5")))
FORWARD_REVIEW_CLUSTER=max(30,int(os.getenv("RESCUE_MATRIX_FORWARD_REVIEW_CLUSTER","150")))
MIN_PF=float(os.getenv("RESCUE_MATRIX_MIN_PF","1.20"))
MAX_ROWS=max(200,int(os.getenv("RESCUE_MATRIX_MAX_ROWS","8000")))

DIMS=("tech","edge_band","regime","pair","xcheck","evidence")
EDGE_BANDS=("<0","0-0.05","0.05-0.10","0.10-0.15","0.15-0.20",">=0.20")


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
    finally: c.close()

def init():
    with _db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS rescue_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        r=c.execute("SELECT value FROM rescue_meta WHERE key='forward_started_at'").fetchone()
        if not r:
            c.execute("INSERT INTO rescue_meta(key,value) VALUES('forward_started_at',?)",(str(time.time()),))
    return {"enabled":True,"mode":"RESCUE_MATRIX_SHADOW","db_path":DB_PATH,"risk_db_path":RISK_DB_PATH}

def _forward_started():
    init()
    with _db() as c:
        r=c.execute("SELECT value FROM rescue_meta WHERE key='forward_started_at'").fetchone()
        return float(r["value"]) if r else time.time()

def _num(v):
    try:
        if v is None or v=="": return None
        x=float(v); return x if math.isfinite(x) else None
    except Exception:return None

def _pf(vals):
    pos=sum(x for x in vals if x>0)
    neg=abs(sum(x for x in vals if x<=0))
    return pos/neg if neg>1e-12 else (999.0 if pos>0 else 0.0)

def _sample_state(cn):
    n=int(cn or 0)
    if n<30:return "COLD"
    if n<50:return "WARMING"
    if n<150:return "MONITOR"
    if n<300:return "CANDIDATE"
    return "MATURE"

def _edge_band(v):
    x=_num(v)
    if x is None:return "NO_EDGE"
    if x<0:return "<0"
    if x<.05:return "0-0.05"
    if x<.10:return "0.05-0.10"
    if x<.15:return "0.10-0.15"
    if x<.20:return "0.15-0.20"
    return ">=0.20"

def _tech_label(v):
    try:n=int(v or 0)
    except Exception:n=0
    return f"{n}/4" if n else "0/4"

def _load_risk():
    if not os.path.exists(RISK_DB_PATH):return []
    try:
        with _db(RISK_DB_PATH) as c:
            rows=c.execute(
                """SELECT * FROM risk_candidates
                   WHERE status='CLOSED' AND net_pct IS NOT NULL
                   ORDER BY opened_at ASC,id ASC LIMIT ?""",(MAX_ROWS,)
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:return []

def _load_blackbox():
    if not os.path.exists(RISK_DB_PATH):return {}
    try:
        with _db(RISK_DB_PATH) as c:
            rows=c.execute(
                """SELECT id,pair,observed_at,direction,stage_json,raw_json
                   FROM decision_blackbox
                   ORDER BY observed_at ASC,id ASC LIMIT ?""",(MAX_ROWS*3,)
            ).fetchall()
        out={}
        for rr in rows:
            r=dict(rr)
            try:r["stage"]=json.loads(r.get("stage_json") or "{}")
            except Exception:r["stage"]={}
            try:r["raw"]=json.loads(r.get("raw_json") or "{}")
            except Exception:r["raw"]={}
            out.setdefault(str(r.get("pair") or ""),[]).append(r)
        return out
    except Exception:return {}

def _nearest_blackbox(row,by_pair):
    arr=by_pair.get(str(row.get("pair") or ""),[])
    if not arr:return None
    t=float(row.get("opened_at") or 0)
    side=str(row.get("side") or "").upper()
    best=None; best_dt=1e99
    for b in arr:
        dt=abs(float(b.get("observed_at") or 0)-t)
        if dt>JOIN_TOLERANCE_SEC:continue
        d=str(b.get("direction") or "").upper()
        if side in {"LONG","SHORT"} and d in {"LONG","SHORT"} and d!=side:continue
        if dt<best_dt:best=b;best_dt=dt
    return best

def _xcheck(raw):
    for key in ("binance_crosscheck","binance_xcheck","xcheck"):
        x=raw.get(key)
        if isinstance(x,dict):
            state=str(x.get("state") or x.get("verdict") or x.get("status") or "NO_DATA").upper()
            if state in {"AGREE","CONFLICT","NEUTRAL","NO_DATA","NOT_APPLICABLE"}:return state
            return state or "NO_DATA"
    return "NO_DATA"

def _evidence(stage,raw):
    e=(stage or {}).get("evidence_gate")
    if not isinstance(e,dict):e=raw.get("evidence_gate") if isinstance(raw.get("evidence_gate"),dict) else {}
    applies=e.get("applies")
    passed=e.get("passed")
    state=str(e.get("state") or "").upper()
    reason=str(e.get("reason") or "").upper()
    if passed is True:return "PASS"
    if state in {"PASS","APPROVE","READY"}:return "PASS"
    if state in {"HOLD","DROP","REJECT","BLOCK"}:return state
    if passed is False and applies is True:return "HOLD"
    if applies is False:return "NOT_APPLICABLE"
    if "HOLD" in reason or "DROP" in reason or "REJECT" in reason:return "HOLD"
    return "NO_DATA"

def _enrich(rows):
    bb=_load_blackbox()
    out=[]; joined=0
    for r0 in rows:
        r=dict(r0)
        b=_nearest_blackbox(r,bb)
        stage=(b or {}).get("stage") or {}
        raw=(b or {}).get("raw") or {}
        if b:joined+=1
        pair=str(r.get("pair") or "")
        r.update({
            "tech":_tech_label(r.get("tech_score")),
            "edge_band":_edge_band(r.get("edge_pct")),
            "regime":str(r.get("regime") or "UNKNOWN").upper(),
            "pair":pair.replace("/USDT:USDT",""),
            "xcheck":_xcheck(raw),
            "evidence":_evidence(stage,raw),
            "jev":str(r.get("jev_verdict") or "WAIT").upper(),
            "cluster_key":f"{pair}|{str(r.get('side') or '').upper()}|{int(float(r.get('opened_at') or 0)//CLUSTER_SEC)*CLUSTER_SEC}",
            "blackbox_joined":bool(b),
        })
        out.append(r)
    return out,joined

def _cluster_rows(rows):
    seen=set(); out=[]
    for r in sorted(rows,key=lambda x:(float(x.get("opened_at") or 0),int(x.get("id") or 0))):
        k=str(r.get("cluster_key") or "")
        if k in seen:continue
        seen.add(k);out.append(r)
    return out

def _metrics(rows):
    raw=[float(r["net_pct"]) for r in rows if _num(r.get("net_pct")) is not None]
    cl_rows=_cluster_rows(rows)
    cl=[float(r["net_pct"]) for r in cl_rows if _num(r.get("net_pct")) is not None]
    def core(vals):
        n=len(vals);wins=sum(1 for x in vals if x>0)
        return {
            "n":n,
            "win_rate_pct":wins/n*100.0 if n else 0.0,
            "avg_net_pct":sum(vals)/n if n else 0.0,
            "profit_factor":_pf(vals),
            "total_net_pct":sum(vals),
        }
    a,b=core(raw),core(cl)
    return {
        **a,
        "cluster_n":b["n"],
        "cluster_win_rate_pct":b["win_rate_pct"],
        "cluster_avg_net_pct":b["avg_net_pct"],
        "cluster_profit_factor":b["profit_factor"],
        "sample_state":_sample_state(b["n"]),
    }

def _group(rows,dims):
    groups={}
    for r in rows:
        key=tuple(str(r.get(d) or "UNKNOWN") for d in dims)
        groups.setdefault(key,[]).append(r)
    out=[]
    for key,q in groups.items():
        m=_metrics(q)
        vals={d:v for d,v in zip(dims,key)}
        out.append({"dimensions":list(dims),"values":vals,**m})
    return out

def _rank_positive(items,min_cn):
    q=[x for x in items if int(x.get("cluster_n") or 0)>=min_cn and float(x.get("cluster_avg_net_pct") or 0)>0 and float(x.get("cluster_profit_factor") or 0)>=MIN_PF]
    q.sort(key=lambda x:(int(x.get("cluster_n") or 0),float(x.get("cluster_avg_net_pct") or 0),float(x.get("cluster_profit_factor") or 0)),reverse=True)
    return q

def _rank_negative(items,min_cn):
    q=[x for x in items if int(x.get("cluster_n") or 0)>=min_cn and float(x.get("cluster_avg_net_pct") or 0)<0]
    q.sort(key=lambda x:(int(x.get("cluster_n") or 0),-float(x.get("cluster_avg_net_pct") or 0)),reverse=True)
    return q

def _intersections(rows,mode):
    # RESCUE discovery is intentionally anchored on JEV APPROVE, because current
    # shadow evidence suggests APPROVE is a materially different cohort.
    approved=[r for r in rows if str(r.get("jev") or "")=="APPROVE"]
    all_items=[]
    for size in (2,3,4,5):
        for dims in combinations(DIMS,size):
            all_items.extend(_group(approved,dims))

    min_cn=HIST_MIN_CLUSTER if mode=="HISTORICAL_DIAGNOSTIC" else 1
    positives=_rank_positive(all_items,min_cn)
    negatives=_rank_negative(all_items,min_cn)

    full=_group(approved,DIMS)
    full.sort(key=lambda x:int(x.get("cluster_n") or 0),reverse=True)

    tech_edge=_group(approved,("tech","edge_band"))
    regime_pair=_group(approved,("regime","pair"))
    x_ev=_group(approved,("xcheck","evidence"))

    # Forward candidates must be large enough before they can even be reviewed.
    for x in positives:
        cn=int(x.get("cluster_n") or 0)
        x["forward_review_eligible"]=bool(
            mode=="FORWARD_ONLY"
            and cn>=FORWARD_REVIEW_CLUSTER
            and float(x.get("cluster_avg_net_pct") or 0)>0
            and float(x.get("cluster_profit_factor") or 0)>=MIN_PF
        )
        x["disposition"]="FORWARD_REVIEW" if x["forward_review_eligible"] else ("DISCOVERY_ONLY" if mode=="HISTORICAL_DIAGNOSTIC" else "COLLECTING")

    return {
        "jev_anchor":"APPROVE",
        "approved_metrics":_metrics(approved),
        "top_positive_intersections":positives[:30],
        "top_negative_intersections":negatives[:20],
        "full_cells":full[:50],
        "tech_x_edge":sorted(tech_edge,key=lambda x:int(x.get("cluster_n") or 0),reverse=True),
        "regime_x_pair":sorted(regime_pair,key=lambda x:int(x.get("cluster_n") or 0),reverse=True)[:50],
        "xcheck_x_evidence":sorted(x_ev,key=lambda x:int(x.get("cluster_n") or 0),reverse=True),
    }

def _section(rows,mode):
    enriched,joined=_enrich(rows)
    return {
        "mode":mode,
        "overall":_metrics(enriched),
        "raw_rows":len(enriched),
        "blackbox_joined":joined,
        "blackbox_join_coverage_pct":joined/len(enriched)*100.0 if enriched else 0.0,
        "matrix":_intersections(enriched,mode),
    }

def report():
    init()
    rows=_load_risk()
    start=_forward_started()
    historical=_section(rows,"HISTORICAL_DIAGNOSTIC")
    forward=_section([r for r in rows if float(r.get("opened_at") or 0)>=start],"FORWARD_ONLY")
    return {
        "status":"ok",
        "mode":"RESCUE_MATRIX_SHADOW",
        "forward_started_at":start,
        "cluster_sec":CLUSTER_SEC,
        "historical":historical,
        "forward":forward,
        "policy":{
            "historical_min_cluster":HIST_MIN_CLUSTER,
            "forward_review_cluster":FORWARD_REVIEW_CLUSTER,
            "min_profit_factor":MIN_PF,
            "join_tolerance_sec":JOIN_TOLERANCE_SEC,
            "historical_is_discovery_only":True,
            "auto_promotion":False,
        },
        "dimensions":["JEV APPROVE","TECH","EDGE BAND","REGIME","PAIR","BINANCE X-CHECK","EVIDENCE GATE"],
        "note":"Historical intersections are discovery-only. Only forward cluster-aware confirmation may become eligible for manual review.",
        "changes_paper_execution":False,
        "changes_trading_decisions":False,
        "live_execution":False,
    }

def status():
    init()
    return {
        "enabled":True,
        "mode":"RESCUE_MATRIX_SHADOW",
        "risk_db_path":RISK_DB_PATH,
        "db_path":DB_PATH,
        "forward_started_at":_forward_started(),
        "cluster_sec":CLUSTER_SEC,
        "changes_paper_execution":False,
        "changes_trading_decisions":False,
        "live_execution":False,
    }

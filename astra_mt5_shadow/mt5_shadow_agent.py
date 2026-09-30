"""MYSHKA / ASTRA - MT5 Shadow Agent V1.

Consumes the token-protected Windows MT5 Shadow Collector.
SHADOW ONLY:
- never changes action/reason;
- never calls any MT5 order API;
- attaches MT5 consensus and records forward 5m/10m/15m outcomes;
- degrades to NO_DATA on collector/network failure.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Optional

BASE_URL = os.getenv("MT5_SHADOW_BASE_URL", "http://host.docker.internal:8115").rstrip("/")
TOKEN = os.getenv("MT5_SHADOW_TOKEN", "")
TIMEOUT_SEC = max(1.0, float(os.getenv("MT5_SHADOW_HTTP_TIMEOUT_SEC", "3")))
CACHE_SEC = max(2, int(os.getenv("MT5_SHADOW_AGENT_CACHE_SEC", "8")))
MAX_AGE_SEC = max(CACHE_SEC, int(os.getenv("MT5_SHADOW_AGENT_MAX_AGE_SEC", "60")))
DB_PATH = os.getenv("MT5_SHADOW_DB_PATH", "/data/myshka_mt5_shadow.sqlite3")
HORIZONS = tuple(sorted({
    int(x.strip()) for x in os.getenv("MT5_SHADOW_HORIZONS_SEC", "300,600,900").split(",") if x.strip()
}))
CLUSTER_SEC = max(60, int(os.getenv("MT5_SHADOW_CLUSTER_SEC", "300")))
MAX_SETTLE_DELAY_SEC = max(30, int(os.getenv("MT5_SHADOW_MAX_SETTLE_DELAY_SEC", "120")))

_LOCK = threading.RLock()
_CACHE: dict[str, dict] = {}


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def init() -> dict:
    with _LOCK, _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS mt5_shadow_outcomes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                side TEXT NOT NULL,
                source_minute INTEGER NOT NULL,
                cluster_bucket INTEGER NOT NULL,
                cluster_key TEXT NOT NULL,
                opened_at REAL NOT NULL,
                target_at REAL NOT NULL,
                horizon_sec INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                entry_price REAL NOT NULL,
                exit_price REAL,
                action TEXT,
                reason TEXT,
                tech_score INTEGER,
                edge_pct REAL,
                total_cost_pct REAL,
                jev_verdict TEXT,
                evidence_state TEXT,
                adaptive_state TEXT,
                mt5_state TEXT,
                mt5_alignment TEXT,
                mt5_score REAL,
                mt5_symbol TEXT,
                external_state TEXT,
                stack_state TEXT,
                settled_at REAL,
                settle_delay_sec REAL,
                gross_pct REAL,
                net_pct REAL,
                direction_hit INTEGER,
                UNIQUE(pair,side,source_minute,horizon_sec)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_mt5_status_target ON mt5_shadow_outcomes(status,target_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_mt5_align ON mt5_shadow_outcomes(mt5_alignment,horizon_sec,status)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_mt5_stack ON mt5_shadow_outcomes(stack_state,horizon_sec,status)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_mt5_pair ON mt5_shadow_outcomes(pair,horizon_sec,status)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_mt5_cluster ON mt5_shadow_outcomes(cluster_key,horizon_sec,status)")
    return status()


def _ticker(pair: str) -> str:
    return str(pair or "").upper().split(":")[0].split("/")[0].replace("-","").replace("_","")


def _side(r: dict) -> str:
    sig = r.get("signal") or {}
    return str(r.get("direction") or sig.get("direction") or "WAIT").upper()


def _market_price(r: dict) -> Optional[float]:
    m = r.get("market") or {}
    for k in ("last_price","last","price","close"):
        x = _num(m.get(k))
        if x is not None and x > 0:
            return x
    candles = m.get("candles") or r.get("candles") or []
    if candles:
        c = candles[-1]
        if isinstance(c, dict):
            x = _num(c.get("close"))
            if x is not None and x > 0:
                return x
    return None


def _http_snapshot(ticker: str) -> dict:
    if not TOKEN:
        return {"status":"NO_DATA","reason":"token_missing","read_only":True}
    qs = urllib.parse.urlencode({"ticker":ticker})
    req = urllib.request.Request(
        BASE_URL + "/snapshot?" + qs,
        headers={"X-MT5-SHADOW-TOKEN":TOKEN,"Accept":"application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8","replace")
            data = json.loads(raw)
            return data if isinstance(data,dict) else {"status":"NO_DATA","reason":"invalid_json_shape"}
    except Exception as exc:
        return {"status":"NO_DATA","reason":f"{type(exc).__name__}:{exc}","read_only":True}


def _snapshot(ticker: str) -> dict:
    now = time.time()
    with _LOCK:
        cur = _CACHE.get(ticker)
        if cur and now-float(cur.get("_cached_at") or 0) < CACHE_SEC:
            return dict(cur)
    out = _http_snapshot(ticker)
    out["_cached_at"] = now
    with _LOCK:
        _CACHE[ticker] = dict(out)
    return out


def _alignment(side: str, state: str) -> str:
    side = str(side or "").upper()
    state = str(state or "").upper()
    if side not in {"LONG","SHORT"}:
        return "NOT_APPLICABLE"
    if state in {"","NO_DATA"}:
        return "NO_DATA"
    if state == "NEUTRAL":
        return "NEUTRAL"
    return "AGREE" if state == side else "CONFLICT"


def _stack_state(mt5_align: str, external_state: str) -> str:
    e = str(external_state or "NO_DATA").upper()
    m = str(mt5_align or "NO_DATA").upper()
    if m == "AGREE" and e == "BOTH_AGREE":
        return "MT5_AGREE+EXT_BOTH_AGREE"
    if m == "CONFLICT" and e == "BOTH_CONFLICT":
        return "MT5_CONFLICT+EXT_BOTH_CONFLICT"
    if m == "AGREE":
        return "MT5_AGREE"
    if m == "CONFLICT":
        return "MT5_CONFLICT"
    if m == "NEUTRAL":
        return "MT5_NEUTRAL"
    return "MT5_NO_DATA"


def _attach(r: dict) -> dict:
    side = _side(r)
    ticker = _ticker(r.get("pair") or "")
    if side not in {"LONG","SHORT"}:
        view = {
            "state":"NOT_APPLICABLE","alignment":"NOT_APPLICABLE",
            "stack_state":"NOT_APPLICABLE","shadow_only":True,"read_only":True,
        }
        r["mt5_shadow"] = view
        return view

    snap = _snapshot(ticker)
    state = str(snap.get("direction") or snap.get("status") or "NO_DATA").upper()
    if str(snap.get("status") or "").upper() != "READY":
        state = "NO_DATA"

    align = _alignment(side,state)
    ext = r.get("external_market_shadow") or {}
    ext_state = str(ext.get("combined_state") or "NO_DATA")
    view = {
        "state":state,
        "alignment":align,
        "score":_num(snap.get("score")),
        "symbol":snap.get("symbol"),
        "frames":snap.get("frames") or {},
        "tick":snap.get("tick") or {},
        "terminal":snap.get("terminal") or {},
        "reason":snap.get("reason","ok" if state!="NO_DATA" else "no_data"),
        "external_state":ext_state,
        "stack_state":_stack_state(align,ext_state),
        "shadow_only":True,
        "read_only":True,
        "changes_trade_decision":False,
    }
    r["mt5_shadow"] = view
    return view


def _settle(results: list[dict], now: float) -> dict:
    by_pair = {str(r.get("pair") or ""):r for r in (results or []) if r.get("pair")}
    closed = skipped = 0
    with _LOCK, _conn() as con:
        rows = con.execute(
            "SELECT * FROM mt5_shadow_outcomes WHERE status='OPEN' AND target_at<=? ORDER BY target_at",
            (now,),
        ).fetchall()
        for row in rows:
            delay = max(0.0, now-float(row["target_at"]))
            if delay > MAX_SETTLE_DELAY_SEC:
                con.execute(
                    "UPDATE mt5_shadow_outcomes SET status='SKIPPED',settled_at=?,settle_delay_sec=? WHERE id=?",
                    (now,delay,int(row["id"])),
                )
                skipped += 1
                continue
            r = by_pair.get(str(row["pair"]))
            if not r:
                continue
            exit_price = _market_price(r)
            if exit_price is None:
                continue
            entry = float(row["entry_price"])
            raw = (exit_price/entry-1.0)*100.0
            gross = raw if str(row["side"])=="LONG" else -raw
            cost = float(row["total_cost_pct"] or 0.0)
            net = gross-cost
            con.execute(
                """
                UPDATE mt5_shadow_outcomes
                SET status='CLOSED',exit_price=?,settled_at=?,settle_delay_sec=?,
                    gross_pct=?,net_pct=?,direction_hit=?
                WHERE id=? AND status='OPEN'
                """,
                (exit_price,now,delay,gross,net,1 if gross>0 else 0,int(row["id"])),
            )
            closed += 1
        con.commit()
    return {"closed":closed,"skipped":skipped}


def _record(r: dict, mt5v: dict, now: float) -> int:
    side = _side(r)
    if side not in {"LONG","SHORT"}:
        return 0
    pair = str(r.get("pair") or "")
    price = _market_price(r)
    if not pair or price is None:
        return 0

    sig = r.get("signal") or {}
    edge = r.get("edge") or {}
    jev = r.get("jev") or {}
    evidence = r.get("evidence_gate") or {}
    adaptive = r.get("adaptive_learner") or {}
    source_minute = int(now//60)*60
    cluster_bucket = int(now//CLUSTER_SEC)*CLUSTER_SEC
    cluster_key = f"{pair}|{side}|{cluster_bucket}"

    common = (
        str(r.get("action") or ""),
        str(r.get("reason") or ""),
        int(sig.get("tech_score") or 0),
        _num(edge.get("net_edge_pct")),
        _num(edge.get("total_cost_pct")),
        str(jev.get("verdict") or ""),
        str(evidence.get("state") or ""),
        str(adaptive.get("state") or ""),
        str(mt5v.get("state") or "NO_DATA"),
        str(mt5v.get("alignment") or "NO_DATA"),
        _num(mt5v.get("score")),
        str(mt5v.get("symbol") or ""),
        str(mt5v.get("external_state") or "NO_DATA"),
        str(mt5v.get("stack_state") or "MT5_NO_DATA"),
    )

    made = 0
    with _LOCK, _conn() as con:
        for h in HORIZONS:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO mt5_shadow_outcomes(
                    pair,side,source_minute,cluster_bucket,cluster_key,opened_at,target_at,horizon_sec,status,
                    entry_price,action,reason,tech_score,edge_pct,total_cost_pct,jev_verdict,evidence_state,
                    adaptive_state,mt5_state,mt5_alignment,mt5_score,mt5_symbol,external_state,stack_state
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (pair,side,source_minute,cluster_bucket,cluster_key,now,now+int(h),int(h),"OPEN",price,*common),
            )
            made += int(bool(cur.rowcount))
        con.commit()
    return made


def observe_results(results: list[dict], now: Optional[float] = None) -> dict:
    try:
        init()
        ts = float(now if now is not None else time.time())
        settled = _settle(results or [],ts)
        attached = created = 0
        for r in results or []:
            action_before = r.get("action")
            reason_before = r.get("reason")
            view = _attach(r)
            attached += 1
            created += _record(r,view,ts)
            if r.get("action") != action_before or r.get("reason") != reason_before:
                r["action"] = action_before
                r["reason"] = reason_before
                raise RuntimeError("MT5 shadow attempted to change trade decision")
        return {"status":"ok","attached":attached,"created":created,**settled}
    except Exception as exc:
        return {"status":"error","error":f"{type(exc).__name__}: {exc}","attached":0,"created":0,"closed":0,"skipped":0}


def _pf(vals: list[float]) -> float:
    pos = sum(x for x in vals if x>0)
    neg = abs(sum(x for x in vals if x<=0))
    return pos/neg if neg>1e-12 else (999.0 if pos>0 else 0.0)


def _cluster_rows(rows: list[dict]) -> list[dict]:
    seen=set()
    out=[]
    for r in sorted(rows,key=lambda x:(float(x.get("opened_at") or 0),int(x.get("id") or 0))):
        key=str(r.get("cluster_key") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _metrics(rows: list[dict]) -> dict:
    vals=[float(r["net_pct"]) for r in rows if r.get("net_pct") is not None]
    cl=_cluster_rows(rows)
    cvals=[float(r["net_pct"]) for r in cl if r.get("net_pct") is not None]
    return {
        "n":len(vals),
        "win_rate_pct":sum(1 for x in vals if x>0)/len(vals)*100.0 if vals else 0.0,
        "avg_net_pct":sum(vals)/len(vals) if vals else 0.0,
        "profit_factor":_pf(vals),
        "cluster_n":len(cvals),
        "cluster_win_rate_pct":sum(1 for x in cvals if x>0)/len(cvals)*100.0 if cvals else 0.0,
        "cluster_avg_net_pct":sum(cvals)/len(cvals) if cvals else 0.0,
        "cluster_profit_factor":_pf(cvals),
    }


def report() -> dict:
    init()
    with _LOCK, _conn() as con:
        rows=[dict(r) for r in con.execute(
            "SELECT * FROM mt5_shadow_outcomes WHERE status='CLOSED' ORDER BY opened_at,id"
        ).fetchall()]
        counts={str(r["status"]):int(r["n"]) for r in con.execute(
            "SELECT status,COUNT(*) n FROM mt5_shadow_outcomes GROUP BY status"
        ).fetchall()}

    out={}
    for h in HORIZONS:
        part=[r for r in rows if int(r.get("horizon_sec") or 0)==int(h)]
        anchor=[r for r in part if str(r.get("jev_verdict") or "").upper()=="APPROVE" and int(r.get("tech_score") or 0)>=3]
        by_pair={}
        for pair in sorted({str(r.get("pair") or "") for r in anchor if r.get("pair")}):
            by_pair[pair]=_metrics([r for r in anchor if str(r.get("pair"))==pair])
        out[str(h)]={
            "all":_metrics(part),
            "anchor_jev_approve_tech3plus":_metrics(anchor),
            "by_mt5_alignment":{s:_metrics([r for r in anchor if str(r.get("mt5_alignment") or "")==s]) for s in ("AGREE","CONFLICT","NEUTRAL","NO_DATA")},
            "by_stack_state":{s:_metrics([r for r in anchor if str(r.get("stack_state") or "")==s]) for s in sorted({str(r.get("stack_state") or "") for r in anchor})},
            "by_pair":by_pair,
        }
    return {
        "status":"ok",
        "mode":"SHADOW_ONLY",
        "open":counts.get("OPEN",0),
        "closed":counts.get("CLOSED",0),
        "skipped":counts.get("SKIPPED",0),
        "horizons_sec":list(HORIZONS),
        "by_horizon":out,
        "auto_gate_enable":False,
        "changes_trading_decisions":False,
        "live_execution":False,
    }


def status() -> dict:
    return {
        "status":"ok",
        "mode":"SHADOW_ONLY",
        "base_url":BASE_URL,
        "token_present":bool(TOKEN),
        "cache_symbols":len(_CACHE),
        "horizons_sec":list(HORIZONS),
        "db_path":DB_PATH,
        "read_only":True,
        "changes_trading_decisions":False,
        "live_execution":False,
    }

"""MYSHKA / ASTRA — Bybit Top Traders Shadow V1.

Purpose:
- receive public master-trader snapshots from a local Selenium collector;
- build an equal-weight LONG/SHORT consensus per pair;
- attach the consensus to ASTRA scan rows as SHADOW metadata only;
- never changes action/reason, never sends orders, never clicks Copy.

The Selenium collector runs on the Windows host. This module runs inside ASTRA
and only accepts authenticated snapshots through the local bridge API.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
from typing import Any, Optional

DB_PATH = os.getenv("BYBIT_TOPTRADERS_DB_PATH", "/data/myshka_bybit_toptraders.sqlite3")
ENABLED = os.getenv("BYBIT_TOPTRADERS_ENABLED", "true").lower() in {"1","true","yes","on"}
MAX_AGE_SEC = max(30, int(os.getenv("BYBIT_TOPTRADERS_MAX_AGE_SEC", "180")))
MIN_TRADERS = max(1, int(os.getenv("BYBIT_TOPTRADERS_MIN_TRADERS", "2")))
CONSENSUS_RATIO = min(1.0, max(0.50, float(os.getenv("BYBIT_TOPTRADERS_CONSENSUS_RATIO", "0.60"))))
_LOCK = threading.RLock()


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _norm_pair(v: Any) -> str:
    s = str(v or "").upper().strip().replace("-", "/").replace("_", "/")
    if not s:
        return ""
    if ":" in s:
        s = s.split(":", 1)[0]
    s = s.replace("PERP", "")
    if "/" not in s:
        for q in ("USDT","USDC","USD"):
            if s.endswith(q) and len(s) > len(q):
                s = s[:-len(q)] + "/" + q
                break
    return s


def _norm_side(v: Any) -> str:
    s = str(v or "").strip().upper()
    if s in {"LONG","BUY","BUY LONG","OPEN LONG","ЛОНГ"}:
        return "LONG"
    if s in {"SHORT","SELL","SELL SHORT","OPEN SHORT","ШОРТ"}:
        return "SHORT"
    return "WAIT"


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
            CREATE TABLE IF NOT EXISTS trader_snapshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at REAL NOT NULL,
                observed_at REAL NOT NULL,
                trader_id TEXT NOT NULL,
                trader_name TEXT,
                source_url TEXT,
                status TEXT NOT NULL,
                raw_json TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS trader_positions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL,
                observed_at REAL NOT NULL,
                trader_id TEXT NOT NULL,
                trader_name TEXT,
                pair TEXT NOT NULL,
                side TEXT NOT NULL,
                leverage REAL,
                pnl_pct REAL,
                source_url TEXT,
                FOREIGN KEY(snapshot_id) REFERENCES trader_snapshots(id)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_btt_snap_trader ON trader_snapshots(trader_id,observed_at DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_btt_pos_pair ON trader_positions(pair,observed_at DESC)")
        con.commit()
    return status()


def push(payload: dict) -> dict:
    init()
    now = time.time()
    trader_id = str(payload.get("trader_id") or payload.get("source_url") or "").strip()
    if not trader_id:
        return {"status":"error","reason":"trader_id_required"}

    observed_at = _num(payload.get("observed_at")) or now
    trader_name = str(payload.get("trader_name") or payload.get("name") or trader_id)[:200]
    source_url = str(payload.get("source_url") or "")[:2000]
    scrape_status = str(payload.get("status") or "ok")[:80]
    positions = payload.get("positions") or []
    clean = []
    if isinstance(positions, list):
        for p in positions:
            if not isinstance(p, dict):
                continue
            pair = _norm_pair(p.get("pair") or p.get("symbol"))
            side = _norm_side(p.get("side") or p.get("direction"))
            if pair and side in {"LONG","SHORT"}:
                clean.append({
                    "pair":pair,
                    "side":side,
                    "leverage":_num(p.get("leverage")),
                    "pnl_pct":_num(p.get("pnl_pct")),
                })

    with _LOCK, _conn() as con:
        cur = con.execute(
            """
            INSERT INTO trader_snapshots(received_at,observed_at,trader_id,trader_name,source_url,status,raw_json)
            VALUES(?,?,?,?,?,?,?)
            """,
            (now,observed_at,trader_id,trader_name,source_url,scrape_status,
             json.dumps(payload,ensure_ascii=False,default=str)[:200000]),
        )
        sid = int(cur.lastrowid)
        for p in clean:
            con.execute(
                """
                INSERT INTO trader_positions(snapshot_id,observed_at,trader_id,trader_name,pair,side,leverage,pnl_pct,source_url)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (sid,observed_at,trader_id,trader_name,p["pair"],p["side"],p["leverage"],p["pnl_pct"],source_url),
            )
        # keep database bounded
        cutoff = now - 7 * 86400
        con.execute("DELETE FROM trader_positions WHERE observed_at < ?", (cutoff,))
        con.execute("DELETE FROM trader_snapshots WHERE observed_at < ?", (cutoff,))
        con.commit()

    return {
        "status":"ok",
        "trader_id":trader_id,
        "observed_at":observed_at,
        "positions_received":len(clean),
        "shadow_only":True,
        "sends_orders":False,
    }


def _latest_snapshots() -> list[dict]:
    init()
    now = time.time()
    cutoff = now - MAX_AGE_SEC
    with _LOCK, _conn() as con:
        rows = [
            dict(r) for r in con.execute(
                """
                SELECT s.*
                FROM trader_snapshots s
                JOIN (
                    SELECT trader_id, MAX(observed_at) AS mx
                    FROM trader_snapshots
                    WHERE observed_at >= ?
                    GROUP BY trader_id
                ) z ON z.trader_id=s.trader_id AND z.mx=s.observed_at
                ORDER BY s.trader_id
                """,
                (cutoff,),
            ).fetchall()
        ]
    return rows


def consensus(pair: str) -> dict:
    init()
    target = _norm_pair(pair)
    now = time.time()
    cutoff = now - MAX_AGE_SEC
    with _LOCK, _conn() as con:
        snaps = [
            dict(r) for r in con.execute(
                """
                SELECT s.id,s.trader_id,s.trader_name,s.observed_at,s.source_url
                FROM trader_snapshots s
                JOIN (
                    SELECT trader_id, MAX(observed_at) AS mx
                    FROM trader_snapshots
                    WHERE observed_at >= ?
                    GROUP BY trader_id
                ) z ON z.trader_id=s.trader_id AND z.mx=s.observed_at
                """,
                (cutoff,),
            ).fetchall()
        ]
        votes = []
        for s in snaps:
            rows = con.execute(
                """
                SELECT pair,side,leverage,pnl_pct
                FROM trader_positions
                WHERE snapshot_id=? AND pair=?
                ORDER BY id
                """,
                (int(s["id"]),target),
            ).fetchall()
            # one vote per trader/pair; conflicting same-trader rows cancel to neutral
            sides = {str(r["side"]).upper() for r in rows if str(r["side"]).upper() in {"LONG","SHORT"}}
            if len(sides) == 1:
                side = next(iter(sides))
                votes.append({
                    "trader_id":s["trader_id"],
                    "trader_name":s["trader_name"],
                    "side":side,
                    "age_sec":max(0.0,now-float(s["observed_at"])),
                    "source_url":s["source_url"],
                })

    longs = sum(v["side"] == "LONG" for v in votes)
    shorts = sum(v["side"] == "SHORT" for v in votes)
    n = len(votes)
    if n < MIN_TRADERS:
        state = "INSUFFICIENT"
        direction = "NEUTRAL"
        ratio = max(longs,shorts) / n if n else 0.0
    else:
        majority = max(longs,shorts)
        ratio = majority / n if n else 0.0
        if ratio < CONSENSUS_RATIO or longs == shorts:
            state = "NEUTRAL"
            direction = "NEUTRAL"
        else:
            direction = "LONG" if longs > shorts else "SHORT"
            state = "CONSENSUS"

    return {
        "status":"ok",
        "pair":target,
        "state":state,
        "direction":direction,
        "traders":n,
        "long_votes":longs,
        "short_votes":shorts,
        "consensus_ratio":ratio,
        "required_ratio":CONSENSUS_RATIO,
        "min_traders":MIN_TRADERS,
        "max_age_sec":MAX_AGE_SEC,
        "votes":votes,
        "shadow_only":True,
        "changes_trade_decision":False,
        "sends_orders":False,
    }


def _row_side(r: dict) -> str:
    sig = r.get("signal") or {}
    return _norm_side(r.get("direction") or sig.get("direction"))


def observe_results(results: list[dict]) -> dict:
    attached = 0
    for r in results or []:
        before_action = r.get("action")
        before_reason = r.get("reason")
        pair = str(r.get("pair") or "")
        side = _row_side(r)
        c = consensus(pair) if pair else {
            "status":"ok","state":"NO_DATA","direction":"NEUTRAL","traders":0,
            "shadow_only":True,"changes_trade_decision":False,
        }
        direction = str(c.get("direction") or "NEUTRAL").upper()
        if side not in {"LONG","SHORT"}:
            align = "NOT_APPLICABLE"
        elif direction == "NEUTRAL":
            align = c.get("state") if c.get("state") in {"INSUFFICIENT","NO_DATA"} else "NEUTRAL"
        else:
            align = "AGREE" if direction == side else "CONFLICT"
        view = dict(c)
        view["myshka_direction"] = side
        view["alignment"] = align
        r["bybit_top_traders_shadow"] = view
        attached += 1
        if r.get("action") != before_action or r.get("reason") != before_reason:
            r["action"] = before_action
            r["reason"] = before_reason
            raise RuntimeError("Bybit top traders shadow attempted to change trade decision")
    return {"status":"ok","attached":attached,"shadow_only":True}


def status() -> dict:
    try:
        init_db_only = False
        # avoid recursion through init()->status()
        now = time.time()
        if not os.path.exists(DB_PATH):
            return {
                "enabled":ENABLED,"state":"COLD","fresh_traders":0,
                "max_age_sec":MAX_AGE_SEC,"min_traders":MIN_TRADERS,
                "consensus_ratio":CONSENSUS_RATIO,"shadow_only":True,
                "changes_trade_decision":False,"sends_orders":False,
            }
        with _LOCK, _conn() as con:
            cutoff = now - MAX_AGE_SEC
            fresh = con.execute(
                "SELECT COUNT(DISTINCT trader_id) n FROM trader_snapshots WHERE observed_at>=?",
                (cutoff,),
            ).fetchone()["n"]
            last = con.execute("SELECT MAX(observed_at) mx FROM trader_snapshots").fetchone()["mx"]
        return {
            "enabled":ENABLED,
            "state":"READY" if int(fresh or 0) >= MIN_TRADERS else "WARMING",
            "fresh_traders":int(fresh or 0),
            "last_observed_at":last,
            "last_age_sec":(max(0.0,now-float(last)) if last else None),
            "max_age_sec":MAX_AGE_SEC,
            "min_traders":MIN_TRADERS,
            "consensus_ratio":CONSENSUS_RATIO,
            "shadow_only":True,
            "changes_trade_decision":False,
            "sends_orders":False,
        }
    except Exception as exc:
        return {"enabled":ENABLED,"state":"ERROR","error":f"{type(exc).__name__}: {exc}","shadow_only":True}


def report() -> dict:
    init()
    st = status()
    pairs = set()
    for s in _latest_snapshots():
        try:
            raw = json.loads(s.get("raw_json") or "{}")
        except Exception:
            raw = {}
        for p in raw.get("positions") or []:
            if isinstance(p, dict):
                q = _norm_pair(p.get("pair") or p.get("symbol"))
                if q:
                    pairs.add(q)
    return {
        "status":"ok",
        "mode":"BYBIT_TOP_TRADERS_SHADOW_V1",
        "state":st,
        "pairs":{p:consensus(p) for p in sorted(pairs)},
        "notes":[
            "equal-weight trader votes",
            "fresh latest snapshot per trader only",
            "no ROI weighting",
            "no copy button automation",
            "never changes ASTRA action/reason",
            "never sends orders",
        ],
    }

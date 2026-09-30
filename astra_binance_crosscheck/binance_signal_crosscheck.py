"""MYSHKA / ASTRA — Binance Signal Crosscheck V1 (SHADOW only).

Purpose:
- Compare MYSHKA LONG/SHORT candidates with public Binance USDⓈ-M futures crowding.
- Use official public long/short ratio endpoints (no Binance API key).
- Never creates/rescues/rejects a trade. No order routing.
- Records 5m/10m/15m hypothetical outcomes using the normal ASTRA scan prices.

Design:
- Scanner path is non-blocking: candidates only read the latest cached Binance snapshot.
- A background worker refreshes requested symbols with a conservative cache interval.
- Consensus is diagnostic: AGREE / CONFLICT / NEUTRAL / NO_DATA.
"""
from __future__ import annotations

import json
import math
import os
import queue
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Optional

DB_PATH = os.getenv("BINANCE_CROSSCHECK_DB_PATH", "/data/myshka_binance_crosscheck.sqlite3")
ENABLED = os.getenv("BINANCE_CROSSCHECK_ENABLED", "true").lower() in {"1","true","yes","on"}
BASE_URL = os.getenv("BINANCE_FAPI_BASE_URL", "https://fapi.binance.com").rstrip("/")
PERIOD = os.getenv("BINANCE_CROSSCHECK_PERIOD", "5m")
CACHE_SEC = max(30, int(os.getenv("BINANCE_CROSSCHECK_CACHE_SEC", "60")))
MAX_AGE_SEC = max(CACHE_SEC, int(os.getenv("BINANCE_CROSSCHECK_MAX_AGE_SEC", "180")))
HTTP_TIMEOUT_SEC = max(1.0, float(os.getenv("BINANCE_CROSSCHECK_HTTP_TIMEOUT_SEC", "4")))
NEUTRAL_BAND = min(0.20, max(0.01, float(os.getenv("BINANCE_CROSSCHECK_NEUTRAL_BAND", "0.03"))))
HORIZONS = tuple(
    sorted({int(x.strip()) for x in os.getenv("BINANCE_CROSSCHECK_HORIZONS_SEC", "300,600,900").split(",") if x.strip()})
)
MAX_SETTLE_DELAY_SEC = max(30, int(os.getenv("BINANCE_CROSSCHECK_MAX_SETTLE_DELAY_SEC", "120")))

_LOCK = threading.RLock()
_CACHE: dict[str, dict] = {}
_Q: "queue.Queue[str]" = queue.Queue(maxsize=200)
_QUEUED: set[str] = set()
_WORKER_STARTED = False


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
    global _WORKER_STARTED
    with _LOCK:
        con = _conn()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS binance_crosscheck_outcomes(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pair TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    source_minute INTEGER NOT NULL,
                    opened_at REAL NOT NULL,
                    target_at REAL NOT NULL,
                    horizon_sec INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    consensus TEXT NOT NULL,
                    consensus_score REAL,
                    global_long REAL,
                    global_short REAL,
                    top_long REAL,
                    top_short REAL,
                    top_position_long REAL,
                    top_position_short REAL,
                    snapshot_age_sec REAL,
                    settled_at REAL,
                    settle_delay_sec REAL,
                    gross_pct REAL,
                    direction_hit INTEGER,
                    UNIQUE(pair,side,source_minute,horizon_sec)
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_bx_status_target ON binance_crosscheck_outcomes(status,target_at)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_bx_consensus ON binance_crosscheck_outcomes(consensus,status)")
            con.commit()
        finally:
            con.close()

        if ENABLED and not _WORKER_STARTED:
            t = threading.Thread(target=_worker_loop, name="binance-crosscheck", daemon=True)
            t.start()
            _WORKER_STARTED = True
    return status()


def _symbol(pair: str) -> str:
    p = str(pair or "").upper().split(":")[0]
    return p.replace("/", "").replace("-", "").replace("_", "")


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
        else:
            x = _num(getattr(c, "close", None))
        if x is not None and x > 0:
            return x
    return None


def _side(r: dict) -> str:
    sig = r.get("signal") or {}
    return str(r.get("direction") or sig.get("direction") or "WAIT").upper()


def _request(path: str, symbol: str) -> Optional[dict]:
    qs = urllib.parse.urlencode({"symbol": symbol, "period": PERIOD, "limit": 1})
    url = BASE_URL + path + "?" + qs
    req = urllib.request.Request(url, headers={"User-Agent": "MYSHKA-ASTRA/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if isinstance(data, list) and data:
            return data[-1] if isinstance(data[-1], dict) else None
    except Exception:
        return None
    return None


def _shares(row: Optional[dict], long_keys: tuple[str,...], short_keys: tuple[str,...]) -> tuple[Optional[float],Optional[float]]:
    if not row:
        return None, None
    lo = next((_num(row.get(k)) for k in long_keys if _num(row.get(k)) is not None), None)
    sh = next((_num(row.get(k)) for k in short_keys if _num(row.get(k)) is not None), None)
    return lo, sh


def _fetch_symbol(symbol: str) -> dict:
    now = time.time()
    global_row = _request("/futures/data/globalLongShortAccountRatio", symbol)
    top_row = _request("/futures/data/topLongShortAccountRatio", symbol)
    pos_row = _request("/futures/data/topLongShortPositionRatio", symbol)

    gl, gs = _shares(global_row, ("longAccount",), ("shortAccount",))
    tl, ts = _shares(top_row, ("longAccount",), ("shortAccount",))
    pl, ps = _shares(pos_row, ("longPosition",), ("shortPosition",))

    components = []
    for lo, sh in ((gl,gs),(tl,ts),(pl,ps)):
        if lo is not None and sh is not None:
            components.append(lo - sh)
    score = sum(components) / len(components) if components else None

    if score is None:
        crowd = "NO_DATA"
    elif score > NEUTRAL_BAND:
        crowd = "LONG"
    elif score < -NEUTRAL_BAND:
        crowd = "SHORT"
    else:
        crowd = "NEUTRAL"

    return {
        "symbol": symbol,
        "fetched_at": now,
        "period": PERIOD,
        "crowd_direction": crowd,
        "crowd_score": score,
        "global_long": gl, "global_short": gs,
        "top_long": tl, "top_short": ts,
        "top_position_long": pl, "top_position_short": ps,
        "sources_ok": sum(1 for x in (global_row,top_row,pos_row) if x),
    }


def _worker_loop() -> None:
    while True:
        try:
            symbol = _Q.get(timeout=2.0)
        except queue.Empty:
            continue
        try:
            snap = _fetch_symbol(symbol)
            with _LOCK:
                _CACHE[symbol] = snap
        finally:
            with _LOCK:
                _QUEUED.discard(symbol)
            _Q.task_done()


def _queue_refresh(symbol: str) -> None:
    if not ENABLED or not symbol:
        return
    now = time.time()
    with _LOCK:
        cur = _CACHE.get(symbol)
        fresh = cur and now - float(cur.get("fetched_at") or 0.0) < CACHE_SEC
        if fresh or symbol in _QUEUED:
            return
        _QUEUED.add(symbol)
    try:
        _Q.put_nowait(symbol)
    except queue.Full:
        with _LOCK:
            _QUEUED.discard(symbol)


def _snapshot(symbol: str) -> Optional[dict]:
    with _LOCK:
        snap = dict(_CACHE.get(symbol) or {})
    if not snap:
        return None
    age = max(0.0, time.time() - float(snap.get("fetched_at") or 0.0))
    snap["age_sec"] = age
    if age > MAX_AGE_SEC:
        return None
    return snap


def _consensus(my_side: str, snap: Optional[dict]) -> dict:
    if not snap:
        return {"state":"NO_DATA","reason":"binance_snapshot_missing"}
    crowd = str(snap.get("crowd_direction") or "NO_DATA").upper()
    if crowd == "NO_DATA":
        state = "NO_DATA"
    elif crowd == "NEUTRAL":
        state = "NEUTRAL"
    elif crowd == my_side:
        state = "AGREE"
    else:
        state = "CONFLICT"
    return {
        "state": state,
        "myshka_direction": my_side,
        "binance_direction": crowd,
        "score": snap.get("crowd_score"),
        "snapshot_age_sec": snap.get("age_sec"),
        "global_long": snap.get("global_long"),
        "global_short": snap.get("global_short"),
        "top_long": snap.get("top_long"),
        "top_short": snap.get("top_short"),
        "top_position_long": snap.get("top_position_long"),
        "top_position_short": snap.get("top_position_short"),
        "period": snap.get("period"),
        "shadow_only": True,
    }


def _settle(results: list[dict], now: float) -> dict:
    by_pair = {str(r.get("pair") or ""): r for r in results or [] if r.get("pair")}
    closed = skipped = 0
    with _LOCK:
        con = _conn()
        try:
            rows = con.execute(
                "SELECT * FROM binance_crosscheck_outcomes WHERE status='OPEN' AND target_at<=? ORDER BY target_at",
                (now,),
            ).fetchall()
            for row in rows:
                delay = max(0.0, now - float(row["target_at"]))
                if delay > MAX_SETTLE_DELAY_SEC:
                    con.execute(
                        "UPDATE binance_crosscheck_outcomes SET status='SKIPPED',settled_at=?,settle_delay_sec=? WHERE id=?",
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
                raw = (exit_price-entry)/entry*100.0
                gross = raw if str(row["side"]) == "LONG" else -raw
                con.execute(
                    """
                    UPDATE binance_crosscheck_outcomes
                    SET status='CLOSED',exit_price=?,settled_at=?,settle_delay_sec=?,gross_pct=?,direction_hit=?
                    WHERE id=?
                    """,
                    (exit_price,now,delay,gross,1 if gross>0 else 0,int(row["id"])),
                )
                closed += 1
            con.commit()
        finally:
            con.close()
    return {"closed":closed,"skipped":skipped}


def observe_results(results: list[dict], now: Optional[float] = None) -> dict:
    """Attach Binance consensus and record SHADOW outcomes. Never changes action/reason."""
    try:
        init()
        ts = float(now or time.time())
        settled = _settle(results or [], ts)
        created = attached = 0
        with _LOCK:
            con = _conn()
            try:
                for r in results or []:
                    side = _side(r)
                    if side not in {"LONG","SHORT"}:
                        r["binance_crosscheck"] = {"state":"NOT_APPLICABLE","shadow_only":True}
                        continue
                    pair = str(r.get("pair") or "")
                    symbol = _symbol(pair)
                    _queue_refresh(symbol)
                    snap = _snapshot(symbol)
                    cc = _consensus(side, snap)
                    r["binance_crosscheck"] = cc
                    attached += 1
                    price = _market_price(r)
                    if price is None or cc["state"] == "NO_DATA":
                        continue
                    source_minute = int(ts // 60) * 60
                    for h in HORIZONS:
                        cur = con.execute(
                            """
                            INSERT OR IGNORE INTO binance_crosscheck_outcomes(
                                pair,symbol,side,source_minute,opened_at,target_at,horizon_sec,
                                entry_price,consensus,consensus_score,global_long,global_short,
                                top_long,top_short,top_position_long,top_position_short,snapshot_age_sec
                            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                pair,symbol,side,source_minute,ts,ts+h,h,price,cc["state"],_num(cc.get("score")),
                                _num(cc.get("global_long")),_num(cc.get("global_short")),
                                _num(cc.get("top_long")),_num(cc.get("top_short")),
                                _num(cc.get("top_position_long")),_num(cc.get("top_position_short")),
                                _num(cc.get("snapshot_age_sec")),
                            ),
                        )
                        if cur.rowcount:
                            created += 1
                con.commit()
            finally:
                con.close()
        return {"status":"ok","attached":attached,"created":created,**settled}
    except Exception as exc:
        return {"status":"error","error":f"{type(exc).__name__}: {exc}","attached":0,"created":0,"closed":0,"skipped":0}


def _metrics(rows: list[dict]) -> dict:
    vals = [float(r["gross_pct"]) for r in rows if r.get("gross_pct") is not None]
    n = len(vals)
    wins = sum(1 for x in vals if x > 0)
    return {
        "n":n,
        "wins":wins,
        "win_rate_pct":wins/n*100.0 if n else 0.0,
        "avg_gross_pct":sum(vals)/n if n else 0.0,
        "total_gross_pct":sum(vals),
    }


def report() -> dict:
    init()
    with _LOCK:
        con = _conn()
        try:
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM binance_crosscheck_outcomes WHERE status='CLOSED' ORDER BY opened_at"
            ).fetchall()]
            counts = {
                str(r["status"]):int(r["n"]) for r in con.execute(
                    "SELECT status,COUNT(*) n FROM binance_crosscheck_outcomes GROUP BY status"
                ).fetchall()
            }
        finally:
            con.close()

    by_horizon = {}
    for h in HORIZONS:
        part = [r for r in rows if int(r.get("horizon_sec") or 0)==h]
        by_horizon[str(h)] = {}
        for state in ("AGREE","CONFLICT","NEUTRAL"):
            by_horizon[str(h)][state] = _metrics([r for r in part if r.get("consensus")==state])
    return {
        "status":"ok","enabled":ENABLED,"mode":"SHADOW_ONLY",
        "period":PERIOD,"horizons_sec":list(HORIZONS),
        "by_horizon":by_horizon,
        "open":counts.get("OPEN",0),"closed":counts.get("CLOSED",0),"skipped":counts.get("SKIPPED",0),
        "cache_symbols":len(_CACHE),
        "note":"Diagnostic crosscheck only. Does not change ENTER/DROP or route orders.",
    }


def status() -> dict:
    if not os.path.exists(DB_PATH):
        if ENABLED:
            try:
                init()
            except Exception:
                pass
    return {
        "enabled":ENABLED,
        "mode":"SHADOW_ONLY",
        "period":PERIOD,
        "cache_sec":CACHE_SEC,
        "max_age_sec":MAX_AGE_SEC,
        "horizons_sec":list(HORIZONS),
        "cache_symbols":len(_CACHE),
        "queue_size":_Q.qsize(),
        "db_path":DB_PATH,
        "live_execution":False,
        "changes_trade_decision":False,
        "public_binance_api_only":True,
    }

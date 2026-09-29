"""MYSHKA / ASTRA Risk Intelligence SHADOW.

One observer for the next validation layer. It evaluates candidates and records
what each additional guard *would* have done, but it never changes ENTER/DROP.

Includes:
- Context Veto 2.0 readiness (historical context signature, min sample gate)
- loss-streak guard
- pair cooldown / blacklist signal
- adaptive EDGE recommendations by pair and regime
- BTC conflict filter
- OI + price divergence detector
- funding extreme guard
- correlation / crowding guard using open Analytics entries
- volatility shock guard
- spread / modeled-cost history
- JEV post-mortem
- A/B EDGE thresholds
- confidence score 0..100

No extra market API calls are made. Five-minute outcomes are settled using the
normal ASTRA scan results.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
import sqlite3
import threading
import time
from typing import Any, Optional

DB_PATH = os.getenv("RISK_INTELLIGENCE_DB_PATH", "/data/myshka_risk_intelligence.sqlite3")
ANALYTICS_DB_PATH = os.getenv("ANALYTICS_DB_PATH", "/data/myshka_analytics.sqlite3")
HORIZON_SEC = max(60, int(os.getenv("RISK_INTELLIGENCE_HORIZON_SEC", "300")))
MAX_SETTLE_DELAY_SEC = max(30, int(os.getenv("RISK_INTELLIGENCE_MAX_SETTLE_DELAY_SEC", "90")))
CONTEXT_MIN_N = max(10, int(os.getenv("RISK_CONTEXT_MIN_N", "30")))
PAIR_MIN_N = max(3, int(os.getenv("RISK_PAIR_MIN_N", "5")))
PAIR_BAD_AVG = float(os.getenv("RISK_PAIR_BAD_AVG_NET_PCT", "-0.10"))
VOL_SHOCK_MULT = float(os.getenv("RISK_VOL_SHOCK_MULT", "1.80"))
BTC_CONFLICT_PCT = float(os.getenv("RISK_BTC_CONFLICT_PCT", "0.10"))
OI_DIVERGENCE_PCT = float(os.getenv("RISK_OI_DIVERGENCE_PCT", "0.50"))
FUNDING_EXTREME_PCT = float(os.getenv("RISK_FUNDING_EXTREME_PCT", "0.020"))
SPREAD_WARN_PCT = float(os.getenv("RISK_SPREAD_WARN_PCT", "0.050"))
COUNTERFACTUAL_DB_PATH = os.getenv("COUNTERFACTUAL_DB_PATH", "/data/myshka_counterfactual.sqlite3")
BLACKBOX_RETENTION = max(500, int(os.getenv("RISK_BLACKBOX_RETENTION", "5000")))
PROMOTION_MIN_N = max(10, int(os.getenv("RISK_PROMOTION_MIN_N", "30")))
DRIFT_WINDOW = max(20, int(os.getenv("RISK_DRIFT_WINDOW", "50")))
AB_THRESHOLDS = (0.05, 0.10, 0.15, 0.20)
CONFIDENCE_BINS = ((0,29),(30,49),(50,69),(70,84),(85,100))
_LOCK = threading.RLock()


def _conn(path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    if path == DB_PATH:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    return con


@contextmanager
def _db(path: str = DB_PATH):
    """SQLite context that always closes the OS file handle.

    sqlite3.Connection.__exit__ commits/rolls back but does not close the
    connection, which leaves temporary DB files locked on Windows.
    """
    con = _conn(path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init() -> dict:
    with _LOCK, _db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS risk_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                side TEXT NOT NULL,
                source_minute INTEGER NOT NULL,
                opened_at REAL NOT NULL,
                target_at REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                entry_price REAL NOT NULL,
                exit_price REAL,
                action TEXT,
                regime TEXT,
                reason TEXT,
                tech_score INTEGER,
                edge_pct REAL,
                expected_move_pct REAL,
                total_cost_pct REAL,
                spread_pct REAL,
                atr_pct REAL,
                atr_median_pct REAL,
                rsi REAL,
                volume_ratio REAL,
                jev_verdict TEXT,
                jev_confidence REAL,
                price_15m_pct REAL,
                oi_15m_pct REAL,
                funding_rate_pct REAL,
                long_short_ratio REAL,
                btc_15m_pct REAL,
                context_samples INTEGER,
                context_signature TEXT,
                context_hist_n INTEGER,
                context_hist_avg_net REAL,
                pair_hist_n INTEGER,
                pair_hist_avg_net REAL,
                pair_hist_win_rate REAL,
                regime_hist_n INTEGER,
                regime_hist_avg_net REAL,
                loss_streak INTEGER,
                same_side_open INTEGER,
                pair_edge_recommendation REAL,
                regime_edge_recommendation REAL,
                confidence_score REAL,
                flags_json TEXT,
                ab_json TEXT,
                settled_at REAL,
                settle_delay_sec REAL,
                gross_pct REAL,
                net_pct REAL,
                direction_hit INTEGER,
                UNIQUE(pair, side, source_minute)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_ri_status_target ON risk_candidates(status,target_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_ri_pair_status ON risk_candidates(pair,status)")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_blackbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pair TEXT NOT NULL,
                source_slot INTEGER NOT NULL,
                observed_at REAL NOT NULL,
                action TEXT,
                reason TEXT,
                direction TEXT,
                tech_score INTEGER,
                edge_pct REAL,
                edge_passed INTEGER,
                jev_verdict TEXT,
                risk_confidence REAL,
                risk_flags_json TEXT,
                stage_json TEXT,
                raw_json TEXT,
                UNIQUE(pair, source_slot)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_blackbox_observed ON decision_blackbox(observed_at DESC)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_blackbox_pair ON decision_blackbox(pair,observed_at DESC)")
    return status()


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _signal_score(sig: dict) -> int:
    side = str(sig.get("direction") or "WAIT").upper()
    fast, slow = _num(sig.get("ema_fast")), _num(sig.get("ema_slow"))
    rsi, vol = _num(sig.get("rsi")), _num(sig.get("volume_ratio"))
    reg = str(sig.get("structure") or "RANGE").upper()
    if side not in {"LONG","SHORT"} or None in {fast,slow,rsi,vol}:
        return 0
    if side == "LONG":
        checks = [fast > slow, reg == "UP", 52 <= rsi <= 72, vol >= 0.60]
    else:
        checks = [fast < slow, reg == "DOWN", 28 <= rsi <= 48, vol >= 0.60]
    return sum(bool(x) for x in checks)


def _analytics_rows(where: str = "", params: tuple = ()) -> list[dict]:
    if not os.path.exists(ANALYTICS_DB_PATH):
        return []
    try:
        sql = "SELECT * FROM analytics_trades WHERE status='CLOSED' AND mode='STRICT'"
        if where:
            sql += " AND " + where
        sql += " ORDER BY opened_at ASC"
        with _db(ANALYTICS_DB_PATH) as con:
            return [dict(x) for x in con.execute(sql, params).fetchall()]
    except Exception:
        return []


def _open_analytics_rows() -> list[dict]:
    if not os.path.exists(ANALYTICS_DB_PATH):
        return []
    try:
        with _db(ANALYTICS_DB_PATH) as con:
            return [dict(x) for x in con.execute("SELECT * FROM analytics_trades WHERE status='OPEN'").fetchall()]
    except Exception:
        return []


def _metrics(rows: list[dict]) -> dict:
    nets = [float(r["net_pct"]) for r in rows if r.get("net_pct") is not None]
    n = len(nets)
    wins = sum(1 for x in nets if x > 0)
    return {
        "n": n,
        "avg_net_pct": (sum(nets)/n) if n else 0.0,
        "win_rate_pct": (wins/n*100.0) if n else 0.0,
        "total_net_pct": sum(nets),
    }


def _loss_streak(rows: Optional[list[dict]] = None) -> int:
    rows = rows if rows is not None else _analytics_rows()
    streak = 0
    for r in reversed(rows):
        if float(r.get("net_pct") or 0.0) < 0:
            streak += 1
        else:
            break
    return streak


def _pair_stats(pair: str, limit: int = 10, rows: Optional[list[dict]] = None) -> dict:
    src = rows if rows is not None else _analytics_rows()
    q = [r for r in src if str(r.get("pair") or "") == pair]
    return _metrics(q[-max(1,limit):])


def _regime_stats(regime: str, limit: int = 50, rows: Optional[list[dict]] = None) -> dict:
    src = rows if rows is not None else _analytics_rows()
    q = [r for r in src if str(r.get("regime") or "") == regime]
    return _metrics(q[-max(1,limit):])


def _context_signature(side: str, btc15: Optional[float], oi15: Optional[float],
                       funding: Optional[float], ls: Optional[float]) -> str:
    def sgn(x: Optional[float], dead: float) -> str:
        if x is None: return "?"
        if x > dead: return "+"
        if x < -dead: return "-"
        return "0"
    if ls is None:
        lsb = "?"
    elif ls < 0.8:
        lsb = "LOW"
    elif ls > 1.2:
        lsb = "HIGH"
    else:
        lsb = "MID"
    return f"{side}|BTC{sgn(btc15,0.05)}|OI{sgn(oi15,0.25)}|F{sgn(funding,0.005)}|LS{lsb}"


def _context_historical(signature: str, rows: Optional[list[dict]] = None) -> dict:
    rows = rows if rows is not None else _analytics_rows()
    matched = []
    for r in rows:
        sig = _context_signature(
            str(r.get("side") or ""),
            _num(r.get("btc_15m_pct")),
            _num(r.get("oi_15m_pct")),
            _num(r.get("funding_rate_pct")),
            _num(r.get("long_short_ratio")),
        )
        if sig == signature:
            matched.append(r)
    return _metrics(matched)


def _adaptive_edge(rows: list[dict]) -> Optional[float]:
    if len(rows) < PAIR_MIN_N:
        return None
    best = None
    for t in AB_THRESHOLDS:
        q = [r for r in rows if _num(r.get("expected_edge_pct")) is not None and float(r.get("expected_edge_pct")) >= t]
        m = _metrics(q)
        if m["n"] >= PAIR_MIN_N and m["avg_net_pct"] > 0:
            best = t
            break
    if best is not None:
        return best
    # If no profitable historical threshold exists yet, recommend the strictest
    # tested threshold as a SHADOW warning, not a trading rule.
    return max(AB_THRESHOLDS)


def _market_price(r: dict) -> Optional[float]:
    m = r.get("market") or {}
    x = _num(m.get("last_price"))
    return x if x is not None and x > 0 else None


def _candidate_features(r: dict, history_rows: list[dict], open_rows: list[dict]) -> Optional[dict]:
    sig = r.get("signal") or {}
    side = str(r.get("direction") or sig.get("direction") or "WAIT").upper()
    if side not in {"LONG","SHORT"}:
        return None
    price = _market_price(r)
    if price is None:
        return None

    edge = r.get("edge") or {}
    jev = r.get("jev") or {}
    ctx = r.get("context") or {}
    mkt = r.get("market") or {}
    regime = str(sig.get("structure") or "RANGE").upper()
    edge_pct = _num(edge.get("net_edge_pct"))
    btc15 = _num(ctx.get("btc_price_change_15m_pct"))
    oi15 = _num(ctx.get("oi_change_15m_pct"))
    p15 = _num(ctx.get("price_change_15m_pct"))
    funding = _num(ctx.get("funding_rate_pct"))
    ls = _num(ctx.get("long_short_ratio"))
    signature = _context_signature(side, btc15, oi15, funding, ls)

    pair_name = str(r.get("pair") or "")
    pair_hist = _pair_stats(pair_name, rows=history_rows)
    regime_hist = _regime_stats(regime, rows=history_rows)
    context_hist = _context_historical(signature, rows=history_rows)
    loss_streak = _loss_streak(history_rows)
    same_side_open = sum(1 for x in open_rows if str(x.get("side") or "").upper() == side)

    pair_rows = [x for x in history_rows if str(x.get("pair") or "") == pair_name]
    regime_rows = [x for x in history_rows if str(x.get("regime") or "") == regime]
    pair_edge = _adaptive_edge(pair_rows)
    regime_edge = _adaptive_edge(regime_rows)

    atr = _num(mkt.get("atr_pct"))
    atr_med = _num(mkt.get("atr_pct_median"))
    spread = _num(mkt.get("spread_pct"))
    flags = []

    if loss_streak >= 3:
        flags.append("LOSS_STREAK_3PLUS")
    if pair_hist["n"] >= PAIR_MIN_N and pair_hist["avg_net_pct"] <= PAIR_BAD_AVG and pair_hist["win_rate_pct"] <= 40:
        flags.append("PAIR_COOLDOWN")
    if context_hist["n"] >= CONTEXT_MIN_N and context_hist["avg_net_pct"] < 0:
        flags.append("CONTEXT_VETO_CANDIDATE")
    if btc15 is not None:
        if (side == "LONG" and btc15 <= -BTC_CONFLICT_PCT) or (side == "SHORT" and btc15 >= BTC_CONFLICT_PCT):
            flags.append("BTC_AGAINST")
    if p15 is not None and oi15 is not None:
        if side == "LONG" and p15 > 0.10 and oi15 <= -OI_DIVERGENCE_PCT:
            flags.append("OI_PRICE_DIVERGENCE")
        if side == "SHORT" and p15 < -0.10 and oi15 >= OI_DIVERGENCE_PCT:
            flags.append("OI_PRICE_DIVERGENCE")
    if funding is not None:
        if (side == "LONG" and funding >= FUNDING_EXTREME_PCT) or (side == "SHORT" and funding <= -FUNDING_EXTREME_PCT):
            flags.append("FUNDING_EXTREME")
    if same_side_open >= 2:
        flags.append("CORRELATION_CROWDING")
    if atr is not None and atr_med is not None and atr_med > 0 and atr / atr_med >= VOL_SHOCK_MULT:
        flags.append("VOLATILITY_SHOCK")
    if spread is not None and spread >= SPREAD_WARN_PCT:
        flags.append("SPREAD_HIGH")
    if pair_edge is not None and edge_pct is not None and edge_pct < pair_edge:
        flags.append("PAIR_EDGE_BELOW_HISTORY")
    if regime_edge is not None and edge_pct is not None and edge_pct < regime_edge:
        flags.append("REGIME_EDGE_BELOW_HISTORY")

    score = 35.0
    tech = _signal_score(sig)
    score += tech * 8.0
    if edge_pct is not None:
        score += max(-15.0, min(20.0, edge_pct * 80.0))
    verdict = str(jev.get("verdict") or "").upper()
    if verdict == "APPROVE":
        score += 10.0
    elif verdict == "REJECT":
        score -= 15.0
    confidence = _num(jev.get("confidence"))
    if confidence is not None:
        score += max(-5.0, min(5.0, (confidence - 0.5) * 10.0))
    score -= min(45.0, len(flags) * 7.0)
    if pair_hist["n"] >= PAIR_MIN_N:
        score += max(-8.0, min(8.0, pair_hist["avg_net_pct"] * 20.0))
    score = max(0.0, min(100.0, score))

    ab = {f"{t:.2f}": bool(edge_pct is not None and edge_pct > t) for t in AB_THRESHOLDS}

    return {
        "pair": str(r.get("pair") or ""), "side": side, "entry": price,
        "action": str(r.get("action") or ""), "regime": regime,
        "reason": str(r.get("reason") or ""), "tech_score": tech,
        "edge_pct": edge_pct, "expected_move_pct": _num(edge.get("expected_move_pct")),
        "total_cost_pct": _num(edge.get("total_cost_pct")), "spread_pct": spread,
        "atr_pct": atr, "atr_median_pct": atr_med, "rsi": _num(sig.get("rsi")),
        "volume_ratio": _num(sig.get("volume_ratio")), "jev_verdict": verdict or "WAIT",
        "jev_confidence": confidence, "price_15m_pct": p15, "oi_15m_pct": oi15,
        "funding_rate_pct": funding, "long_short_ratio": ls, "btc_15m_pct": btc15,
        "context_samples": int(ctx.get("samples") or 0), "context_signature": signature,
        "context_hist": context_hist, "pair_hist": pair_hist, "regime_hist": regime_hist,
        "loss_streak": loss_streak, "same_side_open": same_side_open,
        "pair_edge_recommendation": pair_edge, "regime_edge_recommendation": regime_edge,
        "confidence_score": score, "flags": flags, "ab": ab,
    }


def _json_dump(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        return "{}"


def _record_blackbox(r: dict, now: float, history_rows: list[dict], open_rows: list[dict]) -> bool:
    pair = str(r.get("pair") or "")
    if not pair:
        return False
    sig = r.get("signal") or {}
    edge = r.get("edge") or {}
    jev = r.get("jev") or {}
    ctx = r.get("context") or {}
    guard = r.get("guard") or {}
    evidence_gate = r.get("evidence_gate") or {}
    risk = _candidate_features(r, history_rows, open_rows)
    direction = str(r.get("direction") or sig.get("direction") or "WAIT").upper()
    tech_score = _signal_score(sig)
    flags = (risk or {}).get("flags", [])
    confidence = (risk or {}).get("confidence_score")
    stage = {
        "tech": {
            "direction": direction, "score": tech_score,
            "structure": sig.get("structure"), "rsi": sig.get("rsi"),
            "volume_ratio": sig.get("volume_ratio"), "reason": sig.get("reason"),
        },
        "edge": {
            "passed": bool(edge.get("passed")) if edge else None,
            "net_edge_pct": edge.get("net_edge_pct"),
            "expected_move_pct": edge.get("expected_move_pct"),
            "total_cost_pct": edge.get("total_cost_pct"),
            "reason": edge.get("reason"),
            "min_required_net_edge_pct": edge.get("min_required_net_edge_pct"),
        },
        "context": {
            "samples": ctx.get("samples"), "age_sec": ctx.get("age_sec"),
            "price_15m_pct": ctx.get("price_change_15m_pct"),
            "oi_15m_pct": ctx.get("oi_change_15m_pct"),
            "funding_rate_pct": ctx.get("funding_rate_pct"),
            "long_short_ratio": ctx.get("long_short_ratio"),
            "btc_15m_pct": ctx.get("btc_price_change_15m_pct"),
            "external_event_count": ctx.get("external_event_count"),
        },
        "jev": {
            "verdict": jev.get("verdict"), "confidence": jev.get("confidence"),
            "reason": jev.get("reason"),
        },
        "guard": {
            "passed": guard.get("passed"), "reasons": guard.get("reasons"),
        },
        "evidence_gate": {
            "applies": evidence_gate.get("applies"), "passed": evidence_gate.get("passed"),
            "state": evidence_gate.get("state"), "reason": evidence_gate.get("reason"),
            "candidate_edge_pct": evidence_gate.get("candidate_edge_pct"),
            "qualified_threshold_pct": evidence_gate.get("qualified_threshold_pct"),
            "evidence_n": evidence_gate.get("evidence_n"),
            "evidence_avg_net_pct": evidence_gate.get("evidence_avg_net_pct"),
            "evidence_profit_factor": evidence_gate.get("evidence_profit_factor"),
            "recent_avg_net_pct": evidence_gate.get("recent_avg_net_pct"),
        },
        "risk_intelligence": {
            "flags": flags, "confidence_score": confidence,
            "pair_edge_recommendation": (risk or {}).get("pair_edge_recommendation"),
            "regime_edge_recommendation": (risk or {}).get("regime_edge_recommendation"),
        },
        "final": {"action": r.get("action"), "reason": r.get("reason")},
        "market": {
            "last_price": (r.get("market") or {}).get("last_price"),
            "spread_pct": (r.get("market") or {}).get("spread_pct"),
            "atr_pct": (r.get("market") or {}).get("atr_pct"),
            "atr_pct_median": (r.get("market") or {}).get("atr_pct_median"),
        },
    }
    slot = int(now // 15) * 15
    with _LOCK, _db() as con:
        cur = con.execute(
            """
            INSERT OR REPLACE INTO decision_blackbox(
                pair,source_slot,observed_at,action,reason,direction,tech_score,
                edge_pct,edge_passed,jev_verdict,risk_confidence,risk_flags_json,
                stage_json,raw_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                pair, slot, now, str(r.get("action") or ""), str(r.get("reason") or "")[:1000],
                direction, tech_score, _num(edge.get("net_edge_pct")),
                1 if bool(edge.get("passed")) else 0 if edge else None,
                str(jev.get("verdict") or ""), confidence, _json_dump(flags),
                _json_dump(stage), _json_dump(r),
            ),
        )
        con.execute(
            "DELETE FROM decision_blackbox WHERE id NOT IN (SELECT id FROM decision_blackbox ORDER BY id DESC LIMIT ?)",
            (BLACKBOX_RETENTION,),
        )
        return bool(cur.rowcount)


def _record_candidate(r: dict, now: float, history_rows: list[dict], open_rows: list[dict]) -> bool:
    f = _candidate_features(r, history_rows, open_rows)
    if not f:
        return False
    source_minute = int(now // 60) * 60
    values = (
        f["pair"], f["side"], source_minute, now, now + HORIZON_SEC, f["entry"],
        f["action"], f["regime"], f["reason"][:1000], f["tech_score"], f["edge_pct"],
        f["expected_move_pct"], f["total_cost_pct"], f["spread_pct"], f["atr_pct"],
        f["atr_median_pct"], f["rsi"], f["volume_ratio"], f["jev_verdict"],
        f["jev_confidence"], f["price_15m_pct"], f["oi_15m_pct"], f["funding_rate_pct"],
        f["long_short_ratio"], f["btc_15m_pct"], f["context_samples"], f["context_signature"],
        f["context_hist"]["n"], f["context_hist"]["avg_net_pct"],
        f["pair_hist"]["n"], f["pair_hist"]["avg_net_pct"], f["pair_hist"]["win_rate_pct"],
        f["regime_hist"]["n"], f["regime_hist"]["avg_net_pct"], f["loss_streak"],
        f["same_side_open"], f["pair_edge_recommendation"], f["regime_edge_recommendation"],
        f["confidence_score"], json.dumps(f["flags"], separators=(",",":")),
        json.dumps(f["ab"], separators=(",",":")),
    )
    with _LOCK, _db() as con:
        cur = con.execute(
            """
            INSERT OR IGNORE INTO risk_candidates(
                pair,side,source_minute,opened_at,target_at,entry_price,action,regime,reason,
                tech_score,edge_pct,expected_move_pct,total_cost_pct,spread_pct,atr_pct,
                atr_median_pct,rsi,volume_ratio,jev_verdict,jev_confidence,price_15m_pct,
                oi_15m_pct,funding_rate_pct,long_short_ratio,btc_15m_pct,context_samples,
                context_signature,context_hist_n,context_hist_avg_net,pair_hist_n,
                pair_hist_avg_net,pair_hist_win_rate,regime_hist_n,regime_hist_avg_net,
                loss_streak,same_side_open,pair_edge_recommendation,regime_edge_recommendation,
                confidence_score,flags_json,ab_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, values
        )
        return bool(cur.rowcount)


def _settle(results: list[dict], now: float) -> dict:
    by_pair = {str(r.get("pair") or ""): r for r in results if r.get("pair")}
    closed = skipped = 0
    with _LOCK, _db() as con:
        rows = con.execute("SELECT * FROM risk_candidates WHERE status='OPEN' AND target_at<=? ORDER BY target_at", (now,)).fetchall()
        for row in rows:
            delay = max(0.0, now - float(row["target_at"]))
            if delay > MAX_SETTLE_DELAY_SEC:
                con.execute("UPDATE risk_candidates SET status='SKIPPED',settled_at=?,settle_delay_sec=? WHERE id=?",
                            (now,delay,int(row["id"])))
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
            costs = float(row["total_cost_pct"] or 0.0)
            net = gross - costs
            con.execute(
                """UPDATE risk_candidates SET status='CLOSED',exit_price=?,settled_at=?,
                   settle_delay_sec=?,gross_pct=?,net_pct=?,direction_hit=? WHERE id=?""",
                (exit_price,now,delay,gross,net,1 if gross>0 else 0,int(row["id"]))
            )
            closed += 1
    return {"closed":closed,"skipped":skipped}


def observe_results(results: list[dict], now: Optional[float] = None) -> dict:
    try:
        init()
        ts = float(now or time.time())
        out = _settle(results or [], ts)
        history_rows = _analytics_rows()
        open_rows = _open_analytics_rows()
        created = 0
        blackbox = 0
        for r in results or []:
            if _record_blackbox(r, ts, history_rows, open_rows):
                blackbox += 1
            if _record_candidate(r, ts, history_rows, open_rows):
                created += 1
        return {"status":"ok","created":created,"blackbox":blackbox,**out}
    except Exception as exc:
        return {"status":"error","error":f"{type(exc).__name__}: {exc}","created":0,"closed":0,"skipped":0}


def status() -> dict:
    try:
        if not os.path.exists(DB_PATH):
            init()
        with _LOCK, _db() as con:
            rows = con.execute("SELECT status,COUNT(*) n FROM risk_candidates GROUP BY status").fetchall()
        counts = {str(r["status"]):int(r["n"]) for r in rows}
        return {
            "enabled":True,"mode":"SHADOW","db_path":DB_PATH,"horizon_sec":HORIZON_SEC,
            "open":counts.get("OPEN",0),"closed":counts.get("CLOSED",0),
            "skipped":counts.get("SKIPPED",0),
        }
    except Exception as exc:
        return {"enabled":True,"mode":"SHADOW","db_path":DB_PATH,"error":f"{type(exc).__name__}: {exc}"}


def _closed_rows() -> list[dict]:
    init()
    with _LOCK, _db() as con:
        return [dict(x) for x in con.execute("SELECT * FROM risk_candidates WHERE status='CLOSED' ORDER BY opened_at").fetchall()]


def _ab_report(rows: list[dict]) -> dict:
    out = {}
    for t in AB_THRESHOLDS:
        key = f"{t:.2f}"
        q = []
        for r in rows:
            try:
                ab = json.loads(r.get("ab_json") or "{}")
            except Exception:
                ab = {}
            if bool(ab.get(key)):
                q.append(r)
        out[key] = _metrics(q)
    return out


def _flag_report(rows: list[dict]) -> list[dict]:
    groups: dict[str,list[dict]] = defaultdict(list)
    for r in rows:
        try:
            flags = json.loads(r.get("flags_json") or "[]")
        except Exception:
            flags = []
        for flag in flags:
            groups[str(flag)].append(r)
    out = [{"flag":k,**_metrics(v)} for k,v in groups.items()]
    out.sort(key=lambda x:(-int(x["n"]),float(x["avg_net_pct"])))
    return out


def _jev_report(rows: list[dict]) -> dict:
    out = {}
    for verdict in ("APPROVE","REJECT","WAIT"):
        q = [r for r in rows if str(r.get("jev_verdict") or "").upper()==verdict]
        out[verdict] = _metrics(q)
    return out


def _cost_report(rows: list[dict]) -> list[dict]:
    groups: dict[str,list[dict]] = defaultdict(list)
    for r in rows:
        groups[str(r.get("pair") or "")].append(r)
    out=[]
    for pair,q in groups.items():
        costs=[float(x["total_cost_pct"]) for x in q if x.get("total_cost_pct") is not None]
        spreads=[float(x["spread_pct"]) for x in q if x.get("spread_pct") is not None]
        out.append({
            "pair":pair.replace("/USDT:USDT",""),"n":len(q),
            "avg_cost_pct":sum(costs)/len(costs) if costs else 0.0,
            "avg_spread_pct":sum(spreads)/len(spreads) if spreads else 0.0,
            "avg_net_pct":_metrics(q)["avg_net_pct"],
        })
    out.sort(key=lambda x:-x["n"])
    return out


def _flag_groups(rows: list[dict]) -> dict[str,list[dict]]:
    groups: dict[str,list[dict]] = defaultdict(list)
    for r in rows:
        try:
            flags = json.loads(r.get("flags_json") or "[]")
        except Exception:
            flags = []
        for flag in flags:
            groups[str(flag)].append(r)
    return groups


def _guard_effectiveness(rows: list[dict]) -> list[dict]:
    out = []
    for flag, q in _flag_groups(rows).items():
        nets = [float(x["net_pct"]) for x in q if x.get("net_pct") is not None]
        n = len(nets)
        saved = sum(1 for x in nets if x <= 0)
        false_blocks = sum(1 for x in nets if x > 0)
        out.append({
            "guard": flag, "n": n,
            "saved_losses": saved,
            "false_blocks": false_blocks,
            "false_block_rate_pct": (false_blocks / n * 100.0) if n else 0.0,
            "avg_hypothetical_net_pct": (sum(nets) / n) if n else 0.0,
            "total_hypothetical_net_pct": sum(nets),
        })
    out.sort(key=lambda x: (-int(x["n"]), float(x["avg_hypothetical_net_pct"])))
    return out


def _confidence_calibration(rows: list[dict]) -> list[dict]:
    out = []
    for lo, hi in CONFIDENCE_BINS:
        q = [r for r in rows if _num(r.get("confidence_score")) is not None and lo <= float(r["confidence_score"]) <= hi]
        m = _metrics(q)
        out.append({"label": f"{lo}-{hi}", "min": lo, "max": hi, **m})
    return out


def _promotion_gate(rows: list[dict]) -> list[dict]:
    out = []
    for flag, q in _flag_groups(rows).items():
        q = [x for x in q if x.get("net_pct") is not None]
        n = len(q)
        m = _metrics(q)
        half = max(1, n // 2)
        first = _metrics(q[:half]) if q else _metrics([])
        second = _metrics(q[half:]) if q[half:] else _metrics([])
        stable = bool(
            n >= PROMOTION_MIN_N
            and first["n"] >= max(5, PROMOTION_MIN_N // 3)
            and second["n"] >= max(5, PROMOTION_MIN_N // 3)
            and first["avg_net_pct"] < 0
            and second["avg_net_pct"] < 0
        )
        false_rate = 100.0 - m["win_rate_pct"]
        # For a veto-style guard, hypothetical positive outcomes are false blocks.
        false_block_rate = m["win_rate_pct"]
        if n < 10:
            readiness = "WARMING"
        elif n < PROMOTION_MIN_N:
            readiness = "EARLY"
        elif stable and m["avg_net_pct"] < 0 and false_block_rate <= 20.0:
            readiness = "READY_FOR_REVIEW"
        else:
            readiness = "HOLD"
        out.append({
            "guard": flag, "n": n, "sample_state": "COLD" if n < 10 else "EARLY" if n < PROMOTION_MIN_N else "USABLE",
            "effect_stable": stable, "false_block_rate_pct": false_block_rate,
            "avg_hypothetical_net_pct": m["avg_net_pct"], "readiness": readiness,
        })
    out.sort(key=lambda x: (x["readiness"] != "READY_FOR_REVIEW", -int(x["n"])))
    return out


def _drift_report(rows: list[dict]) -> dict:
    q = [r for r in rows if r.get("net_pct") is not None]
    if len(q) < 40:
        return {"state":"WARMING","n":len(q),"window":DRIFT_WINDOW,"reason":"need >=40 closed shadow outcomes"}
    w = min(DRIFT_WINDOW, len(q) // 2)
    recent = q[-w:]
    prior = q[-2*w:-w]
    mr, mp = _metrics(recent), _metrics(prior)
    def mean_field(part: list[dict], field: str) -> float:
        vals = [float(x[field]) for x in part if x.get(field) is not None]
        return sum(vals)/len(vals) if vals else 0.0
    net_delta = mr["avg_net_pct"] - mp["avg_net_pct"]
    win_delta = mr["win_rate_pct"] - mp["win_rate_pct"]
    cost_delta = mean_field(recent,"total_cost_pct") - mean_field(prior,"total_cost_pct")
    conf_delta = mean_field(recent,"confidence_score") - mean_field(prior,"confidence_score")
    stale = abs(net_delta) >= 0.25 or abs(win_delta) >= 20.0 or abs(cost_delta) >= 0.05
    return {
        "state":"STALE" if stale else "STABLE","n":len(q),"window":w,
        "recent":mr,"prior":mp,
        "avg_net_delta_pct":net_delta,"win_rate_delta_pp":win_delta,
        "avg_cost_delta_pct":cost_delta,"confidence_delta":conf_delta,
    }


def _db_open_stale(path: str, table: str, now: float, target_col: Optional[str] = None) -> dict:
    if not os.path.exists(path):
        return {"ok":False,"count":0,"stale":0,"detail":"DB missing"}
    try:
        with _db(path) as con:
            if target_col:
                rows = con.execute(f"SELECT * FROM {table} WHERE status='OPEN'").fetchall()
                stale = sum(1 for r in rows if r[target_col] is not None and now > float(r[target_col]) + MAX_SETTLE_DELAY_SEC)
            else:
                rows = con.execute(f"SELECT * FROM {table} WHERE status='OPEN'").fetchall()
                stale = sum(1 for r in rows if r["opened_at"] is not None and now > float(r["opened_at"]) + HORIZON_SEC + MAX_SETTLE_DELAY_SEC)
        return {"ok":stale==0,"count":len(rows),"stale":stale}
    except Exception as exc:
        return {"ok":False,"count":0,"stale":0,"detail":f"{type(exc).__name__}: {exc}"}


def _watchdog() -> dict:
    now = time.time()
    checks = []
    try:
        with _LOCK, _db() as con:
            last = con.execute("SELECT MAX(observed_at) t FROM decision_blackbox").fetchone()
            last_t = float(last["t"] or 0) if last else 0.0
            recent = con.execute(
                "SELECT stage_json FROM decision_blackbox WHERE observed_at>=? ORDER BY observed_at DESC LIMIT 60",
                (now - 90.0,),
            ).fetchall()
        age = now - last_t if last_t else None
        checks.append({"name":"scanner_freshness","ok":age is not None and age <= 90.0,"detail":"no snapshots" if age is None else f"age {age:.0f}s"})
        missing = 0
        for row in recent:
            try:
                stage = json.loads(row["stage_json"] or "{}")
            except Exception:
                stage = {}
            if (stage.get("market") or {}).get("last_price") in (None,0,""):
                missing += 1
        checks.append({"name":"market_price_coverage","ok":missing==0,"detail":f"missing {missing}/{len(recent)}"})
    except Exception as exc:
        checks.extend([
            {"name":"scanner_freshness","ok":False,"detail":f"{type(exc).__name__}: {exc}"},
            {"name":"market_price_coverage","ok":False,"detail":"blackbox unavailable"},
        ])

    risk = _db_open_stale(DB_PATH,"risk_candidates",now,"target_at")
    analytics = _db_open_stale(ANALYTICS_DB_PATH,"analytics_trades",now,None)
    cf = _db_open_stale(COUNTERFACTUAL_DB_PATH,"counterfactuals",now,"target_at")
    checks.append({"name":"risk_settlement","ok":risk["ok"],"detail":f"open {risk['count']} · stale {risk['stale']}"})
    checks.append({"name":"paper_analytics_positions","ok":analytics["ok"],"detail":f"open {analytics['count']} · stale {analytics['stale']}"})
    checks.append({"name":"counterfactual_settlement","ok":cf["ok"],"detail":f"open {cf['count']} · stale {cf['stale']}"})
    checks.append({"name":"risk_db","ok":os.path.exists(DB_PATH),"detail":DB_PATH})
    checks.append({"name":"analytics_and_cf_db","ok":os.path.exists(ANALYTICS_DB_PATH) and os.path.exists(COUNTERFACTUAL_DB_PATH),"detail":"analytics + counterfactual"})
    ok_n = sum(1 for x in checks if x["ok"])
    return {"ok":ok_n==len(checks),"ok_n":ok_n,"total":len(checks),"checks":checks}


def quality_report() -> dict:
    rows = _closed_rows()
    with _LOCK, _db() as con:
        bb = con.execute("SELECT COUNT(*) n FROM decision_blackbox").fetchone()
    blackbox_count = int(bb["n"] or 0) if bb else 0
    return {
        "status":"ok","mode":"SHADOW","shadow_only":True,
        "blackbox_count":blackbox_count,
        "guard_effectiveness":_guard_effectiveness(rows),
        "confidence_calibration":_confidence_calibration(rows),
        "promotion_gate":_promotion_gate(rows),
        "drift":_drift_report(rows),
        "watchdog":_watchdog(),
        "policy":{"promotion_min_n":PROMOTION_MIN_N,"drift_window":DRIFT_WINDOW},
        "note":"Quality Control is observational only. It never activates guards automatically.",
    }


def replay(limit: int = 20, decision_id: Optional[int] = None) -> dict:
    init()
    n = max(1,min(100,int(limit)))
    with _LOCK, _db() as con:
        if decision_id is not None:
            rows = con.execute("SELECT * FROM decision_blackbox WHERE id=?",(int(decision_id),)).fetchall()
        else:
            rows = con.execute("SELECT * FROM decision_blackbox ORDER BY observed_at DESC LIMIT ?",(n,)).fetchall()
    items = []
    for row in rows:
        d = dict(row)
        for field, target in (("risk_flags_json","risk_flags"),("stage_json","stages"),("raw_json","raw")):
            try:
                d[target] = json.loads(d.get(field) or ("[]" if field=="risk_flags_json" else "{}"))
            except Exception:
                d[target] = [] if field=="risk_flags_json" else {}
            d.pop(field,None)
        items.append(d)
    return {"status":"ok","mode":"BLACK_BOX","items":items}


def report() -> dict:
    rows = _closed_rows()
    overall = _metrics(rows)
    latest = None
    with _LOCK, _db() as con:
        rr = con.execute("SELECT * FROM risk_candidates ORDER BY opened_at DESC LIMIT 1").fetchone()
        if rr:
            latest = dict(rr)
    if latest:
        try: latest["flags"] = json.loads(latest.get("flags_json") or "[]")
        except Exception: latest["flags"] = []
        try: latest["ab"] = json.loads(latest.get("ab_json") or "{}")
        except Exception: latest["ab"] = {}
        latest.pop("flags_json",None); latest.pop("ab_json",None)

    return {
        "status":"ok","mode":"SHADOW","shadow_only":True,
        "overall":overall,"open":status().get("open",0),"skipped":status().get("skipped",0),
        "sample_state":"COLD" if overall["n"]<10 else "EARLY" if overall["n"]<30 else "USABLE" if overall["n"]<100 else "MATURE",
        "latest":latest,
        "ab_edge":_ab_report(rows),
        "flags":_flag_report(rows),
        "jev_postmortem":_jev_report(rows),
        "cost_history":_cost_report(rows)[:15],
        "policy":{
            "context_min_n":CONTEXT_MIN_N,"pair_min_n":PAIR_MIN_N,
            "vol_shock_mult":VOL_SHOCK_MULT,"btc_conflict_pct":BTC_CONFLICT_PCT,
            "oi_divergence_pct":OI_DIVERGENCE_PCT,"funding_extreme_pct":FUNDING_EXTREME_PCT,
            "spread_warn_pct":SPREAD_WARN_PCT,"ab_thresholds":list(AB_THRESHOLDS),
        },
        "note":"All guards are SHADOW. No entry, veto, sizing, or execution rule is changed.",
    }

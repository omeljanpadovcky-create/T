from pathlib import Path
import sys

MARKER = "MYSHKA_ANALYTICS_SHADOW_CORE_V2"


def replace_once(s: str, old: str, new: str, label: str) -> str:
    if old not in s:
        raise RuntimeError(f"patch target not found: {label}")
    return s.replace(old, new, 1)


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")

    if MARKER in s:
        compile(s, str(path), "exec")
        print("[OK] api.py already has Analytics SHADOW core V2")
        return

    # Do not attempt to stack V2 on top of a half-applied/broken V1.
    if "MYSHKA_ANALYTICS_SHADOW_V1" in s:
        raise RuntimeError("old Analytics V1 marker found; restore a clean backup before applying V2")

    old_import = "from .context_collector import start as context_start, status as context_status, snapshot as context_snapshot, ingest_external as context_ingest\n"
    new_import = old_import + (
        "from .analytics_shadow import init as analytics_init, status as analytics_status, report as analytics_report, "
        "recent as analytics_recent, record_entry as analytics_record_entry, record_close as analytics_record_close, "
        "record_skip as analytics_record_skip\n"
    )
    s = replace_once(s, old_import, new_import, "analytics import")

    startup = (
        '@app.on_event("startup")\n'
        'def _startup_phone_control():\n'
        '    # MYSHKA_CONTEXT_24_7_PATCH_V1\n'
        '    context_start()\n'
        '    _start_phone_threads()\n'
    )
    startup_new = (
        '@app.on_event("startup")\n'
        'def _startup_phone_control():\n'
        '    # MYSHKA_CONTEXT_24_7_PATCH_V1\n'
        '    context_start()\n'
        f'    # {MARKER}\n'
        '    analytics_init()\n'
        '    _start_phone_threads()\n'
    )
    s = replace_once(s, startup, startup_new, "startup analytics init")

    s = replace_once(
        s,
        '        "context_collector": context_status(),\n',
        '        "context_collector": context_status(),\n        "analytics_shadow": analytics_status(),\n',
        "health analytics status",
    )

    context_ingest_tail = (
        '@app.post("/context/ingest")\n'
        'def context_ingest_api(req: ContextIngestRequest, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return context_ingest(\n'
        '        source=req.source, kind=req.kind, text=req.text, pair=req.pair,\n'
        '        sentiment=req.sentiment, score=req.score, url=req.url, ts=req.ts, extra=req.extra,\n'
        '    )\n\n\n'
    )
    endpoints = (
        '@app.get("/analytics/status")\n'
        'def analytics_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return analytics_status()\n\n\n'
        '@app.get("/analytics/report")\n'
        'def analytics_report_api(mode: str = "STRICT", min_segment_n: int = 3, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return analytics_report(mode=mode, min_segment_n=min_segment_n)\n\n\n'
        '@app.get("/analytics/recent")\n'
        'def analytics_recent_api(limit: int = 50, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return {"status": "ok", "trades": analytics_recent(limit)}\n\n\n'
    )
    s = replace_once(s, context_ingest_tail, context_ingest_tail + endpoints, "analytics endpoints")

    control_status_target = '        "stats": global_summary(),\n        "integrations": {\n'
    control_status_new = '        "stats": global_summary(),\n        "analytics": analytics_status(),\n        "integrations": {\n'
    s = replace_once(s, control_status_target, control_status_new, "control status analytics")

    open_target = (
        '            p = {\n'
        '                "pair": pair,\n'
        '                "side": r.get("direction") or sig.get("direction"),\n'
        '                "regime": sig.get("structure") or "RANGE",\n'
        '                "entry": entry,\n'
        '                "opened_at": time.time(),\n'
        '                "horizon_sec": 300,\n'
        '                "expected_edge_pct": float(edge.get("net_edge_pct") or 0.0),\n'
        '                "costs_pct": float(edge.get("total_cost_pct") or 0.0),\n'
        '                "notional_pct_equity": float(size.get("notional_pct_equity") or 0.0),\n'
        '            }\n'
        '            _PHONE["positions"][pair] = p\n'
    )
    open_new = open_target.replace(
        '            _PHONE["positions"][pair] = p\n',
        '            p["analytics_id"] = analytics_record_entry(p, r)\n'
        '            _PHONE["positions"][pair] = p\n',
    )
    s = replace_once(s, open_target, open_new, "record analytics entry")

    stale_target = (
        '                stale.append({\n'
        '                    "pair": pair, "side": p.get("side"),\n'
        '                    "delay_sec": round(settle_delay, 1),\n'
        '                    "horizon_sec": int(p.get("horizon_sec", 300)),\n'
        '                })\n'
    )
    stale_new = (
        '                stale.append({\n'
        '                    "pair": pair, "side": p.get("side"),\n'
        '                    "delay_sec": round(settle_delay, 1),\n'
        '                    "horizon_sec": int(p.get("horizon_sec", 300)),\n'
        '                    "analytics_id": p.get("analytics_id"),\n'
        '                })\n'
    )
    s = replace_once(s, stale_target, stale_new, "stale analytics id")

    stale_loop = (
        '    for x in stale:\n'
        '        _emit_event({"event": "SETTLE_SKIPPED", "source": "phone-engine", **x})\n'
    )
    stale_loop_new = (
        '    for x in stale:\n'
        '        analytics_record_skip(analytics_id=x.get("analytics_id"), note="stale settlement", closed_at=now)\n'
        '        _emit_event({"event": "SETTLE_SKIPPED", "source": "phone-engine", **x})\n'
    )
    s = replace_once(s, stale_loop, stale_loop_new, "record skipped analytics")

    close_target = (
        '            trade_id = log_trade(rec)\n'
        '            closed.append({"trade_id": trade_id, "pair": pair, "side": p["side"], "gross_pct": gross, "net_pct": net, "direction_hit": hit})\n'
    )
    close_new = (
        '            trade_id = log_trade(rec)\n'
        '            analytics_record_close(analytics_id=p.get("analytics_id"), gross_pct=gross, net_pct=net, direction_hit=hit, closed_at=now)\n'
        '            closed.append({"trade_id": trade_id, "pair": pair, "side": p["side"], "gross_pct": gross, "net_pct": net, "direction_hit": hit})\n'
    )
    s = replace_once(s, close_target, close_new, "record analytics close")

    # Critical safety check: generated api.py must parse before it is written.
    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Analytics SHADOW core V2 (no Telegram modifications)")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_analytics_core_v2.py <ASTRA_PROJECT_DIR>")
    root = Path(sys.argv[1]).resolve()
    patch_api(root / "api.py")


if __name__ == "__main__":
    main()

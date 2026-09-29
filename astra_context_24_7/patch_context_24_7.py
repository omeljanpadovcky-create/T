from __future__ import annotations

from pathlib import Path
import sys

MARKER = "MYSHKA_CONTEXT_24_7_PATCH_V1"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"patch target not found: {label}")
    return text.replace(old, new, 1)


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    if MARKER in s:
        print("[OK] api.py already has Background Context 24/7 patch")
        return

    s = replace_once(
        s,
        "from .runtime_control import get_state as runtime_get, set_flag as runtime_set, patch as runtime_patch\n",
        "from .runtime_control import get_state as runtime_get, set_flag as runtime_set, patch as runtime_patch\n"
        "from .context_collector import start as context_start, status as context_status, snapshot as context_snapshot, ingest_external as context_ingest\n",
        "context import",
    )

    s = replace_once(
        s,
        "class ControlSetRequest(BaseModel):\n    name: str\n    value: bool\n\n\ndef _account_client():\n",
        "class ControlSetRequest(BaseModel):\n    name: str\n    value: bool\n\n\n"
        "class ContextIngestRequest(BaseModel):\n"
        "    source: str\n"
        "    kind: str = 'event'\n"
        "    text: str = ''\n"
        "    pair: str = '*'\n"
        "    sentiment: Optional[str] = None\n"
        "    score: Optional[float] = None\n"
        "    url: str = ''\n"
        "    ts: Optional[float] = None\n"
        "    extra: dict = Field(default_factory=dict)\n\n\n"
        "def _account_client():\n",
        "context ingest model",
    )

    s = replace_once(
        s,
        "@app.on_event(\"startup\")\ndef _startup_phone_control():\n    _start_phone_threads()\n",
        "@app.on_event(\"startup\")\ndef _startup_phone_control():\n"
        f"    # {MARKER}\n"
        "    context_start()\n"
        "    _start_phone_threads()\n",
        "startup collector",
    )

    s = replace_once(
        s,
        '        "runtime": runtime_get(),\n        "phone_engine": phone_engine_status(),\n',
        '        "runtime": runtime_get(),\n        "phone_engine": phone_engine_status(),\n        "context_collector": context_status(),\n',
        "health context",
    )

    stats_marker = '@app.get("/stats")\ndef stats(limit: int = 100, x_myshka_token: Optional[str] = Header(default=None)):\n'
    endpoints = (
        '@app.get("/context/status")\n'
        'def context_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return context_status()\n\n\n'
        '@app.get("/context/snapshot")\n'
        'def context_snapshot_api(pair: str = "BTC/USDT:USDT", minutes: int = 30, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return context_snapshot(pair, minutes=minutes)\n\n\n'
        '@app.post("/context/ingest")\n'
        'def context_ingest_api(req: ContextIngestRequest, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return context_ingest(\n'
        '        source=req.source, kind=req.kind, text=req.text, pair=req.pair,\n'
        '        sentiment=req.sentiment, score=req.score, url=req.url, ts=req.ts, extra=req.extra,\n'
        '    )\n\n\n'
    )
    s = replace_once(s, stats_marker, endpoints + stats_marker, "context endpoints")

    training_marker = (
        '    training_meta = {\n'
        '        "active": training_active,\n'
        '        "learner_n": learner_n,\n'
        '        "until_trades": CONFIG.TRAINING_UNTIL_TRADES,\n'
        '        "tech_required": CONFIG.TRAINING_MIN_TECH_CONDITIONS if training_active else 4,\n'
        '        "volume_min": CONFIG.TRAINING_VOLUME_RATIO_MIN if training_active else CONFIG.VOLUME_RATIO_MIN,\n'
        '    }\n\n'
    )
    training_new = training_marker + (
        '    # Background context is SHADOW-only: it is recorded with decisions,\n'
        '    # but cannot create, approve or veto a trade yet.\n'
        '    shadow_context = context_snapshot(req.pair, direction=sig.direction)\n\n'
    )
    s = replace_once(s, training_marker, training_new, "shadow snapshot")

    strict_old = '                "training": training_meta,\n            }\n\n    # JEV is the chief decision coordinator.'
    strict_new = '                "training": training_meta, "context": shadow_context,\n            }\n\n    # JEV is the chief decision coordinator.'
    if "MYSHKA_STRICT_EDGE_BUFFER_005" in s:
        if strict_old in s:
            s = s.replace(strict_old, strict_new, 1)
        elif '"context": shadow_context' not in s[s.find("MYSHKA_STRICT_EDGE_BUFFER_005"):s.find("# JEV is the chief decision coordinator")]:
            raise RuntimeError("STRICT buffer block found but its return shape changed")

    tail = '                "jev": _clean(jev.as_dict()), "training": training_meta}\n'
    if tail not in s:
        raise RuntimeError("JEV return tail not found")
    s = s.replace(tail, '                "jev": _clean(jev.as_dict()), "training": training_meta, "context": shadow_context}\n')

    s = replace_once(
        s,
        '            "guard_reasons": guard.reasons, "training": training_meta,\n',
        '            "guard_reasons": guard.reasons, "training": training_meta, "context": shadow_context,\n',
        "guard return context",
    )

    s = replace_once(
        s,
        '        "training": training_meta,\n    }\n\n\n@app.post("/evaluate")\n',
        '        "training": training_meta,\n        "context": shadow_context,\n    }\n\n\n@app.post("/evaluate")\n',
        "enter return context",
    )

    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched")


def patch_telegram(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    if "CTX SHADOW:" in s:
        print("[OK] telegram_notify.py already has CTX SHADOW output")
        return

    s = replace_once(
        s,
        'def _short(text, limit=180):\n    text = str(text or "").replace("\\n", " ").strip()\n    return text if len(text) <= limit else text[:limit-1] + "…"\n\n\ndef format_scan_digest',
        'def _short(text, limit=180):\n    text = str(text or "").replace("\\n", " ").strip()\n    return text if len(text) <= limit else text[:limit-1] + "…"\n\n\n'
        'def _ctx_num(v, suffix="%", digits=3):\n'
        '    try:\n'
        '        if v is None:\n'
        '            return "—"\n'
        '        return f"{float(v):+.{digits}f}{suffix}"\n'
        '    except Exception:\n'
        '        return "—"\n\n\n'
        'def format_scan_digest',
        "telegram helper",
    )

    marker = '        if jev:\n'
    block = (
        '        ctx = r.get("context") or {}\n'
        '        if ctx:\n'
        '            age = ctx.get("age_sec")\n'
        '            age_txt = "—" if age is None else f"{float(age):.0f}s"\n'
        '            lines.append(\n'
        '                "CTX SHADOW: "\n'
        '                f"n={int(ctx.get(\'samples\') or 0)} · age {age_txt} · "\n'
        '                f"Δ5m {_ctx_num(ctx.get(\'price_change_5m_pct\'))} · "\n'
        '                f"Δ15m {_ctx_num(ctx.get(\'price_change_15m_pct\'))} · "\n'
        '                f"OI15 {_ctx_num(ctx.get(\'oi_change_15m_pct\'))} · "\n'
        '                f"fund {_ctx_num(ctx.get(\'funding_rate_pct\'), digits=4)} · "\n'
        '                f"L/S {_ctx_num(ctx.get(\'long_short_ratio\'), suffix=\'\', digits=2)} · "\n'
        '                f"ext {int(ctx.get(\'external_event_count\') or 0)}"\n'
        '            )\n\n'
    )
    s = replace_once(s, marker, block + marker, "telegram context line")
    path.write_text(s, encoding="utf-8")
    print("[OK] telegram_notify.py patched")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_context_24_7.py <ASTRA_PROJECT_DIR>")
    root = Path(sys.argv[1]).resolve()
    patch_api(root / "api.py")
    patch_telegram(root / "telegram_notify.py")


if __name__ == "__main__":
    main()

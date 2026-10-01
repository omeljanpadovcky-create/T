from pathlib import Path
import sys

MARKER = "MYSHKA_FASTTRACK_SHADOW_CTX_V1"

root = Path(sys.argv[1]).resolve()
p = root / "api.py"
if not p.exists():
    raise SystemExit("api.py not found")

s = p.read_text(encoding="utf-8")
if MARKER in s:
    print("[OK] fasttrack shadow ctx already installed")
    raise SystemExit(0)

old = '''        return {"action": "DROP" if jev.verdict == "REJECT" else "WAIT", "reason": "jev",
                "pair": req.pair, "signal": _clean(sig.as_dict()), "edge": _clean(edge.as_dict()) if edge else None,
                "jev": _clean(jev.as_dict()), "training": training_meta, "context": shadow_context}
'''

new = '''        # MYSHKA_FASTTRACK_SHADOW_CTX_V1
        # Diagnostic context only. It does NOT change the production signal,
        # JEV verdict, action, sizing, lock, guard, or routing.
        return {"action": "DROP" if jev.verdict == "REJECT" else "WAIT", "reason": "jev",
                "pair": req.pair, "signal": _clean(sig.as_dict()), "edge": _clean(edge.as_dict()) if edge else None,
                "jev": _clean(jev.as_dict()), "training": training_meta, "context": shadow_context,
                "fasttrack_shadow_ctx": {
                    "spread_pct": req.spread_pct,
                    "atr_pct": req.atr_pct,
                    "atr_pct_median": req.atr_pct_median,
                    "horizon_sec": req.horizon_sec,
                    "realized_pnl_today_pct": req.realized_pnl_today_pct,
                    "realized_pnl_this_week_pct": req.realized_pnl_this_week_pct,
                    "open_positions_count": len(req.open_positions),
                    "kill_switch_engaged": effective_kill,
                }}
'''

if old not in s:
    raise SystemExit("JEV return anchor not found; api.py left unchanged")

p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("[OK] installed", MARKER)

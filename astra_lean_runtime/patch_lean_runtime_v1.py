from pathlib import Path
import re
import sys

MARKER = "MYSHKA_LEAN_RUNTIME_V1"

DISABLE_SINGLE = {
    "evidence_gate_apply(results)",
    "adaptive_learner_apply(results)",
    "counterfactual_observe(results)",
    "risk_intelligence_observe(results)",
    "forward_experiment_observe(results)",
    "news_outcomes_observe(results)",
    "multihorizon_observe(results)",
    "binance_crosscheck_observe(results)",
    "external_market_observe(results)",
    "external_xcheck_observe(results)",
    "live_dry_run_observe(results)",
    "freqtrade_dryrun_observe(results)",
    "freqtrade_live_observe(results)",
}

def patch_api(root: Path) -> None:
    p = root / "api.py"
    s = p.read_text(encoding="utf-8-sig")
    compile(s, str(p), "exec")
    if MARKER in s:
        print("[OK] lean runtime already installed")
        return

    lines = s.splitlines(True)
    out = []
    disabled = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped in DISABLE_SINGLE:
            indent = line[:len(line)-len(line.lstrip())]
            out.append(f"{indent}# {MARKER}: disabled legacy runtime call: {stripped}\n")
            disabled.append(stripped)
            i += 1
            continue

        # hardening_observe is a multi-line diagnostic call.
        if stripped.startswith("hardening_observe(results, config_snapshot={"):
            indent = line[:len(line)-len(line.lstrip())]
            out.append(f"{indent}# {MARKER}: disabled hardening observer block\n")
            depth = line.count("(") + line.count("{") - line.count(")") - line.count("}")
            i += 1
            while i < len(lines) and depth > 0:
                depth += lines[i].count("(") + lines[i].count("{") - lines[i].count(")") - lines[i].count("}")
                i += 1
            disabled.append("hardening_observe")
            continue

        out.append(line)
        i += 1

    s2 = "".join(out)

    # Insert a visible marker near the first scan results assignment.
    anchor = '        results = out.get("results") or []\n'
    if anchor in s2:
        s2 = s2.replace(anchor, anchor + f"        # {MARKER}: only FastTrack execution observer remains active\n", 1)
    else:
        raise RuntimeError("scan results anchor not found")

    if "fasttrack_canary_observe(results)" not in s2:
        raise RuntimeError("FastTrack canary observer missing; refusing LEAN patch")

    compile(s2, str(p), "exec")
    p.write_text(s2, encoding="utf-8")
    print("[OK] installed", MARKER)
    print("[OK] disabled:", ", ".join(disabled))

if __name__ == "__main__":
    patch_api(Path(sys.argv[1]).resolve())

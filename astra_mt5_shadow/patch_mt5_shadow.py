from pathlib import Path
import ast
import re
import sys

API_MARKER = "MYSHKA_MT5_SHADOW_V1"
TG_MARKER = "MYSHKA_MT5_SHADOW_TG_V1"


def _insert_after_line(s: str, pattern: str, addition: str, label: str) -> str:
    m = re.search(pattern, s, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"{label} not found")
    return s[:m.end()] + addition + s[m.end():]


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if API_MARKER in s:
        print("[OK] api.py MT5 Shadow already present")
        return

    import_patterns = [
        r"^from \.external_market_shadow import .+\n",
        r"^from \.binance_signal_crosscheck import .+\n",
        r"^from \.multihorizon_shadow import .+\n",
    ]
    for pat in import_patterns:
        if re.search(pat, s, flags=re.MULTILINE):
            s = _insert_after_line(
                s, pat,
                "from .mt5_shadow_agent import init as mt5_shadow_init, status as mt5_shadow_status, report as mt5_shadow_report, observe_results as mt5_shadow_observe\n",
                "MT5 import anchor",
            )
            break
    else:
        raise RuntimeError("MT5 import anchor not found")

    init_patterns = [
        r"^[ \t]+external_market_init\(\)\n",
        r"^[ \t]+binance_crosscheck_init\(\)\n",
        r"^[ \t]+multihorizon_init\(\)\n",
    ]
    for pat in init_patterns:
        if re.search(pat, s, flags=re.MULTILINE):
            s = _insert_after_line(
                s, pat,
                f"    # {API_MARKER}\n    mt5_shadow_init()\n",
                "MT5 startup anchor",
            )
            break
    else:
        raise RuntimeError("MT5 startup anchor not found")

    health_patterns = [
        r'^[ \t]+"external_market_shadow":\s*external_market_status\(\),\n',
        r'^[ \t]+"binance_crosscheck":\s*binance_crosscheck_status\(\),\n',
        r'^[ \t]+"multihorizon_shadow":\s*multihorizon_status\(\),\n',
    ]
    for pat in health_patterns:
        if re.search(pat, s, flags=re.MULTILINE):
            s = _insert_after_line(
                s, pat,
                f'        # {API_MARKER}\n        "mt5_shadow": mt5_shadow_status(),\n',
                "MT5 health anchor",
            )
            break
    else:
        raise RuntimeError("MT5 health anchor not found")

    endpoints = (
        f'# {API_MARKER}\n'
        '@app.get("/mt5-shadow/status")\n'
        'def mt5_shadow_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return mt5_shadow_status()\n\n\n'
        '@app.get("/mt5-shadow/report")\n'
        'def mt5_shadow_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return mt5_shadow_report()\n\n\n'
    )
    route_anchors = [
        '@app.get("/external-market/status")\n',
        '@app.get("/forward-experiments/status")\n',
        '@app.get("/binance-crosscheck/status")\n',
    ]
    for anchor in route_anchors:
        if anchor in s:
            s = s.replace(anchor, endpoints + anchor, 1)
            break
    else:
        raise RuntimeError("MT5 endpoint anchor not found")

    observer_patterns = [
        r"^[ \t]+external_market_observe\(results\)\n",
        r"^[ \t]+binance_crosscheck_observe\(results\)\n",
        r"^[ \t]+multihorizon_observe\(results\)\n",
    ]
    for pat in observer_patterns:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]*", m.group(0)).group(0)
            addition = (
                f"{indent}# {API_MARKER}: MT5/Libertex read-only SHADOW only\n"
                f"{indent}mt5_shadow_observe(results)\n"
            )
            s = s[:m.end()] + addition + s[m.end():]
            break
    else:
        raise RuntimeError("MT5 observer anchor not found")

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: MT5 Shadow V1")


def _contains_final(node: ast.AST) -> bool:
    for x in ast.walk(node):
        if isinstance(x, ast.Constant) and isinstance(x.value, str) and "FINAL:" in x.value:
            return True
    return False


def patch_telegram(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if TG_MARKER in s:
        print("[OK] telegram_notify.py MT5 Shadow already present")
        return

    tree = ast.parse(s)
    target_func = None
    jev_if = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _contains_final(node):
            target_func = node
            for x in ast.walk(node):
                if isinstance(x, ast.If) and isinstance(x.test, ast.Name) and x.test.id == "jev":
                    jev_if = x
                    break
            if jev_if is not None:
                break

    if target_func is None or jev_if is None:
        raise RuntimeError("Telegram formatter/JEV insertion point not found")

    lines = s.splitlines(True)
    insert_at = jev_if.lineno - 1
    indent = " " * jev_if.col_offset

    block = [
        f"{indent}# {TG_MARKER}\n",
        f"{indent}_mt5 = r.get(\"mt5_shadow\") or {{}}\n",
        f"{indent}if _mt5:\n",
        f"{indent}    _mfr = _mt5.get(\"frames\") or {{}}\n",
        f"{indent}    _m5 = (_mfr.get(\"M5\") or {{}}).get(\"state\",\"—\")\n",
        f"{indent}    _m15 = (_mfr.get(\"M15\") or {{}}).get(\"state\",\"—\")\n",
        f"{indent}    _h1 = (_mfr.get(\"H1\") or {{}}).get(\"state\",\"—\")\n",
        f"{indent}    lines.append(\n",
        f"{indent}        \"MT5 XCHECK: \" + str(_mt5.get(\"state\",\"NO_DATA\")) +\n",
        f"{indent}        \" · \" + str(_mt5.get(\"alignment\",\"NO_DATA\")) +\n",
        f"{indent}        \" · M5 \" + str(_m5) + \" · M15 \" + str(_m15) + \" · H1 \" + str(_h1) +\n",
        f"{indent}        \" · \" + str(_mt5.get(\"symbol\") or \"—\")\n",
        f"{indent}    )\n",
        f"{indent}    _term = _mt5.get(\"terminal\") or {{}}\n",
        f"{indent}    _company = str(_term.get(\"company\") or \"\")\n",
        f"{indent}    _server = str(_term.get(\"server\") or \"\")\n",
        f"{indent}    if _company or _server:\n",
        f"{indent}        lines.append(\"MT5 SOURCE: \" + (_company or \"—\") + \" · \" + (_server or \"—\"))\n",
        f"{indent}    lines.append(\"MT5 STACK: \" + str(_mt5.get(\"stack_state\",\"MT5_NO_DATA\")))\n",
        "\n",
    ]

    lines[insert_at:insert_at] = block
    out = "".join(lines)
    compile(out, str(path), "exec")
    path.write_text(out, encoding="utf-8")
    print(f"[OK] telegram_notify.py patched in {target_func.name}: MT5 Shadow lines")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_mt5_shadow.py <ASTRA_PROJECT_DIR>")
    root = Path(sys.argv[1]).resolve()
    patch_api(root / "api.py")
    patch_telegram(root / "telegram_notify.py")


if __name__ == "__main__":
    main()

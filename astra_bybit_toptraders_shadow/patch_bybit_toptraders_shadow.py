from pathlib import Path
import re
import sys

MARKER = "MYSHKA_BYBIT_TOPTRADERS_SHADOW_V1"


def _insert_after_line(s: str, pattern: str, addition: str, label: str) -> str:
    m = re.search(pattern, s, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"{label} not found")
    return s[:m.end()] + addition + s[m.end():]


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig").lstrip("\ufeff")
    compile(s, str(path), "exec")
    changed = False

    imp = (
        "from .bybit_toptraders_shadow import init as bybit_toptraders_init, "
        "status as bybit_toptraders_status, report as bybit_toptraders_report, "
        "push as bybit_toptraders_push, consensus as bybit_toptraders_consensus, "
        "observe_results as bybit_toptraders_observe\n"
    )
    if "from .bybit_toptraders_shadow import" not in s:
        for pat in (
            r"^from \.binance_signal_crosscheck import .+\n",
            r"^from \.external_market_shadow import .+\n",
            r"^from \.fasttrack_paper_canary import .+\n",
        ):
            if re.search(pat, s, flags=re.MULTILINE):
                s = _insert_after_line(s, pat, imp, "import anchor")
                changed = True
                break
        else:
            raise RuntimeError("Bybit top-traders import anchor not found")

    if "bybit_toptraders_init()" not in s:
        for pat in (
            r"^[ \t]+binance_crosscheck_init\(\)\n",
            r"^[ \t]+external_market_init\(\)\n",
            r"^[ \t]+fasttrack_canary_init\(\)\n",
        ):
            m = re.search(pat, s, flags=re.MULTILINE)
            if m:
                indent = re.match(r"^[ \t]+", m.group(0)).group(0)
                s = s[:m.end()] + f"{indent}# {MARKER}\n{indent}bybit_toptraders_init()\n" + s[m.end():]
                changed = True
                break
        else:
            raise RuntimeError("Bybit top-traders startup anchor not found")

    if '"bybit_toptraders_shadow": bybit_toptraders_status(),' not in s:
        for pat in (
            r'^[ \t]+"binance_crosscheck":\s*binance_crosscheck_status\(\),\n',
            r'^[ \t]+"external_market_shadow":\s*external_market_status\(\),\n',
            r'^[ \t]+"fasttrack_paper_canary":\s*fasttrack_canary_status\(\),\n',
        ):
            m = re.search(pat, s, flags=re.MULTILINE)
            if m:
                indent = re.match(r"^[ \t]+", m.group(0)).group(0)
                s = s[:m.end()] + f'{indent}"bybit_toptraders_shadow": bybit_toptraders_status(),\n' + s[m.end():]
                changed = True
                break
        else:
            raise RuntimeError("Bybit top-traders health anchor not found")

    if '@app.post("/bybit-top-traders/push")' not in s:
        endpoints = (
            f'# {MARKER}\n'
            '@app.post("/bybit-top-traders/push")\n'
            'def bybit_toptraders_push_api(payload: dict, x_myshka_token: Optional[str] = Header(default=None)):\n'
            '    _require_token(x_myshka_token)\n'
            '    return bybit_toptraders_push(payload)\n\n\n'
            '@app.get("/bybit-top-traders/status")\n'
            'def bybit_toptraders_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
            '    _require_token(x_myshka_token)\n'
            '    return bybit_toptraders_status()\n\n\n'
            '@app.get("/bybit-top-traders/report")\n'
            'def bybit_toptraders_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
            '    _require_token(x_myshka_token)\n'
            '    return bybit_toptraders_report()\n\n\n'
            '@app.get("/bybit-top-traders/consensus/{pair:path}")\n'
            'def bybit_toptraders_consensus_api(pair: str, x_myshka_token: Optional[str] = Header(default=None)):\n'
            '    _require_token(x_myshka_token)\n'
            '    return bybit_toptraders_consensus(pair)\n\n\n'
        )
        for anchor in (
            '@app.get("/binance-crosscheck/status")\n',
            '@app.get("/external-market/status")\n',
            '@app.get("/fasttrack-canary/status")\n',
        ):
            if anchor in s:
                s = s.replace(anchor, endpoints + anchor, 1)
                changed = True
                break
        else:
            raise RuntimeError("Bybit top-traders endpoint anchor not found")

    if "bybit_toptraders_observe(results)" not in s:
        for pat in (
            r"^[ \t]+binance_crosscheck_observe\(results\)\n",
            r"^[ \t]+external_market_observe\(results\)\n",
            r"^[ \t]+fasttrack_canary_observe\(results\)\n",
        ):
            m = re.search(pat, s, flags=re.MULTILINE)
            if m:
                indent = re.match(r"^[ \t]*", m.group(0)).group(0)
                s = s[:m.end()] + (
                    f"{indent}# {MARKER}: SHADOW annotation only; never changes action\n"
                    f"{indent}bybit_toptraders_observe(results)\n"
                ) + s[m.end():]
                changed = True
                break
        else:
            raise RuntimeError("Bybit top-traders observer anchor not found")

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py Bybit Top Traders Shadow V1 " + ("patched" if changed else "already complete"))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_bybit_toptraders_shadow.py <ASTRA_PROJECT_DIR>")
    root = Path(sys.argv[1]).resolve()
    patch_api(root / "api.py")


if __name__ == "__main__":
    main()

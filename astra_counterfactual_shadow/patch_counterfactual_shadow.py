from pathlib import Path
import ast
import sys

MARKER = "MYSHKA_COUNTERFACTUAL_SHADOW_V1"


def replace_once(s: str, old: str, new: str, label: str) -> str:
    if old not in s:
        raise RuntimeError(f"patch target not found: {label}")
    return s.replace(old, new, 1)


def find_results_assignment_end_line(source: str) -> int:
    tree = ast.parse(source)
    fn = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_engine_step_unlocked":
            fn = node
            break
    if fn is None:
        raise RuntimeError("_engine_step_unlocked not found")

    candidates = []
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            else:
                targets = [node.target]
            for t in targets:
                if isinstance(t, ast.Name) and t.id == "results":
                    candidates.append(node)
    if not candidates:
        raise RuntimeError("results assignment not found inside _engine_step_unlocked")

    # Prefer the earliest assignment; normal engine obtains the full universe once per step.
    node = sorted(candidates, key=lambda x: x.lineno)[0]
    return int(getattr(node, "end_lineno", node.lineno))


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if MARKER in s:
        print("[OK] api.py already has Counterfactual SHADOW")
        return

    analytics_import = (
        "from .analytics_shadow import init as analytics_init, status as analytics_status, report as analytics_report, "
        "recent as analytics_recent, record_entry as analytics_record_entry, record_close as analytics_record_close, "
        "record_skip as analytics_record_skip\n"
    )
    cf_import = (
        "from .counterfactual_shadow import init as counterfactual_init, status as counterfactual_status, "
        "report as counterfactual_report, recent as counterfactual_recent, observe_results as counterfactual_observe\n"
    )
    s = replace_once(s, analytics_import, analytics_import + cf_import, "counterfactual import")

    s = replace_once(
        s,
        "    analytics_init()\n    _start_phone_threads()\n",
        f"    analytics_init()\n    # {MARKER}\n    counterfactual_init()\n    _start_phone_threads()\n",
        "startup counterfactual init",
    )

    s = replace_once(
        s,
        '        "analytics_shadow": analytics_status(),\n',
        '        "analytics_shadow": analytics_status(),\n        "counterfactual_shadow": counterfactual_status(),\n',
        "health counterfactual status",
    )

    analytics_recent_block = (
        '@app.get("/analytics/recent")\n'
        'def analytics_recent_api(limit: int = 50, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return {"status": "ok", "trades": analytics_recent(limit)}\n\n\n'
    )
    cf_endpoints = (
        '@app.get("/counterfactual/status")\n'
        'def counterfactual_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return counterfactual_status()\n\n\n'
        '@app.get("/counterfactual/report")\n'
        'def counterfactual_report_api(min_stage_n: int = 3, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return counterfactual_report(min_stage_n=min_stage_n)\n\n\n'
        '@app.get("/counterfactual/recent")\n'
        'def counterfactual_recent_api(limit: int = 50, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return {"status": "ok", "items": counterfactual_recent(limit)}\n\n\n'
    )
    s = replace_once(s, analytics_recent_block, analytics_recent_block + cf_endpoints, "counterfactual endpoints")

    # AST-guided insertion immediately after the normal scan results are produced.
    end_line = find_results_assignment_end_line(s)
    lines = s.splitlines(keepends=True)
    indent = "    "
    insertion = (
        f"{indent}# {MARKER}: observe rejected candidates using the same normal scan results\n"
        f"{indent}counterfactual_observe(results)\n"
    )
    lines.insert(end_line, insertion)
    s = "".join(lines)

    # Safety: never write a syntactically broken api.py.
    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Counterfactual SHADOW observer + API (no Telegram changes)")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_counterfactual_shadow.py <ASTRA_PROJECT_DIR>")
    root = Path(sys.argv[1]).resolve()
    patch_api(root / "api.py")


if __name__ == "__main__":
    main()

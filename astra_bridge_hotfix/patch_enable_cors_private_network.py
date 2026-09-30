from pathlib import Path
import ast
import sys

MARKER = "MYSHKA_CORS_ALLOW_PRIVATE_NETWORK_V2"


def _is_cors_add_middleware(node: ast.Call) -> bool:
    fn = node.func
    if not (
        isinstance(fn, ast.Attribute)
        and fn.attr == "add_middleware"
        and isinstance(fn.value, ast.Name)
        and fn.value.id == "app"
    ):
        return False
    if not node.args:
        return False
    first = node.args[0]
    return isinstance(first, ast.Name) and first.id == "CORSMiddleware"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if MARKER in s:
        print("[OK] CORSMiddleware private-network hotfix already present")
        return

    tree = ast.parse(s, filename=str(path))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _is_cors_add_middleware(n)]
    if not calls:
        raise RuntimeError("app.add_middleware(CORSMiddleware, ...) not found")

    # Patch each CORSMiddleware registration. In practice ASTRA has one.
    lines = s.splitlines(True)
    edits = []
    for call in calls:
        kw = next((k for k in call.keywords if k.arg == "allow_private_network"), None)
        if kw is not None:
            if not getattr(kw.value, "lineno", None) or not getattr(kw.value, "end_lineno", None):
                raise RuntimeError("Could not locate allow_private_network value")
            start = sum(len(x) for x in lines[:kw.value.lineno-1]) + kw.value.col_offset
            end = sum(len(x) for x in lines[:kw.value.end_lineno-1]) + kw.value.end_col_offset
            edits.append((start, end, "True"))
            continue

        # Insert immediately after the CORSMiddleware first argument.
        first = call.args[0]
        if not getattr(first, "end_lineno", None):
            raise RuntimeError("Could not locate CORSMiddleware argument")
        pos = sum(len(x) for x in lines[:first.end_lineno-1]) + first.end_col_offset
        edits.append((pos, pos, ", allow_private_network=True"))

    for start, end, repl in sorted(edits, reverse=True):
        s = s[:start] + repl + s[end:]

    # Marker is appended as a harmless comment only after successful source edit.
    s += "\n# " + MARKER + "\n"
    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] CORSMiddleware allow_private_network=True")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_enable_cors_private_network.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()

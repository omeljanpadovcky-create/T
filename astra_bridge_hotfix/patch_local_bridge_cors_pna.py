from pathlib import Path
import re
import sys

MARKER = "MYSHKA_LOCAL_BRIDGE_CORS_PNA_V1"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if MARKER in s:
        print("[OK] Local Bridge CORS/PNA hotfix already present")
        return

    # Ensure Response is importable for middleware responses if needed.
    # We deliberately avoid relying on a specific existing FastAPI import layout.
    inject_import = "from starlette.middleware.base import BaseHTTPMiddleware\n"
    if inject_import not in s:
        lines = s.splitlines(True)
        insert_at = 0
        for i, line in enumerate(lines):
            if line.startswith("from __future__ import"):
                insert_at = i + 1
        lines.insert(insert_at, inject_import)
        s = "".join(lines)

    app_match = re.search(r"(?m)^(\s*)app\s*=\s*FastAPI\([^\n]*\)\s*$", s)
    if not app_match:
        # Multiline FastAPI(...) fallback: insert after the first assignment block
        idx = s.find("app = FastAPI(")
        if idx < 0:
            raise RuntimeError("FastAPI app assignment not found")
        end = s.find("\n", idx)
        if end < 0:
            end = len(s)
        insert_pos = end + 1
    else:
        insert_pos = app_match.end() + 1

    middleware = f"""
# {MARKER}
class _MyshkaLocalBridgeCorsPnaMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        origin = request.headers.get("origin") or ""
        requested_private = (request.headers.get("access-control-request-private-network") or "").lower() == "true"

        # Handle browser preflight explicitly so HTTPS GitHub Pages can talk to localhost.
        if request.method.upper() == "OPTIONS":
            from starlette.responses import Response
            response = Response(status_code=204)
        else:
            response = await call_next(request)

        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type,X-MYSHKA-TOKEN"
            response.headers["Access-Control-Max-Age"] = "600"

        if requested_private or origin:
            response.headers["Access-Control-Allow-Private-Network"] = "true"

        return response

app.add_middleware(_MyshkaLocalBridgeCorsPnaMiddleware)
"""
    s = s[:insert_pos] + middleware + s[insert_pos:]

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: CORS + Private Network Access for localhost bridge")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_local_bridge_cors_pna.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()

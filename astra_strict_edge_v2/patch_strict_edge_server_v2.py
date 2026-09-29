from pathlib import Path
import sys

OLD_MARKER = "MYSHKA_STRICT_EDGE_BUFFER_005"
MARKER = "MYSHKA_STRICT_EDGE_PAYLOAD_V2"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_strict_edge_server_v2.py <api.py>")

    path = Path(sys.argv[1]).resolve()
    src = path.read_text(encoding="utf-8-sig")
    compile(src, str(path), "exec")

    if MARKER in src:
        print("[OK] STRICT EDGE server payload V2 already present")
        return
    if OLD_MARKER not in src:
        raise RuntimeError("STRICT EDGE +0.05 patch marker not found; aborting safely")

    lines = src.splitlines()
    marker_i = next((i for i, line in enumerate(lines) if OLD_MARKER in line), -1)
    if marker_i < 0:
        raise RuntimeError("STRICT EDGE marker location not found")

    cond_i = next(
        (i for i in range(marker_i, min(len(lines), marker_i + 30))
         if "if strict_4of4 and edge is not None and edge.net_edge_pct <= 0.05:" in lines[i]),
        -1,
    )
    if cond_i < 0:
        raise RuntimeError("STRICT EDGE condition not found near marker")

    indent = lines[cond_i][: len(lines[cond_i]) - len(lines[cond_i].lstrip(" \t"))]
    body = indent + "    "

    edge_i = next(
        (i for i in range(cond_i + 1, min(len(lines), cond_i + 25))
         if '"signal": _clean(sig.as_dict()), "edge": _clean(edge.as_dict()),' in lines[i]),
        -1,
    )
    training_i = next(
        (i for i in range(cond_i + 1, min(len(lines), cond_i + 25))
         if 'training_meta["strict_edge_min_pct"] = 0.05' in lines[i]),
        -1,
    )
    if edge_i < 0 or training_i < 0:
        raise RuntimeError("Expected STRICT EDGE return payload not found; aborting safely")

    payload_block = [
        body + "# " + MARKER,
        body + "edge_payload = _clean(edge.as_dict())",
        body + "if not isinstance(edge_payload, dict):",
        body + "    edge_payload = {}",
        body + 'edge_payload["passed"] = False',
        body + 'edge_payload["reason"] = "strict_edge_buffer"',
        body + 'edge_payload["min_required_net_edge_pct"] = 0.05',
    ]

    # Insert directly before training_meta so the payload belongs only to this
    # strict-buffer DROP branch.
    lines[training_i:training_i] = payload_block

    # Account for inserted lines when locating the return payload line.
    if edge_i >= training_i:
        edge_i += len(payload_block)

    old_line = lines[edge_i]
    line_indent = old_line[: len(old_line) - len(old_line.lstrip(" \t"))]
    lines[edge_i] = line_indent + '"signal": _clean(sig.as_dict()), "edge": edge_payload,'

    out = "\n".join(lines) + ("\n" if src.endswith("\n") else "")
    compile(out, str(path), "exec")
    path.write_text(out, encoding="utf-8")

    print("[OK] STRICT EDGE server payload now returns passed=false on strict buffer DROP")
    print("[OK] reason=strict_edge_buffer")
    print("[OK] min_required_net_edge_pct=0.05")


if __name__ == "__main__":
    main()

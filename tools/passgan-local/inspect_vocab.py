#!/usr/bin/env python
"""Inspect PassGAN's character vocabulary and generated text encoding."""
from __future__ import print_function

import argparse
import collections
import os
import pickle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--samples", required=True)
    args = parser.parse_args()

    inv_path = os.path.join(args.input_dir, "inv_charmap.pickle")
    map_path = os.path.join(args.input_dir, "charmap.pickle")
    for path in (inv_path, map_path, args.samples):
        if not os.path.isfile(path):
            raise SystemExit("Missing file: " + path)

    with open(inv_path, "rb") as handle:
        inv_charmap = pickle.load(handle, encoding="latin1")
    with open(map_path, "rb") as handle:
        charmap = pickle.load(handle, encoding="latin1")

    print("Character vocabulary inspection")
    print("Vocabulary size:", len(inv_charmap))
    print("Character map size:", len(charmap))
    print("First 80 inverse-map entries (repr):")
    for index, value in enumerate(inv_charmap[:80]):
        print("  {0}: {1}".format(index, repr(value)))
    unusual = []
    for index, value in enumerate(inv_charmap):
        if isinstance(value, str) and any(ord(ch) > 127 or ord(ch) < 32 or ord(ch) == 127 for ch in value):
            unusual.append((index, value))
    print("Non-ASCII/control vocabulary entries:", len(unusual))
    for index, value in unusual[:100]:
        print("  {0}: {1}".format(index, repr(value)))

    with open(args.samples, "rb") as handle:
        raw = handle.read()
    print("")
    print("Sample file bytes:", len(raw))
    try:
        decoded = raw.decode("utf-8")
        print("UTF-8 decode: OK")
    except UnicodeDecodeError as error:
        decoded = raw.decode("utf-8", "replace")
        print("UTF-8 decode: FAILED at byte", error.start, "-", str(error))

    lines = [line for line in decoded.splitlines() if line]
    non_ascii = sum(1 for line in lines if any(ord(ch) > 127 for ch in line))
    controls = [(i + 1, repr(line)) for i, line in enumerate(lines)
                if any((ord(ch) < 32 and ch not in "\t") or ord(ch) == 127 for ch in line)]
    replacement = sum(1 for ch in decoded if ch == "\ufffd")
    print("Non-empty lines:", len(lines))
    print("Lines with non-ASCII chars:", non_ascii)
    print("Lines with control chars:", len(controls))
    print("UTF-8 replacement characters:", replacement)
    if controls:
        print("Control-character line examples:")
        for line_no, value in controls[:10]:
            print("  line {0}: {1}".format(line_no, value))

    print("")
    print("Interpretation: non-ASCII symbols may be part of the model vocabulary.")
    print("This diagnostic does not assess password strength or model quality.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

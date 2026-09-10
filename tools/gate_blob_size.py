#!/usr/bin/env python3
"""gate_blob_size.py — fail the build if any tracked file exceeds 1 MB.

Why: ARCHITECTURE.md §0 — "Any file > 1 MB fails CI: no committed corpora."
gatekit is a stdlib-only harness; large binary blobs (datasets, media,
vendored archives) have no place in the repo and bloat every clone.

Usage:
    python3 tools/gate_blob_size.py [--root PATH] [--json]

Exit code: 0 if no findings, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

MAX_BYTES = 1024 * 1024
SKIP_DIR_NAMES = {".git"}


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def scan(root: pathlib.Path) -> list[dict]:
    findings: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_BYTES:
            rel = path.relative_to(root).as_posix()
            findings.append(
                {
                    "path": rel,
                    "line": 1,
                    "message": f"{size} bytes exceeds {MAX_BYTES} byte limit",
                }
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = pathlib.Path(args.root).resolve() if args.root else repo_root()
    findings = scan(root)

    if args.json:
        print(json.dumps({"verdict": "fail" if findings else "ok", "findings": findings}))
    else:
        for f in findings:
            print(f"{f['path']}:{f['line']}: {f['message']}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

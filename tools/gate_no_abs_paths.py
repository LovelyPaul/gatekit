#!/usr/bin/env python3
"""gate_no_abs_paths.py — fail the build if a tracked text file contains an
absolute personal filesystem path.

Why: a per-user home directory path baked into a committed file (under
/Users/<name>, /home/<name>, or the Windows Users folder equivalent) leaks
the author's local machine layout and breaks for every other contributor.
ARCHITECTURE.md §0 makes this a non-negotiable: "No absolute personal paths
anywhere in the repo."

This tool's own test fixtures are exempt (they intentionally contain such
paths to exercise the gate itself); everything else tracked in the repo,
except .git/ and binary files, is scanned.

Usage:
    python3 tools/gate_no_abs_paths.py [--root PATH] [--json]

Exit code: 0 if no findings, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

PATTERN = re.compile(r"(/Users/[A-Za-z0-9_.-]+|/home/[A-Za-z0-9_.-]+|C:\\Users\\)")

SKIP_DIR_NAMES = {".git"}

# Fixture directories/files that intentionally contain absolute paths as
# gate test data — never scanned for real violations.
FIXTURE_DIR_MARKERS = ("tests/fixtures", "test_tools_fixtures")
FIXTURE_FILE_NAMES = {"test_tools.py"}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mov", ".webp", ".pyc",
    ".so", ".dylib", ".dll", ".bin",
}


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def is_binary(path: pathlib.Path) -> bool:
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with path.open("rb") as fh:
            chunk = fh.read(8192)
    except OSError:
        return True
    return b"\x00" in chunk


def is_own_fixture(path: pathlib.Path, root: pathlib.Path) -> bool:
    rel = path.relative_to(root).as_posix()
    if not rel.startswith("tools/"):
        return False
    if path.name in FIXTURE_FILE_NAMES:
        return True
    return any(marker in rel for marker in FIXTURE_DIR_MARKERS)


def iter_tracked_files(root: pathlib.Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        yield path


def scan(root: pathlib.Path) -> list[dict]:
    findings: list[dict] = []
    for path in iter_tracked_files(root):
        if is_own_fixture(path, root):
            continue
        if is_binary(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(root).as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = PATTERN.search(line)
            if match:
                findings.append(
                    {
                        "path": rel,
                        "line": lineno,
                        "message": f"absolute personal path found: {match.group(0)}",
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

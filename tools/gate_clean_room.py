#!/usr/bin/env python3
"""gate_clean_room — this repository names no other project's vocabulary.

gatekit was written from scratch. Patterns like hook-enforced gates and
assumption ledgers are ordinary engineering practice and belong to nobody,
but the *names* another project coined do not belong here: importing them
would misrepresent where this code came from and invite a provenance
argument the code itself does not deserve.

The check is mechanical and deliberately narrow: it looks for a fixed list
of foreign project and plugin names in tracked text. It cannot judge whether
an idea was borrowed; it only keeps another project's vocabulary out of this
one's documentation and code.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

#: Foreign project, marketplace and plugin names. Matched case-insensitively
#: on word-ish boundaries so ordinary Korean/English prose is unaffected.
FORBIDDEN = [
    "gptaku", "fivetaku", "gptaku-plugins", "gptaku_doctor",
    "insane-search", "insane-design", "insane-research", "insane-review",
    "insane-crawl", "insane-slide", "insane-video", "insane-harness",
    "pumasi", "품앗이", "kkirikkiri", "끼리끼리", "goaljaby", "골잡이",
    "show-me-the-prd", "skillers-suda", "vibe-sunsang", "바선생",
    "git-teacher", "깃선생", "tikeytaka", "ddiring", "띠링", "gaseo", "nopal",
]

TEXT_SUFFIXES = {".md", ".py", ".json", ".yml", ".yaml", ".txt", ".sh", ".html", ".js"}
SKIP_DIRS = {".git", "__pycache__", ".gatekit", "node_modules", ".review"}
#: These files necessarily contain the names they police: the gate itself
#: holds the list, and its tests inject those names as fixtures.
EXEMPT = {"tools/gate_clean_room.py", "tools/test_tools.py"}


def _pattern() -> re.Pattern:
    alts = sorted((re.escape(t) for t in FORBIDDEN), key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(alts) + r")(?![A-Za-z0-9_-])", re.IGNORECASE)


def scan(root: pathlib.Path) -> list:
    findings = []
    pattern = _pattern()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if rel in EXEMPT or any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in pattern.finditer(line):
                findings.append({
                    "path": rel, "line": lineno,
                    "message": f"foreign project name '{match.group(1)}' — describe it in gatekit's own terms",
                })
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parent.parent))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    findings = scan(pathlib.Path(args.root).resolve())
    if args.json:
        print(json.dumps({"ok": not findings, "findings": findings}, ensure_ascii=False))
    else:
        for f in findings:
            print(f"{f['path']}:{f['line']}: {f['message']}")
        if not findings:
            print("gate_clean_room: ok")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

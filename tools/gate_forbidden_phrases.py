#!/usr/bin/env python3
"""gate_forbidden_phrases.py — keep execution steps out of skills, and keep
commands anchored to the policy/config vocabulary they must respect.

Why FORBIDDEN applies to plugin/skills/**: ARCHITECTURE.md §0 draws a hard
line — SKILL.md is a "≤ 40-line trigger shim", commands/*.md hold "the
execution instruction". If a skill starts embedding imperative step-by-step
instructions ("Step 1:", "EXECUTE IMMEDIATELY", "WHEN TRIGGERED"), the skill
has silently become a second, competing execution path that drifts from the
command file it's supposed to just point at. Grepping these phrases out of
skills is how that boundary stays enforced instead of just documented.

Why REQUIRED applies to plugin/commands/*.md: gates live in hooks, not
prose (CLAUDE.md), but commands still need to *tell the model* that gates
exist and that output language is not fixed. Every command must reference
policy/ (the runtime-loaded policy documents in plugin/policy/) at least
once, and must mention output_lang (the ledger field that controls which
language user-facing text is emitted in, per ARCHITECTURE.md §8). A command
missing either is not wired into the rest of the contract even if it reads
fine in isolation.

Usage:
    python3 tools/gate_forbidden_phrases.py [--root PATH] [--json]

Exit code: 0 if no findings, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

# Execution-step language that must never appear inside a skill shim.
FORBIDDEN_IN_SKILLS: list[tuple[str, re.Pattern[str]]] = [
    ("EXECUTE IMMEDIATELY", re.compile(r"EXECUTE IMMEDIATELY", re.IGNORECASE)),
    ("WHEN TRIGGERED", re.compile(r"WHEN TRIGGERED", re.IGNORECASE)),
    ("numbered execution step (e.g. 'Step 1:')", re.compile(r"^\s*Step\s+\d+\s*:", re.IGNORECASE | re.MULTILINE)),
]

# Tokens every command file must reference at least once.
REQUIRED_IN_COMMANDS: list[tuple[str, re.Pattern[str]]] = [
    ("policy/", re.compile(r"policy/")),
    ("output_lang", re.compile(r"output_lang")),
]


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def scan(root: pathlib.Path) -> list[dict]:
    findings: list[dict] = []

    for skill_md in sorted((root / "plugin" / "skills").glob("*/SKILL.md")):
        rel = skill_md.relative_to(root).as_posix()
        text = skill_md.read_text(encoding="utf-8")
        lines = text.splitlines()
        for label, pattern in FORBIDDEN_IN_SKILLS:
            for lineno, line in enumerate(lines, start=1):
                if pattern.search(line):
                    findings.append(
                        {
                            "path": rel,
                            "line": lineno,
                            "message": f"forbidden execution-step phrase in skill: {label}",
                        }
                    )

    for cmd_md in sorted((root / "plugin" / "commands").glob("*.md")):
        rel = cmd_md.relative_to(root).as_posix()
        text = cmd_md.read_text(encoding="utf-8")
        for label, pattern in REQUIRED_IN_COMMANDS:
            if not pattern.search(text):
                findings.append(
                    {
                        "path": rel,
                        "line": 1,
                        "message": f"command must reference '{label}' at least once",
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

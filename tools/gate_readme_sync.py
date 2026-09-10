#!/usr/bin/env python3
"""gate_readme_sync.py — keep README.md and README.ko.md in sync with the
actual set of shipped commands.

Why: ARCHITECTURE.md §1 lists one command file per pipeline stage under
plugin/commands/, each invoked as `/gatekit:<name>`. Both READMEs document
that command list for humans (English primary, Korean translation). If a
command is added, renamed, or removed and only one of the two READMEs (or
neither) is updated, users following the Korean doc get a different picture
of the tool than users following the English one. This gate treats
plugin/commands/*.md as the source of truth and fails if either README's
`/gatekit:<name>` mentions don't match that set exactly.

Usage:
    python3 tools/gate_readme_sync.py [--root PATH] [--json]

Exit code: 0 if no findings, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

COMMAND_REF_RE = re.compile(r"/gatekit:([A-Za-z0-9_-]+)")


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def actual_commands(root: pathlib.Path) -> set[str]:
    commands_dir = root / "plugin" / "commands"
    if not commands_dir.is_dir():
        return set()
    return {p.stem for p in commands_dir.glob("*.md")}


def referenced_commands(path: pathlib.Path) -> set[str]:
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8")
    return set(COMMAND_REF_RE.findall(text))


def scan(root: pathlib.Path) -> list[dict]:
    findings: list[dict] = []
    expected = actual_commands(root)

    for readme_name in ("README.md", "README.ko.md"):
        path = root / readme_name
        rel = readme_name
        if not path.is_file():
            findings.append({"path": rel, "line": 1, "message": f"{readme_name} is missing"})
            continue

        found = referenced_commands(path)
        missing = sorted(expected - found)
        extra = sorted(found - expected)

        for name in missing:
            findings.append(
                {"path": rel, "line": 1, "message": f"missing reference to /gatekit:{name}"}
            )
        for name in extra:
            findings.append(
                {
                    "path": rel,
                    "line": 1,
                    "message": f"references /gatekit:{name} which has no plugin/commands/{name}.md",
                }
            )

    if (root / "README.md").is_file() and (root / "README.ko.md").is_file():
        en_set = referenced_commands(root / "README.md")
        ko_set = referenced_commands(root / "README.ko.md")
        if en_set != ko_set:
            only_en = sorted(en_set - ko_set)
            only_ko = sorted(ko_set - en_set)
            if only_en:
                findings.append(
                    {
                        "path": "README.ko.md",
                        "line": 1,
                        "message": f"missing commands present in README.md: {', '.join(only_en)}",
                    }
                )
            if only_ko:
                findings.append(
                    {
                        "path": "README.md",
                        "line": 1,
                        "message": f"missing commands present in README.ko.md: {', '.join(only_ko)}",
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

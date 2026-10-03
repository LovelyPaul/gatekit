#!/usr/bin/env python3
"""gate_skill_size.py — enforce the skill/command size and tool-allowlist split.

Why the line limits: ARCHITECTURE.md §0 makes SKILL.md a "≤ 40-line trigger
shim" whose only job is to point at the corresponding command file, which
holds the real execution instructions (commands/*.md, capped at 160 lines).
Letting either grow without bound turns the command/skill split back into
two competing products with duplicated, drifting instructions.

Why AskUserQuestion is forbidden in allowed-tools: a command or skill is
invoked by the harness with its frontmatter tool list already granted —
those tools run auto-approved, with no interactive confirmation step. If
AskUserQuestion is declared there, the model believes it can pause and ask
the user something, but the question UI never renders (there is no human
turn waiting on it); the call either hangs or silently no-ops. Interactive
questions belong in the command's own scripted flow (see policy/), never in
a static allowed-tools grant.

Why a shim that duplicates a command must say `user-invocable: false`
(ADR-0026 D2): Claude Code lists every command and every skill in the `/`
menu, so each command appeared twice (`/gatekit:build` and
`/gatekit:gatekit-build`). The key hides the shim from the menu while the
model can still invoke it; Codex ignores the key and still loads the skill.
A shim duplicates a command when its folder is named after the command,
alone or after a `<prefix>-`.

Usage:
    python3 tools/gate_skill_size.py [--root PATH] [--json]

Exit code: 0 if no findings, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

SKILL_MAX_LINES = 40
COMMAND_MAX_LINES = 160

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
# Matches `allowed-tools: Foo, Bar` (inline) and the following indented/dash
# lines of a YAML block-list form:
#   allowed-tools:
#     - Foo
#     - Bar
ALLOWED_TOOLS_INLINE_RE = re.compile(r"(?im)^allowed-tools:\s*(.+)$")
ALLOWED_TOOLS_BLOCK_RE = re.compile(
    r"(?im)^allowed-tools:\s*\n((?:^[ \t]*-.*\n?)+)"
)
USER_INVOCABLE_FALSE_RE = re.compile(r"(?m)^user-invocable:\s*false\s*$")


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def extract_frontmatter(text: str) -> str:
    match = FRONTMATTER_RE.match(text)
    return match.group(1) if match else ""


def frontmatter_lists_ask_user_question(text: str) -> bool:
    fm = extract_frontmatter(text)
    if not fm:
        return False

    inline = ALLOWED_TOOLS_INLINE_RE.search(fm)
    if inline:
        value = inline.group(1).strip()
        if not value.startswith("|") and not value.startswith(">"):
            # Inline scalar or flow list, e.g. "Read, AskUserQuestion, Bash"
            # or "[Read, AskUserQuestion]".
            if "AskUserQuestion" in value:
                return True
            # If it's a scalar (not a flow list) and doesn't contain a colon
            # implying the next key, still just check substring above.

    block = ALLOWED_TOOLS_BLOCK_RE.search(fm)
    if block:
        for line in block.group(1).splitlines():
            item = line.strip().lstrip("-").strip()
            if item == "AskUserQuestion":
                return True

    return False


def count_lines(path: pathlib.Path) -> int:
    text = path.read_text(encoding="utf-8")
    if text == "":
        return 0
    # A trailing newline shouldn't count as an extra blank line.
    return len(text.splitlines())


def duplicates_a_command(skill_dir: str, commands: set[str]) -> bool:
    return skill_dir in commands or any(skill_dir.endswith("-" + c) for c in commands)


def scan(root: pathlib.Path) -> list[dict]:
    findings: list[dict] = []
    commands = {p.stem for p in (root / "plugin" / "commands").glob("*.md")}

    for skill_md in sorted((root / "plugin" / "skills").glob("*/SKILL.md")):
        rel = skill_md.relative_to(root).as_posix()
        n = count_lines(skill_md)
        if n > SKILL_MAX_LINES:
            findings.append(
                {
                    "path": rel,
                    "line": SKILL_MAX_LINES + 1,
                    "message": f"SKILL.md has {n} lines, exceeds max {SKILL_MAX_LINES}",
                }
            )
        text = skill_md.read_text(encoding="utf-8")
        if frontmatter_lists_ask_user_question(text):
            findings.append(
                {
                    "path": rel,
                    "line": 1,
                    "message": (
                        "allowed-tools lists AskUserQuestion: auto-approved "
                        "tool grants never render the question UI"
                    ),
                }
            )
        if duplicates_a_command(skill_md.parent.name, commands) and not \
                USER_INVOCABLE_FALSE_RE.search(extract_frontmatter(text)):
            findings.append(
                {
                    "path": rel,
                    "line": 1,
                    "message": (
                        "shim of a command lacks `user-invocable: false`: "
                        "the / menu would list the command twice (ADR-0026 D2)"
                    ),
                }
            )

    for cmd_md in sorted((root / "plugin" / "commands").glob("*.md")):
        rel = cmd_md.relative_to(root).as_posix()
        n = count_lines(cmd_md)
        if n > COMMAND_MAX_LINES:
            findings.append(
                {
                    "path": rel,
                    "line": COMMAND_MAX_LINES + 1,
                    "message": f"command has {n} lines, exceeds max {COMMAND_MAX_LINES}",
                }
            )
        text = cmd_md.read_text(encoding="utf-8")
        if frontmatter_lists_ask_user_question(text):
            findings.append(
                {
                    "path": rel,
                    "line": 1,
                    "message": (
                        "allowed-tools lists AskUserQuestion: auto-approved "
                        "tool grants never render the question UI"
                    ),
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

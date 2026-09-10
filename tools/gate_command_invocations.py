#!/usr/bin/env python3
"""gate_command_invocations — every kernel call in a command must actually run.

Command files are executed from the *user's* project directory, where the
``gatekit`` package is not importable. The only invocation form that works
there is the launcher::

    python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" <subcommand> ...

This gate fails the build when a command or policy file uses a form that
breaks at runtime (``python3 -m gatekit``, or ``cd "${CLAUDE_PLUGIN_ROOT}"``
which retargets relative paths into the plugin), or names a subcommand that
``plugin/gatekit/cli.py`` does not register. It exists because an earlier
draft shipped 29 unrunnable invocations that read correctly and passed every
other gate.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

LAUNCHER_RE = re.compile(r'python3 "\$\{CLAUDE_PLUGIN_ROOT\}/bin/gatekit\.py" ([a-z-]+)')
BAD_FORMS = [
    (re.compile(r"python3 -m gatekit"), "use the launcher: python3 \"${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py\" <sub>"),
    (re.compile(r'cd "\$\{CLAUDE_PLUGIN_ROOT\}"'), "never cd into the plugin; run from the project directory"),
]
SUBCOMMANDS_RE = re.compile(r'^\s*"([a-z-]+)":\s*\("gatekit\.', re.MULTILINE)


def registered_subcommands(root: pathlib.Path) -> set:
    cli = root / "plugin" / "gatekit" / "cli.py"
    if not cli.is_file():
        return set()
    return set(SUBCOMMANDS_RE.findall(cli.read_text(encoding="utf-8")))


def scan(root: pathlib.Path) -> list:
    findings = []
    subs = registered_subcommands(root)
    files = sorted((root / "plugin" / "commands").glob("*.md")) + sorted((root / "plugin" / "policy").glob("*.md"))
    for path in files:
        rel = path.relative_to(root).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern, message in BAD_FORMS:
                if pattern.search(line):
                    findings.append({"path": rel, "line": lineno, "message": message})
            for sub in LAUNCHER_RE.findall(line):
                if subs and sub not in subs:
                    findings.append({"path": rel, "line": lineno,
                                     "message": f"subcommand '{sub}' is not registered in cli.py"})
    launcher = root / "plugin" / "bin" / "gatekit.py"
    if not launcher.is_file() or launcher.stat().st_size == 0:
        findings.append({"path": "plugin/bin/gatekit.py", "line": 0, "message": "launcher missing or empty"})
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
            print("gate_command_invocations: ok")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

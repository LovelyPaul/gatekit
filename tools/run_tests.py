#!/usr/bin/env python3
"""run_tests.py — single entry point for the full gatekit test suite.

Runs the plugin's own unittest suite (plugin/tests/, via unittest discover)
followed by the CI gate self-tests (tools/test_tools.py), and prints one
summary line so CI and humans can grep a single pass/fail signal:

    tests: ok
    tests: fail

Usage:
    python3 tools/run_tests.py [--root PATH]

Exit code: 0 if both suites pass, 1 otherwise.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys


def repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: pathlib.Path) -> int:
    print(f"$ {' '.join(cmd)}  (cwd={cwd})")
    proc = subprocess.run(cmd, cwd=str(cwd))
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)

    root = pathlib.Path(args.root).resolve() if args.root else repo_root()

    plugin_dir = root / "plugin"
    plugin_tests_dir = plugin_dir / "tests"
    ok = True

    if plugin_tests_dir.is_dir():
        # cwd must be plugin/ so that `from gatekit import ...` resolves
        # (gatekit is a top-level package under plugin/, not under repo
        # root) — see plugin/tests/test_lang.py's own subprocess check of
        # `python3 -m gatekit ...` with cwd=plugin.
        rc = run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=plugin_dir,
        )
        ok = ok and rc == 0
    else:
        print(f"plugin/tests not found under {root}, skipping plugin unittest discovery")

    test_tools_path = root / "tools" / "test_tools.py"
    if test_tools_path.is_file():
        rc = run([sys.executable, str(test_tools_path), "-v"], cwd=root)
        ok = ok and rc == 0
    else:
        print(f"{test_tools_path} not found, skipping gate self-tests")
        ok = False

    print(f"tests: {'ok' if ok else 'fail'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

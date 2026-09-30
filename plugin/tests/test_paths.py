"""Tests for gatekit.paths — project root and state directory resolution."""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import paths


class TempProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # realpath: macOS /var -> /private/var symlink would break comparisons.
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestProjectRoot(TempProject):
    def test_finds_ancestor_with_gatekit_dir(self) -> None:
        (self.root / ".gatekit").mkdir()
        deep = self.root / "src" / "auth" / "nested"
        deep.mkdir(parents=True)
        self.assertEqual(paths.project_root(str(deep)), self.root)

    def test_finds_ancestor_with_git_dir(self) -> None:
        (self.root / ".git").mkdir()
        deep = self.root / "a" / "b"
        deep.mkdir(parents=True)
        self.assertEqual(paths.project_root(str(deep)), self.root)

    def test_gatekit_marker_wins_over_higher_git(self) -> None:
        (self.root / ".git").mkdir()
        inner = self.root / "packages" / "app"
        inner.mkdir(parents=True)
        (inner / ".gatekit").mkdir()
        self.assertEqual(paths.project_root(str(inner)), inner)

    def test_falls_back_to_cwd_when_no_marker(self) -> None:
        deep = self.root / "no" / "markers"
        deep.mkdir(parents=True)
        self.assertEqual(paths.project_root(str(deep)), deep)

    def test_none_uses_process_cwd(self) -> None:
        (self.root / ".gatekit").mkdir()
        previous = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertEqual(paths.project_root(None), self.root)
        finally:
            os.chdir(previous)

    def test_nonexistent_cwd_does_not_raise(self) -> None:
        missing = self.root / "gone"
        self.assertIsInstance(paths.project_root(str(missing)), pathlib.Path)


class TestDerivedDirs(TempProject):
    def test_state_dir(self) -> None:
        self.assertEqual(paths.state_dir(self.root), self.root / ".gatekit")

    def test_spec_dir(self) -> None:
        self.assertEqual(paths.spec_dir(self.root), self.root / "spec")

    def test_runs_dir_and_hook_error_log(self) -> None:
        self.assertEqual(paths.runs_dir(self.root), self.root / ".gatekit" / "runs")
        self.assertEqual(
            paths.hook_error_log(self.root),
            self.root / ".gatekit" / "runs" / "hook-errors.log",
        )

    def test_jobs_dir(self) -> None:
        self.assertEqual(paths.jobs_dir(self.root), self.root / ".gatekit" / "jobs")

    def test_plugin_root_contains_plugin_json(self) -> None:
        found = paths.plugin_root()
        self.assertTrue((found / ".claude-plugin" / "plugin.json").is_file())

    def test_expand_argv_replaces_plugin_root_token(self) -> None:
        # ADR-0018 decision 1: argv runs without a shell, so gatekit expands
        # the one token task-gates.md documents before subprocess.run sees it.
        root = str(paths.plugin_root())
        out = paths.expand_argv(
            ["python3", "${CLAUDE_PLUGIN_ROOT}/gatekit/gates/tokens.py", "src/**"]
        )
        # argv[0] may be resolved to a full path (ADR-0019 decision 3c).
        self.assertEqual(out[1:], [root + "/gatekit/gates/tokens.py", "src/**"])

    def test_expand_argv_touches_nothing_else(self) -> None:
        argv = ["echo", "$HOME", "~/x", "${OTHER}", "*.ts"]
        self.assertEqual(paths.expand_argv(argv)[1:], argv[1:])

    def test_expand_argv_returns_a_new_list(self) -> None:
        argv = ["${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py"]
        paths.expand_argv(argv)
        self.assertEqual(argv, ["${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py"])

    def test_ensure_dir_is_idempotent(self) -> None:
        target = self.root / "x" / "y"
        paths.ensure_dir(target)
        paths.ensure_dir(target)
        self.assertTrue(target.is_dir())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

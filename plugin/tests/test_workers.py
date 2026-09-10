"""Tests for gatekit.workers — backend registry, unsafe-flag rule, probes."""
from __future__ import annotations

import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import config, verdict, workers


def write_config(root: pathlib.Path, cfg: dict) -> None:
    state = root / ".gatekit"
    state.mkdir(parents=True, exist_ok=True)
    (state / "config.json").write_text(json.dumps(cfg), encoding="utf-8")


def make_stub_binary(directory: pathlib.Path, name: str, exit_code: int = 0,
                     body: str = "stub 1.2.3") -> pathlib.Path:
    """A tiny shell script that prints `body` and exits `exit_code`."""
    path = directory / name
    path.write_text("#!/bin/sh\necho '%s'\nexit %d\n" % (body, exit_code), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class WorkerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        self._bin = tempfile.TemporaryDirectory()
        self.bindir = pathlib.Path(os.path.realpath(self._bin.name))
        self._old_path = os.environ.get("PATH", "")
        # PATH is *replaced*, not prepended: a real `claude` or `codex` on the
        # developer's machine must not decide the outcome of these tests.
        os.environ["PATH"] = str(self.bindir)

    def tearDown(self) -> None:
        os.environ["PATH"] = self._old_path
        self._bin.cleanup()
        self._tmp.cleanup()


class TestResolve(WorkerTestCase):
    def test_default_is_claude_with_documented_argv(self) -> None:
        backend = workers.resolve(self.root)
        self.assertEqual(backend["name"], "claude")
        self.assertEqual(backend["argv"][:2], ["claude", "-p"])
        self.assertIn("--output-format", backend["argv"])
        self.assertIn("--permission-mode", backend["argv"])
        self.assertFalse(backend["unsafe"])

    def test_codex_is_disabled_by_default(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            workers.resolve(self.root, "codex")
        self.assertIn("disabled", str(ctx.exception))

    def test_codex_argv_uses_workspace_write_sandbox(self) -> None:
        argv = config.DEFAULTS["worker"]["backends"]["codex"]["argv"]
        self.assertEqual(argv, ["codex", "exec", "--sandbox", "workspace-write"])

    def test_unknown_backend_raises(self) -> None:
        with self.assertRaises(ValueError):
            workers.resolve(self.root, "nope")

    def test_empty_argv_raises(self) -> None:
        write_config(self.root, {"worker": {"backends": {"bad": {"argv": [], "enabled": True}}}})
        with self.assertRaises(ValueError):
            workers.resolve(self.root, "bad")

    def test_bypass_flag_without_unsafe_raises(self) -> None:
        for flag in ("--dangerously-skip-permissions", "--permission-mode=bypassPermissions",
                     "--yolo"):
            write_config(self.root, {"worker": {"backends": {
                "risky": {"argv": ["claude", flag], "enabled": True}}}})
            with self.assertRaises(ValueError, msg=flag) as ctx:
                workers.resolve(self.root, "risky")
            self.assertIn("bypass", str(ctx.exception))

    def test_bypass_flag_with_unsafe_true_resolves(self) -> None:
        write_config(self.root, {"worker": {"backends": {"risky": {
            "argv": ["claude", "--dangerously-skip-permissions"],
            "enabled": True, "unsafe": True}}}})
        backend = workers.resolve(self.root, "risky")
        self.assertTrue(backend["unsafe"])


class TestCheck(WorkerTestCase):
    def test_missing_executable_is_fail(self) -> None:
        result = workers.check(self.root, "claude")
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("PATH", result["detail"])

    def test_present_executable_with_version_is_ok(self) -> None:
        make_stub_binary(self.bindir, "claude", 0, "1.2.3 (Claude Code)")
        result = workers.check(self.root, "claude")
        self.assertEqual(result["verdict"], verdict.OK)
        self.assertIn("1.2.3", result["detail"])

    def test_failing_version_probe_is_unverified_not_fail(self) -> None:
        make_stub_binary(self.bindir, "claude", 3, "boom")
        result = workers.check(self.root, "claude")
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)

    def test_unknown_backend_is_fail(self) -> None:
        self.assertEqual(workers.check(self.root, "ghost")["verdict"], verdict.FAIL)


class TestCli(WorkerTestCase):
    def test_list_json_marks_default_and_states(self) -> None:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(workers.run(["list", "--json", "--root", str(self.root)]), 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["default"], "claude")
        by_name = {b["name"]: b for b in payload["backends"]}
        self.assertTrue(by_name["claude"]["enabled"])
        self.assertFalse(by_name["codex"]["enabled"])

    def test_enable_then_set_default_persists(self) -> None:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workers.run(["enable", "codex", "--root", str(self.root)]), 0)
            self.assertEqual(workers.run(["set-default", "codex", "--root", str(self.root)]), 0)
        cfg = config.load(self.root)
        self.assertTrue(cfg["worker"]["backends"]["codex"]["enabled"])
        self.assertEqual(cfg["worker"]["default"], "codex")
        self.assertEqual(workers.resolve(self.root)["name"], "codex")

    def test_enable_refuses_unsafe_backend_without_opt_in(self) -> None:
        import contextlib
        import io

        write_config(self.root, {"worker": {"backends": {
            "risky": {"argv": ["claude", "--dangerously-skip-permissions"], "enabled": False}}}})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = workers.run(["enable", "risky", "--root", str(self.root)])
        self.assertEqual(code, 2)
        self.assertFalse(config.load(self.root)["worker"]["backends"]["risky"]["enabled"])

    def test_check_missing_binary_exits_1(self) -> None:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(workers.run(["check", "claude", "--root", str(self.root)]), 1)


if __name__ == "__main__":
    unittest.main()

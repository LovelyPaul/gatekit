"""ADR-0019 decision 2: the same plugin/ tree installs as a Codex plugin."""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import doctor, hookio, hosts, verdict  # noqa: E402

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[1]


def plugin_hooks() -> dict:
    return json.loads((PLUGIN_DIR / "hooks" / "hooks.json").read_text(encoding="utf-8"))


def matcher_for(event: str, script: str) -> str:
    for entry in plugin_hooks()["hooks"][event]:
        if any(script in h["command"] for h in entry["hooks"]):
            return entry.get("matcher", "")
    raise AssertionError("%s not registered on %s" % (script, event))


class TestHooksServeCodexTools(unittest.TestCase):
    """2a: Codex's own tool names reach the same gates."""

    def test_write_gate_sees_apply_patch(self) -> None:
        self.assertIn("apply_patch", matcher_for("PreToolUse", "gates/write.py").split("|"))

    def test_spawn_gate_sees_codex_spawn(self) -> None:
        self.assertIn(
            "collaborationspawn_agent", matcher_for("PreToolUse", "gates/spawn.py").split("|")
        )

    def test_claude_tool_names_kept(self) -> None:
        self.assertIn("Write", matcher_for("PreToolUse", "gates/write.py").split("|"))
        self.assertIn("Agent", matcher_for("PreToolUse", "gates/spawn.py").split("|"))


class TestHostFromEnvironment(unittest.TestCase):
    """2b: with no --host flag, Codex is recognised by PLUGIN_ROOT."""

    def test_plugin_root_env_means_codex(self) -> None:
        self.assertEqual(hookio.host_from_argv([], env={"PLUGIN_ROOT": "/p"}), "codex")

    def test_claude_env_means_claude(self) -> None:
        self.assertEqual(hookio.host_from_argv([], env={"CLAUDE_PLUGIN_ROOT": "/p"}), "claude")

    def test_flag_beats_environment(self) -> None:
        self.assertEqual(
            hookio.host_from_argv(["--host", "claude"], env={"PLUGIN_ROOT": "/p"}), "claude"
        )

    def test_empty_plugin_root_is_not_evidence(self) -> None:
        self.assertEqual(hookio.host_from_argv([], env={"PLUGIN_ROOT": ""}), "claude")


class TestHostNeutralSkills(unittest.TestCase):
    """2c: every shim tells a host without slash commands where the command is."""

    def commands(self) -> list:
        return sorted(p.stem for p in (PLUGIN_DIR / "commands").glob("*.md"))

    def test_every_command_has_a_skill(self) -> None:
        skills = {p.name for p in (PLUGIN_DIR / "skills").iterdir() if p.is_dir()}
        self.assertEqual(skills, {"gatekit-" + c for c in self.commands()})

    def test_shim_names_the_command_file_relative_to_the_plugin(self) -> None:
        for name in self.commands():
            text = (PLUGIN_DIR / "skills" / ("gatekit-" + name) / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("`/gatekit:%s`" % name, text, name)
            self.assertIn("commands/%s.md" % name, text, name)
            self.assertIn("policy/codex.md", text, name)
            self.assertLessEqual(len(text.splitlines()), 40, name)

    def test_codex_policy_exists_and_covers_the_differences(self) -> None:
        text = (PLUGIN_DIR / "policy" / "codex.md").read_text(encoding="utf-8")
        for needle in ("${CLAUDE_PLUGIN_ROOT}", "AskUserQuestion", "$gatekit-", "/hooks"):
            self.assertIn(needle, text)


class TestDoctorReportsCodexPluginTrust(unittest.TestCase):
    """2d: an installed Codex plugin whose hooks are untrusted is a visible warn."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(os.path.realpath(self._tmp.name))
        self.codex_home = base / "codex-home"
        self.root = base / "project"
        (self.root / ".gatekit").mkdir(parents=True)
        self._old = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = str(self.codex_home)

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = self._old
        self._tmp.cleanup()

    def install_plugin(self) -> pathlib.Path:
        hooks = self.codex_home / "plugins" / "cache" / "gatekit" / "gatekit" / "9.9.9" / "hooks" / "hooks.json"
        hooks.parent.mkdir(parents=True)
        hooks.write_text("{}", encoding="utf-8")
        return hooks

    def write_config(self, text: str) -> None:
        self.codex_home.mkdir(parents=True, exist_ok=True)
        (self.codex_home / "config.toml").write_text(text, encoding="utf-8")

    def test_no_codex_plugin_is_not_a_finding(self) -> None:
        self.assertIsNone(hosts.codex_plugin_trust())

    def test_installed_but_untrusted_warns_with_terminal_fix(self) -> None:
        self.install_plugin()
        self.write_config("[plugins.\"gatekit@gatekit\"]\nenabled = true\n")
        result = doctor.axis_host_layer(self.root)
        self.assertEqual(result["verdict"], verdict.WARN)
        self.assertIn("/hooks", result["fix"])

    def test_installed_and_trusted_is_ok(self) -> None:
        hooks = self.install_plugin()
        self.write_config(
            '[hooks.state.%s]\ntrusted_hash = "abc"\n' % json.dumps(str(hooks) + ":pre_tool_use:0:0")
        )
        self.assertTrue(hosts.codex_plugin_trust())
        self.assertEqual(doctor.axis_host_layer(self.root)["verdict"], verdict.OK)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

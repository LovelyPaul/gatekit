"""ADR-0029 amendment: the session cannot make the Stop and question gates
stand down by enabling the legacy plugin itself.

Review finding (plausible after the rename): ``legacy_plugin_enabled`` read
the project's ``.claude/settings.local.json``, which the model can write, and
was re-read at every Stop. Now only the user's own settings enable the
legacy plugin (a project file may only switch it off), its plugin cache
directory must exist, and the answer is taken once, at the session's first
prompt, into the ledger; the Stop and question gates read that snapshot only.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_names_compat import PY, Temp, _fenced  # noqa: E402

from gatekit import approval, contract, ledger, names  # noqa: E402
from gatekit.gates import prompt as prompt_gate  # noqa: E402
from gatekit.gates import question as question_gate  # noqa: E402
from gatekit.gates import stop as stop_gate  # noqa: E402


class Legacy(Temp):
    def setUp(self) -> None:
        super().setUp()
        self.home = self.fake_home()
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        self.user_settings({"gatebound@gatebound": True})
        (self.home / ".claude" / "plugins" / "installed_plugins.json").write_text(
            json.dumps({"version": 2, "plugins": {"gatekit@gatekit": {}, "gatebound@gatebound": {}}}),
            encoding="utf-8")
        crit = {"id": "bad", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20}
        (self.root / "spec" / "05-gate.md").write_text(_fenced("gatekit", "criterion", crit),
                                                       encoding="utf-8")
        contract.derive(self.root)
        approval.approve(self.root, "spec/05-gate.md")
        led = ledger.Ledger.load(self.root, "s")
        led.data["active_pipeline"] = "build"
        led.save()

    def user_settings(self, table: dict) -> None:
        (self.home / ".claude" / "settings.json").write_text(
            json.dumps({"enabledPlugins": table}), encoding="utf-8")

    def project_settings(self, name: str, table: dict) -> None:
        (self.root / ".claude").mkdir(exist_ok=True)
        (self.root / ".claude" / name).write_text(json.dumps({"enabledPlugins": table}),
                                                  encoding="utf-8")

    def cache(self) -> None:
        (self.home / ".claude" / "plugins" / "cache" / "gatekit" / "gatekit" / "0.16.5").mkdir(
            parents=True)

    def prompt(self):
        return prompt_gate.handle({"session_id": "s", "cwd": str(self.root), "prompt": "hi"})

    def stop(self):
        return stop_gate.handle({"session_id": "s", "cwd": str(self.root), "hook_event_name": "Stop"})

    def ask(self):
        return question_gate.handle({"session_id": "s", "cwd": str(self.root),
                                     "tool_name": "AskUserQuestion", "tool_input": {}})

    def asked(self) -> int:
        return ledger.Ledger.load(self.root, "s").data["questions"]["asked"]


class TestWhoCanEnableTheLegacyPlugin(Legacy):
    def test_project_local_settings_cannot_enable_it(self) -> None:
        self.cache()
        self.project_settings("settings.local.json", {"gatekit@gatekit": True})
        with self.renamed():
            self.assertEqual(names.legacy_plugin_enabled(self.root), [])

    def test_project_shared_settings_cannot_enable_it(self) -> None:
        self.cache()
        self.project_settings("settings.json", {"gatekit@gatekit": True})
        with self.renamed():
            self.assertEqual(names.legacy_plugin_enabled(self.root), [])

    def test_user_settings_and_cache_enable_it(self) -> None:
        self.cache()
        self.user_settings({"gatekit@gatekit": True, "gatebound@gatebound": True})
        with self.renamed():
            self.assertEqual(names.legacy_plugin_enabled(self.root), ["gatekit@gatekit"])

    def test_user_settings_without_a_cache_dir_do_not(self) -> None:
        self.user_settings({"gatekit@gatekit": True, "gatebound@gatebound": True})
        with self.renamed():
            self.assertEqual(names.legacy_plugin_enabled(self.root), [])

    def test_a_project_may_still_switch_it_off(self) -> None:
        self.cache()
        self.user_settings({"gatekit@gatekit": True, "gatebound@gatebound": True})
        self.project_settings("settings.local.json", {"gatekit@gatekit": False})
        with self.renamed():
            self.assertEqual(names.legacy_plugin_enabled(self.root), [])


class TestSnapshotAtTheFirstPrompt(Legacy):
    def test_enabling_it_mid_session_changes_nothing(self) -> None:
        with self.renamed():
            self.prompt()  # snapshot: nothing legacy enabled
            self.assertEqual(ledger.Ledger.load(self.root, "s").data["legacy_plugins"], [])
            # the session now enables the old plugin, every way it could
            self.cache()
            self.user_settings({"gatekit@gatekit": True, "gatebound@gatebound": True})
            self.project_settings("settings.local.json", {"gatekit@gatekit": True})
            self.assertEqual(self.stop()["decision"], "block")
            before = self.asked()
            self.ask()
            self.assertEqual(self.asked(), before + 1)
            self.prompt()  # a later prompt does not refresh the snapshot
            self.assertEqual(ledger.Ledger.load(self.root, "s").data["legacy_plugins"], [])
            self.assertEqual(self.stop()["decision"], "block")

    def test_enabled_at_the_first_prompt_stands_down_all_session(self) -> None:
        self.cache()
        self.user_settings({"gatekit@gatekit": True, "gatebound@gatebound": True})
        with self.renamed():
            self.prompt()
            self.assertEqual(ledger.Ledger.load(self.root, "s").data["legacy_plugins"],
                             ["gatekit@gatekit"])
            self.user_settings({"gatebound@gatebound": True})  # disabled later
            self.assertIsNone(self.stop())
            before = self.asked()
            self.assertIsNone(self.ask())
            self.assertEqual(self.asked(), before)

    def test_no_prompt_yet_means_judge(self) -> None:
        self.cache()
        self.user_settings({"gatekit@gatekit": True, "gatebound@gatebound": True})
        with self.renamed():
            self.assertIsNone(ledger.Ledger.load(self.root, "s").data.get("legacy_plugins"))
            self.assertEqual(self.stop()["decision"], "block")

    def test_before_the_rename_the_snapshot_is_empty(self) -> None:
        self.cache()
        self.user_settings({"gatekit@gatekit": True, "gatebound@gatebound": True})
        self.prompt()
        self.assertEqual(ledger.Ledger.load(self.root, "s").data["legacy_plugins"], [])

    def test_blank_ledger_has_no_snapshot(self) -> None:
        self.assertIn("legacy_plugins", ledger._blank("x"))
        self.assertIsNone(ledger._blank("x")["legacy_plugins"])


if __name__ == "__main__":
    unittest.main()

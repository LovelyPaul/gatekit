"""ADR-0029: the compatibility layer for the rename to gatebound.

Every contract the name is part of accepts both names, while everything a
user sees still says gatekit.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import (approval, contract, design, doctor, hosts, jobs, ledger,  # noqa: E402
                     migrate, names, paths, spec)
from gatekit.gates import bash as bash_gate  # noqa: E402
from gatekit.gates import prompt as prompt_gate  # noqa: E402
from gatekit.gates import question as question_gate  # noqa: E402
from gatekit.gates import spawn as spawn_gate  # noqa: E402
from gatekit.gates import stop as stop_gate  # noqa: E402
from gatekit.gates import write as write_gate  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "spec"
GATES = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates"
PY = sys.executable


class Temp(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        self._env = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    @contextlib.contextmanager
    def renamed(self):
        """Pretend the rename happened: gatebound current, gatekit legacy."""
        saved = (names.CURRENT, names.FUTURE, names.LEGACY)
        names.CURRENT, names.FUTURE, names.LEGACY = "gatebound", "gatebound", ("gatekit",)
        try:
            yield
        finally:
            names.CURRENT, names.FUTURE, names.LEGACY = saved

    def fake_home(self) -> pathlib.Path:
        home = self.root / "_home"
        (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
        os.environ["HOME"] = str(home)
        os.environ["USERPROFILE"] = str(home)
        os.environ["CODEX_HOME"] = str(home / ".codex")
        return home


# ------------------------------------------------------------------ names
class TestNames(unittest.TestCase):
    def test_current_name_is_still_gatekit(self) -> None:
        self.assertEqual(names.CURRENT, "gatekit")
        self.assertEqual(names.FUTURE, "gatebound")
        self.assertEqual(names.LEGACY, ())
        self.assertEqual(names.all_names(), ("gatebound", "gatekit"))

    def test_fence_aliases(self) -> None:
        self.assertEqual(set(names.fence_names("gatekit-task")),
                         {"gatekit-task", "gatebound-task"})
        self.assertEqual(set(names.fence_names("gatebound-scope")),
                         {"gatekit-scope", "gatebound-scope"})
        self.assertEqual(names.fence_names("python"), ("python",))
        self.assertEqual(names.fence("criterion"), "gatekit-criterion")

    def test_env_names_current_first(self) -> None:
        self.assertEqual(names.env_names("TASK_ID"), ("GATEKIT_TASK_ID", "GATEBOUND_TASK_ID"))


# ------------------------------------------------------------------ 1. fences
def _fenced(prefix: str, kind: str, body: dict) -> str:
    return "```%s-%s\n%s\n```\n" % (prefix, kind, json.dumps(body))


class TestFenceAliases(Temp):
    TASK = {"id": "t1", "title": "T", "write_scope": ["src/**"], "instruction": "x",
            "gates": [{"name": "g", "argv": [PY, "-c", "pass"]}], "depends_on": [], "round": 1}

    def test_spec_parse_fences_reads_both_prefixes(self) -> None:
        for prefix in ("gatekit", "gatebound"):
            text = _fenced(prefix, "task", self.TASK)
            self.assertEqual(spec.parse_fences(text, "gatekit-task"), [self.TASK], prefix)
            detailed = spec._parse_fences_detailed(text, "gatekit-discovery")
            self.assertEqual(detailed, [])
            disc = spec._parse_fences_detailed(_fenced(prefix, "discovery", {"a": 1}),
                                               "gatekit-discovery")
            self.assertEqual(disc[0][1], {"a": 1})

    def test_contract_derive_reads_gatebound_criterion_and_budget(self) -> None:
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        text = (_fenced("gatebound", "criterion", {"id": "c1", "argv": [PY, "-c", "pass"]})
                + _fenced("gatekit", "criterion", {"id": "c2", "argv": [PY, "-c", "pass"]})
                + _fenced("gatebound", "budget", {"total_budget_s": 60}))
        (self.root / "spec" / "05-gate.md").write_text(text, encoding="utf-8")
        derived = contract.derive(self.root)
        self.assertEqual([c["id"] for c in derived["criteria"]], ["c1", "c2"])

    def test_jobs_and_design_read_gatebound_tasks(self) -> None:
        (self.root / "spec").mkdir()
        (self.root / "spec" / "04-tasks.md").write_text(
            _fenced("gatebound", "task", self.TASK), encoding="utf-8")
        self.assertEqual([t["id"] for t in jobs.load_tasks(self.root)], ["t1"])
        self.assertEqual(contract.parse_fences(_fenced("gatebound", "task", self.TASK),
                                               "gatekit-task"), [self.TASK])

    def test_spawn_scope_fence_alias(self) -> None:
        body = '{"write_scope": ["src/**"], "stop_when": "done"}'
        for prefix in ("gatekit", "gatebound"):
            text = "do it\n```%s-scope\n%s\n```\n" % (prefix, body)
            self.assertEqual(spawn_gate.extract_fence(text).strip(), body, prefix)

    def test_spec_validate_same_verdict_with_either_prefix(self) -> None:
        old = self.root / "old"
        new = self.root / "new"
        shutil.copytree(FIXTURES / "valid-en", old)
        shutil.copytree(FIXTURES / "valid-en", new)
        for path in (new / "spec").glob("*.md"):
            text = path.read_text(encoding="utf-8")
            path.write_text(text.replace("```gatekit-", "```gatebound-"), encoding="utf-8")
        self.assertIn("```gatebound-task", (new / "spec" / "04-tasks.md").read_text(encoding="utf-8"))
        a, b = spec.validate(old), spec.validate(new)
        self.assertEqual(a["verdict"], b["verdict"])
        self.assertEqual(sorted(f["message"] for f in a["findings"]),
                         sorted(f["message"] for f in b["findings"]))


# ------------------------------------------------------------------ 2. state dir
class TestStateDir(Temp):
    def test_neither_gives_current_name(self) -> None:
        self.assertEqual(paths.state_dir(self.root), self.root / ".gatekit")

    def test_old_only(self) -> None:
        (self.root / ".gatekit").mkdir()
        self.assertEqual(paths.state_dir(self.root), self.root / ".gatekit")

    def test_new_only(self) -> None:
        (self.root / ".gatebound").mkdir()
        self.assertEqual(paths.state_dir(self.root), self.root / ".gatebound")
        self.assertEqual(paths.approvals_file(self.root), self.root / ".gatebound" / "approvals.json")
        deep = self.root / "a" / "b"
        deep.mkdir(parents=True)
        self.assertEqual(paths.project_root(str(deep)), self.root)

    def test_both_prefers_the_one_with_approvals(self) -> None:
        (self.root / ".gatekit").mkdir()
        (self.root / ".gatebound").mkdir()
        self.assertEqual(paths.state_dir(self.root), self.root / ".gatebound")
        (self.root / ".gatekit" / "approvals.json").write_text("{}", encoding="utf-8")
        self.assertEqual(paths.state_dir(self.root), self.root / ".gatekit")

    def test_gatebound_project_is_governed(self) -> None:
        (self.root / ".gatebound").mkdir()
        event = {"session_id": "s", "cwd": str(self.root), "prompt": "/gatekit:build"}
        prompt_gate.handle(event)
        self.assertTrue((self.root / ".gatebound" / "runs" / "s.json").is_file())
        self.assertFalse((self.root / ".gatekit").exists())


class TestProtectedStateBothNames(Temp):
    def setUp(self) -> None:
        super().setUp()
        (self.root / ".gatebound").mkdir()
        (self.root / "spec").mkdir()

    def write(self, rel: str):
        return write_gate.handle({"session_id": "s", "cwd": str(self.root), "tool_name": "Write",
                                  "tool_input": {"file_path": str(self.root / rel)}})

    def bash(self, command: str):
        return bash_gate.handle({"session_id": "s", "cwd": str(self.root), "tool_name": "Bash",
                                 "tool_input": {"command": command}})

    def denied(self, result) -> bool:
        return bool(result) and result["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_write_gate_protects_gatebound(self) -> None:
        for rel in (".gatebound/approvals.json", ".gatebound/contract.json",
                    ".gatebound/runs/s.json", ".gatekit/approvals.json"):
            self.assertTrue(self.denied(self.write(rel)), rel)
        for rel in (".gatebound/config.json", ".gatebound/eval/driver.py"):
            self.assertIsNone(self.write(rel), rel)

    def test_protected_state_reports_the_matched_dir(self) -> None:
        self.assertEqual(write_gate.protected_state(self.root, ".gatebound/approvals.json"),
                         ".gatebound/approvals.json")
        self.assertEqual(write_gate.protected_state(self.root, ".GATEKIT/contract.json"),
                         ".gatekit/contract.json")

    def test_bash_gate_protects_gatebound(self) -> None:
        for command in ("echo {} > .gatebound/approvals.json", "rm -rf .gatebound",
                        "cp x.json .gatebound/", "eval \"$(cat x)\" .gatebound/contract.json"):
            self.assertTrue(self.denied(self.bash(command)), command)
        self.assertIsNone(self.bash("echo {} > .gatebound/config.json"))

    def test_spec_allowlist_covers_gatebound(self) -> None:
        self.assertTrue(write_gate.in_allowlist(".gatebound/config.json"))
        self.assertTrue(write_gate.in_allowlist(".gatekit/config.json"))

    def test_evaluator_scratch_under_gatebound(self) -> None:
        job = paths.jobs_dir(self.root) / "j1" / "evaluate"
        job.mkdir(parents=True)
        (job / "task.json").write_text(json.dumps({"id": "evaluate", "write_scope": "read-only"}),
                                       encoding="utf-8")
        os.environ["GATEBOUND_TASK_ID"] = "evaluate"
        os.environ["GATEBOUND_JOB_ID"] = "j1"
        os.environ.pop("GATEKIT_TASK_ID", None)
        os.environ.pop("GATEKIT_JOB_ID", None)
        self.assertIsNone(self.write(".gatebound/eval/shot.png"))
        self.assertTrue(self.denied(self.write("src/app.py")))


# ------------------------------------------------------------------ 3. argv aliases
class TestArgvAliases(Temp):
    def setUp(self) -> None:
        super().setUp()
        self.tokens = str(paths.plugin_root() / "gatekit" / "gates" / "tokens.py")
        self.launcher = str(paths.plugin_root() / "bin" / "gatekit.py")

    def old_checkout(self, *tail: str) -> str:
        # A deleted checkout under someone's home, built at run time so no
        # personal path is committed.
        return os.path.join(self.root.anchor, "Users", "someone", "Projects", "gatekit",
                            "plugin", *tail)

    def test_study_gallery_shapes(self) -> None:
        cases = {
            "${CLAUDE_PLUGIN_ROOT}/gatekit/gates/tokens.py": self.tokens,
            "${CLAUDE_PLUGIN_ROOT}/gatebound/gates/tokens.py": self.tokens,
            "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py": self.launcher,
            "${CLAUDE_PLUGIN_ROOT}/bin/gatebound.py": self.launcher,
            self.old_checkout("gatekit", "gates", "tokens.py"): self.tokens,
            self.old_checkout("gatebound", "gates", "tokens.py"): self.tokens,
            self.old_checkout("bin", "gatekit.py"): self.launcher,
            "C:\\Users\\someone\\cache\\gatekit\\0.16.5\\gatekit\\gates\\tokens.py": self.tokens,
        }
        for raw, want in cases.items():
            if raw.startswith("C:") and os.name != "nt":
                continue
            out = paths.expand_argv(["python3", raw, "--lang", "ko", "src/**"])
            self.assertEqual(os.path.normcase(out[1]), os.path.normcase(want), raw)
            self.assertEqual(out[2:], ["--lang", "ko", "src/**"])

    def test_unknown_gate_or_existing_path_is_left_alone(self) -> None:
        missing = self.old_checkout("gatekit", "gates", "no_such_gate.py")
        self.assertEqual(paths.expand_argv(["python3", missing])[1], missing)
        real = self.root / "gatekit" / "gates" / "tokens.py"
        real.parent.mkdir(parents=True)
        real.write_text("print(1)\n", encoding="utf-8")
        self.assertEqual(paths.expand_argv(["python3", str(real)])[1], str(real))
        self.assertEqual(paths.expand_argv(["python3", "gatekit/gates/tokens.py"])[1],
                         "gatekit/gates/tokens.py")
        self.assertEqual(paths.expand_argv(["python3", self.old_checkout("tests", "x.py")])[1],
                         self.old_checkout("tests", "x.py"))

    def test_criterion_with_dead_checkout_path_runs(self) -> None:
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        dead = self.old_checkout("bin", "gatekit.py")
        crit = {"id": "cli", "argv": [PY, dead, "lang", "hello"], "timeout_s": 60}
        (self.root / "spec" / "05-gate.md").write_text(_fenced("gatekit", "criterion", crit),
                                                       encoding="utf-8")
        derived = contract.derive(self.root)
        self.assertEqual(derived["criteria"][0]["argv"][1], dead)  # pinned as written
        result = contract.execute(self.root)
        self.assertEqual(result["verdict"], "ok", result)


# ------------------------------------------------------------------ 4. env
class TestEnv(Temp):
    def test_task_id_reads_current_then_other(self) -> None:
        env = {"GATEBOUND_TASK_ID": "b"}
        self.assertEqual(names.task_id(env), "b")
        env["GATEKIT_TASK_ID"] = "k"
        self.assertEqual(names.task_id(env), "k")
        self.assertIsNone(names.job_id({}))
        self.assertEqual(names.job_id({"GATEBOUND_JOB_ID": "j"}), "j")

    def test_worker_env_sets_both(self) -> None:
        self.assertEqual(names.worker_env("t", "j"), {
            "GATEKIT_TASK_ID": "t", "GATEBOUND_TASK_ID": "t",
            "GATEKIT_JOB_ID": "j", "GATEBOUND_JOB_ID": "j"})

    def test_spawned_worker_gets_both_and_no_leak(self) -> None:
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        probe = self.root / "probe.py"
        probe.write_text(
            "import os,sys\n"
            "ok = (os.environ.get('GATEKIT_TASK_ID') == 't1' and os.environ.get('GATEBOUND_TASK_ID') == 't1'\n"
            "      and os.environ.get('GATEBOUND_JOB_ID') == os.environ.get('GATEKIT_JOB_ID')\n"
            "      and 'GATEBOUND_LEAK' not in os.environ and 'GATEKIT_LEAK' not in os.environ)\n"
            "sys.exit(0 if ok else 3)\n", encoding="utf-8")
        cfg = {"worker": {"default": "fake",
                          "backends": {"fake": {"argv": [PY, str(probe)], "enabled": True}}},
               "build": {"max_retries": 0, "parallel": 1, "task_timeout_s": 60,
                         "execution": "worker"}}
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        task = dict(TestFenceAliases.TASK, gates=[{"name": "g", "argv": [PY, "-c", "pass"]}])
        (self.root / "spec" / "04-tasks.md").write_text(_fenced("gatekit", "task", task),
                                                        encoding="utf-8")
        os.environ["GATEBOUND_LEAK"] = "x"
        os.environ["GATEKIT_LEAK"] = "x"
        job = jobs.start(self.root, no_preflight=True)
        status = json.loads((paths.jobs_dir(self.root) / job["job_id"] / "tasks" / "t1"
                             / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["exit"], 0, status)

    def test_worker_under_gatebound_env_never_approves(self) -> None:
        (self.root / ".gatekit").mkdir()
        os.environ.pop("GATEKIT_TASK_ID", None)
        os.environ["GATEBOUND_TASK_ID"] = "t1"
        with self.assertRaises(PermissionError):
            approval.approve(self.root, "spec/05-gate.md")


# ------------------------------------------------------------------ 5. approve guard / arming
class TestApproveAndArming(Temp):
    def test_approve_guard_recognises_gatebound_launcher(self) -> None:
        for command in ('python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatebound.py" approve spec/05-gate.md',
                        "gatebound approve spec/05-gate.md",
                        "python3 -m gatebound approve spec/05-gate.md",
                        "env -u GATEBOUND_TASK_ID python3 bin/gatebound.py approve x",
                        "bash -c 'python3 gatebound.py approve x'",
                        "python3 gatekit.py approve spec/05-gate.md"):
            self.assertTrue(bash_gate.invokes_gatekit_approve(command), command)
        self.assertFalse(bash_gate.invokes_gatekit_approve("python3 bin/gatebound.py approve check x"))
        self.assertTrue(bash_gate._APPROVE_RE.search("x/gatebound.py' approve spec"))

    def test_bash_gate_denies_gatebound_approve_in_worker(self) -> None:
        (self.root / ".gatekit").mkdir()
        os.environ.pop("GATEKIT_TASK_ID", None)
        os.environ["GATEBOUND_TASK_ID"] = "t1"
        result = bash_gate.handle({"session_id": "s", "cwd": str(self.root), "tool_name": "Bash",
                                   "tool_input": {"command": "python3 bin/gatebound.py approve spec/05-gate.md"}})
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_gatebound_commands_arm_the_stop_gate(self) -> None:
        for text in ("/gatebound:build", "<command-name>/gatebound:build</command-name>",
                     "# /gatebound:verify", "$gatebound-build go", "/gatekit:build"):
            self.assertIn(prompt_gate.detect_command(text), ("build", "verify"), text)
        self.assertEqual(prompt_gate.language_signal("$gatebound-build 시작해"), " 시작해")
        (self.root / ".gatekit").mkdir()
        prompt_gate.handle({"session_id": "s", "cwd": str(self.root),
                            "prompt": "<command-name>/gatebound:build</command-name>"})
        self.assertEqual(ledger.Ledger.load(self.root, "s").data["active_pipeline"], "build")


# ------------------------------------------------------------------ 6. AGENTS.md
class TestAgentsMarkers(Temp):
    def test_replaces_either_marker_pair(self) -> None:
        proot = paths.plugin_root()
        for name in ("gatekit", "gatebound"):
            begin, end = names.agents_markers(name)
            existing = "# Mine\n\n%s\nold block\n%s\n\ntail\n" % (begin, end)
            merged = hosts.merged_agents_md(existing, proot)
            self.assertNotIn("old block", merged, name)
            self.assertIn("# Mine", merged)
            self.assertIn("tail", merged)
            self.assertEqual(merged.count(":begin"), 1, name)
            self.assertIn(hosts.BLOCK_BEGIN, merged)
        self.assertEqual(hosts.BLOCK_BEGIN, names.agents_markers()[0])


# ------------------------------------------------------------------ 7. doctor
class TestDoctorBothNames(Temp):
    def setUp(self) -> None:
        super().setUp()
        self.home = self.fake_home()
        (self.root / ".gatekit").mkdir()

    def install(self, *keys: str, enabled=None) -> None:
        table = {k: {"version": "0.1"} for k in keys}
        (self.home / ".claude" / "plugins" / "installed_plugins.json").write_text(
            json.dumps({"version": 2, "plugins": table}), encoding="utf-8")
        enabled = keys if enabled is None else enabled
        (self.home / ".claude" / "settings.json").write_text(
            json.dumps({"enabledPlugins": {k: True for k in enabled}}), encoding="utf-8")

    def test_single_plugin_still_ok(self) -> None:
        self.install("gatekit@gatekit")
        self.assertEqual(doctor.axis_hooks_registered(self.root)["verdict"], "ok")

    def test_both_plugins_enabled_fails(self) -> None:
        self.install("gatekit@gatekit", "gatebound@gatebound")
        axis = doctor.axis_hooks_registered(self.root)
        self.assertEqual(axis["verdict"], "fail")
        self.assertIn("gatebound@gatebound", axis["detail"])
        self.assertIn("/plugin disable", axis["fix"])

    def test_both_enabled_in_project_settings_fails(self) -> None:
        self.install("gatekit@gatekit", "gatebound@gatebound", enabled=("gatekit@gatekit",))
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.local.json").write_text(
            json.dumps({"enabledPlugins": {"gatebound@gatebound": True}}), encoding="utf-8")
        self.assertEqual(doctor.axis_hooks_registered(self.root)["verdict"], "fail")

    def test_installed_but_disabled_second_plugin_is_not_a_conflict(self) -> None:
        self.install("gatekit@gatekit", "gatebound@gatebound", enabled=("gatekit@gatekit",))
        self.assertEqual(doctor.axis_hooks_registered(self.root)["verdict"], "ok")

    def test_both_in_codex_cache_fails(self) -> None:
        self.install("gatekit@gatekit")
        for name in ("gatekit", "gatebound"):
            (self.home / ".codex" / "plugins" / "cache" / name / name / "0.1" / "hooks").mkdir(parents=True)
        axis = doctor.axis_hooks_registered(self.root)
        self.assertEqual(axis["verdict"], "fail")
        self.assertIn("Codex", axis["detail"])

    def test_both_state_dirs_fail_axis_3(self) -> None:
        (self.root / ".gatebound").mkdir()
        axis = doctor.axis_project_state(self.root)
        self.assertEqual(axis["verdict"], "fail")
        self.assertIn(".gatebound", axis["detail"])
        self.assertIn("migrate", axis["fix"])

    def test_gatebound_dir_alone_is_ok(self) -> None:
        (self.root / ".gatekit").rmdir()
        (self.root / ".gatebound").mkdir()
        self.assertEqual(doctor.axis_project_state(self.root)["verdict"], "ok")


# ------------------------------------------------------------------ 8. coexistence
class TestCoexistence(Temp):
    def setUp(self) -> None:
        super().setUp()
        self.home = self.fake_home()
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        (self.home / ".claude" / "settings.json").write_text(
            json.dumps({"enabledPlugins": {"gatekit@gatekit": True, "gatebound@gatebound": True}}),
            encoding="utf-8")
        crit = {"id": "bad", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20}
        (self.root / "spec" / "05-gate.md").write_text(_fenced("gatekit", "criterion", crit),
                                                       encoding="utf-8")
        contract.derive(self.root)
        approval.approve(self.root, "spec/05-gate.md")
        led = ledger.Ledger.load(self.root, "s")
        led.data["active_pipeline"] = "build"
        led.save()

    def stop(self):
        return stop_gate.handle({"session_id": "s", "cwd": str(self.root), "hook_event_name": "Stop"})

    def ask(self):
        return question_gate.handle({"session_id": "s", "cwd": str(self.root),
                                     "tool_name": "AskUserQuestion", "tool_input": {}})

    def test_inert_under_the_current_name(self) -> None:
        self.assertEqual(names.legacy_plugin_enabled(self.root), [])
        self.assertEqual(self.stop()["decision"], "block")

    def test_after_rename_new_plugin_stands_down(self) -> None:
        with self.renamed():
            self.assertEqual(names.legacy_plugin_enabled(self.root), ["gatekit@gatekit"])
            self.assertIsNone(self.stop())
            before = ledger.Ledger.load(self.root, "s").data["questions"]["asked"]
            self.assertIsNone(self.ask())
            self.assertEqual(ledger.Ledger.load(self.root, "s").data["questions"]["asked"], before)
            out = prompt_gate.handle({"session_id": "s", "cwd": str(self.root), "prompt": "hi"})
            context = json.dumps(out)
            self.assertIn("gatekit@gatekit", context)
            again = json.dumps(prompt_gate.handle({"session_id": "s", "cwd": str(self.root),
                                                   "prompt": "hi"}))
            self.assertNotIn("gatekit@gatekit", again)  # once per session
            # write/bash keep running
            res = write_gate.handle({"session_id": "s", "cwd": str(self.root), "tool_name": "Write",
                                     "tool_input": {"file_path": str(self.root / ".gatekit/approvals.json")}})
            self.assertEqual(res["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_legacy_disabled_in_project_does_not_stand_down(self) -> None:
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "settings.json").write_text(
            json.dumps({"enabledPlugins": {"gatekit@gatekit": False}}), encoding="utf-8")
        with self.renamed():
            self.assertEqual(names.legacy_plugin_enabled(self.root), [])
            self.assertEqual(self.stop()["decision"], "block")

    def test_unreadable_settings_never_raise(self) -> None:
        (self.home / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
        with self.renamed():
            self.assertEqual(names.legacy_plugin_enabled(self.root), [])


# ------------------------------------------------------------------ migrate
def _git(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)


class TestMigrate(Temp):
    def setUp(self) -> None:
        super().setUp()
        state = self.root / ".gatekit"
        (state / "runs").mkdir(parents=True)
        (state / "config.json").write_text("{}", encoding="utf-8")
        (state / "approvals.json").write_text('{"approvals": []}', encoding="utf-8")
        (self.root / "spec").mkdir()
        (self.root / "spec" / "05-gate.md").write_text("```gatekit-criterion\n{}\n```\n",
                                                       encoding="utf-8")
        (self.root / ".gitignore").write_text("node_modules/\n.gatekit/runs/\n/.gatekit/jobs/\n",
                                              encoding="utf-8")

    def run_cli(self, *args: str):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = migrate.run(["--root", str(self.root), *args])
        return code, out.getvalue()

    def test_default_target_is_current_and_noop(self) -> None:
        code, out = self.run_cli("--apply", "--json")
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["to"], ".gatekit")
        self.assertEqual(report["actions"], [])
        self.assertTrue((self.root / ".gatekit").is_dir())

    def test_dry_run_changes_nothing(self) -> None:
        code, out = self.run_cli("--to", "gatebound", "--json")
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertFalse(report["applied"])
        self.assertTrue(report["actions"])
        self.assertTrue((self.root / ".gatekit").is_dir())
        self.assertFalse((self.root / ".gatebound").exists())

    def test_apply_renames_and_is_idempotent(self) -> None:
        spec_before = (self.root / "spec" / "05-gate.md").read_bytes()
        code, _ = self.run_cli("--to", "gatebound", "--apply")
        self.assertEqual(code, 0)
        self.assertFalse((self.root / ".gatekit").exists())
        self.assertTrue((self.root / ".gatebound" / "approvals.json").is_file())
        self.assertEqual((self.root / ".gitignore").read_text(encoding="utf-8"),
                         "node_modules/\n.gatebound/runs/\n/.gatebound/jobs/\n")
        self.assertEqual((self.root / "spec" / "05-gate.md").read_bytes(), spec_before)
        self.assertEqual(paths.state_dir(self.root), self.root / ".gatebound")
        code, out = self.run_cli("--to", "gatebound", "--apply", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["actions"], [])

    def test_refuses_when_both_exist(self) -> None:
        (self.root / ".gatebound").mkdir()
        code, out = self.run_cli("--to", "gatebound", "--apply", "--json")
        self.assertEqual(code, 1)
        self.assertIn("both", json.loads(out)["detail"])
        self.assertTrue((self.root / ".gatekit" / "approvals.json").is_file())

    def test_regenerates_agents_block_when_present(self) -> None:
        begin, end = names.agents_markers()
        (self.root / "AGENTS.md").write_text("# Mine\n\n%s\nstale\n%s\n" % (begin, end),
                                             encoding="utf-8")
        code, _ = self.run_cli("--to", "gatebound", "--apply")
        self.assertEqual(code, 0)
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("stale", text)
        self.assertIn("# Mine", text)

    @unittest.skipIf(shutil.which("git") is None, "git not available")
    def test_uses_git_mv_when_tracked(self) -> None:
        _git(self.root, "init", "-q")
        _git(self.root, "add", ".gatekit/config.json", ".gatekit/approvals.json")
        code, _ = self.run_cli("--to", "gatebound", "--apply")
        self.assertEqual(code, 0)
        staged = _git(self.root, "diff", "--cached", "--name-status").stdout
        self.assertIn(".gatebound/approvals.json", staged)
        self.assertTrue((self.root / ".gatebound" / "runs").is_dir())  # untracked moved too
        self.assertFalse((self.root / ".gatekit").exists())

    def test_registered_in_cli(self) -> None:
        from gatekit import cli
        self.assertIn("migrate", cli.SUBCOMMANDS)


# ------------------------------------------------------------------ hooks exit 0
class TestHooksExitZero(Temp):
    def test_gates_exit_zero_in_a_gatebound_project_with_broken_settings(self) -> None:
        home = self.fake_home()
        (home / ".claude" / "settings.json").write_text("{broken", encoding="utf-8")
        (self.root / ".gatebound").mkdir()
        (self.root / ".gatebound" / "approvals.json").write_text("{broken", encoding="utf-8")
        events = {
            "prompt.py": {"prompt": "/gatebound:build"},
            "stop.py": {"hook_event_name": "Stop"},
            "question.py": {"tool_name": "AskUserQuestion", "tool_input": {}},
            "write.py": {"tool_name": "Write", "tool_input": {"file_path": "x.py"}},
            "bash.py": {"tool_name": "Bash", "tool_input": {"command": "gatebound approve x"}},
        }
        for script, extra in events.items():
            event = dict({"session_id": "s", "cwd": str(self.root)}, **extra)
            proc = subprocess.run([PY, str(GATES / script)], input=json.dumps(event),
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, (script, proc.stderr[-300:]))


if __name__ == "__main__":
    unittest.main()

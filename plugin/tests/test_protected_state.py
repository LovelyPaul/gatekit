"""ADR-0027 decision 1: approvals.json and contract.json are written only by gatekit."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import approval, contract, ledger  # noqa: E402
from gatekit.gates import bash as bash_gate  # noqa: E402
from gatekit.gates import write as write_gate  # noqa: E402

PLUGIN = pathlib.Path(__file__).resolve().parents[1]
WRITE_SCRIPT = PLUGIN / "gatekit" / "gates" / "write.py"
BASH_SCRIPT = PLUGIN / "gatekit" / "gates" / "bash.py"
PY = sys.executable

PROTECTED = (".gatekit/approvals.json", ".gatekit/contract.json")


class Project(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        (self.root / "spec" / "05-gate.md").write_text(
            "```gatekit-criterion\n"
            + json.dumps({"id": "c", "argv": [PY, "-c", "pass"]}) + "\n```\n",
            encoding="utf-8")
        contract.derive(self.root)
        self.session = "sess-protect"
        self._env = {k: os.environ.pop(k) for k in ("GATEKIT_TASK_ID", "GATEKIT_JOB_ID")
                     if k in os.environ}

    def tearDown(self) -> None:
        os.environ.pop("GATEKIT_TASK_ID", None)
        os.environ.pop("GATEKIT_JOB_ID", None)
        os.environ.update(self._env)
        self._tmp.cleanup()

    def approve(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")

    def tool(self, name: str, tool_input: dict) -> dict:
        return {"session_id": self.session, "hook_event_name": "PreToolUse",
                "tool_name": name, "tool_input": tool_input, "cwd": str(self.root)}

    def write(self, path: str):
        return write_gate.handle(self.tool("Write", {"file_path": path}))

    def bash(self, command: str):
        return bash_gate.handle(self.tool("Bash", {"command": command}))

    def assertDenied(self, result) -> None:  # noqa: N802
        self.assertIsNotNone(result)
        out = result["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("/gatekit:gate", out["permissionDecisionReason"])


class TestProtectedPath(Project):
    def test_variants_are_protected(self) -> None:
        variants = [
            ".gatekit/approvals.json", ".gatekit/contract.json",
            "./.gatekit/approvals.json", str(self.root / ".gatekit" / "contract.json"),
            ".GATEKIT/Approvals.JSON", ".gatekit/CONTRACT.json",
            ".gatekit/approvals.json.", ".gatekit/approvals.json  ", ".gatekit./contract.json",
            ".gatekit/approvals.json::$DATA", ".gatekit/contract.json:evil",
            "src/../.gatekit/approvals.json", "spec/../.gatekit/./contract.json",
            ".gatekit\\approvals.json",
        ]
        for raw in variants:
            with self.subTest(raw=raw):
                self.assertIsNotNone(write_gate.protected_state(self.root, raw))

    def test_others_are_not_protected(self) -> None:
        for raw in (".gatekit/config.json", ".gatekit/baseline.json", "src/contract.json",
                    "approvals.json", ".gatekit/runs/x.json", ".gatekit/eval/contract.json.bak",
                    "spec/05-gate.md"):
            with self.subTest(raw=raw):
                self.assertIsNone(write_gate.protected_state(self.root, raw))

    def test_symlinked_file_and_directory(self) -> None:
        (self.root / "link.json").symlink_to(self.root / ".gatekit" / "approvals.json")
        (self.root / "state").symlink_to(self.root / ".gatekit", target_is_directory=True)
        self.assertIsNotNone(write_gate.protected_state(self.root, "link.json"))
        self.assertIsNotNone(write_gate.protected_state(self.root, "state/contract.json"))

    def test_hard_link(self) -> None:
        os.link(self.root / ".gatekit" / "contract.json", self.root / "copy.json")
        self.assertIsNotNone(write_gate.protected_state(self.root, "copy.json"))

    def test_bad_input_is_not_an_error(self) -> None:
        self.assertIsNone(write_gate.protected_state(self.root, ""))
        self.assertIsNone(write_gate.protected_state(self.root, "a\x00b"))


class TestWriteGate(Project):
    def test_denied_before_and_after_approval(self) -> None:
        for approved in (False, True):
            if approved:
                self.approve()
            for path in PROTECTED:
                for tool in ("Write", "Edit", "MultiEdit"):
                    with self.subTest(approved=approved, path=path, tool=tool):
                        self.assertDenied(write_gate.handle(self.tool(tool, {"file_path": path})))
                with self.subTest(approved=approved, path=path, tool="NotebookEdit"):
                    self.assertDenied(write_gate.handle(
                        self.tool("NotebookEdit", {"notebook_path": path})))

    def test_denied_without_a_spec_or_with_the_gate_off(self) -> None:
        (self.root / ".gatekit" / "config.json").write_text(
            json.dumps({"enforce_spec_before_code": False}), encoding="utf-8")
        self.assertDenied(self.write(".gatekit/approvals.json"))

    def test_denied_for_a_scoped_worker(self) -> None:
        jdir = self.root / ".gatekit" / "jobs" / "j1" / "tasks" / "t1"
        jdir.mkdir(parents=True)
        (jdir / "task.json").write_text(json.dumps({"write_scope": [".gatekit/**"]}),
                                        encoding="utf-8")
        os.environ["GATEKIT_TASK_ID"] = "t1"
        os.environ["GATEKIT_JOB_ID"] = "j1"
        self.assertDenied(self.write(".gatekit/contract.json"))
        self.assertIsNone(self.write(".gatekit/notes.json"))

    def test_apply_patch_after_approval(self) -> None:
        self.approve()
        for header in ("Add File", "Update File", "Delete File"):
            patch = "*** Begin Patch\n*** %s: .gatekit/Contract.json\n*** End Patch" % header
            with self.subTest(header=header):
                self.assertDenied(write_gate.handle(self.tool("apply_patch", {"command": patch})))
        moved = ("*** Begin Patch\n*** Update File: src/a.py\n"
                 "*** Move to: .gatekit/approvals.json\n*** End Patch")
        self.assertDenied(write_gate.handle(self.tool("apply_patch", {"command": moved})))
        plain = "*** Begin Patch\n*** Update File: src/a.py\n*** End Patch"
        self.assertIsNone(write_gate.handle(self.tool("apply_patch", {"command": plain})))

    def test_other_state_writes_unchanged(self) -> None:
        self.assertIsNone(self.write(".gatekit/config.json"))
        result = self.write("src/app.py")  # rule (a): not approved yet
        self.assertIn("05-gate.md", result["hookSpecificOutput"]["permissionDecisionReason"])
        self.approve()
        self.assertIsNone(self.write("src/app.py"))
        self.assertIsNone(self.write(".gatekit/baseline.json"))

    def test_korean_message(self) -> None:
        led = ledger.Ledger.load(self.root, self.session)
        led.data["output_lang"] = "ko"
        led.save()
        reason = self.write(".gatekit/approvals.json")["hookSpecificOutput"][
            "permissionDecisionReason"]
        self.assertIn("/gatekit:gate", reason)
        self.assertIn("gatekit", reason)
        self.assertRegex(reason, "[가-힣]")


class TestBashGate(Project):
    COMMANDS = (
        "echo {} > .gatekit/approvals.json",
        "echo {} >> ./.gatekit/contract.json",
        "jq . x.json | tee .gatekit/approvals.json",
        "cp /tmp/forged.json .gatekit/approvals.json",
        "mv forged.json .GATEKIT/contract.json",
        "install -m 644 f .gatekit/contract.json",
        "dd if=f of=.gatekit/approvals.json",
        "sed -i 's/fail/ok/' .gatekit/contract.json",
        "perl -pi -e 's/a/b/' .gatekit/approvals.json",
        "cd .gatekit && echo x > approvals.json",
        "cd src && echo x > ../.gatekit/contract.json",
        "bash -c 'echo x > .gatekit/approvals.json'",
        "rm .gatekit/contract.json",
        "rm -rf .gatekit",
        "mv .gatekit/approvals.json /tmp/a",
        "cp forged/approvals.json .gatekit/",
        "truncate -s 0 .gatekit/contract.json",
        "touch .gatekit/approvals.json",
        # review: globs and braces in a target
        "echo {} > .gatekit/approval?.json",
        "cp /tmp/f .gatekit/a*s.json",
        "jq . x | tee .gatekit/{approvals,x}.json",
        "echo > .gatekit/approvals.js[o]n",
        "echo > .gate*/contract.json",
        "rm .gatekit/*",
        "rm -rf .gatek?t",
        # review: cd behind shell keywords, pushd, conditional cd
        "{ cd .gatekit; echo > approvals.json; }",
        "if true; then cd .gatekit; fi; echo {} > approvals.json",
        "for i in 1; do cd .gatekit; done; echo {} > approvals.json",
        "! cd .gatekit; echo > contract.json",
        "pushd .gatekit; echo > approvals.json",
        "cd .gatekit; false && cd /tmp; echo > approvals.json",
        # review: copies into .gatekit that do not name it as a literal destination
        "cp -t .gatekit /tmp/x/approvals.json",
        "cp --target-directory=.gatekit /tmp/x/contract.json",
        "install -t .gatekit /tmp/x/approvals.json",
        "cp /tmp/x/* .gatekit/",
        "cp -r /tmp/fake/.gatekit .",
    )

    def test_denied_before_and_after_approval(self) -> None:
        for approved in (False, True):
            if approved:
                self.approve()
            for command in self.COMMANDS:
                with self.subTest(approved=approved, command=command):
                    self.assertDenied(self.bash(command))

    def test_copies_through_a_symlink_or_of_a_directory(self) -> None:
        (self.root / "g").symlink_to(self.root / ".gatekit", target_is_directory=True)
        fake = self.root / "fake"
        (fake / ".gatekit").mkdir(parents=True)
        (fake / "approvals.json").write_text("{}", encoding="utf-8")
        for approved in (False, True):
            if approved:
                self.approve()
            for command in ("cp /tmp/x/approvals.json g", "cp /tmp/x/approvals.json g/",
                            "rsync -a fake/ .", "cp -R fake/ .", "rsync -a fake/ .gatekit"):
                with self.subTest(approved=approved, command=command):
                    self.assertDenied(self.bash(command))

    def test_globs_and_cd_that_miss_the_files_are_allowed(self) -> None:
        self.approve()
        for command in ("rm -rf build/*", "rm -f *.json", "echo > src/*.txt",
                        "cd src && echo x > approvals.json", "cp -r fake/ build",
                        "if true; then cd src; fi; echo x > out.txt", "cp a* src/"):
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))

    def test_opaque_command_naming_the_file_after_approval(self) -> None:
        self.approve()
        self.assertDenied(self.bash(
            "python3 -c \"open('.gatekit/approvals.json','w').write('{}')\""))
        self.assertDenied(self.bash("git checkout HEAD -- .gatekit/contract.json"))
        # Other opaque commands are still not judged after approval.
        self.assertIsNone(self.bash("python3 -c \"open('src/x.py','w')\""))

    def test_launcher_stays_allowed_for_the_host(self) -> None:
        launcher = 'python3 "%s"' % (PLUGIN / "bin" / "gatekit.py")
        for approved in (False, True):
            if approved:
                self.approve()
            for sub in ("approve spec/05-gate.md", "contract derive", "approve check spec/05-gate.md"):
                with self.subTest(approved=approved, sub=sub):
                    self.assertIsNone(self.bash("%s %s" % (launcher, sub)))
        self.assertDenied(self.bash(launcher + " contract derive --json > .gatekit/contract.json"))

    def test_worker_approve_still_denied(self) -> None:
        os.environ["GATEKIT_TASK_ID"] = "t1"
        reason = self.bash('python3 "%s" approve spec/05-gate.md' % (PLUGIN / "bin" / "gatekit.py"))
        self.assertIn("worker", reason["hookSpecificOutput"]["permissionDecisionReason"])

    def test_reads_and_other_writes_unchanged(self) -> None:
        self.approve()
        for command in ("cat .gatekit/approvals.json", "jq . .gatekit/contract.json",
                        "cp .gatekit/contract.json /tmp/c.json", "echo x > .gatekit/notes.txt",
                        "rm -rf .gatekit/runs", "echo x > src/app.py", "ls -la .gatekit"):
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))

    def test_reads_before_approval_unchanged(self) -> None:
        self.assertIsNone(self.bash("cat .gatekit/approvals.json"))
        self.assertIsNone(self.bash("echo x > .gatekit/notes.txt"))


class TestExitZero(Project):
    def run_hook(self, script: pathlib.Path, event) -> subprocess.CompletedProcess:
        data = event if isinstance(event, str) else json.dumps(event)
        return subprocess.run([PY, str(script)], input=data, capture_output=True,
                              text=True, timeout=60)

    def test_deny_exits_zero(self) -> None:
        for script, event in (
                (WRITE_SCRIPT, self.tool("Write", {"file_path": ".gatekit/approvals.json"})),
                (BASH_SCRIPT, self.tool("Bash", {"command": "echo > .gatekit/contract.json"}))):
            with self.subTest(script=script.name):
                proc = self.run_hook(script, event)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn('"deny"', proc.stdout)

    def test_internal_error_exits_zero(self) -> None:
        for script in (WRITE_SCRIPT, BASH_SCRIPT):
            with self.subTest(script=script.name):
                proc = self.run_hook(script, "{not json")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                weird = self.tool("Write" if script is WRITE_SCRIPT else "Bash",
                                  {"file_path": 7, "command": ["x"]})
                self.assertEqual(self.run_hook(script, weird).returncode, 0)


if __name__ == "__main__":
    unittest.main()

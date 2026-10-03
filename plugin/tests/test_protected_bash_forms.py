"""ADR-0027 amendment: shell forms that reached gatekit's state unseen.

An interpreter fed its script on stdin, a link made and written in one
command, a path built from a variable, and a git restore by directory
pathspec. Each is denied before and after approval; the normal-work forms
next to them stay allowed.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_protected_state import PLUGIN, Project  # noqa: E402


class Forms(Project):
    def assertDenied(self, result) -> None:  # noqa: N802
        """The protected-state rule itself, not rule (a) or an opaque refusal."""
        super().assertDenied(result)
        self.assertIn("ADR-0027", result["hookSpecificOutput"]["permissionDecisionReason"])

    def assertOpaque(self, result) -> None:  # noqa: N802
        self.assertIsNotNone(result)
        self.assertIn("cannot determine", result["hookSpecificOutput"]["permissionDecisionReason"])

    def denied_always(self, commands) -> None:
        for approved in (False, True):
            if approved:
                self.approve()
            for command in commands:
                with self.subTest(approved=approved, command=command):
                    self.assertDenied(self.bash(command))

    def allowed_after_approval(self, commands) -> None:
        self.approve()
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))


class TestInterpreterOnStdin(Forms):
    def test_stdin_script_naming_the_file_is_denied(self) -> None:
        self.denied_always((
            "python3 <<PY\nimport json\njson.dump({}, open('.gatekit/contract.json','w'))\nPY",
            "node <<'JS'\nrequire('fs').writeFileSync('.gatekit/approvals.json','{}')\nJS",
            "echo \"open('.gatekit/approvals.json','w').write('{}')\" | python3",
            "python3 <<< \"open('.gatekit/approvals.json','w')\"",
            "ruby <<RB\nFile.write('.gatekit/contract.json', '{}')\nRB",
            "perl <<PL\nopen(F, '>', '.gatekit/approvals.json');\nPL",
        ))

    def test_stdin_script_is_opaque_before_approval(self) -> None:
        for command in ("python3 < script.py", "cat gen.py | python3", "node < build.js",
                        "python3 <<PY\nprint(1)\nPY", "echo 'puts 1' | ruby"):
            with self.subTest(command=command):
                self.assertOpaque(self.bash(command))

    def test_script_file_operand_unchanged(self) -> None:
        for command in ("python3 script.py", "python3 script.py < input.txt",
                        "cat data.json | python3 tool.py", "node build.js <<EOF\nx\nEOF",
                        "python3 -m json.tool .gatekit/contract.json", "python3 -m pytest -q",
                        "python3 --version", "node --version"):
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))

    def test_stdin_script_not_naming_the_file_after_approval(self) -> None:
        self.allowed_after_approval(("python3 < script.py", "cat gen.py | python3"))


class TestLinkSources(Forms):
    def test_link_to_protected_state_is_denied(self) -> None:
        (self.root / "sub").mkdir()
        self.denied_always((
            "ln -s .gatekit/approvals.json l && echo x > l",
            "ln -s ../.gatekit/approvals.json sub/l; cp x sub/l",
            "ln .gatekit/approvals.json h2; echo x >> h2",
            "ln -sf .gatekit/contract.json x",
            "ln -s .gatekit g2; echo x > g2/approvals.json",
            "ln -sfn .gatekit g2",
            "cp -s .gatekit/approvals.json l",
            "cp -al .gatekit bk",
            "ln -t sub .gatekit/contract.json",
        ))

    def test_other_links_and_copies_allowed(self) -> None:
        self.allowed_after_approval((
            "ln -s src/app.py l", "ln -s ../shared/config.json .", "ln -sf build/out current",
            "cp -a .gatekit /tmp/backup", "cp .gatekit/contract.json /tmp/c.json",
        ))


class TestVariablePaths(Forms):
    def test_variable_built_paths_are_denied(self) -> None:
        self.denied_always((
            "d=.gatekit; echo x > $d/approvals.json",
            "d=.gatekit; cp sub/approvals.json $d/",
            "export d=.gatekit; echo > ${d}/contract.json",
            'D="$PWD/.gatekit"; rm -rf "$D"',
            "echo x > $PWD/.gatekit/approvals.json",
            'echo x > "${PWD}/.gatekit/contract.json"',
        ))

    def test_other_variable_paths_allowed(self) -> None:
        self.allowed_after_approval((
            "d=build; echo x > $d/out.txt", "echo x > $HOME/notes.txt",
            "out=dist; cp a.json $out/", "echo x > $TMPDIR/approvals.json",
        ))


class TestGitPathspec(Forms):
    def test_restore_by_directory_is_denied(self) -> None:
        self.denied_always((
            "git checkout -- .gatekit",
            "git restore .gatekit",
            "git checkout HEAD~1 -- .gatekit",
            "git restore --source=HEAD~1 .gatekit",
            "git restore -s HEAD~1 -- .gatekit/",
            "git checkout stash@{0} -- .gatekit/",
            "git stash push -- .gatekit",
            "git reset HEAD -- .gatekit/approvals.json",
            "git -C src checkout -- ../.gatekit",
        ))

    def test_trust_boundary_and_normal_git_allowed(self) -> None:
        self.allowed_after_approval((
            "git checkout -- .", "git reset --hard", "git reset --hard HEAD~1",
            "git checkout -b feature", "git checkout main", "git stash", "git stash pop",
            "git restore src/app.py", "git clean -fdx",
        ))

    def test_git_reads_allowed_before_approval(self) -> None:
        for command in ("git status", "git diff .gatekit/approvals.json",
                        "git log -p -- .gatekit/approvals.json",
                        "git show HEAD:.gatekit/approvals.json", "git add .gatekit/",
                        'git commit -m "approve gate"'):
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))


class TestLauncherUnchanged(Forms):
    def test_launcher_commands_allowed(self) -> None:
        launcher = 'python3 "%s"' % (PLUGIN / "bin" / "gatekit.py")
        for approved in (False, True):
            if approved:
                self.approve()
            for sub in ("approve spec/05-gate.md", "contract derive", "contract run",
                        "jobs status", "jobs clean"):
                with self.subTest(approved=approved, sub=sub):
                    self.assertIsNone(self.bash("%s %s" % (launcher, sub)))



class TestWholeStateDirectory(Forms):
    """ADR-0027 amendment B: everything under .gatekit/ is gatekit's, except
    config.json (the user's settings) and eval/** (evaluator scratch)."""

    GATEKIT_ONLY = (
        ".gatekit/runs/contract-last.json", ".gatekit/runs/sess-1.json",
        ".gatekit/runs/hook-errors.log", ".gatekit/jobs/j1/tasks/t1/status.json",
        ".gatekit/jobs/j1/job.json", ".gatekit/attempts.json", ".gatekit/baseline.json",
        ".gatekit/notes.txt", ".GATEKIT/Runs/X.json", "other/.gatekit/runs/x.json",
        ".gatekit/eval/../runs/x.json", ".gatekit/jobs",
    )
    USER_OWNED = (".gatekit/config.json", ".GATEKIT/Config.json", ".gatekit/eval",
                  ".gatekit/eval/drive.mjs", ".gatekit/eval/shots/a.png", ".gatekit",
                  "src/runs/x.json", "config/status.json")

    def test_protected_state_covers_the_directory(self) -> None:
        from gatekit.gates import write as write_gate
        for raw in self.GATEKIT_ONLY:
            with self.subTest(raw=raw):
                self.assertIsNotNone(write_gate.protected_state(self.root, raw))
        for raw in self.USER_OWNED:
            with self.subTest(raw=raw):
                self.assertIsNone(write_gate.protected_state(self.root, raw))

    def test_user_owned_names_followed_through_links(self) -> None:
        from gatekit.gates import write as write_gate
        (self.root / ".gatekit" / "runs").mkdir()
        (self.root / ".gatekit" / "eval").symlink_to(self.root / ".gatekit" / "runs",
                                                    target_is_directory=True)
        (self.root / ".gatekit" / "config.json").symlink_to(
            self.root / ".gatekit" / "approvals.json")
        self.assertIsNotNone(write_gate.protected_state(self.root, ".gatekit/eval/x.json"))
        self.assertIsNotNone(write_gate.protected_state(self.root, ".gatekit/config.json"))

    def test_write_tool_denied_before_and_after_approval(self) -> None:
        for approved in (False, True):
            if approved:
                self.approve()
            for path in self.GATEKIT_ONLY[:9]:
                with self.subTest(approved=approved, path=path):
                    self.assertDenied(self.write(path))
            for path in (".gatekit/config.json", ".gatekit/eval/drive.mjs"):
                with self.subTest(approved=approved, path=path):
                    self.assertIsNone(self.write(path))

    def test_evaluator_scratch_still_writable(self) -> None:
        import json
        edir = self.root / ".gatekit" / "jobs" / "j1" / "evaluate"
        edir.mkdir(parents=True)
        (edir / "task.json").write_text(json.dumps({"id": "evaluate"}), encoding="utf-8")
        self.approve()
        os.environ["GATEKIT_TASK_ID"] = "evaluate"
        os.environ["GATEKIT_JOB_ID"] = "j1"
        self.assertIsNone(self.write(".gatekit/eval/drive.mjs"))
        self.assertIsNone(self.bash("echo x > .gatekit/eval/server.log"))
        self.assertDenied(self.write(".gatekit/runs/contract-last.json"))
        self.assertDenied(self.bash("echo x > .gatekit/jobs/j1/status.json"))

    def test_bash_writes_denied(self) -> None:
        (self.root / "sub").mkdir()
        self.denied_always((
            "echo x > .gatekit/other.json",
            "jq . x > .gatekit/runs/contract-last.json",
            "mkdir -p .gatekit/jobs/t1 && echo '{}' > .gatekit/jobs/t1/status.json",
            "echo '{}' > .gatekit/jobs/t1/contract.json",
            "rm -rf .gatekit/runs", "rm -rf .gatekit/jobs/abc", "rm -rf .gatekit",
            "rm .gatekit/runs/*", "echo > .gatekit/*.json", "rm -f .gatekit/b*",
            "cp x .gatekit/", "cp -R sub .gatekit", "ln -sfn sub .gatekit",
            "cp -a other/.gatekit/. .gatekit", "mv .gatekit/attempts.json /tmp/a",
            "ln -s .gatekit/runs/contract-last.json l",
            "tar -xf a.tar -C .gatekit", "unzip -o a.zip -d .gatekit/runs",
            "find .gatekit -name '*.json' -exec rm {} +", "find .gatekit/runs -delete",
            "cd .gatekit && python3 -c \"open('approvals.json','w').write('{}')\"",
            "python3 -c \"import pathlib; pathlib.Path('.gatekit','approvals.json').write_text('{}')\"",
            "python3 -c \"open('.gatekit/runs/s.json','w')\"",
            "if true; then cd .gatekit; fi; echo {} > attempts.json",
            "d=.gatekit/runs; echo x > $d/s.json",
            "git checkout -- .gatekit/runs",
        ))

    def test_bash_normal_work_allowed(self) -> None:
        commands = (
            "mkdir .gatekit", "mkdir -p .gatekit/eval", "echo x > .gatekit/eval/log.txt",
            "rm -rf .gatekit/eval", "cp cfg.json .gatekit/config.json",
            "cp config.json .gatekit/", "cat .gatekit/runs/x.json", "jq . .gatekit/attempts.json",
            "ls -R .gatekit", "grep -r x .gatekit", "diff .gatekit/baseline.json /tmp/b",
            "python3 -m json.tool .gatekit/baseline.json", "wc -c .gatekit/approvals.json",
            "tar -czf backup.tgz .gatekit", "zip -r b.zip .gatekit",
            "rsync -a .gatekit/ /tmp/bk/", "cp -a .gatekit /tmp/bk", "git add .gatekit/",
            "git diff .gatekit/attempts.json", "rm -rf node_modules", "rm -rf build dist",
            "echo x > sub/approvals.json", "echo x > config/status.json",
            "cd .gatekit && ls", "tar -xf a.tar -C build", "find . -name '*.pyc' -delete",
            "d=.gatekit/eval; echo x > $d/log.txt",
        )
        for approved in (False, True):
            if approved:
                self.approve()
            for command in commands:
                with self.subTest(approved=approved, command=command):
                    result = self.bash(command)
                    reason = (result or {}).get("hookSpecificOutput", {}).get(
                        "permissionDecisionReason", "")
                    self.assertNotIn("ADR-0027", reason)
        for command in commands:
            with self.subTest(command=command):
                self.assertIsNone(self.bash(command))

    def test_git_clean_stays_allowed(self) -> None:
        self.allowed_after_approval(("git clean -fdx", "git stash", "git checkout -b f"))

    def test_message_names_the_rule(self) -> None:
        reason = self.write(".gatekit/runs/contract-last.json")["hookSpecificOutput"][
            "permissionDecisionReason"]
        self.assertIn(".gatekit/runs/contract-last.json", reason)
        self.assertIn("config.json", reason)

    def test_setup_still_creates_config(self) -> None:
        import shutil
        import subprocess
        launcher = PLUGIN / "bin" / "gatekit.py"
        fresh = self.root / "fresh"
        fresh.mkdir()
        (fresh / ".git").mkdir()
        command = 'python3 "%s" workers set-default claude' % launcher
        event = self.tool("Bash", {"command": command})
        event["cwd"] = str(fresh)
        from gatekit.gates import bash as bash_gate
        self.assertIsNone(bash_gate.handle(event))
        proc = subprocess.run([sys.executable, str(launcher), "workers", "set-default", "claude"],
                              cwd=str(fresh), capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((fresh / ".gatekit" / "config.json").is_file())
        shutil.rmtree(fresh)


if __name__ == "__main__":
    unittest.main()

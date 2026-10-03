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


if __name__ == "__main__":
    unittest.main()

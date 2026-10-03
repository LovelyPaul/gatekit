"""The shell gates finish well inside the hook timeout, whatever the input.

Review finding (2026-10-04): ``(?im)^\\s*using\\s+namespace\\b`` in the
PowerShell reader was quadratic over a masked here-string (``\\s*`` crossed
newlines): 40k lines took 7 s, 100k 45 s, against a 10 s hook timeout — and a
PreToolUse hook that times out does not block. Two fixes (ADR-0028
amendment): the patterns no longer let whitespace runs cross lines or start
a match at every blank, and a command larger than
:data:`gatekit.gates.bash.MAX_COMMAND_BYTES` is not parsed at all — denied as
opaque while a restriction is active, otherwise judged only by the linear
protected-state mention scan.
"""
from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import approval, names, pwsh  # noqa: E402
from gatekit.gates import bash as bash_gate  # noqa: E402
from gatekit.gates import powershell as ps_gate  # noqa: E402

#: Generous: CI runners are slow and shared. The reviewer's 40k-line
#: here-string took 7.3 s before the fix.
BOUND_S = 2.0
PAYLOAD = "open('.gatekit/approvals.json','w').write('x')\n"


def reviewer_inputs():
    """The inputs of the review's dos.py, named."""
    out = []
    for n in (5000, 10000, 20000, 40000):
        out.append(("PowerShell", "ps here-string %d" % n, "@'\n" + "x\n" * n + PAYLOAD + "'@ | python -"))
    for n in (20000, 40000):
        out.append(("Bash", "bash heredoc %d" % n, "python - <<'EOF'\n" + "x\n" * n + PAYLOAD + "EOF"))
        out.append(("Bash", "bash lines %d" % n,
                    "\n".join(["echo x"] * n) + "\necho x > .gatekit/approvals.json"))
        out.append(("PowerShell", "ps lines %d" % n,
                    "\n".join(["Write-Host x"] * n) + "\nSet-Content .gatekit/approvals.json x"))
    return out


def under_cap_shapes():
    """Pathological shapes just under the cap, where the parser does run."""
    size = bash_gate.MAX_COMMAND_BYTES - 200
    return [
        ("PowerShell", "here-string of blank lines",
         "@'\n" + "\n" * size + "'@ | python -"),
        ("PowerShell", "here-string of indented lines",
         "@'\n" + "  \t\n" * (size // 4) + "'@ | python -"),
        ("PowerShell", "one long blank run", "Write-Host" + " " * size + "x"),
        ("PowerShell", "blank run in a string", "Write-Host '" + " " * size + "+'"),
        ("PowerShell", "brackets and blanks", "[ " * (size // 2)),
        ("PowerShell", "using lines", "using namespace X\n" * (size // 18)),
        ("PowerShell", "comment of blanks", "<#" + " \n" * (size // 2) + "#>"),
        ("Bash", "blank lines", "\n" * size + "echo x"),
        ("Bash", "one long blank run", "echo" + " " * size + "x"),
        ("Bash", "heredoc markers", "cat <<EOF\n" * (size // 10)),
    ]


class Project(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        (self.root / "spec" / "05-gate.md").write_text("# Gate\n", encoding="utf-8")
        self._env = {k: os.environ.pop(k) for k in list(os.environ)
                     if k.startswith(names.env_prefixes())}

    def tearDown(self) -> None:
        for key in list(os.environ):
            if key.startswith(names.env_prefixes()):
                del os.environ[key]
        os.environ.update(self._env)
        self._tmp.cleanup()

    def approve(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")

    def judge(self, tool: str, command: str):
        event = {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": tool,
                 "cwd": str(self.root), "tool_input": {"command": command}}
        gate = ps_gate if tool == "PowerShell" else bash_gate
        start = time.perf_counter()
        result = gate.handle(event)
        return result, time.perf_counter() - start

    def reason(self, result) -> str:
        return result["hookSpecificOutput"]["permissionDecisionReason"]


class TestTiming(Project):
    def check(self, cases) -> None:
        for approved in (False, True):
            if approved:
                self.approve()
            for tool, name, command in cases:
                with self.subTest(approved=approved, case=name):
                    _, elapsed = self.judge(tool, command)
                    self.assertLess(elapsed, BOUND_S, "%s took %.2f s" % (name, elapsed))

    def test_reviewer_inputs_finish_fast(self) -> None:
        self.check(reviewer_inputs())

    def test_pathological_shapes_under_the_cap_finish_fast(self) -> None:
        self.check(under_cap_shapes())

    def test_reviewer_inputs_naming_state_are_still_denied(self) -> None:
        self.approve()
        for tool, name, command in reviewer_inputs():
            with self.subTest(case=name):
                result, _ = self.judge(tool, command)
                self.assertIsNotNone(result, name)
                self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_mention_text_of_a_long_blank_run_is_linear(self) -> None:
        text = "x" + " " * 200000 + "+ 'y'"
        start = time.perf_counter()
        pwsh.mention_text(text, pwsh.PSWriteTargets())
        self.assertLess(time.perf_counter() - start, BOUND_S)


class TestUsingNamespaceStillOpaque(unittest.TestCase):
    def test_forms(self) -> None:
        for command in ("using namespace System.IO\n[File]::WriteAllText('a', 'b')",
                        "  using namespace System.IO; [File]::Delete('a')",
                        "Write-Host x\n\tUSING   namespace System.IO"):
            with self.subTest(command=command):
                self.assertTrue(pwsh.read(command, "/proj").opaque, command)

    def test_not_a_statement(self) -> None:
        self.assertFalse(pwsh.read("Write-Host 'using namespace x'", "/proj").opaque)


class TestSizeCap(Project):
    BIG_PS = "Write-Host x\n" * (bash_gate.MAX_COMMAND_BYTES // 13 + 10)
    BIG_SH = "echo x\n" * (bash_gate.MAX_COMMAND_BYTES // 7 + 10)

    def test_over_the_cap_is_opaque_while_restricted(self) -> None:
        for tool, command in (("PowerShell", self.BIG_PS), ("Bash", self.BIG_SH)):
            with self.subTest(tool=tool):
                result, elapsed = self.judge(tool, command)
                self.assertIsNotNone(result)
                self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
                self.assertIn("KB", self.reason(result))
                self.assertLess(elapsed, BOUND_S)

    def test_over_the_cap_is_allowed_after_approval_unless_it_names_state(self) -> None:
        self.approve()
        for tool, command in (("PowerShell", self.BIG_PS), ("Bash", self.BIG_SH)):
            with self.subTest(tool=tool):
                result, _ = self.judge(tool, command)
                self.assertIsNone(result)
                result, _ = self.judge(tool, command + "x > .gatekit/config.json\n")
                self.assertIsNone(result)
                result, _ = self.judge(tool, command + "x > .gatekit/approvals.json\n")
                self.assertIsNotNone(result)
                self.assertIn("ADR-0027", self.reason(result))

    def test_over_the_cap_mention_scan_sees_through_ps_quoting(self) -> None:
        self.approve()
        for tail in ("Set-Content ('.gate' + 'kit/approvals.json') x\n",
                     "Set-Content .gate`kit\\approvals.json x\n",
                     "Set-Content GATEKI~1\\approvals.json x\n"):
            with self.subTest(tail=tail):
                result, _ = self.judge("PowerShell", self.BIG_PS + tail)
                self.assertIsNotNone(result, tail)
                self.assertIn("ADR-0027", self.reason(result))

    def test_a_worker_over_the_cap_is_denied(self) -> None:
        self.approve()
        os.environ["GATEKIT_TASK_ID"] = "t1"
        os.environ["GATEKIT_JOB_ID"] = "j1"
        for tool, command in (("PowerShell", self.BIG_PS), ("Bash", self.BIG_SH)):
            with self.subTest(tool=tool):
                result, _ = self.judge(tool, command)
                self.assertIsNotNone(result)

    def test_huge_input_is_linear(self) -> None:
        self.approve()
        command = "x " * (2 * 1024 * 1024)
        for tool in ("PowerShell", "Bash"):
            with self.subTest(tool=tool):
                result, elapsed = self.judge(tool, command)
                self.assertIsNone(result)
                self.assertLess(elapsed, BOUND_S)

    def test_cap_is_64_kb(self) -> None:
        self.assertEqual(bash_gate.MAX_COMMAND_BYTES, 64 * 1024)
        self.assertIs(ps_gate.MAX_COMMAND_BYTES, bash_gate.MAX_COMMAND_BYTES)


if __name__ == "__main__":
    unittest.main()

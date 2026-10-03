"""Tests for gatekit/pwsh.py and gates/powershell.py (ADR-0028).

The PowerShell tool's calls meet the decisions the Bash gate makes. Every
test is pure parsing — no ``pwsh`` is run — so the suite passes on any OS.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import approval, ledger, pwsh  # noqa: E402
from gatekit.gates import powershell as ps_gate  # noqa: E402

PLUGIN = pathlib.Path(__file__).resolve().parents[1]
GATE_SCRIPT = PLUGIN / "gatekit" / "gates" / "powershell.py"
TOOL = "PowerShell"


def encoded(text: str) -> str:
    return base64.b64encode(text.encode("utf-16-le")).decode("ascii")


def parse(command: str, cwd: str = "/proj"):
    """(sorted targets relative to *cwd*, opaque) for *command*."""
    found = pwsh.read(command, cwd)
    prefix = cwd.replace("\\", "/").rstrip("/") + "/"
    rel = sorted(t[len(prefix):] if t.startswith(prefix) else t for t in found.targets)
    return rel, found.opaque


# (command, expected targets relative to /proj, expected opaque)
TABLE = [
    # -- content cmdlets and their aliases ------------------------------
    ("Set-Content -Path src/x.ts -Value 1", ["src/x.ts"], False),
    ("Set-Content src\\x.ts 'hello'", ["src/x.ts"], False),
    ("sc src/x.ts hi", ["src/x.ts"], False),
    ("Add-Content -LiteralPath notes.txt -Value x", ["notes.txt"], False),
    ("ac log.txt x", ["log.txt"], False),
    ("Clear-Content log.txt", ["log.txt"], False),
    ("'x' | Out-File -FilePath out.txt", ["out.txt"], False),
    ("Get-Process | Out-File out.txt -Append -Encoding utf8", ["out.txt"], False),
    ("Get-Date | Tee-Object -FilePath t.log", ["t.log"], False),
    ("Get-Date | Tee-Object -Variable v", [], False),
    ("Get-Process | Export-Csv -Path p.csv -NoTypeInformation", ["p.csv"], False),
    ("Get-Process | ConvertTo-Json | Out-File p.json", ["p.json"], False),
    # -- items ----------------------------------------------------------
    ("New-Item -ItemType File -Path src/a.ts", ["src/a.ts"], False),
    ("New-Item -Path src -Name b.ts -ItemType File", ["src/b.ts"], False),
    ("ni c.ts -Force", ["c.ts"], False),
    ("mkdir build", ["build"], False),
    ("New-Item -ItemType Directory dist", ["dist"], False),
    ("Copy-Item a.ts b.ts", ["b.ts"], False),
    ("copy a.ts -Destination out\\b.ts", ["out/b.ts"], False),
    ("Copy-Item -Path a -Destination b -Recurse", ["b"], False),
    ("cp src/a.ts src/b.ts", ["src/b.ts"], False),
    ("Move-Item -Path a.ts -Destination lib/", ["lib"], False),
    ("mv a.ts b.ts", ["b.ts"], False),
    ("Remove-Item -Recurse -Force build", ["build"], False),
    ("del a.txt, b.txt", ["a.txt", "b.txt"], False),
    ("rm -rf build", ["build"], False),
    ("Rename-Item old.ts new.ts", ["new.ts"], False),
    ("ren src\\old.ts new.ts", ["src/new.ts"], False),
    ("Microsoft.PowerShell.Management\\Remove-Item x.txt", ["x.txt"], False),
    ("Invoke-WebRequest https://example.test/a -OutFile dl.zip", ["dl.zip"], False),
    ("Expand-Archive a.zip -DestinationPath out", ["out"], False),
    ("Set-Item Env:FOO bar", [], False),
    ("Remove-Item Env:GATEKIT_TASK_ID", [], False),
    # -- .NET -------------------------------------------------------------
    ("[IO.File]::WriteAllText('w.txt', 'x')", ["w.txt"], False),
    ('[System.IO.File]::AppendAllText("a.log", "x")', ["a.log"], False),
    ("[IO.File]::WriteAllBytes($p, $b)", [], True),
    ("[IO.File]::ReadAllText('r.txt')", [], False),
    ("Add-Type -TypeDefinition $src", [], True),
    ("$o = New-Object -ComObject Scripting.FileSystemObject", [], True),
    ("(Get-Item x).Delete()", [], True),
    ("[Reflection.Assembly]::LoadFile('a.dll')", [], True),
    # -- redirects --------------------------------------------------------
    ("echo hi > r.txt", ["r.txt"], False),
    ("echo hi >> r.txt", ["r.txt"], False),
    ("dir *> all.log", ["all.log"], False),
    ("npm test 2> err.log", ["err.log"], False),
    ("npm test 2>&1 > out.log", ["out.log"], False),
    ("echo hi>r2.txt", ["r2.txt"], False),
    ("Get-ChildItem > $null", [], False),
    # -- parameter spelling ---------------------------------------------
    ("Set-Content -Pa src/x.ts -Va 1", ["src/x.ts"], False),
    ("set-content -PATH src/x.ts -value 1", ["src/x.ts"], False),
    ("Set-Content -Path:src/x.ts -Value:1", ["src/x.ts"], False),
    ("Set-Content -Bogus 1 x.ts", [], True),
    ("Set-Content @params", [], True),
    # -- working directory ----------------------------------------------
    ("Set-Location src; Set-Content x.ts 1", ["src/x.ts"], False),
    ("cd src && sc x.ts 1", ["src/x.ts"], False),
    ("Push-Location src; Pop-Location; sc x.ts 1", ["x.ts"], False),
    ("Pop-Location; sc x.ts 1", [], True),
    # -- variables and expressions --------------------------------------
    ("Set-Content $env:TEMP\\x.txt 1", [], True),
    ('Set-Content "$dir\\x.ts" 1', [], True),
    ("Set-Content 'literal$x.ts' 1", ["literal$x.ts"], False),
    ('Set-Content "$PWD\\x.ts" 1', ["x.ts"], False),
    ("Set-Content (Join-Path src x.ts) 1", [], True),
    ("Get-ChildItem *.tmp | Remove-Item", [], True),
    ("ForEach-Object { Remove-Item $_ }", [], True),
    ("if ($true) { Set-Content x.ts 1 }", ["x.ts"], False),
    ("$null = New-Item y.ts", ["y.ts"], False),
    ("$out = 'z.ts'; Set-Content $out 1", [], True),
    ('Write-Output "a; Remove-Item x"', [], False),
    ('Write-Output "$(Remove-Item x.txt)"', ["x.txt"], False),
    # -- nested code ------------------------------------------------------
    ("iex 'Set-Content x.ts 1'", ["x.ts"], False),
    ("Invoke-Expression $code", [], True),
    ('pwsh -Command "Set-Content x.ts 1"', ["x.ts"], False),
    ("powershell -NoProfile -EncodedCommand " + encoded("Set-Content x.ts 1"), ["x.ts"], True),
    ("& 'python' -c \"open('x','w')\"", [], True),
    ("& $tool x", [], True),
    ("cmd /c \"echo x > y\"", [], True),
    ("bash -c 'echo x > y.txt'", ["y.txt"], False),
    ("Write-Output x --% > y", [], True),
    # -- interpreters and programs --------------------------------------
    ('python -c "print(1)"', [], True),
    ("'print(1)' | python", [], True),
    ("python script.py", [], False),
    ('py -3 -c "x"', [], True),
    ('node -e "x"', [], True),
    ("Start-Process notepad", [], False),
    ("Start-Process pwsh -ArgumentList '-c','x'", [], True),
    ("Start-Process npm -ArgumentList 'test' -RedirectStandardOutput out.log", ["out.log"], False),
    # -- quoting, here-strings, comments, continuation -------------------
    ("@'\nSet-Content inner.ts 1\n'@ | Set-Content -Path h.ts", ["h.ts"], False),
    ('@"\n$x and more\n"@ | Out-File h2.txt', ["h2.txt"], False),
    ("Set-Content `\n  -Path src/x.ts `\n  -Value 1", ["src/x.ts"], False),
    ("Set-Content src/a`'b.ts 1", ["src/a'b.ts"], False),
    ("Set-Content 'it''s.txt' 1", ["it's.txt"], False),
    ("# Set-Content x.ts\nGet-ChildItem", [], False),
    ("<# Remove-Item x #> Get-Date", [], False),
    # -- reads, git, npm --------------------------------------------------
    ("Get-Content src/x.ts", [], False),
    ("Get-ChildItem -Recurse src | Select-String foo", [], False),
    ("Test-Path .gatekit\\approvals.json", [], False),
    ('git status; git add -A; git commit -m "a > b"', [], False),
    ("git checkout -- src/x.ts", [], True),
    ("npm install; npx vitest run", [], False),
    # -- spellings PowerShell treats alike ------------------------------
    ("Set-Content \u2018src/q.ts\u2019 1", ["src/q.ts"], False),
    ("Set-Content \u201csrc/q.ts\u201d 1", ["src/q.ts"], False),
    ("Set-Content \u2013Path src/q.ts \u2013Value 1", ["src/q.ts"], False),
    ("Set-Content -Path:'src/q.ts' -Value 1", ["src/q.ts"], False),
    ("& (Get-Command Set-Content) src/x.ts 1", [], True),
    (".(gcm sc) src/x.ts 1", [], True),
    ("Set-Alias w Set-Content; w src/x.ts 1", [], True),
    # -- Windows paths ----------------------------------------------------
    ("Set-Content 'x.ts::$DATA' 1", ["x.ts"], False),
    ("Set-Content 'x.ts.' 1", ["x.ts"], False),
]


class TestParserTable(unittest.TestCase):
    def test_table_is_large_enough(self) -> None:
        self.assertGreaterEqual(len(TABLE), 40)

    def test_table(self) -> None:
        for command, targets, opaque in TABLE:
            with self.subTest(command=command):
                self.assertEqual(parse(command), (targets, opaque))


class TestParserDetails(unittest.TestCase):
    def test_removed_and_copies_are_recorded(self) -> None:
        found = pwsh.read("Move-Item a.ts lib\\b.ts", "/proj")
        self.assertEqual(found.removed, ["/proj/a.ts"])
        self.assertEqual(found.copies, [(["/proj/a.ts"], "/proj/lib/b.ts", ["a.ts"])])
        found = pwsh.read("Rename-Item src\\old.ts new.ts", "/proj")
        self.assertEqual(found.removed, ["/proj/src/old.ts"])

    def test_remove_records_removed(self) -> None:
        found = pwsh.read("Remove-Item -LiteralPath a, b", "/proj")
        self.assertEqual(sorted(found.removed), ["/proj/a", "/proj/b"])

    def test_link_target_is_recorded(self) -> None:
        found = pwsh.read("New-Item -ItemType SymbolicLink -Path l -Target .gatekit", "/proj")
        self.assertEqual(found.targets, ["/proj/l"])
        self.assertIn("/proj/.gatekit", found.linked)

    def test_windows_drive_and_long_path_prefix(self) -> None:
        self.assertEqual(parse("Set-Content C:\\proj\\x.ts 1", "C:\\proj"), (["x.ts"], False))
        self.assertEqual(parse("Set-Content \\\\?\\C:\\proj\\x.ts 1", "C:\\proj"), (["x.ts"], False))
        self.assertEqual(parse("Set-Content \\x.ts 1", "C:\\proj"), (["C:/x.ts"], False))
        self.assertEqual(parse("Set-Content FileSystem::C:\\proj\\y.ts 1", "C:\\proj"),
                         (["y.ts"], False))

    def test_tilde_expands(self) -> None:
        found = pwsh.read("Set-Content ~/x.txt 1", "/proj")
        self.assertEqual(found.targets, [os.path.expanduser("~").replace("\\", "/") + "/x.txt"])

    def test_assignment_is_recorded_for_the_protected_check(self) -> None:
        found = pwsh.read("$d = '.gatekit'; Set-Content \"$d\\approvals.json\" x", "/proj")
        self.assertTrue(found.opaque)
        self.assertEqual(found.assigns.get("d"), ".gatekit")
        self.assertTrue(any("$d" in raw for raw in found.dollar))

    def test_unknown_cwd_records_cwds(self) -> None:
        found = pwsh.read("cd .gatekit; Set-Content approvals.json x", "/proj")
        self.assertIn("/proj/.gatekit", found.cwds)
        self.assertEqual(found.targets, ["/proj/.gatekit/approvals.json"])

    def test_unbalanced_quote_is_opaque(self) -> None:
        self.assertTrue(parse("Set-Content 'x.ts 1")[1])

    def test_deep_nesting_is_opaque(self) -> None:
        cmd = "iex 'Set-Content x 1'"
        for _ in range(6):
            cmd = "iex '%s'" % cmd.replace("'", "''")
        self.assertTrue(parse(cmd)[1])

    def test_bad_encoded_command_is_opaque(self) -> None:
        self.assertTrue(parse("pwsh -enc not-base64!!")[1])

    def test_mention_text_sees_through_backticks_and_concatenation(self) -> None:
        found = pwsh.read("iex ('Set-Content .gate' + 'kit/approvals.json x')", "/proj")
        self.assertTrue(found.opaque)
        self.assertIn(".gatekit/approvals.json", pwsh.mention_text(
            "iex ('Set-Content .gate' + 'kit/approvals.json x')", found))
        found = pwsh.read("pwsh -enc " + encoded("Set-Content .gatekit/a.json x"), "/proj")
        self.assertIn(".gatekit/a.json", pwsh.mention_text("", found))


class TestApproveDetection(unittest.TestCase):
    def test_denied_forms(self) -> None:
        for cmd in (
            "python C:\\gk\\plugin\\bin\\gatekit.py approve spec/05-gate.md",
            '& python "$env:CLAUDE_PLUGIN_ROOT\\bin\\gatekit.py" approve spec\\05-gate.md',
            "$env:GATEKIT_TASK_ID=''; py -3 bin\\gatekit.py approve spec/05-gate.md",
            "Remove-Item Env:GATEKIT_TASK_ID; python bin/gatekit.py approve --note x spec/05-gate.md",
            'pwsh -Command "python bin/gatekit.py approve spec/05-gate.md"',
            "Start-Process python -ArgumentList 'bin\\gatekit.py','approve','spec/05-gate.md'",
            "python -m gatekit approve spec/05-gate.md",
            "python bin/gatekit.py approve --root . spec/05-gate.md",
            "python bin/gatekit.`py approve spec/05-gate.md",
            "pwsh -enc " + encoded("python bin/gatekit.py approve spec/05-gate.md"),
        ):
            with self.subTest(cmd=cmd):
                self.assertTrue(pwsh.invokes_gatekit_approve(cmd))

    def test_review_forms(self) -> None:
        for cmd in (
            "python3 bin/gatekit.py ap''prove x",
            'python3 bin/gatekit.py app""rove x',
            "python3 bin/gatekit.py ('ap'+'prove') x",
            "python3 bin/gatekit.py $('approve') x",
            "python3 bin/gatekit.py <#c#> approve x",
            "python3 -m gatekit `\n approve x",
            "python3 -mgatekit approve x",
            "$g='bin/gatekit.py'; python3 $g approve x",
            "python3 -m gatekit.approval spec/05-gate.md",
            "python3 -m gatekit.cli approve x",
        ):
            with self.subTest(cmd=cmd):
                self.assertTrue(pwsh.invokes_gatekit_approve(cmd))

    def test_detector_is_linear(self) -> None:
        import time
        start = time.monotonic()
        pwsh.invokes_gatekit_approve("gatekit " * 50000)
        self.assertLess(time.monotonic() - start, 2.0)

    def test_allowed_forms(self) -> None:
        for cmd in (
            "python bin/gatekit.py approve check spec/05-gate.md",
            "python bin\\gatekit.py approve list",
            "python bin/gatekit.py approve --root . check spec/05-gate.md",
            "python bin/gatekit.py jobs status",
            "Select-String -Pattern approve src/a.ts",
        ):
            with self.subTest(cmd=cmd):
                self.assertFalse(pwsh.invokes_gatekit_approve(cmd))


# --------------------------------------------------------------------------
# hook level
# --------------------------------------------------------------------------
def run_gate_subprocess(event: dict, env_extra: "dict | None" = None, raw: "str | None" = None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
    env.pop("PYTHONPATH", None)
    env.update(env_extra or {})
    proc = subprocess.run(
        [sys.executable, str(GATE_SCRIPT)],
        input=raw if raw is not None else json.dumps(event),
        capture_output=True, text=True, env=env, timeout=30)
    return proc.returncode, proc.stdout, proc.stderr


class PSProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        (self.root / "spec" / "05-gate.md").write_text("# Gate\n", encoding="utf-8")
        self._env = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("GATEKIT_")}

    def tearDown(self) -> None:
        for key in list(os.environ):
            if key.startswith("GATEKIT_"):
                del os.environ[key]
        os.environ.update(self._env)
        self._tmp.cleanup()

    def event(self, command: str, cwd: "str | None" = None, tool: str = TOOL) -> dict:
        return {"session_id": "sess-ps", "hook_event_name": "PreToolUse",
                "cwd": cwd or str(self.root), "tool_name": tool,
                "tool_input": {"command": command, "description": "d"}}

    def run_ps(self, command: str, **kwargs):
        return ps_gate.handle(self.event(command, **kwargs))

    def approve(self) -> None:
        approval.approve(self.root, "spec/05-gate.md")

    def reason(self, result: dict) -> str:
        return result["hookSpecificOutput"]["permissionDecisionReason"]

    def assertDenied(self, command: str, needle: str = "") -> None:  # noqa: N802
        result = self.run_ps(command)
        self.assertIsNotNone(result, command)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny", command)
        if needle:
            self.assertIn(needle, self.reason(result), command)

    def assertAllowed(self, command: str) -> None:  # noqa: N802
        result = self.run_ps(command)
        self.assertIsNone(result, "%s -> %s" % (command, result and self.reason(result)))


READS = (
    "Get-Content src/x.ts",
    "Get-ChildItem -Recurse -Filter *.ts src",
    "gci src | Select-String -Pattern TODO",
    "Test-Path .gatekit\\approvals.json",
    "Get-Content .gatekit\\approvals.json | ConvertFrom-Json",
    "git status; git diff; git log --oneline -5",
    "git add -A; git commit -m \"feat: x > y\"",
    "npm test",
    "npx vitest run",
    "npm run build 2>&1 | Select-String error",
    "python -m pytest -q",
)


class TestSpecBeforeCode(PSProject):
    def test_write_into_code_denied_before_approval(self) -> None:
        for cmd in ("Set-Content src/x.ts 'x'", "'x' > src\\x.ts", "New-Item -ItemType File src/a.ts",
                    "Copy-Item spec/01-prd.md src/x.ts", "[IO.File]::WriteAllText('src/x.ts','x')"):
            self.assertDenied(cmd, "src/x.ts" if "a.ts" not in cmd else "src/a.ts")

    def test_spec_docs_and_markdown_allowed_before_approval(self) -> None:
        self.assertAllowed("Set-Content spec/01-prd.md '# PRD'")
        self.assertAllowed("'notes' | Out-File docs\\notes.md")
        self.assertAllowed("Add-Content README.md x")

    def test_reads_git_and_npm_allowed_before_approval(self) -> None:
        for cmd in READS:
            with self.subTest(cmd=cmd):
                self.assertAllowed(cmd)

    def test_opaque_denied_before_approval(self) -> None:
        for cmd in ("python -c \"open('x','w')\"", "iex $code", "Set-Content $p x",
                    "Get-ChildItem *.tmp | Remove-Item"):
            self.assertDenied(cmd, "cannot determine")

    def test_reviewed_forms_denied_before_approval(self) -> None:
        for cmd in ("Start-Process git 'clean -fdx'", "Start-Process python3.12 '-c x'",
                    "Start-Process robocopy 'src out /E'",
                    "gci | % Delete", "Save-Help -DestinationPath src/help",
                    "New-ModuleManifest -Path src/m.psd1", "Unblock-File src/x.ts",
                    "Get-Process | epal -Path src/a.txt"):
            with self.subTest(cmd=cmd):
                self.assertDenied(cmd)

    def test_member_names_that_only_read_stay_allowed(self) -> None:
        self.assertAllowed("Get-ChildItem src | % FullName")
        self.assertAllowed("Get-ChildItem src | ForEach-Object Name")

    def test_after_approval_writes_and_opaque_allowed(self) -> None:
        self.approve()
        for cmd in ("Set-Content src/x.ts 'x'", "'x' > src\\x.ts", "iex $code",
                    "python -c \"open('x','w')\""):
            self.assertAllowed(cmd)

    def test_no_spec_dir_allows(self) -> None:
        (self.root / "spec" / "05-gate.md").unlink()
        (self.root / "spec").rmdir()
        self.assertAllowed("Set-Content src/x.ts x")

    def test_cd_inside_command_and_event_cwd(self) -> None:
        self.assertDenied("cd src; Set-Content x.ts 1")
        self.assertAllowed("Set-Location spec; Set-Content 01-prd.md 1")
        (self.root / "src").mkdir()
        result = self.run_ps("Set-Content x.ts 1", cwd=str(self.root / "src"))
        self.assertIsNotNone(result)

    def test_other_tools_are_ignored(self) -> None:
        self.assertIsNone(self.run_ps("Set-Content src/x.ts 1", tool="Bash"))
        self.assertIsNone(self.run_ps("Set-Content src/x.ts 1", tool="Read"))

    def test_missing_or_non_string_command_allowed(self) -> None:
        event = self.event("")
        self.assertIsNone(ps_gate.handle(event))
        event["tool_input"] = {"command": ["x"]}
        self.assertIsNone(ps_gate.handle(event))

    def test_reason_in_korean(self) -> None:
        led = ledger.Ledger.load(self.root, "sess-ps")
        led.set_output_lang("ko")
        led.save()
        result = self.run_ps("Set-Content src/x.ts 1")
        self.assertIn("승인", self.reason(result))
        result = self.run_ps("iex $code")
        self.assertRegex(self.reason(result), "[가-힣]")


class TestProtectedState(PSProject):
    DENIED = (
        "Set-Content .gatekit\\approvals.json x",
        "'x' > .gatekit/contract.json",
        "Remove-Item -Recurse -Force .gatekit",
        "Copy-Item evil.json .gatekit\\approvals.json",
        "Copy-Item evil.json .gatekit",
        "cd .gatekit; Set-Content approvals.json x",
        "Set-Content .GATEKIT\\Approvals.JSON x",
        "Set-Content '.gatekit\\approvals.json::$DATA' x",
        "Set-Content .gatekit\\approvals.json. x",
        "iex 'Set-Content .gatekit/approvals.json x'",
        "iex ('Set-Content .gate' + 'kit/approvals.json x')",
        "Set-Content .gate`kit\\approvals.json x",
        "pwsh -enc " + encoded("Set-Content .gatekit/approvals.json x"),
        "$d = '.gatekit'; Set-Content \"$d\\approvals.json\" x",
        "New-Item -ItemType SymbolicLink -Path l -Target .gatekit",
        "Rename-Item .gatekit\\approvals.json a.bak",
        "Move-Item .gatekit\\approvals.json x.json",
        "[IO.File]::WriteAllText('.gatekit\\approvals.json','x')",
        "[IO.File]::WriteAllText($p + 'GATEKI~1\\approvals.json', 'x')",
        "Clear-Content .gatekit\\runs\\contract-last.json",
        "bash -c 'echo x > .gatekit/approvals.json'",
        "Set-Content \u2018.gatekit\\approvals.json\u2019 x",
        "Set-Content -Path:'.gatekit\\approvals.json' -Value x",
        "Get-Item .gatekit\\approvals.json | Remove-Item",
        "Set-Content -Path ([IO.Path]::Combine('.gatekit','approvals.json')) -Value x",
        "Remove-Item -Recurse -Force .",
    )

    # ADR-0028 review: forms a separate review pass found allowed.
    REVIEWED = (
        "Set-Content .gatekit/state.json x; echo $",
        "Set-Content .gatekit/state.json x; Write-Output @",
        "using namespace System.IO; [File]::WriteAllText('.gatekit/state.json','x')",
        "([type]'IO.File')::WriteAllText('.gatekit/state.json','x')",
        "$t=[IO.File]; $t::WriteAllText('.gatekit/state.json','x')",
        "[IO.File]::'WriteAllText'('.gatekit/state.json','x')",
        "[System.IO.File, mscorlib]::Delete('.gatekit/state.json')",
        "Get-Item -Force .gatekit/state.json | % Delete",
        "Get-Item -Force .gatekit/state.json | ForEach-Object -MemberName MoveTo -ArgumentList x",
        "Set-Item alias:zz Set-Content; zz .gatekit/state.json x",
        "${function:zz} = { Set-Content $args[0] x }; zz .gatekit/state.json",
        "'x' | Set-Content -- .gatekit/state.json",
        "New-PSDrive G FileSystem .gatekit; sc G:\\state.json x",
        "Start-Transcript -OutputDirectory .gatekit",
        "Remove-Item * -Recurse -Force",
        "Remove-Item .\\* -Recurse",
        "[Environment]::CurrentDirectory = (Resolve-Path .gatekit); [IO.File]::WriteAllText('state.json','x')",
        "pwsh -wd .gatekit -c 'sc state.json x'",
        "pwsh -WorkingDirectory .gatekit -Command 'sc state.json x'",
        "Start-Job -WorkingDirectory .gatekit { sc state.json x }",
        "$PWD = '.gatekit'; Set-Content $PWD/state.json x",
        "Set-Content src/x.ps1 'Set-Content .gatekit/state.json x'; & ./src/x.ps1",
        "Start-Process git 'checkout -- .gatekit'",
        "Start-Process tar '-xf a.tar -C .gatekit'",
        "Unblock-File .gatekit/state.json",
    )

    def test_reviewed_forms_denied_after_approval(self) -> None:
        self.approve()
        for cmd in self.REVIEWED + (
                "pwsh -EncodedCommand:" + encoded("Set-Content .gatekit/state.json x"),
                "pwsh -enc '%s'" % (lambda b: b[:8] + " " + b[8:])(
                    encoded("Set-Content .gatekit/state.json x"))):
            with self.subTest(cmd=cmd):
                self.assertDenied(cmd)

    def test_reader_never_raises_on_deep_nesting(self) -> None:
        cmd = "Set-Content .gatekit/state.json x; " + '"$(' * 900 + ")" * 900
        self.approve()
        self.assertDenied(cmd)

    def check_all_denied(self) -> None:
        for cmd in self.DENIED + ("Set-Content \\\\?\\%s\\.gatekit\\approvals.json x" % self.root,):
            with self.subTest(cmd=cmd):
                self.assertDenied(cmd, "ADR-0027")

    def test_denied_before_approval(self) -> None:
        self.check_all_denied()

    def test_denied_after_approval(self) -> None:
        self.approve()
        self.check_all_denied()

    def test_denied_with_no_restriction_at_all(self) -> None:
        (self.root / "spec" / "05-gate.md").unlink()
        (self.root / "spec").rmdir()
        self.check_all_denied()

    def test_user_owned_and_reads_allowed(self) -> None:
        self.approve()
        for cmd in ("Set-Content .gatekit\\config.json '{}'",
                    "'log' > .gatekit\\eval\\run.log",
                    "Get-Content .gatekit\\approvals.json",
                    "python bin/gatekit.py contract derive",
                    "python bin\\gatekit.py approve spec/05-gate.md"):
            with self.subTest(cmd=cmd):
                self.assertAllowed(cmd)


class TestTaskScope(PSProject):
    def setUp(self) -> None:
        super().setUp()
        self.approve()
        task_dir = self.root / ".gatekit" / "jobs" / "job-1" / "tasks" / "auth"
        task_dir.mkdir(parents=True)
        self.task_json = task_dir / "task.json"
        self.task_json.write_text(json.dumps({"id": "auth", "write_scope": ["src/auth/**"]}))
        os.environ["GATEKIT_TASK_ID"] = "auth"
        os.environ["GATEKIT_JOB_ID"] = "job-1"

    def test_inside_scope_allowed(self) -> None:
        self.assertAllowed("Set-Content src\\auth\\token.ts x")
        self.assertAllowed("cd src/auth; 'x' | Out-File token.ts")

    def test_outside_scope_denied(self) -> None:
        self.assertDenied("Set-Content src\\other.ts x", "src/auth/**")
        self.assertDenied("cd src/auth; Set-Content ..\\other.ts x")
        self.assertDenied("Set-Content src/auth/a.ts x; Set-Content spec/01-prd.md x")

    def test_opaque_denied(self) -> None:
        self.assertDenied("git checkout -- src/auth/a.ts", "cannot determine")
        self.assertDenied("Set-Content $env:OUT x", "cannot determine")

    def test_read_only_task(self) -> None:
        self.task_json.write_text(json.dumps({"id": "auth", "write_scope": "read-only"}))
        self.assertDenied("Set-Content src/auth/token.ts x")
        self.assertAllowed("Get-Content src/auth/token.ts | Measure-Object -Line")

    def test_outside_root_denied(self) -> None:
        self.assertDenied("Set-Content C:\\escape\\x.ts x")
        self.assertDenied("Set-Content /tmp/escape.ts x")


class TestEvaluatorScratch(PSProject):
    def setUp(self) -> None:
        super().setUp()
        self.approve()
        edir = self.root / ".gatekit" / "jobs" / "job-eval" / "evaluate"
        edir.mkdir(parents=True)
        (edir / "task.json").write_text(json.dumps({"id": "evaluate", "write_scope": "read-only"}))
        os.environ["GATEKIT_TASK_ID"] = "evaluate"
        os.environ["GATEKIT_JOB_ID"] = "job-eval"

    def test_scratch_allowed(self) -> None:
        self.assertAllowed("New-Item -ItemType Directory -Force .gatekit\\eval")
        self.assertAllowed("npx playwright test *> .gatekit\\eval\\run.log")
        self.assertAllowed("Set-Content .gatekit/eval/drive.mjs x")

    def test_other_writes_denied(self) -> None:
        self.assertDenied("Set-Content .gatekit\\approvals.json x")
        self.assertDenied("Set-Content src\\app.ts x")
        self.assertDenied("Set-Content .gatekit\\eval\\a x; Set-Content src\\app.ts x")


class TestWorkerNeverApproves(PSProject):
    def setUp(self) -> None:
        super().setUp()
        self.approve()
        os.environ["GATEKIT_TASK_ID"] = "auth"
        os.environ["GATEKIT_JOB_ID"] = "job-1"

    def test_denied(self) -> None:
        for cmd in ("Remove-Item Env:GATEKIT_TASK_ID; python bin\\gatekit.py approve spec/05-gate.md",
                    "& python \"$env:CLAUDE_PLUGIN_ROOT\\bin\\gatekit.py\" approve spec\\05-gate.md",
                    "python -m gatekit approve spec/05-gate.md"):
            with self.subTest(cmd=cmd):
                self.assertDenied(cmd, "never approves")

    def test_check_and_list_not_refused_as_approval(self) -> None:
        for cmd in ("python bin\\gatekit.py approve check spec/05-gate.md",
                    "python bin/gatekit.py approve list"):
            result = self.run_ps(cmd)
            if result is not None:
                self.assertNotIn("never approves", self.reason(result))

    def test_host_session_may_approve(self) -> None:
        del os.environ["GATEKIT_TASK_ID"]
        self.assertAllowed("python bin\\gatekit.py approve spec/05-gate.md")

    def test_korean_reason(self) -> None:
        led = ledger.Ledger.load(self.root, "sess-ps")
        led.set_output_lang("ko")
        led.save()
        result = self.run_ps("python bin/gatekit.py approve spec/05-gate.md")
        self.assertRegex(self.reason(result), "[가-힣]")


class TestSubprocessContract(PSProject):
    def test_deny_is_json_exit_zero(self) -> None:
        code, out, _ = run_gate_subprocess(self.event("Set-Content src/x.ts 1"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_allow_prints_nothing(self) -> None:
        code, out, _ = run_gate_subprocess(self.event("Get-ChildItem"))
        self.assertEqual((code, out.strip()), (0, ""))

    def test_internal_error_exits_zero(self) -> None:
        code, out, _ = run_gate_subprocess({}, raw="not json")
        self.assertEqual((code, out.strip()), (0, ""))
        event = self.event("x")
        event["tool_input"] = "not a dict"
        code, out, _ = run_gate_subprocess(event)
        self.assertEqual(code, 0)

    def test_reader_crash_exits_zero(self) -> None:
        original = pwsh.read

        def boom(*_a, **_k):
            raise RuntimeError("reader exploded")

        pwsh.read = boom
        try:
            from gatekit import hookio
            import io
            code = hookio.run(ps_gate.handle, stdin=io.StringIO(json.dumps(
                self.event("Set-Content src/x.ts 1"))), exit_process=False)
        finally:
            pwsh.read = original
        self.assertEqual(code, 0)
        log = self.root / ".gatekit" / "runs" / "hook-errors.log"
        self.assertIn("reader exploded", log.read_text(encoding="utf-8"))


class TestRegistration(unittest.TestCase):
    def test_hooks_json_routes_powershell_to_this_gate(self) -> None:
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        entries = [e for e in hooks["hooks"]["PreToolUse"]
                   if "PowerShell" in e.get("matcher", "").split("|")]
        self.assertEqual(len(entries), 1)
        command = entries[0]["hooks"][0]["command"]
        self.assertIn("gates/powershell.py", command)
        self.assertIn("|| py -3", command)

    def test_doctor_requires_the_gate(self) -> None:
        from gatekit import doctor

        self.assertIn("powershell.py", doctor.GATE_SCRIPTS)


if __name__ == "__main__":
    unittest.main()

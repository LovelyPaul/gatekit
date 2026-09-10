#!/usr/bin/env python3
"""test_tools.py — fault-injection tests for the tools/gate_*.py CI gates.

Each test builds a minimal, throwaway repo tree under a TemporaryDirectory,
injects exactly one fault the corresponding gate is supposed to catch, and
asserts the gate exits 1 with a finding that mentions the fault. A second
test per gate builds a clean tree and asserts exit 0. This is the CI gate
for the gates themselves: if a gate's logic regresses, one of these should
fail before it reaches main.

Run directly:
    python3 tools/test_tools.py -v

Or via the aggregate runner:
    python3 tools/run_tests.py
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

TOOLS_DIR = pathlib.Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent


def run_gate(script: str, root: pathlib.Path, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(TOOLS_DIR / script), "--root", str(root), "--json"]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def write(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def minimal_clean_repo(root: pathlib.Path) -> None:
    """A tree with the minimum structure every gate expects to find clean."""
    write(root / ".claude-plugin" / "marketplace.json", json.dumps({
        "name": "gatekit",
        "plugins": [{"name": "gatekit", "source": "./plugin"}],
    }))
    write(root / "plugin" / ".claude-plugin" / "plugin.json", json.dumps({
        "name": "gatekit",
        "version": "0.1.0",
        "commands": "./commands",
        "skills": "./skills",
    }))
    write(root / "plugin" / "hooks" / "hooks.json", json.dumps({
        "hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/gatekit/gates/stop.py"'}]}]
        }
    }))
    write(root / "plugin" / "gatekit" / "gates" / "stop.py", "# stop gate\n")
    write(root / "plugin" / "bin" / "gatekit.py", "# launcher\n")
    write(root / "plugin" / "gatekit" / "cli.py", 'SUBCOMMANDS = {\n    "doctor": ("gatekit.doctor", "x"),\n    "spec": ("gatekit.spec", "x"),\n}\n')
    write(root / "plugin" / "commands" / "build.md", (
        "---\nallowed-tools: Read, Bash\n---\n"
        "# /gatekit:build\n\nSee policy/verification.md. Output follows output_lang.\n"
    ))
    write(root / "plugin" / "skills" / "build" / "SKILL.md", (
        "---\nallowed-tools: Read\n---\n# build trigger\nSee the build command.\n"
    ))
    write(root / "CHANGELOG.md", "# Changelog\n\n## 0.1.0 — 2026-09-10\n\n- initial\n")
    write(root / "README.md", "# gatekit\n\nCommands: /gatekit:build\n")
    write(root / "README.ko.md", "# gatekit\n\n명령어: /gatekit:build\n")


class TestNoAbsPaths(unittest.TestCase):
    def test_clean_repo_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            proc = run_gate("gate_no_abs_paths.py", root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_abs_path_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "docs" / "notes.md", "see /Users/alice/project/file.txt for details\n")
            proc = run_gate("gate_no_abs_paths.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(any("notes.md" in f["path"] for f in payload["findings"]))

    def test_windows_style_path_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "docs" / "win.md", r"path: C:\Users\bob\file.txt" + "\n")
            proc = run_gate("gate_no_abs_paths.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_own_fixtures_are_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "tools" / "tests" / "fixtures" / "abs_path.txt", "/Users/alice/x\n")
            proc = run_gate("gate_no_abs_paths.py", root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class TestSkillSize(unittest.TestCase):
    def test_clean_repo_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            proc = run_gate("gate_skill_size.py", root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_oversized_skill_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            body = "---\nallowed-tools: Read\n---\n" + "\n".join(f"line {i}" for i in range(50))
            write(root / "plugin" / "skills" / "big" / "SKILL.md", body)
            proc = run_gate("gate_skill_size.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(any("big/SKILL.md" in f["path"] for f in payload["findings"]))

    def test_oversized_command_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            body = "---\nallowed-tools: Read\n---\n" + "\n".join(f"line {i}" for i in range(200))
            write(root / "plugin" / "commands" / "huge.md", body)
            proc = run_gate("gate_skill_size.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_ask_user_question_inline_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(
                root / "plugin" / "commands" / "asks.md",
                "---\nallowed-tools: Read, AskUserQuestion, Bash\n---\n# cmd\n",
            )
            proc = run_gate("gate_skill_size.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(any("AskUserQuestion" in f["message"] for f in payload["findings"]))

    def test_ask_user_question_block_list_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(
                root / "plugin" / "skills" / "asks" / "SKILL.md",
                "---\nallowed-tools:\n  - Read\n  - AskUserQuestion\n---\n# trigger\n",
            )
            proc = run_gate("gate_skill_size.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(any("AskUserQuestion" in f["message"] for f in payload["findings"]))


class TestBlobSize(unittest.TestCase):
    def test_clean_repo_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            proc = run_gate("gate_blob_size.py", root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_oversized_blob_via_sparse_file_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            big = root / "assets" / "big.bin"
            big.parent.mkdir(parents=True, exist_ok=True)
            with big.open("wb") as fh:
                fh.seek(1024 * 1024 + 1)
                fh.write(b"\0")
            proc = run_gate("gate_blob_size.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(any("big.bin" in f["path"] for f in payload["findings"]))


class TestForbiddenPhrases(unittest.TestCase):
    def test_clean_repo_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            proc = run_gate("gate_forbidden_phrases.py", root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_execute_immediately_in_skill_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(
                root / "plugin" / "skills" / "bad" / "SKILL.md",
                "---\nallowed-tools: Read\n---\nEXECUTE IMMEDIATELY when this triggers.\n",
            )
            proc = run_gate("gate_forbidden_phrases.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_step_one_in_skill_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(
                root / "plugin" / "skills" / "bad2" / "SKILL.md",
                "---\nallowed-tools: Read\n---\nStep 1: do the thing\n",
            )
            proc = run_gate("gate_forbidden_phrases.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_command_missing_policy_reference_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(
                root / "plugin" / "commands" / "nopolicy.md",
                "---\nallowed-tools: Read\n---\n# /gatekit:nopolicy\n\nOutput follows output_lang.\n",
            )
            proc = run_gate("gate_forbidden_phrases.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(any("policy/" in f["message"] for f in payload["findings"]))

    def test_command_missing_output_lang_reference_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(
                root / "plugin" / "commands" / "nolang.md",
                "---\nallowed-tools: Read\n---\n# /gatekit:nolang\n\nSee policy/verification.md.\n",
            )
            proc = run_gate("gate_forbidden_phrases.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(any("output_lang" in f["message"] for f in payload["findings"]))


class TestManifest(unittest.TestCase):
    def test_clean_repo_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            proc = run_gate("gate_manifest.py", root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_missing_hook_script_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            (root / "plugin" / "gatekit" / "gates" / "stop.py").unlink()
            proc = run_gate("gate_manifest.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(any("stop.py" in f["message"] for f in payload["findings"]))

    def test_empty_hook_script_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "plugin" / "gatekit" / "gates" / "stop.py", "")
            proc = run_gate("gate_manifest.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_version_mismatch_with_changelog_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "CHANGELOG.md", "# Changelog\n\n## 0.2.0 — 2026-09-11\n\n- newer\n")
            proc = run_gate("gate_manifest.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(any("0.2.0" in f["message"] for f in payload["findings"]))

    def test_non_semver_version_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            plugin_json_path = root / "plugin" / ".claude-plugin" / "plugin.json"
            data = json.loads(plugin_json_path.read_text())
            data["version"] = "v1"
            write(plugin_json_path, json.dumps(data))
            proc = run_gate("gate_manifest.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_invalid_json_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "plugin" / "hooks" / "hooks.json", "{not valid json")
            proc = run_gate("gate_manifest.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_missing_marketplace_source_dir_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / ".claude-plugin" / "marketplace.json", json.dumps({
                "name": "gatekit",
                "plugins": [{"name": "gatekit", "source": "./nonexistent"}],
            }))
            proc = run_gate("gate_manifest.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)


class TestReadmeSync(unittest.TestCase):
    def test_clean_repo_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            proc = run_gate("gate_readme_sync.py", root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_readme_missing_a_command_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "plugin" / "commands" / "verify.md", (
                "---\nallowed-tools: Read\n---\n# /gatekit:verify\n\nSee policy/. output_lang applies.\n"
            ))
            # README.md not updated with the new command.
            proc = run_gate("gate_readme_sync.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(any("verify" in f["message"] for f in payload["findings"]))

    def test_readme_and_ko_readme_mismatch_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "plugin" / "commands" / "doctor.md", (
                "---\nallowed-tools: Read\n---\n# /gatekit:doctor\n\nSee policy/. output_lang applies.\n"
            ))
            write(root / "README.md", "# gatekit\n\nCommands: /gatekit:build /gatekit:doctor\n")
            # README.ko.md not updated with /gatekit:doctor.
            proc = run_gate("gate_readme_sync.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_readme_extra_command_not_shipped_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "README.md", "# gatekit\n\nCommands: /gatekit:build /gatekit:ghost\n")
            proc = run_gate("gate_readme_sync.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(any("ghost" in f["message"] for f in payload["findings"]))


class TestCommandInvocations(unittest.TestCase):
    def test_clean_repo_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "plugin" / "commands" / "doctor.md",
                  '---\nallowed-tools: Bash\n---\nRun `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" doctor`. policy/ output_lang\n')
            proc = run_gate("gate_command_invocations.py", root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_module_form_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "plugin" / "commands" / "x.md", "python3 -m gatekit doctor\n")
            proc = run_gate("gate_command_invocations.py", root)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("launcher", proc.stdout)

    def test_cd_into_plugin_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "plugin" / "commands" / "x.md",
                  'cd "${CLAUDE_PLUGIN_ROOT}" && python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" doctor\n')
            proc = run_gate("gate_command_invocations.py", root)
            self.assertEqual(proc.returncode, 1)

    def test_unregistered_subcommand_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "plugin" / "commands" / "x.md",
                  'python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" frobnicate\n')
            proc = run_gate("gate_command_invocations.py", root)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("frobnicate", proc.stdout)

    def test_missing_launcher_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            (root / "plugin" / "bin" / "gatekit.py").unlink()
            proc = run_gate("gate_command_invocations.py", root)
            self.assertEqual(proc.returncode, 1)


class TestManifestHooksDuplicate(unittest.TestCase):
    def test_duplicate_hooks_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            pj = root / "plugin" / ".claude-plugin" / "plugin.json"
            data = json.loads(pj.read_text())
            data["hooks"] = "./hooks/hooks.json"
            pj.write_text(json.dumps(data))
            proc = run_gate("gate_manifest.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout)
            self.assertIn("loaded automatically", proc.stdout)

    def test_missing_standard_hooks_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            (root / "plugin" / "hooks" / "hooks.json").unlink()
            proc = run_gate("gate_manifest.py", root)
            self.assertEqual(proc.returncode, 1, proc.stdout)


class TestManualAccuracy(unittest.TestCase):
    def _manual_repo(self, root: pathlib.Path) -> None:
        minimal_clean_repo(root)
        write(root / "plugin" / "spec-kit" / "templates" / "ko" / "01-prd.md", "# prd\n")
        write(root / "docs" / "manual" / "00-index.md",
              "# index\n\n- [소개](01-intro.md)\n")
        write(root / "docs" / "manual" / "01-intro.md",
              '# intro\n\n`python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" doctor`\n\n/gatekit:build\n\n01-prd.md\n')

    def test_clean_manual_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._manual_repo(root)
            proc = run_gate("gate_manual_accuracy.py", root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_module_form_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._manual_repo(root)
            write(root / "docs" / "manual" / "01-intro.md", "# intro\n\npython3 -m gatekit doctor\n")
            proc = run_gate("gate_manual_accuracy.py", root)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("launcher", proc.stdout)

    def test_unknown_subcommand_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._manual_repo(root)
            write(root / "docs" / "manual" / "01-intro.md",
                  '# intro\n\n`python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" frobnicate`\n')
            proc = run_gate("gate_manual_accuracy.py", root)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("frobnicate", proc.stdout)

    def test_unknown_slash_command_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._manual_repo(root)
            write(root / "docs" / "manual" / "01-intro.md", "# intro\n\n/gatekit:nosuch\n")
            proc = run_gate("gate_manual_accuracy.py", root)
            self.assertEqual(proc.returncode, 1)

    def test_broken_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._manual_repo(root)
            write(root / "docs" / "manual" / "00-index.md", "# index\n\n- [x](01-intro.md)\n- [y](99-gone.md)\n")
            proc = run_gate("gate_manual_accuracy.py", root)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("99-gone.md", proc.stdout)

    def test_unlinked_page_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._manual_repo(root)
            write(root / "docs" / "manual" / "02-orphan.md", "# orphan\n")
            proc = run_gate("gate_manual_accuracy.py", root)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("02-orphan.md", proc.stdout)


class TestCleanRoom(unittest.TestCase):
    def test_clean_repo_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            proc = run_gate("gate_clean_room.py", root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_foreign_project_name_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "docs" / "manual" / "01-intro.md", "# intro\n\ngptaku 에서 영감을 받았다\n")
            proc = run_gate("gate_clean_room.py", root)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("gptaku", proc.stdout)

    def test_korean_plugin_name_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "docs" / "note.md", "# note\n\n품앗이 방식의 병렬 위임\n")
            proc = run_gate("gate_clean_room.py", root)
            self.assertEqual(proc.returncode, 1)

    def test_detection_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "docs" / "note.md", "See Insane-Search for the ladder.\n")
            proc = run_gate("gate_clean_room.py", root)
            self.assertEqual(proc.returncode, 1)

    def test_ordinary_words_are_not_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            write(root / "docs" / "note.md",
                  "# note\n\nadded a note, ddl handling, gaseous mixtures, nopalito\n")
            proc = run_gate("gate_clean_room.py", root)
            self.assertEqual(proc.returncode, 0, proc.stdout)


class TestManualBundle(unittest.TestCase):
    """The Notion bundle must keep the tree and survive Korean filenames."""

    def _repo(self, root: pathlib.Path) -> None:
        minimal_clean_repo(root)
        write(root / "docs" / "manual" / "00-index.md", "# 색인\n\n- [소개](01-intro.md)\n")
        write(root / "docs" / "manual" / "01-intro.md", "# 소개\n\n본문\n")

    def _build(self, root: pathlib.Path, out: pathlib.Path, title: str = "매뉴얼"):
        return subprocess.run(
            [sys.executable, str(TOOLS_DIR / "build_manual_bundle.py"),
             "--root", str(root), "--out", str(out), "--title", title],
            capture_output=True, text=True, timeout=30)

    def test_bundle_has_parent_and_children(self) -> None:
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._repo(root)
            out = root / "out.zip"
            proc = self._build(root, out)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            with zipfile.ZipFile(out) as z:
                names = z.namelist()
            self.assertIn("매뉴얼.md", names)
            self.assertIn("매뉴얼/00-index.md", names)
            self.assertIn("매뉴얼/01-intro.md", names)

    def test_filenames_carry_the_utf8_flag(self) -> None:
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self._repo(root)
            out = root / "out.zip"
            self._build(root, out)
            with zipfile.ZipFile(out) as z:
                self.assertTrue(all(i.flag_bits & 0x800 for i in z.infolist()),
                                "UTF-8 filename flag missing; Korean titles would mangle")

    def test_missing_manual_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            minimal_clean_repo(root)
            proc = self._build(root, root / "out.zip")
            self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":
    unittest.main()

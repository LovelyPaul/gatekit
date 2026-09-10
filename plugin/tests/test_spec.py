"""Tests for gatekit.spec.

The kernel modules `paths`, `lang` and `verdict` are owned by another agent and
may not exist yet. When one is missing this module installs a minimal stub in
`sys.modules` before importing `gatekit.spec`, so these tests are meaningful on
their own. When the real module is present it is used unchanged, and these
tests then also exercise the real integration.
"""
from __future__ import annotations

import importlib
import io
import json
import os
import pathlib
import sys
import types
import unittest
from contextlib import redirect_stdout

PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "spec"


# ---------------------------------------------------------------------------
# stubs for kernel modules that may not exist yet
# ---------------------------------------------------------------------------


def _ensure(module_name: str, build):
    """Import `module_name`; on failure install the stub `build()` produces."""
    try:
        importlib.import_module(module_name)
    except ImportError:
        sys.modules[module_name] = build()


def _stub_paths() -> types.ModuleType:
    mod = types.ModuleType("gatekit.paths")

    def project_root(cwd=None):
        return pathlib.Path(cwd or os.getcwd())

    mod.project_root = project_root
    mod.state_dir = lambda root: pathlib.Path(root) / ".gatekit"
    mod.spec_dir = lambda root: pathlib.Path(root) / "spec"
    mod.plugin_root = lambda: PLUGIN_DIR
    return mod


def _stub_lang() -> types.ModuleType:
    mod = types.ModuleType("gatekit.lang")

    def detect(text: str) -> str:
        if not text:
            return "en"
        hangul = sum(1 for ch in text if "가" <= ch <= "힣" or "ᄀ" <= ch <= "ᇿ")
        latin = sum(1 for ch in text if ("a" <= ch.lower() <= "z"))
        letters = hangul + latin
        if letters == 0:
            return "en"
        return "ko" if hangul / letters >= 0.30 else "en"

    mod.detect = detect
    mod.run = lambda argv: 0
    return mod


def _stub_verdict() -> types.ModuleType:
    mod = types.ModuleType("gatekit.verdict")
    mod.OK, mod.WARN, mod.FAIL, mod.UNVERIFIED = "ok", "warn", "fail", "unverified"
    mod.ORDER = ["ok", "warn", "unverified", "fail"]

    def aggregate(verdicts):
        verdicts = list(verdicts)
        if "fail" in verdicts:
            return "fail"
        if "unverified" in verdicts:
            return "unverified"
        if "warn" in verdicts:
            return "warn"
        return "ok"

    mod.aggregate = aggregate
    mod.render = lambda v, lang: v
    return mod


_ensure("gatekit.paths", _stub_paths)
_ensure("gatekit.lang", _stub_lang)
_ensure("gatekit.verdict", _stub_verdict)

from gatekit import spec  # noqa: E402


def messages(report, file=None):
    return [
        f["message"]
        for f in report["findings"]
        if file is None or f["file"] == file
    ]


def verdicts_for(report, file):
    return [f["verdict"] for f in report["findings"] if f["file"] == file]


# ---------------------------------------------------------------------------
# fence parsing
# ---------------------------------------------------------------------------


class ParseFencesTests(unittest.TestCase):
    def test_parses_every_named_fence(self):
        text = (
            "intro\n"
            "```gatekit-task\n{\"id\": \"a\"}\n```\n"
            "middle\n"
            "```gatekit-task\n{\"id\": \"b\"}\n```\n"
        )
        self.assertEqual(
            [t["id"] for t in spec.parse_fences(text, "gatekit-task")], ["a", "b"]
        )

    def test_ignores_other_fence_names(self):
        text = "```python\n{\"id\": \"a\"}\n```\n"
        self.assertEqual(spec.parse_fences(text, "gatekit-task"), [])

    def test_skips_malformed_bodies(self):
        text = "```gatekit-task\n{oops}\n```\n```gatekit-task\n{\"id\": \"b\"}\n```\n"
        self.assertEqual(
            [t["id"] for t in spec.parse_fences(text, "gatekit-task")], ["b"]
        )

    def test_rejects_non_object_body(self):
        text = "```gatekit-task\n[1, 2]\n```\n"
        self.assertEqual(spec.parse_fences(text, "gatekit-task"), [])

    def test_reports_line_number_of_malformed_fence(self):
        text = "line one\nline two\n```gatekit-task\n{oops}\n```\n"
        detailed = spec._parse_fences_detailed(text, "gatekit-task")
        self.assertEqual(len(detailed), 1)
        line_no, parsed, err = detailed[0]
        self.assertEqual(line_no, 3)
        self.assertIsNone(parsed)
        self.assertIsNotNone(err)


# ---------------------------------------------------------------------------
# valid sets
# ---------------------------------------------------------------------------


class ValidSetTests(unittest.TestCase):
    def test_korean_set_has_no_failures(self):
        report = spec.validate(FIXTURES / "valid-ko")
        self.assertEqual(report["lang"], "ko")
        self.assertNotIn(
            "fail",
            [f["verdict"] for f in report["findings"]],
            msg=json.dumps(report["findings"], ensure_ascii=False, indent=2),
        )
        self.assertEqual(report["verdict"], "ok")

    def test_english_set_has_no_failures(self):
        report = spec.validate(FIXTURES / "valid-en")
        self.assertEqual(report["lang"], "en")
        self.assertNotIn(
            "fail",
            [f["verdict"] for f in report["findings"]],
            msg=json.dumps(report["findings"], indent=2),
        )
        self.assertEqual(report["verdict"], "ok")

    def test_language_detected_from_prd_when_not_given(self):
        self.assertEqual(spec.validate(FIXTURES / "valid-ko")["lang"], "ko")
        self.assertEqual(spec.validate(FIXTURES / "valid-en")["lang"], "en")

    def test_explicit_lang_overrides_detection(self):
        # Forcing "en" on the Korean set makes every Korean heading a miss.
        report = spec.validate(FIXTURES / "valid-ko", lang="en")
        self.assertEqual(report["lang"], "en")
        self.assertEqual(report["verdict"], "fail")


# ---------------------------------------------------------------------------
# missing files
# ---------------------------------------------------------------------------


class MissingFileTests(unittest.TestCase):
    def test_missing_required_files_fail(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "spec").mkdir()
            report = spec.validate(root)
            self.assertEqual(report["verdict"], "fail")
            self.assertEqual(verdicts_for(report, "01-prd.md"), ["fail"])
            self.assertEqual(verdicts_for(report, "05-gate.md"), ["fail"])
            # optional files only warn
            self.assertEqual(verdicts_for(report, "PROGRESS.md"), ["warn"])
            self.assertEqual(verdicts_for(report, "RECOVERY.md"), ["warn"])

    def test_missing_optional_file_only_warns(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-ko", root)
            (root / "spec" / "PROGRESS.md").unlink()
            report = spec.validate(root)
            self.assertEqual(report["verdict"], "warn")
            self.assertEqual(verdicts_for(report, "PROGRESS.md"), ["warn"])


# ---------------------------------------------------------------------------
# headings
# ---------------------------------------------------------------------------


class HeadingTests(unittest.TestCase):
    def test_cross_language_heading_is_a_failure(self):
        report = spec.validate(FIXTURES / "cross-lang")
        self.assertEqual(report["verdict"], "fail")
        msgs = messages(report, "02-screens.md")
        self.assertTrue(
            any("Negative space" in m for m in msgs),
            msg="cross-language heading not reported: %r" % msgs,
        )
        # and the Korean heading it replaced is reported missing
        self.assertTrue(any("근거 없는 영역" in m for m in msgs), msgs)

    def test_missing_heading_is_a_failure(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-en", root)
            path = root / "spec" / "03-architecture.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace("## Constraints", "## Limits"),
                encoding="utf-8",
            )
            report = spec.validate(root)
            self.assertEqual(report["verdict"], "fail")
            self.assertTrue(
                any("## Constraints" in m for m in messages(report, "03-architecture.md"))
            )

    def test_extra_non_canonical_heading_is_allowed(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-en", root)
            path = root / "spec" / "03-architecture.md"
            path.write_text(
                path.read_text(encoding="utf-8") + "\n## Open questions\n\nNone.\n",
                encoding="utf-8",
            )
            self.assertEqual(spec.validate(root)["verdict"], "ok")


# ---------------------------------------------------------------------------
# assumption ledger
# ---------------------------------------------------------------------------


class LedgerTests(unittest.TestCase):
    def test_inline_without_row_fails_and_row_without_inline_warns(self):
        report = spec.validate(FIXTURES / "ledger-mismatch")
        self.assertEqual(report["verdict"], "fail")
        prd = [f for f in report["findings"] if f["file"] == "01-prd.md"]
        fails = [f["message"] for f in prd if f["verdict"] == "fail"]
        warns = [f["message"] for f in prd if f["verdict"] == "warn"]
        self.assertTrue(any("2" in m for m in fails), fails)
        self.assertTrue(any("3" in m for m in warns), warns)

    def test_matched_ledger_produces_no_finding(self):
        report = spec.validate(FIXTURES / "valid-ko")
        self.assertEqual([f for f in report["findings"] if f["file"] == "01-prd.md"], [])

    def test_english_inline_marker_is_recognised(self):
        text = "> ⚠️ Assumption 4: the API is stable.\n"
        self.assertEqual(spec._inline_assumption_numbers(text), [4])

    def test_korean_inline_marker_is_recognised(self):
        text = "> ⚠️ 가정 7: 사용자는 로그인 상태다.\n"
        self.assertEqual(spec._inline_assumption_numbers(text), [7])

    def test_trailing_number_form_is_recognised(self):
        text = "> ⚠️ Assumption: the API is stable (A2)\n"
        self.assertEqual(spec._inline_assumption_numbers(text), [2])


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------


class TaskTests(unittest.TestCase):
    def _validate_tasks(self, body: str, lang: str = "en"):
        return spec._check_tasks(body, lang)

    def test_same_round_scope_collision_fails(self):
        report = spec.validate(FIXTURES / "scope-collision")
        self.assertEqual(report["verdict"], "fail")
        msgs = messages(report, "04-tasks.md")
        self.assertTrue(
            any("note-store" in m and "note-ui" in m for m in msgs), msgs
        )

    def test_different_rounds_may_overlap(self):
        body = (
            "## Task list\n"
            '```gatekit-task\n{"id": "a", "write_scope": ["src/x/**"], '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 1}\n```\n'
            '```gatekit-task\n{"id": "b", "write_scope": ["src/x/y.ts"], '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 2}\n```\n'
        )
        self.assertEqual(self._validate_tasks(body), [])

    def test_duplicate_ids_fail(self):
        body = (
            '```gatekit-task\n{"id": "a", "write_scope": ["src/x/**"], '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 1}\n```\n'
            '```gatekit-task\n{"id": "a", "write_scope": ["src/y/**"], '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 1}\n```\n'
        )
        msgs = [f["message"] for f in self._validate_tasks(body)]
        self.assertTrue(any("Duplicate task id" in m for m in msgs), msgs)

    def test_empty_write_scope_fails_but_read_only_passes(self):
        empty = (
            '```gatekit-task\n{"id": "a", "write_scope": [], '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 1}\n```\n'
        )
        msgs = [f["message"] for f in self._validate_tasks(empty)]
        self.assertTrue(any("write_scope" in m for m in msgs), msgs)

        read_only = (
            '```gatekit-task\n{"id": "a", "write_scope": "read-only", '
            '"gates": [{"name": "t", "argv": ["true"]}], "round": 1}\n```\n'
        )
        self.assertEqual(self._validate_tasks(read_only), [])

    def test_unresolvable_dependency_fails(self):
        body = (
            '```gatekit-task\n{"id": "a", "write_scope": ["src/x/**"], '
            '"gates": [{"name": "t", "argv": ["true"]}], '
            '"depends_on": ["ghost"], "round": 1}\n```\n'
        )
        msgs = [f["message"] for f in self._validate_tasks(body)]
        self.assertTrue(any("ghost" in m for m in msgs), msgs)

    def test_task_without_gate_fails(self):
        body = (
            '```gatekit-task\n{"id": "a", "write_scope": ["src/x/**"], '
            '"gates": [], "round": 1}\n```\n'
        )
        msgs = [f["message"] for f in self._validate_tasks(body)]
        self.assertTrue(any("gate" in m.lower() for m in msgs), msgs)

    def test_malformed_fence_reports_line_number(self):
        report = spec.validate(FIXTURES / "malformed-fence")
        self.assertEqual(report["verdict"], "fail")
        msgs = messages(report, "04-tasks.md")
        malformed = [m for m in msgs if "gatekit-task" in m]
        self.assertTrue(malformed, msgs)
        self.assertTrue(
            any(any(ch.isdigit() for ch in m) for m in malformed),
            msg="no line number in %r" % malformed,
        )

    def test_glob_intersection_rules(self):
        self.assertTrue(spec._globs_intersect("src/a/**", "src/a/b.ts"))
        self.assertTrue(spec._globs_intersect("src/a/b.ts", "src/a/**"))
        self.assertTrue(spec._globs_intersect("src/a/*.ts", "src/a/b.ts"))
        self.assertTrue(spec._globs_intersect("src/a/**", "src/a/**"))
        self.assertFalse(spec._globs_intersect("src/a/**", "src/b/**"))
        self.assertFalse(spec._globs_intersect("src/a/b.ts", "src/a/c.ts"))
        self.assertFalse(spec._globs_intersect("src/ab/**", "src/a/c.ts"))


# ---------------------------------------------------------------------------
# criteria
# ---------------------------------------------------------------------------


class CriterionTests(unittest.TestCase):
    def test_missing_not_counted_section_fails(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-en", root)
            path = root / "spec" / "05-gate.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "## Not counted as done", "## Notes"
                ),
                encoding="utf-8",
            )
            report = spec.validate(root)
            self.assertEqual(report["verdict"], "fail")

    def test_empty_argv_fails(self):
        body = (
            "## Not counted as done\n"
            '```gatekit-criterion\n{"id": "c", "argv": []}\n```\n'
        )
        msgs = [f["message"] for f in spec._check_criteria(body, "en")]
        self.assertTrue(any("argv" in m for m in msgs), msgs)

    def test_non_string_argv_fails(self):
        body = (
            "## Not counted as done\n"
            '```gatekit-criterion\n{"id": "c", "argv": ["python3", 3]}\n```\n'
        )
        msgs = [f["message"] for f in spec._check_criteria(body, "en")]
        self.assertTrue(any("argv" in m for m in msgs), msgs)

    def test_duplicate_criterion_ids_fail(self):
        body = (
            "## Not counted as done\n"
            '```gatekit-criterion\n{"id": "c", "argv": ["true"]}\n```\n'
            '```gatekit-criterion\n{"id": "c", "argv": ["true"]}\n```\n'
        )
        msgs = [f["message"] for f in spec._check_criteria(body, "en")]
        self.assertTrue(any("Duplicate criterion id" in m for m in msgs), msgs)

    def test_no_criteria_fails(self):
        body = "## Not counted as done\n\nnothing here\n"
        msgs = [f["message"] for f in spec._check_criteria(body, "en")]
        self.assertTrue(any("gatekit-criterion" in m for m in msgs), msgs)


# ---------------------------------------------------------------------------
# traceability
# ---------------------------------------------------------------------------


class TraceabilityTests(unittest.TestCase):
    def test_unreferenced_task_warns(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-en", root)
            path = root / "spec" / "05-gate.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace("note-ui-tests", "other-tests"),
                encoding="utf-8",
            )
            report = spec.validate(root)
            self.assertEqual(report["verdict"], "warn")
            warn = [
                f
                for f in report["findings"]
                if f["verdict"] == "warn" and "note-ui" in f["message"]
            ]
            self.assertTrue(warn, report["findings"])

    def test_referenced_tasks_produce_no_warning(self):
        report = spec.validate(FIXTURES / "valid-en")
        self.assertEqual(
            [f for f in report["findings"] if "note-store" in f["message"]], []
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class CliTests(unittest.TestCase):
    def test_valid_set_exits_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = spec.run(["validate", "--root", str(FIXTURES / "valid-ko")])
        self.assertEqual(code, 0)
        # Human-readable output is localized; the label comes from
        # verdict.render, so assert only that something was rendered.
        self.assertTrue(buf.getvalue().startswith("spec: "), buf.getvalue())
        self.assertNotIn("[fail]", buf.getvalue())

    def test_english_set_renders_english_label(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = spec.run(["validate", "--root", str(FIXTURES / "valid-en")])
        self.assertEqual(code, 0)
        self.assertIn("ok", buf.getvalue().lower())

    def test_failing_set_exits_one(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = spec.run(["validate", "--root", str(FIXTURES / "cross-lang")])
        self.assertEqual(code, 1)

    def test_warn_only_set_exits_zero(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp) / "case"
            shutil.copytree(FIXTURES / "valid-ko", root)
            (root / "spec" / "PROGRESS.md").unlink()
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = spec.run(["validate", "--root", str(root)])
            self.assertEqual(code, 0)

    def test_json_output_is_parseable(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            spec.run(["validate", "--json", "--root", str(FIXTURES / "valid-en")])
        report = json.loads(buf.getvalue())
        self.assertEqual(report["verdict"], "ok")
        self.assertEqual(report["lang"], "en")
        self.assertIsInstance(report["findings"], list)

    def test_unknown_subcommand_returns_two(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(spec.run([]), 2)


# ---------------------------------------------------------------------------
# heading map and templates agree
# ---------------------------------------------------------------------------


class TemplateConsistencyTests(unittest.TestCase):
    def test_every_template_carries_its_canonical_headings(self):
        hm = spec.heading_map()
        for lang in ("ko", "en"):
            for name in hm["files"]:
                path = PLUGIN_DIR / "spec-kit" / "templates" / lang / name
                self.assertTrue(path.exists(), "missing template %s/%s" % (lang, name))
                present = set(spec._present_headings(path.read_text(encoding="utf-8")))
                for heading in hm[lang][name]:
                    self.assertIn(
                        heading, present, "%s/%s lacks %r" % (lang, name, heading)
                    )

    def test_templates_have_no_cross_language_headings(self):
        hm = spec.heading_map()
        for lang in ("ko", "en"):
            other = "en" if lang == "ko" else "ko"
            for name in hm["files"]:
                path = PLUGIN_DIR / "spec-kit" / "templates" / lang / name
                present = set(spec._present_headings(path.read_text(encoding="utf-8")))
                stray = present & set(hm[other][name]) - set(hm[lang][name])
                self.assertEqual(stray, set(), "%s/%s: %r" % (lang, name, stray))

    def test_template_fences_are_valid_json(self):
        checks = [
            ("04-tasks.md", "gatekit-task"),
            ("05-gate.md", "gatekit-criterion"),
        ]
        for lang in ("ko", "en"):
            for name, fence in checks:
                text = (PLUGIN_DIR / "spec-kit" / "templates" / lang / name).read_text(
                    encoding="utf-8"
                )
                detailed = spec._parse_fences_detailed(text, fence)
                self.assertTrue(detailed, "%s/%s has no %s fence" % (lang, name, fence))
                for line_no, _, err in detailed:
                    self.assertIsNone(
                        err, "%s/%s line %d: %s" % (lang, name, line_no, err)
                    )

    def test_templates_stay_under_120_lines(self):
        hm = spec.heading_map()
        for lang in ("ko", "en"):
            for name in hm["files"]:
                path = PLUGIN_DIR / "spec-kit" / "templates" / lang / name
                count = len(path.read_text(encoding="utf-8").splitlines())
                self.assertLessEqual(count, 120, "%s/%s is %d lines" % (lang, name, count))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

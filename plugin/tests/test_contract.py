"""Tests for gatekit.contract — derive, freshness, and sandboxed execution."""
from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import approval, contract

PY = sys.executable


def criterion_fence(obj: dict) -> str:
    return "```gatekit-criterion\n" + json.dumps(obj) + "\n```\n"


class TempProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        self.gate = self.root / "spec" / "05-gate.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_gate(self, *criteria: dict, prose: str = "# Gate\n\nSome prose.\n") -> None:
        body = prose + "".join(criterion_fence(c) for c in criteria)
        self.gate.write_text(body, encoding="utf-8")


class TestDerive(TempProject):
    def test_derives_criteria_and_source_hash(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"], "expect": {"exit": 0}})
        data = contract.derive(self.root)
        self.assertEqual(data["version"], 1)
        self.assertEqual(len(data["criteria"]), 1)
        self.assertEqual(data["criteria"][0]["id"], "a")
        self.assertEqual(data["source_sha256"], approval.sha256_file(self.gate))
        self.assertIn("derived_at", data)

    def test_writes_contract_file(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        target = self.root / ".gatekit" / "contract.json"
        self.assertTrue(target.is_file())
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["criteria"][0]["id"], "a")

    def test_multiple_fences_preserve_order(self) -> None:
        self.write_gate(
            {"id": "first", "argv": ["true"]},
            {"id": "second", "argv": ["true"]},
        )
        ids = [c["id"] for c in contract.derive(self.root)["criteria"]]
        self.assertEqual(ids, ["first", "second"])

    def test_prose_between_fences_is_ignored(self) -> None:
        body = (
            "# Gate\n\nintro\n"
            + criterion_fence({"id": "a", "argv": ["true"]})
            + "\nmore prose mentioning gatekit-criterion in text\n"
            + criterion_fence({"id": "b", "argv": ["true"]})
        )
        self.gate.write_text(body, encoding="utf-8")
        self.assertEqual(len(contract.derive(self.root)["criteria"]), 2)

    def test_other_fence_languages_ignored(self) -> None:
        body = (
            "```json\n{\"id\": \"not-a-criterion\"}\n```\n"
            + criterion_fence({"id": "real", "argv": ["true"]})
        )
        self.gate.write_text(body, encoding="utf-8")
        criteria = contract.derive(self.root)["criteria"]
        self.assertEqual([c["id"] for c in criteria], ["real"])

    def test_missing_gate_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            contract.derive(self.root)

    def test_invalid_json_fence_raises_with_context(self) -> None:
        self.gate.write_text("```gatekit-criterion\n{not json}\n```\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            contract.derive(self.root)

    def test_criterion_without_id_raises(self) -> None:
        self.write_gate({"argv": ["true"]})
        with self.assertRaises(ValueError):
            contract.derive(self.root)

    def test_criterion_without_argv_raises(self) -> None:
        self.write_gate({"id": "a"})
        with self.assertRaises(ValueError):
            contract.derive(self.root)

    def test_duplicate_ids_raise(self) -> None:
        self.write_gate({"id": "dup", "argv": ["true"]}, {"id": "dup", "argv": ["true"]})
        with self.assertRaises(ValueError):
            contract.derive(self.root)

    def test_defaults_are_filled(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        crit = contract.derive(self.root)["criteria"][0]
        self.assertEqual(crit["expect"], {"exit": 0})
        self.assertEqual(crit["artifacts"], [])
        self.assertGreater(crit["timeout_s"], 0)


class TestStatus(TempProject):
    def test_absent_contract_is_unverified(self) -> None:
        self.assertEqual(contract.status(self.root), "unverified")

    def test_fresh_contract_is_ok(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        self.assertEqual(contract.status(self.root), "ok")

    def test_edited_gate_makes_contract_stale(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        self.gate.write_text(self.gate.read_text(encoding="utf-8") + "\nextra\n", encoding="utf-8")
        self.assertEqual(contract.status(self.root), "fail")

    def test_corrupt_contract_is_unverified(self) -> None:
        (self.root / ".gatekit" / "contract.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(contract.status(self.root), "unverified")

    def test_deleted_gate_makes_contract_stale(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        self.gate.unlink()
        self.assertEqual(contract.status(self.root), "fail")


class TestExecute(TempProject):
    def test_passing_criterion_is_ok(self) -> None:
        self.write_gate({"id": "pass", "argv": [PY, "-c", "print('hi')"], "timeout_s": 20})
        contract.derive(self.root)
        result = contract.execute(self.root)
        self.assertEqual(result["verdict"], "ok")
        self.assertEqual(result["criteria"][0]["verdict"], "ok")
        self.assertEqual(result["criteria"][0]["exit"], 0)
        self.assertIn("hi", result["criteria"][0]["stdout_tail"])

    def test_plugin_root_token_in_argv_is_expanded(self) -> None:
        # ADR-0018 decision 1: the documented token-gate form must run.
        self.write_gate({
            "id": "tokens-help",
            "argv": [PY, "${CLAUDE_PLUGIN_ROOT}/gatekit/gates/tokens.py", "--help"],
            "timeout_s": 20,
        })
        contract.derive(self.root)
        stored = json.loads((self.root / ".gatekit" / "contract.json").read_text())
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", stored["criteria"][0]["argv"][1])
        result = contract.execute(self.root)
        self.assertEqual(result["criteria"][0]["verdict"], "ok", result["criteria"][0])

    def test_failing_exit_code_is_fail(self) -> None:
        self.write_gate({"id": "bad", "argv": [PY, "-c", "raise SystemExit(3)"], "timeout_s": 20})
        contract.derive(self.root)
        result = contract.execute(self.root)
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["criteria"][0]["exit"], 3)

    def test_expected_nonzero_exit_is_ok(self) -> None:
        self.write_gate(
            {
                "id": "expects-2",
                "argv": [PY, "-c", "raise SystemExit(2)"],
                "expect": {"exit": 2},
                "timeout_s": 20,
            }
        )
        contract.derive(self.root)
        self.assertEqual(contract.execute(self.root)["criteria"][0]["verdict"], "ok")

    def test_timeout_is_unverified_never_ok_or_fail(self) -> None:
        self.write_gate(
            {
                "id": "slow",
                "argv": [PY, "-c", "import time; time.sleep(5)"],
                "timeout_s": 1,
            }
        )
        contract.derive(self.root)
        result = contract.execute(self.root)
        crit = result["criteria"][0]
        self.assertEqual(crit["verdict"], "unverified")
        self.assertIn("timeout", " ".join(result["reasons"]).lower())
        self.assertEqual(result["verdict"], "unverified")

    def test_missing_executable_is_unverified(self) -> None:
        self.write_gate({"id": "ghost", "argv": ["gatekit-no-such-binary-xyz"], "timeout_s": 10})
        contract.derive(self.root)
        self.assertEqual(contract.execute(self.root)["criteria"][0]["verdict"], "unverified")

    def test_missing_artifact_is_fail(self) -> None:
        self.write_gate(
            {
                "id": "art",
                "argv": [PY, "-c", "pass"],
                "artifacts": ["reports/junit.xml"],
                "timeout_s": 20,
            }
        )
        contract.derive(self.root)
        result = contract.execute(self.root)
        self.assertEqual(result["criteria"][0]["verdict"], "fail")

    def test_present_artifact_is_hashed(self) -> None:
        (self.root / "reports").mkdir()
        (self.root / "reports" / "junit.xml").write_text("<xml/>", encoding="utf-8")
        self.write_gate(
            {
                "id": "art",
                "argv": [PY, "-c", "pass"],
                "artifacts": ["reports/junit.xml"],
                "timeout_s": 20,
            }
        )
        contract.derive(self.root)
        crit = contract.execute(self.root)["criteria"][0]
        self.assertEqual(crit["verdict"], "ok")
        self.assertEqual(len(crit["artifact_hashes"]["reports/junit.xml"]), 64)

    def test_absolute_artifact_path_is_fail(self) -> None:
        self.write_gate(
            {"id": "abs", "argv": [PY, "-c", "pass"], "artifacts": ["/etc/hosts"], "timeout_s": 20}
        )
        contract.derive(self.root)
        self.assertEqual(contract.execute(self.root)["criteria"][0]["verdict"], "fail")

    def test_dotdot_artifact_path_is_fail(self) -> None:
        self.write_gate(
            {
                "id": "up",
                "argv": [PY, "-c", "pass"],
                "artifacts": ["../outside.txt"],
                "timeout_s": 20,
            }
        )
        contract.derive(self.root)
        self.assertEqual(contract.execute(self.root)["criteria"][0]["verdict"], "fail")

    def test_symlink_artifact_escaping_root_is_fail(self) -> None:
        outside = pathlib.Path(os.path.realpath(tempfile.mkdtemp()))
        try:
            secret = outside / "secret.txt"
            secret.write_text("top secret\n", encoding="utf-8")
            link = self.root / "escape.txt"
            os.symlink(str(secret), str(link))
            self.write_gate(
                {
                    "id": "sym",
                    "argv": [PY, "-c", "pass"],
                    "artifacts": ["escape.txt"],
                    "timeout_s": 20,
                }
            )
            contract.derive(self.root)
            crit = contract.execute(self.root)["criteria"][0]
            self.assertEqual(crit["verdict"], "fail")
            self.assertNotIn("escape.txt", crit.get("artifact_hashes", {}))
        finally:
            import shutil

            shutil.rmtree(outside, ignore_errors=True)

    def test_symlink_staying_inside_root_is_allowed(self) -> None:
        real = self.root / "real.txt"
        real.write_text("fine\n", encoding="utf-8")
        os.symlink(str(real), str(self.root / "alias.txt"))
        self.write_gate(
            {"id": "ok-sym", "argv": [PY, "-c", "pass"], "artifacts": ["alias.txt"], "timeout_s": 20}
        )
        contract.derive(self.root)
        self.assertEqual(contract.execute(self.root)["criteria"][0]["verdict"], "ok")

    def test_stale_contract_is_unverified_with_reason(self) -> None:
        self.write_gate({"id": "a", "argv": [PY, "-c", "pass"], "timeout_s": 20})
        contract.derive(self.root)
        self.gate.write_text(self.gate.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
        result = contract.execute(self.root)
        self.assertEqual(result["verdict"], "unverified")
        self.assertIn("contract_stale", result["reasons"])
        self.assertEqual(result["criteria"], [])

    def test_absent_contract_is_unverified(self) -> None:
        result = contract.execute(self.root)
        self.assertEqual(result["verdict"], "unverified")

    def test_empty_criteria_is_unverified_not_ok(self) -> None:
        self.write_gate(prose="# Gate\n\nNo fences at all.\n")
        contract.derive(self.root)
        self.assertEqual(contract.execute(self.root)["verdict"], "unverified")

    def test_runs_with_cwd_at_project_root(self) -> None:
        self.write_gate(
            {"id": "cwd", "argv": [PY, "-c", "import os; print(os.getcwd())"], "timeout_s": 20}
        )
        contract.derive(self.root)
        out = contract.execute(self.root)["criteria"][0]["stdout_tail"]
        self.assertIn(str(self.root), out)

    def test_no_shell_interpretation(self) -> None:
        # A shell would expand this into two commands; subprocess without a
        # shell passes it as one literal argument.
        marker = self.root / "pwned.txt"
        self.write_gate(
            {
                "id": "noshell",
                "argv": [PY, "-c", "print('safe')", ";", f"touch {marker}"],
                "timeout_s": 20,
            }
        )
        contract.derive(self.root)
        contract.execute(self.root)
        self.assertFalse(marker.exists())

    def test_budget_exhaustion_marks_remaining_unverified(self) -> None:
        self.write_gate(
            {"id": "slow", "argv": [PY, "-c", "import time; time.sleep(3)"], "timeout_s": 30},
            {"id": "after", "argv": [PY, "-c", "pass"], "timeout_s": 30},
        )
        contract.derive(self.root)
        result = contract.execute(self.root, total_budget_s=1.0)
        verdicts = {c["id"]: c["verdict"] for c in result["criteria"]}
        self.assertEqual(verdicts["slow"], "unverified")
        self.assertEqual(verdicts["after"], "unverified")
        self.assertEqual(result["verdict"], "unverified")

    def test_output_tails_are_truncated(self) -> None:
        self.write_gate(
            {
                "id": "loud",
                "argv": [PY, "-c", "print('x' * 100000)"],
                "timeout_s": 20,
            }
        )
        contract.derive(self.root)
        tail = contract.execute(self.root)["criteria"][0]["stdout_tail"]
        self.assertLessEqual(len(tail), contract.TAIL_CHARS + 16)

    def test_elapsed_is_recorded(self) -> None:
        self.write_gate({"id": "a", "argv": [PY, "-c", "pass"], "timeout_s": 20})
        contract.derive(self.root)
        self.assertGreaterEqual(contract.execute(self.root)["criteria"][0]["elapsed_s"], 0.0)

    def test_mixed_results_aggregate_fail_over_unverified(self) -> None:
        self.write_gate(
            {"id": "bad", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20},
            {"id": "slow", "argv": [PY, "-c", "import time; time.sleep(5)"], "timeout_s": 1},
        )
        contract.derive(self.root)
        self.assertEqual(contract.execute(self.root)["verdict"], "fail")

    def test_reasons_name_failing_criteria(self) -> None:
        self.write_gate({"id": "named", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20})
        contract.derive(self.root)
        self.assertIn("named", " ".join(contract.execute(self.root)["reasons"]))


class TestRun(TempProject):
    def _run(self, argv: "list[str]") -> "tuple[int, str]":
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = contract.run(argv)
        return rc, out.getvalue()

    def test_derive_subcommand(self) -> None:
        self.write_gate({"id": "a", "argv": [PY, "-c", "pass"], "timeout_s": 20})
        rc, _ = self._run(["derive", "--root", str(self.root)])
        self.assertEqual(rc, 0)
        self.assertTrue((self.root / ".gatekit" / "contract.json").is_file())

    def test_derive_missing_gate_is_nonzero(self) -> None:
        rc, _ = self._run(["derive", "--root", str(self.root)])
        self.assertNotEqual(rc, 0)

    def test_status_subcommand(self) -> None:
        rc, out = self._run(["status", "--root", str(self.root)])
        self.assertEqual(out.strip(), "unverified")

    def test_run_json_output(self) -> None:
        self.write_gate({"id": "a", "argv": [PY, "-c", "pass"], "timeout_s": 20})
        self._run(["derive", "--root", str(self.root)])
        rc, out = self._run(["run", "--json", "--root", str(self.root)])
        payload = json.loads(out)
        self.assertEqual(payload["verdict"], "ok")
        self.assertEqual(rc, 0)

    def test_run_nonzero_when_failing(self) -> None:
        self.write_gate({"id": "a", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20})
        self._run(["derive", "--root", str(self.root)])
        rc, _ = self._run(["run", "--json", "--root", str(self.root)])
        self.assertNotEqual(rc, 0)

    def test_unknown_subcommand_is_nonzero(self) -> None:
        rc, _ = self._run(["bogus", "--root", str(self.root)])
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestDeclaredTotalBudget(unittest.TestCase):
    """spec/05-gate.md may declare its own total budget via a gatekit-budget fence.

    Without this, a suite that is legitimately slower than the 45s default can
    never reach `ok` through the Stop gate: the criteria pass individually but
    the run is cut off and reported `unverified`. Observed in the first real
    end-to-end run, where a 24.5s full-suite criterion was clamped to 20s.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        self.addCleanup(self._tmp.cleanup)

    def _write_gate(self, extra: str = "") -> None:
        (self.root / "spec" / "05-gate.md").write_text(
            "# gate\n\n## Not counted as done\n\n- nothing\n\n"
            '```gatekit-criterion\n'
            '{"id": "quick", "argv": ["python3", "-c", "pass"], "timeout_s": 5}\n'
            "```\n" + extra,
            encoding="utf-8",
        )

    def test_default_budget_when_no_fence(self) -> None:
        self._write_gate()
        data = contract.derive(self.root)
        self.assertEqual(data.get("total_budget_s"), contract.TOTAL_BUDGET_S)

    def test_declared_budget_is_stored_and_used(self) -> None:
        self._write_gate(
            '\n```gatekit-budget\n{"total_budget_s": 180}\n```\n'
        )
        data = contract.derive(self.root)
        self.assertEqual(data["total_budget_s"], 180.0)
        result = contract.execute(self.root)
        self.assertEqual(result["verdict"], "ok")
        self.assertEqual(result["total_budget_s"], 180.0)

    def test_explicit_argument_overrides_declared_budget(self) -> None:
        self._write_gate('\n```gatekit-budget\n{"total_budget_s": 180}\n```\n')
        contract.derive(self.root)
        result = contract.execute(self.root, total_budget_s=7)
        self.assertEqual(result["total_budget_s"], 7.0)

    def test_non_positive_budget_is_rejected(self) -> None:
        self._write_gate('\n```gatekit-budget\n{"total_budget_s": 0}\n```\n')
        with self.assertRaises(ValueError):
            contract.derive(self.root)

    def test_budget_is_capped_so_a_gate_cannot_hang_a_session(self) -> None:
        self._write_gate('\n```gatekit-budget\n{"total_budget_s": 99999}\n```\n')
        with self.assertRaises(ValueError):
            contract.derive(self.root)


PY = sys.executable


class TestExpectOutput(TempProject):
    """`expect` can pin what a command prints, not only how it exits. This is
    what turns "no test was skipped" from prose into a criterion."""

    def run_one(self, expect: dict, code: str = "print('ran 3 tests\\nOK')") -> dict:
        self.write_gate({"id": "c", "argv": [PY, "-c", code], "expect": expect, "timeout_s": 20})
        contract.derive(self.root)
        return contract.execute(self.root)["criteria"][0]

    def test_stdout_contains_string_passes(self) -> None:
        self.assertEqual(self.run_one({"stdout_contains": "OK"})["verdict"], "ok")

    def test_stdout_contains_missing_fails_and_names_the_expectation(self) -> None:
        result = self.run_one({"stdout_contains": "PASSED"})
        self.assertEqual(result["verdict"], "fail")
        self.assertIn("stdout_contains", result["stderr_tail"])
        self.assertIn("PASSED", result["stderr_tail"])

    def test_stdout_contains_list_requires_all(self) -> None:
        self.assertEqual(self.run_one({"stdout_contains": ["ran 3", "OK"]})["verdict"], "ok")
        self.assertEqual(self.run_one({"stdout_contains": ["ran 3", "FAILED"]})["verdict"], "fail")

    def test_stdout_not_contains_catches_skips(self) -> None:
        skipped = "print('ran 3 tests\\nOK (skipped=2)')"
        result = self.run_one({"stdout_not_contains": "skipped"}, skipped)
        self.assertEqual(result["verdict"], "fail")
        self.assertIn("skipped", result["stderr_tail"])
        self.assertEqual(self.run_one({"stdout_not_contains": ["skipped", "TODO"]})["verdict"], "ok")

    def test_stdout_regex(self) -> None:
        self.assertEqual(self.run_one({"stdout_regex": r"ran \d+ tests"})["verdict"], "ok")
        self.assertEqual(self.run_one({"stdout_regex": r"ran 0 tests"})["verdict"], "fail")

    def test_stderr_expectations(self) -> None:
        code = "import sys; sys.stderr.write('warning: deprecated\\n')"
        self.assertEqual(self.run_one({"stderr_contains": "deprecated"}, code)["verdict"], "ok")
        self.assertEqual(self.run_one({"stderr_not_contains": "deprecated"}, code)["verdict"], "fail")

    def test_output_checked_beyond_the_tail(self) -> None:
        # The stored tail is 2000 chars; the expectation must see the whole stream.
        code = "print('MARKER'); print('x' * 5000)"
        self.assertEqual(self.run_one({"stdout_contains": "MARKER"}, code)["verdict"], "ok")

    def test_exit_checked_before_output(self) -> None:
        code = "print('OK'); raise SystemExit(1)"
        result = self.run_one({"exit": 0, "stdout_contains": "OK"}, code)
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["exit"], 1)

    def test_unverified_stays_unverified(self) -> None:
        self.write_gate({"id": "c", "argv": ["/nonexistent-binary-xyz"], "expect": {"stdout_contains": "OK"}})
        contract.derive(self.root)
        self.assertEqual(contract.execute(self.root)["criteria"][0]["verdict"], "unverified")


class TestExpectValidation(TempProject):
    def test_unknown_expect_key_is_a_derive_error(self) -> None:
        self.write_gate({"id": "c", "argv": [PY, "-c", "pass"], "expect": {"exit": 0, "stdout_contain": "x"}})
        with self.assertRaises(ValueError) as ctx:
            contract.derive(self.root)
        self.assertIn("stdout_contain", str(ctx.exception))

    def test_non_string_expectation_is_a_derive_error(self) -> None:
        self.write_gate({"id": "c", "argv": [PY, "-c", "pass"], "expect": {"stdout_contains": 3}})
        with self.assertRaises(ValueError):
            contract.derive(self.root)

    def test_invalid_regex_is_a_derive_error(self) -> None:
        self.write_gate({"id": "c", "argv": [PY, "-c", "pass"], "expect": {"stdout_regex": "("}})
        with self.assertRaises(ValueError):
            contract.derive(self.root)

    def test_non_integer_exit_is_a_derive_error(self) -> None:
        self.write_gate({"id": "c", "argv": [PY, "-c", "pass"], "expect": {"exit": "zero"}})
        with self.assertRaises(ValueError):
            contract.derive(self.root)

    def test_expect_keys_constant(self) -> None:
        self.assertEqual(
            contract.EXPECT_KEYS,
            ("exit", "stdout_contains", "stdout_not_contains", "stdout_regex",
             "stderr_contains", "stderr_not_contains", "stderr_regex"),
        )


# ---------------------------------------------------------------------------
# design inputs (ADR-0008 decision 6)
# ---------------------------------------------------------------------------


class TestInputs(TempProject):
    """derive records the design inputs; a changed one makes the contract stale."""

    def write_input(self, name: str, text: str) -> None:
        (self.root / "spec" / name).write_text(text, encoding="utf-8")

    def test_derive_records_all_three_inputs(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        data = contract.derive(self.root)
        self.assertEqual(
            sorted(data["inputs"]),
            ["spec/02-design.md", "spec/02-screens.md", "spec/tokens.json"],
        )

    def test_absent_input_hashes_to_empty_string(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        data = contract.derive(self.root)
        self.assertEqual(data["inputs"]["spec/02-design.md"], "")

    def test_present_input_hashes_to_its_content(self) -> None:
        self.write_input("02-design.md", "# design\n")
        self.write_gate({"id": "a", "argv": ["true"]})
        data = contract.derive(self.root)
        self.assertEqual(
            data["inputs"]["spec/02-design.md"],
            approval.sha256_file(self.root / "spec" / "02-design.md"),
        )

    def test_status_is_ok_when_inputs_are_unchanged(self) -> None:
        self.write_input("tokens.json", '{"version": 2}\n')
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        self.assertEqual(contract.status(self.root), "ok")

    def test_changed_input_makes_the_contract_stale(self) -> None:
        self.write_input("02-design.md", "# design\n")
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        self.write_input("02-design.md", "# design changed\n")
        self.assertEqual(contract.status(self.root), "fail")

    def test_newly_created_input_makes_the_contract_stale(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        self.write_input("tokens.json", '{"version": 2}\n')
        self.assertEqual(contract.status(self.root), "fail")

    def test_deleted_input_makes_the_contract_stale(self) -> None:
        self.write_input("02-screens.md", "# screens\n")
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        (self.root / "spec" / "02-screens.md").unlink()
        self.assertEqual(contract.status(self.root), "fail")

    def test_a_contract_without_inputs_is_judged_on_the_gate_file_alone(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        target = self.root / ".gatekit" / "contract.json"
        data = json.loads(target.read_text(encoding="utf-8"))
        del data["inputs"]
        target.write_text(json.dumps(data), encoding="utf-8")
        self.write_input("02-design.md", "# new design\n")
        self.assertEqual(contract.status(self.root), "ok")

    def test_stale_inputs_names_only_the_changed_paths(self) -> None:
        self.write_input("02-design.md", "# design\n")
        self.write_input("tokens.json", '{"version": 2}\n')
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        self.write_input("tokens.json", '{"version": 2, "color": {}}\n')
        self.assertEqual(contract.stale_inputs(self.root), ["spec/tokens.json"])

    def test_stale_inputs_is_empty_when_fresh(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        self.assertEqual(contract.stale_inputs(self.root), [])

    def test_stale_inputs_is_empty_without_a_contract(self) -> None:
        self.assertEqual(contract.stale_inputs(self.root), [])

    def test_stale_inputs_is_empty_for_a_pre_inputs_contract(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        target = self.root / ".gatekit" / "contract.json"
        data = json.loads(target.read_text(encoding="utf-8"))
        del data["inputs"]
        target.write_text(json.dumps(data), encoding="utf-8")
        self.write_input("02-design.md", "# new\n")
        self.assertEqual(contract.stale_inputs(self.root), [])

    def test_execute_reports_stale_when_an_input_changed(self) -> None:
        self.write_input("02-design.md", "# design\n")
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        self.write_input("02-design.md", "# other\n")
        result = contract.execute(self.root)
        self.assertEqual(result["verdict"], "unverified")
        self.assertEqual(result["reasons"], [contract.STALE_REASON])


class TestStatusOutput(TempProject):
    """`contract status` names the input that changed, not just the verdict."""

    def test_status_prints_the_changed_input_name(self) -> None:
        (self.root / "spec" / "02-design.md").write_text("# design\n", encoding="utf-8")
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        (self.root / "spec" / "02-design.md").write_text("# other\n", encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            code = contract.run(["status", "--root", str(self.root)])
        self.assertEqual(code, 1)
        text = out.getvalue()
        self.assertIn("fail", text)
        self.assertIn("spec/02-design.md", text)

    def test_fresh_status_prints_only_the_verdict(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        out = io.StringIO()
        with redirect_stdout(out):
            code = contract.run(["status", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().strip(), "ok")

    def test_stale_gate_file_alone_still_prints_fail(self) -> None:
        self.write_gate({"id": "a", "argv": ["true"]})
        contract.derive(self.root)
        self.write_gate({"id": "b", "argv": ["true"]})
        out = io.StringIO()
        with redirect_stdout(out):
            code = contract.run(["status", "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("fail", out.getvalue())


# ------------------------- ADR-0022: zero tests, and the gate-time baseline


def emitting(stdout: str = "", stderr: str = "", code: int = 0, sleep: float = 0) -> list:
    """A fake runner. `{root}` in the text becomes the cwd (the project root)."""
    script = ("import os, sys, time\n"
              "time.sleep(%r)\n"
              "root = os.getcwd()\n"
              "sys.stdout.write(%r.replace('{root}', root))\n"
              "sys.stderr.write(%r.replace('{root}', root))\n"
              "sys.exit(%d)\n" % (sleep, stdout, stderr, code))
    return [PY, "-c", script]


NPM_ENOENT = ("npm error code ENOENT\nnpm error enoent Could not read package.json: "
              "Error: ENOENT: no such file or directory, open '{root}/package.json'\n")


class TestRanNoTestsCriterion(TempProject):
    def test_an_exit_zero_with_no_tests_is_unverified(self) -> None:
        self.write_gate({"id": "unit", "argv": emitting(stdout="  0 passing (1ms)\n")})
        contract.derive(self.root)
        result = contract.execute(self.root)
        item = result["criteria"][0]
        self.assertEqual(item["verdict"], "unverified")
        self.assertIn("ran no tests", item["detail"])
        self.assertEqual(result["verdict"], "unverified")
        self.assertIn("ran no tests", result["reasons"][0])

    def test_pytest_exit_five_is_unverified(self) -> None:
        self.write_gate({"id": "py", "argv": emitting(stdout="== no tests ran in 0.01s ==\n", code=5)})
        contract.derive(self.root)
        self.assertEqual(contract.execute(self.root)["criteria"][0]["verdict"], "unverified")

    def test_a_real_count_stays_ok(self) -> None:
        self.write_gate({"id": "unit", "argv": emitting(stdout="  4 passing (9ms)\n")})
        contract.derive(self.root)
        self.assertEqual(contract.execute(self.root)["criteria"][0]["verdict"], "ok")


class TestBaseline(TempProject):
    def write_tasks(self, *tasks: dict) -> None:
        body = "# Tasks\n\n" + "".join(
            "```gatekit-task\n%s\n```\n" % json.dumps(t) for t in tasks)
        (self.root / "spec" / "04-tasks.md").write_text(body, encoding="utf-8")

    def shell_task(self) -> dict:
        return {"id": "shell-login", "title": "Shell", "write_scope": ["package.json", "bin/**"],
                "instruction": "x", "gates": [{"name": "g", "argv": ["true"]}],
                "depends_on": [], "round": 1}

    def classes(self, result: dict) -> dict:
        return {c["id"]: c["class"] for c in result["criteria"]}

    def run_cli(self, *extra: str) -> "tuple[int, str]":
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = contract.run(["baseline", "--root", str(self.root), *extra])
        return code, out.getvalue()

    def test_every_class(self) -> None:
        self.write_tasks(self.shell_task())
        self.write_gate(
            {"id": "passes", "argv": emitting(stdout="ok\n")},
            {"id": "fails", "argv": emitting(stdout="1 failed\n", code=1)},
            {"id": "later", "argv": emitting(stderr=NPM_ENOENT, code=254)},
            {"id": "later-bin", "argv": ["bin/run-e2e"]},
            {"id": "no-tests", "argv": emitting(stdout="Ran 0 tests in 0.000s\n\nOK\n")},
            {"id": "slow", "argv": emitting(sleep=5), "timeout_s": 1},
        )
        contract.derive(self.root)
        result = contract.baseline(self.root)
        self.assertEqual(self.classes(result), {
            "passes": "already_passes", "fails": "fails", "later": "not_yet_runnable",
            "later-bin": "not_yet_runnable", "no-tests": "unverified", "slow": "unverified"})
        by_id = {c["id"]: c for c in result["criteria"]}
        self.assertIn("shell-login", by_id["later"]["detail"])
        self.assertIn("ran no tests", by_id["no-tests"]["detail"])

    def test_command_errors(self) -> None:
        self.write_tasks({**self.shell_task(), "write_scope": ["src/**"]})
        self.write_gate(
            {"id": "manifest", "argv": emitting(stderr=NPM_ENOENT, code=254)},
            {"id": "missing-bin", "argv": ["no-such-binary-gatekit-xyz"]},
            {"id": "exit-127", "argv": emitting(stderr="sh: foo: command not found\n", code=127)},
        )
        contract.derive(self.root)
        result = contract.baseline(self.root)
        self.assertEqual(set(self.classes(result).values()), {"command_error"})
        manifest = {c["id"]: c for c in result["criteria"]}["manifest"]
        self.assertIn("package.json", manifest["detail"])

    def test_baseline_and_preflight_agree_on_a_program(self) -> None:
        from gatekit import jobs
        self.write_tasks(self.shell_task())
        self.write_gate(
            {"id": "owned", "argv": ["bin/run-e2e"]},
            {"id": "unowned", "argv": ["no-such-binary-gatekit-xyz"]},
            {"id": "script", "argv": ["bash", "bin/e2e.sh"]},
        )
        contract.derive(self.root)
        result = contract.baseline(self.root)
        tasks = contract._baseline_tasks(self.root)
        for crit in contract.load(self.root)["criteria"]:
            gate = jobs.run_gates(self.root, {"gates": [{"name": "g", "argv": crit["argv"]}]})
            kind = jobs.classify_gate_result(gate["gates"][0], crit["argv"], root=self.root,
                                             tasks=tasks)
            with self.subTest(crit=crit["id"]):
                self.assertEqual(kind, self.classes(result)[crit["id"]])
        self.assertEqual(self.classes(result), {"owned": "not_yet_runnable",
                                                "unowned": "command_error",
                                                "script": "not_yet_runnable"})

    def test_uninstalled_dependency_programs(self) -> None:
        self.write_tasks({**self.shell_task(), "write_scope": ["package.json"]})
        self.write_gate(
            {"id": "pw", "argv": ["./node_modules/.bin/playwright", "test"]},
            {"id": "py", "argv": [".venv/bin/pytest"]},
            {"id": "missing", "argv": ["nonexistentprog"]},
        )
        contract.derive(self.root)
        result = contract.baseline(self.root)
        by_id = {c["id"]: c for c in result["criteria"]}
        self.assertEqual(self.classes(result), {"pw": "not_yet_runnable", "py": "unverified",
                                                "missing": "command_error"})
        self.assertIn("shell-login", by_id["pw"]["detail"])
        self.assertIn("pyproject.toml", by_id["py"]["detail"])

    def test_baseline_json_is_written(self) -> None:
        self.write_gate({"id": "passes", "argv": emitting(stdout="ok\n")})
        data = contract.derive(self.root)
        contract.baseline(self.root)
        saved = json.loads((self.root / ".gatekit" / "baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["source_sha256"], data["source_sha256"])
        self.assertEqual(saved["criteria"][0]["class"], "already_passes")
        self.assertIn("elapsed_s", saved)
        self.assertIn("recorded_at", saved)

    def test_cli_exit_codes(self) -> None:
        self.write_gate({"id": "fails", "argv": emitting(code=1)},
                        {"id": "passes", "argv": emitting(stdout="ok\n")})
        contract.derive(self.root)
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("already_passes", out)
        self.assertIn("passes before any work", out)
        self.write_gate({"id": "broken", "argv": ["no-such-binary-gatekit-xyz"]})
        contract.derive(self.root)
        self.assertEqual(self.run_cli()[0], 4)

    def test_cli_json(self) -> None:
        self.write_gate({"id": "passes", "argv": emitting(stdout="ok\n")})
        contract.derive(self.root)
        code, out = self.run_cli("--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["criteria"][0]["class"], "already_passes")

    def test_no_or_stale_contract_exits_one(self) -> None:
        self.assertEqual(self.run_cli()[0], 1)
        self.write_gate({"id": "a", "argv": emitting()})
        contract.derive(self.root)
        self.write_gate({"id": "a", "argv": emitting(code=1)})
        self.assertEqual(self.run_cli()[0], 1)
        self.assertFalse((self.root / ".gatekit" / "baseline.json").exists())

    def test_the_budget_is_respected(self) -> None:
        import time
        self.write_gate({"id": "one", "argv": emitting(sleep=0.6), "timeout_s": 5},
                        {"id": "two", "argv": emitting(sleep=0.6), "timeout_s": 5})
        contract.derive(self.root)
        started = time.monotonic()
        result = contract.baseline(self.root, total_budget_s=0.3)
        self.assertLess(time.monotonic() - started, 1.2)
        self.assertEqual(set(self.classes(result).values()), {"unverified"})

    def test_the_stop_gate_record_is_untouched(self) -> None:
        self.write_gate({"id": "passes", "argv": emitting(stdout="ok\n")})
        contract.derive(self.root)
        contract.baseline(self.root)
        self.run_cli()
        self.assertIsNone(contract.load_last(self.root))
        self.assertIsNone(contract.reusable_last(self.root))


class TestReuseFollowsTheSignatures(TempProject):
    """A record saved under other signatures (e.g. before 0.14.0, when a
    zero-test run counted as ok) must not be reused."""

    def test_a_record_under_other_signatures_is_not_reused(self) -> None:
        from unittest import mock
        from gatekit import runcheck
        self.write_gate({"id": "a", "argv": emitting(stdout="ok\n")})
        contract.derive(self.root)
        contract.save_last(self.root, contract.execute(self.root))
        self.assertIsNotNone(contract.reusable_last(self.root))
        with mock.patch.object(runcheck, "signatures_digest", return_value="0" * 64):
            self.assertIsNone(contract.reusable_last(self.root))

    def test_a_record_without_the_digest_is_not_reused(self) -> None:
        self.write_gate({"id": "a", "argv": emitting(stdout="ok\n")})
        contract.derive(self.root)
        contract.save_last(self.root, contract.execute(self.root))
        path = self.root / ".gatekit" / "runs" / "contract-last.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record.pop("signatures_sha256", None)
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertIsNone(contract.reusable_last(self.root))

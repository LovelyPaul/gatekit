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

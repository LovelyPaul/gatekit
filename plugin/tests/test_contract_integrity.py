"""ADR-0027 decision 2: the Stop gate and `contract run` check the approval and
the contract before judging."""
from __future__ import annotations

import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import approval, contract, ledger  # noqa: E402
from gatekit.gates import stop as stop_gate  # noqa: E402

PY = sys.executable
STOP_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "stop.py"


class Project(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        (self.root / "tests").mkdir()
        self.test_file = self.root / "tests" / "test_a.py"
        self.test_file.write_text("raise SystemExit(0)\n", encoding="utf-8")
        self.session = "sess-integrity"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def gate(self, *criteria: dict, budget: float = None) -> None:
        body = "# Gate\n\n"
        if budget is not None:
            body += "```gatekit-budget\n" + json.dumps({"total_budget_s": budget}) + "\n```\n"
        body += "".join("```gatekit-criterion\n" + json.dumps(c) + "\n```\n" for c in criteria)
        (self.root / "spec" / "05-gate.md").write_text(body, encoding="utf-8")
        contract.derive(self.root)

    def passing(self, approve: bool = True) -> None:
        self.gate({"id": "unit", "argv": [PY, "tests/test_a.py"], "timeout_s": 20},
                  {"id": "smoke", "argv": [PY, "-c", "pass"], "timeout_s": 20, "tier": "verify"})
        if approve:
            approval.approve(self.root, "spec/05-gate.md")

    def failing(self) -> None:
        self.gate({"id": "bad", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20})
        approval.approve(self.root, "spec/05-gate.md")

    def edit_contract(self, fn) -> None:
        path = self.root / ".gatekit" / "contract.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        fn(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def edit_approvals(self, fn) -> None:
        path = self.root / ".gatekit" / "approvals.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        fn(data["approvals"][0])
        path.write_text(json.dumps(data), encoding="utf-8")

    def set_pipeline(self, name: str) -> None:
        led = ledger.Ledger.load(self.root, self.session)
        led.data["active_pipeline"] = name
        led.save()

    def stop(self):
        return stop_gate.handle({"session_id": self.session, "hook_event_name": "Stop",
                                 "cwd": str(self.root), "stop_hook_active": False})

    def led(self) -> ledger.Ledger:
        return ledger.Ledger.load(self.root, self.session)


class TestIntegrity(Project):
    def test_approved_and_matching_is_clear(self) -> None:
        self.passing()
        self.assertIsNone(contract.integrity(self.root))
        self.assertIsNone(contract.integrity(self.root, require_approval=False))

    def test_unapproved_is_gate_not_approved(self) -> None:
        self.passing(approve=False)
        result = contract.integrity(self.root)
        self.assertEqual(result["verdict"], "unverified")
        self.assertEqual(result["criteria"], [])
        self.assertEqual(result["reasons"], [contract.GATE_NOT_APPROVED_REASON])
        self.assertEqual(result["approval"], "unverified")
        # Baseline runs before approval: only the contract itself is checked.
        self.assertIsNone(contract.integrity(self.root, require_approval=False))

    def test_tampered_approval_hash(self) -> None:
        self.passing()
        self.edit_approvals(lambda e: e.update(sha256="0" * 64))
        result = contract.integrity(self.root)
        self.assertEqual(result["reasons"], [contract.GATE_NOT_APPROVED_REASON])
        self.assertEqual(result["approval"], "fail")

    def test_tampered_grading_pin_names_the_file(self) -> None:
        self.passing()
        self.edit_approvals(lambda e: e["grading"]["unit"].update({"tests/test_a.py": "0" * 64}))
        result = contract.integrity(self.root)
        self.assertEqual(result["reasons"], [contract.GATE_NOT_APPROVED_REASON,
                                             contract.GRADING_UNAPPROVED_REASON])
        self.assertEqual(result["unapproved_grading"], ["tests/test_a.py"])

    def test_stale_comes_first(self) -> None:
        self.passing()
        with open(self.root / "spec" / "05-gate.md", "a", encoding="utf-8") as fh:
            fh.write("\nedited\n")
        self.assertEqual(contract.integrity(self.root)["reasons"], [contract.STALE_REASON])

    def test_no_contract_is_left_to_execute(self) -> None:
        self.assertIsNone(contract.integrity(self.root))

    def test_every_field_is_compared(self) -> None:
        edits = {
            "argv": lambda d: d["criteria"][0].update(argv=[PY, "-c", "pass"]),
            "expect": lambda d: d["criteria"][0].update(expect={"exit": 1}),
            "timeout_s": lambda d: d["criteria"][0].update(timeout_s=999.0),
            "tier": lambda d: d["criteria"][0].update(tier="verify"),
            "artifacts": lambda d: d["criteria"][0].update(artifacts=["x"]),
            "id": lambda d: d["criteria"][0].update(id="renamed"),
            "extra key": lambda d: d["criteria"][0].update(skip=True),
            "removed": lambda d: d["criteria"].pop(),
            "added": lambda d: d["criteria"].append(dict(d["criteria"][0], id="more")),
            "order": lambda d: d["criteria"].reverse(),
            "budget": lambda d: d.update(total_budget_s=1.0),
            "grading key": lambda d: d["criteria"][0]["grading"].update({"src/app.py": "x"}),
        }
        for name, fn in edits.items():
            with self.subTest(edit=name):
                self.passing()
                (self.root / "src").mkdir(exist_ok=True)
                (self.root / "src" / "app.py").write_text("", encoding="utf-8")
                self.edit_contract(fn)
                # A renamed id also breaks the approval's grading pin, so the
                # approval check may come first; either way it is refused.
                self.assertIsNotNone(contract.integrity(self.root), name)
                result = contract.integrity(self.root, require_approval=False)
                self.assertIsNotNone(result, name)
                self.assertEqual(result["reasons"], [contract.CONTRACT_MISMATCH_REASON])
                self.assertTrue(result["mismatch"])

    def test_grading_hashes_are_not_compared_with_the_tree(self) -> None:
        self.passing()
        self.test_file.write_text("raise SystemExit(0)  # edited\n", encoding="utf-8")
        self.assertIsNone(contract.integrity(self.root))
        # ADR-0023 still holds the criterion back with the path.
        crit = [c for c in contract.execute(self.root)["criteria"] if c["id"] == "unit"][0]
        self.assertEqual(crit["verdict"], "unverified")
        self.assertEqual(crit["grading_changed"], ["tests/test_a.py"])

    def test_deleted_grading_file_is_not_a_mismatch(self) -> None:
        self.passing()
        self.test_file.unlink()
        self.assertIsNone(contract.integrity(self.root))

    def test_gate_that_no_longer_parses_is_a_mismatch(self) -> None:
        self.passing()
        gate = self.root / "spec" / "05-gate.md"
        gate.write_text("```gatekit-criterion\n{not json\n```\n", encoding="utf-8")
        self.edit_contract(lambda d: d.update(source_sha256=approval.sha256_file(gate)))
        result = contract.integrity(self.root, require_approval=False)
        self.assertEqual(result["reasons"], [contract.CONTRACT_MISMATCH_REASON])


class TestEntryPoints(Project):
    def run_cli(self, *args: str) -> "tuple[int, str]":
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = contract.run(list(args) + ["--root", str(self.root)])
        return code, out.getvalue() + err.getvalue()

    def test_contract_run_refuses_a_mismatch(self) -> None:
        self.failing()
        self.edit_contract(lambda d: d["criteria"][0].update(argv=[PY, "-c", "pass"]))
        code, out = self.run_cli("run")
        self.assertEqual(code, 1)
        self.assertIn("unverified", out)
        self.assertIn(contract.CONTRACT_MISMATCH_REASON, out)
        self.assertIsNone(contract.load_last(self.root))

    def test_contract_run_refuses_unapproved(self) -> None:
        self.passing(approve=False)
        code, out = self.run_cli("run")
        self.assertEqual(code, 1)
        self.assertIn(contract.GATE_NOT_APPROVED_REASON, out)

    def test_contract_run_ok_when_approved(self) -> None:
        self.passing()
        code, out = self.run_cli("run")
        self.assertEqual(code, 0, out)
        self.assertEqual(contract.load_last(self.root)["contract_sha256"],
                         approval.sha256_file(self.root / ".gatekit" / "contract.json"))

    def test_baseline_before_approval_works(self) -> None:
        self.passing(approve=False)
        record = contract.baseline(self.root)
        self.assertEqual({r["id"] for r in record["criteria"]}, {"unit", "smoke"})

    def test_baseline_refuses_a_mismatch(self) -> None:
        self.passing(approve=False)
        self.edit_contract(lambda d: d["criteria"][0].update(argv=[PY, "-c", "pass"]))
        with self.assertRaises(ValueError) as caught:
            contract.baseline(self.root)
        self.assertIn(contract.CONTRACT_MISMATCH_REASON, str(caught.exception))

    def test_reuse_needs_the_same_contract_file(self) -> None:
        self.passing()
        contract.save_last(self.root, contract.execute(self.root))
        self.assertIsNotNone(contract.same_tree_record(self.root))
        self.edit_contract(lambda d: d.update(note="x"))
        self.assertIsNone(contract.same_tree_record(self.root))

    def test_record_without_contract_hash_is_not_reused(self) -> None:
        self.passing()
        contract.save_last(self.root, contract.execute(self.root))
        path = self.root / ".gatekit" / "runs" / contract.LAST_RESULT_NAME
        record = json.loads(path.read_text(encoding="utf-8"))
        record.pop("contract_sha256")
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertIsNone(contract.same_tree_record(self.root))


class TestStopGate(Project):
    def test_normal_flow_is_judged_and_allowed(self) -> None:
        self.passing()
        self.set_pipeline("verify")
        self.assertIsNone(self.stop())
        self.assertEqual(self.led().data["stop"]["final_verdict"], "ok")

    def test_edited_contract_blocks_with_contract_mismatch(self) -> None:
        self.failing()
        self.edit_contract(lambda d: d["criteria"][0].update(argv=[PY, "-c", "pass"]))
        for pipeline in ("build", "verify"):
            with self.subTest(pipeline=pipeline):
                self.set_pipeline(pipeline)
                result = self.stop()
                self.assertEqual(result["decision"], "block")
                self.assertIn("contract_mismatch", result["reason"])
                self.assertIn("/gatekit:gate", result["reason"])
                self.assertIn("contract derive", result["reason"])
                self.assertIn(contract.CONTRACT_MISMATCH_REASON,
                              self.led().data["stop"]["last_reasons"])
        self.assertIsNone(contract.load_last(self.root))

    def test_tampered_approval_blocks_with_gate_not_approved(self) -> None:
        self.passing()
        self.edit_approvals(lambda e: e.update(sha256="0" * 64))
        self.set_pipeline("verify")
        result = self.stop()
        self.assertEqual(result["decision"], "block")
        self.assertIn("gate_not_approved", result["reason"])
        self.assertIn("/gatekit:gate", result["reason"])

    def test_tampered_pin_keeps_the_grading_message(self) -> None:
        self.passing()
        self.edit_approvals(lambda e: e["grading"]["unit"].update({"tests/test_a.py": "0" * 64}))
        self.set_pipeline("verify")
        reason = self.stop()["reason"]
        self.assertIn("grading_unapproved", reason)
        self.assertIn("tests/test_a.py", reason)

    def test_reused_ok_is_refused_after_an_edit(self) -> None:
        self.failing()
        # A record of `ok` for this tree, then the contract loosened to match it.
        self.edit_contract(lambda d: d["criteria"][0].update(argv=[PY, "-c", "pass"]))
        result = contract.execute(self.root)
        self.assertEqual(result["verdict"], "ok")
        contract.save_last(self.root, result)
        self.set_pipeline("verify")
        stopped = self.stop()
        self.assertEqual(stopped["decision"], "block")
        self.assertIn("contract_mismatch", stopped["reason"])
        self.assertNotIn("stop_reused", [e.get("kind") for e in self.led().data.get("events", [])])

    def test_unchanged_tree_still_reuses(self) -> None:
        self.passing()
        self.set_pipeline("verify")
        self.assertIsNone(self.stop())
        led = self.led()
        led.data["stop"]["stood_down"] = None
        led.save()
        self.assertIsNone(self.stop())
        kinds = json.dumps(self.led().data)
        self.assertIn("stop_reused", kinds)

    def test_three_blocks_then_stand_down(self) -> None:
        self.passing(approve=False)
        self.set_pipeline("verify")
        for _ in range(3):
            self.assertIsNotNone(self.stop())
        self.assertIsNone(self.stop())
        self.assertEqual(self.led().data["stop"]["final_verdict"], "unverified")

    def test_korean_messages(self) -> None:
        self.failing()
        self.edit_contract(lambda d: d["criteria"][0].update(argv=[PY, "-c", "pass"]))
        led = self.led()
        led.data["active_pipeline"] = "verify"
        led.data["output_lang"] = "ko"
        led.save()
        reason = self.stop()["reason"]
        self.assertIn("contract_mismatch", reason)
        self.assertRegex(reason, "[가-힣]")

    def test_corrupt_approvals_exits_zero(self) -> None:
        self.passing()
        self.set_pipeline("verify")
        (self.root / ".gatekit" / "approvals.json").write_text("{nope", encoding="utf-8")
        proc = subprocess.run(
            [PY, str(STOP_SCRIPT)], capture_output=True, text=True, timeout=120,
            input=json.dumps({"session_id": self.session, "hook_event_name": "Stop",
                              "cwd": str(self.root)}))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("gate_not_approved", proc.stdout)


if __name__ == "__main__":
    unittest.main()

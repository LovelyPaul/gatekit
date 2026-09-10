"""Tests for gates/question.py — the AskUserQuestion budget counter."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import ledger  # noqa: E402
from gatekit.gates import question as question_gate  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "question.py"


class QuestionProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        self.session = "sess-q"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def event(self) -> dict:
        return {
            "session_id": self.session,
            "hook_event_name": "PostToolUse",
            "cwd": str(self.root),
            "tool_name": "AskUserQuestion",
            "tool_input": {"questions": [{"question": "which stack?"}]},
            "tool_response": {},
        }

    def led(self) -> ledger.Ledger:
        return ledger.Ledger.load(self.root, self.session)

    def set_pipeline(self, name, max_calls=None) -> None:
        led = self.led()
        led.data["active_pipeline"] = name
        if max_calls is not None:
            led.data["questions"]["max_calls"] = max_calls
        led.save()


class TestCounting(QuestionProject):
    def test_increments_asked(self) -> None:
        question_gate.handle(self.event())
        self.assertEqual(self.led().data["questions"]["asked"], 1)

    def test_increments_cumulatively(self) -> None:
        for _ in range(3):
            question_gate.handle(self.event())
        self.assertEqual(self.led().data["questions"]["asked"], 3)

    def test_returns_none_never_blocks(self) -> None:
        """PostToolUse has no block path; this gate is informational only."""
        for _ in range(5):
            self.assertIsNone(question_gate.handle(self.event()))

    def test_records_event(self) -> None:
        question_gate.handle(self.event())
        kinds = [e["kind"] for e in self.led().data["events"]]
        self.assertIn("question_asked", kinds)


class TestBudget(QuestionProject):
    def test_within_budget_is_not_exceeded(self) -> None:
        self.set_pipeline("interview", max_calls=2)
        question_gate.handle(self.event())
        question_gate.handle(self.event())
        self.assertFalse(self.led().data["questions"]["budget_exceeded"])

    def test_over_budget_sets_flag(self) -> None:
        self.set_pipeline("interview", max_calls=2)
        for _ in range(3):
            question_gate.handle(self.event())
        data = self.led().data["questions"]
        self.assertEqual(data["asked"], 3)
        self.assertTrue(data["budget_exceeded"])

    def test_flag_is_informational_not_a_block(self) -> None:
        self.set_pipeline("interview", max_calls=1)
        question_gate.handle(self.event())
        self.assertIsNone(question_gate.handle(self.event()))
        self.assertTrue(self.led().data["questions"]["budget_exceeded"])

    def test_non_interview_pipeline_is_unlimited(self) -> None:
        self.set_pipeline("build")
        for _ in range(20):
            question_gate.handle(self.event())
        self.assertFalse(self.led().data["questions"]["budget_exceeded"])

    def test_no_pipeline_is_unlimited(self) -> None:
        for _ in range(20):
            question_gate.handle(self.event())
        self.assertFalse(self.led().data["questions"]["budget_exceeded"])

    def test_interview_budget_default_is_two(self) -> None:
        self.set_pipeline("interview")
        for _ in range(3):
            question_gate.handle(self.event())
        self.assertTrue(self.led().data["questions"]["budget_exceeded"])

    def test_config_can_raise_the_interview_budget(self) -> None:
        (self.root / ".gatekit" / "config.json").write_text(
            json.dumps({"questions": {"interview_max_calls": 5}}), encoding="utf-8"
        )
        led = self.led()
        led.data["active_pipeline"] = "interview"
        led.save()
        for _ in range(4):
            question_gate.handle(self.event())
        self.assertFalse(self.led().data["questions"]["budget_exceeded"])


class TestSubprocess(QuestionProject):
    def _run(self, event: dict) -> "tuple[int, str, str]":
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_counts_via_subprocess(self) -> None:
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")
        self.assertEqual(self.led().data["questions"]["asked"], 1)

    def test_over_budget_via_subprocess_still_exits_zero(self) -> None:
        self.set_pipeline("interview", max_calls=1)
        self._run(self.event())
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")
        self.assertTrue(self.led().data["questions"]["budget_exceeded"])

    def test_internal_error_exits_zero_and_logs(self) -> None:
        runs = self.root / ".gatekit" / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        (runs / f"{self.session}.json").mkdir()
        code, _, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)
        self.assertTrue((runs / "hook-errors.log").is_file())

    def test_malformed_stdin_exits_zero(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input="{oops",
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

"""Tests for gates/stop.py — contract-enforced completion."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import contract, ledger  # noqa: E402
from gatekit.gates import stop as stop_gate  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "stop.py"
PY = sys.executable


class StopProject(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        self.gate_md = self.root / "spec" / "05-gate.md"
        self.session = "sess-stop"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_contract(self, *criteria: dict) -> None:
        body = "# Gate\n\n" + "".join(
            "```gatekit-criterion\n" + json.dumps(c) + "\n```\n" for c in criteria
        )
        self.gate_md.write_text(body, encoding="utf-8")
        contract.derive(self.root)

    def passing(self) -> None:
        self.write_contract({"id": "ok-crit", "argv": [PY, "-c", "pass"], "timeout_s": 20})

    def failing(self) -> None:
        self.write_contract(
            {"id": "bad-crit", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20}
        )

    def set_pipeline(self, name: str) -> None:
        led = ledger.Ledger.load(self.root, self.session)
        led.data["active_pipeline"] = name
        led.save()

    def event(self, stop_hook_active: bool = False) -> dict:
        return {
            "session_id": self.session,
            "hook_event_name": "Stop",
            "cwd": str(self.root),
            "stop_hook_active": stop_hook_active,
        }

    def led(self) -> ledger.Ledger:
        return ledger.Ledger.load(self.root, self.session)


class TestBlocking(StopProject):
    def test_failing_contract_blocks_in_build(self) -> None:
        self.failing()
        self.set_pipeline("build")
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertEqual(result["decision"], "block")
        self.assertIn("bad-crit", result["reason"])

    def test_failing_contract_blocks_in_verify(self) -> None:
        self.failing()
        self.set_pipeline("verify")
        self.assertIsNotNone(stop_gate.handle(self.event()))

    def test_block_increments_count(self) -> None:
        self.failing()
        self.set_pipeline("build")
        stop_gate.handle(self.event())
        self.assertEqual(self.led().data["stop"]["block_count"], 1)

    def test_blocks_at_most_three_times(self) -> None:
        self.failing()
        self.set_pipeline("build")
        for _ in range(3):
            self.assertIsNotNone(stop_gate.handle(self.event()))
        # 4th attempt: block_count is now 3, so it must let the session stop.
        self.assertIsNone(stop_gate.handle(self.event()))

    def test_stop_hook_active_never_blocks(self) -> None:
        self.failing()
        self.set_pipeline("build")
        self.assertIsNone(stop_gate.handle(self.event(stop_hook_active=True)))

    def test_stop_hook_active_records_verdict(self) -> None:
        self.failing()
        self.set_pipeline("build")
        stop_gate.handle(self.event(stop_hook_active=True))
        self.assertIsNotNone(self.led().data["stop"]["final_verdict"])

    def test_unverified_also_blocks(self) -> None:
        self.write_contract(
            {"id": "slow", "argv": [PY, "-c", "import time; time.sleep(5)"], "timeout_s": 1}
        )
        self.set_pipeline("build")
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertIn("slow", result["reason"])

    def test_reason_lists_criterion_ids(self) -> None:
        self.write_contract(
            {"id": "alpha", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20},
            {"id": "beta", "argv": [PY, "-c", "raise SystemExit(1)"], "timeout_s": 20},
        )
        self.set_pipeline("build")
        reason = stop_gate.handle(self.event())["reason"]
        self.assertIn("alpha", reason)
        self.assertIn("beta", reason)

    def test_reasons_stored_in_ledger(self) -> None:
        self.failing()
        self.set_pipeline("build")
        stop_gate.handle(self.event())
        self.assertTrue(self.led().data["stop"]["last_reasons"])


class TestAllowing(StopProject):
    def test_passing_contract_allows(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.assertIsNone(stop_gate.handle(self.event()))

    def test_passing_records_ok_verdict(self) -> None:
        self.passing()
        self.set_pipeline("build")
        stop_gate.handle(self.event())
        self.assertEqual(self.led().data["stop"]["final_verdict"], "ok")

    def test_no_contract_allows(self) -> None:
        self.set_pipeline("build")
        self.assertIsNone(stop_gate.handle(self.event()))

    def test_inactive_pipeline_allows_without_running(self) -> None:
        self.failing()
        self.set_pipeline("interview")
        self.assertIsNone(stop_gate.handle(self.event()))

    def test_no_pipeline_allows(self) -> None:
        self.failing()
        self.assertIsNone(stop_gate.handle(self.event()))

    def test_final_verdict_is_never_blank_on_allow(self) -> None:
        self.passing()
        self.set_pipeline("build")
        stop_gate.handle(self.event())
        final = self.led().data["stop"]["final_verdict"]
        self.assertTrue(final)
        self.assertIn(final, ("ok", "warn", "fail", "unverified"))

    def test_verdict_recorded_when_giving_up_after_three_blocks(self) -> None:
        self.failing()
        self.set_pipeline("build")
        for _ in range(3):
            stop_gate.handle(self.event())
        stop_gate.handle(self.event())
        self.assertEqual(self.led().data["stop"]["final_verdict"], "fail")

    def test_stale_contract_blocks_with_stale_reason(self) -> None:
        self.passing()
        self.set_pipeline("build")
        self.gate_md.write_text(
            self.gate_md.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8"
        )
        result = stop_gate.handle(self.event())
        self.assertIsNotNone(result)
        self.assertIn("contract_stale", result["reason"])


class TestLanguage(StopProject):
    def test_korean_reason(self) -> None:
        self.failing()
        led = self.led()
        led.data["active_pipeline"] = "build"
        led.set_output_lang("ko")
        led.save()
        reason = stop_gate.handle(self.event())["reason"]
        self.assertTrue(any("가" <= ch <= "힣" for ch in reason), reason)

    def test_english_reason_by_default(self) -> None:
        self.failing()
        self.set_pipeline("build")
        reason = stop_gate.handle(self.event())["reason"]
        self.assertFalse(any("가" <= ch <= "힣" for ch in reason), reason)


class TestSubprocess(StopProject):
    def _run(self, event: dict) -> "tuple[int, str, str]":
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT)],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_allow_via_subprocess(self) -> None:
        self.passing()
        self.set_pipeline("build")
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "")

    def test_block_via_subprocess_uses_top_level_decision(self) -> None:
        self.failing()
        self.set_pipeline("build")
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("reason", payload)

    def test_internal_error_exits_zero_and_logs(self) -> None:
        self.failing()
        self.set_pipeline("build")
        runs = self.root / ".gatekit" / "runs"
        # Corrupt the ledger into a directory so every ledger write raises.
        target = runs / f"{self.session}.json"
        target.unlink()
        target.mkdir()
        code, _, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)
        self.assertTrue((runs / "hook-errors.log").is_file())

    def test_corrupt_contract_json_exits_zero(self) -> None:
        self.set_pipeline("build")
        (self.root / ".gatekit" / "contract.json").write_text("{broken", encoding="utf-8")
        code, out, err = self._run(self.event())
        self.assertEqual(code, 0, err)
        self.assertNotIn("Traceback", err)

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

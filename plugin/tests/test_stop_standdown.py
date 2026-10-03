"""ADR-0024: the Stop gate stands down after the build, runs only turn-tier
criteria under build, and keeps a time budget."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import config, contract, doctor, hookio, jobs, ledger, spec, verdict  # noqa: E402
from gatekit.gates import prompt as prompt_gate  # noqa: E402
from gatekit.gates import stop as stop_gate  # noqa: E402

GATE_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "gatekit" / "gates" / "stop.py"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "spec"
PY = sys.executable

JOB_A = "20260101T000000Z-aaaa"
JOB_B = "20260101T000001Z-bbbb"

BUILD_PROMPT = ("<command-message>gatekit:build</command-message>\n"
                "<command-name>/gatekit:build</command-name>\n"
                "<command-args></command-args>")
VERIFY_PROMPT = ("<command-message>gatekit:verify</command-message>\n"
                 "<command-name>/gatekit:verify</command-name>\n"
                 "<command-args></command-args>")


def counting(crit_id: str, exit_code: int = 0, **extra) -> dict:
    """A criterion that appends its id to test-results/runs.txt when it runs
    (test-results/ is outside the tree fingerprint)."""
    code = (
        "import pathlib; p = pathlib.Path('test-results/runs.txt'); "
        "p.parent.mkdir(exist_ok=True); "
        "p.write_text((p.read_text() if p.exists() else '') + '%s,'); "
        "raise SystemExit(%d)" % (crit_id, exit_code)
    )
    crit = {"id": crit_id, "argv": [PY, "-c", code], "timeout_s": 20}
    crit.update(extra)
    return crit


def sleeping(crit_id: str, seconds: float, **extra) -> dict:
    code = (
        "import pathlib, time; p = pathlib.Path('test-results/runs.txt'); "
        "p.parent.mkdir(exist_ok=True); "
        "p.write_text((p.read_text() if p.exists() else '') + '%s,'); "
        "time.sleep(%s)" % (crit_id, seconds)
    )
    crit = {"id": crit_id, "argv": [PY, "-c", code], "timeout_s": 20}
    crit.update(extra)
    return crit


class Project(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        self.gate_md = self.root / "spec" / "05-gate.md"
        self.session = "sess-0024"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_contract(self, *criteria: dict, budget: float = 0) -> None:
        body = "# Gate\n\n"
        if budget:
            body += "```gatekit-budget\n" + json.dumps({"total_budget_s": budget}) + "\n```\n"
        body += "".join("```gatekit-criterion\n" + json.dumps(c) + "\n```\n" for c in criteria)
        self.gate_md.write_text(body, encoding="utf-8")
        contract.derive(self.root)

    def write_config(self, obj: dict) -> None:
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(obj), encoding="utf-8")

    def prompt(self, text: str) -> dict:
        return prompt_gate.handle({"session_id": self.session, "cwd": str(self.root),
                                   "hook_event_name": "UserPromptSubmit", "prompt": text})

    def stop(self, stop_hook_active: bool = False):
        return stop_gate.handle({"session_id": self.session, "cwd": str(self.root),
                                 "hook_event_name": "Stop",
                                 "stop_hook_active": stop_hook_active})

    def led(self) -> ledger.Ledger:
        return ledger.Ledger.load(self.root, self.session)

    def set_lang(self, lang: str) -> None:
        led = self.led()
        led.set_output_lang(lang)
        led.save()

    def runs(self) -> list:
        path = self.root / "test-results" / "runs.txt"
        return [p for p in path.read_text().split(",") if p] if path.exists() else []

    def touch_source(self, name: str = "app.py") -> None:
        path = self.root / "src" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(str(len(self.runs())) + os.urandom(4).hex(), encoding="utf-8")

    def make_job(self, states: dict, job_id: str = JOB_A) -> str:
        jdir = jobs.job_dir(self.root, job_id)
        (jdir / "tasks").mkdir(parents=True, exist_ok=True)
        jobs.write_json(jdir / "job.json", {"version": 1, "job_id": job_id,
                                            "started_at": jobs._now(), "execution": "host",
                                            "tasks": list(states),
                                            "backend": {"name": "claude"}})
        self.set_states(states, job_id)
        return job_id

    def set_states(self, states: dict, job_id: str = JOB_A) -> None:
        jdir = jobs.job_dir(self.root, job_id)
        for task_id, state in states.items():
            tdir = jdir / "tasks" / task_id
            tdir.mkdir(parents=True, exist_ok=True)
            jobs.write_json(tdir / "status.json", {"task_id": task_id, "state": state})

    def events(self, kind: str) -> list:
        return [e for e in self.led().data["events"] if e["kind"] == kind]


# --------------------------------------------------------------------------
# Decision 1: stand-down
# --------------------------------------------------------------------------


class TestBuildStandDown(Project):
    def test_no_job_keeps_judging_every_stop(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.assertIsNone(self.stop())
        self.touch_source()
        self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["c", "c"])
        self.assertIsNone(self.led().data["stop"]["stood_down"])

    def test_unfinished_job_judges_and_an_ok_does_not_stand_down(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed", "t2": "queued"})
        self.assertIsNone(self.stop())
        self.touch_source()
        self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["c", "c"])
        self.assertIsNone(self.led().data["stop"]["stood_down"])

    def test_unfinished_job_failing_contract_blocks(self) -> None:
        self.write_contract(counting("c", exit_code=1))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "running"})
        result = self.stop()
        self.assertEqual(result["decision"], "block")

    def test_handoff_runs_once_then_stands_down(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed", "t2": "passed"})
        self.assertIsNone(self.stop())  # the handoff check
        self.assertEqual(self.runs(), ["c"])
        stood = self.led().data["stop"]["stood_down"]
        self.assertEqual(stood["pipeline"], "build")
        self.assertEqual(stood["job_id"], JOB_A)
        self.assertEqual(stood["verdict"], verdict.OK)
        self.assertEqual(len(self.events("stop_stood_down")), 1)
        for _ in range(3):
            self.touch_source()  # follow-up edits that would otherwise re-run it
            self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["c"])
        self.assertEqual(self.led().data["stop"]["stood_down"]["skipped"], 3)
        self.assertEqual(self.led().data["stop"]["final_verdict"], verdict.OK)
        self.assertEqual(len(self.events("stop_stood_down")), 1)

    def test_handoff_that_fails_blocks_and_keeps_judging(self) -> None:
        self.write_contract(counting("c", exit_code=1))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.assertEqual(self.stop()["decision"], "block")
        self.assertIsNone(self.led().data["stop"]["stood_down"])
        self.touch_source()
        self.assertEqual(self.stop()["decision"], "block")
        self.assertEqual(self.runs(), ["c", "c"])

    def test_handoff_fixed_on_retry_then_stands_down(self) -> None:
        self.write_contract(counting("c", exit_code=1))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.assertEqual(self.stop()["decision"], "block")
        self.write_contract(counting("c", exit_code=0))
        self.assertIsNone(self.stop())
        self.assertIsNotNone(self.led().data["stop"]["stood_down"])

    def test_stop_hook_active_with_a_failure_does_not_stand_down(self) -> None:
        self.write_contract(counting("c", exit_code=1))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.assertEqual(self.stop()["decision"], "block")
        self.assertIsNone(self.stop(stop_hook_active=True))
        self.assertIsNone(self.led().data["stop"]["stood_down"])
        self.touch_source()
        self.assertEqual(self.stop()["decision"], "block")

    def test_stop_hook_active_with_ok_stands_down(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.assertIsNone(self.stop(stop_hook_active=True))
        self.assertIsNotNone(self.led().data["stop"]["stood_down"])

    def test_failed_job_blocks_up_to_max_then_records_and_stands_down(self) -> None:
        self.write_contract(counting("c", exit_code=1))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed", "t2": "failed", "t3": "blocked"})
        for _ in range(stop_gate.MAX_BLOCKS):
            self.touch_source()
            self.assertEqual(self.stop()["decision"], "block")
            self.assertIsNone(self.led().data["stop"]["stood_down"])
        self.touch_source()
        self.assertIsNone(self.stop())  # out of blocks: final_verdict
        data = self.led().data["stop"]
        self.assertEqual(data["final_verdict"], verdict.FAIL)
        self.assertEqual(data["stood_down"]["verdict"], verdict.FAIL)
        runs = len(self.runs())
        self.touch_source()
        self.assertIsNone(self.stop())
        self.assertEqual(len(self.runs()), runs)
        self.assertEqual(self.led().data["stop"]["final_verdict"], verdict.FAIL)

    def test_a_new_job_clears_the_stand_down(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.stop()
        self.make_job({"t9": "queued"}, job_id=JOB_B)
        self.touch_source()
        self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["c", "c"])
        self.assertIsNone(self.led().data["stop"]["stood_down"])

    def test_a_job_with_no_tasks_is_not_settled(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({})
        self.stop()
        self.touch_source()
        self.stop()
        self.assertEqual(self.runs(), ["c", "c"])
        self.assertIsNone(self.led().data["stop"]["stood_down"])

    def test_a_new_settled_job_clears_the_stand_down(self) -> None:
        # The new job is already settled when the Stop sees it, so only the
        # job id tells the gate this is not the job it stood down for.
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.stop()
        self.make_job({"t9": "passed"}, job_id=JOB_B)
        self.touch_source()
        self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["c", "c"])
        self.assertEqual(self.led().data["stop"]["stood_down"]["job_id"], JOB_B)

    def test_a_redelegated_task_clears_the_stand_down(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed", "t2": "failed"})
        led = self.led()
        led.data["stop"]["block_count"] = stop_gate.MAX_BLOCKS
        led.save()
        self.stop()  # out of blocks: `fail` recorded, stands down
        self.assertEqual(self.led().data["stop"]["stood_down"]["verdict"], verdict.FAIL)
        self.set_states({"t2": "queued"})
        self.touch_source()
        self.stop()
        self.assertEqual(self.runs(), ["c", "c"])
        self.assertIsNone(self.led().data["stop"]["stood_down"])

    def test_a_new_build_prompt_rearms(self) -> None:
        self.write_contract(counting("c", exit_code=1))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        for _ in range(stop_gate.MAX_BLOCKS + 1):
            self.touch_source()
            self.stop()
        self.assertIsNotNone(self.led().data["stop"]["stood_down"])
        self.prompt(BUILD_PROMPT)
        data = self.led().data["stop"]
        self.assertIsNone(data["stood_down"])
        self.assertEqual(data["block_count"], 0)
        self.assertIsNone(data["final_verdict"])
        self.assertEqual(len(self.events("stop_rearmed")), 2)
        self.touch_source()
        self.assertEqual(self.stop()["decision"], "block")

    def test_a_verify_prompt_rearms_and_judges(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.stop()
        self.prompt(VERIFY_PROMPT)
        self.assertIsNone(self.led().data["stop"]["stood_down"])
        self.touch_source()
        self.stop()
        self.assertEqual(self.runs(), ["c", "c"])

    def test_plain_prompt_does_not_rearm(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.stop()
        self.prompt("can you also add a dark mode toggle?")
        self.touch_source()
        self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["c"])

    def test_stood_down_stop_runs_no_criterion_even_when_contract_execute_breaks(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.stop()
        original = contract.execute

        def boom(*args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("contract executed after stand-down")

        contract.execute = boom
        try:
            self.touch_source()
            self.assertIsNone(self.stop())
        finally:
            contract.execute = original


class TestVerifyStandDown(Project):
    def test_verify_judges_until_its_verdict_then_stands_down(self) -> None:
        self.write_contract(counting("c", exit_code=1))
        self.prompt(VERIFY_PROMPT)
        self.assertEqual(self.stop()["decision"], "block")
        self.assertIsNone(self.led().data["stop"]["stood_down"])
        self.write_contract(counting("c"))
        self.assertIsNone(self.stop())
        stood = self.led().data["stop"]["stood_down"]
        self.assertEqual(stood["pipeline"], "verify")
        runs = len(self.runs())
        self.touch_source()
        self.assertIsNone(self.stop())
        self.assertEqual(len(self.runs()), runs)

    def test_verify_after_max_blocks_stands_down(self) -> None:
        self.write_contract(counting("c", exit_code=1))
        self.prompt(VERIFY_PROMPT)
        for _ in range(stop_gate.MAX_BLOCKS):
            self.touch_source()
            self.assertEqual(self.stop()["decision"], "block")
        self.touch_source()
        self.assertIsNone(self.stop())
        self.assertEqual(self.led().data["stop"]["stood_down"]["verdict"], verdict.FAIL)
        runs = len(self.runs())
        self.touch_source()
        self.assertIsNone(self.stop())
        self.assertEqual(len(self.runs()), runs)

    def test_build_stand_down_does_not_carry_into_a_set_pipeline_switch(self) -> None:
        # A stand-down names its pipeline; another pipeline is judged afresh.
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.stop()
        led = self.led()
        led.data["active_pipeline"] = "verify"
        led.save()
        self.touch_source()
        self.stop()
        self.assertEqual(self.runs(), ["c", "c"])


class TestStandDownContextLine(Project):
    def stood_down(self, lang: str = "en") -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.set_lang(lang)
        self.make_job({"t1": "passed"})
        self.stop()

    def test_english_line(self) -> None:
        self.stood_down("en")
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("follow-up edits are not gated", text)
        self.assertIn("/gatekit:verify", text)

    def test_korean_line(self) -> None:
        self.stood_down("ko")
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("게이트를 거치지 않", text)
        self.assertIn("/gatekit:verify", text)

    def test_korean_line_uses_the_manuals_terms(self) -> None:
        """ADR-0026: "Stop 게이트 … 물러남" as in docs/manual/07-gates.md,
        not the mixed "stop 게이트 해제" the 0.16.0 rehearsal showed."""
        self.stood_down("ko")
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("Stop 게이트 물러남", text)
        self.assertIn("turn 등급 판정 ok", text)
        self.assertNotIn("해제", text)
        self.assertNotIn("stop 게이트", text)


class TestContractFieldScope(Project):
    """ADR-0026: `contract=ok` next to a stand-down read as "fully verified"
    while verify-tier criteria had not been judged."""

    def stood_down(self, lang: str = "en") -> None:
        self.write_contract(counting("fast"), counting("suite", tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.set_lang(lang)
        self.make_job({"t1": "passed"})
        self.assertIsNone(self.stop())

    def test_turn_tier_result_names_the_deferred_count(self) -> None:
        self.stood_down("en")
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("contract=ok (last run: turn tier, 1 deferred to /gatekit:verify)", text)

    def test_korean_scope(self) -> None:
        self.stood_down("ko")
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("contract=ok (마지막 실행: turn 등급만, 1개는 /gatekit:verify 로 미룸)", text)

    def test_a_full_run_shows_plain_ok(self) -> None:
        self.stood_down("en")
        contract.save_last(self.root, contract.execute(self.root))
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("contract=ok", text)
        self.assertNotIn("contract=ok (", text)

    def test_no_record_shows_plain_ok(self) -> None:
        self.write_contract(counting("fast"), counting("suite", tier="verify"))
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("contract=ok", text)
        self.assertNotIn("contract=ok (", text)

    def test_budget_cut_names_the_unjudged(self) -> None:
        self.write_contract(counting("a"), counting("b"))
        contract.save_last(self.root, {
            "verdict": "unverified", "criteria": [{"id": "a", "verdict": "ok"}],
            "reasons": [], "scope": ["a"],
            "deferred": [{"id": "b", "tier": "turn", "reason": "budget"}]})
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("contract=ok (last run: 1 unjudged)", text)

    def test_record_for_another_contract_is_ignored(self) -> None:
        self.stood_down("en")
        self.write_contract(counting("fast"), counting("suite", tier="verify"),
                            counting("extra"))
        text = prompt_gate.build_context(self.root, self.led())
        self.assertNotIn("contract=ok (", text)

    def test_record_for_an_older_tree_is_ignored(self) -> None:
        # Review of 0.16.1: after edits the record describes another tree.
        self.stood_down("en")
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "edited.ts").write_text("x", encoding="utf-8")
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("contract=ok", text)
        self.assertNotIn("contract=ok (", text)

    def test_no_fingerprint_when_nothing_is_unjudged(self) -> None:
        # Review of 0.16.2: the tree fingerprint (an os.walk of up to 20 000
        # files) ran on every prompt before the cheap checks.
        self.stood_down("en")
        contract.save_last(self.root, contract.execute(self.root))
        with mock.patch.object(contract, "same_tree_record",
                               wraps=contract.same_tree_record) as spy:
            text = prompt_gate.build_context(self.root, self.led())
        spy.assert_not_called()
        self.assertNotIn("contract=ok (", text)

    def test_no_fingerprint_without_a_record_or_a_scope(self) -> None:
        self.write_contract(counting("a"), counting("b", tier="verify"))
        with mock.patch.object(contract, "same_tree_record") as spy:
            prompt_gate.build_context(self.root, self.led())
            contract.save_last(self.root, {"verdict": "ok", "criteria": [], "reasons": []})
            path = contract._last_result_path(self.root)
            record = json.loads(path.read_text(encoding="utf-8"))
            del record["scope"]
            path.write_text(json.dumps(record), encoding="utf-8")
            prompt_gate.build_context(self.root, self.led())
        spy.assert_not_called()

    def test_fingerprint_still_decides_when_something_is_unjudged(self) -> None:
        self.stood_down("en")
        with mock.patch.object(contract, "same_tree_record",
                               wraps=contract.same_tree_record) as spy:
            text = prompt_gate.build_context(self.root, self.led())
        spy.assert_called_once()
        self.assertIn("contract=ok (last run: turn tier", text)

    def test_record_without_scope_is_ignored(self) -> None:
        # A pre-ADR-0024 record does not say what it judged.
        self.write_contract(counting("a"), counting("b", tier="verify"))
        contract.save_last(self.root, {"verdict": "ok", "criteria": [], "reasons": []})
        path = contract._last_result_path(self.root)
        record = json.loads(path.read_text(encoding="utf-8"))
        del record["scope"]
        path.write_text(json.dumps(record), encoding="utf-8")
        text = prompt_gate.build_context(self.root, self.led())
        self.assertNotIn("contract=ok (", text)

    def test_suffix_never_reads_as_a_verdict(self) -> None:
        # The last turn-tier run failed: the suffix must not say "ok".
        self.write_contract(counting("a", exit_code=1), counting("b", tier="verify"))
        contract.save_last(self.root, contract.execute(self.root, tiers=("turn",)))
        self.assertEqual(contract.load_last(self.root)["result"]["verdict"], "fail")
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("contract=ok (last run: turn tier, 1 deferred to /gatekit:verify)", text)
        self.assertNotIn("ok (turn tier", text)

    def test_line_survives_the_600_char_cut(self) -> None:
        self.stood_down("ko")
        led = self.led()
        led.data["questions"].update({"asked": 99, "unjustified": 12345678901234567890,
                                      "repeated": 98765432109876543210,
                                      "unrealized": 55555555555555555555,
                                      "implementation_choice": True,
                                      "max_calls": "9" * 400})
        led.save()
        # Non-vacuous: uncut, the context is over the limit, so a line placed
        # late would be dropped.
        self.assertGreater(len(prompt_gate.build_context(self.root, self.led())),
                           hookio.MAX_CONTEXT_CHARS)
        result = self.prompt("계속해 주세요 " * 30)
        text = result["hookSpecificOutput"]["additionalContext"]
        self.assertLessEqual(len(text), hookio.MAX_CONTEXT_CHARS)
        self.assertIn("/gatekit:verify", text)

    def test_no_line_while_judging(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "queued"})
        self.stop()
        text = prompt_gate.build_context(self.root, self.led())
        self.assertNotIn("not gated", text)

    def test_no_line_once_the_stand_down_no_longer_applies(self) -> None:
        self.stood_down("en")
        self.make_job({"t9": "queued"}, job_id=JOB_B)
        self.assertNotIn("not gated", prompt_gate.build_context(self.root, self.led()))

    def test_rearming_prompt_shows_no_line(self) -> None:
        self.stood_down("en")
        result = self.prompt(BUILD_PROMPT)
        self.assertNotIn("not gated", result["hookSpecificOutput"]["additionalContext"])


class TestStandDownSubprocess(Project):
    def run_hook(self) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        return subprocess.run([PY, str(GATE_SCRIPT)],
                              input=json.dumps({"session_id": self.session,
                                                "cwd": str(self.root),
                                                "hook_event_name": "Stop"}),
                              capture_output=True, text=True, env=env, timeout=60)

    def test_stood_down_hook_exits_zero_silently(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.stop()
        proc = self.run_hook()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")
        self.assertEqual(self.runs(), ["c"])

    def test_internal_error_after_stand_down_exits_zero(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.stop()
        target = self.root / ".gatekit" / "runs" / (self.session + ".json")
        target.unlink()
        target.mkdir()
        proc = self.run_hook()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)

    def test_corrupt_job_status_still_exits_zero(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        status = jobs.job_dir(self.root, JOB_A) / "tasks" / "t1" / "status.json"
        status.write_text("{broken", encoding="utf-8")
        proc = self.run_hook()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


class TestDoctorShowsStandDown(Project):
    def test_project_state_names_the_stand_down(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.stop()
        result = doctor.axis_project_state(self.root)
        self.assertEqual(result["verdict"], verdict.OK)
        self.assertIn("stood down", result["detail"])
        self.assertIn(JOB_A, result["detail"])


# --------------------------------------------------------------------------
# Decision 2: tiers
# --------------------------------------------------------------------------


class TestTierField(Project):
    def test_default_tier_is_turn(self) -> None:
        self.write_contract(counting("c"))
        self.assertEqual(contract.load(self.root)["criteria"][0]["tier"], "turn")

    def test_verify_tier_is_kept(self) -> None:
        self.write_contract(counting("c", tier="verify"))
        self.assertEqual(contract.load(self.root)["criteria"][0]["tier"], "verify")

    def test_unknown_tier_is_a_derive_error(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self.write_contract(counting("c", tier="nightly"))
        self.assertIn("tier", str(caught.exception))

    def test_non_string_tier_is_a_derive_error(self) -> None:
        with self.assertRaises(ValueError):
            self.write_contract(counting("c", tier=1))


class TestTierValidation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-en", self.root)
        self.gate = self.root / "spec" / "05-gate.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def fails_with_tier(self, tier) -> list:
        text = self.gate.read_text(encoding="utf-8")
        new = text.replace('"argv":', '"tier": %s, "argv":' % json.dumps(tier), 1)
        self.assertNotEqual(new, text)
        self.gate.write_text(new, encoding="utf-8")
        return [f for f in spec.validate(self.root, "en")["findings"]
                if f["file"] == "05-gate.md" and f["verdict"] == "fail"]

    def test_turn_and_verify_pass(self) -> None:
        self.assertEqual(self.fails_with_tier("verify"), [])

    def test_turn_passes(self) -> None:
        self.assertEqual(self.fails_with_tier("turn"), [])

    def test_unknown_value_fails(self) -> None:
        fails = self.fails_with_tier("nightly")
        self.assertTrue(any("tier" in f["message"] for f in fails))

    def test_korean_message(self) -> None:
        text = self.gate.read_text(encoding="utf-8")
        self.gate.write_text(text.replace('"argv":', '"tier": "x", "argv":', 1), encoding="utf-8")
        fails = [f for f in spec.validate(self.root, "ko")["findings"]
                 if f["file"] == "05-gate.md" and f["verdict"] == "fail"]
        self.assertTrue(any("tier" in f["message"] and "기준" in f["message"] for f in fails))


class TestStopRunsTurnTier(Project):
    def test_build_stop_runs_only_turn_criteria(self) -> None:
        self.write_contract(counting("fast"), counting("suite", exit_code=1, tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.assertIsNone(self.stop())  # the failing verify-tier one never blocks
        self.assertEqual(self.runs(), ["fast"])
        deferred = self.led().data["stop"]["deferred"]
        self.assertEqual(deferred, [{"id": "suite", "tier": "verify", "reason": "tier"}])

    def test_verify_tier_is_named_deferred_and_never_ok(self) -> None:
        self.write_contract(counting("fast", exit_code=1), counting("suite", tier="verify"))
        self.prompt(BUILD_PROMPT)
        reason = self.stop()["reason"]
        self.assertIn("fast", reason)
        self.assertIn("deferred to /gatekit:verify", reason)
        self.assertIn("suite", reason)
        self.assertNotIn("suite: ok", reason)
        self.assertIn("1 of 1", reason)  # only what ran is counted

    def test_korean_deferred_line(self) -> None:
        self.write_contract(counting("fast", exit_code=1), counting("suite", tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.set_lang("ko")
        reason = self.stop()["reason"]
        self.assertIn("/gatekit:verify", reason)
        self.assertIn("suite", reason)
        self.assertIn("미룸", reason)

    def test_verify_pipeline_stop_runs_every_tier(self) -> None:
        self.write_contract(counting("fast"), counting("suite", exit_code=1, tier="verify"))
        self.prompt(VERIFY_PROMPT)
        result = self.stop()
        self.assertEqual(result["decision"], "block")
        self.assertIn("suite", result["reason"])
        self.assertEqual(sorted(self.runs()), ["fast", "suite"])

    def test_contract_with_no_turn_criteria_allows_unverified_and_stands_down(self) -> None:
        self.write_contract(counting("suite", tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.assertIsNone(self.stop())
        data = self.led().data["stop"]
        self.assertEqual(data["final_verdict"], verdict.UNVERIFIED)
        self.assertEqual(data["stood_down"]["verdict"], verdict.UNVERIFIED)
        self.assertEqual(self.runs(), [])


class TestRunAndBaselineRunEveryTier(Project):
    def test_contract_run_runs_every_tier(self) -> None:
        self.write_contract(counting("fast"), counting("suite", tier="verify"))
        self.assertEqual(contract.run(["run", "--root", str(self.root)]), 0)
        self.assertEqual(self.runs(), ["fast", "suite"])

    def test_execute_without_tiers_defers_nothing(self) -> None:
        self.write_contract(counting("fast"), counting("suite", tier="verify"))
        result = contract.execute(self.root)
        self.assertEqual(result["deferred"], [])
        self.assertEqual(result["scope"], ["fast", "suite"])

    def test_execute_turn_tier_defers_verify(self) -> None:
        self.write_contract(counting("fast"), counting("suite", tier="verify"))
        result = contract.execute(self.root, tiers=("turn",))
        self.assertEqual([c["id"] for c in result["criteria"]], ["fast"])
        self.assertEqual(result["scope"], ["fast"])
        self.assertEqual(result["verdict"], verdict.OK)
        self.assertNotIn("suite", " ".join(result["reasons"]))

    def test_no_criteria_in_tier(self) -> None:
        self.write_contract(counting("suite", tier="verify"))
        result = contract.execute(self.root, tiers=("turn",))
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)
        self.assertEqual(result["reasons"], [contract.NO_CRITERIA_IN_TIER_REASON])
        self.assertEqual(self.runs(), [])

    def test_baseline_runs_every_tier(self) -> None:
        self.write_contract(counting("fast"), counting("suite", tier="verify"))
        record = contract.baseline(self.root)
        self.assertEqual([r["id"] for r in record["criteria"]], ["fast", "suite"])


class TestReuseKeyedByScope(Project):
    def test_full_run_is_not_reused_as_a_turn_tier_result(self) -> None:
        self.write_contract(counting("fast"), counting("suite", tier="verify"))
        contract.run(["run", "--root", str(self.root)])
        self.prompt(BUILD_PROMPT)
        self.stop()
        self.assertEqual(self.runs(), ["fast", "suite", "fast"])
        self.assertEqual(self.events("stop_reused"), [])

    def test_turn_tier_result_is_not_reused_for_the_verify_stop(self) -> None:
        self.write_contract(counting("fast"), counting("suite", tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.stop()
        led = self.led()
        led.data["active_pipeline"] = "verify"
        led.save()
        self.stop()
        self.assertEqual(self.runs(), ["fast", "fast", "suite"])

    def test_same_scope_is_reused(self) -> None:
        self.write_contract(counting("fast"), counting("suite", tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.stop()
        self.stop()
        self.assertEqual(self.runs(), ["fast"])
        self.assertEqual(len(self.events("stop_reused")), 1)

    def test_full_run_reused_when_scopes_coincide(self) -> None:
        # No verify-tier criterion: a full run and a turn run cover the same ids.
        self.write_contract(counting("fast"))
        contract.run(["run", "--root", str(self.root)])
        self.prompt(BUILD_PROMPT)
        self.stop()
        self.assertEqual(self.runs(), ["fast"])

    def test_full_run_reused_by_the_verify_stop(self) -> None:
        self.write_contract(counting("fast"), counting("suite", tier="verify"))
        self.prompt(VERIFY_PROMPT)
        contract.run(["run", "--root", str(self.root)])
        self.stop()
        self.assertEqual(self.runs(), ["fast", "suite"])

    def test_a_record_without_scope_is_never_reused(self) -> None:
        self.write_contract(counting("fast"))
        result = contract.execute(self.root)
        contract.save_last(self.root, result)
        last = contract.load_last(self.root)
        last.pop("scope")
        config.write_json_atomic(self.root / ".gatekit" / "runs" / contract.LAST_RESULT_NAME, last)
        self.assertIsNone(contract.reusable_last(self.root))
        self.assertIsNone(contract.reusable_last(self.root, tiers=("turn",)))


# --------------------------------------------------------------------------
# Decision 3: Stop-gate budget
# --------------------------------------------------------------------------


class TestBudgetConfig(unittest.TestCase):
    def test_default(self) -> None:
        self.assertEqual(config.DEFAULTS["stop"]["budget_s"], 120)
        self.assertEqual(config.stop_budget_s(config.DEFAULTS), (120.0, ""))

    def test_max_is_the_stop_cap(self) -> None:
        self.assertEqual(config.STOP_BUDGET_MAX_S, stop_gate.STOP_BUDGET_CAP_S)
        value, problem = config.stop_budget_s({"stop": {"budget_s": 900}})
        self.assertEqual(value, 570.0)
        self.assertIn("570", problem)

    def test_valid_value(self) -> None:
        self.assertEqual(config.stop_budget_s({"stop": {"budget_s": 45.5}}), (45.5, ""))
        self.assertEqual(config.stop_budget_s({"stop": {"budget_s": 570}}), (570.0, ""))

    def test_invalid_values_fall_back_to_default(self) -> None:
        for bad in ("fast", True, 0, -3, None, [1]):
            value, problem = config.stop_budget_s({"stop": {"budget_s": bad}})
            self.assertEqual(value, 120.0, bad)
            self.assertTrue(problem, bad)

    def test_missing_stop_section(self) -> None:
        self.assertEqual(config.stop_budget_s({}), (120.0, ""))
        self.assertEqual(config.stop_budget_s({"stop": "x"})[0], 120.0)


class TestBudgetDoctor(Project):
    def test_out_of_range_budget_warns(self) -> None:
        self.write_config({"stop": {"budget_s": 9000}})
        result = doctor.axis_project_state(self.root)
        self.assertEqual(result["verdict"], verdict.WARN)
        self.assertIn("stop.budget_s", result["detail"])

    def test_valid_budget_is_ok(self) -> None:
        self.write_config({"stop": {"budget_s": 60}})
        self.assertEqual(doctor.axis_project_state(self.root)["verdict"], verdict.OK)


class TestStopBudget(Project):
    def test_criteria_past_the_budget_are_deferred_and_do_not_block(self) -> None:
        self.write_config({"stop": {"budget_s": 0.5}})
        self.write_contract(sleeping("slow", 1.0), counting("later", exit_code=1), budget=60)
        self.prompt(BUILD_PROMPT)
        self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["slow"])
        data = self.led().data["stop"]
        self.assertEqual(data["deferred"], [{"id": "later", "tier": "turn", "reason": "budget"}])
        # Not judged is not ok: recorded `unverified`, naming the deferred id,
        # without spending a block.
        self.assertEqual(data["final_verdict"], verdict.UNVERIFIED)
        self.assertIn("later", " ".join(data["last_reasons"]))
        self.assertEqual(data["block_count"], 0)
        self.assertIsNone(data["stood_down"])

    def test_a_fail_before_the_budget_still_blocks(self) -> None:
        self.write_config({"stop": {"budget_s": 0.5}})
        self.write_contract(counting("bad", exit_code=1), sleeping("slow", 1.0),
                            counting("later"), budget=60)
        self.prompt(BUILD_PROMPT)
        result = self.stop()
        self.assertEqual(result["decision"], "block")
        self.assertIn("bad", result["reason"])
        self.assertIn("deferred: Stop-gate budget", result["reason"])
        self.assertIn("later", result["reason"])  # named as deferred, not failing
        self.assertNotIn("later: ", result["reason"])

    def test_a_timed_out_criterion_that_ran_still_blocks(self) -> None:
        self.write_config({"stop": {"budget_s": 0.5}})
        self.write_contract(sleeping("hang", 5, timeout_s=1), counting("later"), budget=60)
        self.prompt(BUILD_PROMPT)
        result = self.stop()
        self.assertEqual(result["decision"], "block")
        self.assertIn("hang: unverified", result["reason"])

    def test_ran_no_tests_still_blocks(self) -> None:
        self.write_contract({"id": "empty", "timeout_s": 20,
                             "argv": [PY, "-c", "print('collected 0 items'); "
                                      "print('no tests ran in 0.01s')"]})
        self.prompt(BUILD_PROMPT)
        result = self.stop()
        self.assertEqual(result["decision"], "block")
        self.assertIn("empty: unverified", result["reason"])

    def test_contract_budget_exhaustion_is_still_unverified(self) -> None:
        # The contract's own budget (1 s) runs out before the Stop budget (120 s).
        self.write_contract(sleeping("slow", 1.5, timeout_s=5), counting("later"), budget=1)
        self.prompt(BUILD_PROMPT)
        result = self.stop()
        self.assertEqual(result["decision"], "block")
        self.assertIn("later: unverified", result["reason"])

    def test_both_budgets_spent_is_the_contracts_unverified(self) -> None:
        # Stop budget (0.5 s) and contract budget (1 s) are both spent when
        # `later` comes up: the contract's limit wins, `unverified`, not deferred.
        self.write_config({"stop": {"budget_s": 0.5}})
        self.write_contract(sleeping("slow", 1.5, timeout_s=5), counting("later"), budget=1)
        self.prompt(BUILD_PROMPT)
        result = self.stop()
        self.assertEqual(result["decision"], "block")
        self.assertIn("later: unverified", result["reason"])
        self.assertEqual(self.led().data["stop"]["deferred"], [])

    def test_verify_pipeline_stop_ignores_the_stop_budget(self) -> None:
        self.write_config({"stop": {"budget_s": 0.5}})
        self.write_contract(sleeping("slow", 1.0), counting("later"), budget=60)
        self.prompt(VERIFY_PROMPT)
        self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["slow", "later"])
        self.assertEqual(self.led().data["stop"]["deferred"], [])

    def test_contract_run_ignores_the_stop_budget(self) -> None:
        self.write_config({"stop": {"budget_s": 0.5}})
        self.write_contract(sleeping("slow", 1.0), counting("later"), budget=60)
        self.assertEqual(contract.run(["run", "--root", str(self.root)]), 0)
        self.assertEqual(self.runs(), ["slow", "later"])

    def test_execute_start_budget_defers(self) -> None:
        self.write_contract(sleeping("slow", 0.6), counting("later"), budget=60)
        result = contract.execute(self.root, start_budget_s=0.3)
        self.assertEqual([c["id"] for c in result["criteria"]], ["slow"])
        self.assertEqual(result["deferred"], [{"id": "later", "tier": "turn", "reason": "budget"}])
        # What ran passed, but `later` was never judged: not ok.
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)
        self.assertEqual(result["scope"], ["slow"])  # the ids actually judged
        self.assertIn(contract.BUDGET_DEFERRED_REASON + ": later", result["reasons"])

    def test_a_budget_fail_keeps_its_fail(self) -> None:
        self.write_contract(counting("bad", exit_code=1), sleeping("slow", 0.6),
                            counting("later"), budget=60)
        result = contract.execute(self.root, start_budget_s=0.3)
        self.assertEqual(result["verdict"], verdict.FAIL)


class TestBudgetDeferralIsNotOk(Project):
    """Review of ADR-0024: a Stop cut by its budget has not judged the
    contract, so it is never `ok` and never stands the gate down."""

    def handoff(self, *criteria: dict) -> None:
        self.write_config({"stop": {"budget_s": 0.5}})
        self.write_contract(*criteria, budget=60)
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed", "t2": "passed"})

    def test_settled_handoff_cut_by_the_budget_does_not_stand_down(self) -> None:
        self.handoff(sleeping("slow", 1.0), counting("broken", exit_code=1))
        self.assertIsNone(self.stop())  # deferral does not block
        data = self.led().data["stop"]
        self.assertEqual(data["final_verdict"], verdict.UNVERIFIED)
        self.assertIsNone(data["stood_down"])
        self.assertEqual(data["block_count"], 0)
        self.assertEqual(self.events("stop_stood_down"), [])
        # Same tree: the deferred criterion runs first next time, and blocks.
        result = self.stop()
        self.assertEqual(result["decision"], "block")
        self.assertIn("broken: fail", result["reason"])
        self.assertEqual(self.runs()[:2], ["slow", "broken"])
        self.assertIsNone(self.led().data["stop"]["stood_down"])

    def test_deferred_first_converges_then_stands_down(self) -> None:
        self.handoff(sleeping("a", 0.6), sleeping("b", 0.6), sleeping("c", 0.6))
        self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["a"])
        self.assertIsNone(self.led().data["stop"]["stood_down"])
        self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["a", "b"])  # b before anything else
        self.assertIsNone(self.led().data["stop"]["stood_down"])
        self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["a", "b", "c"])
        data = self.led().data["stop"]
        # Every turn-tier criterion was judged on this tree: a real `ok`.
        self.assertEqual(data["final_verdict"], verdict.OK)
        self.assertEqual(data["stood_down"]["verdict"], verdict.OK)
        self.assertEqual(data["block_count"], 0)
        self.assertIsNone(self.stop())
        self.assertEqual(self.runs(), ["a", "b", "c"])

    def test_an_edit_drops_what_an_earlier_tree_judged(self) -> None:
        self.handoff(sleeping("a", 0.6), sleeping("b", 0.6))
        self.stop()
        self.touch_source()
        self.assertIsNone(self.stop())  # b runs first, a is deferred now
        self.assertEqual(self.runs(), ["a", "b"])
        data = self.led().data["stop"]
        self.assertEqual(data["final_verdict"], verdict.UNVERIFIED)
        self.assertIsNone(data["stood_down"])
        self.assertEqual(data["deferred"], [{"id": "a", "tier": "turn", "reason": "budget"}])

    def test_stop_hook_active_cut_by_the_budget_does_not_stand_down(self) -> None:
        self.handoff(sleeping("slow", 1.0), counting("later"))
        self.assertIsNone(self.stop(stop_hook_active=True))
        self.assertIsNone(self.led().data["stop"]["stood_down"])

    def test_out_of_blocks_cut_by_the_budget_still_does_not_stand_down(self) -> None:
        self.handoff(sleeping("slow", 1.0), counting("later"))
        led = self.led()
        led.data["stop"]["block_count"] = stop_gate.MAX_BLOCKS
        led.save()
        self.assertIsNone(self.stop())
        data = self.led().data["stop"]
        self.assertIsNone(data["stood_down"])
        self.assertEqual(data["final_verdict"], verdict.UNVERIFIED)

    def test_budget_cut_record_is_not_reused_by_the_verify_stop(self) -> None:
        self.handoff(sleeping("slow", 1.0), counting("broken", exit_code=1))
        self.stop()
        self.prompt(VERIFY_PROMPT)
        result = self.stop()  # no file changed
        self.assertEqual(result["decision"], "block")
        self.assertIn("broken: fail", result["reason"])
        # Both judged again; the one the budget deferred goes first.
        self.assertEqual(self.runs(), ["slow", "broken", "slow"])
        self.assertEqual(self.events("stop_reused"), [])

    def test_budget_cut_record_is_never_reusable(self) -> None:
        self.write_contract(sleeping("slow", 0.6), counting("later"), budget=60)
        contract.save_last(self.root, contract.execute(self.root, start_budget_s=0.3))
        self.assertEqual(contract.load_last(self.root)["scope"], ["slow"])
        self.assertIsNone(contract.reusable_last(self.root))
        self.assertIsNone(contract.reusable_last(self.root, tiers=("turn",)))

    def test_context_line_names_the_budget_deferred(self) -> None:
        self.handoff(sleeping("slow", 1.0), counting("later"))
        self.stop()
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("later", text)
        self.assertIn("budget", text)
        self.assertNotIn("not gated", text)

    def test_korean_context_line_names_the_budget_deferred(self) -> None:
        self.handoff(sleeping("slow", 1.0), counting("later"))
        self.set_lang("ko")
        self.stop()
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("later", text)
        self.assertIn("예산", text)


class TestStoodDownLineNamesTheTier(Project):
    def test_turn_tier_and_verify_count(self) -> None:
        self.write_contract(counting("fast"), counting("s1", tier="verify"),
                            counting("s2", tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.stop()
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("turn-tier ok", text)
        self.assertIn("2 deferred to /gatekit:verify", text)

    def test_no_verify_tier_no_count(self) -> None:
        self.write_contract(counting("fast"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed"})
        self.stop()
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("turn-tier ok", text)
        self.assertNotIn("deferred to", text)

    def test_korean(self) -> None:
        self.write_contract(counting("fast"), counting("s1", tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.set_lang("ko")
        self.make_job({"t1": "passed"})
        self.stop()
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("turn", text)
        self.assertIn("1개", text)


class TestUnpassedTasksAreNotAHandoffOk(Project):
    """Review of ADR-0024: a settled job with a failed or blocked task is not
    done, whatever the contract says (ADR-0024 decision 1)."""

    def test_failed_task_blocks_even_with_an_ok_contract(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed", "t2": "failed", "t3": "blocked"})
        result = self.stop()
        self.assertEqual(result["decision"], "block")
        self.assertIn("t2 (failed)", result["reason"])
        self.assertIn("t3 (blocked)", result["reason"])
        self.assertNotIn("t1", result["reason"])
        # Host execution reruns a task with `jobs complete`; a worker build with
        # `jobs redelegate`. Naming only the latter pushes a host session to
        # spawn a worker.
        self.assertIn("jobs complete <task>", result["reason"])
        self.assertIn("jobs redelegate <task>", result["reason"])
        data = self.led().data["stop"]
        self.assertEqual(data["block_count"], 1)
        self.assertIsNone(data["stood_down"])

    def test_up_to_max_blocks_then_fail_recorded_and_stands_down(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed", "t2": "timeout"})
        for _ in range(stop_gate.MAX_BLOCKS):
            self.assertEqual(self.stop()["decision"], "block")
        self.assertIsNone(self.stop())
        data = self.led().data["stop"]
        self.assertEqual(data["final_verdict"], verdict.FAIL)
        self.assertEqual(data["stood_down"]["verdict"], verdict.FAIL)
        self.assertIn("t2 (timeout)", " ".join(data["last_reasons"]))

    def test_only_blocked_tasks_record_unverified(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed", "t2": "blocked"})
        led = self.led()
        led.data["stop"]["block_count"] = stop_gate.MAX_BLOCKS
        led.save()
        self.assertIsNone(self.stop())
        data = self.led().data["stop"]
        self.assertEqual(data["final_verdict"], verdict.UNVERIFIED)
        self.assertEqual(data["stood_down"]["verdict"], verdict.UNVERIFIED)

    def test_failing_contract_and_failed_task_name_both(self) -> None:
        self.write_contract(counting("c", exit_code=1))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "failed"})
        reason = self.stop()["reason"]
        self.assertIn("c: fail", reason)
        self.assertIn("t1 (failed)", reason)

    def test_nothing_in_turn_tier_with_a_failed_task_blocks(self) -> None:
        self.write_contract(counting("suite", tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "failed"})
        self.assertEqual(self.stop()["decision"], "block")
        self.assertIsNone(self.led().data["stop"]["stood_down"])

    def test_stop_hook_active_with_a_failed_task_does_not_stand_down(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "failed"})
        self.assertIsNone(self.stop(stop_hook_active=True))
        data = self.led().data["stop"]
        self.assertIsNone(data["stood_down"])
        self.assertEqual(data["final_verdict"], verdict.FAIL)

    def test_stopped_job_is_recorded_without_a_block(self) -> None:
        # `jobs stop` is an explicit end: no block, but not ok either.
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed", "t2": "stopped"})
        self.assertIsNone(self.stop())
        data = self.led().data["stop"]
        self.assertEqual(data["block_count"], 0)
        self.assertEqual(data["final_verdict"], verdict.FAIL)
        self.assertEqual(data["stood_down"]["verdict"], verdict.FAIL)
        self.assertIn("t2 (stopped)", " ".join(data["last_reasons"]))

    def test_korean_message(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.set_lang("ko")
        self.make_job({"t1": "failed"})
        reason = self.stop()["reason"]
        self.assertIn("t1 (failed)", reason)
        self.assertIn("태스크", reason)

    def test_unsettled_job_failed_task_does_not_change_judging(self) -> None:
        # Only the handoff check of a settled job looks at task states.
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "failed", "t2": "queued"})
        self.assertIsNone(self.stop())


class TestTurnTierWarnings(unittest.TestCase):
    """Review of ADR-0024: tiering every criterion `verify` silently turns the
    build's Stop gate off, so `spec validate` warns (never fails)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "case"
        shutil.copytree(FIXTURES / "valid-en", self.root)
        self.gate = self.root / "spec" / "05-gate.md"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def gate_findings(self, lang: str = "en") -> list:
        return [f for f in spec.validate(self.root, lang)["findings"]
                if f["file"] == "05-gate.md"]

    def tier_all(self, tier: str) -> None:
        text = self.gate.read_text(encoding="utf-8")
        self.gate.write_text(text.replace('"argv":', '"tier": "%s", "argv":' % tier),
                             encoding="utf-8")

    def test_no_turn_criterion_warns(self) -> None:
        self.tier_all("verify")
        found = self.gate_findings()
        self.assertTrue(any(f["verdict"] == "warn" and "turn" in f["message"] for f in found))
        self.assertFalse(any(f["verdict"] == "fail" for f in found))

    def test_korean_no_turn_warning(self) -> None:
        self.tier_all("verify")
        found = self.gate_findings("ko")
        self.assertTrue(any(f["verdict"] == "warn" and "turn" in f["message"]
                            and "기준" in f["message"] for f in found))

    def test_a_turn_criterion_does_not_warn(self) -> None:
        text = self.gate.read_text(encoding="utf-8")
        self.gate.write_text(text.replace('"argv":', '"tier": "verify", "argv":', 1),
                             encoding="utf-8")
        self.assertFalse(any(f["verdict"] == "warn" and "turn" in f["message"]
                             for f in self.gate_findings()))

    def test_verify_tier_screenshot_criterion_warns(self) -> None:
        text = self.gate.read_text(encoding="utf-8")
        shot = ("```gatekit-criterion\n" + json.dumps(
            {"id": "screenshots", "tier": "verify", "argv": ["npx", "playwright", "test"],
             "artifacts": ["spec/design/build-t1.png"]}) + "\n```\n\n")
        self.gate.write_text(text.replace("```gatekit-criterion", shot + "```gatekit-criterion", 1),
                             encoding="utf-8")
        found = self.gate_findings()
        self.assertTrue(any(f["verdict"] == "warn" and "screenshots" in f["message"]
                            for f in found))
        self.assertFalse(any(f["verdict"] == "fail" for f in found))


class TestNoTurnTierIsSaid(Project):
    def test_context_line_says_nothing_is_judged(self) -> None:
        self.write_contract(counting("suite", tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.stop()
        text = prompt_gate.build_context(self.root, self.led())
        self.assertIn("no turn-tier criteria", text)

    def test_block_message_says_nothing_is_judged(self) -> None:
        self.write_contract(counting("suite", tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "failed"})
        self.assertIn("no turn-tier criteria", self.stop()["reason"])

    def test_no_line_with_a_turn_criterion(self) -> None:
        self.write_contract(counting("fast"), counting("suite", tier="verify"))
        self.prompt(BUILD_PROMPT)
        self.assertNotIn("no turn-tier", prompt_gate.build_context(self.root, self.led()))


class TestUnfinishedJobLine(Project):
    """Review of ADR-0024: a host job left with queued tasks keeps the gate
    judging every turn; the context line says how to end it."""

    def test_english(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed", "t2": "queued", "t3": "queued"})
        text = self.prompt("next?")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("build job unfinished: 2 tasks queued", text)
        self.assertIn("`jobs stop` ends judging", text)
        self.assertLessEqual(len(text), hookio.MAX_CONTEXT_CHARS)

    def test_korean(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.set_lang("ko")
        self.make_job({"t1": "queued"})
        text = self.prompt("다음은 무엇인가요?")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("`jobs stop`", text)
        self.assertIn("대기 1개", text)
        self.assertLessEqual(len(text), hookio.MAX_CONTEXT_CHARS)

    def test_no_queued_task_no_line(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.make_job({"t1": "passed", "t2": "running"})
        self.assertNotIn("jobs stop", prompt_gate.build_context(self.root, self.led()))


class TestNonDictStopRecord(Project):
    """`"stop": null` in a hand-edited ledger made the gate fail open, silently,
    at every turn end. It is reset to a blank record instead."""

    def corrupt(self, value) -> None:
        path = self.root / ".gatekit" / "runs" / (self.session + ".json")
        data = json.loads(path.read_text(encoding="utf-8"))
        data["stop"] = value
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_null_stop_still_judges(self) -> None:
        self.write_contract(counting("c", exit_code=1))
        self.prompt(BUILD_PROMPT)
        for value in (None, "garbage", [1]):
            self.corrupt(value)
            result = self.stop()
            self.assertEqual(result["decision"], "block", value)
            data = self.led().data["stop"]
            self.assertEqual(data["block_count"], 1)
            self.assertIsNone(data["stood_down"])

    def test_null_stop_records_a_verdict_on_allow(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.corrupt(None)
        self.assertIsNone(self.stop())
        self.assertEqual(self.led().data["stop"]["final_verdict"], verdict.OK)

    def test_null_stop_prompt_hook_still_answers(self) -> None:
        self.write_contract(counting("c"))
        self.prompt(BUILD_PROMPT)
        self.corrupt(None)
        self.assertIn("pipeline=build",
                      self.prompt("hi")["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

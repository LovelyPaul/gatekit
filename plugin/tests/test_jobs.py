"""Tests for gatekit.jobs — job dirs, worker spawn, gate verdicts, redelegate.

Every test uses a fake worker (a python script in the fixtures dir, registered
as a custom backend) so no real agent CLI and no network is needed.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

# Make the `gatekit` package importable however this suite is discovered:
# `discover -s plugin/tests` loads tests as top-level modules and puts only
# `plugin/tests` on sys.path, so `plugin/` has to be added explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import jobs, verdict

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "jobs"
FAKE_WORKER = FIXTURES / "fake_worker.py"
GATE_EXISTS = FIXTURES / "gate_file_exists.py"


def task_fence(task: dict) -> str:
    return "```gatekit-task\n%s\n```\n" % json.dumps(task)


class JobTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(os.path.realpath(self._tmp.name))
        (self.root / ".gatekit").mkdir()
        (self.root / "spec").mkdir()
        (self.root / "src").mkdir()
        self._env_keys = []

    def tearDown(self) -> None:
        for key in self._env_keys:
            os.environ.pop(key, None)
        self._tmp.cleanup()

    # -- helpers ---------------------------------------------------------

    def set_env(self, **kw) -> None:
        for key, value in kw.items():
            os.environ[key] = str(value)
            self._env_keys.append(key)

    def write_config(self, **backend_overrides) -> None:
        backend = {"argv": [sys.executable, str(FAKE_WORKER)], "enabled": True}
        backend.update(backend_overrides)
        cfg = {
            "worker": {"default": "fake", "backends": {"fake": backend}},
            "build": {"max_retries": 2, "parallel": 2, "task_timeout_s": 60},
        }
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def write_tasks(self, *tasks) -> None:
        body = "# Tasks\n\n" + "\n".join(task_fence(t) for t in tasks)
        (self.root / "spec" / "04-tasks.md").write_text(body, encoding="utf-8")

    def simple_task(self, task_id="write-note", target="src/note.txt", **extra) -> dict:
        task = {
            "id": task_id,
            "title": "Write a note",
            "write_scope": [target],
            "instruction": "Create %s." % target,
            "gates": [{"name": "file-exists",
                       "argv": [sys.executable, str(GATE_EXISTS), target]}],
            "depends_on": [],
            "round": 1,
        }
        task.update(extra)
        return task

    def task_dir(self, job_id, task_id) -> pathlib.Path:
        return self.root / ".gatekit" / "jobs" / job_id / "tasks" / task_id


# ------------------------------------------------------------------- basics


class TestJobId(unittest.TestCase):
    def test_job_id_is_timestamp_plus_four_hex(self) -> None:
        job_id = jobs.new_job_id()
        stamp, suffix = job_id.rsplit("-", 1)
        self.assertEqual(len(suffix), 4)
        int(suffix, 16)  # must parse as hex
        self.assertTrue(stamp.endswith("Z"))
        self.assertNotEqual(jobs.new_job_id(), job_id)


class TestAtomicWrite(JobTestCase):
    def test_write_json_leaves_no_temp_files(self) -> None:
        target = self.root / "sub" / "x.json"
        jobs.write_json(target, {"a": 1})
        self.assertEqual(json.loads(target.read_text()), {"a": 1})
        leftovers = [p.name for p in target.parent.iterdir() if p.name.startswith(".tmp-")]
        self.assertEqual(leftovers, [])

    def test_write_json_replaces_existing_content(self) -> None:
        target = self.root / "x.json"
        jobs.write_json(target, {"a": 1})
        jobs.write_json(target, {"b": 2})
        self.assertEqual(json.loads(target.read_text()), {"b": 2})


class TestPrompt(JobTestCase):
    def test_prompt_carries_instruction_scope_gates_and_no_success_claim(self) -> None:
        task = self.simple_task()
        prompt = jobs.build_prompt(task, "job-1")
        self.assertIn("Create src/note.txt.", prompt)
        self.assertIn("src/note.txt", prompt)
        self.assertIn("file-exists", prompt)
        self.assertIn("Do not claim success", prompt)
        self.assertIn("gates decide", prompt)


class TestOrdering(unittest.TestCase):
    def test_depends_on_lands_in_a_later_wave(self) -> None:
        tasks = [
            {"id": "b", "depends_on": ["a"], "round": 1},
            {"id": "a", "depends_on": [], "round": 1},
        ]
        waves = jobs.order_tasks(tasks)
        self.assertEqual([t["id"] for t in waves[0]], ["a"])
        self.assertEqual([t["id"] for t in waves[1]], ["b"])

    def test_rounds_are_honoured_before_dependencies(self) -> None:
        tasks = [
            {"id": "late", "depends_on": [], "round": 2},
            {"id": "early", "depends_on": [], "round": 1},
        ]
        waves = jobs.order_tasks(tasks)
        self.assertEqual([t["id"] for t in waves[0]], ["early"])
        self.assertEqual([t["id"] for t in waves[1]], ["late"])

    def test_dependency_cycle_still_schedules_every_task(self) -> None:
        tasks = [
            {"id": "a", "depends_on": ["b"], "round": 1},
            {"id": "b", "depends_on": ["a"], "round": 1},
        ]
        scheduled = [t["id"] for wave in jobs.order_tasks(tasks) for t in wave]
        self.assertEqual(sorted(scheduled), ["a", "b"])


# ------------------------------------------------------------------- running


class TestStart(JobTestCase):
    def test_dry_run_creates_dirs_but_spawns_nothing(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.set_env(FAKE_WORKER_OUT=str(self.root / "src" / "note.txt"))
        job = jobs.start(self.root, dry_run=True)
        tdir = self.task_dir(job["job_id"], "write-note")
        self.assertTrue((tdir / "task.json").is_file())
        self.assertTrue((tdir / "prompt.md").is_file())
        self.assertFalse((tdir / "output.txt").exists())
        self.assertFalse((self.root / "src" / "note.txt").exists())
        status = json.loads((tdir / "status.json").read_text())
        self.assertEqual(status["state"], "queued")

    def test_happy_path_worker_and_gate_pass(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.set_env(FAKE_WORKER_OUT="src/note.txt", FAKE_WORKER_BODY="hello")
        job = jobs.start(self.root)
        tdir = self.task_dir(job["job_id"], "write-note")
        status = json.loads((tdir / "status.json").read_text())
        self.assertEqual(status["state"], "passed")
        self.assertEqual(status["gates_passed"], 1)
        self.assertEqual((self.root / "src" / "note.txt").read_text(), "hello")
        gates = json.loads((tdir / "gates.json").read_text())
        self.assertEqual(gates["verdict"], verdict.OK)

    def test_worker_receives_task_and_job_env(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.set_env(FAKE_WORKER_OUT="src/note.txt")
        job = jobs.start(self.root)
        stderr = (self.task_dir(job["job_id"], "write-note") / "stderr.txt").read_text()
        self.assertIn("task=write-note", stderr)
        self.assertIn("job=%s" % job["job_id"], stderr)

    def test_prompt_reaches_the_worker_on_stdin(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.set_env(FAKE_WORKER_OUT="src/note.txt")
        job = jobs.start(self.root)
        stderr = (self.task_dir(job["job_id"], "write-note") / "stderr.txt").read_text()
        self.assertNotIn("prompt=0 chars", stderr)

    def test_exit_zero_but_failing_gate_is_failed_never_passed(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        # Worker exits 0 but writes nothing, so the file-exists gate fails.
        self.set_env(FAKE_WORKER_EXIT=0)
        job = jobs.start(self.root)
        status = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(status["exit"], 0)
        self.assertEqual(status["state"], "failed")
        self.assertNotEqual(status["state"], "passed")
        self.assertIn("exited 0 but gates", status["detail"])

    def test_nonzero_worker_exit_is_failed(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.set_env(FAKE_WORKER_OUT="src/note.txt", FAKE_WORKER_EXIT=2)
        job = jobs.start(self.root)
        status = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(status["state"], "failed")

    def test_timeout_kills_worker_and_records_timeout_state(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.set_env(FAKE_WORKER_OUT="src/note.txt", FAKE_WORKER_SLEEP=30)
        cfg = json.loads((self.root / ".gatekit" / "config.json").read_text())
        cfg["build"]["task_timeout_s"] = 1
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        job = jobs.start(self.root)
        status = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(status["state"], "timeout")
        self.assertIn("task_timeout_s", status["detail"])

    def test_unknown_task_id_is_rejected(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        with self.assertRaises(ValueError):
            jobs.start(self.root, task_ids=["ghost"])

    def test_no_tasks_is_rejected(self) -> None:
        self.write_config()
        (self.root / "spec" / "04-tasks.md").write_text("# empty\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            jobs.start(self.root)

    def test_disabled_backend_refuses_to_start(self) -> None:
        self.write_config(enabled=False)
        self.write_tasks(self.simple_task())
        with self.assertRaises(ValueError):
            jobs.start(self.root)

    def test_job_json_records_backend_and_unsafe_flag(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.set_env(FAKE_WORKER_OUT="src/note.txt")
        job = jobs.start(self.root, dry_run=True)
        saved = json.loads(
            (self.root / ".gatekit" / "jobs" / job["job_id"] / "job.json").read_text())
        self.assertEqual(saved["backend"]["name"], "fake")
        self.assertFalse(saved["backend"]["unsafe"])


# ---------------------------------------------------------------- reporting


class TestStatusAndResults(JobTestCase):
    def test_status_reports_fail_when_a_task_failed(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        payload = jobs.status(self.root, job["job_id"])
        self.assertEqual(payload["verdict"], verdict.FAIL)
        self.assertTrue(payload["done"])

    def test_status_without_any_job_is_unverified(self) -> None:
        payload = jobs.status(self.root)
        self.assertEqual(payload["verdict"], verdict.UNVERIFIED)

    def test_wait_returns_immediately_for_a_finished_job(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.set_env(FAKE_WORKER_OUT="src/note.txt")
        job = jobs.start(self.root)
        payload = jobs.wait(self.root, job["job_id"], timeout=5)
        self.assertTrue(payload["done"])
        self.assertEqual(payload["verdict"], verdict.OK)

    def test_results_compact_prints_one_line_per_task(self) -> None:
        import contextlib
        import io

        self.write_config()
        self.write_tasks(self.simple_task())
        self.set_env(FAKE_WORKER_OUT="src/note.txt")
        jobs.start(self.root)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            jobs.run(["results", "--compact", "--root", str(self.root)])
        lines = [line for line in buf.getvalue().splitlines() if line.strip()]
        self.assertEqual(lines, ["write-note passed 1/1"])

    def test_clean_all_removes_every_job_dir(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        self.set_env(FAKE_WORKER_OUT="src/note.txt")
        jobs.start(self.root, dry_run=True)
        jobs.start(self.root, dry_run=True)
        removed = jobs.clean(self.root, all_jobs=True)
        self.assertEqual(len(removed), 2)
        self.assertEqual(list((self.root / ".gatekit" / "jobs").iterdir()), [])

    def test_clean_default_keeps_the_newest_job(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        jobs.start(self.root, dry_run=True)
        jobs.start(self.root, dry_run=True)
        jobs.clean(self.root)
        self.assertEqual(len(list((self.root / ".gatekit" / "jobs").iterdir())), 1)


# --------------------------------------------------------------- redelegate


class TestRedelegate(JobTestCase):
    def test_second_attempt_succeeds_and_archives_the_first(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        counter = str(self.root / "attempts.txt")
        # Attempt 1 writes nothing (gate fails); attempt 2 writes the file.
        self.set_env(FAKE_WORKER_OUT="src/note.txt", FAKE_WORKER_ATTEMPT_FILE=counter,
                     FAKE_WORKER_PASS_AT=2)
        job = jobs.start(self.root)
        tdir = self.task_dir(job["job_id"], "write-note")
        first = json.loads((tdir / "status.json").read_text())
        self.assertEqual(first["state"], "failed")

        status = jobs.redelegate(self.root, "write-note", job["job_id"])
        self.assertEqual(status["state"], "passed")
        self.assertEqual(status["attempt"], 2)
        self.assertTrue((tdir / "attempt-1" / "gates.json").is_file())
        self.assertTrue((tdir / "attempt-1" / "output.txt").is_file())

    def test_new_prompt_carries_the_failed_gate_output(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        counter = str(self.root / "attempts.txt")
        self.set_env(FAKE_WORKER_OUT="src/note.txt", FAKE_WORKER_ATTEMPT_FILE=counter,
                     FAKE_WORKER_PASS_AT=2)
        job = jobs.start(self.root)
        tdir = self.task_dir(job["job_id"], "write-note")
        jobs.redelegate(self.root, "write-note", job["job_id"])
        prompt = (tdir / "prompt.md").read_text()
        self.assertIn("Previous attempt failed", prompt)
        self.assertIn("file-exists", prompt)
        self.assertIn("missing: src/note.txt", prompt)

    def test_beyond_max_retries_raises_and_cli_exits_3(self) -> None:
        import contextlib
        import io

        self.write_config()
        self.write_tasks(self.simple_task())
        cfg = json.loads((self.root / ".gatekit" / "config.json").read_text())
        cfg["build"]["max_retries"] = 1
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        job = jobs.start(self.root)  # attempt 1 fails (no file written)
        jobs.redelegate(self.root, "write-note", job["job_id"])  # attempt 2, also fails
        with self.assertRaises(jobs.RetryBudgetExceeded):
            jobs.redelegate(self.root, "write-note", job["job_id"])
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = jobs.run(["redelegate", "write-note", "--root", str(self.root)])
        self.assertEqual(code, 3)

    def test_redelegating_an_unknown_task_raises(self) -> None:
        self.write_config()
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root, dry_run=True)
        with self.assertRaises(ValueError):
            jobs.redelegate(self.root, "ghost", job["job_id"])


# --------------------------------------------------------------------- gates


class TestRunGates(JobTestCase):
    def test_task_without_gates_is_unverified_and_never_passes(self) -> None:
        self.write_config()
        task = self.simple_task(gates=[])
        self.write_tasks(task)
        self.set_env(FAKE_WORKER_OUT="src/note.txt")
        job = jobs.start(self.root)
        status = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text())
        self.assertEqual(status["state"], "failed")
        self.assertEqual(status["gates_verdict"], verdict.UNVERIFIED)

    def test_unrunnable_gate_argv_is_fail_not_crash(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [
            {"name": "ghost", "argv": ["definitely-not-a-real-binary-xyz"]}]})
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertEqual(result["gates"][0]["verdict"], verdict.FAIL)

    def test_gate_stdout_and_stderr_tails_are_captured(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [
            {"name": "exists", "argv": [sys.executable, str(GATE_EXISTS), "nope.txt"]}]})
        self.assertEqual(result["verdict"], verdict.FAIL)
        self.assertIn("missing: nope.txt", result["gates"][0]["stderr_tail"])

    def test_gates_run_sequentially_and_all_are_reported(self) -> None:
        (self.root / "a.txt").write_text("a", encoding="utf-8")
        result = jobs.run_gates(self.root, {"gates": [
            {"name": "one", "argv": [sys.executable, str(GATE_EXISTS), "a.txt"]},
            {"name": "two", "argv": [sys.executable, str(GATE_EXISTS), "b.txt"]},
        ]})
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["passed"], 1)
        self.assertEqual(result["verdict"], verdict.FAIL)


class TestLoadTasks(JobTestCase):
    def test_tasks_come_from_fences_in_04_tasks(self) -> None:
        self.write_tasks(self.simple_task("a"), self.simple_task("b"))
        loaded = jobs.load_tasks(self.root)
        self.assertEqual([t["id"] for t in loaded], ["a", "b"])

    def test_missing_tasks_file_yields_empty_list(self) -> None:
        self.assertEqual(jobs.load_tasks(self.root), [])


if __name__ == "__main__":
    unittest.main()


class TestEvaluate(JobTestCase):
    """`jobs evaluate` runs one read-only worker as the independent evaluator."""

    def write_eval_config(self, read_only=True, exit_code=0) -> None:
        backend = {
            "argv": [sys.executable, "/nonexistent/should-not-run"],
            "enabled": True,
        }
        if read_only:
            backend["read_only_argv"] = [sys.executable, str(FAKE_WORKER)]
        cfg = {
            "worker": {"default": "fake", "backends": {"fake": backend}},
            "build": {"task_timeout_s": 60},
            "verify": {"evaluator": "fake"},
        }
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        self.set_env(FAKE_WORKER_EXIT=exit_code)

    def test_uses_read_only_argv_and_records_state(self) -> None:
        self.write_eval_config()
        result = jobs.evaluate(self.root)
        self.assertEqual(result["state"], "passed")
        self.assertEqual(result["exit"], 0)
        edir = self.root / ".gatekit" / "jobs" / result["job_id"] / "evaluate"
        self.assertTrue((edir / "output.txt").is_file())
        status = json.loads((edir / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "passed")
        job = json.loads((self.root / ".gatekit" / "jobs" / result["job_id"] / "job.json").read_text(encoding="utf-8"))
        self.assertTrue(job["backend"]["read_only"])
        self.assertEqual(job["kind"], "evaluate")

    def test_worker_sees_evaluate_task_id_and_read_only_scope(self) -> None:
        self.write_eval_config()
        result = jobs.evaluate(self.root)
        edir = self.root / ".gatekit" / "jobs" / result["job_id"] / "evaluate"
        stderr = (edir / "stderr.txt").read_text(encoding="utf-8")
        self.assertIn("task=evaluate", stderr)
        task = json.loads((edir / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(task["write_scope"], "read-only")

    def test_prompt_file_is_used_verbatim(self) -> None:
        self.write_eval_config()
        brief = self.root / "brief.md"
        brief.write_text("EVALUATE THIS\n", encoding="utf-8")
        result = jobs.evaluate(self.root, prompt_path=brief)
        edir = self.root / ".gatekit" / "jobs" / result["job_id"] / "evaluate"
        self.assertEqual((edir / "prompt.md").read_text(encoding="utf-8"), "EVALUATE THIS\n")

    def test_default_brief_mentions_contract_run_and_read_only(self) -> None:
        self.write_eval_config()
        result = jobs.evaluate(self.root)
        edir = self.root / ".gatekit" / "jobs" / result["job_id"] / "evaluate"
        text = (edir / "prompt.md").read_text(encoding="utf-8")
        self.assertIn("contract run", text)
        self.assertIn("unverified", text)
        self.assertIn("Do not fix", text)

    def test_nonzero_exit_is_failed(self) -> None:
        self.write_eval_config(exit_code=3)
        self.assertEqual(jobs.evaluate(self.root)["state"], "failed")

    def test_output_tail_returned(self) -> None:
        self.write_eval_config()
        result = jobs.evaluate(self.root)
        self.assertIn("fake-worker report", result["output_tail"])

    def test_missing_read_only_argv_refuses(self) -> None:
        self.write_eval_config(read_only=False)
        with self.assertRaises(ValueError):
            jobs.evaluate(self.root)

    def test_agent_evaluator_refuses_cli_path(self) -> None:
        self.write_eval_config()
        cfg = json.loads((self.root / ".gatekit" / "config.json").read_text(encoding="utf-8"))
        cfg["verify"]["evaluator"] = "agent"
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        with self.assertRaises(ValueError):
            jobs.evaluate(self.root)

    def test_explicit_backend_overrides_config(self) -> None:
        self.write_eval_config()
        cfg = json.loads((self.root / ".gatekit" / "config.json").read_text(encoding="utf-8"))
        cfg["verify"]["evaluator"] = "agent"
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        self.assertEqual(jobs.evaluate(self.root, backend_name="fake")["state"], "passed")

    def test_cli_prints_tail_and_exits_zero(self) -> None:
        import io
        from contextlib import redirect_stdout
        self.write_eval_config()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = jobs.run(["evaluate", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("fake-worker report", buf.getvalue())
        self.assertIn("passed", buf.getvalue())

    def test_cli_nonzero_on_failed(self) -> None:
        import io
        from contextlib import redirect_stdout
        self.write_eval_config(exit_code=2)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(jobs.run(["evaluate", "--root", str(self.root)]), 1)


class TestWorkerEnvIsolation(JobTestCase):
    def test_parent_gatekit_env_is_not_inherited(self) -> None:
        self.write_config()
        self.set_env(GATEKIT_LEAK="x", FAKE_WORKER_OUT="src/note.txt")
        self.write_tasks(self.simple_task())
        job = jobs.start(self.root)
        stderr = (self.task_dir(job["job_id"], "write-note") / "stderr.txt").read_text(encoding="utf-8")
        self.assertIn("task=write-note", stderr)
        # the fake worker echoes GATEKIT_TASK_ID/JOB_ID only; prove the leak key is gone via a probe
        probe = self.root / "probe.py"
        probe.write_text("import os,sys; sys.exit(1 if 'GATEKIT_LEAK' in os.environ else 0)", encoding="utf-8")
        cfg = json.loads((self.root / ".gatekit" / "config.json").read_text(encoding="utf-8"))
        cfg["worker"]["backends"]["fake"]["argv"] = [sys.executable, str(probe)]
        (self.root / ".gatekit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        job = jobs.start(self.root)
        status = json.loads((self.task_dir(job["job_id"], "write-note") / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["exit"], 0)


# ------------------------------------------------------- design in the prompt


class TestDesignSection(JobTestCase):
    """ADR-0008 decision 4: the brief carries the design its task touches."""

    def write_tokens(self, data: dict) -> None:
        (self.root / "spec" / "tokens.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

    def v2(self, **kw) -> dict:
        data = {"version": 2, "source": [], "patterns": []}
        data.update(kw)
        return data

    def test_prompt_without_tokens_is_byte_identical_to_today(self) -> None:
        task = self.simple_task()
        before = jobs.build_prompt(task, "job-1")
        after = jobs.build_prompt(task, "job-1", root=self.root)
        self.assertEqual(before, after)
        self.assertNotIn("## Design", after)

    def test_unparsable_tokens_leaves_the_prompt_unchanged(self) -> None:
        (self.root / "spec" / "tokens.json").write_text("{nope", encoding="utf-8")
        task = self.simple_task()
        self.assertEqual(
            jobs.build_prompt(task, "job-1"),
            jobs.build_prompt(task, "job-1", root=self.root),
        )

    def test_design_section_sits_between_gates_and_reporting(self) -> None:
        self.write_tokens(self.v2(color={"primary": "#3366ff"}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        gates_at = prompt.index("## Gates that will judge this task")
        design_at = prompt.index("## Design")
        report_at = prompt.index("## Reporting")
        self.assertLess(gates_at, design_at)
        self.assertLess(design_at, report_at)

    def test_token_groups_are_rendered_as_group_dot_name_lines(self) -> None:
        self.write_tokens(self.v2(color={"primary": "#3366ff"}, space={"md": "16px"}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("color.primary: #3366ff", prompt)
        self.assertIn("space.md: 16px", prompt)

    def test_open_groups_need_no_code_change(self) -> None:
        self.write_tokens(self.v2(radius={"sm": "4px"}, motion={"fast": "120ms"}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("radius.sm: 4px", prompt)
        self.assertIn("motion.fast: 120ms", prompt)

    def test_object_token_with_a_value_key_renders_as_one_line(self) -> None:
        """`{"value": ..., "evidence": ...}` is one token, not two.

        The worker needs the value. `evidence` is bookkeeping for the spec
        reader, and rendering it as `color.primary.evidence` would read like a
        second token it could use.
        """
        self.write_tokens(self.v2(color={"primary": {"value": "#3366ff", "evidence": "preset:calm"}}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("color.primary: #3366ff", prompt)
        self.assertNotIn("color.primary.value", prompt)
        self.assertNotIn("preset:calm", prompt)

    def test_a_merged_preset_token_renders_as_its_value(self) -> None:
        """What `design merge-preset` writes must read correctly in a brief."""
        self.write_tokens(
            self.v2(
                source=["preset:calm"],
                color={"primary": "#aaaaaa", "accent": {"value": "#ff0000", "evidence": "preset:calm"}},
                radius={"md": {"value": "8px", "evidence": "preset:calm"}},
            )
        )
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("color.primary: #aaaaaa", prompt)
        self.assertIn("color.accent: #ff0000", prompt)
        self.assertIn("radius.md: 8px", prompt)
        self.assertNotIn(".evidence", prompt)

    def test_nested_object_without_a_value_key_still_recurses(self) -> None:
        self.write_tokens(self.v2(font={"body": {"size": "16px", "leading": "1.5"}}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("font.body.size: 16px", prompt)
        self.assertIn("font.body.leading: 1.5", prompt)

    def test_empty_tokens_object_leaves_the_prompt_unchanged(self) -> None:
        """A file holding `{}` carries no design, so it adds no section."""
        (self.root / "spec" / "tokens.json").write_text("{}", encoding="utf-8")
        task = self.simple_task()
        self.assertEqual(
            jobs.build_prompt(task, "job-1"),
            jobs.build_prompt(task, "job-1", root=self.root),
        )

    def test_tokens_with_no_groups_and_no_patterns_leaves_the_prompt_unchanged(self) -> None:
        self.write_tokens(self.v2(source=["figma.com/x"]))
        task = self.simple_task()
        self.assertEqual(
            jobs.build_prompt(task, "job-1"),
            jobs.build_prompt(task, "job-1", root=self.root),
        )

    def test_patterns_alone_are_enough_to_produce_a_section(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P1", "rule": "Cards in a list.", "applies_to": "all", "evidence": "x"}])
        )
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("## Design", prompt)

    def test_an_empty_group_alone_does_not_produce_a_section(self) -> None:
        self.write_tokens(self.v2(color={}))
        task = self.simple_task()
        self.assertEqual(
            jobs.build_prompt(task, "job-1"),
            jobs.build_prompt(task, "job-1", root=self.root),
        )

    def test_pattern_applying_to_all_is_always_included(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P1", "rule": "Cards in a list.", "applies_to": "all", "evidence": "x"}])
        )
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("- P1: Cards in a list. (applies to all)", prompt)

    def test_pattern_scoped_to_a_screen_the_task_names_is_included(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Bottom sheet on mobile.", "applies_to": ["S3"], "evidence": "x"}])
        )
        task = self.simple_task(instruction="Build the S3 detail view.")
        prompt = jobs.build_prompt(task, "job-1", root=self.root)
        self.assertIn("- P2: Bottom sheet on mobile. (applies to S3)", prompt)

    def test_pattern_scoped_to_a_screen_the_task_does_not_name_is_omitted(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Bottom sheet on mobile.", "applies_to": ["S9"], "evidence": "x"}])
        )
        task = self.simple_task(instruction="Build the S3 detail view.")
        self.assertNotIn("P2", jobs.build_prompt(task, "job-1", root=self.root))

    def test_screen_reference_in_the_title_counts(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Card grid.", "applies_to": ["S4"], "evidence": "x"}])
        )
        task = self.simple_task(title="S4 gallery", instruction="plain")
        self.assertIn("- P2: Card grid. (applies to S4)", jobs.build_prompt(task, "job-1", root=self.root))

    def test_zero_padded_applies_to_matches_the_unpadded_form(self) -> None:
        """`S01` in applies_to and `S1` in the task are the same screen.

        Missing the match loses the worker a design rule silently, which is
        worse than a rule it did not need.
        """
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Card grid.", "applies_to": ["S01"], "evidence": "x"}])
        )
        task = self.simple_task(instruction="Build the S1 view.")
        self.assertIn("- P2: Card grid.", jobs.build_prompt(task, "job-1", root=self.root))

    def test_unpadded_applies_to_matches_a_padded_mention(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Card grid.", "applies_to": ["S1"], "evidence": "x"}])
        )
        task = self.simple_task(instruction="Build the S01 view.")
        self.assertIn("- P2: Card grid.", jobs.build_prompt(task, "job-1", root=self.root))

    def test_padding_does_not_make_different_screens_match(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Card grid.", "applies_to": ["S01"], "evidence": "x"}])
        )
        task = self.simple_task(instruction="Build the S10 view.")
        self.assertNotIn("P2", jobs.build_prompt(task, "job-1", root=self.root))

    def test_screen_match_respects_word_boundaries(self) -> None:
        self.write_tokens(
            self.v2(patterns=[{"id": "P2", "rule": "Card grid.", "applies_to": ["S1"], "evidence": "x"}])
        )
        task = self.simple_task(title="plain", instruction="Touch nothing in S12.")
        self.assertNotIn("P2", jobs.build_prompt(task, "job-1", root=self.root))

    def test_design_section_names_the_spec_files_to_read(self) -> None:
        self.write_tokens(self.v2(color={"primary": "#3366ff"}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn(
            "Read spec/02-design.md and spec/02-screens.md for anything not listed here.",
            prompt,
        )

    def test_v1_tokens_reach_the_prompt_too(self) -> None:
        self.write_tokens({"source": "figma", "color": {"primary": "#3366ff"}})
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertIn("## Design", prompt)
        self.assertIn("color.primary: #3366ff", prompt)

    def test_reserved_keys_are_not_rendered_as_groups(self) -> None:
        self.write_tokens(self.v2(source=["figma"], color={"primary": "#3366ff"}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", root=self.root)
        self.assertNotIn("source.", prompt)
        self.assertNotIn("version", prompt.split("## Design")[1].split("## Reporting")[0])

    def test_extra_section_still_follows_the_design_section(self) -> None:
        self.write_tokens(self.v2(color={"primary": "#3366ff"}))
        prompt = jobs.build_prompt(self.simple_task(), "job-1", "gate output", root=self.root)
        self.assertLess(prompt.index("## Design"), prompt.index("## Previous attempt failed"))

    def test_start_threads_the_root_into_the_written_prompt(self) -> None:
        self.write_config()
        self.write_tokens(self.v2(color={"primary": "#3366ff"}))
        task = self.simple_task()
        self.write_tasks(task)
        job = jobs.start(self.root, dry_run=True)
        written = (self.task_dir(job["job_id"], "write-note") / "prompt.md").read_text(encoding="utf-8")
        self.assertIn("color.primary: #3366ff", written)


# ----------------------------------------------------- exit 3 is unverified


class TestGateExitThree(JobTestCase):
    """ADR-0008 decision 5 needs a gate that can say `unverified` by exit code."""

    def gate_exiting(self, code: int) -> dict:
        return {
            "name": "coded",
            "argv": [sys.executable, "-c", "import sys; sys.exit(%d)" % code],
        }

    def test_exit_three_is_unverified(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [self.gate_exiting(3)]})
        self.assertEqual(result["gates"][0]["verdict"], verdict.UNVERIFIED)
        self.assertEqual(result["verdict"], verdict.UNVERIFIED)

    def test_exit_three_detail_says_unverified(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [self.gate_exiting(3)]})
        self.assertEqual(result["gates"][0]["detail"], "exit 3 (unverified)")
        self.assertEqual(result["gates"][0]["exit"], 3)

    def test_exit_zero_is_still_ok(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [self.gate_exiting(0)]})
        self.assertEqual(result["gates"][0]["verdict"], verdict.OK)
        self.assertEqual(result["gates"][0]["detail"], "exit 0")

    def test_other_non_zero_exits_are_still_fail(self) -> None:
        for code in (1, 2, 4):
            result = jobs.run_gates(self.root, {"gates": [self.gate_exiting(code)]})
            self.assertEqual(result["gates"][0]["verdict"], verdict.FAIL, "exit %d" % code)
            self.assertEqual(result["gates"][0]["detail"], "exit %d" % code)

    def test_unverified_gate_is_not_counted_as_passed(self) -> None:
        result = jobs.run_gates(self.root, {"gates": [self.gate_exiting(3)]})
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["total"], 1)

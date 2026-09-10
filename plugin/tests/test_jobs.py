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

"""Worker jobs (§10).

`jobs start` builds `.gatekit/jobs/<job_id>/`, writes one directory per task,
spawns the configured worker backend with the task prompt on stdin, then runs
the task's gates. A worker that exits 0 but fails a gate is `failed`, never
`passed` — the worker's own report never decides the verdict.

Every JSON write goes through `write_json` (tmp file + `os.replace`) so a job
directory read concurrently never sees a half-written file.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional

from gatekit import config, paths, spec, verdict, workers

STATES = (
    "queued",
    "running",
    "gating",
    "passed",
    "failed",
    "timeout",
    "redelegated",
)

GATE_TIMEOUT_S = 60.0
#: Exit code by which a task gate reports `unverified`: it ran, but it could not
#: judge (ADR-0008 decision 5 — the token gate uses it when tokens.json is
#: absent or the task wrote no file it knows how to scan). 0 is `ok`, every
#: other non-zero code is `fail`.
GATE_UNVERIFIED_EXIT = 3
TAIL_BYTES = 4000
#: How much failed-gate output `redelegate` appends to the next prompt.
REDELEGATE_TAIL_CHARS = 2000


# --------------------------------------------------------------------- helpers


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_job_id() -> str:
    """UTC timestamp + 4 hex chars, sortable and collision-resistant."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "%s-%s" % (stamp, secrets.token_hex(2))


def write_json(path, data) -> None:
    """Atomic JSON write: temp file in the same directory, then os.replace."""
    path = str(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path, default=None):
    try:
        with open(str(path), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def _tail(text: str, limit: int = TAIL_BYTES) -> str:
    return text if len(text) <= limit else text[-limit:]


def jobs_dir(root):
    return paths.state_dir(root) / "jobs"


def job_dir(root, job_id: str):
    return jobs_dir(root) / job_id


def latest_job_id(root) -> Optional[str]:
    base = jobs_dir(root)
    if not base.is_dir():
        return None
    names = sorted(p.name for p in base.iterdir() if (p / "job.json").is_file())
    return names[-1] if names else None


def load_tasks(root) -> list:
    """Parse ```gatekit-task fences out of spec/04-tasks.md."""
    src = paths.spec_dir(root) / "04-tasks.md"
    if not src.is_file():
        return []
    return spec.parse_fences(src.read_text(encoding="utf-8"), "gatekit-task")


# ------------------------------------------------------------------- prompt


def _pattern_applies(pattern: dict, task_text: str) -> bool:
    """True when *pattern* governs a task whose words are *task_text*.

    ``applies_to: "all"`` always applies. A list applies when the task names one
    of its screen ids. Ids are compared on their canonical spelling, so `S01`
    matches `S1` while `S12` still does not drag in a pattern scoped to `S1`.
    """
    from gatekit import design as design_mod

    applies_to = pattern.get("applies_to")
    if isinstance(applies_to, str):
        return applies_to.strip().lower() == "all"
    if not isinstance(applies_to, list):
        return False
    # Compare on the canonical spelling so `S01` in applies_to still matches a
    # task that writes `S1`, and neither matches `S10`.
    mentioned = set(design_mod.referenced_ids(task_text))
    for screen in applies_to:
        if not isinstance(screen, str) or not screen.strip():
            continue
        try:
            wanted = design_mod.normalize_id(screen.strip())
        except (ValueError, IndexError):
            # Not an `S<n>`-shaped id; fall back to a literal bounded match.
            if re.search(
                r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(screen.strip()), task_text
            ):
                return True
            continue
        if wanted in mentioned:
            return True
    return False


def _applies_to_text(pattern: dict) -> str:
    applies_to = pattern.get("applies_to")
    if isinstance(applies_to, list):
        return ", ".join(str(s) for s in applies_to)
    return str(applies_to)


def _token_lines(prefix: str, value) -> list:
    """Render one token as ``<prefix>: <value>`` lines.

    A dict carrying a ``value`` key is one token that knows where it came from,
    which is the shape ``design merge-preset`` writes. Only its value reaches
    the worker: ``evidence`` is bookkeeping for the spec reader, and rendering
    it as ``color.primary.evidence`` would read like a second usable token.
    A dict without ``value`` is a genuinely nested group and still recurses.
    """
    if isinstance(value, dict):
        if "value" in value:
            return ["%s: %s" % (prefix, value["value"])]
        lines = []
        for key, child in value.items():
            lines.extend(_token_lines("%s.%s" % (prefix, key), child))
        return lines
    return ["%s: %s" % (prefix, value)]


def has_design(tokens: dict) -> bool:
    """True when *tokens* carries anything a worker could act on.

    A parsable file is not the same as a design. ``{}`` and a file holding only
    ``version``/``source`` normalize to a truthy dict but say nothing, so the
    prompt must stay byte-identical to the one with no file at all.
    """
    from gatekit import design as design_mod

    if any(entries for entries in design_mod.token_groups(tokens).values()):
        return True
    return bool(tokens.get("patterns"))


def _design_lines(task: dict, tokens: dict) -> list:
    """The ``## Design`` section body, generated from tokens.json by code.

    ADR-0008 decision 4: a pattern reaches the worker through the same brief as
    its instruction, so nothing depends on the task author having remembered to
    write "follow P2" into the text.
    """
    from gatekit import design as design_mod

    task_text = "\n".join(
        [str(task.get("title", "")), str(task.get("instruction", ""))]
    )
    lines = []
    for pattern in tokens.get("patterns") or []:
        if not isinstance(pattern, dict) or not _pattern_applies(pattern, task_text):
            continue
        lines.append(
            "- %s: %s (applies to %s)"
            % (pattern.get("id", "P?"), str(pattern.get("rule", "")).strip(), _applies_to_text(pattern))
        )

    token_lines = []
    for group, entries in sorted(design_mod.token_groups(tokens).items()):
        for name, value in entries.items():
            token_lines.extend(_token_lines("%s.%s" % (group, name), value))
    if token_lines:
        if lines:
            lines.append("")
        lines.extend(token_lines)

    if lines:
        lines.append("")
    lines.append(
        "Read spec/02-design.md and spec/02-screens.md for anything not listed here."
    )
    return lines


def build_prompt(task: dict, job_id: str, extra: str = "", root=None) -> str:
    """The self-contained brief handed to the worker on stdin.

    *root* is optional so existing callers keep working: without it, and
    whenever ``spec/tokens.json`` is absent or unparsable, the prompt is
    byte-identical to the one this function produced before ADR-0008.
    """
    scope = task.get("write_scope")
    if isinstance(scope, list):
        scope_text = "\n".join("- %s" % s for s in scope) or "- (none)"
    else:
        scope_text = "- %s" % (scope or "read-only")

    gates = task.get("gates") or []
    if gates:
        gate_text = "\n".join(
            "- %s: %s" % (g.get("name", "gate-%d" % i), " ".join(g.get("argv") or []))
            for i, g in enumerate(gates)
        )
    else:
        gate_text = "- (none declared)"

    parts = [
        "# Task %s — %s" % (task.get("id", "?"), task.get("title", "")),
        "",
        "job: %s" % job_id,
        "",
        "## Instruction",
        "",
        str(task.get("instruction", "")).strip(),
        "",
        "## Write scope",
        "",
        "You may create or modify ONLY these paths. Writes outside this scope are",
        "denied by a hook, not by convention.",
        "",
        scope_text,
        "",
        "## Gates that will judge this task",
        "",
        "These commands run after you exit. They decide whether the task passed.",
        "",
        gate_text,
        "",
    ]

    if root is not None:
        from gatekit import design as design_mod

        tokens = design_mod.load_tokens(root)
        if has_design(tokens):
            parts += ["## Design", ""] + _design_lines(task, tokens) + [""]

    parts += [
        "## Reporting",
        "",
        "When you are done, reply with a short report: what you changed and what",
        "you could not do. Do not claim success; the gates decide.",
    ]
    if extra:
        parts += ["", "## Previous attempt failed", "", extra.strip()]
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------- task running


def _task_dir(jdir, task_id: str):
    return jdir / "tasks" / task_id


def _set_status(jdir, task_id: str, **fields) -> dict:
    path = _task_dir(jdir, task_id) / "status.json"
    status = read_json(path, {}) or {}
    status.update(fields)
    status["task_id"] = task_id
    status["updated_at"] = _now()
    write_json(path, status)
    return status


def run_gates(root, task: dict) -> dict:
    """Run every gate of a task sequentially. Returns the gates.json payload."""
    results = []
    for index, gate in enumerate(task.get("gates") or []):
        name = gate.get("name") or "gate-%d" % index
        argv = gate.get("argv")
        if not isinstance(argv, list) or not argv:
            results.append(
                {
                    "name": name,
                    "verdict": verdict.FAIL,
                    "exit": None,
                    "detail": "gate has no argv",
                    "stdout_tail": "",
                    "stderr_tail": "",
                }
            )
            continue
        started = time.time()
        try:
            proc = subprocess.run(
                [str(a) for a in argv],
                cwd=str(root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=GATE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            results.append(
                {
                    "name": name,
                    "verdict": verdict.UNVERIFIED,
                    "exit": None,
                    "detail": "timed out after %ds" % int(GATE_TIMEOUT_S),
                    "elapsed_s": round(time.time() - started, 3),
                    "stdout_tail": "",
                    "stderr_tail": "",
                }
            )
            continue
        except OSError as exc:
            results.append(
                {
                    "name": name,
                    "verdict": verdict.FAIL,
                    "exit": None,
                    "detail": "could not run: %s" % exc,
                    "elapsed_s": round(time.time() - started, 3),
                    "stdout_tail": "",
                    "stderr_tail": "",
                }
            )
            continue
        out = (proc.stdout or b"").decode("utf-8", "replace")
        err = (proc.stderr or b"").decode("utf-8", "replace")
        if proc.returncode == 0:
            gate_verdict, detail = verdict.OK, "exit 0"
        elif proc.returncode == GATE_UNVERIFIED_EXIT:
            # A gate that could not judge says so by exit code rather than by
            # guessing. `unverified` is never rounded to either side, so this
            # task neither passes nor fails on it.
            gate_verdict, detail = verdict.UNVERIFIED, "exit %d (unverified)" % GATE_UNVERIFIED_EXIT
        else:
            gate_verdict, detail = verdict.FAIL, "exit %d" % proc.returncode
        results.append(
            {
                "name": name,
                "verdict": gate_verdict,
                "exit": proc.returncode,
                "detail": detail,
                "elapsed_s": round(time.time() - started, 3),
                "stdout_tail": _tail(out),
                "stderr_tail": _tail(err),
            }
        )
    aggregate = verdict.aggregate([r["verdict"] for r in results]) if results else verdict.UNVERIFIED
    passed = sum(1 for r in results if r["verdict"] == verdict.OK)
    return {
        "verdict": aggregate,
        "passed": passed,
        "total": len(results),
        "gates": results,
        "ran_at": _now(),
    }


def _spawn_worker(root, backend: dict, task: dict, job_id: str, tdir, timeout_s: float) -> dict:
    """Run the worker for one task; returns {"exit", "timed_out"}."""
    # A worker gets exactly the two gatekit variables it needs; nothing a
    # parent worker or evaluator session exported leaks into it.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GATEKIT_")}
    env["GATEKIT_TASK_ID"] = str(task.get("id", ""))
    env["GATEKIT_JOB_ID"] = job_id
    prompt = (tdir / "prompt.md").read_text(encoding="utf-8")

    out_path, err_path = tdir / "output.txt", tdir / "stderr.txt"
    started = time.time()
    with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
        try:
            proc = subprocess.Popen(
                list(backend["argv"]),
                cwd=str(root),
                env=env,
                stdin=subprocess.PIPE,
                stdout=out_f,
                stderr=err_f,
            )
        except OSError as exc:
            err_f.write(("gatekit: could not spawn worker: %s\n" % exc).encode("utf-8"))
            return {"exit": None, "timed_out": False, "spawn_error": str(exc),
                    "elapsed_s": round(time.time() - started, 3)}
        try:
            proc.communicate(prompt.encode("utf-8"), timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.communicate(timeout=5)
            except Exception:
                pass
            timed_out = True
    return {
        "exit": proc.returncode,
        "timed_out": timed_out,
        "elapsed_s": round(time.time() - started, 3),
    }


def execute_task(root, jdir, job_id: str, task: dict, backend: dict, timeout_s: float) -> dict:
    """Spawn worker, then gates. Returns the final status dict."""
    task_id = str(task.get("id"))
    tdir = _task_dir(jdir, task_id)
    _set_status(jdir, task_id, state="running", started_at=_now())

    result = _spawn_worker(root, backend, task, job_id, tdir, timeout_s)

    if result["timed_out"]:
        return _set_status(
            jdir,
            task_id,
            state="timeout",
            exit=None,
            elapsed_s=result.get("elapsed_s"),
            finished_at=_now(),
            detail="worker exceeded task_timeout_s=%s and was killed" % timeout_s,
        )

    _set_status(jdir, task_id, state="gating", exit=result["exit"],
                elapsed_s=result.get("elapsed_s"))
    gates = run_gates(root, task)
    write_json(tdir / "gates.json", gates)

    worker_ok = result["exit"] == 0
    all_gates_ok = gates["total"] > 0 and gates["verdict"] == verdict.OK
    state = "passed" if (worker_ok and all_gates_ok) else "failed"
    if not worker_ok:
        detail = "worker exited %s" % result["exit"]
    elif not all_gates_ok:
        detail = "worker exited 0 but gates verdict is %s (%d/%d ok)" % (
            gates["verdict"], gates["passed"], gates["total"],
        )
    else:
        detail = "worker exited 0 and %d/%d gates ok" % (gates["passed"], gates["total"])

    return _set_status(
        jdir,
        task_id,
        state=state,
        exit=result["exit"],
        gates_verdict=gates["verdict"],
        gates_passed=gates["passed"],
        gates_total=gates["total"],
        finished_at=_now(),
        detail=detail,
    )


# ------------------------------------------------------------------ evaluate

EVALUATOR_BRIEF = """# Evaluator brief

You are the evaluator. You did not write this code and you must not change it.
Your session is read-only: the CLI sandbox and the write gate both refuse
writes, and any attempt to write is itself a finding against you.

1. Run `{launcher} contract run --json` from the project root.
2. Read `spec/05-gate.md` and carry out every E2E step it describes by hand,
   in order. Record what you actually observed, not what should happen.
3. For each criterion and each E2E step give one verdict from
   `ok / warn / fail / unverified`. A step you could not run is `unverified`;
   never round it to either side.
4. Do not fix anything you find. Report it.
5. Reply with the verdict table only — one row per criterion and per E2E step,
   then the aggregate — in {lang}. Do not paste command transcripts.
"""


def evaluator_brief(root, lang: str = "en") -> str:
    return EVALUATOR_BRIEF.format(launcher=paths.cli_invocation(), lang=lang)


def evaluate(root, backend_name=None, prompt_path=None, timeout_s=None, lang: str = "en") -> dict:
    """Run one read-only worker as the independent evaluator.

    The backend is *backend_name* or ``verify.evaluator`` from config; ``agent``
    means the host's own subagent and is not runnable from here. The worker
    gets ``GATEKIT_TASK_ID=evaluate`` with a read-only ``task.json`` so the
    write gate refuses writes inside its session, on top of the backend's
    ``read_only_argv`` sandbox.
    """
    name = backend_name or workers.evaluator_name(root)
    if name == "agent":
        raise ValueError(
            "verify.evaluator is 'agent' (the host's own subagent); run "
            "`workers set-evaluator <backend>` or pass --backend to use a CLI evaluator"
        )
    backend = workers.resolve(root, name, read_only=True)
    cfg = config.load(root)
    if timeout_s is None:
        timeout_s = float((cfg.get("build") or {}).get("task_timeout_s", 900))

    job_id = new_job_id()
    jdir = job_dir(root, job_id)
    edir = jdir / "evaluate"
    edir.mkdir(parents=True, exist_ok=True)
    task = {"id": "evaluate", "title": "independent evaluation", "write_scope": "read-only"}
    write_json(edir / "task.json", task)
    if prompt_path is not None:
        prompt = pathlib.Path(prompt_path).read_text(encoding="utf-8")
    else:
        prompt = evaluator_brief(root, lang)
    (edir / "prompt.md").write_text(prompt, encoding="utf-8")
    write_json(jdir / "job.json", {
        "job_id": job_id,
        "kind": "evaluate",
        "started_at": _now(),
        "backend": {"name": backend["name"], "argv": backend["argv"],
                    "unsafe": backend["unsafe"], "read_only": True},
        "timeout_s": timeout_s,
    })
    write_json(edir / "status.json", {"task_id": "evaluate", "state": "running", "started_at": _now()})

    result = _spawn_worker(root, backend, task, job_id, edir, timeout_s)
    if result["timed_out"]:
        state, detail = "timeout", "evaluator exceeded %ss and was killed" % timeout_s
    elif result["exit"] == 0:
        state, detail = "passed", "evaluator exited 0"
    else:
        state, detail = "failed", "evaluator exited %s" % result["exit"]
    status_doc = {
        "task_id": "evaluate", "state": state, "exit": result["exit"],
        "elapsed_s": result.get("elapsed_s"), "finished_at": _now(), "detail": detail,
    }
    write_json(edir / "status.json", status_doc)
    try:
        output = (edir / "output.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        output = ""
    return {"job_id": job_id, "backend": backend["name"], "state": state,
            "exit": result["exit"], "detail": detail, "output_tail": _tail(output)}


# ----------------------------------------------------------------- scheduling


def order_tasks(tasks: list) -> list:
    """Group tasks into waves honouring `round` then `depends_on`.

    Returns a list of waves; every task in a wave may run concurrently.
    A dependency cycle (or a dependency on an unknown id) leaves the remaining
    tasks in one final wave rather than dropping them.
    """
    remaining = list(tasks)
    known = {str(t.get("id")) for t in tasks}
    done = set()
    waves = []
    while remaining:
        rounds = [int(t.get("round", 1) or 1) for t in remaining]
        current_round = min(rounds)
        ready = [
            t
            for t in remaining
            if int(t.get("round", 1) or 1) == current_round
            and all(
                (str(d) in done or str(d) not in known)
                for d in (t.get("depends_on") or [])
            )
        ]
        if not ready:  # cycle or cross-round dependency: run what is left as-is
            waves.append(list(remaining))
            break
        waves.append(ready)
        for t in ready:
            done.add(str(t.get("id")))
        ready_ids = {id(t) for t in ready}
        remaining = [t for t in remaining if id(t) not in ready_ids]
    return waves


def _run_wave(root, jdir, job_id, wave, backend, timeout_s, parallel) -> None:
    """Run one wave, at most `parallel` tasks at a time.

    Tasks are run sequentially within each slot using threads; the heavy lifting
    is subprocess I/O, so threads are sufficient and keep the stdlib-only rule.
    """
    import threading

    limit = max(1, int(parallel or 1))
    lock = threading.Semaphore(limit)
    errors = []

    def worker(task):
        with lock:
            try:
                execute_task(root, jdir, job_id, task, backend, timeout_s)
            except BaseException as exc:  # never let one task kill the job
                errors.append((task.get("id"), exc))
                _set_status(
                    jdir,
                    str(task.get("id")),
                    state="failed",
                    finished_at=_now(),
                    detail="gatekit internal error: %s" % exc,
                )

    threads = [threading.Thread(target=worker, args=(t,)) for t in wave]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


# ---------------------------------------------------------------- subcommands


def start(root, task_ids=None, backend_name=None, parallel=None, dry_run=False) -> dict:
    """Create a job directory and (unless dry_run) run every selected task."""
    cfg = config.load(root)
    build_cfg = cfg.get("build") or {}
    tasks = load_tasks(root)
    if task_ids:
        wanted = [t.strip() for t in task_ids if t.strip()]
        by_id = {str(t.get("id")): t for t in tasks}
        missing = [w for w in wanted if w not in by_id]
        if missing:
            raise ValueError("unknown task id(s): %s" % ", ".join(missing))
        tasks = [by_id[w] for w in wanted]
    if not tasks:
        raise ValueError(
            "no tasks found; expected ```gatekit-task fences in spec/04-tasks.md"
        )

    backend = workers.resolve(root, backend_name)
    parallel = int(parallel or build_cfg.get("parallel", 3) or 1)
    timeout_s = float(build_cfg.get("task_timeout_s", 900) or 900)
    max_retries = int(build_cfg.get("max_retries", 2) or 0)

    job_id = new_job_id()
    jdir = job_dir(root, job_id)
    (jdir / "tasks").mkdir(parents=True, exist_ok=True)

    job = {
        "version": 1,
        "job_id": job_id,
        "started_at": _now(),
        "backend": {
            "name": backend["name"],
            "argv": backend["argv"],
            "unsafe": backend["unsafe"],
        },
        "parallel": parallel,
        "task_timeout_s": timeout_s,
        "max_retries": max_retries,
        "dry_run": bool(dry_run),
        "tasks": [str(t.get("id")) for t in tasks],
        "config": {"build": build_cfg},
    }
    write_json(jdir / "job.json", job)

    for task in tasks:
        task_id = str(task.get("id"))
        tdir = _task_dir(jdir, task_id)
        tdir.mkdir(parents=True, exist_ok=True)
        write_json(tdir / "task.json", task)
        (tdir / "prompt.md").write_text(
            build_prompt(task, job_id, root=root), encoding="utf-8"
        )
        _set_status(jdir, task_id, state="queued", attempt=1, created_at=_now())

    if dry_run:
        return job

    for wave in order_tasks(tasks):
        _run_wave(root, jdir, job_id, wave, backend, timeout_s, parallel)

    job["finished_at"] = _now()
    write_json(jdir / "job.json", job)
    return job


def status(root, job_id: Optional[str] = None) -> dict:
    job_id = job_id or latest_job_id(root)
    if not job_id:
        return {"job_id": None, "verdict": verdict.UNVERIFIED, "tasks": [],
                "detail": "no jobs under .gatekit/jobs/"}
    jdir = job_dir(root, job_id)
    job = read_json(jdir / "job.json", {}) or {}
    rows = []
    for task_id in job.get("tasks", []):
        st = read_json(_task_dir(jdir, task_id) / "status.json", {}) or {}
        rows.append(
            {
                "id": task_id,
                "state": st.get("state", "queued"),
                "attempt": st.get("attempt", 1),
                "gates_passed": st.get("gates_passed", 0),
                "gates_total": st.get("gates_total", 0),
                "detail": st.get("detail", ""),
            }
        )
    states = [r["state"] for r in rows]
    if not rows:
        overall = verdict.UNVERIFIED
    elif any(s in ("failed", "timeout") for s in states):
        overall = verdict.FAIL
    elif any(s in ("queued", "running", "gating") for s in states):
        overall = verdict.UNVERIFIED
    else:
        overall = verdict.OK
    return {
        "job_id": job_id,
        "verdict": overall,
        "backend": (job.get("backend") or {}).get("name"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "done": all(s in ("passed", "failed", "timeout", "redelegated") for s in states)
        if states
        else False,
        "tasks": rows,
    }


def wait(root, job_id: Optional[str] = None, timeout: float = 0.0) -> dict:
    """Poll `status` until every task is terminal or `timeout` seconds elapse."""
    deadline = time.time() + timeout if timeout and timeout > 0 else None
    while True:
        current = status(root, job_id)
        if current.get("done"):
            return current
        if deadline is not None and time.time() >= deadline:
            current["detail"] = "wait timed out after %ss" % timeout
            return current
        time.sleep(0.2)


def results(root, job_id: Optional[str] = None) -> dict:
    return status(root, job_id)


def redelegate(root, task_id: str, job_id: Optional[str] = None) -> dict:
    """Archive the failed attempt, extend the prompt with the gate output, rerun."""
    job_id = job_id or latest_job_id(root)
    if not job_id:
        raise ValueError("no job to redelegate in")
    jdir = job_dir(root, job_id)
    job = read_json(jdir / "job.json", {}) or {}
    tdir = _task_dir(jdir, task_id)
    if not tdir.is_dir():
        raise ValueError("task %r is not part of job %s" % (task_id, job_id))

    st = read_json(tdir / "status.json", {}) or {}
    attempt = int(st.get("attempt", 1) or 1)
    max_retries = int(job.get("max_retries", 2) or 0)
    if attempt > max_retries:
        raise RetryBudgetExceeded(
            "task %r already used %d attempt(s); max_retries=%d"
            % (task_id, attempt, max_retries)
        )

    archive = tdir / ("attempt-%d" % attempt)
    archive.mkdir(parents=True, exist_ok=True)
    for name in ("prompt.md", "output.txt", "stderr.txt", "gates.json", "status.json"):
        src = tdir / name
        if src.is_file():
            shutil.move(str(src), str(archive / name))

    gates = read_json(archive / "gates.json", {}) or {}
    failed = [
        g for g in gates.get("gates", []) if g.get("verdict") in (verdict.FAIL, verdict.UNVERIFIED)
    ]
    if failed:
        last = failed[-1]
        extra = "\n".join(
            [
                "Attempt %d failed gate `%s` (%s)." % (attempt, last.get("name"), last.get("detail", "")),
                "",
                "stdout (tail):",
                "```",
                _tail(last.get("stdout_tail", ""), REDELEGATE_TAIL_CHARS),
                "```",
                "",
                "stderr (tail):",
                "```",
                _tail(last.get("stderr_tail", ""), REDELEGATE_TAIL_CHARS),
                "```",
                "",
                "Fix the cause, stay inside the write scope, then stop.",
            ]
        )
    else:
        extra = "Attempt %d did not pass. No gate output was captured (the worker " \
                "may have exited non-zero or timed out). Re-do the task." % attempt

    task = read_json(tdir / "task.json", {}) or {}
    (tdir / "prompt.md").write_text(
        build_prompt(task, job_id, extra, root=root), encoding="utf-8"
    )
    _set_status(jdir, task_id, state="queued", attempt=attempt + 1, created_at=_now(),
                detail="redelegated after attempt %d" % attempt)

    backend = workers.resolve(root, (job.get("backend") or {}).get("name"))
    timeout_s = float(job.get("task_timeout_s", 900) or 900)
    return execute_task(root, jdir, job_id, task, backend, timeout_s)


class RetryBudgetExceeded(Exception):
    """Raised when `redelegate` is asked to exceed `build.max_retries`."""


def clean(root, all_jobs: bool = False) -> list:
    """Remove job directories. Default keeps the newest job."""
    base = jobs_dir(root)
    if not base.is_dir():
        return []
    names = sorted(p.name for p in base.iterdir() if p.is_dir())
    victims = names if all_jobs else names[:-1]
    for name in victims:
        shutil.rmtree(str(base / name), ignore_errors=True)
    return victims


# --------------------------------------------------------------------------- CLI


def _usage() -> str:
    return (
        "usage: python3 -m gatekit jobs <command>\n"
        "  start [--tasks id,id] [--backend name] [--parallel N] [--dry-run]\n"
        "  status [--job ID] [--json]\n"
        "  wait [--job ID] [--timeout S]\n"
        "  results [--job ID] [--compact|--json]\n"
        "  redelegate <task_id> [--job ID]\n"
        "  evaluate [--backend name] [--prompt FILE] [--lang ko|en] [--json]\n"
        "  clean [--all]\n"
    )


def _opt(argv: list, flag: str):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def _print_table(payload: dict) -> None:
    print("job %s  backend=%s  verdict=%s" % (
        payload.get("job_id"), payload.get("backend"), payload.get("verdict")))
    for row in payload.get("tasks", []):
        print("  %-24s %-12s %d/%d  %s" % (
            row["id"], row["state"], row["gates_passed"], row["gates_total"],
            row.get("detail", "")))


def _print_compact(payload: dict) -> None:
    for row in payload.get("tasks", []):
        print("%s %s %d/%d" % (row["id"], row["state"], row["gates_passed"], row["gates_total"]))


def run(argv: list) -> int:
    argv = list(argv)
    root = paths.project_root(_opt(argv, "--root"))
    if not argv or argv[0] in ("-h", "--help", "help"):
        sys.stdout.write(_usage())
        return 0 if argv else 1
    cmd, rest = argv[0], argv[1:]
    job_id = _opt(rest, "--job")

    try:
        if cmd == "start":
            tasks_arg = _opt(rest, "--tasks")
            job = start(
                root,
                task_ids=tasks_arg.split(",") if tasks_arg else None,
                backend_name=_opt(rest, "--backend"),
                parallel=_opt(rest, "--parallel"),
                dry_run="--dry-run" in rest,
            )
            payload = status(root, job["job_id"])
            if "--json" in rest:
                print(json.dumps(payload, indent=2))
            else:
                _print_table(payload)
            return 0 if payload["verdict"] != verdict.FAIL else 1

        if cmd in ("status", "results"):
            payload = status(root, job_id)
            if "--json" in rest:
                print(json.dumps(payload, indent=2))
            elif "--compact" in rest:
                _print_compact(payload)
            else:
                _print_table(payload)
            return 0 if payload["verdict"] != verdict.FAIL else 1

        if cmd == "wait":
            timeout = float(_opt(rest, "--timeout") or 0)
            payload = wait(root, job_id, timeout)
            if "--json" in rest:
                print(json.dumps(payload, indent=2))
            else:
                _print_table(payload)
            return 0 if payload["verdict"] != verdict.FAIL else 1

        if cmd == "redelegate":
            positional = [a for a in rest if not a.startswith("--")]
            if not positional:
                print("jobs redelegate: missing <task_id>", file=sys.stderr)
                return 2
            st = redelegate(root, positional[0], job_id)
            print("%s %s — %s" % (st.get("task_id"), st.get("state"), st.get("detail", "")))
            return 0 if st.get("state") == "passed" else 1

        if cmd == "evaluate":
            result = evaluate(
                root,
                backend_name=_opt(rest, "--backend"),
                prompt_path=_opt(rest, "--prompt"),
                lang=_opt(rest, "--lang") or "en",
            )
            if "--json" in rest:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print("evaluate job %s  backend=%s  state=%s — %s" % (
                    result["job_id"], result["backend"], result["state"], result["detail"]))
                print("--- evaluator reply (tail) ---")
                print(result["output_tail"].rstrip("\n"))
            return 0 if result["state"] == "passed" else 1

        if cmd == "clean":
            removed = clean(root, all_jobs="--all" in rest)
            print("removed %d job dir(s)%s" % (
                len(removed), (": " + ", ".join(removed)) if removed else ""))
            return 0

    except RetryBudgetExceeded as exc:
        print("jobs: %s" % exc, file=sys.stderr)
        return 3
    except ValueError as exc:
        print("jobs: %s" % exc, file=sys.stderr)
        return 2

    print("jobs: unknown command %r\n" % cmd, file=sys.stderr)
    sys.stderr.write(_usage())
    return 2

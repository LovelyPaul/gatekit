---
name: build
description: Run spec/04-tasks.md as worker jobs behind the gates — spawn workers per task, let the gates decide pass or fail, redelegate failures, and hand off to verify.
argument-hint: "[optional: task ids to build, comma-separated]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# /gatekit:build

Input: `$ARGUMENTS` — optional comma-separated task ids. Empty means every task.

**You do not write source code in this command.** Workers do. While a job runs,
the main session reads status and routes failures; it never edits files under a
task's `write_scope` itself. If you catch yourself about to fix the code
directly, redelegate instead.

## Step 0 — load policy and language

1. Read `${CLAUDE_PLUGIN_ROOT}/policy/language.md` and
   `${CLAUDE_PLUGIN_ROOT}/policy/verification.md`.
2. Detect the language and call it `output_lang`:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "$(head -40 spec/01-prd.md)"
```

Every user-facing string below is written in `output_lang`.

## Step 1 — preconditions (both must hold)

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve check spec/05-gate.md
```

- `spec validate` must not print `fail`. If it does, show the findings and stop.
  Route the user to the pipeline that owns the failing file.
- `approve check` must print `ok`. `fail` means the gate file changed after it
  was approved; `unverified` means it was never approved. In either case **stop**
  and tell the user to run `/gatekit:gate`. Never approve on their behalf, and
  never edit `spec/05-gate.md` to make a hash match. A stale contract can now
  also come from a changed design input (`02-screens.md`, `02-design.md`, or
  `tokens.json`); the fix is the same: `/gatekit:tasks` then `/gatekit:gate`.

Then confirm a worker is actually available:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers check "$(python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers list --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["default"])')" --probe
```

`--probe` sends one trivial prompt through the backend's read-only argv. It
takes a few seconds and is the only check that catches a CLI that exists but
cannot answer here: not logged in, or run inside a sandbox that hides its
credentials. `fail` means exactly that — stop, show the detail, and do not
start the job; the fix is to log in, or (under a sandboxed host such as
Codex) to run this command and `jobs start` with the host's escalated
permissions so the worker CLI can reach its credentials and network.
`unverified` (the probe timed out) is not a blocker; say so once and continue.

## Step 2 — start the job

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs start
```

Add `--tasks <ids>` when `$ARGUMENTS` named specific tasks, `--backend <name>`
when the user asked for one. Read `max_retries` and `parallel` from
`.gatekit/config.json`; do not pass `--parallel` unless the user asked.

The command prints one row per task. Record the job id. It first runs every
task's gates once, before any worker (ADR-0009): gates that already pass
record the task `passed` with no worker (a `warn: gate passed before any
work existed` detail means that gate can pass on an empty tree — tell the
user); a gate whose *command* errors ends the start with exit 4 and names the
task and gate — fix it in `spec/04-tasks.md` (usually a glob instead of a
directory) and start again, never `--no-preflight` to get past it.

## Step 3 — poll

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs status
```

**Never read `output.txt` or `stderr.txt` into context.** They hold whole worker
transcripts and will swamp the session. Use the status table and:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs results --compact
```

which prints `id state gates_passed/total`, one line per task. Read a task's
`gates.json` only when you need the specific failing gate's name.

Terminal states are `passed`, `failed`, `timeout`, `redelegated`, `stopped`
and `blocked`. A `blocked` task never ran because an in-job dependency did
not pass: do not redelegate it; fix the dependency, then
`jobs start --tasks <id>`. To end a job early (a gate turned out wrong), run
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs stop` — it ends this
job's own workers only. Never kill worker processes by name.

## Step 4 — redelegate failures

For every task in `failed` or `timeout`:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs redelegate <task_id>
```

This archives the attempt under `attempt-N/`, appends the failed gate's output
to the prompt and re-runs. Exit code 3 means the task is out of retries
(`build.max_retries`); do not retry past it.

Before redelegating, read the failing gate's output tail in `gates.json`. If
the gate command itself is wrong (it names a path the task was never asked to
create, or fails the same way regardless of the code), fix `spec/04-tasks.md`
first; `redelegate` re-reads the task from it and says `task re-read …
(gates changed)`. A wrong gate handed back with "fix the cause" teaches the
worker to make the wrong command pass.

Count consecutive failures per task. **On the third failure of the same task,
stop redelegating** and switch to diagnosis mode:

1. Read `spec/RECOVERY.md`.
2. Read that task's `gates.json` for the failing gate name and its output tail.
3. Write the diagnosis into `spec/RECOVERY.md` under a heading naming the task:
   what gate fails, what the output says, and the two most likely causes.
4. **Stop the pipeline.** Report to the user that the task is blocked, show the
   failing gate, and say what you would need to unblock it. Do not fix the code
   yourself and do not start another job.

## Step 5 — update progress

When every task is terminal, update `spec/PROGRESS.md` in `output_lang`.

If the file does not exist, copy
`${CLAUDE_PLUGIN_ROOT}/spec-kit/templates/<output_lang>/PROGRESS.md` first and
fill it in. **Keep the template's headings exactly** — `spec validate` requires
them and rejects a heading from the other language. Add your content under the
existing headings; never invent a replacement heading:

- current status: the job id, its backend, and whether the build is done,
- milestones: one line per task — id, final state, gates passed of total,
- failed attempts: every redelegated task with the gate that failed and what
  changed on the retry,
- tasks left blocked, with the failing gate named,
- the timestamp.

Then run `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate` and fix
any PROGRESS.md finding before reporting. Report the same table in chat. State
verdicts as they are. A `timeout` is not a
pass, and a task whose gates never ran is `unverified`, not done.

## Step 6 — hand off

If every task is `passed`, tell the user to run `/gatekit:verify` and stop.
Build passing is not the same as the completion contract passing; only
`/gatekit:verify` reports that, and it uses an evaluator that did not write the
code.

If any task is blocked, say so plainly and do not hand off.

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
  never edit `spec/05-gate.md` to make a hash match.

Then confirm a worker is actually available:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers check "$(python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers list --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["default"])')"
```

`fail` means the backend binary is missing — stop and route to `/gatekit:setup`.
`unverified` is not a blocker; say so once and continue.

## Step 2 — start the job

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs start
```

Add `--tasks <ids>` when `$ARGUMENTS` named specific tasks, `--backend <name>`
when the user asked for one. Read `max_retries` and `parallel` from
`.gatekit/config.json`; do not pass `--parallel` unless the user asked.

The command prints one row per task. Record the job id.

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

Terminal states are `passed`, `failed`, `timeout` and `redelegated`.

## Step 4 — redelegate failures

For every task in `failed` or `timeout`:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs redelegate <task_id>
```

This archives the attempt under `attempt-N/`, appends the failed gate's output
to the prompt and re-runs. Exit code 3 means the task is out of retries
(`build.max_retries`); do not retry past it.

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

When every task is terminal, write `spec/PROGRESS.md` in `output_lang`:

- the job id and its backend,
- one line per task: id, final state, gates passed of total,
- tasks left blocked, with the failing gate named,
- the timestamp.

Report the same table in chat. State verdicts as they are. A `timeout` is not a
pass, and a task whose gates never ran is `unverified`, not done.

## Step 6 — hand off

If every task is `passed`, tell the user to run `/gatekit:verify` and stop.
Build passing is not the same as the completion contract passing; only
`/gatekit:verify` reports that, and it uses an evaluator that did not write the
code.

If any task is blocked, say so plainly and do not hand off.

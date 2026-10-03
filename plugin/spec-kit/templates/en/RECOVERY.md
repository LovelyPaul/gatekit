---
title: "{{project_name}} — recovery procedure"
date: "{{date}}"
status: "draft"
---

# {{project_name}} — recovery procedure

What to do when the build fails. This document exists so that fixing is not
improvised.

## Diagnosis loop

One step at a time, in order. Do not skip ahead.

1. **Record the symptom verbatim.** Failing criterion id, exit code, last five
   lines of stderr. Observations only, no interpretation.
2. **State one hypothesis.** A single sentence about what is wrong.
3. **Decide what would falsify it.** If the hypothesis is wrong, what would you
   see instead?
4. **Observe.** Logs, a test, a minimal reproduction. If the hypothesis does
   not survive, return to step 2.
5. **Make the smallest fix.** Change one cause. Changing several at once makes
   it impossible to know which one mattered.
6. **Re-run the same criterion.** `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract run`.

## Retry limit

| Subject | Limit | On exceeding it |
|---|---|---|
| Consecutive failures of one task | 3 (the first attempt plus `build.max_retries` retries, default 2) | `jobs redelegate` and `jobs complete` refuse a fourth attempt with exit 3; `jobs start` already refuses a task with 2. Stop and report to a human. |
| The same failure twice in a row | 2 | Exit 3 even with retries left: identical gate output means retrying unchanged will not converge. Decide whether the gate or the instruction is wrong. |
| Stop-hook blocks | 3 | Release the block and record `final_verdict`; for a finished job the hook then stands down until `/gatekit:build` or `/gatekit:verify`. A job left with tasks `queued` is never finished, so the hook judges every turn: end it with `jobs stop`. Never loop forever. |
| Re-testing the same hypothesis | 1 | If the same hypothesis fails twice, change the hypothesis. |

The counts follow the task across jobs and are kept in `.gatekit/attempts.json`;
`build.max_retries: 0` turns both task limits off. Once the cause is fixed,
`jobs start --force-retry <task_id>` clears that task's count.

Hitting a limit means the diagnosis is wrong. The answer is to redefine the
problem, not to try harder. The report must say what was attempted and why each
attempt failed.

## Scope lock

- Do not widen `write_scope` while fixing a failure. If the cause lies outside
  the scope, report that and re-split the task instead of expanding.
- Do not delete or `skip` a failing test.
- Do not weaken a criterion in `spec/05-gate.md`. If a criterion is wrong, a
  human must approve the replacement.
- Do not slip unrelated refactoring into a fix.

## Rollback procedure

1. Preserve the current attempt under
   `.gatekit/jobs/<job_id>/tasks/<id>/attempt-N/`.
2. Return the files in the task scope to the last state that passed its gates:
   `git restore -- <write_scope paths>` or `git checkout <sha> -- <paths>`.
3. Add one row to the "Failed attempts" table in `PROGRESS.md`.
4. Re-run the gates to confirm the restored state actually passes. Do not move
   to the next task without that confirmation.

If there is no point to roll back to (no commit), stop and report to a human
rather than improvising a revert.

---
name: verify
description: Verify the build against the completion contract with an independent evaluator — a read-only agent runs the criteria and the E2E steps, then the main session re-runs the contract and reports per-criterion verdicts.
argument-hint: "[optional: criterion id to focus on]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent
---

# /gatekit:verify

Input: `$ARGUMENTS` — optional criterion id to focus the report on.

**Producer ≠ evaluator.** The session that built the code does not get to grade
it. This command spawns a separate evaluator agent that may read and run but not
write, and only then reports. Do not shortcut it by running the checks yourself
and calling that verification.

## Step 0 — load policy and language

1. Read `${CLAUDE_PLUGIN_ROOT}/policy/verification.md` and
   `${CLAUDE_PLUGIN_ROOT}/policy/language.md`.
2. Detect the language and call it `output_lang`:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "$(head -40 spec/01-prd.md)"
```

## Step 1 — preconditions

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract derive
```

Re-derive first: the contract must match the current `spec/05-gate.md`, or every
run comes back `unverified` with `contract_stale`. If `spec/05-gate.md` is
missing, stop and route the user to `/gatekit:gate`.

## Step 2 — run the evaluator

Read who grades — the `evaluator` field of:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers list --json
```

It is `agent` unless the user ran `workers set-evaluator <backend>`.

**If the evaluator is a backend name** (set with `workers set-evaluator
<name>`), the grader is a separate CLI, possibly a different model, running
with that backend's `read_only_argv`. Write the bullet list below (from "You
are the evaluator" onward, in `output_lang`, leaving out the one bullet that
starts "Record the result under" — a CLI evaluator cannot write) to
`.gatekit/evaluator-prompt.md`, then run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs evaluate --prompt .gatekit/evaluator-prompt.md --lang <output_lang>
```

It prints the evaluator's reply tail (the verdict table) and its state.
`failed` or `timeout` means the evaluator did not finish; that is
`unverified` for every criterion, never a pass. Then continue at Step 3 and
write `spec/PROGRESS.md` yourself in Step 5.

**If the evaluator is `agent`**, spawn one Agent. Its prompt **must** contain
this fence verbatim — the spawn gate parses it as JSON and denies the spawn
without it:

````
```gatekit-scope
{"write_scope": "read-only", "stop_when": "every criterion in .gatekit/contract.json and every E2E step in spec/05-gate.md has a verdict", "tools": ["Read", "Grep", "Glob", "Bash"]}
```
````

The rest of the evaluator's prompt says, in `output_lang`:

- You are the evaluator. You did not write this code and you must not change it.
- Run `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract run --json` from the project root.
- Read `spec/05-gate.md` and carry out every E2E step it describes by hand,
  in order. Record what you actually observed, not what should happen.
- For each criterion and each E2E step, give one verdict from
  `ok / warn / fail / unverified`. A step you could not run is `unverified`;
  never round it to either side.
- Do not fix anything you find. Report it.
- Record the result under the **last-verification heading that already exists**
  in `spec/PROGRESS.md` (`## 마지막 검증` in Korean, `## Last verification` in
  English). Do not add a heading in another language — `spec validate` treats
  that as cross-language residue and fails. If the file or the heading is
  missing, copy
  `${CLAUDE_PLUGIN_ROOT}/spec-kit/templates/<output_lang>/PROGRESS.md` first.
  Write the timestamp, the aggregate verdict, and one line per criterion and per
  E2E step. This file is the one exception to read-only; nothing else may be
  written.
- Reply with the verdict table only. Do not paste command transcripts.

## Step 3 — re-run the contract yourself

After the evaluator returns:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract run --json
```

Run it once, in the main session. Two independent runs that disagree is itself a
finding — report the disagreement rather than picking the better result.

## Step 4 — report

Report in `output_lang`, in this order:

1. The aggregate verdict.
2. One row per criterion: id, verdict, and for anything not `ok` the reason and
   the tail of its output. Focus on `$ARGUMENTS` if one was given, but list all.
3. One row per E2E step from the evaluator.
4. Any disagreement between the evaluator's run and yours.

Rules for the report:

- `unverified` stays `unverified` everywhere it appears. A criterion that timed
  out, a step nobody could run, a missing artifact that could not be checked —
  none of these are passes and none are failures.
- Never restate a worker's or the evaluator's claim of success as a verdict. The
  contract run decides.
- If the aggregate is `ok`, say the contract passes and name the commit or the
  working tree it passed against.
- If it is anything else, list what would have to change, and stop. Do not fix
  the code here; route failures back through `/gatekit:build`.

## Step 5 — leave the trail

Confirm `spec/PROGRESS.md` carries the evaluator's result under the
last-verification heading for `output_lang`. If the evaluator could not write
it, write it yourself from its reply and say that you did. Then run
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate` and fix any
PROGRESS.md finding before reporting.

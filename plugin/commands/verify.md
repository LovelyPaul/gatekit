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
missing, stop and route the user to `/gatekit:gate`. The contract can also go
stale because a design input changed (`02-screens.md`, `02-design.md`, or
`tokens.json`); `contract status` names which file changed. The fix is the
same either way: `/gatekit:tasks` then `/gatekit:gate`.

## Step 2 — run the evaluator

Read who grades — the `evaluator` field of:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers list --json
```

Unless the user set one explicitly, this resolves to an enabled backend whose
name differs from the host, so the grader is not the model that wrote the code
(ADR-0013). When no such backend exists it falls back to `agent` and the JSON
carries `evaluator_warning` — **report that warning to the user**: it means the
producer is grading itself, which is what this command exists to prevent. The
fix is `/gatekit:setup codex`.

**If the evaluator is a backend name**, the grader is a separate CLI, a
different model, running read-only against source (`write.py` refuses inside
its session either way). Write the bullet list below (from "You
are the evaluator" onward, in `output_lang`, leaving out the one bullet that
starts "Record the result under" — a CLI evaluator cannot write) to
`.gatekit/evaluator-prompt.md`, then run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs evaluate --prompt .gatekit/evaluator-prompt.md --lang <output_lang>
```

**For a Codex evaluator specifically** (ADR-0015): `--sandbox read-only`
blocks more than source edits — Vitest's config cache, Playwright's
`test-results/` — so most criteria would read `unverified` for a reason
unrelated to the code. `evaluate` runs Codex with `--sandbox workspace-write`
instead, relying on the write gate as the real protection, but only once this
project's Codex hooks are actually trusted. If they are not, `evaluate`
refuses with `EvaluatorSandboxError` naming the exact fix — **show that
message to the user verbatim**; do not retry with `--force-read-only-evaluator`
on their behalf, since that silently trades the fix for an honest-but-mostly-
`unverified` report.

It prints the evaluator's reply tail (the verdict table) and its state.
`failed` or `timeout` means the evaluator did not finish; that is
`unverified` for every criterion, never a pass. Then continue at Step 3 and
write `spec/PROGRESS.md` yourself in Step 5.

**Screenshot judging (decision 9) depends on the evaluator backend actually
being able to read an image file**, which not every CLI backend supports
the same way an `agent` evaluator (a multimodal model reading via `Read`)
does. If the configured backend's documentation does not confirm image
input, treat every `-visual` verdict from it as `unverified` rather than
trusting a text-only guess about an image it could not actually see.

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
- **For each screenshot criterion that came back `ok`** (ADR-0017 decision
  9 — its `artifacts` entry is a `spec/design/build-<task-id>.png`), read
  that image file and judge it, in addition to the criterion's own pass:
  does it match the design direction on record (a chosen preset, or a
  pattern in `spec/02-design.md`)? Does it show any pattern listed in
  `${CLAUDE_PLUGIN_ROOT}/spec-kit/design-antipatterns.json` (an unstated
  purple-to-blue gradient hero, one sans-serif used for every text role, a
  page of identical cards, decorative emoji standing in for icons,
  centered-everything with no deliberate asymmetry)? Report this as its own
  verdict, on a criterion id suffixed `-visual` (e.g.
  `task-one-screenshot-visual`), separate from the capture criterion's own
  `ok`/`fail` — the screenshot existing and the screenshot looking right
  are two different facts. If you cannot open or read the image, that
  verdict is `unverified`, not a silent skip.
- Do not fix anything you find. Report it.
- Record the result under the **last-verification heading that already exists**
  in `spec/PROGRESS.md` (`## 마지막 검증` in Korean, `## Last verification` in
  English). Do not add a heading in another language — `spec validate` treats
  that as cross-language residue and fails. If the file or the heading is
  missing, copy
  `${CLAUDE_PLUGIN_ROOT}/spec-kit/templates/<output_lang>/PROGRESS.md` first,
  filling its YAML frontmatter block (`title`/`date`/`status`) along with the
  rest of the placeholders.
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

1. The aggregate verdict (code criteria only — see the note below on why
   this cannot include `-visual` verdicts).
2. One row per criterion: id, verdict, and for anything not `ok` the reason and
   the tail of its output. Focus on `$ARGUMENTS` if one was given, but list all.
3. One row per E2E step from the evaluator.
4. **One row per `-visual` verdict, reported with the same weight as any
   other criterion, never folded silently into the aggregate or omitted
   because the aggregate already said `ok`.**
5. Any disagreement between the evaluator's run and yours.

Rules for the report:

- `unverified` stays `unverified` everywhere it appears. A criterion that timed
  out, a step nobody could run, a missing artifact that could not be checked —
  none of these are passes and none are failures.
- Never restate a worker's or the evaluator's claim of success as a verdict. The
  contract run decides.
- **The `contract run` aggregate (`ok`/`fail`/`unverified`) only ever counts
  code criteria — it has no way to see a `-visual` verdict, since that comes
  from the evaluator reading an image, not from running a command.** Never
  report "the contract passes" on the strength of the aggregate alone while
  any `-visual` verdict reads `fail`. Check both: if the aggregate is `ok`
  **and** every `-visual` verdict is `ok` or `unverified` (never `fail`),
  say the contract passes and name the commit or the working tree it passed
  against. If the aggregate is `ok` but a `-visual` verdict is `fail`, say
  so explicitly and plainly — do not let a clean aggregate imply the build
  is done when a screenshot criterion's own visual judgement says otherwise.
- If the aggregate is anything else, or any `-visual` verdict is `fail`,
  list what would have to change, and stop. Do not fix the code here; route
  failures back through `/gatekit:build`.

## Step 5 — leave the trail

Confirm `spec/PROGRESS.md` carries the evaluator's result under the
last-verification heading for `output_lang`. If the evaluator could not write
it, write it yourself from its reply and say that you did. Then run
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate` and fix any
PROGRESS.md finding before reporting.

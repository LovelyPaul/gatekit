---
name: gate
description: Derive executable completion criteria into spec/05-gate.md, show them for approval, and on approval pin the hash so the build gate opens.
argument-hint: "[optional: extra criteria to include]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# /gatekit:gate

Input: `$ARGUMENTS` — optional additional criteria the user wants enforced.

## Step 0 — load policy and language

1. Read `${CLAUDE_PLUGIN_ROOT}/policy/language.md` and
   `${CLAUDE_PLUGIN_ROOT}/policy/verification.md`.
2. Detect the language:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "$(head -40 spec/01-prd.md)"
```

Call it `output_lang`.

3. Read `${CLAUDE_PLUGIN_ROOT}/spec-kit/heading-map.json` and
   `${CLAUDE_PLUGIN_ROOT}/spec-kit/templates/<output_lang>/05-gate.md`.

## Step 1 — read the inputs

Read the acceptance criteria in `spec/01-prd.md` and every task in
`spec/04-tasks.md`. Both files must exist; if `04-tasks.md` is missing, stop and
send the user to `/gatekit:tasks`.

## Step 2 — derive criteria

When writing `spec/05-gate.md`, fill its YAML frontmatter block (`title`/
`date`/`status`) at the top along with the rest of the template.

**Read `${CLAUDE_PLUGIN_ROOT}/spec-kit/gate-criteria.md` and follow it.** It
covers deriving by runner invocation rather than by task (ADR-0020), the
fence fields and their requirements, measuring before declaring a budget,
booting the app once, the single screenshot criterion (ADR-0017 decision
9), and why every criterion must run here before it is written in.

## Step 3 — write the "not counted as done" section

This section is the point of the file. Write the conditions that make a
plausible-looking pass invalid, at minimum:

- tests passing because they were skipped, disabled, or narrowed — and where
  the runner prints skips, make that a criterion with `stdout_not_contains`
  rather than only a sentence here
- a criterion that timed out, which is `unverified` and never a pass
- a command exiting 0 with its declared artifact absent
- a UI task's screenshot criterion coming back `unverified` (no browser, no
  E2E runner) being reported as if the screen were confirmed working — it
  means nobody, human or evaluator, has actually looked at it yet
- **a feature whose own tests pass while nothing on a real screen reaches
  it.** A real trial shipped three features this way: each had passing
  tests and none was wired into the page. So for a UI-bearing project,
  cover the wiring itself with at least one criterion that drives the app
  end to end — open the screen, act on it, assert the result — rather than
  trusting per-feature tests to imply it
- TODOs, stubs, or empty implementations left behind
- editing this file to remove a failing criterion
- reporting success without having run anything

Add project-specific ones from the constraints in `spec/03-architecture.md`.

## Step 4 — validate and derive the contract

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate --json
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract derive
```

`spec validate` must not be `fail` before you continue. `contract derive` writes `.gatekit/contract.json` with the source hash of `05-gate.md`.

Then run every criterion once against the current tree (ADR-0022). Skip this
only if you already ran it while measuring the budget and changed nothing but
the `gatekit-budget` fence since:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract baseline
```

It prints one line per criterion: `already_passes`, `not_yet_runnable` (a
missing path some task writes), `fails`, `command_error` or `unverified`
(including "ran no tests"), and writes `.gatekit/baseline.json`. Exit 4 means
a `command_error`: fix that criterion and re-run Step 4 before asking for
approval. Everything else is information for the user, not a block.

## Step 5 — show the criteria

Present every criterion to the user in `output_lang`, as a table: id, what it
proves, the exact command, and its baseline class. Flag each `already_passes`
as "passes before any work — confirm it tests new behaviour". Then state
plainly what approval changes:

> Approving pins the hash of this file. From that point the write gate stops
> blocking edits outside `spec/`, so source files can be written. The Stop hook
> will run these commands and block completion while any of them fails or comes
> back unverified. Editing this file afterwards expires the approval.

## Step 6 — approve

One `AskUserQuestion` in `output_lang`, with options: approve as written,
revise a named criterion, or add a criterion. On revise or add, apply the
change, re-run Step 4, and ask again.

On approve:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve spec/05-gate.md
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve check spec/05-gate.md
```

The check must print `ok`. Never edit the file to make a hash match.

## Step 7 — report

In `output_lang`: (1) the file path and the number of criteria; (2) the
`spec validate` and `approve check` results, quoted from the runs; (3) that
the write gate now allows source edits outside `spec/`; (4) that any later
edit to `05-gate.md` expires the approval and requires re-approval plus
`contract derive`; (5) the next command, `/gatekit:build`.

If the user did not approve, say so explicitly and state that the write gate
remains closed. Do not approve on their behalf.

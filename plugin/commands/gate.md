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

One criterion per acceptance criterion in 01, plus one per task in 04 whose
completion is not already covered. Each is a ` ```gatekit-criterion ` fence:

```json
{"id": "task-one-works", "argv": ["python3", "-m", "unittest", "discover", "-k", "task_one"],
 "expect": {"exit": 0}, "timeout_s": 30, "artifacts": []}
```

Requirements:

- `id` unique, and containing the task id it verifies so traceability holds
- `argv` a non-empty list of strings, run without a shell — no `&&`, no pipes,
  no redirection. Chain steps by adding more criteria instead.
- `timeout_s` realistic; the total budget across all criteria is 45 seconds
- `artifacts` only for files the command genuinely produces. A declared
  artifact that does not appear is a `fail`, so do not declare aspirational ones.

Every criterion must be **runnable in this repository right now**. Run each one
before writing it in. A criterion you have not executed is a guess, and the
Stop hook will execute it for real.

## Step 3 — write the "not counted as done" section

This section is the point of the file. Write the conditions that make a
plausible-looking pass invalid, at minimum:

- tests passing because they were skipped, disabled, or narrowed
- a criterion that timed out, which is `unverified` and never a pass
- a command exiting 0 with its declared artifact absent
- TODOs, stubs, or empty implementations left behind
- editing this file to remove a failing criterion
- reporting success without having run anything

Add project-specific ones from the constraints in `spec/03-architecture.md`.

## Step 4 — validate and derive the contract

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate --json
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract derive
```

`spec validate` must not be `fail` before you continue. `contract derive`
writes `.gatekit/contract.json` with the source hash of `05-gate.md`.

## Step 5 — show the criteria

Present every criterion to the user in `output_lang`, as a table: id, what it
proves, the exact command. Then state plainly what approval changes:

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

In `output_lang`:

1. The file path and the number of criteria.
2. The `spec validate` and `approve check` results, quoted from the runs.
3. That the write gate now allows source edits outside `spec/`.
4. That any later edit to `05-gate.md` expires the approval and requires
   re-approval plus `contract derive`.
5. Next command: `/gatekit:build`.

If the user did not approve, say so explicitly and state that the write gate
remains closed. Do not approve on their behalf.

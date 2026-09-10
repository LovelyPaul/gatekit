---
name: tasks
description: Derive vertical-slice tasks from the spec into spec/04-tasks.md as gatekit-task fences, with non-overlapping write scopes and at least one gate each.
argument-hint: "[optional: constraints, e.g. 'round 1 only' or 'backend first']"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# /gatekit:tasks

Input: `$ARGUMENTS` — optional constraints on scope or ordering.

## Step 0 — load policy and language

1. Read `${CLAUDE_PLUGIN_ROOT}/policy/language.md` and
   `${CLAUDE_PLUGIN_ROOT}/policy/verification.md`.
2. Detect the language from `spec/01-prd.md`:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "$(head -40 spec/01-prd.md)"
```

Call it `output_lang`.

3. Read `${CLAUDE_PLUGIN_ROOT}/spec-kit/heading-map.json` and
   `${CLAUDE_PLUGIN_ROOT}/spec-kit/templates/<output_lang>/04-tasks.md`.

## Step 1 — read the inputs

Read `spec/01-prd.md` (features `F<n>`, acceptance criteria, assumption
ledger), `spec/02-screens.md` if it exists (screens `S<n>`, states,
components), and `spec/03-architecture.md` (stack, data model, naming rules,
constraints).

Then look at the actual repository: which directories exist, what the test
command is, how files are currently named. Task write scopes must point at real
paths, and gates must be commands that actually run here.

If `spec/01-prd.md` is missing, stop and tell the user to run
`/gatekit:interview` first. Do not invent requirements.

## Step 2 — cut vertical slices

Each task must deliver something demonstrable end to end: data, logic, and the
surface a user touches, together.

- Correct: "user can submit the form and see the saved value" — touches route,
  handler, storage, and screen.
- Wrong: "create all the database models", "set up the component library".
  Horizontal layers finish without proving anything works.

Sizing: one task is a single focused work session. A task whose instruction
needs more than a paragraph to state is two tasks.

Cover every feature `F<n>` from 01. A feature with no task is a gap; say so
rather than silently dropping it.

## Step 3 — assign write scopes and rounds

`write_scope` is a list of globs, or the string `"read-only"` for tasks that
only investigate.

Rules that `spec validate` enforces:

- ids unique across the file
- `write_scope` non-empty, or exactly `"read-only"`
- every `depends_on` id exists in this file
- **no two tasks in the same round have intersecting write scopes**
- every task has at least one gate

Assign rounds by dependency: a task goes in the first round where all its
dependencies are already done and no sibling in that round shares its files.
When two tasks want the same file, either sequence them into different rounds
or re-cut them so their file boundaries differ. Never widen a scope to make a
collision disappear.

## Step 4 — write gates

Every task carries at least one gate: an argv list, run without a shell, that
fails when the task is not done.

```json
"gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}]
```

The gate must be a command that exists in this repository. Verify it runs
before writing it into the file. A gate that always passes is worse than no
gate, because it manufactures false evidence.

## Step 5 — write spec/04-tasks.md

Fill the template. Headings verbatim from the heading map. Each task is one
` ```gatekit-task ` fence containing a single JSON object. The instruction
field must be self-contained: a worker reads only that string and its scope,
with no access to this conversation.

Fill the execution-order table so a human can see the rounds at a glance.

## Step 6 — validate

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate --json
```

On `fail`, fix the specific finding. Scope collisions are re-cut, never
widened. Malformed JSON is rewritten. Re-run until `ok` or `warn`.

A traceability warning about tasks missing from 05 is expected here; the next
command resolves it.

## Step 7 — report

In `output_lang`:

1. The file path written.
2. Task count and round count, on their own line.
3. The `spec validate` verdict, quoted from the run.
4. Any feature from 01 with no covering task.
5. Next command: `/gatekit:gate`.

Do not run any task. This command only plans them.

---
name: interview
description: Turn a rough idea into spec/01-prd.md and spec/03-architecture.md, draft-first, with every unconfirmed judgement recorded in the assumption ledger.
argument-hint: "[what you want to build, in your own words]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# /gatekit:interview

Input: `$ARGUMENTS` — the user's description of what they want to build.

If `$ARGUMENTS` is empty, or names a product without a real user and their
pain ("a chatbot", "a productivity app"), stop and route the user to
`/gatekit:discover`. This pipeline assumes the problem is already known.

## Step 0 — load policy and language

1. Read `${CLAUDE_PLUGIN_ROOT}/policy/language.md`,
   `${CLAUDE_PLUGIN_ROOT}/policy/questioning.md`, and
   `${CLAUDE_PLUGIN_ROOT}/policy/verification.md`.
2. Detect the output language from the user's own words:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "$ARGUMENTS"
```

Call the result `output_lang`. Every user-facing string below is written in it.
Identifiers are never translated.

3. Read `${CLAUDE_PLUGIN_ROOT}/spec-kit/heading-map.json` and the templates in
   `${CLAUDE_PLUGIN_ROOT}/spec-kit/templates/<output_lang>/`. If no template
   directory matches, use `en` and say so once.

## Step 1 — research before asking

Look at what is already knowable. Do not ask the user for any of it.

- `spec/00-discovery.md` — if it exists, its `gatekit-discovery` fence is the
  primary source of facts. Map it as follows:
  - `user` → the users table's first row; `current_way` → that row's "what
    they do today"; the row's situation and need come from `problem` and the
    last link of `why_chain`. Anything the fence does not say for that row
    is an assumption, not a guess.
  - `frequency_per_month`, `minutes_per_run`, `wait` → rows of the
    current-state table, source "discovery interview", measured on the
    file's written date. `wait` is its own row, never added to minutes.
  - `why_chain`'s last link → the cause in the problem paragraph.
  - `failed_attempts` with result `failed` → non-goals (do not rebuild what
    failed); with result `works-but-costly` → the seed of the first feature.
  - `deadline` → a non-goal bounding scope ("not in this round") when it is
    not "none".
  - Every gate in `unpassed`, and every unconfirmed line under the file's
    last section → an assumption ledger row with an inline marker.
- `spec/` — do 01 or 03 already exist? If so, you are revising, not creating.
- The repository: languages, frameworks, test runner, existing conventions.
- `README*`, `package.json`, `pyproject.toml`, lockfiles, CI config.

Record what you found. These are facts, not assumptions.

## Step 2 — one open probe

**Skip this step entirely when `spec/00-discovery.md` exists.** The discovery
record already holds the answer to any open probe; asking again is the
over-questioning `policy/questioning.md` forbids.

Otherwise ask exactly one open question about past behaviour, in
`output_lang`, as plain chat text (not `AskUserQuestion`). Follow
`policy/questioning.md`.

If the user's text already answers it, or the user gave a stop signal
("알아서 해줘", "you decide"), skip this step entirely.

## Step 3 — draft

Write both files from the templates, filling every placeholder. Do not leave
`{{…}}` markers in the delivered files.

- `spec/01-prd.md` — problem, measured current state, goals, non-goals, users,
  features with `F<n>` ids, acceptance criteria, assumption ledger.
- `spec/03-architecture.md` — stack, data model, identifiers and tokens,
  external integrations, constraints.

Headings must come verbatim from `heading-map.json[<output_lang>]`. Never mix
the two languages' headings in one file.

Every judgement you made without confirmation becomes both an inline marker at
the place it is used and a numbered ledger row:

```
> ⚠️ Assumption 2: {{what you assumed}}
```

Numbers must match one-to-one between markers and rows. Measured values you do
not have are written as "not measured" plus a ledger row, never invented.

## Step 4 — validate

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate --json
```

If the verdict is `fail`: read the findings, **discard the failing file and
rewrite it** from the template. Do not hand the user a file that fails
validation, and do not patch around a finding you do not understand. Re-run
until the verdict is `ok` or `warn`, or until three rewrites have failed — then
stop and report exactly which findings remain.

Findings for files that do not exist yet (02, 04, 05, RECOVERY, PROGRESS) are
expected `warn` at this stage. Do not create those files here.

## Step 5 — decisions only

At most **two** `AskUserQuestion` calls, four options each, labels and
descriptions in `output_lang`. Ask only about decisions the user alone owns:
the priority among goals, a trade-off with real consequences, or which
assumption is most likely wrong.

Skip this step entirely after a stop signal.

## Step 6 — confirm

One final `AskUserQuestion`: does the draft match what they meant? Offer
approve, revise a named section, or start over. Apply the answer.

## Step 7 — report

In `output_lang`, in this order:

1. The two file paths written.
2. The `spec validate` verdict, quoted from the actual run.
3. The residual assumptions as a numbered list matching the ledger, each with
   its impact if wrong.
4. The next command: `/gatekit:mockup` if there is a design to read, otherwise
   `/gatekit:tasks`.

Do not claim the spec is correct. Claim only that it validates and that these
assumptions are open.

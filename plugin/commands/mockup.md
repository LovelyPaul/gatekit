---
name: mockup
description: Read a Figma file, HTML, or screenshots and derive spec/02-screens.md plus spec/tokens.json, recording every screen state the mockup does not evidence as an assumption.
argument-hint: "[Figma URL | path to HTML | path to screenshots]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, mcp__figma__get_design_context, mcp__figma__get_variable_defs, mcp__figma__get_screenshot, mcp__figma__get_metadata
---

# /gatekit:mockup

Input: `$ARGUMENTS` — a Figma URL, one or more HTML files, or screenshot paths.

## Step 0 — load policy and language

1. Read `${CLAUDE_PLUGIN_ROOT}/policy/language.md`,
   `${CLAUDE_PLUGIN_ROOT}/policy/questioning.md`, and
   `${CLAUDE_PLUGIN_ROOT}/policy/verification.md`.
2. Detect the language:

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "$ARGUMENTS"
```

If `$ARGUMENTS` is only a URL or a path, detect from the user's surrounding
message instead. Call the result `output_lang`.

3. Read `${CLAUDE_PLUGIN_ROOT}/spec-kit/heading-map.json` and
   `${CLAUDE_PLUGIN_ROOT}/spec-kit/templates/<output_lang>/02-screens.md`.

## Step 1 — read the source deterministically

Pick the branch that matches the input. Extract; do not imagine.

**Figma URL** — if the Figma MCP tools are available:
`get_metadata` for the frame tree, `get_design_context` for structure and
component names, `get_variable_defs` for tokens, `get_screenshot` when a visual
check is needed. If the tools are unavailable, say so plainly, ask the user for
an export or screenshots, and stop. Do not guess a design from a URL.

**HTML files** — Read each file. Extract routes or page boundaries, repeated
class or component patterns, and CSS custom properties for tokens.

**Screenshots** — Read each image. Name each screen after what it shows, and
record which file each observation came from.

Every extracted item carries its evidence: the frame name, file path, or
selector it came from.

## Step 2 — write spec/02-screens.md

Fill the template. Headings verbatim from `heading-map.json[<output_lang>]`.

- **Screen list** — one row per screen with an `S<n>` id and its evidence.
- **Screen flow** — transitions the mockup actually shows. A transition you
  inferred is an assumption, marked as such in the evidence column.
- **Per-screen states** — every screen lists normal, empty, error, and loading.
  Mockups almost never show all four. Design the missing ones, write them out,
  and mark each one assumed.
- **Components** — name, screens used on, variants, source component name.
- **Design tokens** — a summary table only.
- **Negative space** — what the mockup does **not** cover. If this list is
  empty, you did not read closely enough. Look for: offline, permissions,
  long lists, long strings, error recovery, first-run.

## Step 3 — write spec/tokens.json

Machine-readable values, grouped by kind:

```json
{"version": 1, "source": "<figma url or file path>",
 "color": {"primary": "#000000"}, "space": {"md": "16px"},
 "font": {"body": {"size": "16px", "line_height": 1.5}}}
```

Token names are identifiers: keep them as the design system spells them. Omit a
group entirely rather than inventing values for it.

## Step 4 — push gaps into the assumption ledger

Every state, flow, or component **not** evidenced by the mockup becomes a row in
the assumption ledger of `spec/01-prd.md`, plus an inline marker in
`02-screens.md` where it is used.

- If `spec/01-prd.md` exists, append rows continuing the existing numbering.
- If it does not exist, create it from the template in draft mode: fill the
  headings, mark unknown sections "not yet interviewed", and record the gaps.
  Then tell the user to run `/gatekit:interview` to complete it.

Inline marker numbers and ledger row numbers must match exactly.

## Step 5 — validate

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate --json
```

On `fail`, rewrite the offending file from the template rather than patching.
Never deliver a failing file. Missing 03, 04, 05 are expected `warn` here.

## Step 6 — ask only about gaps

At most **one** `AskUserQuestion` call, four options, in `output_lang`. Use it
for the single gap where guessing wrong would cost the most, usually an error
or empty state with a real branch behind it.

Skip it after a stop signal.

## Step 7 — report

In `output_lang`:

1. Files written, with paths.
2. Screens and states extracted, as counts on their own line.
3. The `spec validate` verdict quoted from the run.
4. The negative-space list.
5. The new assumption rows by number.
6. Next command: `/gatekit:interview` if 01 is still a draft, otherwise
   `/gatekit:tasks`.

State what the mockup showed and what you filled in. Never present a designed
state as an observed one.

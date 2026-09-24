---
name: mockup
description: Read a Figma file, HTML, or screenshots and derive spec/02-screens.md plus spec/tokens.json, recording every screen state the mockup does not evidence as an assumption.
argument-hint: "[Figma URL | path to HTML | path to screenshots]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, mcp__figma__get_design_context, mcp__figma__get_variable_defs, mcp__figma__get_screenshot, mcp__figma__get_metadata
---

# /gatekit:mockup

Input: `$ARGUMENTS` — a Figma URL, one or more HTML files, or screenshot paths.

`spec/tokens.json` is shared with `/gatekit:design`: either command may
create it, and both merge into it rather than overwriting.

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

## Step 1 — re-entry check

If `spec/02-screens.md` or `spec/tokens.json` already exists, you are
**revising**, not creating: keep every existing `S<n>` id stable, add new
rows rather than overwriting, and when a new source contradicts an existing
row, do not delete it — append a new row whose evidence reads
`supersedes A<n>: <source>` in the assumption ledger, and note the
supersession next to the row it replaces.

## Step 1.5 — force the source-or-new choice, every run

**ADR-0017 decision 3.** Never infer "no design source" from `$ARGUMENTS`
being empty. Ask explicitly, every time this command runs, regardless of
`$ARGUMENTS`:

- **`$ARGUMENTS` already names a Figma URL, HTML files, or screenshot
  paths** — confirm briefly, in `output_lang`, rather than skipping the
  question outright: "이 소스로 진행할까요, 아니면 새로 디자인을 받을까요?"
  A user who pasted a stale or wrong link should still get the chance to say
  "actually, design something new." A plain-text confirmation is enough
  here; do not spend an `AskUserQuestion` call on a yes/no when the source is
  already in hand.
- **`$ARGUMENTS` is empty** — ask directly, as one `AskUserQuestion`: does a
  design source exist somewhere (a Figma link, screenshots, an HTML export, a
  live site to point at) that was just not attached, or should gatekit
  propose something new. This costs one question on every mockup run,
  deliberately — the point is that "no source" becomes something the user
  said, not something the command assumed from silence.

Answering "I have a source" and then not providing one in the same turn is
treated as a stop signal would be under `policy/questioning.md`: ask once
more for the path or link, and only fall through to the new-design branch
below if the user says there truly is none.

**New-design branch.** List `${CLAUDE_PLUGIN_ROOT}/spec-kit/presets/design/*.json`
for available presets and offer them as the options in one `AskUserQuestion`
(a short description per preset drawn from its own `patterns` — density,
palette warmth, the general feel — not just its filename). Run
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" design merge-preset <name>`
on the pick. If the preset catalog is ever empty (it should not be — see its
own README for the seed/observed distinction), ask the user directly for a
style direction instead (palette warmth, density, a reference product they
like the feel of) as one `AskUserQuestion`, and write their answer straight
into `spec/tokens.json`'s token groups rather than merging a preset — but
this is the fallback of a fallback, not the expected path. Either way, the
chosen direction becomes the input Step 2 below extracts from, in place of a
Figma/HTML/screenshot source — proceed to Step 3 directly with placeholder
screens named from `spec/01-prd.md`'s features, marking every layout
decision as an assumption (Step 5).

## Step 2 — read the source deterministically

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

## Step 3 — write spec/02-screens.md

Fill the template, including its YAML frontmatter block (`title`/`date`/
`status`) at the top. Headings verbatim from `heading-map.json[<output_lang>]`.

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

## Step 4 — write spec/tokens.json

Machine-readable values, grouped by kind. If the file already exists (from a
prior mockup run or from `/gatekit:design`), merge into it rather than
overwriting — add new token names and append to `source` rather than
replacing it:

```json
{"version": 1, "source": "<figma url or file path>",
 "color": {"primary": "#000000"}, "space": {"md": "16px"},
 "font": {"body": {"size": "16px", "line_height": 1.5}}}
```

Token names are identifiers: keep them as the design system spells them. Omit a
group entirely rather than inventing values for it.

## Step 5 — push gaps into the assumption ledger

Every state, flow, or component **not** evidenced by the mockup becomes a row in
the assumption ledger of `spec/01-prd.md`, plus an inline marker in
`02-screens.md` where it is used.

- If `spec/01-prd.md` exists, append rows continuing the existing numbering.
- If it does not exist, create it from the template in draft mode: fill the
  headings, mark unknown sections "not yet interviewed", and record the gaps.
  Then tell the user to run `/gatekit:interview` to complete it.

Inline marker numbers and ledger row numbers must match exactly. A
supersession row from Step 1 is a ledger row like any other.

## Step 6 — validate

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate --json
```

On `fail`, rewrite the offending file from the template rather than patching.
Never deliver a failing file. Missing 03, 04, 05 are expected `warn` here.

## Step 7 — one question: the static preview, or straight to the gap

**One** `AskUserQuestion` call, skipped after a stop signal ("알아서 해줘").
This is independent of the live prototype gate in Step 7b below, which is
never skippable for a UI-bearing project — this question only decides
whether to *also* draw the quick static picture first.

**`$ARGUMENTS` empty, or the new-design branch from Step 1.5 ran** — the
screens were designed, not observed — spend it on the preview (ADR-0011): see
a preview of the screens, or go straight to the live prototype. On a yes, run
Step 7a. **A design source was read** — the screens were observed, so a
drawing adds nothing: spend the call on the single gap where guessing wrong
costs most, usually an error or empty state with a real branch behind it, and
go straight to Step 7b.

## Step 7a — draw, show, correct (only on a yes in Step 7)

Write `spec/design/preview-<project>.html` — one section per `S<n>`, built
from `spec/02-screens.md` (layout, components, the four states) and
`spec/tokens.json` (every value) — and publish it so the user can open it.

- **First visible element is the banner**, in `output_lang`: an approximate
  pattern only, the real build may differ, drawn from the spec rather than
  observed. This is the responsibility boundary, not politeness — the user is
  looking at the *screen spec*, not the product.
- **Static.** A screen's four states are four panels to read, not to click.
- **Tokens only.** Every value comes from `tokens.json` by name; one the
  tokens do not carry is **not invented** but drawn as a labelled placeholder
  naming what is missing. One file, no external requests, no build step.

Then loop until the user is done: show it → they say what to change → **edit
`spec/02-screens.md`**, never only the HTML, since that file is what reaches
the workers → redraw and show again. Nothing is recorded as approved and no
assumption closes; the corrections are the point and they travel in the spec.
Re-run `spec validate` after any edit, and **never cite the preview in an
evidence cell** — it is drawn from this spec, so it cannot be evidence for it
(ADR-0011). When the user is satisfied here, continue to Step 7b — the static
preview does not substitute for it.

## Step 7b — the live prototype gate (ADR-0017 decision 4, not skippable for a UI-bearing project)

`spec validate` refuses `/gatekit:tasks` while this step's confirmation is
missing (the `prototype_required` finding) — this is the direct fix for "기다림
끝에 보여지는 결과는 엉망": the user must see and touch the real shape of the
thing before `/gatekit:build` starts, not after. Skipped entirely when
`spec/01-prd.md` carries the `[non-ui]` marker (a pure CLI or library spec has
nothing to prototype).

1. Build `spec/design/prototype-<project>.html` as **real, clickable HTML and
   CSS** — every named screen `S<n>` reachable through the flow
   `02-screens.md` records, styled from `spec/tokens.json`, all four states
   for each screen present as actually-navigable views (not four static
   panels side by side as in Step 7a — clicking "empty the list" or
   triggering an error must show that state). This is still frontend-only,
   disconnected from any backend: no build has started, the same boundary
   Step 7a's static preview already drew, now expressed as working markup
   instead of a picture. **Fill every screen with realistic sample content,
   not empty inputs or lorem ipsum** — every feature `01-prd.md` lists as an
   `F<n>` should be visibly present and populated with plausible data (a
   character list showing real-looking character names and a last-message
   preview, not three blank cards), so the prototype reads as a finished
   product's actual screen, not a wireframe waiting for content. This is
   the whole point of the prototype gate: the user judges completeness
   against what the finished thing would look like, not against an
   abstraction.
2. Hand it to the user to actually open (a file path today; a
   Claude-in-Chrome-driven walkthrough where that tool is available and the
   user wants it — never the required path, since it adds real per-round
   latency a static file does not have). Ask for feedback as concrete change
   requests against a specific screen and element, not free-form prose about
   the whole app.
3. Apply each revision directly to the HTML/CSS **and** to `02-screens.md`
   (the file `/gatekit:tasks` actually reads — nothing new needed here, this
   is the same write-back path Step 7a's loop already uses), then hand the
   prototype back. Repeat until the user confirms explicitly.
4. **Before asking for final confirmation, ask one explicit question: does
   this prototype fully cover what you want built, or is something still
   missing?** This is not the same question as "does this look right" —
   the prototype is the first time the whole feature set is visible as
   actual screens rather than a list, and a gap that a `01-prd.md` bullet
   list hid can become obvious once it is something to click through. If
   the answer names something missing, treat it as new ground for
   `/gatekit:interview`'s Step 2 conversation: route back there, let the
   feature get defined properly (page, behavior, data — not invented here),
   then return to regenerate this prototype once `01-prd.md` and
   `02-screens.md` reflect it. Do not silently invent the missing feature
   in the HTML to avoid the round trip.
5. On confirmation, append a line to `spec/02-screens.md`, after the
   Negative space section, in the exact form `spec validate` scans for:
   `Prototype confirmed <date>` (or `프로토타입 확정 <date>` in Korean). This
   is prose, not a hash-anchored approval like `05-gate.md`'s — the
   prototype is revised in-loop until confirmed, so there is no single
   moment before that to pin a hash to.

Never treat "the prototype looks finished to me" as confirmation — only the
user's explicit yes, via a closing `AskUserQuestion` ("이대로 확정할까요?" /
"더 수정할 부분이 있어요"), writes the confirmation line.

## Step 8 — report

In `output_lang`:

1. Files written, with paths (the static preview and the live prototype, if
   drawn).
2. Screens and states extracted, as counts on their own line.
3. The `spec validate` verdict quoted from the run.
4. The negative-space list, then the new assumption rows by number.
5. Whether the prototype is confirmed yet, and if not, what is still open.
6. Next command: `/gatekit:interview` if 01 is still a draft, else
   `/gatekit:tasks` — but only once the prototype is confirmed; say so
   plainly if it is not.

State what the mockup showed and what you filled in. Never present a designed
state as an observed one.

## Step 9 — ask what happens next

**ADR-0017 decision 6.** One closing `AskUserQuestion`, in `output_lang`,
after the report. If the prototype from Step 7b is not yet confirmed, "more
work at this step" means continuing that revision loop, not a fresh run of
Step 1 — options: continue revising the prototype (only if unconfirmed),
proceed to the next command named in Step 8 (only once confirmed), or stop
here for now.

- Proceeding: actually invoke the named next command.
- Continuing to revise: return to Step 7b's loop.
- Stopping: confirm what is saved and what remains (prototype confirmation,
  if still open), then end the turn.

---
name: interview
description: Turn a chosen problem into spec/01-prd.md and spec/03-architecture.md through a deep, free-ranging interview on implementation shape — pages, what each page does, what data it needs — laying the groundwork for design and tasks.
argument-hint: "[what you want to build, in your own words]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# /gatekit:interview

Input: `$ARGUMENTS` — the user's description of what they want to build.

If `$ARGUMENTS` is empty, or names a product without a real user and their
pain ("a chatbot", "a productivity app"), stop and route the user to
`/gatekit:discover`. This pipeline assumes the problem is already known.

**The point of this command is not writing a PRD quickly — it is a deep
interview that turns a chosen problem into implementation shape**: how many
pages or screens the thing needs, what each one does, what a user sees and
can act on, what information it needs to work. Design direction (palette,
typography, mood) is deliberately out of scope here — that is
`/gatekit:mockup`'s job, once this command's output gives it something
concrete to design for. **Never say "ADR-0017" or any other internal rule
name to the user** — these are comments in this file for you, not
vocabulary for them.

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

**From `policy/questioning.md`, these apply:** both stop-signal categories
(delegating and exhausted — see `discover.md` for the distinction), and the
guard against asking what is already knowable. The two-call
`AskUserQuestion` budget does **not** apply to the interview conversation
itself (Step 2 below) — see Step 2 for why.

## Step 1 — bring discovery in as given, do not re-ask it

Look at what is already knowable. Do not ask the user for any of it.

**If `spec/00-discovery.md` exists, its `pains` entry marked `chosen: true`
is the starting point of this interview, taken as settled fact — not
re-verified, not re-asked.** Since 2026-09-20, discovery is a free-ranging
conversation summarized post-hoc; read the chosen pain's fields (`summary`,
`user`, `current_way`, `frequency_per_month`, `minutes_per_run`, `why_chain`,
`failed_attempts`) as the problem this interview builds on. **Read `notes`
too, if present — it holds whatever the discovery conversation established
that the named fields have no slot for (success criteria the user stated,
concrete requirements like "여러 캐릭터를 만들 수 있어야 한다").** Treat it
with the same weight as the named fields, not as a footnote: a requirement
recorded there is as settled as one recorded in `current_way`, and Step 2's
own conversation should build on it rather than re-asking something `notes`
already answered. Whatever the chosen pain never established is an open gap
this interview's own conversation (Step 2) can pick up if it turns out to
matter for implementation shape — but the problem itself, why it happens,
and who has it are not re-litigated here.

**Check the verdict gate first.** Run `spec validate` (Step 4 below does
this anyway, but do it now, before the interview starts): if a finding
names `pain_verdict_blocks`, the chosen pain's confirmed verdict is
`eliminate` or `reuse` — **stop before continuing**, tell the user in
`output_lang` which verdict blocked it and why (quoting the
`verdict_suggested.why` that led there), and ask whether they want to pick a
different pain from `00-discovery.md`'s `pains` list instead. Do not
continue from a discovery record whose chosen pain is blocked. A finding
naming `pain_verdict_unconfirmed` (proposed but not user-confirmed) is not
blocking — resolve it early in Step 2's conversation instead of silently
carrying `verdict_suggested` forward as fact.

Also look at:
- `spec/` — do 01 or 03 already exist? If so, you are revising, not creating.
- The repository: languages, frameworks, test runner, existing conventions.
- `README*`, `package.json`, `pyproject.toml`, lockfiles, CI config.

Record what you found. These are facts, not assumptions.

## Step 2 — the interview: one continuous conversation toward implementation shape

**There is no fixed number of questions and no ceiling — the same principle
`discover.md` follows.** This is not a two-call budget of discrete
decisions; it is a conversation that keeps going, one question at a time,
in `output_lang`, plain chat (not `AskUserQuestion`), for as long as it is
still turning up something concrete the design and task-cutting stages will
need and do not have yet.

**Ask one question, then stop and wait for the actual reply
(`policy/questioning.md`).** Sending a question ends your turn — never
invent or imagine the user's answer and continue on your own to a second or
third question in the same turn. Every next question is written only after
a real reply arrives. A run of self-generated questions with no actual
answer in between is not an interview.

**Every message the user sees is either a question or a plain statement in
`output_lang` — nothing else.** No narration of your own process ("Let me
note this," "I'll follow up on that"), no meta-commentary on the answer
just given, nothing between reading an answer and asking the next question
— see `discover.md`'s identical rule, which applies here word for word.

Ask about, in whatever order the conversation actually goes (follow
whatever thread the last answer opened, the same way `discover.md` does —
not a fixed checklist):

- **How many pages or screens does this need**, and what is each one for?
  A todo app might be one page; a multi-role tool might need several. Do
  not assume a number — ask, and let the answer shape everything after it.
- **For each page, what can a user actually do there** — every feature that
  lives on it, described as behavior ("registers a task, sees it appear in
  a list immediately"), not as a UI element name.
- **What does each feature need to work** — what information it reads,
  what it writes, what has to already exist for it to make sense (a user
  needs to exist before a task can belong to them, say).
- **The unglamorous branches**: what happens when a list is empty, an
  action fails, two people try to do the same thing, something the user
  expects to see is missing. These are exactly the kind of question that
  keeps surfacing new ground, not padding.
- **How this specific feature reached the PRD (mapping to behavior)** — for
  each feature that comes out of this conversation, confirm the specific
  translation from "the feature exists" to "here is what happens when
  someone uses it," in the same turn the feature itself comes up, not as a
  separate pass afterward. This is exactly the check a prior real trial
  (`gk-trial2`) skipped: Assumption 4 there recorded that "각 단계를 어떤
  화면 동작으로 옮길지는 인터뷰어가 정했고 사용자가 확인하지 않았다" — the
  interviewer decided a mapping silently and it reached the PRD as fact. A
  mapping that is genuinely obvious from something the user already said
  needs no separate question; one that is not gets however much
  back-and-forth it takes, in the moment it comes up, not deferred to a
  later confirmation pass.

Each question should have a **recommended answer** drawn from what has been
said so far — people correct a wrong guess faster than they fill a blank.
**When more than one plausible scenario exists, list them as a short
numbered set (1/2/3/4, one short phrase each) instead of spelling them out
as rambling prose** — still plain chat, never `AskUserQuestion`. A single
clear guess stays a single sentence. **Whenever you list numbered
branches, always add one final option for "none of these — tell me
directly"**, so a real answer outside the guessed set always has somewhere
to go. **Never precede the question with a preview sentence ("~이
궁금합니다") and then ask the same thing again as the actual question** —
say it once. A question stops being worth asking when the next likely answer
already
appears, in substance, in the last exchange or two (a reworded repeat is
not new information). A stop signal always wins immediately.

**When the conversation stops producing anything new** — no more pages
surfacing, no more unanswered "what does this need," the branches covered —
say so plainly and ask directly, in plain chat: continue the interview
(if something still feels thin), or stop here and write the design
documents now. This is not a routing formality; it is the actual judgement
call this command exists to get right; never predict how much is left
before asking it.

## Step 3 — draft

Once the interview settles (Step 2's own confirmation, not a fixed point),
write both files from the templates, filling every placeholder — including
each file's YAML frontmatter block (`title`/`date`/`status`) at the top. Do
not leave `{{…}}` markers in the delivered files, in the frontmatter or
anywhere else.

- `spec/01-prd.md` — problem, measured current state, goals, non-goals, users,
  features with `F<n>` ids (each one's page and behavior fixed by Step 2's
  conversation, not decided here), acceptance criteria, assumption ledger.
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

**Every ledger row also gets `Blocking` and `Confirmed` (`y`/`n`).** Mark
`Blocking: y` when being wrong about this specific row would directly hurt
how a core feature (an `F<n>`) actually feels to use — not only when it
would sink the entire plan. "Would this make the plan collapse" is too high
a bar and lets exactly the assumptions worth catching slip through as `n`:
a numeric weighting or a display form for a feature's whole point (how
intimacy is computed, how it is shown to the user, for a feature whose
description is literally "친밀도와 말투 변화") is blocking even though the
plan survives being wrong about it — what does not survive is that
feature's actual quality. Things that are genuinely low-cost to be wrong
about (which of three interchangeable sample characters ships first, an
internal file name) stay `Blocking: n`. Every row starts `Confirmed: n`
unless Step 1's or Step 2's
own conversation already established it as fact (in which case it is not an
assumption at all — do not add a row for something you already know). A row
marked `Blocking: y` and left `Confirmed: n` makes `spec validate` fail, not
warn — `/gatekit:gate` will refuse to proceed while it stands, so name the
blocking rows plainly in Step 6's report rather than letting the user
discover the block later.

Since Step 2 already confirms each feature's page/behavior mapping as it
comes up, an assumption row for that mapping should be rare here — its
presence usually means Step 2 moved on before actually confirming something,
which is worth noticing rather than papering over with a ledger row.

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

## Step 5 — confirm the draft

One `AskUserQuestion`: does the draft match what the interview actually
established? Offer approve, revise a named section (returns to Step 2's
conversation on that point, then re-drafts), or start over.

## Step 6 — report

In `output_lang`, in this order:

1. The two file paths written.
2. The `spec validate` verdict, quoted from the actual run.
3. The residual assumptions as a numbered list matching the ledger, each with
   its impact if wrong.
4. The pages/screens the interview settled on and what each one does, as a
   short list — this is the concrete output the next command needs.
5. The next command: `/gatekit:mockup` — to pick or extract a design
   direction for the pages just settled.

Do not claim the spec is correct. Claim only that it validates and that these
assumptions are open.

## Step 7 — ask what happens next

One closing `AskUserQuestion`, in `output_lang`, right after the report —
this is a routing choice after the draft already validated, not an
information-gathering question. Options: proceed to `/gatekit:mockup` now
(to recommend and pick a design direction for the pages just settled),
revise a named section of the draft, or stop here for now.

- Proceeding: actually invoke `/gatekit:mockup`.
- Revising: apply the change, re-run Step 4's validation, and ask this
  question again.
- Stopping: confirm the files are saved and name `/gatekit:mockup` for
  later, then end the turn.

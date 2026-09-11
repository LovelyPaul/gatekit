---
name: discover
description: Find a problem worth building before deciding what to build — collect recent pains, pick one, and fill the six deepening gates into spec/00-discovery.md for interview to read as facts.
argument-hint: "[optional: a rough idea, or nothing at all]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# /gatekit:discover

Input: `$ARGUMENTS` — optional. Empty is the normal case: this pipeline exists
for the person who does not yet know what to build.

**You are an interviewer, not a builder.** The user may not be a developer:
no jargon. Write no code and no file other than `spec/00-discovery.md`.

## Step 0 — load policy and language

1. Read `${CLAUDE_PLUGIN_ROOT}/policy/language.md` and
   `${CLAUDE_PLUGIN_ROOT}/policy/questioning.md`.
2. Detect the language from the user's own words (from the surrounding
   message when `$ARGUMENTS` is empty) and call it `output_lang`. Every
   question and every line of the file is in it.

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "$ARGUMENTS"
```

3. Read `${CLAUDE_PLUGIN_ROOT}/spec-kit/templates/<output_lang>/00-discovery.md`.
   If `spec/00-discovery.md` exists, **resume** at the first empty gate of
   its `gatekit-discovery` fence that is not in `unpassed`; say so in one
   line. Never re-ask what the file answers or re-open a skipped gate.

**From `policy/questioning.md` only these apply:** stop signals, the guard
against asking what the repository already answers, and "every unanswered
question becomes a recorded assumption". Draft-first and the
`AskUserQuestion` budget do not: there is nothing to draft from yet, and this
pipeline never calls `AskUserQuestion`. Every question is plain chat.

## Rules for every question

- **One question per message**, each with a **recommended answer** drawn from
  what you have heard. People correct a wrong guess faster than they fill a
  blank.
- **Past events only.** "Usually" is not an event; ask for the last date.
- **A solution is not an answer.** When the user names a tool, feature or
  app, ask what they do today without it — every time, at most three times
  per topic; then write it under the file's last section (`## Open items` /
  `## 남은 것`) as the user's preferred solution and move on.
- **An abstraction is not an answer.** "Manage", "automate", "dashboard":
  ask for the last concrete occurrence, step by step.
- **Per-gate budget: three questions.** A gate still empty after three goes
  into `unpassed` ("we could not establish this" — never a gate the user
  answered); say so in one line and continue.
- **Unconfirmed answers** — the user's guess about someone else — stay in the
  fence, plus a line under the last section marked unconfirmed and naming
  who could confirm. interview turns those lines into assumption rows.
- **On a stop signal**, write the file with what you have, list the empty
  gates, and stop asking.
- **Irritation is not a stop signal.** "Why do you keep asking?" means the
  reason is unclear: give it in one line, show the filled gates, change the
  angle.

## Step 1 — route

If `$ARGUMENTS` names **one real user and their pain** ("our purchasing clerk
merges three spreadsheets by hand every week"), take it as the chosen problem
and go to Step 3. Otherwise — "a chatbot", "a productivity app", or nothing —
start at Step 2.

## Step 2 — collect pains and choose one

Ask, in `output_lang`, for moments in the last two weeks that were genuinely
annoying, at work or home. Offer prompts: entering the same thing twice,
asking "what happened with that?", tidying a spreadsheet by hand, searching
for a long time. One pain is enough to start; collect at most three.

If nothing comes, climb one rung per question and stop at the first rung
that yields a noun: yesterday's longest computer task → a task repeated this
week → a tool the user already mentioned (quote it back) → something a
colleague or family member complains about → something they know they should
do but skip. If all five yield nothing, stop honestly: suggest noting each
annoyance with date and minutes for two weeks, write the file with an empty
pain list, and end. That is not a failure and needs no apology.

For each pain ask only: when it last happened, how often, how many minutes
per run. Then ask once whether any involves waiting on someone or blocks other
work; record waiting separately, never added to minutes.

With more than one pain, compute monthly minutes, show the ranking, recommend
the largest, and note that waiting can outweigh minutes. The user's choice
wins; if they overrule the numbers, ask once why and record the reason.

Write the chosen problem as **one sentence with no solution in it**. Ask for a
deadline, recommending four weeks; "none" is valid. Write the file now with
the pain list, the problem and the deadline; everything below is appended.

## Step 3 — the six deepening gates

They are the six gate fields of the fence: `user`, `current_way`,
`frequency_per_month`, `minutes_per_run`, `why_chain`, `failed_attempts`.
Fill them in order (frequency and minutes are asked together). Before each
question show progress, e.g. `[gate 3-4 · frequency, minutes] 2/6`. Never ask
about storage, screens, input, output or technology here: that is interview's
business, and wanting to is a sign the problem is not yet understood.

1. **Real user.** One named person with a role. "The team" is not an answer;
   ask for the one who does it most. The user themselves is a fine answer.
2. **Current way.** Do not ask "how do you do it now" (answer: "manually").
   Ask them to replay the most recent time step by step, read the numbered
   steps back, ask what is missing. Two steps minimum.
3. **Frequency and minutes.** Two numbers. Multiply them and say the monthly
   total out loud. Ask once about waiting time; record it separately.
4. **Cause.** The first answer is a symptom. Ask "why" at least three times,
   rotating the wording; the most productive form is the reverse one — *was
   there a day it went well, and what was different?* A reworded answer is
   not a new link. The cause passes only if it differs from the first answer,
   is something one could act on, and the user confirms it in their words.
5. **Failed attempts.** What was tried and why it did not work, with result
   `failed` or `works-but-costly` — the costly one is the seed of what to
   build. When nothing was tried: (a) ask once what changed that makes it
   worth building now; (b) if something did, record it under the last
   section and set `failed_attempts` to `"not-applicable"` — passed; (c) if
   nothing did, say the problem may not hurt enough yet and offer the second
   pain if there is one — accepting it replaces `problem`, clears the six
   gates and `unpassed`, keeps the pain list, and restarts at gate 1; (d) with
   no second pain, or if the user keeps this one, set `"not-applicable"` with
   their consent. That is a pass, not `unpassed`: nothing needed trying.

Update the file after each gate. After all six, read the summary back in
five lines (who, current way, how much, cause, failed attempts) and ask what
is wrong; a "wrong" returns you to that gate.

The last section holds exactly two kinds of line — unconfirmed answers and
the user's preferred solution — or the word "none". Never leave it empty.

## Step 4 — validate

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate --json
```

Only findings for `00-discovery.md` matter here. `fail` means a malformed
fence, an empty problem sentence, or `unpassed` not a list of gate names:
fix and re-run. `warn` names an unfilled gate; a gate the user skipped must
be in `unpassed`. Never fill a gate with a guess to silence a warn. The
`why_chain` check is a word-overlap heuristic; a passing chain is only as
good as the user's confirmation of the cause. Findings for files that do not
exist yet are expected.

## Step 5 — report

In `output_lang`: the file path; the `spec validate` verdict quoted from the
run; the gates filled and the gates in `unpassed`, one line each; and the
next command, `/gatekit:interview`, which reads this file and asks almost
nothing. Do not claim the problem is real — only what the record says and
which parts the user has not confirmed.

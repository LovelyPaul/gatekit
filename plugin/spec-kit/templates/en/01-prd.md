# {{project_name}} — product requirements

Written: {{date}} · Status: draft

## Problem

{{Who is blocked, when, trying to do what. One paragraph. Describe the problem, not the solution.}}

## Current state (measured)

Write what is true today, in numbers. If you do not know, write "not measured"
and add a row to the assumption ledger.

| Metric | Current value | Source | Measured on |
|---|---|---|---|
| {{e.g. time to complete an order}} | {{value or not measured}} | {{logs / interview / estimate}} | {{date}} |

## Goals

- {{A verifiable outcome. Not "faster" but "3 min → under 60 s".}}
- {{Keep this to three or fewer.}}

## Non-goals

- {{Explicitly out of scope for this round. This is what stops scope creep later.}}

## Users

| User | Situation | What they do today | What they need |
|---|---|---|---|
| {{role}} | {{when they reach for this}} | {{current workaround}} | {{unmet need}} |

## Features

Each feature carries an `F<n>` identifier. Tasks (04) and completion criteria
(05) reference these identifiers.

### F1 — {{feature name}}

{{What the user can now do. Describe behaviour, not implementation.}}

### F2 — {{feature name}}

{{…}}

## Acceptance criteria

Every item must be observable. "Works well" is not an acceptance criterion.

- **F1** — Given {{context}}, when {{action}}, then {{observable result}}.
- **F2** — {{…}}

## Assumption ledger

Record every unconfirmed judgement here. Wherever the body of this document
leans on an assumption, leave the blockquote marker below and keep its number
matching a row in this table.

> ⚠️ Assumption 1: {{what you assumed}}

| # | Assumption | Basis | Impact if wrong | How to confirm |
|---|---|---|---|---|
| 1 | {{what you assumed}} | {{why you believed it}} | {{what breaks}} | {{who to ask, how}} |

Rule: inline markers and table rows correspond one-to-one by number. If only
one side exists, `python3 -m gatekit spec validate` reports it. When an
assumption is confirmed, do not delete the row — replace the basis with the
confirmed fact.

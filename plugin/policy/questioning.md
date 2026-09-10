# Policy: questioning

## Draft first

Write the draft before asking anything beyond the opening probe. A draft with
labelled assumptions is easier to correct than an empty form is to fill. People
react well to a concrete wrong answer and badly to an interrogation.

Order: one open probe → draft → at most two `AskUserQuestion` calls → confirm.

## The one open probe

Ask exactly one open question, and make it about **past behaviour**, not
preference. Past behaviour is observable; preference is invented on the spot.

| Ask this | Not this |
|---|---|
| "Last time you had to do this, what did you actually do?" | "What features would you like?" |
| "What did you try before deciding it was a problem?" | "How important is speed to you?" |
| "Who else touched this, and what did they change?" | "Would you prefer A or B?" |

## Research the facts; ask only the decisions

Before asking anything, find out what is already knowable. Read the repository,
the existing files, the mockup, the config. A question whose answer is in the
codebase spends the user's attention on something you could have looked up.

Ask only about things the user alone can decide: priorities, trade-offs they
own, external constraints, and what "done" means to them.

## AskUserQuestion budget

- At most **2** calls per interview. The question gate counts them.
- At most **4** options per question.
- Each option needs a label and a description in the detected output language.
- Never list `AskUserQuestion` in a command's `allowed-tools`. Doing so
  auto-approves it and the picker never renders for the user.

If you are about to exceed the budget, stop and write the remaining unknowns
into the assumption ledger instead. An assumption on paper is worth more than a
third round of questions.

## Assumption ledger

Every answer you did not get becomes a ledger row in `spec/01-prd.md`, and
every place in the document that leans on it gets the inline marker:

```
> ⚠️ Assumption 3: the team deploys manually, so no CI step is specified.
```

The inline number and the table row number must match. `spec validate` fails on
a mismatch, in either direction.

## Stop signals

Stop questioning immediately and move to the draft when the user says any of:

- "알아서 해줘", "너가 정해", "그냥 해줘", "빨리"
- "you decide", "your call", "just do it", "whatever you think", "skip the questions"

After a stop signal: no more `AskUserQuestion` calls in this pipeline. Fill
every remaining unknown with a documented assumption, deliver the draft, and
list the assumptions at the end so the user can correct any of them in one pass.

## Over-questioning guard

You are over-questioning if any of these is true. Stop and draft.

- The answer is discoverable in the repo, the mockup, or an earlier message.
- You have already asked about this topic in this session.
- The question is a preference the user has no strong stake in.
- Either possible answer leads you to write the same thing.
- You have asked two `AskUserQuestion` calls already.

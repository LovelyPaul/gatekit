# ADR-0024: The Stop gate stands down after the build, runs only turn-tier criteria, and keeps a time budget

Status: accepted 2026-10-03 (owner approval in session).

## Context

The `study-gallery` build (gatekit 0.12, 10 tasks under host execution) took
50 minutes. The session then went on for 3 h 47 min after the last task
passed. Session transcripts put 17 minutes of that on model work and 145
minutes (64 %) on running the completion contract:

- The Stop hook ran the full 26-criterion contract 15 times, 348–570 s each;
  the user cancelled 7 of those runs. There were 8 manual `contract run`s on
  top.
- `active_pipeline` stayed `build` for the rest of the session because
  `/gatekit:verify` was never run. Every turn end — pure questions and
  unplanned follow-up feature work alike — re-ran the whole contract.
- Only 3 of the runs blocked. After `MAX_BLOCKS` the gate could no longer
  block but still ran the contract at every turn end.
- While the Stop hook ran (up to 570 s) the user's next message waited in the
  queue. The user ended up asking to delete the hooks.

0.13.0 (ADR-0020) reuses the last result when the tree and contract are
unchanged, and the criteria were consolidated: the contract now takes about
161 s, 135 s of which is `e2e-suite` re-running what the task gates already
passed. But any edit still triggers the full run at the next turn end.

The cause is one rule: "judge at every Stop while `active_pipeline` is
`build`". The pipeline field says which command the user last invoked. It
does not say whether the build is still going on.

Constraints that do not move: `unverified` never rounds to either side;
hooks exit 0 on internal error; standard library only; `contract run` stays
the explicit, always-fresh, full check that `/gatekit:verify` relies on.

## Decision

### 1. The Stop gate stands down once the build has its verdict

While `active_pipeline == build`, the Stop gate judges only while the latest
job is unsettled, and once more after it settles: the handoff check. A job is
**settled** when every task in it is in a terminal state (`passed`, `failed`,
`timeout`, `redelegated`, `stopped`, `blocked`). Redelegating a task archives
the attempt that ended and puts a new attempt of the same task in its place,
in `queued`; that new attempt is not terminal, so the job is unsettled again.

- **No job yet** (the build has not started one): judge every Stop, as
  before.
- **Unsettled job**: judge every Stop, as before. A verdict reached now does
  not stand the gate down.
- **Settled job**: judge as before (block while `fail`/`unverified` and
  `block_count < MAX_BLOCKS`). When a verdict is recorded — the handoff check
  comes back `ok`, or the gate allows after `MAX_BLOCKS` and records
  `final_verdict` — the gate records a **stand-down** for that job and judges
  nothing more. Every later Stop in the session exits 0 at once, without
  running a criterion, while the stand-down applies: same pipeline, same
  latest job, job still settled.
- A job that ends with `failed`/`blocked` tasks therefore behaves as before:
  it is judged and blocked up to `MAX_BLOCKS`, then `final_verdict` is
  recorded, and only then does the gate stand down. The record says the work
  did not pass.
- A new job (a later `jobs start` in the same session), or a redelegated
  task in the stood-down job, means the stand-down no longer applies. The
  gate clears it and judges again.
- `stop_hook_active` still never blocks. An allow made there is a recorded
  verdict only when it is `ok`. Otherwise the first block of every turn would
  stand the gate down after a single retry.

Under `active_pipeline == verify` the rule is the same without the job part.
The gate judges until verify's verdict is recorded (`ok`, or `final_verdict`
after `MAX_BLOCKS`), then stands down.

**Re-arming.** A prompt that invokes `/gatekit:build` or `/gatekit:verify`
(even the same pipeline again) re-arms the gate. The prompt hook resets
`stop` to `{"block_count": 0, "final_verdict": null, "last_reasons": [],
"stood_down": null, "deferred": []}` and records a `stop_rearmed` event.
`/gatekit:doctor` and `/gatekit:setup` still clear the pipeline, which
disarms the gate entirely, as before.

**Record.** The ledger's `stop` object gains `stood_down: null |
{"pipeline", "job_id", "verdict", "at", "skipped"}`. `skipped` counts the
Stops that exited without judging. The transition is logged once as a
`stop_stood_down` event. `doctor`'s project-state axis names a stand-down in
the most recently updated session ledger. While the stand-down applies, the
prompt hook's context line, in `output_lang`, says that follow-up edits are
not gated and that `/gatekit:verify` re-checks the contract. It sits ahead of
the fields that may be cut at 600 characters.

Why this is honest: the gate judges the job it was armed for, and it does
judge it — the handoff check is the same check as before. What it stops doing
is re-judging every unplanned edit after the job's verdict is on record. That
work is outside the job's contract until the user asks for a check again.
`/gatekit:verify` still runs the full contract.

### 2. Criterion tiers: `turn` and `verify`

A `gatekit-criterion` fence may carry `"tier": "turn" | "verify"`. The
default is `"turn"`, so existing contracts behave as before. `spec validate`
fails on any other value, and so does `contract derive`.

- The Stop gate under `build` runs only `turn` criteria. Each `verify`-tier
  criterion is listed in its report as "deferred to /gatekit:verify". It is
  not judged there, never blocks, and is never reported as `ok`.
- The Stop gate under `verify`, `contract run` (and therefore
  `/gatekit:verify`) and `contract baseline` run every tier.
- `execute(..., tiers=...)` returns the ids in scope as `scope` and the
  criteria left out as `deferred: [{"id", "tier", "reason"}]`. These are not
  part of `criteria` and do not count in the aggregate.
- If no criterion is in the selected tier, nothing runs and the result is
  `unverified` with reason `no_criteria_in_tier`. The Stop gate allows,
  records `unverified` (nothing was judged; it is not rounded to `ok`), and
  counts that as the job's recorded verdict for the stand-down. Blocking
  would ask the agent to fix something the Stop gate cannot see.
- Reuse (ADR-0020) is keyed on what was in scope. `runs/contract-last.json`
  records `scope`, the sorted ids the run covered, and the Stop gate reuses a
  record only when that equals the ids its own tier selection covers now. So
  a turn-tier result is never reused as a full-contract result for the verify
  Stop gate, and a full `contract run` result is never reused as a turn-tier
  one, unless the contract has no `verify` criteria and the two scopes are
  the same set. A record without `scope` (written before this ADR) is never
  reused.

Guidance for `/gatekit:gate` (`spec-kit/gate-criteria.md`): a full
regression suite that repeats what the task gates already passed goes in
`verify`. One happy-path journey, the screenshot capture, unit tests,
typecheck and static checks stay `turn`.

### 3. A Stop-gate time budget: `stop.budget_s`

New config key `stop.budget_s`: default 120, at most 570 (the Stop gate's
existing cap below the 600 s hook timeout). `config.stop_budget_s(cfg)`
returns the value in force and a problem string. A non-number, a boolean,
zero or a negative value means the default; above 570 means 570. `doctor`'s
project-state axis reports the problem as `warn`.

The Stop gate under `build` starts no new criterion once `stop.budget_s` has
elapsed since its run began. A criterion it starts in time runs to its own
`timeout_s`, bounded as before by the contract's budget and the 570 s cap, so
the budget is a soft bound on starting, not a kill switch. Criteria it never
started are listed as "deferred: Stop-gate budget". They are not judged and
do not block. They are not judged either, so the run is not `ok` (see the
amendment below). A `fail` among the criteria that ran still blocks. So does an
`unverified` from a criterion that did run: it timed out, ran no tests, or
its grading files changed. When the contract's own budget runs out first,
the next criterion is "budget exhausted" `unverified` as before. That is the
contract's limit, not the Stop gate's.

The Stop gate under `verify`, `contract run` and `contract baseline` take no
Stop budget. Deferred criteria are re-run there under the contract's own
budget.

**Why this does not round `unverified`.** A deferred criterion is not given a
verdict by the Stop gate at all: not `ok`, not `unverified`, not `fail`. It
sits outside the run's `criteria`, and the report lists it by name. A
`verify`-tier deferral stays outside the aggregate: that criterion is
`/gatekit:verify`'s to judge. A budget deferral does not (amendment below):
a run that left a turn-tier criterion unjudged is `unverified`, never `ok`. An `unverified` the
gate did produce (a timeout, a run with no tests) stays `unverified` and
blocks. Before this ADR the same situation, the budget running out, gave
"budget exhausted before this criterion ran" `unverified`, which blocked a
turn over a check nobody had started. That was a correct verdict on the
wrong question. "Has the slow suite passed?" is verify's question, not every
turn end's.

**Order.** Criteria the last recorded run deferred for the budget run first
(amendment below), then the ADR-0020 order: criteria that were `fail` or
`unverified` in the last recorded result, then the rest in declared order. A
slow criterion declared early still costs every Stop its run time, so the
gate guidance says to tier it `verify` or declare it last.

## Amendment (review, 2026-10-03)

A review reproduced holes in the decisions above. The owner approved these
changes.

1. **A budget-cut run is not `ok`.** As first written, a Stop cut by
   `stop.budget_s` aggregated only the criteria that ran. With `slow`
   (passes) then `broken` (exits 1) and a 1 s budget, the handoff check came
   back `ok`, recorded `stood_down.verdict: ok` and never judged `broken`.
   Now `execute` returns `unverified` with the reason
   `deferred_by_stop_budget: <ids>` when everything that ran passed and a
   criterion was deferred for the budget; a `fail` or `unverified` that ran
   keeps its own verdict. The Stop gate allows that run (nothing to fix, so
   no block, and it does not count toward `MAX_BLOCKS`), records
   `unverified` and does **not** stand down — not under `stop_hook_active`,
   not after `MAX_BLOCKS`. The next Stop runs the deferred criteria first,
   and when the tree, contract and no-tests signatures are those of the last
   record, keeps that record's verdicts for criteria it did not reach. Every
   Stop judges at least one criterion the tree has not had judged (the first
   one always starts), so a tree left alone reaches a full turn-tier verdict
   within as many Stops as there are turn-tier criteria, and only then
   stands down. An edit starts the count again; each of those Stops is an
   allow, so it never traps the session. The prompt hook's context line
   names the unjudged ids while they are on record, and the stood-down line
   says what was judged: `turn-tier ok` under `build`, plus `N deferred to
   /gatekit:verify` when the contract has `verify`-tier criteria.
2. **`scope` is what was judged.** `save_last` recorded the tier selection,
   budget-deferred ids included, so the verify-pipeline Stop reused a
   budget-cut build record as a full judgement. `scope` now holds the ids
   actually judged, and a record with any budget deferral is never reused,
   by any caller.
3. **A settled job with unpassed tasks is not a handoff `ok`.** Decision 1
   says such a job is blocked up to `MAX_BLOCKS`, but the gate looked only
   at the contract, so an `ok` contract stood it down as `ok` with a task
   `failed`. The handoff check now reads the job's task states. Any task in
   `failed`, `timeout` or `blocked` blocks, naming the tasks, and counts
   toward `MAX_BLOCKS`; after that `final_verdict` is recorded and the gate
   stands down, as decision 1 says. The verdict is `fail` when a task
   failed, timed out or was stopped, `unverified` when the only unpassed
   tasks are `blocked` (never ran). A task `stopped` by `jobs stop` makes the
   handoff `fail` too but does not block: the job was ended on purpose and
   there is nothing left to run, so the gate records it and stands down. An
   allow under `stop_hook_active` with such tasks is never a recorded
   verdict.

## Consequences

- After a build's handoff check, the rest of the session's turn ends cost
  nothing. The study-gallery session would have run the contract once after
  its last task, not fifteen times.
- Follow-up work in the same session is not contract-gated. The context line
  says so at every prompt, and `/gatekit:verify` (or `/gatekit:build` for a
  new job) arms the gate again. This is a deliberate trade: per-turn
  re-judging of unplanned work cost 64 % of the session and the user's trust
  in the hooks.
- A turn end under `build` costs about `stop.budget_s` plus the last
  criterion's overrun at most. The full regression suite runs in
  `/gatekit:verify`.
- `contract run` output and `baseline.json` are unchanged in shape. Results
  gain `scope` and `deferred`. Each criterion in `contract.json` gains
  `tier`.
- `docs/ARCHITECTURE.md` §3 (stop, prompt), §4 (ledger `stop`), §5 (tier,
  scope, deferred), §9 (`stop.budget_s`), §12 (doctor), §13 (tests) and §14
  (`execute`, `reusable_last`, `config.stop_budget_s`) are updated to match.

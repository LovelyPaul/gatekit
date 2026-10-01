# ADR-0020: The Stop gate reuses a result for an unchanged tree, and criteria share runner invocations

Status: accepted 2026-10-01 (owner approval in session: "응, 1·2번 둘 다 진행해줘").

## Context

A real build (`study-gallery`, Next.js + Supabase, 10 tasks, 26 criteria)
spent most of its wall-clock time waiting on the Stop gate, not building.
From that project's own session ledger and job directory:

- With `active_pipeline: build`, the Stop gate ran the whole contract at the
  end of **every** turn: 9 runs in one session (3 blocks, 6 allows), each up
  to the 570 s cap. Two consecutive one-word turns ("continue") took 8 min
  and 8 min (15:36→15:44, 15:47→15:56 UTC) with nothing changed in between.
- 21 of the 26 criteria were separate `npm run e2e -- <spec>` /
  `npx playwright test -g …` processes. Playwright's `webServer` starts
  `next dev` for each process when none is running, and the dev server
  compiles every page on first request, so every criterion paid a cold
  start. The login spec passed as a task gate in 17 s on a warm server and
  timed out at 90 s as the first criterion of a cold contract run.
- Every spec ran twice (a 360 px and a 1280 px Playwright project).
- On the last block, 9 criteria consumed the whole budget and 17 never ran
  (`budget exhausted before this criterion ran`): ten minutes produced
  mostly `unverified`.

Two things are wrong. The Stop gate re-proves a result it already has when
nothing changed, and `/gatekit:gate` derives one runner process per task
and per screenshot, multiplying the start-up cost by the number of tasks.

Constraints: `unverified` never rounds to a pass; hooks exit 0 on error;
standard library only; `contract run` stays the explicit, always-fresh
check that `/gatekit:verify` and users rely on.

## Decision

1. **Stop gate result reuse.** After each contract run it performs, the
   Stop gate records the result with a fingerprint of the project tree and
   the contract's `source_sha256` in `.gatekit/runs/contract-last.json`.
   At the next Stop, if the contract is unchanged and the current
   fingerprint equals the recorded one, the gate judges that recorded
   result again instead of re-running, and says it reused it. Any change in
   the tree or the contract runs the contract again.
   - The fingerprint hashes `(relative path, size, mtime_ns)` of every file
     under the project root except state and build output that criteria
     themselves rewrite: `.git`, `.gatekit`, `node_modules`, `.next`,
     `.nuxt`, `.svelte-kit`, `.turbo`, `.cache`, `dist`, `build`, `out`,
     `coverage`, `test-results`, `playwright-report`, `__pycache__`,
     `.venv`, `venv`, `*.tsbuildinfo`, `spec/PROGRESS.md`, and every
     artifact path the contract declares. It is taken **after** the run,
     so files a run writes do not invalidate it on their own.
   - Over 20 000 files the fingerprint is not computed and nothing is
     reused: "could not tell" means run again.
   - Only the Stop gate reuses. `gatekit contract run` and `/gatekit:verify`
     always execute.
   - When the gate does run, criteria that were `fail` or `unverified` in
     the recorded result run first, so a budget cut lands on criteria that
     last passed rather than on the ones still being fixed.
   - State outside the tree (a database, a dev server, the network) is not
     fingerprinted. A reused result is evidence about the same code, not a
     fresh observation of external services; the reuse message says when
     it was recorded.

2. **Criteria share runner invocations.** `/gatekit:gate` derives criteria
   by runner invocation, not by task: one criterion runs the whole E2E
   suite once on a single viewport project; the wiring criterion stays one
   criterion; one screenshot criterion captures every UI task's
   `spec/design/build-<task-id>.png` and declares all of them as its
   `artifacts`; static checks (typecheck, TODO scan, tokens) stay as they
   are. Per-spec criteria are kept only where the suite cannot finish
   inside the budget as a whole. Traceability holds because each task id
   still appears in `05-gate.md` (in the screenshot artifact paths and
   the suite criterion's description). The gate command also tells the
   agent to measure one full `contract run` before declaring a budget, and
   to prefer a server that compiles once (`next build && next start`, or a
   dev server started before the run) over one cold `next dev` per
   invocation.

## Consequences

- A turn that changes nothing ends without a contract run; a turn that
  changes code runs it once, failing criteria first.
- A contract for a UI project shrinks from roughly 2N+5 runner processes
  (N tasks) to about four, so the budget covers every criterion.
- Failure messages are coarser: "the suite failed" instead of "this
  task's spec failed". The suite's own output tail names the failing test,
  and per-task task gates (unchanged) still localise failures during the
  build.
- `docs/ARCHITECTURE.md` §3 (stop gate) and `commands/gate.md` are updated.

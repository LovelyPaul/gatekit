# ADR-0023: Notice when the files that grade the work change

Status: accepted 2026-10-03 (owner approval in session).

Origin: a pattern idea from Ouroboros-style self-improving agent loops, where
the loop that is graded can also reach the grader. Only the idea is taken; no
code from any such project (clean-room rule).

## Context

A gate or a completion criterion is a command, and most of them name the file
that does the judging: `python3 -m pytest tests/test_login.py`,
`node --test test/cart.test.js`, `./scripts/e2e.sh`. A worker is allowed to
write inside its `write_scope`, and a task's scope often covers its own tests.
That is on purpose: ADR-0013's recheck flow exists because gates and tests are
refined mid-build, and on the gk-trial2 run most respawns came from a gate that
moved while the code was already right.

The same freedom lets a worker that cannot make a test pass make the test
easier instead: delete an assertion, skip a case, widen a tolerance. The gate
then passes and nothing records that the thing doing the judging changed. The
completion contract has the same exposure after approval: `05-gate.md`'s hash
is pinned, but the spec files its criteria run are not.

The owner was offered four options:

1. **Strict protection**: the write gate refuses edits to grading files that
   existed at approval; changing one needs `05-gate.md` re-approved. Strongest,
   but it breaks ADR-0013 — a refined gate or test mid-build is normal — and
   every such refinement would cost a re-approval round trip.
2. **Lock on pass**: once a task passes, the write gate refuses later edits to
   its grading files. Edits before the pass stay allowed, so it does not catch
   a task loosening its own test on the way to its first pass — the case this
   ADR is about.
3. **Detect and report only**: record grading-file hashes, never block a
   write. A criterion whose grading file changed since approval is withheld as
   `unverified`; a task that passed only after its own grading file changed is
   reported, its verdict kept.
4. **Defer** the step until real builds on 0.14.0 show whether it is needed.

The owner chose 3. For completion criteria the approved file is the
contract, so a change there cannot be a pass; it is reported as `unverified`
(never `fail`, since nothing was shown wrong, and never `ok`). For tasks a
test that was itself wrong is fixed exactly this way, so a refusal would send
a correct task back to a worker; the change is put in front of the reviewer
instead.

## Decision

Amended the same day after review, before 0.15.0 was pushed: decision 1
narrowed (brownfield checks went `unverified`), decision 2 extended
(re-deriving cleared the hold without re-approval), decision 3 moved the
failed hashes to the attempt ledger (a failure in one job and a pass in the
next went unflagged, and preflight failures were never recorded).

### 1. Grading files

For a task gate's or a criterion's `argv`, after `${CLAUDE_PLUGIN_ROOT}`
expansion, a token is a grading file when it names an existing regular file
inside the project root **and** either

- it is argv[0] given as a path (holds a slash), i.e. a script; a bare
  program name (`pytest`, `npm`) is looked up on PATH and never counts; or
- it looks like a test: a directory segment `test`, `tests`, `__tests__`,
  `spec` or `e2e`, or a basename matching `test_*`, `*_test.*`, `*.test.*`,
  `*.spec.*`, `*_spec.*` or `conftest.py` (case-insensitive).

Nothing under a build-output or dependency directory (`node_modules`,
`.venv`, `venv`, `dist`, `build`, `out`, `.next`, `coverage`, `target`,
`__pycache__`) counts, argv[0] included: a build or an install rewrites
those legitimately.

The lists live in `plugin/spec-kit/grading-patterns.json`, beside
`no-tests-signatures.json`, because they are runner conventions that grow
with use and the repo keeps such tables as data (`runcheck.grading_patterns`
reads them; an unreadable file means only argv[0] scripts count). They are
deliberately narrower than `spec.py`'s `_TEST_DIR_SEGMENTS`, which classifies
write scopes and errs toward "test".

Why only these: a brownfield check names the code it inspects —
`grep -q print src/app.py`, `eslint src/x.js`, `node --check src/app.js`,
`tsc src/index.ts`, `sqlite3 app.db`, `test -f dist/index.html`. The build
edits or creates exactly those files, so counting them made honest passes
`unverified`. An interpreter's script (`bash scripts/e2e.sh`,
`python3 src/app.py --selftest`) counts only when it is test-shaped, for the
same reason: `node dist/cli.js` is build output being exercised.

Token handling: options are skipped except the value of `--opt=path`
(`--spec=e2e/login.spec.ts`); a pytest node id counts by its part before
`::`; a trailing pytest `[param]` and a `:<line>` or `:<line>:<col>`
location (vitest, jest) are dropped. The path is resolved like ADR-0022's
missing paths (`runcheck.relativize`): `.`/`..` collapsed, the root
stripped, anything outside the root or still climbing with `..` dropped. The
file's realpath must also stay inside the root's realpath, so a symlink out
does not count. A token that names a directory, a glob, or nothing is not a
grading file.

`runcheck.grading_hashes(argv, root)` returns `{relpath: sha256}` for them,
reading each file in 1 MiB chunks. The cost is hashing the handful of files a
command names, once per run.

**Limitations.** A command that names no file (`npm test`, `pytest` with no
arguments, `make check`) or only a directory or glob (`pytest tests/`,
`vitest 'src/**/*.test.ts'`) has no grading files, and nothing here covers
it. A criterion author who wants the coverage names the spec file in argv
(`npx playwright test e2e/login.spec.ts`).

### 2. Criteria: hashed at derive, pinned at approval, `unverified` on change

`contract derive` records, per criterion, `"grading": {relpath: sha256}` for
the grading files that exist at that moment.

**Approval pins them.** `approve spec/05-gate.md` stores, beside the file
hash in `approvals.json`, `"grading": {criterion id: {relpath: sha256}}`:
taken from `contract.json` when that was derived from the very file being
approved (so the approval covers the contract the user was shown), otherwise
hashed then from the file's criteria. Without this a re-derive after a test
edit recorded the new hashes and the criterion counted as `ok` again with
nobody having approved the change — and `/gatekit:verify` re-derives every
time.

When the contract is executed (`contract run`, the Stop gate, verify's run and
`contract baseline` all go through `contract.execute`):

- If the derived contract no longer records an approved grading file with its
  approved hash (`contract.unapproved_grading`), nothing runs: the result is
  `unverified` with reason `grading_unapproved` and the paths. This is the
  same handling as a stale approval of `05-gate.md`:
  `approve check spec/05-gate.md` prints `fail` and names the paths
  (`approval.check_gate`), the prompt context says `gate approval STALE
  (re-approve)`, and the Stop gate sends the user to `/gatekit:gate`.
  Re-deriving alone does not clear it; re-approving does. Only files that
  existed at approval are compared, so a test written during the build (and
  recorded by verify's re-derive) is not held back. An approval recorded
  without `grading` (before 0.15.0) is judged on the file hash alone, as
  before.
- Otherwise each criterion runs. Afterwards, if any recorded grading file now
  hashes differently or is missing, a result that would be `ok` becomes
  `unverified` with detail `grading file changed since approval (if intended,
  re-run /gatekit:gate to re-approve; otherwise revert it): <paths>` and
  `grading_changed: [paths]`. The instruction comes before the paths because
  a reason line is cut at 120 characters; the Stop gate also adds a hint line
  in `output_lang` naming every path in full. A `fail` stays `fail`; an
  already `unverified` result keeps its own reason. A file that did not exist
  at derive time is not tracked.

**The write gate is untouched.** Its spec-before-code rule keys on the file
hash alone (`approval.check`), so a changed or re-derived grading file never
blocks a write — the owner's choice of option 3.

**A worker never approves.** `approve` refuses (exit 1) when
`GATEKIT_TASK_ID` is set, which every worker and the evaluator have.
`contract derive` stays allowed there; its result is stale until approved.
What remains: the host session itself can still run `approve`. That is the
same trust boundary as approving `05-gate.md` at all, which `gate.md` puts
behind an `AskUserQuestion`; prose is not enforcement, and nothing here
claims otherwise.

The Stop gate's reuse (ADR-0020) does not need a new check: a changed grading
file changes the tree fingerprint, so the old `ok` is not reused. A test pins
this. `contract baseline` runs right after derive, so it sees no change.

### 3. Tasks: "passed only after its own grading file changed"

`run_gates` records, on each gate in `gates.json`, `"grading": {relpath:
sha256}` taken just before that gate runs.

Every path that records a task's gate result (`preflight`; `execute_task`, so
also `redelegate`; `complete_task`; `recheck`) calls
`jobs.note_grading(root, jdir, task_id, gates, passed)`:

- For each gate whose verdict is `fail`, the task's entry in
  `.gatekit/attempts.json` (ADR-0014/0021, under `_ATTEMPTS_LOCK`) gets
  `failed_grading[<gate name>]` set to that gate's hashes: the most recent
  failure of that gate, in any job.
- When the task passes, each gate in `failed_grading` is compared with the
  same gate's hashes now. Any path whose hash differs or that is gone is
  added to this job's `status.json` `grading_changed_after_failure` (a sorted
  list, kept for the rest of the job, carried by `redelegate`), and
  `failed_grading` is cleared.
- `note_grading` runs before `record_attempt`, whose pass resets the entry;
  `jobs start --force-retry <id>` deletes the entry and the failed hashes
  with it.
- Preflight failures count: an existing test that fails there and is loosened
  before the first attempt is flagged. A test not written yet hashes to
  nothing at preflight, so greenfield work stays unflagged. A pass at a later
  job's preflight is compared too.

The verdict stays `passed`. `jobs status` appends
`(grading changed after failure: <paths>)` to the row, `results --compact`
appends `grading-changed=<paths>`, the status payload carries
`grading_changed_after_failure` per row, `jobs status --all --json` lists
every job, and `/gatekit:verify` reads that and lists such tasks as a
warning: "passed only after its own test changed — review the diff of
<paths>".

## Consequences

- A loosened test is visible at verify time with the paths to diff, and a
  loosened approved criterion cannot count as proven, re-derived or not.
- No write is blocked and no task verdict changes, so ADR-0013's recheck flow
  is untouched. A correct fix to a wrong test is flagged too; that is the
  price of reporting rather than judging, and the reviewer decides.
- A changed grading file makes the contract `unverified` until
  `/gatekit:gate` re-approves, which is the same step a changed `05-gate.md`
  already needs.
- A gate or criterion that rewrites its own grading file — a snapshot test
  run with `-u`/`--update-snapshots` whose snapshot is named in argv, a
  formatter run over the test it then executes — is flagged every time it
  changes something. Name only the test, not the file it rewrites, or accept
  the flag and re-approve.
- Commands that name no file, or only a directory or glob, are not covered
  (decision 1); neither is a brownfield check of source files, by design.
- The host session can still approve; see decision 2.

**Contract changes** (`docs/ARCHITECTURE.md`): §2 lists the new fields in
`contract.json`, `approvals.json`, `gates.json`, `status.json` and
`attempts.json`; §5 gains the `grading` rule and `grading_unapproved`; §7
the pinned grading, `check_gate` and the worker refusal; §10 the task report;
§13 the tests; §14 `runcheck.grading_files`, `runcheck.grading_hashes`,
`runcheck.grading_patterns`, `contract.unapproved_grading`,
`approval.check_gate` and `jobs.note_grading`.

## Rejected alternatives

- Options 1, 2 and 4 above, for the reasons given.
- **Withhold the task** when its grading file changed between a failure and a
  pass. A test that was itself wrong is fixed exactly this way, and a refusal
  would send a correct task back to a worker.
- **Hash the whole write scope.** Code changes between a failure and a pass
  are the point of an attempt; only the judging files say something.
- **Diff and judge the change** (e.g. count removed assertions). Runner- and
  language-specific guessing; the reviewer reading the diff is cheaper and
  right more often.

## Open questions

- Files a test imports (fixtures, conftest.py, snapshots) are not grading
  files unless argv names them.
- Whether `/gatekit:verify` should fail, rather than warn, when a task's flag
  is set and no human has looked at the diff.

# ADR-0023: Notice when the files that grade the work change

Status: accepted 2026-10-03 (owner approval in session).

Origin: a pattern idea from Ouroboros-style self-improving agent loops, where
the loop that is graded can also reach the grader. Only the idea is taken; no
code from any such project (clean-room rule).

## Context

A gate or a completion criterion is a command, and most of them name the file
that does the judging: `python3 -m pytest tests/test_login.py`,
`node --test test/cart.test.js`, `bash scripts/e2e.sh`. A worker is allowed to
write inside its `write_scope`, and a task's scope often covers its own tests.
That is on purpose: ADR-0013's recheck flow exists because gates and tests are
refined mid-build, and on the gk-trial2 run most respawns came from a gate that
moved while the code was already right.

The same freedom lets a worker that cannot make a test pass make the test
easier instead: delete an assertion, skip a case, widen a tolerance. The gate
then passes and nothing records that the thing doing the judging changed. The
completion contract has the same exposure after approval: `05-gate.md`'s hash
is pinned, but the spec files its criteria run are not.

The owner considered three responses:

1. **Block writes** to grading files during a build (in the write gate).
   This breaks ADR-0013: a refined gate or test is normal, and the write gate
   cannot tell a fix from a loosening.
2. **Detect and refuse**: fail or withhold the task when its grading file
   changed between a failure and a pass. Same problem one step later: a test
   that was itself wrong is fixed exactly this way, and a refusal would send a
   correct task back to a worker.
3. **Detect and report only**: record that it happened, keep the verdict, and
   put it in front of the reviewer.

The owner chose 3 for tasks. For completion criteria the approved file is the
contract, so a change there cannot be a pass; it is reported as `unverified`
(never `fail`, since nothing was shown wrong, and never `ok`).

## Decision

### 1. Grading files

For a task gate's or a criterion's `argv`, after `${CLAUDE_PLUGIN_ROOT}`
expansion, the grading files are the tokens that name an existing regular file
inside the project root:

- argv[0] counts only when it is a path (holds a slash), i.e. a script; a bare
  program name (`pytest`, `npm`) is looked up on PATH and never counts.
- Every later token that does not start with `-`. A pytest node id
  (`tests/test_a.py::test_x`) counts by the part before `::`.
- The token is resolved like ADR-0022's missing paths
  (`runcheck.relativize`): `.`/`..` collapsed, the root stripped, anything
  outside the root or still climbing with `..` dropped. The file's realpath
  must also stay inside the root's realpath, so a symlink out does not count.
- A token that names a directory or nothing is not a grading file.

`runcheck.grading_hashes(argv, root)` returns `{relpath: sha256}` for them.
The cost is hashing the handful of files a command names, once per run.

**Limitation.** A command that names no file (`npm test`, `pytest` with no
arguments, `make check`) has no grading files, and nothing here covers it. A
criterion author who wants the coverage names the spec file in argv
(`npx playwright test e2e/login.spec.ts`).

### 2. Criteria: hashed at derive, `unverified` on change

`contract derive` records, per criterion, `"grading": {relpath: sha256}` for
the grading files that exist at that moment. Approval pins the `05-gate.md`
that was derived, so these are the approved files.

When the contract is executed (`contract run`, the Stop gate, verify's run and
`contract baseline` all go through `contract.execute`), each criterion still
runs. Afterwards, if any recorded grading file now hashes differently or is
missing, a result that would be `ok` becomes `unverified` with detail
`grading file changed since approval: <path> — re-derive and re-approve
05-gate if the change is intended`. A `fail` stays `fail`; an already
`unverified` result keeps its own reason. A file that did not exist at derive
time is not tracked, since there was nothing approved to compare against.
Re-deriving records the current hashes and clears it.

The Stop gate's reuse (ADR-0020) does not need a new check: a changed grading
file changes the tree fingerprint, so the old `ok` is not reused. A test pins
this. `contract baseline` runs right after derive, so it sees no change.

### 3. Tasks: "passed only after its own grading file changed"

`run_gates` records, on each gate in `gates.json`, `"grading": {relpath:
sha256}` taken just before that gate runs.

Every path that records a task's gate result (`execute_task`, so also
`redelegate`; `complete_task`; `recheck`) then updates the task's
`status.json`:

- For each gate whose verdict is `fail`, `failed_grading[<gate name>]` is set
  to that gate's hashes. This is the most recent failure of that gate in this
  job.
- When the task is `passed`, each gate in `failed_grading` is compared with the
  same gate's hashes now. Any path whose hash differs or that is gone is
  added to `grading_changed_after_failure` (a sorted list, kept for the rest
  of the job), and `failed_grading` is cleared.
- `redelegate` carries both fields into the new attempt's `status.json` (the
  old one moves to `attempt-N/`).

The verdict stays `passed`. `jobs status` appends
`(grading changed after failure: <paths>)` to the row, `results --compact`
appends `grading-changed=<paths>`, the status payload carries
`grading_changed_after_failure` per row, and `/gatekit:verify` lists such
tasks as a warning: "passed only after its own test changed — review the diff
of <paths>".

## Consequences

- A loosened test is visible at verify time with the paths to diff, and a
  loosened approved criterion cannot count as proven.
- No write is blocked and no task verdict changes, so ADR-0013's recheck flow
  is untouched. A correct fix to a wrong test is flagged too; that is the
  price of reporting rather than judging, and the reviewer decides.
- A changed grading file makes the contract `unverified` until re-derive and
  re-approval, which is the same step a changed `05-gate.md` already needs.
- Commands that name no file are not covered (decision 1).

**Contract changes** (`docs/ARCHITECTURE.md`): §2 lists the new fields in
`contract.json`, `gates.json` and `status.json`; §5 gains the `grading` rule;
§10 the task report; §13 the tests; §14 `runcheck.grading_files`,
`runcheck.grading_hashes` and `jobs.note_grading`.

## Rejected alternatives

- Options 1 and 2 above, for the reasons given.
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

# ADR-0022: "Not runnable yet" is not broken, zero tests is not a pass, and criteria get a baseline

Status: accepted 2026-10-03 (owner approval in session).

Origin: ADR-0009's first and third open questions, and a real job.

## Context

In `study-gallery` job `20260929T140930Z-bb7c`, 7 of 10 tasks started with
the preflight warning "gate `e2e` failed at preflight (exit 254) in a way that
may be the command rather than the work". The gate was
`npm run e2e -- e2e/login.spec.ts` and stderr said
`npm error code ENOENT … Could not read package.json`. `package.json` did not
exist yet because the first task, `shell-login`, creates it. The gate was
fine. The warning was noise, and seven repeats of it teach the reader to skip
warnings.

`classify_gate_result` only knows "a pattern matched and names an argv token"
(refuse), "a pattern matched and names nothing" (warn) and "anything else"
(silent). It never asks the one question that decides this case: **will any
task in this job create the path that is missing?**

The opposite hole is worse. Preflight records a task `passed` and spawns no
worker when its gates pass before any work, warning only when the write scope
is empty. A gate that runs zero tests passes: `jest --passWithNoTests`,
`vitest --passWithNoTests`, `mocha` with no specs, `node --test` with no
matches, `go test` on a package with no test files, `cargo test` with no
tests. Those all exit 0. Python's `unittest` exits 0 on "Ran 0 tests" before
3.12 and 5 after; `pytest` exits 5. A task whose tests do not exist yet but
whose scope has a file would be skipped silently. The same zero-test exit 0
would satisfy a completion criterion.

ADR-0009 also left open whether the command-error check should run on
`05-gate.md`'s criteria when `/gatekit:gate` derives them. Today the gate
command tells the author to run each criterion by hand, and that instruction
has been followed and still misread.

The constraints: `unverified` never rounds; stdlib only; hooks exit 0 on
error; and gatekit's own run time stays negligible. The owner watches it.

## Decision

### 1. A missing path that a task will write is `not_yet_runnable`

When a failing gate's output names a missing path, the path is extracted and
made relative to the project root. That covers:
- `ENOENT: no such file or directory, open|stat|lstat|scandir|access '<p>'`
- `No such file or directory: '<p>'`
- `<p>: No such file or directory`, where `<p>` opens the line or follows a
  `<prog>: ` prefix and holds no space. A path with spaces is ambiguous in
  that form, and no extraction beats a wrong one.
- `can't open file '<p>'`
- pytest's `ERROR: file or directory not found: <p>`
- node's `Cannot find module '<p>'`, only when `<p>` looks like a path:
  absolute, starting `./` or `../`, or holding a slash and not a scoped
  package (`@scope/pkg`), or equal to one of the gate's arguments. A bare
  package name such as `express` is not a path.

Python's `No module named` names a module, not a path, so it is left alone.
Matching is textual, so Windows backslashes and drive letters work. `.` and
`..` segments are collapsed first, with `ntpath` rules for a Windows-shaped
path and `posixpath` rules otherwise, so `/r/web/../src/a.ts` is
`src/a.ts`. A path under the root is stripped to relative. Both the root and
the path are also compared in realpath form where the path or its parent
exists on this host, so `/var/…` matches a root given as `/private/var/…`.
A relative path is taken relative to the root, which is the gates' cwd. A
path outside the root cannot be written by a task.

Each relative path is checked against every `write_scope` glob of the job's
tasks, using the write gate's own matcher (`gates/write.py: matches`), so
"covered" means exactly what the write gate would allow. Then:

- **Covered** → a new kind, `not_yet_runnable`. The job starts silently.
  `preflight.json` records, on that gate, `preflight: "not_yet_runnable"` and
  a detail naming the path and the task that writes it.
- **Not covered**:
  - If the path came from npm's `Could not read package.json`, the runner
    cannot start in this project and no task will make it start. That is
    `command_error`, refused with exit 4, and the message names
    `package.json` (not whichever path npm printed first, often `.npmrc`)
    and says no task writes it.
  - Otherwise ADR-0009's rule stands. A line naming one of the gate's own
    arguments is `command_error`, now worded with the missing path and "no
    task in this job writes it". Anything else is `suspicious`.
- **No path extracted** → today's behaviour.
- Exit 126/127 are `command_error` first, as before, with one exception.
  When argv[0] is a shell or interpreter (`sh`, `bash`, `zsh`, `node`,
  `python`, `python3`, `ruby`, `deno`, `bun`, `tsx`, `ts-node`; a version
  suffix or `.exe` is ignored) and the missing path is covered and is one of
  the gate's own arguments, the owner check runs first. `bash
  scripts/e2e.sh` exits 127 when the script does not exist yet. argv[0]
  itself not being found (`nonexistentprog`, 127) stays `command_error`.
- A program that could not be executed at all (`run_gates` gets an
  `OSError`) is recorded with `could not run: <error>` in `stderr_tail`, so
  the classifier sees it. It is `not_yet_runnable` when argv[0] is a path a
  task writes, and `command_error` otherwise. This is the same rule
  `contract baseline` applies, so both agree.
- When the covered path is one of the gate's own arguments, `jobs start`
  prints one `note:` line per task naming the path and the task that writes
  it. It is a notice, not a warning, and is recorded as
  `preflight_notices` in `job.json`.

Refusal is deliberately *not* extended to every uncovered path. ADR-0009's
reason holds: a test that fails with `FileNotFoundError` about a file the
code under test should produce, outside any declared scope (a temp output, a
fixture), is expected pre-work failure. Refusing it would block a correct job
with exit 4. The new refusal is limited to a case that can only be a broken
command: the package manager cannot find the manifest, and nothing creates
it.

### 2. A gate that ran no tests is `unverified`, not `ok`

`plugin/spec-kit/no-tests-signatures.json` lists signatures. Each has an id,
an anchored multiline `pattern`, the exit codes it applies to, and a
`positive` pattern that reports a non-zero count. There is one per runner:
pytest, unittest, jest, vitest, playwright, node:test, mocha, go and cargo.

A result is "ran no tests" when, over the full stdout and stderr:
- some signature's pattern matches and its exit list contains the exit code,
  **and**
- **no** signature's positive pattern matches anywhere.

The second condition is what keeps a mixed run with real tests `ok`: cargo's
doc-test `running 0 tests` after `running 5 tests`, or `go test ./...` with
one empty package.

`run_gates` and the contract's criterion runner both apply it. A result that
would have been `ok` becomes `unverified` with detail `ran no tests
(<signature id>)`.

The exit list is `[0]` everywhere except pytest and unittest, which list
`[0, 5]`. Exit 5 is each runner's documented "no tests were collected/run"
code. That is the runner saying it could not judge, which is `unverified` by
this repo's vocabulary, not `fail`. Jest, vitest and playwright exit 1 on "no
tests found" by default. That is left a `fail`: it is already not a pass, and
a non-zero exit is indistinguishable from a real failure without guessing.

Because the result is no longer `ok`, preflight no longer skips the task, and
the Stop gate no longer counts the criterion as proven. No warning is
printed at preflight. "No tests yet" is the normal state before a task
writes them.

pytest's exit 5 also covers "every test deselected" (`-k nomatch` prints
`==== 1 deselected in 0.00s ====`). The `pytest-deselected` signature,
`^=*\s*\d+ deselected\b`, lists exit 5 only, so a run that deselects some
tests and passes the rest is untouched.

go's positive pattern accepts trailing text after the duration (`ok  m/pkg
0.123s  coverage: 80.0% of statements`) but not `[no tests to run]`, and its
pattern is anchored at the start of a `?` or `ok` line like the others.

ANSI escapes (`\x1b[...m` and other CSI sequences) are stripped before
matching, so colour forced on by `FORCE_COLOR` or `--color=yes` does not
split an anchored pattern.

The signature list is data under `plugin/spec-kit/`, which answers ADR-0009's
third open question for this list. An unreadable file, or one whose top
level is not an object with a `signatures` list, means "no signatures":
results stay as the runner reported them, and nothing raises. Each entry is
type-checked on its own. An entry that is not an object, lacks a string
`id`, `pattern` or `positive`, has a pattern that does not compile, or has
`exits` that is not a list of integers (`true` is not an exit code) is
skipped, and the other entries still apply.

The Stop gate's reuse record (`runs/contract-last.json`, ADR-0020) carries
`signatures_sha256`, the hash of the signature file. A record whose hash is
missing or differs is not reused. A result saved before 0.14.0, when a
zero-test run counted as `ok`, is therefore re-judged.

### 3. `contract baseline` runs the criteria once at gate time

`gatekit contract baseline [--json] [--budget S]` runs the derived contract
against the current tree within the contract's budget, the same budget as
`contract run`, and sorts each criterion into one of five classes:

- `already_passes` (`ok`)
- `not_yet_runnable` (decision 1, against `spec/04-tasks.md`'s scopes; also a
  could-not-execute whose program is a path a task writes)
- `fails` (expected before work)
- `command_error` (decision 1's refusal cases, 126/127, and a program that
  cannot be executed and that no task writes)
- `unverified` (timeout, budget, ran no tests)

It writes `.gatekit/baseline.json` (`recorded_at`, `source_sha256`,
`elapsed_s`, per-criterion `class`, `verdict`, `exit`, `elapsed_s`,
`detail`). It prints one line per criterion and the total time. It exits 0
unless a criterion is `command_error`, which exits 4, matching preflight. A
missing or stale contract exits 1 with the reason.

It is a separate file. It never writes `runs/contract-last.json`, so the
Stop gate's reuse (ADR-0020) neither sees it nor is invalidated by it.

`/gatekit:gate` runs it between derive and approval and puts the table in
the approval question:
- `already_passes` is flagged "passes before any work — confirm it tests new
  behaviour".
- `command_error` must be fixed before approval is asked for.
- Everything else is informational.

Baseline runs every criterion against the pre-work tree. Anything a
criterion creates there (build output, a database file, a snapshot)
persists into the build. `/gatekit:gate` says so before running it.

It never approves. `gate-criteria.md`'s "measure first" step uses `contract
baseline --budget 600`, which reports each criterion's `elapsed_s`. When no
budget needs declaring, that run is the only one. When the budget fence is
then added or changed, `/gatekit:gate` runs the baseline again, so
`baseline.json`'s `source_sha256` always matches the `05-gate.md` that gets
approved. There is no "skip after a budget-only edit" shortcut.

## Consequences

- The `study-gallery` job would have started silently. Each `e2e` gate's
  `preflight.json` names `shell-login` as the task that writes
  `package.json`.
- A zero-test pass can no longer skip a task or satisfy a criterion. A
  project whose criterion legitimately runs no tests must say so with a
  criterion that does not invoke a test runner.
- `/gatekit:gate` costs one contract run, the one `gate-criteria.md` already
  asked for, or two when the measurement leads to a budget edit. Preflight's added cost is a few regexes over output it already
  holds, plus glob matching against the job's scopes.
- New refusal surface: npm without a manifest that no task writes. That job
  could not have passed anyway. A program given as a path that cannot be
  executed and that no task writes is also refused now; before, preflight
  recorded no output for it and started silently.
- Trade-off: a typo'd path inside a broad scope (`python3 src/tset_app.py`
  with scope `src/**`) was refused before 0.14.0 and now starts, because a
  task could write that path. The gate fails after the task runs instead of
  at preflight. The `note:` line naming the path and its owner is the
  disclosure; it is not a warning because the common case is correct.
- `contract baseline` runs the criteria against the pre-work tree, and
  anything they create persists. `/gatekit:gate` runs it on every pass,
  including after a budget-only edit, so `baseline.json`'s `source_sha256`
  always matches the approved `05-gate.md`.

**Contract changes** (`docs/ARCHITECTURE.md`):
- §1 lists the data file.
- §2 lists `.gatekit/baseline.json`.
- §5 gains "ran no tests" and `contract baseline`.
- §10's preflight paragraph gains `not_yet_runnable` and the uncovered-path
  rules.
- §13 lists the tests.
- §14 gains `runcheck.py`'s functions and the new `classify_gate_result`
  arguments.

## Rejected alternatives

- **Refuse every uncovered missing path.** It turns a test's own
  `FileNotFoundError` into exit 4 and blocks correct jobs, which is what
  ADR-0009 avoided.
- **Treat any "no tests" text as unverified regardless of counts.** Breaks
  every multi-package run with one empty package.
- **Convert jest/vitest/playwright's exit 1 "no tests found" to
  `unverified`.** A non-zero exit already fails. Softening a failure into
  `unverified` is not wrong, but it adds a rule with no case behind it.
- **Run the baseline inside `approve`.** Approval is a hash pin and must stay
  instant. Running commands there would make an approval depend on the
  tree's state.

## Open questions

- A run where every collected test is skipped (`3 skipped`, exit 0) proved
  nothing either, but it is not detected. Skips are often intentional
  (platform guards), and a rule would need per-runner wording for "all
  skipped" versus "some skipped". Left open.
- The signature list is per runner, not per reporter. A custom reporter that
  prints none of these lines still passes on zero tests. Adding a signature
  is a data change.
- `baseline.json` is not consulted by anything after approval. Whether
  `/gatekit:verify` should report criteria that `already_passes` at baseline
  and were never seen failing is left open.

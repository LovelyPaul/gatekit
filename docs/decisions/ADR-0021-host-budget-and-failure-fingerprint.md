# ADR-0021: `jobs complete` is budgeted, and an identical failure stops early

Status: accepted 2026-10-03 (owner approval in session).

Origin: ADR-0014's first open question, and a gap between ADR-0014's intent
and the host-execution path.

## Context

ADR-0014 put a per-task consecutive-failure count in `.gatekit/attempts.json`
and made `redelegate` and `start` refuse at the budget. It also said "a host
attempt is an attempt: it must count exactly as a worker's does". It counts,
but nothing refuses: `complete_task` — the path every build takes under the
default `build.execution = "host"` — records the failure and never consults
the budget. A host session can `jobs complete` a task inside one job and fail
indefinitely. The budget binds only the non-default mode.

ADR-0014 also left open whether to record the failing gate's output, so a task
failing the same way each time can be told apart from one making progress. A
consecutive count treats "3 failed, then 2 failed, then 1 failed" the same as
three identical failures. The second is the loop the budget exists to stop,
and it is visible after two attempts, not three.

`spec/RECOVERY.md` (the template) says redelegating one task is limited to 3.
Under the code, `build.max_retries` (default 2) is the number of retries after
the first attempt: `redelegate` refuses once the carried count exceeds it, so
the third consecutive failure is the last one, and `start` will not include a
task that already has 2. The template's "3" reads as three redelegations.

## Decision

1. **`complete_task` enforces the budget.** At entry, before any gate runs, it
   refuses when the task's carried consecutive failures exceed `max_retries`
   (read from `job.json` as `redelegate` reads it; `<= 0` disables), raising
   `RetryBudgetExceeded`, CLI exit 3. The message names the task and the count
   and points at `spec/RECOVERY.md` and `jobs start --force-retry <id>`.
   With the default of 2 the host gets three attempts, as a worker does
   (one plus two redelegations). `recheck` stays uncounted and unrefused.

2. **Failure fingerprint.** When `record_attempt` folds in a failure and is
   given the gates result, it stores `last_failure_sha` — sha256 over a
   canonical JSON of the gates whose verdict is not `ok`, sorted by name:
   name, verdict, exit code, and the normalized `stdout_tail` and
   `stderr_tail` — and `repeats`, the number of consecutive failures with that
   same fingerprint (1 for a new one). A pass clears the entry; `blocked` and
   `stopped` leave it alone, as before. When no gate failed (the worker exited
   non-zero over passing gates), no gates result was given, or every failing
   gate printed nothing, there is no evidence of sameness: the fingerprint
   fields are dropped and the count alone applies. Entries written before
   this ADR, without the fields, read as "no fingerprint".

   `normalize_gate_output(text, root)` is a pure function and deliberately
   conservative, because a false "same" stops a task that is making progress
   and a false "different" only costs one more attempt. It replaces only: the
   absolute project root (with `<root>`), ISO-8601 date-times and compact
   `YYYYMMDDTHHMMSSZ` stamps, `HH:MM:SS` clock times not preceded by a word
   character, dot or colon (so `app.js:12:34:56` stays a location), durations
   (a number followed, optionally after one space or tab — never a newline —
   by `ns`/`us`/`µs`/`ms`/`s`/`sec`/`secs`/`seconds`/`min`/`mins`/`minutes`,
   with no word character or hyphen after the unit, so `2 us-east` stays),
   hex addresses of six or more digits after `0x`, and trailing whitespace.
   Ordinary integers stay: "3 failed" and "2 failed" hash differently.

   `gates.json` keeps only the last `TAIL_BYTES` (4000) characters of each
   stream, and where that cut lands moves with the length of any volatile
   token after it. A tail at the cap therefore loses everything up to and
   including its first newline before it is normalized, so two identical
   long failures still compare equal. (An untruncated stream of exactly
   4000 characters loses its first line too; that only removes evidence.)

   The read-modify-write of `attempts.json` in `record_attempt` and
   `clear_attempts` runs under a module-level lock, since `_run_wave`
   finishes tasks on parallel threads and an unlocked update erased other
   tasks' entries. The fingerprint is computed before the lock is taken.

3. **The same failure twice stops early.** `redelegate`, `complete_task` and
   `start` also refuse a task whose `repeats >= 2` — its last two consecutive
   failures produced identical gate output — whatever budget remains, unless
   `max_retries <= 0`. Same exception, exit 3, distinct message: retrying
   unchanged will not converge; decide whether the gate is wrong (fix it, then
   `jobs recheck`) or the instruction is (edit the task); `--force-retry <id>`
   clears the entry, as before.

4. **`jobs status`** rows carry `repeated_failures`, and the table prints
   `(n consecutive, same failure)` when it is 2 or more.

## Consequences

- Host builds are budgeted for the first time. A session that keeps calling
  `jobs complete` on a failing task gets exit 3 on the fourth call by default,
  or the third when the last two failures were identical.
- The identical-failure stop fires after two attempts instead of three on the
  common loop (same assertion, same missing file), and never when the output
  moved, so a task making progress keeps its full budget.
- The ledger stores one 64-character hash per task, not output. The output
  itself is already in the job's `gates.json` and `attempt-N/` archives.
- `recheck` still neither counts nor clears; a gate fixed and rechecked to a
  pass does not clear the ledger either, which is ADR-0014's behaviour and
  unchanged here.
- `spec/RECOVERY.md`'s template states the limit as the code enforces it:
  three consecutive failures by default, two identical ones.

**Contract changes** (`docs/ARCHITECTURE.md`): §2's `attempts.json` line names
the new fields; §10 gains the fingerprint, the normalization, the `complete`
refusal and the same-failure refusal; §13 lists the new tests; §14 gains
`normalize_gate_output`, `failure_fingerprint`, `repeated_failures` and the
`gates` argument of `record_attempt`.

## Rejected alternatives

- **Store the output, compare later.** Kilobytes per task in a committed file,
  for a comparison a hash answers.
- **Aggressive normalization (all digits, all paths).** Turns "3 failed" and
  "2 failed" into the same line — exactly the false "same" that stops a task
  converging.
- **Fingerprint every gate, passing ones included.** A gate that newly passes
  is progress and already changes the failing set; including passing output
  only adds volatile text.
- **Refuse on the first repeat (`repeats >= 1`).** That is every failure.

## Open questions

- The lock is per process. Two gatekit processes updating `attempts.json`
  at once (say, a `jobs complete` while a worker-mode `jobs start` drains)
  can still lose an update. A cross-process lock (`fcntl` on POSIX,
  `msvcrt` on Windows, around `.gatekit/attempts.json.lock`) is stdlib but
  could not be tested on Windows here, so it is left for a change that can.
- A failure with no evidence — every failing gate silent, a worker exit
  over passing gates, a gate timeout with no output — never fingerprints, so
  only the consecutive count stops it.
- `recheck` runs gates without touching the ledger, so it also sidesteps
  the host budget: a session can recheck a task any number of times.
- A worker timeout returns from `execute_task` before `record_attempt` runs, so
  it is not counted, although ADR-0014 lists `timeout` as a failure state.
  Left as found; it predates this ADR.
- Whether a passing `recheck` should clear the ledger entry, since it is
  evidence the code is right. Today it does not.

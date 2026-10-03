# ADR-0027: Protected state files, and a Stop gate that checks the approval and the contract it judges

Status: accepted 2026-10-03 (owner approval in session).

Origin: the idea comes from a study member's Windows fork,
github.com/yeoul9703/gatekit-cc-windows, which closed both holes below in its
own tree. Only the idea is taken; the code here is written from this
repository's own modules (clean-room rule).

## Context

ADR-0023 pins the grading files' hashes inside `.gatekit/approvals.json`, and
`.gatekit/contract.json` holds the criteria derived from `spec/05-gate.md`.
Both files are plain JSON in the project, and nothing stopped a session from
rewriting them:

1. **The write gate allowed both files.** Rule (a)'s allowlist holds
   `.gatekit/**`, so a `Write` to `.gatekit/approvals.json` with the current
   hash of `05-gate.md` was allowed before approval — and that one write opens
   code writing without the user. After approval the Bash gate does not parse
   at all, so `echo … > .gatekit/approvals.json` was allowed too.
2. **The Stop gate trusted `contract.json`.** `contract.status` compares only
   the recorded `source_sha256` (and the design inputs) with the files. A
   `contract.json` whose criteria were loosened by hand, with the recorded
   source hash left as it was, was judged as if it were the approved contract.

Reproduced on 0.16.4 (a temporary project, `05-gate.md` with one criterion
that exits 1, derived, then approved):

```
pre-approval Write .gatekit/approvals.json   -> allowed
post-approval Write .gatekit/contract.json   -> allowed
post-approval Bash `echo {} > .gatekit/approvals.json` -> allowed
contract.json criterion argv edited to `python -c pass`, pipeline verify:
Stop -> allowed, final_verdict "ok"
```

## Decision

### 1. `approvals.json` and `contract.json` are written only by gatekit

`.gatekit/approvals.json` and `.gatekit/contract.json` are written only by
gatekit's own CLI (`approve`, `contract derive`). Every other writer is denied,
always: before and after approval, in any session, with or without
`GATEKIT_TASK_ID`, and whatever `enforce_spec_before_code` says.

- **Write gate.** `Write`, `Edit`, `MultiEdit`, `NotebookEdit` and every file an
  `apply_patch` header names (`Add`/`Update`/`Delete File`, `Move to`) are
  checked against the two files before rules (a) and (b), and the patch path
  no longer skips this check when no rule is active.
- **Matching.** A target is protected when its last two path segments are
  `.gatekit` and `approvals.json` or `contract.json`, compared
  case-insensitively everywhere, after: `\` read as `/`, Git Bash `/c/…` read
  as `C:/…`, each segment cut at an NTFS stream suffix (`::$DATA`, `:name`;
  a drive letter is kept) and stripped of trailing dots and spaces, `.` and
  `..` resolved. The check runs on the path as written (joined to the project
  root when relative) and again on its `realpath`, so a symlinked file or
  directory is followed; when the target exists, `os.path.samefile` against
  the two files also catches a hard link or a short (8.3) name. A protected
  file outside the project root is still protected: it is some gatekit
  project's record.
- **Bash gate.** Each target the existing static extraction finds (redirects,
  `tee`, `cp`/`mv`/`ln`/`install`/`rsync` destinations, `sed -i`, `perl -i`,
  `dd of=`, `touch`/`rm`/`truncate`/…, `cd` tracking, `sh -c` recursion) goes
  through the same check. Before approval this happens inside
  `write.decide_path`, which the Bash gate already calls for every target.
  After approval the Bash gate judges nothing else, so a narrow always-on
  check runs first on every command (the parse is static and cheap; only its
  protected-file findings are acted on). It denies when a resolved target is
  protected; when a removed path (`rm`, `rmdir`, `unlink`
  operands, `mv` sources) is a protected file or a directory that contains
  one (`rm -rf .gatekit`, `mv .gatekit x`); when a `cp`/`mv`/`ln`/`install`/
  `rsync` destination is the `.gatekit` directory and a source's base name
  is a protected name; and when the command is otherwise opaque (inline
  interpreter code, `git checkout`, `eval`, …) and its text names
  `.gatekit/approvals.json` or `.gatekit/contract.json`.
- **The launcher stays allowed.** `python3 "<plugin>/bin/gatekit.py" approve
  spec/05-gate.md` and `… contract derive` name no write target in shell
  syntax, so the host session runs them as before. A worker's `approve` stays
  denied (ADR-0023). Redirecting the launcher's output into a protected file
  is a redirect like any other and is denied.
- **Message.** The deny reason (en/ko, by `output_lang`) names the path, says
  the file is gatekit's own record, and points to `/gatekit:gate`.

### 2. The Stop gate and `contract run` check the approval and the contract first

Before any criterion runs, `contract.integrity(root, require_approval)` is
evaluated, in this order, and the first failure is the result
(`unverified`, no criteria):

1. no contract — as before, `execute` reports it;
2. `contract_stale` — `contract.status` is not `ok` (unchanged; the remedy is
   `contract derive`);
3. **`gate_not_approved`** (when `require_approval`) — `approval.check_gate`
   is not `ok`: no approval, a stale one, or (ADR-0023) a pinned grading file
   the contract no longer records with its pinned hash. In that last case the
   result also carries `grading_unapproved` as a second reason and the paths
   in `unapproved_grading`, so the existing message that names the files is
   kept. `grading_unapproved` is now a sub-case of `gate_not_approved` rather
   than a separate gate;
4. **`contract_mismatch`** — `05-gate.md` is parsed again in memory and the
   result compared with `contract.json`: the ordered list of criteria with
   every field except `grading` (`id`, `argv`, `expect`, `timeout_s`,
   `artifacts`, `tier`, and any extra key), and `total_budget_s`. A
   `05-gate.md` that no longer parses is a mismatch too. `grading` is
   compared by its keys: each recorded path must be a grading file of that
   criterion's argv now, or be absent from disk. Its hashes are not compared
   with the tree: a grading file legitimately changes between derive and
   Stop, and that case is ADR-0023's per-criterion `unverified` with the
   paths; the hashes that matter are the approval's pins, which step 3 checks.
   The result carries `mismatch`, a short list of what differs.

- **Who requires the approval.** The Stop gate (both pipelines, so
  `/gatekit:verify` too) and `contract run` require it. `contract baseline`
  does not: `/gatekit:gate` runs it between `derive` and the approval, so it
  checks steps 2 and 4 only. `contract.execute` itself is unchanged, so a
  caller inside gatekit decides; the three CLI/hook entry points above are
  the only callers.
- **Blocking.** Both new reasons block in the Stop gate like any other
  `unverified` (block count, `MAX_BLOCKS`, `stop_hook_active`, stand-down of
  ADR-0024 unchanged), with a message in `output_lang` that says what to do:
  for `gate_not_approved`, restore `05-gate.md` and fix the code, or re-run
  `/gatekit:gate` for a new approval; for `contract_mismatch`, run `contract
  derive` to restore the contract from the approved gate and fix the code,
  or re-run `/gatekit:gate` if the criteria must change.
- **No reuse across a refusal.** The Stop gate runs the check before it looks
  at `runs/contract-last.json`, and a refusal has no criteria, so it is never
  recorded. A record also carries `contract_sha256`, the hash of
  `contract.json` it was judged under; `same_tree_record` (and so
  `reusable_last` and the reuse in the Stop gate) refuses a record without it
  or with another hash. `.gatekit` is outside the tree fingerprint, so
  without this an edited `contract.json` would have reused the last result.

## Consequences

- An approval can no longer be forged by a file write, and the Stop gate no
  longer judges criteria the user did not approve.
- A project that never approves `05-gate.md` (for example with
  `enforce_spec_before_code: false`) gets `gate_not_approved` from the Stop
  gate under `build`/`verify` instead of a judgement. That is the honest
  verdict: the criteria were never agreed. `/gatekit:gate` always approves
  before `/gatekit:build`, so the normal flow is unaffected.
- Stop-gate and `contract run` cost one more parse of `05-gate.md` plus the
  grading-file hashes it already computes at derive; no criterion runs twice.

### Remaining trust boundary

- **The host session can still run `gatekit approve` itself.** Approval is a
  user act mediated by `/gatekit:gate`'s `AskUserQuestion`; the hook cannot
  tell a user-approved invocation from one the model ran on its own. Loosening
  `05-gate.md`, re-deriving and approving in the host session therefore still
  passes, as ADR-0023 already states.
- **Before approval**, a write through an opaque command (a Python one-liner,
  `node -e`, `git checkout`, …) is denied as `opaque` by the existing rule,
  whatever it names. **After approval** that rule is off; only the narrow check
  above runs, so an opaque command that does not spell the path
  (`python3 -c "open('.gate'+'kit/appro'+'vals.json','w')"`, `cd .gatekit &&
  python3 -c …`, a script file, an archive extracted over the root) is not
  seen. Its effect is bounded by decision 2: an edited `contract.json` is
  `contract_mismatch`, and an `approvals.json` whose hash or pins no longer fit
  is `gate_not_approved`. What still passes is a forged approval that is
  consistent with a re-derived contract — the same outcome as the host
  running `gatekit approve`.
- Other `.gatekit/**` files (session ledgers, `runs/contract-last.json`, job
  directories) stay writable as before.

**Contract changes** (`docs/ARCHITECTURE.md`): §2 notes that the two files are
written only by gatekit; §3 the write and bash gates' protected-file rule and
the Stop gate's integrity check; §5 `contract.integrity`,
`gate_not_approved`, `contract_mismatch`, the baseline exception and
`contract_sha256` in the Stop record; §7 that an approval is not a file
write; §13 the tests; §14 `write.protected_state`, `contract.integrity`,
`contract.mismatch` and the reason constants.

## Rejected alternatives

- **Sign or MAC the files.** Any key the hooks can read, the session can read;
  it moves the secret, not the boundary.
- **Make `execute` check the approval for every caller.** Baseline runs before
  approval by design, and the many direct callers in tests and tools are not
  entry points a session can reach; the check belongs where a verdict is
  issued.
- **Compare `grading` hashes with the tree in `contract_mismatch`.** That turns
  every test edited during the build into a contract mismatch and drops
  ADR-0023's per-criterion path list.
- **Judge every Bash command after approval.** That changes post-approval
  behaviour for every command (opaque denials would return); the narrow check
  acts only on findings that touch the two files.

## Open questions

- **PowerShell.** Claude Code's PowerShell tool does not pass through the
  `Bash` matcher, so a PowerShell command that writes either file is not seen
  by any gate. Covering it (a matcher and a static reading of PowerShell
  syntax) is a later ADR.
- Whether `runs/contract-last.json` and the session ledger (`active_pipeline`,
  `stop.stood_down`) need the same protection: a forged record or a cleared
  pipeline would let a Stop pass without a run.
- An opaque command after approval that does not spell the path (above).

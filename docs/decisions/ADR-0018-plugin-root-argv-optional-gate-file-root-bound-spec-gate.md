# ADR-0018: `${CLAUDE_PLUGIN_ROOT}` in argv, a not-yet-written gate file, and a spec gate bound to its own project

Status: accepted 2026-09-29 (owner approval in the session that found the
defects); implemented the same day.

Origin: a full discover → interview → design → mockup → tasks → gate run
for a new project (`study-gallery`, a Next.js app) started from a Claude
Code session whose working directory was the gatekit repository itself.

## Context

Three defects surfaced, each blocking or misreporting a step that was
otherwise done correctly.

1. **The documented token-gate argv never runs.**
   `spec-kit/task-gates.md` tells `/gatekit:tasks` to write the token gate
   as `["python3", "${CLAUDE_PLUGIN_ROOT}/gatekit/gates/tokens.py", …]`.
   Task gates (`jobs.run_gates`) and completion criteria
   (`contract._run_one`) both run argv through `subprocess.run` with no
   shell, so the `${…}` text reaches Python literally. Observed from the
   new project's root:

   ```
   can't open file '<project>/${CLAUDE_PLUGIN_ROOT}/gatekit/gates/tokens.py'
   literal exit=2
   ```

   Every task following the documentation carries a gate that fails for a
   reason unrelated to its work. The run worked around it by writing an
   absolute path — which ties a committed spec file to one machine.

2. **A missing `05-gate.md` is a `fail` from the first command on.**
   `heading-map.json` lists `05-gate.md` in `required_files`, so
   `spec validate` reports `missing_required` / `fail` during discover,
   interview, design, mockup and tasks — every stage before the one whose
   job is to write it. Each of those commands tells the agent "never hand
   the user a file that fails validation", so the agent either explains
   the same false alarm at every step or is pushed toward writing a
   placeholder gate file early. Nothing is protected by the `fail`: code
   is already locked until `05-gate.md` is *approved* (the write gate's
   rule (a), §3) and `jobs start` / the Stop gate already require an
   approved, derived contract.

3. **Rule (a) of the write gate governs paths outside its project.**
   `decide_path` computes `relpath = None` for a target outside the
   project root and then falls through to the approval check, so while
   `spec/05-gate.md` is unapproved every write *anywhere else on disk* is
   denied — the session's scratchpad, and another project's own
   `spec/*.md`. In this run that blocked creating the new project's
   folder, copying the spec into it, and writing its `04-tasks.md`; the
   user had to run each of those commands by hand with `!`. Rule (a)'s
   purpose is "this project's code waits for this project's approved
   gate"; a file outside the project is not this project's code.

(A fourth reported item — the prompt hook saying "gate approved" at
session start — was accurate: a finished trial's approved gate file was
still in the gatekit repository's untracked `spec/` and `.gatekit/`. The
fix was moving that trial state out of the repository, not code.)

The standing constraints apply: hooks are the enforcement; every hook exits
0 on internal error; verdicts are `ok / warn / fail / unverified`; standard
library only; tests first.

## Decision

1. **gatekit expands `${CLAUDE_PLUGIN_ROOT}` in argv before running it.**
   `paths.expand_argv(argv)` replaces every occurrence of the literal
   `${CLAUDE_PLUGIN_ROOT}` inside each argv element with
   `paths.plugin_root()`. `jobs.run_gates` and `contract._run_one` call it
   immediately before `subprocess.run`. Only this one token is expanded —
   no other `$VAR`, no `~`, no globbing — so argv stays shell-free and a
   spec file stays portable across machines. The stored fence, the task
   snapshot and `contract.json` keep the unexpanded text.

2. **`05-gate.md` leaves `required_files`.** Its absence becomes
   `missing_optional` (`warn`), like `04-tasks.md` before `/gatekit:tasks`.
   `01-prd.md` stays required. The approval check (§7), the write gate
   (§3 rule (a)) and the contract run (§5) are unchanged and remain the
   things that stop a build without an approved gate.

3. **Rule (a) applies only to targets inside the project root.** In
   `gates/write.py` `decide_path`, a target whose `relpath` is `None`
   (outside the root, after realpath resolution) is allowed by rule (a).
   Rule (b) is unchanged: a scoped worker (`GATEKIT_TASK_ID` set) is still
   denied every write outside the root. The Bash gate inherits both
   through `decide_path`; its `opaque` denial for targets it cannot
   determine is unchanged, since "could not tell" may still be inside the
   project.

## Consequences

- A token gate written exactly as `task-gates.md` shows now runs on every
  machine the plugin is installed on.
- `spec validate` before `/gatekit:gate` reports the gate file as a `warn`
  ("not written yet"), matching every other not-yet-reached stage.
- A session opened in one gatekit project can write into another folder
  (new project scaffolding, scratch files) without the user running shell
  commands by hand. Code inside the governed project stays locked exactly
  as before. A `..` path that resolves outside the root is now allowed by
  rule (a); it was never this project's file.
- `ARCHITECTURE.md` §3 (write rule (a)), §5 (argv execution), §6 (task
  gates) and the `required_files` note in `heading-map.json` are updated
  to match.

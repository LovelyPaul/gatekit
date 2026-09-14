# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 0.6.0 — 2026-09-14

### Added

- Gate preflight (ADR-0009): `jobs start` runs every task's gates once
  before spawning a worker. Gates that already pass record the task
  `passed` with no worker (and a `warn` when nothing exists in the write
  scope yet); a gate whose command itself errors refuses the job with exit 4
  and names the task and gate; `--no-preflight` opts out.
- `jobs stop [--job ID]`: ends this job's own workers (pid plus spawn-time
  check, so a recycled pid is never signalled), marks running and queued
  tasks `stopped`, records `stopped_at`.
- Dependency gating: a task whose in-job `depends_on` did not pass is left
  `blocked` instead of run. `stopped` and `blocked` are terminal, not done.

### Changed

- `jobs redelegate` re-reads the task from `spec/04-tasks.md` and says so in
  the status line when the gates, instruction or write scope changed; a task
  removed from the file is refused. The redelegate prompt tells the worker a
  gate command that looks wrong is to be reported, not coded around.
- `tasks.md`, `gate.md`, `build.md`: glob-pattern notes for `node --test` and
  `gates/tokens.py`, the preflight outcomes, `stop`, and `blocked`.

### Fixed

- A dependent task no longer starts in the same second its dependency is
  recorded `failed` (seen in the Tetris trial, `docs/retros/`).

## 0.5.0 — 2026-09-13

### Added

- `/gatekit:design` (ADR-0008): design enters at any stage from a Figma
  URL, screenshots, HTML, a live site URL, a preset name or a pattern file,
  into `spec/02-design.md` and `spec/tokens.json` v2 (open token groups,
  machine-readable `P<n>` patterns). Re-running revises instead of
  overwriting and records superseded ledger rows; during a build it reports
  the tasks a change touches and edits neither 04 nor 05.
- Worker briefs carry a generated `## Design` section with the patterns and
  token values the task touches; absent design leaves the brief unchanged.
- `gates/tokens.py`, a task gate: colour literals a worker wrote must be
  design tokens. Exit 0 ok, 1 fail, 3 unverified; `run_gates` now reads
  exit 3 as `unverified`. Colours only at this release.
- `gatekit design merge-preset <name>` and `gatekit design impact`.

### Changed

- `contract derive` records the hashes of `02-screens.md`, `02-design.md`
  and `tokens.json`; `contract status` is `fail` when any of them changed,
  the rule `05-gate.md` already had, and `doctor` names the changed file.
- `spec validate` checks the `tokens.json` shape (warn only) and warns on a
  superseded assumption row that is still the one cited inline.

## 0.4.0 — 2026-09-13

### Added

- `expect` in a `gatekit-criterion` can pin output, not only the exit code:
  `stdout_contains`, `stdout_not_contains`, `stdout_regex` and the `stderr_*`
  forms. Judged over the whole stream after the exit code; an unmet one is
  `fail` naming the expectation. Unknown keys, wrong types and invalid
  regexes are refused by `derive` and reported by `spec validate` through one
  shared validator. "No test was skipped" is now a criterion, not prose; the
  gate command says when to use it.

## 0.3.1 — 2026-09-13

### Added

- `workers check --probe` sends one trivial prompt through the backend's
  `read_only_argv`. A Codex-hosted build failed both tasks with
  "Not logged in" because the sandbox hid the Claude CLI's credentials while
  the plain check said `ok`; the probe reports `fail` with the output tail
  before a job starts. `/gatekit:build` runs it, and the Codex layer's
  AGENTS block and skill notes say to run worker commands with escalated
  permissions.
- `spec validate` warns when `spec/PROGRESS.md` is older than the latest
  terminal task status: a session that ended between the build and the
  progress write leaves a file that claims failure after the tasks passed.

## 0.3.0 — 2026-09-13

### Fixed

- Language detection ignores path and identifier tokens: a Codex session
  switched to English on `src/hello.ts 만들어줘`.

### Added

- Codex CLI as a second host (ADR-0006). The gates read `--host <name>` from
  their argv and render the Stop block in the host's dialect; the write gate
  judges every file an `apply_patch` names; the prompt gate recognises
  `$gatekit-<name>` skill invocations. `gatekit install --host codex`
  generates `.codex/hooks.json`, one skill per command under
  `.agents/skills/gatekit-*` and a managed block in `AGENTS.md`, all from
  `plugin/`, idempotently. `doctor` gains axis 8 over that layer. The README
  carries a host parity table in the verdict vocabulary; the spawn and
  question gates are `unverified` under Codex until observed.
- The evaluator can be a different CLI than the builder (ADR-0007). Backends
  carry `read_only_argv`; `verify.evaluator` names `agent` or a backend;
  `workers set-evaluator` sets it; `jobs evaluate` runs the backend once,
  read-only, with `GATEKIT_TASK_ID=evaluate` so the write gate refuses writes
  inside its session; `/gatekit:verify` branches on the setting.
- Observed in a real Codex 0.154 session and folded back in: shell commands
  arrive as `Bash` events (bash gate confirmed), subagents spawn through
  `collaborationspawn_agent` with an encrypted prompt (the spawn gate allows
  and records `spawn_unscoped`; the subagent's own writes still meet the
  gates), and the parity table says so.

## 0.2.0 — 2026-09-11

### Fixed

- A slash command with no arguments flipped a Korean session to `en`: the
  prompt gate counted the Latin letters of the `<command-name>` tag body as
  the user's words. Language is now detected from `<command-args>` only, and
  empty args keep the stored language.

### Added

- `/gatekit:discover`, an optional first pipeline for the user who does not
  yet know what to build. It collects recent pains, picks one, and fills six
  deepening gates (one named user, the current way as ordered steps,
  frequency, minutes, a cause reached by asking why three times, and what
  was already tried) into `spec/00-discovery.md` as a `gatekit-discovery`
  JSON fence. `spec validate` checks the fence: a missing fence or empty
  problem sentence is `fail`, every unfilled gate is `warn`, and gates the
  user chose to skip are declared in `unpassed` rather than guessed. The
  file's absence is silent (`heading-map.json` `absent_ok`). `interview`
  reads the fence as facts, skips its open probe when the file exists, and
  routes an argument with no real user and no pain to `discover`. Skill
  `gatekit-discover`, ko/en templates, ledger pipeline value `discover`,
  ADR-0005.

## 0.1.1 — 2026-09-11

### Fixed

- The stop gate and the interview question budget never engaged in a real
  session: nothing in production set the ledger's `active_pipeline`, and the
  tests injected it directly. The prompt gate now records the pipeline when a
  prompt invokes `/gatekit:<pipeline>` — in the tagged
  `<command-name>/gatekit:<name></command-name>` body Claude Code actually
  sends, or as a bare invocation (`doctor`/`setup` clear it); entering a
  different pipeline resets the question budget. `gatekit ledger set-pipeline
  <name|none> --session <id>` exposes the same write for debugging. An
  end-to-end test drives the prompt gate and then the stop gate with no
  ledger injection.
- The Bash tool bypassed the write gate entirely: `cat > src/x.ts`, `sed -i`,
  `tee` and `git apply` created files that the Write tool was denied. A sixth
  hook, PreToolUse `Bash` → `gates/bash.py`, judges every path a shell
  command would write with the same function as the Write gate, and denies
  commands whose write targets cannot be determined while a rule is active
  (ADR-0004).
- The Stop hook's `timeout` in `hooks.json` was 60 s while a `gatekit-budget`
  fence may declare up to 600 s: a project that honestly declared a slow
  suite had its stop gate killed mid-run with no verdict and no log line.
  The timeout is now 600 s (the largest value the hook documentation shows)
  and the stop gate caps the contract run at 570 s via a new
  `contract.execute(cap_s=…)` argument, so a cut run reports `unverified`
  instead of vanishing. Tests pin both numbers; the dead `STOP_BUDGET_S`
  constant is gone.

## 0.1.0 — 2026-09-10

Initial release.

### Added

- Session ledger (`gatekit/ledger.py`) tracking output language, active
  pipeline, question budget, declared write scopes, and stop-hook state
  per `session_id`.
- Four-state verdict vocabulary (`ok / warn / fail / unverified`) and
  aggregation rules (`gatekit/verdict.py`).
- Output language detection (`gatekit/lang.py`) — Hangul-ratio based
  `ko`/`en` classification, with `ko`/`en` templates and Korean never
  the default.
- Hash-anchored approvals (`gatekit/approval.py`) for spec files.
- Executable completion contracts (`gatekit/contract.py`) derived from
  `gatekit-criterion` fenced blocks in `spec/05-gate.md`, run under a
  45-second total budget with per-criterion timeouts.
- Task and criterion parsing from fenced JSON blocks in `spec/*.md`
  (`gatekit/spec.py`).
- Job runner and worker backends (`gatekit/jobs.py`, `gatekit/workers.py`)
  supporting the Claude CLI by default and an optional Codex backend,
  with per-task write-scope enforcement via `GATEKIT_TASK_ID`.
- Five hook gates (`prompt`, `write`, `spawn`, `question`, `stop`) wired
  through `plugin/hooks/hooks.json`, each exiting 0 on internal error and
  logging to `.gatekit/runs/hook-errors.log`.
- Seven-axis doctor diagnosis (`gatekit/doctor.py`).
- Eight commands: `/gatekit:interview`, `/gatekit:mockup`,
  `/gatekit:tasks`, `/gatekit:gate`, `/gatekit:build`, `/gatekit:verify`,
  `/gatekit:doctor`, `/gatekit:setup`.
- CI gates (`tools/gate_*.py`) enforcing no absolute personal paths, skill
  and command size limits, a 1 MB blob-size cap, forbidden execution-step
  phrases in skills, manifest/hook/CHANGELOG consistency, and README ↔
  command-list sync, run on Python 3.9 and 3.12.
- `bin/gatekit.py` launcher so every command runs the kernel from the user's project directory; `tools/gate_command_invocations.py` fails CI on any invocation form that cannot run there.
- Doctor axis 2 reads `installed_plugins.json` and `settings.json` structurally: installed-but-disabled is `fail`, not `ok`.
- `spec/05-gate.md` may declare a run-wide budget with a `gatekit-budget` fence (default 45 s, ceiling 600 s), so a slow-but-passing suite is not permanently `unverified` at the stop gate.
- `/gatekit:build` and `/gatekit:verify` start `spec/PROGRESS.md` from the language template and re-validate, instead of writing freehand headings that `spec validate` then rejects.
- `docs/manual/` — a 12-page Korean user manual covering install, concepts, the pipeline, all eight commands, the spec files, the gates, the CLI, a worked example, troubleshooting, security posture and the design decisions.
- `docs/assets/` — three diagrams (pipeline, hook gates, verdict vocabulary) as SVG plus 2x PNG, referenced from the manual pages they illustrate.
- `tools/gate_manual_accuracy.py` keeps the manual from citing commands, subcommands or spec files that do not exist, and `tools/gate_clean_room.py` keeps other projects' names out of this repository.
- `tools/build_manual_bundle.py` packages `docs/manual/` into a Notion import archive (one parent page, one child per file) with the UTF-8 filename flag set so Korean titles survive.
- `plugin.json` does not list `hooks/hooks.json`; Claude Code loads it automatically and a duplicate reference fails plugin load. `tools/gate_manifest.py` rejects the duplicate.


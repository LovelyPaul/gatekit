# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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


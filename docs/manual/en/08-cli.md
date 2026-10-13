# CLI reference

## It must be this form

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" <subcommand> [args]
```

### Why other forms do not work

Commands run **in the user's project directory**. There, the `gatekit` package is not on `sys.path`. So the module-execution form dies with an import error in the project directory.

The `bin/gatekit.py` launcher computes the plugin root from its own location, puts it at the front of `sys.path`, and then calls the dispatcher. Otherwise it behaves the same.

Running after `cd` into the plugin root does not work either. Once the working directory changes, project-root detection and every relative path point at the plugin instead.

The CI gate `tools/gate_command_invocations.py` enforces this rule. If an invocation form that does not run gets into a command or policy file or a spec template (`plugin/spec-kit/templates/`), the build fails.

## 10 subcommands

The `SUBCOMMANDS` registry in `cli.py` is the full list. Modules are imported lazily, so if one breaks, the rest still work.

| Subcommand | Role |
|---|---|
| `doctor` | 8-axis diagnosis of install, hooks, state, workers, and host |
| `spec` | Validate the spec set |
| `contract` | Derive, report status of, and run the completion contract |
| `approve` | Hash-anchored approval |
| `jobs` | Run and manage worker jobs |
| `workers` | Manage worker backends |
| `ledger` | Inspect the session ledger and set the pipeline |
| `install` | Generate the Codex host layer (`--host codex`) |
| `migrate` | Move the state directory to a different name (preview by default) |
| `lang` | Detect the output language |

Called with no arguments, it prints usage and exits with code 1. `-h`, `--help`, and `help` exit 0. An unknown subcommand exits 2.

## doctor

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" doctor [--root PATH] [--json]
```

It gives a verdict on each of 8 axes (plugin files, hook registration, project state, spec set, contract freshness, workers, python, Codex host layer) and a `fix` string for each axis.

| Exit code | Meaning |
|---|---|
| 0 | No axis is `fail` |
| 1 | One or more axes are `fail` |

## spec

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate [--root PATH] [--json] [--lang ko|en]
```

`validate` is the only subcommand. `--root` sets that path as the project root directly. Without it, the root is detected by walking up the directory tree.

| Exit code | Meaning |
|---|---|
| 0 | The verdict is not `fail` |
| 1 | The verdict is `fail` |
| 2 | A subcommand other than `validate` |

## contract

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract derive [--root PATH] [--json]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract status [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract run [--root PATH] [--json] [--budget SECONDS]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract baseline [--root PATH] [--json] [--budget SECONDS]
```

| Action | What it does |
|---|---|
| `derive` | Derives the fences in `05-gate.md` into `.gatekit/contract.json`. Records the source hash and the budget with it |
| `status` | Prints one of `ok` (current) / `fail` (stale) / `unverified` (missing) |
| `run` | Runs each criterion and issues an aggregate verdict |
| `baseline` | Before approval, runs the criteria once and classifies each as `already_passes` (passes before any work) / `not_yet_runnable` (a path some task will create does not exist yet) / `fails` / `command_error` / `unverified` (ran no tests at all, skipped every collected test, or includes a program inside a not-yet-installed `node_modules` or `.venv` when no task creates a manifest), and records the result in `.gatekit/baseline.json`. It runs on the pre-work tree, so files the criteria create (build output, DB files, and so on) stay behind. It does not touch the Stop gate's record (ADR-0022) |

`--budget` overrides the budget declared in the contract.

| Exit code | Meaning |
|---|---|
| 0 | `derive` succeeded, `status`/`run` is `ok`, or `baseline` has no `command_error` |
| 1 | `derive` failed, `status`/`run` is not `ok`, or there is no current contract for `baseline` |
| 2 | Argument error |
| 4 | In `baseline`, a criterion's command itself is an error |

## approve

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve <path> [--note "..."] [--by NAME] [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve check <path> [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve list [--root PATH]
```

`approve <path>` asks nothing and records the current hash. Asking the user with `AskUserQuestion` is the command file's job. Approving `spec/05-gate.md` also records the hash of each criterion's grading files, and `approve check spec/05-gate.md` prints `fail` and writes the path to stderr if the contract was re-derived after one of those files changed (ADR-0023). The write gate looks only at file hashes, so this never blocks a write. Inside a worker (`GATEKIT_TASK_ID` is set), `approve` is refused with exit code 1. `check` and `list` still work. If a worker tries to clear the variable with `env -u GATEKIT_TASK_ID` and run it, the bash gate refuses that command first.

| Exit code | Meaning |
|---|---|
| 0 | Approval succeeded, `list` succeeded, or `check` is `ok` |
| 1 | The target file is missing, an approval was attempted inside a worker, or `check` is `fail`/`unverified` |
| 2 | Missing argument |

## jobs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs start [--tasks id,id] [--backend name] [--parallel N] [--dry-run] [--no-preflight] [--force-retry id,id]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs status [--job ID | --all] [--json]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs wait [--job ID] [--timeout S]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs results [--job ID | --all] [--compact|--json]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs redelegate <task_id> [--job ID]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs stop [--job ID]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs evaluate [--backend name] [--prompt FILE] [--lang ko|en] [--force-read-only-evaluator] [--json]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs clean [--all]
```

`results --compact` prints one line per task: `id state gates_passed/total`. A task that passed only after a gate failed once (including a failed preflight run and failures in earlier jobs) and the grading files that gate's argv points to (test files, the argv[0] script) then changed stays `passed`, but gets `(grading changed after failure: <path>)` in the `status` table and `grading-changed=<path>` in `results --compact`, and is recorded in `grading_changed_after_failure` in `status.json`. The hashes at the time of failure are kept per task in `.gatekit/attempts.json`; on a pass they are compared and then removed. `--force-retry` clears only the failure count and keeps these hashes, so failure → loosened test → `--force-retry` → pass is flagged too. With `--all`, `status` and `results` show every job, oldest first (with `--json`, `{"jobs": [...]}`), and the exit code follows the most recent job's verdict. This is a report; it does not block writes or change verdicts (ADR-0023). `clean` keeps the most recent job by default; `--all` removes everything. `evaluate` uses the backend that `verify.evaluator` (or `--backend`) points to as the evaluator. With trusted project hooks, the Codex backend runs with `--sandbox workspace-write` plus `-c sandbox_workspace_write.network_access=true` (the write gate is the real protection; the network lets the evaluator start the app on localhost); without them, it refuses with the exact command that fixes it. `--force-read-only-evaluator` skips that refusal and forces `--sandbox read-only` as before (ADR-0015). It records into `.gatekit/jobs/<job>/evaluate/` and prints the tail of the response (the verdict table). If the state is not `passed`, every criterion is `unverified`.

Before launching workers, `start` runs each task's gates once first (ADR-0009). If a task already passes, it is recorded as `passed` with no worker, and if it passed while its write scope holds no files at all, it gets a `warn` (the gate may always pass). If a gate command itself is an error (exit code 126 or 127, or output such as `Cannot find module` or `No such file or directory` that points directly at one of the gate's arguments), the job does not start, and it reports the task and gate name with exit code 4. Exit code 2 or higher, or similar output that does not point at an argument, is only a suspicion: it starts and leaves a warning. However, if some task in the same job is set to create the missing path the output points to (for example, `Could not read package.json`) through its `write_scope`, the gate simply cannot run yet, so the job starts without a warning and records that task's name in `preflight.json`. The same holds when a shell or interpreter exits 127 because the script it got as an argument is missing, as in `bash scripts/e2e.sh` or `node scripts/e2e.js`, if some task creates that script (a program that cannot be found at all is still refused). When a missing path is written directly in a gate argument, a `note:` line per task reports that path and the task that will create it. This is because a typo in the path would only surface after that task finishes (it is a notice, not a warning). If `package.json` is missing and no task creates it, the job is refused with exit code 4 and the message names `package.json`. A program that cannot run at all (by name or by path) is also refused if no task creates it. However, a program inside `node_modules`, `.venv`, or `venv`, such as `./node_modules/.bin/playwright` or `.venv/bin/pytest`, is not refused, because the dependencies just are not installed yet. If some task creates `package.json` (or `pyproject.toml`, `requirements.txt`, and so on), the job starts without a warning; otherwise it starts with a warning (ADR-0022). A gate that passed without running any tests (`No tests found`, `Ran 0 tests`, pytest with everything deselected, and so on) and a gate that skipped every test (`3 skipped`, `OK (skipped=3)`, `3 pending` after `0 passing`, and so on, ADR-0022 amendment A) are `unverified`, so they are not treated as passing in advance. `--no-preflight` skips this step. If a task has already reached `max_retries`, `start` refuses to begin (exit code 3, ADR-0014) unless you reset that task's consecutive failure counter (`.gatekit/attempts.json`) with `--force-retry <task_id>`. `redelegate` re-reads the task from the current `spec/04-tasks.md`, writes `task re-read … (gates changed)` in the status line if the gates, instruction, or write scope changed, and checks the same counter, refusing likewise if it is exhausted. `stop` terminates only the workers this job launched (it checks both the pid and the start time) and records running and queued tasks as `stopped`.

Task states are `queued` / `running` / `gating` / `passed` / `failed` / `timeout` / `redelegated` / `stopped` / `blocked`. `blocked` means the task did not run because a task it depends on in the same job is not `passed`. `stopped` and `blocked` are terminal states, not completion.

| Exit code | Meaning |
|---|---|
| 0 | The verdict is not `fail` |
| 1 | The verdict is `fail` |
| 2 | Argument error, unknown command |
| 3 | Retry budget exhausted (`build.max_retries` exceeded) |

## workers

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers list [--json] [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers check <name> [--probe] [--json]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers set-default <name>
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers enable <name>
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers set-evaluator <agent|name>
```

The verdict rules for `check`:

| Verdict | Condition |
|---|---|
| `ok` | On PATH, and `argv[0] --version` exits 0 |
| `unverified` | On PATH, but the version probe failed, errored, or timed out |
| `fail` | Not on PATH, the backend does not exist, or `argv` is invalid |

`enable` refuses if argv contains a sandbox bypass flag and the config entry does not have `"unsafe": true`.

`check --probe` actually sends a one-sentence prompt through the backend's `read_only_argv`. It is the only check that catches, before a build, a backend whose binary exists but cannot answer (not logged in, or the sandbox hides the credentials). An answer is `ok`, a non-zero exit code is `fail` with the output tail, and a timeout is `unverified`. `/gatekit:build` runs this check before it starts a job.

| Exit code | Meaning |
|---|---|
| 0 | Success, or `check` is `ok`/`unverified` |
| 1 | `check` is `fail` |
| 2 | Missing name, unknown backend, unsafe refusal, unknown command |

## ledger

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" ledger show --session <id> [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" ledger init --session <id> [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" ledger set-pipeline <interview|mockup|tasks|gate|build|verify|none> --session <id> [--root PATH]
```

`--session` is required. `show` prints the whole ledger JSON, and `init` prints the path of the file it created. `set-pipeline` records `active_pipeline`. Normally the prompt gate sees a `/gatekit:<pipeline>` call and records it automatically, so you only call this by hand for debugging. Switching to a different pipeline resets the question budget.

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | No ledger for that session |
| 2 | Unknown name for `set-pipeline` |
| 2 | Argument error |

## install

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" install --host codex [--root PATH] [--dry-run]
```

Generates the Codex host layer in the project: `.codex/hooks.json`, `.agents/skills/gatekit-<command>/{SKILL.md,command.md}`, and a managed block in `AGENTS.md`. The source is `plugin/`, and the generated files can be regenerated. Running it twice gives the same result. `--dry-run` only shows the list of files it would write.

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 2 | Unknown host (`claude` is installed as a plugin, so it is not accepted here) |

## migrate

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" migrate [--root PATH] [--to gatekit|gatebound] [--apply] [--json]
```

gatekit will be renamed gatebound after the study cohort ends (ADR-0029). This subcommand moves the project's state directory (`.gatekit/` ↔ `.gatebound/`) to the target name. By default it is a preview and prints only the plan. It changes things only when you pass `--apply`.

- Renames the directory. If git tracks files under it, it uses `git mv`.
- Rewrites lines in `.gitignore` that point to the old directory to use the new name.
- If `.codex/hooks.json` exists, it regenerates the Codex layer; if `AGENTS.md` has only the managed block, it regenerates that block.
- It neither reads nor writes `spec/`. Approvals are tied to the hash of `05-gate.md`, so leave the `gatekit-*` fences as they are. Both prefixes keep being read.
- If the directory already has the target name, it does nothing. Running it twice gives the same result.
- If both `.gatekit/` and `.gatebound/` exist, it refuses. Clean up one first (axis 3 of `/gatekit:doctor` tells you which one the hooks use).

The default for `--to` is the current name (`gatekit`), so it does nothing before the rename. You can rehearse with `--to gatebound`. After the move, the current plugin reads `.gatebound/` as it is.

| Exit code | Meaning |
|---|---|
| 0 | Success, or nothing to do |
| 1 | Refused because both directories exist, or applying failed |
| 2 | Argument error |

## lang

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "text to detect"
```

Prints a single word, `ko` or `en`. Always exits 0.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang --spec [--root PATH]
```

Picks the language from the project instead of from text, following the same precedence as the prompt hook. If the user set the language of the most recently updated session ledger (`.gatekit/runs/`) through a prompt (`lang_source` is `"prompt"`), it prints that `output_lang`. Otherwise it reads the first 40 lines of prose in `spec/01-prd.md` (or `spec/00-discovery.md` if that file is missing or has no signal), skipping front matter, code blocks, table rows, and inline code. If the spec does not settle it either, it prints that ledger's `output_lang`, and if there is none, `en`. Command files first use the `output_lang=` context line that the prompt hook injected this turn, and run this form only when that line is absent (ADR-0026). A command does not know its own session id, so it treats the most recent ledger as this session's. If two sessions in one project receive prompts at the same time, it may read the other session's ledger. Always exits 0.

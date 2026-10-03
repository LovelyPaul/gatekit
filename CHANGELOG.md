# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 0.16.3 — 2026-10-03

Fixes from a review of 0.16.2 (ADR-0026, amended).

### Fixed

- **Doctor's port probe finds a `webServer` that is not an object
  literal.** `webServer: process.env.CI ? undefined : { port: 3100 }` and
  `const webServer = { port: 3200 }; defineConfig({ webServer })` were
  missed. The scan now searches a value for its first `{` or `[` up to the
  value's end and also reads `webServer =` declarations. A `webServer`
  inside a value already read is not read again, so a file of nested
  matches no longer takes seconds.
- **The prompt hook no longer walks the tree on every prompt.** The
  `contract=` scope suffix fingerprinted the project (up to 20 000 files)
  before checking whether the last run had left anything unjudged. It now
  reads the record first and fingerprints only when something is
  unjudged. What it shows is unchanged.
- **The built-in evaluator brief names its scratch directory.** The brief
  `jobs evaluate` uses without `--prompt` said any write is a finding; it
  now names `.gatekit/eval/` as the one exception, as the spec-kit brief
  does.
- **Spec language: frontmatter after a BOM, and only when it closes.** A
  PRD saved with a UTF-8 BOM had its English frontmatter read as prose, and
  a leading `---` with no closing line hid the whole file. A BOM is now
  ignored, and the block is frontmatter only when it closes within 60
  lines; otherwise the `---` is a thematic break.

## 0.16.2 — 2026-10-03

Fixes from a review of 0.16.1 (ADR-0026, amended).

### Fixed

- **A CLI evaluator can write its scratch directory.** The evaluator brief
  sends scratch files to `.gatekit/eval/`, but a CLI evaluator (`jobs
  evaluate`, e.g. Codex) runs under `GATEKIT_TASK_ID=evaluate` with a
  read-only scope, so the write gate denied every Write and Bash target
  there. The write gate now allows `.gatekit/eval/**` inside the project
  root for the evaluator only. Every other path stays denied for it,
  including anything outside the root, and other task ids are unchanged.
  The brief no longer says the write gate allows paths outside the project
  for every evaluator; that holds only for the `agent` evaluator.
- **The spec's language is read from its prose.** A Korean PRD whose first
  lines were mostly an English metric table and a code block read as
  English. The spec fallback now counts the first 40 prose lines
  (headings, paragraphs, list items) and skips YAML frontmatter, fenced
  code, table rows and inline code. An English PRD that names a Korean
  product is still English.
- **A resumed session from before 0.16.1 keeps its language.** Its ledger
  had no `lang_source`, so a language a prompt had set was replaced by the
  spec's on the next bare prompt. Such a ledger now counts as
  prompt-set when it is Korean or has seen a prompt.
- **The `contract=` scope describes a run on this tree.** After edits the
  suffix described an older run, `ok (turn tier; …)` read as a pass even
  when that run had failed, and a record without a scope read as having
  judged nothing. The suffix now appears only for a record on the current
  contract and tree that lists its scope, and reads `contract=ok (last run:
  turn tier, 1 deferred to /gatekit:verify)` (Korean `마지막 실행: turn
  등급만, 1개는 /gatekit:verify 로 미룸`). It names scope, never a verdict.
- **Doctor's port probe reads only the `webServer` block.** It reported
  ports in comments and in later blocks such as `use`, and missed
  `process.env.PORT || 3000`. It now drops comments, reads the `webServer`
  value up to its balanced closing brace or bracket, and takes the literal
  fallback after `||` or `??`.
- **Descriptions match what the commands do.** The build command and skill
  said build spawns a worker per task; by default this session implements
  each task and `jobs complete` runs its gates, with workers on request. The
  discover skill no longer mentions the removed deepening gates. Doctor is
  described with its eight axes, including the Codex host layer, in
  QUICKSTART, the CLI manual page, `commands/doctor.md` and the doctor skill.

## 0.16.1 — 2026-10-03

Fixes from a real rehearsal of 0.16.0: one `/gatekit:build` on a small Korean
project, three follow-up turns, one `/gatekit:verify` (ADR-0026).

### Fixed

- **A bare `/gatekit:build` no longer leaves a Korean project in English.**
  A slash command with no arguments carries no language signal, so the ledger
  kept its blank `en`, and build reports and Stop-gate messages came out in
  English. While no prompt in the session has carried a signal, the prompt
  hook now takes the language from the spec: the first 40 lines of
  `spec/01-prd.md`, else `spec/00-discovery.md`. A prompt that does carry a
  signal still wins, and the session keeps it. The ledger records where the
  language came from (`lang_source`).
- **Doctor warns when the Playwright port is taken.** In the rehearsal
  another project's long-running server held the `webServer` port. With
  `reuseExistingServer: true` the e2e tests ran against that app and failed
  confusingly. Axis 3 (project state) now reads the `webServer` `port:` and
  `url:` values from `playwright.config.{ts,js,mjs,cjs}` (at the root and
  under `spec/design/e2e/`) and probes each port on the loopback interface. A
  listener is `warn`, naming the port and, on POSIX with `lsof`, the
  listener's PID, command and working directory, and whether that directory
  is inside this project. Doctor never stops a process. On Windows only the
  socket probe runs.
- **The context line says what the contract result covered.** The Korean
  stand-down line now uses the manual's terms (`Stop 게이트 물러남`) instead
  of `stop 게이트 해제`. When the last recorded result did not judge every
  criterion, `contract=` adds the scope: `contract=ok (turn tier; 1 deferred
  to /gatekit:verify)`, or `N unjudged` after a Stop-budget cut, in
  `output_lang`. On its own, `contract=ok` only means the contract matches
  the approved gate file.
- **The evaluator keeps its scratch files in the project.** The verify
  evaluator wrote a driver script, a server log and screenshots to `/tmp`.
  The evaluator brief now says scratch files go only under `.gatekit/eval/`
  and nothing is written outside the project. This is an instruction, not an
  enforcement mechanism.

## 0.16.0 — 2026-10-03

The Stop gate stops costing the session after the build is over (ADR-0024).
Measured on a real 10-task build: coding took 50 minutes, then the session ran
3 h 47 min more, 64% of it re-running the full completion contract at every
turn end — Q&A turns and unplanned follow-up features included — because the
build pipeline never ended.

### Changed

- **The Stop gate stands down after the build.** While a build job is
  unfinished it judges as before; once the job's last task is settled it
  judges one handoff, and when that verdict is recorded (a pass, or the
  final verdict after three blocks) it stops running the contract for the rest
  of the session. `/gatekit:build` or `/gatekit:verify` re-arms it. The prompt
  context line says follow-up edits are not gated and `/gatekit:verify`
  re-checks. A settled job with a failed or blocked task is not a handoff
  pass; a job left with queued tasks keeps the gate judging, and the context
  line names `jobs stop`.
- **Criterion tiers.** A `gatekit-criterion` may set `"tier": "verify"` (default
  `"turn"`). The Stop gate during a build runs only `turn` criteria and lists
  `verify` ones as deferred, never as passed; `contract run`, `/gatekit:verify`
  and `contract baseline` run every tier. The approval table shows the tier,
  and `spec validate` warns when no criterion is `turn` or the screenshot
  criterion is `verify`. Guidance: the full regression suite that repeats the
  task gates belongs in `verify`.
- **A Stop-gate budget, `stop.budget_s`** (default 120 s, at most 570 s). The
  Stop gate starts no criterion past it. A run cut short is `unverified`,
  never a pass, never stands the gate down and never blocks; the next turn end
  runs the unjudged criteria first and, on an unchanged tree, keeps what was
  already judged. A criterion that ran and failed, timed out or ran no tests
  still blocks. A cut run's result is never reused as a full judgement.
- **A worker cannot approve through the shell.** Inside a worker session (`GATEKIT_TASK_ID` set), the Bash gate denies any command that runs `gatekit approve`, including `env -u GATEKIT_TASK_ID python3 …/gatekit.py approve …`, quoted or `${CLAUDE_PLUGIN_ROOT}` paths, `-m gatekit`, `sh -c`, `eval` and `xargs`. `approve check` and `approve list` stay allowed (ADR-0023).
- **`--force-retry` keeps the failed grading hashes.** It resets a task's failure count and repeats, but a task that fails, has its test loosened, is force-retried and then passes is still flagged `grading changed after failure`.
- **gatekit's own `spec/` folder is not a test directory.** Under the top-level `spec/`, only test-shaped names (`*_spec.*`, `test_*`, …) count as grading files. Updating `spec/tokens.json` or `spec/02-design.md` after approval no longer holds back the criteria that read them.
- **Host builds call `jobs complete` once.** `/gatekit:build` no longer pre-runs a task's gate commands before `jobs complete` runs them again (measured 24–62 s per task, paid twice).
- **Cheaper e2e task gates.** Task-gate guidance now recommends running only the task's spec on one viewport (`--project mobile`) against one reused server (`reuseExistingServer`). Task e2e gates that ran every project cost about 299 s per full pass.
- **A "tasks not passed" block names the right rerun:** `jobs complete <task>`
  under host execution, `jobs redelegate <task>` under worker execution.

### Fixed

- **A ledger whose `stop` record is not an object no longer disables the Stop
  gate.** It is replaced by a blank record instead of making every Stop fail
  open silently.

## 0.15.0 — 2026-10-03

gatekit notices when the files that grade the work change (ADR-0023). Nothing
is blocked: refining a gate or a test mid-build keeps working.

### Changed

- **A criterion whose test file changed since approval is `unverified`.**
  `contract derive` hashes each criterion's grading files: argv[0] when it is
  a script path, and every argv file that looks like a test (under `test/`,
  `tests/`, `__tests__/`, `spec/` or `e2e/`, or named `test_*`, `*_test.*`,
  `*.test.*`, `*.spec.*`, `*_spec.*`, `conftest.py`; the lists are in
  `plugin/spec-kit/grading-patterns.json`). Source files a check inspects
  (`grep -q print src/app.py`, `sqlite3 app.db`), build output and installed
  dependencies never count. `--opt=path` values count; pytest `[param]` and
  `file:line` suffixes are dropped. If a grading file changes or disappears
  afterwards, a criterion that would pass is `unverified` with "grading file
  changed since approval (if intended, re-run /gatekit:gate to re-approve;
  otherwise revert it): <paths>". A failing criterion stays `fail`. A command
  that names no file (`npm test`) or only a directory or glob is not
  covered; name the test file in argv to cover it.
- **Approving `05-gate.md` also pins those files.** Re-deriving after a test
  edit does not clear the hold: `contract run` and the Stop gate report
  `grading_unapproved`, and `approve check spec/05-gate.md` prints `fail`
  and names the paths, until `/gatekit:gate` re-approves. A test written
  after approval is not held back. The write gate still looks at the file
  hash alone, so no write is blocked.
- **A worker cannot approve.** `approve` exits 1 when `GATEKIT_TASK_ID` is
  set; `approve check` and `list` still work.

### Added

- **Tasks that pass only after their own test changed are flagged.** Each
  gate in `gates.json` records the hashes of its grading files. A failing
  gate's hashes are kept per task in `.gatekit/attempts.json`, from any job
  and from preflight, until a pass or `--force-retry`. When the task passes
  and a file of a gate that failed has changed since, that job's
  `status.json` records `grading_changed_after_failure`. `jobs status`
  appends `(grading changed after failure: <paths>)` and `results --compact`
  appends `grading-changed=<paths>`, and `/gatekit:verify` reports it as a
  warning: "passed only after its own test changed — review the diff of
  <paths>". The task stays `passed`. This works the same for worker
  attempts, `redelegate`, `jobs complete`, `jobs recheck` and preflight.
- **`jobs status --all` and `jobs results --all`** show every job, oldest
  first (`--json`: `{"jobs": [...]}`); `/gatekit:verify` reads them so a
  flag from an earlier job is not missed.
- The Stop gate adds a hint line in `output_lang` naming every changed
  grading file in full, since its reason lines are cut at 120 characters.
  `/gatekit:gate` and `/gatekit:build` say what to do when one changed.

## 0.14.0 — 2026-10-03

Gates that cannot run yet stop looking broken, a run of zero tests stops
counting as a pass, and `/gatekit:gate` sees each criterion's state before
approval (ADR-0022). Found on a real job where 7 of 10 tasks warned about a
`package.json` the first task was about to create.

### Changed

- **A missing path that a task will write is not an error.** When a failing
  gate names a missing path (`ENOENT … open '<path>'`, `No such file or
  directory`, `can't open file`, pytest's `file or directory not found`,
  node's `Cannot find module './…'`) and some task in the job has it in its
  `write_scope`, preflight starts and `preflight.json` names that task.
  `bash scripts/e2e.sh`, `node scripts/e2e.js` and `python3 scripts/x.py`
  on a script that a task writes are no longer refused, including bash's
  exit 127; a program that is not found at all still is. When the gate
  names that path in its own arguments, `jobs start` prints one `note:` line
  per task naming the path and the task that writes it, because a typo
  there now shows only after that task runs. npm missing a `package.json`
  that no task writes is refused with exit 4 and the message names
  `package.json`. A refusal for a missing script names the path and says no
  task writes it. A program that cannot be started at all and that no task
  writes, bare name or path, is refused too; before, preflight saw no output
  for it and started silently. A program inside `node_modules`, `.venv` or
  `venv` (`./node_modules/.bin/playwright`, `.venv/bin/pytest`) is not
  refused: it starts silently when a task writes `package.json` (or
  `pyproject.toml`, `requirements.txt`, …) and with a warning otherwise. `..` segments and symlinked prefixes (`/var` vs `/private/var`)
  in a message no longer hide the owner.
- **Zero tests is `unverified`.** A gate or criterion whose runner ran no
  tests is `unverified` with `ran no tests (<runner>)`, not `ok`. This
  covers pytest, unittest, jest, vitest, Playwright, `node --test`, mocha,
  `go test` and `cargo test`. It never applies when the output also reports
  a positive count. pytest's and unittest's exit 5 ("no tests ran") are
  `unverified` too, and so is pytest's exit 5 when every test was
  deselected (`-k` that matches nothing). ANSI colour in the output does not
  hide a match, and `go test` lines with `coverage:` count as a real run.
  Preflight no longer skips such a task, and the Stop gate no longer counts
  it or reuses a result recorded before 0.14.0. The signatures live in
  `plugin/spec-kit/no-tests-signatures.json`; a malformed file or entry is
  skipped rather than breaking a gate run.

### Added

- **`gatekit contract baseline`.** It runs the criteria once before approval
  and classifies each as `already_passes`, `not_yet_runnable`, `fails`,
  `command_error` or `unverified`. Results go to `.gatekit/baseline.json`,
  and the command exits 4 on a `command_error`. `/gatekit:gate` shows the
  classes in the approval table and flags criteria that pass before any
  work. The same run is the budget measurement `gate-criteria.md` asks for;
  it runs again after a budget edit so `baseline.json` always matches the
  approved file. It runs against the pre-work tree, so anything a criterion
  creates there stays. It never writes the Stop gate's `contract-last.json`.

## 0.13.1 — 2026-10-03

`jobs complete` is held to the retry budget, and a task that fails the same
way twice stops early (ADR-0021).

### Fixed

- **`jobs complete` refuses past `build.max_retries`.** Host execution, the
  default, counted every failure but never refused one, so a session could
  fail a task indefinitely inside one job. It now refuses before running any
  gate, with exit 3 and the same pointer to `spec/RECOVERY.md` and
  `jobs start --force-retry <id>` that `redelegate` gives.
- **The `spec/RECOVERY.md` template states the limit the code enforces:**
  three consecutive failures of one task by default (the first attempt plus
  `max_retries` retries), not three redelegations.
- **Parallel tasks no longer lose each other's attempt records.** Workers in
  one wave wrote `attempts.json` without a lock, so concurrent failures or a
  pass could overwrite one another. The read-modify-write is now serialised
  within a process; the cross-process case is an open question in ADR-0021.

### Added

- **Identical failures stop early.** `.gatekit/attempts.json` records a hash
  of the failing gates' output (`last_failure_sha`) and how many consecutive
  failures shared it (`repeats`). Timestamps, clock times, durations, hex
  addresses, the project root and trailing whitespace are ignored; numbers
  are not, so "3 failed" and "2 failed" differ. Two identical failures in a
  row make `redelegate`, `complete` and `start` refuse with exit 3 whatever
  budget is left, pointing at whether the gate or the instruction is wrong.
  `build.max_retries: 0` still disables every refusal; `--force-retry` still
  clears the task. `jobs status` shows `(n consecutive, same failure)`.

Existing `attempts.json` files keep working; their entries simply have no
fingerprint until the next failure.

## 0.13.0 — 2026-10-01

Verification stops costing minutes per turn (ADR-0020). Found on a real
10-task build whose Stop gate ran a 26-criterion contract nine times in one
session, each run up to 570 s.

### Changed

- **The Stop gate reuses its last result when nothing changed.** Each run is
  recorded with the contract's hash and a fingerprint of the project tree
  taken after the run (ignoring `node_modules`, build output, `test-results`,
  `*.tsbuildinfo`, `spec/PROGRESS.md` and declared artifacts). A Stop with
  both unchanged judges that result again and says so; any change runs the
  contract, last run's failing and unverified criteria first. `contract run`
  always executes, and records its result so the Stop ending a
  `/gatekit:verify` turn does not repeat it.
- **`/gatekit:gate` derives criteria by runner invocation, not per task.**
  One E2E suite criterion on a single viewport, one wiring criterion, one
  screenshot criterion listing every UI task's `build-<task-id>.png`, plus
  the cheap static checks. For a Next.js app that is about three Playwright
  processes instead of twenty-one cold `next dev` starts. The rules also say
  to measure a `contract run` before declaring a budget and to boot the app
  once. They now live in `plugin/spec-kit/gate-criteria.md`.

Existing `spec/05-gate.md` files are not rewritten; the new derivation
applies the next time `/gatekit:gate` runs.

## 0.12.0 — 2026-10-01

One plugin tree for the Claude desktop app, Codex's plugin system and
Windows, in the same repository and release (ADR-0019).

### Added

- **Codex plugin install.** `codex plugin marketplace add LovelyPaul/gatekit`
  then `codex plugin add gatekit@gatekit` installs the same `plugin/` folder
  Claude Code uses. The hooks also match Codex's tool names (`apply_patch`,
  `collaborationspawn_agent`) and answer in Codex's dialect when Codex runs
  them (detected from `PLUGIN_ROOT`); every skill tells a host without slash
  commands where its command file is, and `policy/codex.md` carries the
  Codex differences. Codex runs plugin hooks only after the user trusts them
  in a terminal `codex` → `/hooks` session — the desktop app cannot record
  that trust today (openai/codex#47283) — and `doctor` now reports an
  untrusted install as `warn` with that fix. `gatekit install --host codex`
  keeps working for existing projects.
- **Windows (preview).** Hooks try `python3`, then `python`, then `py -3`;
  hook stdio is UTF-8 whatever the console encoding; criteria, task gates
  and worker spawns find `npm.cmd`/`claude.cmd` through `shutil.which`;
  `jobs stop` uses `tasklist`/`taskkill` (on Windows `os.kill(pid, 0)` ends
  the process it was meant to probe); Git Bash's `/c/…` paths are read as
  `C:/…`. CI now runs the whole suite on `windows-latest`. No real Windows
  host session has been observed yet, hence "preview".
- README and the install manual cover the Claude desktop app
  (**+ → Plugins → Add plugin**; opening the gatekit repository itself is not
  an install and runs no gate).

### Fixed

- A gate that failed in a project with no `.gatekit/` created one to hold
  its error log, after which every later gate treated the project as managed.
  It now logs nothing there.
- `jobs stop` landing between a task's "running" status and its spawn had no
  pid to signal and let the worker run to its timeout; the spawn now honours
  the stop itself.
- After `jobs stop`, finishing the job could erase `stopped_at` when a read
  of `job.json` failed mid-replace (seen on Windows); the merge retries.
- The generated Codex command copy mixed path separators on Windows.

## 0.11.3 — 2026-09-30

Three defects found by running the whole pipeline for a new project from a
session opened in another folder (ADR-0018).

### Fixed

- **The documented token-gate command now runs.** `task-gates.md` tells
  `/gatekit:tasks` to write `python3 "${CLAUDE_PLUGIN_ROOT}/gatekit/gates/tokens.py" …`,
  but task gates and completion criteria run without a shell, so the token
  reached Python literally and every such gate failed with exit 2
  (`can't open file '<project>/${CLAUDE_PLUGIN_ROOT}/…'`). gatekit now
  replaces that one token with the plugin directory before running a gate or
  criterion; nothing else is expanded, and the stored fence stays portable.
- **A missing `05-gate.md` is a `warn` until `/gatekit:gate` writes it.**
  `spec validate` reported it as a `fail` from `/gatekit:discover` onward —
  four stages before the one that creates it. Code stays locked by the
  approval check and the write gate exactly as before.
- **The spec-before-code write gate no longer blocks paths outside its
  project.** While a project's gate was unapproved, every write anywhere
  else on disk was denied — a session's scratch files, and a new project's
  own folder and `spec/` files — so the user had to run those commands by
  hand. The rule now governs only targets inside the project root. A worker
  running a task is still refused every write outside the root.

## 0.11.2 — 2026-09-27

gatekit installs globally but was acting locally in the wrong places: its
gates ran in projects that had never asked for them.

### Fixed

- **Gates no longer act in projects gatekit does not manage.** The plugin
  installs globally, so its hooks fire in every project the user opens — but
  no gate checked whether the project had ever run a gatekit command. The
  spawn gate was the visible damage: it denied *every* subagent in every
  unrelated project, demanding a `gatekit-scope` fence for work gatekit was
  never asked to govern. Observed in a `knowledge-base` project, where three
  consecutive Explore agents were refused before one got through.

  Three more gates were quieter about it: `prompt`, `question` and `stop`
  each created a `.gatekit/` directory and a session ledger in whatever
  project they landed in, and the prompt gate injected its
  `output_lang=… | pipeline=none | no gate spec` context line into every
  prompt of every unrelated project.

  All four now stand down when the project has no `.gatekit/` directory:
  they allow without reading further and write nothing. Enforcement inside a
  real gatekit project is unchanged. `docs/ARCHITECTURE.md` §3 states the
  precondition for every gate.

## 0.11.1 — 2026-09-27

0.11.0 met the Codex host for the first time. Two things it got wrong there,
both found in a real session rather than by reading the code.

### Fixed

- **A bare `"1"` no longer switches the output language to English.** The
  prompt gate refreshed `output_lang` from any prompt containing a
  non-space character, and `lang.detect` returns `en` whenever it finds no
  letters at all — so answering a numbered list with `1` overwrote a stored
  `ko`. That is the *normal* path under Codex, which has no
  `AskUserQuestion` and asks its options as numbered plain chat: a Korean
  interview flipped to English on the first answer and re-confirmed English
  on every later number, ignoring requests to switch back. The session
  ledger from that run shows eight one-character prompts and
  `output_lang: en`.

  `lang.carries_signal()` now separates "no evidence" from "evidence of
  English" — `detect` alone cannot, since it has to return one of the two
  either way — and the gate keeps the stored language unless the prompt
  actually carries a signal. Numbers and bare paths keep it; real words in
  either language still switch it. Verified on a follow-up Codex run:
  thirteen one-character answers, `output_lang` still `ko`.

- **Domain research no longer routes around a missing search tool.**
  `interview` declares `WebSearch` in `allowed-tools`, which the Codex layer
  copies verbatim, and the research step says to run it. Codex has no such
  tool, so it spawned a subagent to "research" from memory instead (the
  ledger records `spawn_unscoped`, task `research_review`). A proposal with
  no source is exactly what that step exists to prevent. The generated skill
  and `AGENTS.md` now tell the model to say the tool is missing and ask
  whether to skip the step or take findings the user pastes.

### Changed

- Both host-parity tables gain rows for the domain-research behaviour above
  and for the `compact` gate, which the Codex layer has never installed (no
  `PreCompact`-equivalent event is known for Codex) and which neither README
  mentioned.

## 0.11.0 — 2026-09-27

Four real projects went through the pipeline (`gk-trial2`, `gk-todo`,
`gk-todo4`, `gk-todo5`). Two of them were abandoned mid-way for the same
reason: the interview was too shallow, so the spec shipped without features
the owner considered obviously necessary, and the first look at a real
screen came only after the build. This release is mostly about that gap.

### Changed

- **`/gatekit:discover` and `/gatekit:interview` are free-ranging
  conversations** (ADR-0017). No named gates, no fixed question slots, no
  progress counter, no question ceiling — the interviewer asks whatever the
  last answer makes worth asking, and a post-hoc summary is confirmed with
  the user rather than filled in live. The earlier six-gate script was found,
  against real runs, to produce a scripted interrogation instead of an
  interview.
- **`/gatekit:interview` now researches the product category and proposes
  what the conversation never raised** (ADR-0017 decision 24). It freezes
  the features the conversation established — the product's own reasons for
  existing, never edited by what follows — then searches four angles
  (standard features, user complaints, leading examples, technical
  postmortems), keeps only candidates two independent sources corroborate,
  and presents them in two labelled groups for the user to prune. The user
  cuts from a fuller draft instead of filling a blank form.
- **`build.execution` defaults to `host`** (applying ADR-0013 decision 1,
  which shipped in 0.8.0 everywhere except the line that decides it). A
  worker is a cold session of the same model, re-deriving the project per
  task; on the run that measured this, 26 minutes of work took 4.5 hours
  across 35 spawns. Spawn a worker when the model must genuinely differ, or
  when a round is wide enough for parallelism to pay. Set
  `"execution": "worker"` explicitly for the old behaviour.
- **A task's gate must test what that task builds.** Pointing several tasks
  at the whole suite let a real trial record three features as complete with
  no code written for them: the first feature's tests made the shared gate
  pass, so preflight skipped every worker. The whole suite keeps its place
  in `spec/05-gate.md`, where "does everything hold together" is the actual
  question.
- **Command files hold the skeleton; their long-form procedures live in
  `policy/` and `spec-kit/` data files.** Seven commands had grown past the
  160-line limit `ARCHITECTURE.md` §0 sets to stop a command from becoming a
  second product beside its skill shim. Nothing was cut — the duplicated
  conversation rules in discover and interview are now one shared file.

### Added

- **A prototype confirmation gate before `/gatekit:tasks`** (ADR-0017
  decision 4). For a UI-bearing project, `/gatekit:mockup` builds a real
  clickable prototype filled with realistic sample content, revises it with
  the user, and asks explicitly whether anything is missing. `spec validate`
  refuses to let tasks proceed until `02-screens.md` records the
  confirmation — so the first look at a screen happens before the build, not
  after.
- **A verdict gate on discovery** (ADR-0017 decision 2). Each improvement
  opportunity carries a model-proposed `verdict_suggested` and a
  user-confirmed `verdict`; a confirmed `eliminate` or `reuse` blocks
  `/gatekit:interview` rather than letting the pipeline build something that
  should not be built. `unknown` never blocks.
- **Screenshot evidence and `-visual` verdicts** (ADR-0017 decisions 9, 22).
  UI tasks leave `spec/design/build-<task-id>.png`; the verify evaluator
  reads those images against the design direction and a seeded
  anti-pattern list. The contract aggregate counts code criteria only, so a
  clean aggregate is never reported as a pass while a `-visual` verdict
  fails.
- **`Blocking` / `Confirmed` columns on every assumption ledger row**
  (ADR-0017 decisions 5, 22). The bar is "would being wrong here hurt a core
  feature's actual quality," not "would the whole plan collapse"; a blocking
  row left unconfirmed fails validation and `/gatekit:gate` refuses to
  proceed.
- **Three seed design presets** (`shadcn-neutral`, `editorial-warm`,
  `tool-dense`) so a project with no design source picks a direction instead
  of defaulting to unstyled browser output.
- **YAML frontmatter on every spec-kit template**, so a written file's
  title, date, and status are readable without opening the body.

### Fixed

- `gate_no_abs_paths` scanned every file on disk despite being documented as
  scanning tracked files, so it failed on git-ignored trial artifacts
  locally while CI stayed green. It now asks git what is tracked.
- `SECURITY.md` carried a placeholder contact address; vulnerability reports
  now go through GitHub's private reporting.
- Both READMEs still described the Claude CLI as the default build worker
  and opened with a stale `0.1.0` status line.
- The Korean user manual described the six-gate discovery script, a
  two-question interview ceiling, six hook gates (there are seven — `compact`
  was undocumented), and no prototype gate. Rewritten against the code, and
  reoriented from "what the system does" to "what you do".

## 0.10.0 — 2026-09-18

The `gk-trial2` retrial's Codex evaluator run: exit 0, 111 seconds, and 12 of
18 criteria came back `unverified` for one repeated reason — `--sandbox
read-only` blocks a test runner's own scratch writes (Vitest's config cache,
Playwright's `test-results/`), not just source edits.

### Fixed

- `jobs.evaluate` under Codex now runs `--sandbox workspace-write`, relying
  on the write gate (a project hook) as the real protection instead of the
  read-only sandbox — but only once Codex has actually recorded trust for
  this project's `.codex/hooks.json`. Verified this was silent, not loud: a
  trusted *project* (`trust_level = "trusted"`) with zero `hooks.state`
  entries for its hooks file still has every project hook skipped by Codex
  without any error, so switching to `workspace-write` with no other change
  would have been a code-writing session with nothing watching it.
- `hosts.codex_hooks_trusted(root)` checks `$CODEX_HOME/config.toml`
  (`tomllib` on 3.11+, a narrow fallback reader for 3.9/3.10) for a
  `hooks.state` entry matching this project's hooks file; any parse failure
  or missing file reads as not trusted. Untrusted and unforced,
  `evaluate` raises `EvaluatorSandboxError` naming the one-time fix
  (`codex exec --sandbox workspace-write "echo trust-check"`, run once by
  hand to approve the hook-trust prompt) rather than silently falling back
  to a mostly-`unverified` report. `--force-read-only-evaluator` keeps the
  stricter sandbox on request. `.codex/hooks.json` is installed
  automatically when absent — installing a file is safe and reversible;
  granting trust is not, and stays a human's decision.
- `job.json.backend.read_only` previously hardcoded `true` for every
  evaluator run regardless of which sandbox actually ran; it now reflects
  the sandbox `evaluate` chose.

Verified against the real `gk-trial2` project, whose Codex hooks were
installed but not yet trusted: `evaluate(root, backend_name="codex")`
raises `EvaluatorSandboxError` with the exact remediation text.

1047 tests pass.

## 0.9.1 — 2026-09-18

A real retrial of `gk-trial2` on 0.9.0 with `build.execution: host`: the same
nine tasks that took 4.5 hours across 25 jobs on 0.7.0 finished in **one job**,
roughly 2m32s wall clock — eight tasks passed at preflight with no worker
spawned, one was implemented by the host session, and the completion contract
ran in 16.2s. `verdict=ok`, all nine tasks `passed`.

### Fixed

- `job.json.finished_at` was never stamped under `build.execution: host`.
  Worker-mode `start()` drains its loop and calls `_finalise_job` when done;
  host mode returns the plan immediately after `preflight`, so nothing ever
  finalised the job — found because the retrial's own `job.json` showed no
  `finished_at` despite every task passing. `status()` now stamps it itself,
  the first time it observes every task as terminal.

## 0.9.0 — 2026-09-17

ADR-0013's first open question, closed the same day it was raised.
`build.max_retries` was meant to stop a task that keeps failing, but
`status.json.attempt` resets on every `jobs start`. Replaying the real
`gk-trial2` job history: one task (`e2e-full-flow`) failed **eight times**
across ten jobs, climbing to attempt 3 and resetting three separate times,
and the budget never fired once.

### Added

- `.gatekit/attempts.json` counts consecutive failures **per task**, across
  jobs. `passed` resets a task's count to zero; `blocked`/`stopped` leave it
  alone, since neither judges the work. Both `jobs start` and
  `jobs redelegate` now refuse a task at the limit (exit 3), where before
  only `redelegate` checked, and starting a fresh job was exactly how the
  budget was escaped.
- `jobs start --force-retry <task_id>[,<task_id>...]` clears one or more
  tasks' counts once the cause is actually fixed.
- `jobs status` reports each task's carried failure count, and the table
  prints `(n consecutive)` whenever it is nonzero — a task at "attempt 1" in
  a fresh job that has already failed elsewhere no longer reads as untried.

### Changed

- `execute_task` and `jobs complete` (host execution, ADR-0013) both feed the
  new counter — a host-implemented attempt counts exactly as a worker's does.
  `jobs recheck` does not: re-running a gate against existing code is not an
  attempt at the work.
- `build.md` states the budget as code-enforced across jobs rather than an
  operator's own count, and documents `--force-retry`.

Verified by replaying `gk-trial2`'s actual job history through the new
counter: `jobs start` now refuses before the run's **third** consecutive
`e2e-full-flow` failure — the real run's other seven attempts, and roughly
two hours, never happen.

## 0.8.0 — 2026-09-17

Measured on a real project (`gk-trial2`, a Next.js + Prisma + Playwright
build): nine tasks whose successful worker output totalled **26 minutes** took
**4.5 hours** of wall clock across 25 jobs and 35 worker spawns, and the
completion contract that judges the result runs in **13.7 seconds**. Only 7 of
those 35 spawns actually failed. ADR-0013 is the response.

### Added

- `jobs recheck [task ...]` re-reads the current `spec/04-tasks.md` and runs a
  task's gates against the working tree — no worker, no new job. A gate names
  files and commands that do not exist until the work is done, so refining one
  mid-build is the normal case; it accounted for 28 of the 35 spawns.
  Rechecking all nine trial tasks takes **6.9 seconds**.
- `build.execution` chooses who implements a task. Under the new `host` mode
  `jobs start` prepares the job, returns an ordered `plan` and spawns nothing;
  the session implements each task and calls `jobs complete <id>`, which runs
  the same gates and writes the same `status.json` a worker's exit would. A
  worker is a cold session of the same model, so it is now reserved for a
  differing model or a genuinely wide round.
- A `PreCompact` hook stamps the live build state into `spec/PROGRESS.md`
  before the conversation is summarised, and the prompt injection names the
  live job on return. Host execution puts a build in one session, so a
  compaction is routine rather than exceptional.
- `jobs shape` reports tasks, rounds, waves and dependency links with no
  evidence in the instruction, plus the round total that dropping them gives.
  `/gatekit:tasks` shows it and asks before writing the file. On the trial
  spec: 9 tasks / 7 rounds, three unevidenced links, **3 rounds** without them.

### Changed

- `verify.evaluator` no longer defaults to `agent`. Unset now resolves to an
  enabled backend whose name differs from the host, so the grader is not the
  model that wrote the code; with none, it falls back to `agent` **and says
  why**, in `workers list` and in `/gatekit:verify`'s report. On the trial the
  field was left alone, so Claude graded Claude. An explicit setting still
  always wins.
- `spec validate` warns when a task writes only test material and its
  transitive dependency reach is two or more — a check that passes only once
  several tasks are done is a criterion in `05-gate.md`, not a task. The
  trial's `e2e-full-flow` failed five times as a task and its command already
  sat in the gate file.
- `build.md` and `tasks.md` rewritten accordingly: build's opening rule is now
  conditional on `execution`, failures route to `recheck` when the gate moved
  rather than to `redelegate`, and the three-failure stop is stated as binding
  across jobs since `max_retries` resets on every `jobs start`.

### Fixed

- `jobs stop` and the draining runner each wrote `job.json` from a snapshot, so
  whichever wrote last dropped the other's field. Surfaced by CI on Python 3.9
  during the 0.7.0 release; 3.13 loses the race the other way and had hidden it
  through three releases.
- `_opt` read an option's value without consuming it, so scanning for bare
  arguments took `--root`'s path as a task id.

### Compatibility

Existing projects keep their behaviour: `config.DEFAULTS` carries
`build.execution = "worker"`, so only a project that sets `host` runs
in-session, and an explicitly configured evaluator is never overridden.

## 0.7.0 — 2026-09-17

### Added

- Design preview (ADR-0011): when `/gatekit:mockup` had no design source to
  read, it offers to draw `spec/design/preview-<project>.html` from the screen
  spec and `tokens.json` — static, tokens-only, opening with a banner saying
  the screens were drawn rather than observed. Corrections are applied to
  `spec/02-screens.md` and the preview redrawn from it; nothing is recorded as
  approved and no assumption closes.
- The worker brief now carries a `## Screens` block (ADR-0011) built by code
  from `spec/02-screens.md` — the layout line and state rows for each `S<n>` a
  task names, matched the same way the `P<n>` design patterns already were.
  Previously only tokens and patterns were pushed and layout was a pointer, so
  a correction made at preview time reached a worker only if it opened the
  file. Copied prose is clipped per paragraph and per block.
- Question signals beyond the raw count (ADR-0012). Past the two free
  interview calls a command must write `ledger.questions.justification` — one
  line naming what it would write differently depending on the answer — which
  the call consumes; a call without one records `unjustified`. A justified
  call followed by no write records `unrealized`; a question that fingerprints
  onto an earlier one records `repeated`; a call whose options are all code
  tokens records `implementation_choice`. All informational, none block.

### Changed

- `spec validate` fails when an evidence cell in `02-screens.md` or
  `02-design.md` cites a `preview-*.html` file, and `/gatekit:design` refuses
  one as input: a drawing made from the spec cannot be evidence for it.
  Remote URLs and rows inside fenced blocks are spared.
- The prompt injection reports the new question signals when any is non-zero:
  `questions=6/2 (2 unjustified, 1 repeat)`.
- `policy/questioning.md` states the budget as a threshold rather than a
  ceiling, and its over-questioning guard gains one condition: a question that
  asks the user to arbitrate a choice the command was better placed to make.

### Deferred

- Build visibility (ADR-0010) is drafted and parked. Elapsed time, `--watch`
  and a file-activity hint are designed but unimplemented: the evidence is one
  abnormal build, so the ranking inside it is inference. One finding stands
  regardless — `output.txt` cannot be tailed for progress, because the default
  backend emits a single JSON object only at exit.

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


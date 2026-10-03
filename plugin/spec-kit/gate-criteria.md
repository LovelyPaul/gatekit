# Deriving completion criteria

Read by `/gatekit:gate` Step 2. It says how many criteria to derive, what
each must satisfy, and how the screenshot criterion is built.

**Derive by runner invocation, not by task (ADR-0020).** Every separate
process that boots the app — a test runner whose `webServer` starts a dev
server, a browser — pays its start-up again, and the Stop hook runs the whole
contract inside a 570-second cap. One criterion per task multiplies that cost
by the task count: a real 10-task build spent most of its time on cold
`next dev` starts and left 17 of 26 criteria unrun. So, for a project with an
E2E runner:

- **one suite criterion** runs the whole E2E suite once, on a single viewport
  project (`npx playwright test --project <one project>`); it covers the
  acceptance criteria in 01 that the suite's specs exercise
- **one wiring criterion** drives the app end to end across features (Step 3
  explains why it is required)
- **one screenshot criterion** (below) captures every UI task's screen in a
  single run
- **cheap static criteria** stay as they are: typecheck, unit tests, a TODO
  scan, the token gate over `src/**`

Add a per-spec criterion only for an acceptance criterion the suite does not
cover, or when the measured suite cannot finish inside the budget as a whole.
A project without an E2E runner keeps one criterion per acceptance criterion
in 01, plus one per task in 04 whose completion is not already covered. Each
is a ` ```gatekit-criterion ` fence:

```json
{"id": "e2e-suite", "argv": ["npx", "playwright", "test", "--project", "mobile"],
 "expect": {"exit": 0, "stdout_not_contains": ["skipped"]}, "timeout_s": 240, "artifacts": []}
```

Requirements:

- `id` unique. **Every task id in 04 must appear somewhere in this file** so
  traceability holds — in the criterion's own id, in an artifact path such as
  `spec/design/build-<task-id>.png`, or in the prose naming what the suite
  criterion covers
- `argv` a non-empty list of strings, run without a shell — no `&&`, no pipes,
  no redirection. Chain steps by adding more criteria instead.
- `timeout_s` realistic. The run-wide budget defaults to 45 seconds; if the
  criteria together need more, add one `gatekit-budget` fence declaring
  `total_budget_s` (ceiling 600). **Measure first**: after `contract derive`,
  run `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract baseline --budget 600`
  once and read each criterion's elapsed time (the gate command runs the
  baseline again after any edit, budget included), then declare — never raise a budget to hide a slow
  test you have not looked at
- **Boot the app once, not once per criterion.** Prefer a server that compiles
  once (`next build && next start`, or the runner's `reuseExistingServer`
  against a server you start before the run) over a cold `next dev` in every
  criterion; dev servers compile each page on first request
- `artifacts` only for files the command genuinely produces. A declared
  artifact that does not appear is a `fail`, so do not declare aspirational ones.
- `expect` beyond `exit` when the exit code alone can lie. A test runner that
  reports skips still exits 0, so pin it: `"expect": {"exit": 0,
  "stdout_not_contains": ["skipped", "SKIP"]}`. `stdout_contains`,
  `stdout_regex` and the `stderr_*` forms exist too; every unknown key is a
  derive error, so spell them exactly.

**The screenshot criterion (ADR-0017 decision 9, ADR-0020).** One criterion
runs the project's E2E runner (`npx playwright test` unless
`spec/03-architecture.md` names a different one already in use) against one
spec that visits, in turn, the screen of every task in 04 whose `write_scope`
touched a UI surface and saves `spec/design/build-<task-id>.png` for each. Its
`artifacts` names every one of those paths, so a missing screen is a `fail`:

```json
{"id": "screenshots", "argv": ["npx", "playwright", "test", "e2e/screenshots.spec.ts", "--project", "mobile"],
 "expect": {"exit": 0}, "timeout_s": 120,
 "artifacts": ["spec/design/build-task-one.png", "spec/design/build-task-two.png"]}
```

Write the actual Playwright spec file this `argv` runs — like every other
criterion it must be runnable here right now, not a guess. If the project
has no E2E runner at all, that setup is the task's own responsibility; do
not derive a criterion whose `argv` cannot run yet. **Never substitute an
MCP browser tool call for the `argv`** — `contract.py` runs criteria with
`subprocess.run`, and `mcp__*` tools exist only inside an agent session. On
a host with no browser the `argv` fails to launch and `contract.py` reports
`unverified`, never a fabricated pass; that is the correct outcome.

Every criterion must be **runnable in this repository right now**. Run each
one before writing it in — an unexecuted criterion is a guess, and the Stop
hook will run it for real. Read the output, not only the exit code:
`node --test <directory>` and `gates/tokens.py <directory>` both "run" and
both are wrong (the first loads the directory as a module, the second scans
zero files and exits 3). Use glob patterns (`tests/rules/*.test.js`).

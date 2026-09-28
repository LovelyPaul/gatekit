# gatekit

Status: 0.11.2 — early. License: MIT.

gatekit is a gate-enforced harness for AI-assisted development in
[Claude Code](https://claude.com/claude-code). It turns the usual prose
instructions you'd put in a `CLAUDE.md` or a slash command into hooks that
actually run, every time, instead of guidance a model can forget or skip
under pressure.

## Why

Prose instructions fire nondeterministically. A `CLAUDE.md` that says
"write tests first" or "get approval before touching `src/`" is only ever
as reliable as the model's attention in that turn. gatekit moves the parts
that matter into things a hook enforces:

- **Gates are hooks, not prose.** `PreToolUse`, `PostToolUse`, `Stop` and
  `UserPromptSubmit` hooks read and act on structured state, not on
  instructions the model has to remember to follow.
- **Assumption ledger.** Every spec keeps an explicit list of assumptions
  made on the user's behalf, so nothing gets decided silently.
- **Hash-anchored approvals.** Approving a spec file records its SHA-256.
  If the file changes afterward, the approval is stale and gatekit knows it
  — nobody has to remember to re-review.
- **Executable completion contracts.** "Done" is a list of commands
  (`gatekit-criterion` blocks) that either exit 0 and produce the expected
  artifacts, or they don't. No done claimed on the honor system.
- **Four-state verdicts.** Every check reports `ok`, `warn`, `fail`, or
  `unverified`. `unverified` ("not checked") is never rounded to a pass or
  a fail — a check that couldn't run tells you that, plainly.
- **Workers only when the model should differ.** By default the session
  running the build implements the tasks itself — a worker is a cold
  session of the same model, re-deriving the project per task to buy a
  second opinion from the model already present. Spawn one when the model
  genuinely has to differ (adversarial verification, a Codex host
  delegating to Claude) or when a round is wide enough for parallelism to
  pay. The Claude CLI is the default backend; Codex is opt-in.

## Requirements

- **Claude Code** on a paid plan (Claude Code is not part of the free tier),
  or the Codex CLI — see [Codex CLI](#codex-cli) below.
- **Python 3.9 or newer, reachable as `python3`.** The hooks in
  `plugin/hooks/hooks.json` invoke `python3` by name, so an interpreter
  installed only as `python` does not satisfy them. Nothing else is needed:
  gatekit is standard library only, with no `pip install` step.
- **On Windows, run gatekit inside WSL.** Claude Code itself runs natively
  on Windows, but a native Windows Python installs as `python`, not
  `python3`, so every gate fails there. Under WSL (Ubuntu ships `python3`)
  it behaves like any other Linux host.

## Install

```
/plugin marketplace add https://github.com/LovelyPaul/gatekit
/plugin install gatekit@gatekit
```

Restart Claude Code after installing so the hooks in `plugin/hooks/hooks.json`
are picked up.

The plugin installs globally, so its hooks are loaded in every project you
open. They stand down in any project that has no `.gatekit/` directory:
no gate acts and no state is written there. A project becomes gatekit's
business the first time you run a `/gatekit:` command in it.

### Codex CLI

Codex has no plugin format, so gatekit generates its layer into your project
from a clone of this repository:

```
git clone https://github.com/LovelyPaul/gatekit
python3 "gatekit/plugin/bin/gatekit.py" install --host codex
```

This writes `.codex/hooks.json`, one skill per command under
`.agents/skills/gatekit-*`, and a managed block in `AGENTS.md`. Trust the
project's `.codex/` layer when Codex asks, start a new session, and invoke
the pipeline as `$gatekit-interview`, `$gatekit-build` and so on. Nothing
beyond `python3` is required.

### Host parity

| | Claude Code | Codex CLI |
|---|---|---|
| Kernel CLI, templates, `spec validate`, contracts | ok | ok |
| write gate (spec before code, task scope) | ok | ok — observed: `apply_patch` arrives as its own event with the patch text and is denied before approval |
| bash gate | ok | ok — observed: code-mode `exec` is unwrapped into one `Bash` event per shell command |
| stop gate (contract at session end) | ok | ok — Codex Stop dialect |
| prompt gate (`active_pipeline`, language) | ok | ok — `$gatekit-<name>` invocation |
| spawn gate (subagent scope fence) | ok | warn — `collaborationspawn_agent` hides the prompt from hooks, so the fence cannot be checked; the subagent's own writes still meet the write and bash gates (observed) |
| question gate (question budget) | ok | n/a — Codex has no `AskUserQuestion`; questions are plain chat and uncounted |
| compact gate (stamp build state before a summary) | ok | not installed — no `PreCompact`-equivalent event is known for Codex, so the layer ships six hooks rather than seven. Build state still lives in the job dir and `spec/PROGRESS.md`; only the narrative stamp is missing |
| `AskUserQuestion` in commands | native picker | numbered options in plain chat |
| `/gatekit:design` live-site branch (`WebFetch`, Chrome tools) | ok | unverified — not yet observed in a real Codex session; the command asks for local captures instead of guessing from the URL |
| `/gatekit:interview` domain research (`WebSearch`) | ok | warn — observed: with no `WebSearch`, Codex routed around the step by spawning a subagent to "research" from memory. The skill now tells it to say so and ask instead; a proposal with no source defeats the step |
| Build worker can be the other CLI | ok (`codex`) | ok (`claude`) |
| Evaluator can be the other CLI | ok (`workers set-evaluator codex`) | ok (`workers set-evaluator claude`) |

`unverified` means exactly that: not observed in a real session yet. A
report from one is welcome. Antigravity is not supported in this release.

Using the other CLI as worker or evaluator needs that CLI installed and
logged in with its own subscription; gatekit shells out to it and never
holds an API key.

## The three flows

gatekit is built around three ways to get from an idea to a done, verified
change:

1. **Discover/interview → spec.** For someone who doesn't yet know what to
   build, `/gatekit:discover` is a free-ranging conversation (no fixed
   question slots) that surfaces and summarizes real problems worth
   solving. `/gatekit:interview` then goes deep on implementation shape —
   pages, behavior, data — and, for a known product category, researches
   it live (four search angles, cross-checked against independent sources)
   to propose standard features the conversation itself never raised,
   separated from the user's own stated reasons for building the thing, so
   the user prunes a fuller draft instead of building up from a blank
   form. Together they write `spec/00-discovery.md`, `spec/01-prd.md`, and
   `spec/03-architecture.md`, including the assumption ledger.
2. **Mockup or design → spec.** Start from a visual mockup or existing
   screens; gatekit derives `spec/02-screens.md` and `spec/tokens.json`, and
   records any gaps it had to guess at as ledger entries instead of
   silently filling them in. `/gatekit:design` covers the design inputs a
   mockup doesn't: a design pattern that applies across screens, or a
   reference site (Figma, a live URL, screenshots, HTML, a preset, or a
   pattern file you wrote) — it writes `spec/02-design.md` and merges into
   the same `spec/tokens.json`, and it may run at any stage, including
   mid-build.
3. **Build → verify.** Once a spec is approved, gatekit breaks it into
   tasks, derives a completion contract, hands tasks to a worker under a
   declared write scope, and then verifies the result independently —
   the agent that built something is never the one that signs off on it.

## Commands

| Command | Produces |
|---|---|
| `/gatekit:discover` | `spec/00-discovery.md` — for the user who does not yet know what to build |
| `/gatekit:interview` | `spec/01-prd.md`, `spec/03-architecture.md` |
| `/gatekit:mockup` | `spec/02-screens.md`, `spec/tokens.json`, ledger gap entries |
| `/gatekit:design` | `spec/02-design.md`, `spec/tokens.json`, ledger gap entries |
| `/gatekit:tasks` | `spec/04-tasks.md` |
| `/gatekit:gate` | `spec/05-gate.md`, `.gatekit/contract.json`, approvals |
| `/gatekit:build` | worker jobs run against `spec/04-tasks.md` |
| `/gatekit:verify` | independent end-to-end check against the completion contract |
| `/gatekit:doctor` | an 8-axis health report on the install itself |
| `/gatekit:setup` | optional Codex backend, other configuration |

## The `spec/` layout

Everything gatekit produces during planning is plain, human-reviewed
Markdown and JSON, meant to be committed:

```
spec/
├── 01-prd.md            # includes an Assumption Ledger
├── 02-screens.md
├── 02-design.md         # optional — patterns, components, tokens summary
├── 03-architecture.md
├── 04-tasks.md          # tasks as fenced gatekit-task JSON blocks
├── 05-gate.md           # completion criteria as fenced gatekit-criterion JSON blocks
├── RECOVERY.md
├── PROGRESS.md
├── tokens.json          # optional, from the mockup or design flow
└── design/              # optional — captures cited as evidence by 02-design.md
```

## State layout

Runtime state lives under `.gatekit/` in your project. `config.json` and
`approvals.json` are meant to be committed; everything under `runs/` and
`jobs/` is per-session and gitignored:

```
.gatekit/
├── config.json          # committed
├── approvals.json        # committed — hash-anchored approvals
├── contract.json         # derived from spec/05-gate.md
├── runs/<session_id>.json   # gitignored — session ledger
├── runs/hook-errors.log     # gitignored
└── jobs/<job_id>/           # gitignored — worker job state
```

## Config

`.gatekit/config.json` controls whether code changes are gated behind an
approved spec (`enforce_spec_before_code`, on by default), which worker
backend builds run against, retry/parallelism limits, and the interview
question budget. See `docs/ARCHITECTURE.md` §9 for the full schema and
defaults.

## Security posture

- Worker sandboxing is **on by default** and is never silently disabled.
  A backend that bypasses its sandbox must explicitly set `"unsafe": true`
  in its config entry, and that flag is recorded in the job's receipt.
- Hooks never block the session on their own internal errors — a broken
  gate script degrades to "allow and log," not "hang the user's session."
- Content pulled in from mockups, screenshots, or the web is treated as
  data to reason about, never as instructions to follow.
- See `SECURITY.md` for the full threat model and how to report a
  vulnerability.

## Documentation

- `docs/manual/` — the user manual (Korean): install, concepts, the
  commands, the spec files, the gates, the CLI, a worked example,
  troubleshooting, and the design decisions. Start at
  `docs/manual/00-index.md`, or jump straight to the "first 30 minutes"
  walkthrough in `docs/manual/01-what-and-why.md` and run the loop once
  before reading the concepts.
- `docs/QUICKSTART.md` — the short path from install to a first run.
- `docs/ARCHITECTURE.md` — the binding contract every module must satisfy.
- `docs/decisions/` — the architectural decision records.
- `docs/retros/` — retrospectives from real trial builds (Korean); each
  lists the tool defects and friction found, with evidence paths.

## Status

**0.11.2 — early.** The core gate/ledger/contract/approval kernel, worker
dispatch (host or a different-model worker), Codex evaluator support, and
the CI enforcement tooling are all in place; expect rough edges. See
`CHANGELOG.md` for what shipped and `docs/decisions/` for the architectural
decisions behind the current shape.

## License

MIT — see `LICENSE`.

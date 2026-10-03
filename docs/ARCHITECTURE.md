# gatekit architecture contract

This file is the single source of truth for module boundaries, file formats and
vocabulary. Every module, command, hook and test must agree with it. If an
implementation needs to deviate, change this file first (with an ADR in
`docs/decisions/`) and then the code.

gatekit is a **clean-room** implementation. It borrows *patterns* that are
common engineering practice (hook-enforced gates, assumption ledgers,
hash-anchored approvals, executable completion contracts, worker job
directories) but contains no code copied from any other project.

## 0. Non-negotiables

| Rule | Why |
|---|---|
| Python 3.9+ standard library only, everywhere | must run on a fresh machine with only `python3` |
| One plugin (`plugin/`), one package (`plugin/gatekit/`) | cross-plugin paths do not exist in Claude Code; single plugin means `${CLAUDE_PLUGIN_ROOT}` reaches everything |
| Gates are hooks, not prose | prose instructions fire nondeterministically; hooks fire every time |
| Every hook exits 0 on any internal error and writes a one-line diagnostic to `.gatekit/runs/hook-errors.log` | a broken hook must never break the user's session |
| Verdict vocabulary is exactly `ok / warn / fail / unverified` | "not checked" must never be rounded to pass or fail |
| No absolute personal paths anywhere in the repo | CI gate `tools/gate_no_abs_paths.py` fails the build |
| `SKILL.md` ≤ 40 lines: trigger shim only. `commands/*.md` is the execution instruction | prevents the command/skill split from becoming two products |
| Data (templates, heading maps, presets, schemas) lives in JSON/Markdown files, not in prompt prose | keeps prompts small and data diffable |
| Any file > 1 MB fails CI | no committed corpora |
| Output language follows `output_lang` (see §8); Korean is never a default | open-source posture |

## 1. Repository layout

```
gatekit/
├── .claude-plugin/marketplace.json     # one plugin: ./plugin
├── plugin/                              # the installable plugin
│   ├── .claude-plugin/plugin.json
│   ├── commands/                        # execution instructions (one per pipeline)
│   │   ├── discover.md    /gatekit:discover    → spec/00-discovery.md (optional first step)
│   │   ├── interview.md   /gatekit:interview   → spec/01-prd.md, spec/03-architecture.md
│   │   ├── mockup.md      /gatekit:mockup      → spec/02-screens.md, spec/tokens.json, ledger gaps, optional preview (ADR-0011)
│   │   ├── design.md      /gatekit:design      → spec/02-design.md, spec/tokens.json, spec/design/, gap entries in ledger
│   │   ├── tasks.md       /gatekit:tasks       → spec/04-tasks.md
│   │   ├── gate.md        /gatekit:gate        → spec/05-gate.md, .gatekit/contract.json, approvals
│   │   ├── build.md       /gatekit:build       → worker jobs over spec/04-tasks.md
│   │   ├── verify.md      /gatekit:verify      → independent E2E + report check
│   │   ├── doctor.md      /gatekit:doctor
│   │   └── setup.md       /gatekit:setup       → optional Codex backend, config
│   ├── skills/<name>/SKILL.md           # ≤ 40-line NL trigger shims that point at the command
│   ├── hooks/hooks.json                 # 7 hook registrations (see §3); auto-loaded, never listed in plugin.json
│   ├── gatekit/                         # kernel package (stdlib only)
│   │   ├── cli.py         dispatcher: python3 -m gatekit <sub>
│   │   ├── hookio.py      hook stdin/stdout contract, safe wrapper, host dialects (§3)
│   │   ├── hosts.py       generated host layers: `gatekit install --host codex` (§15)
│   │   ├── ledger.py      per-session run ledger
│   │   ├── lang.py        output_lang detection
│   │   ├── verdict.py     4-state vocabulary + aggregation
│   │   ├── contract.py    completion contract derive/validate/run/baseline
│   │   ├── runcheck.py    "ran no tests" signatures, missing-path extraction, scope ownership (ADR-0022)
│   │   ├── approval.py    hash-anchored approvals
│   │   ├── spec.py        spec set validation
│   │   ├── jobs.py        job runner (job dir, atomic writes, spawn, gates, redelegate)
│   │   ├── workers.py     worker backends (claude default, codex optional, custom)
│   │   ├── doctor.py      8-axis diagnosis
│   │   ├── config.py      .gatekit/config.json loader with defaults
│   │   ├── paths.py       project root / state dir resolution
│   │   └── gates/         hook entry points: prompt.py write.py bash.py spawn.py question.py compact.py stop.py
│   ├── spec-kit/
│   │   ├── templates/{ko,en}/01-prd.md … 05-gate.md, RECOVERY.md, PROGRESS.md
│   │   ├── heading-map.json             # canonical headings per file per language
│   │   ├── no-tests-signatures.json     # per-runner "ran no tests" patterns (ADR-0022)
│   │   └── grading-patterns.json        # which argv files count as grading files (ADR-0023)
│   ├── policy/language.md questioning.md verification.md   # loaded at runtime by commands
│   └── tests/                           # unittest, run with: cd plugin && python3 -m unittest discover -s tests
├── tools/                               # CI gates (stdlib)
├── docs/ARCHITECTURE.md (this), decisions/ADR-*.md
├── .github/workflows/ci.yml
├── README.md, README.ko.md, CHANGELOG.md, CONTRIBUTING.md, SECURITY.md, LICENSE, CLAUDE.md
```

## 2. Project state layout (inside the user's project)

```
<project>/
├── spec/                       # human-reviewed, committed
│   ├── 00-discovery.md         # optional; ```gatekit-discovery JSON fence (§6a)
│   ├── 01-prd.md               # includes "## Assumption Ledger" / "## 가정 원장"
│   ├── 02-screens.md
│   ├── 02-design.md            # optional; patterns, components, tokens summary (ADR-0008)
│   ├── 03-architecture.md
│   ├── 04-tasks.md             # tasks as ```gatekit-task JSON fences (§6)
│   ├── 05-gate.md              # criteria as ```gatekit-criterion JSON fences (§5)
│   ├── RECOVERY.md
│   ├── PROGRESS.md
│   ├── tokens.json             # optional, from mockup or design pipeline
│   └── design/                 # optional; captures cited as evidence by 02-design.md (ADR-0008)
│       └── preview-<project>.html   # optional; drawn from the spec, never evidence (ADR-0011)
└── .gatekit/
    ├── config.json             # committed. see §9
    ├── approvals.json          # committed. see §7; 05-gate.md's entry pins per-criterion `grading` (ADR-0023)
    ├── contract.json           # derived from 05-gate.md by `gatekit contract derive`; per criterion `grading` hashes (ADR-0023)
    ├── baseline.json           # `gatekit contract baseline` at gate time (ADR-0022); never read by the Stop gate
    ├── runs/<session_id>.json  # ignored. ledger (§4)
    ├── runs/hook-errors.log    # ignored
    ├── attempts.json           # committed. per-task consecutive-failure counts + last failure fingerprint (ADR-0014, ADR-0021) + `failed_grading` (ADR-0023)
    └── jobs/<job_id>/          # ignored. see §10
```

`paths.project_root(cwd)` = nearest ancestor containing `.gatekit/` or `.git/`, else cwd.

**Design preview (ADR-0011).** When `/gatekit:mockup` runs with no design
source, its one `AskUserQuestion` offers a preview instead of a gap question
(a stop signal suppresses both). On a yes it writes
`spec/design/preview-<project>.html` from `02-screens.md` plus `tokens.json`:
static, tokens-only — a value the tokens lack is drawn as a labelled
placeholder, never invented — and opening with a banner saying the screens
were drawn from the spec, not observed. The user's corrections are applied to
**`spec/02-screens.md`**, not to the HTML, and the preview is redrawn from it;
that file is what §10 pushes into worker briefs. No approval is recorded and
no assumption closes. A preview path must never appear in an evidence cell of
`02-screens.md` or `02-design.md` — `spec.validate` fails on it, and
`/gatekit:design` refuses one as input — because a drawing made from the spec
cannot be evidence for the spec.

## 3. Hook I/O contract (`hookio.py`)

Claude Code passes a JSON object on stdin. Codex CLI passes the same object
(same field names) to hooks registered in `.codex/hooks.json`; the gates
serve both hosts from one script, learning the host from `--host <name>` on
their own argv (`hookio.host_from_argv`); with no flag, a non-empty
`PLUGIN_ROOT` in the environment — set by Codex for plugin hooks, not by
Claude Code — means `codex`, otherwise `claude` (ADR-0019). Only the Stop
block differs between the two dialects and `hookio.adapt_output` renders it
(`{"decision":"block","reason"}` for Claude Code, `{"continue":false,"stopReason"}`
for Codex); deny and additionalContext payloads are identical. Codex edits
files through `apply_patch`, whose `tool_input.command` is the patch text;
the write gate takes every `*** Add/Update/Delete File:` and `*** Move to:`
header as a target and refuses a patch that names none while a rule is
active. Fields used:
`session_id`, `hook_event_name`, `cwd`, `tool_name`, `tool_input`, `tool_response`,
`prompt` (UserPromptSubmit), `stop_hook_active` (Stop).

Responses:

| Event | Allow | Block |
|---|---|---|
| UserPromptSubmit | exit 0; optional stdout JSON `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"…"}}` | not used |
| PreToolUse | exit 0 | stdout JSON `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"…"}}`, exit 0 |
| PostToolUse | exit 0 | not used |
| Stop | exit 0 | stdout JSON `{"decision":"block","reason":"…"}`, exit 0. Never block when `stop_hook_active` is true. |

`hookio.run(handler)` reads stdin, calls `handler(event: dict) -> dict | None`,
prints the returned JSON (if any), and **always exits 0**; exceptions are
appended to `.gatekit/runs/hook-errors.log` as one line `iso_ts event_name error`.
Each gate must complete in < 5 s on a normal project. The Stop gate runs the
contract (§5) and is the exception: its hook `timeout` in `hooks.json` is
600 s, the largest value the Claude Code hook documentation shows, and the
gate caps the contract run at `STOP_BUDGET_CAP_S` = 570 s (`gates/stop.py`)
so start-up and teardown fit inside the timeout. A `gatekit-budget` above the
cap runs in full under `contract run` but is cut at the Stop gate, where the
cut is reported as `unverified` — honest, where a hook killed by Claude Code
would record no verdict and no log line. Tests pin `hooks.json` to
`STOP_HOOK_TIMEOUT_S` and the cap to at least 30 s below it.

Registered hooks (plugin/hooks/hooks.json): UserPromptSubmit→`gates/prompt.py`,
PreToolUse `Write|Edit|MultiEdit|NotebookEdit|apply_patch`→`gates/write.py`,
PreToolUse `Bash`→`gates/bash.py` (ADR-0004),
PreToolUse `Agent|Task|collaborationspawn_agent`→`gates/spawn.py` (the Codex tool names are there so the same file serves a Codex plugin install, ADR-0019; a name that does not exist in a host never matches), PostToolUse `AskUserQuestion`→`gates/question.py`,
Stop→`gates/stop.py`.

**Platforms (ADR-0019).** Every hook command is
`python3 "<script>" || python "<script>" || py -3 "<script>"` — valid in sh,
Git Bash and CMD — so a host with only `python` or the Windows launcher still
starts the gate; a gate always exits 0, so the chain only advances when an
interpreter is missing. `hookio` reads stdin and writes stdout as UTF-8
through the binary buffers, whatever the console's locale encoding. The
write and Bash gates read Git Bash's `/c/<dir>/…` as `C:/<dir>/…` on Windows
(`paths.from_msys`). `paths.expand_argv` also resolves a bare `argv[0]`
through `shutil.which` (so `npm` finds `npm.cmd`), and `jobs.py` process
control uses `tasklist` / PowerShell / `taskkill /T /F` on Windows, where
`os.kill(pid, 0)` would terminate the process instead of probing it.
Windows is a preview: CI runs the suite on `windows-latest`, but no real host
session on Windows has been observed yet.

Gate behaviour:

Every gate stands down in a project that has no `.gatekit/` directory. The
plugin installs globally, so these hooks fire in every project the user
opens; a project with no `.gatekit/` has never run a gatekit command and
never asked to be governed. Such a gate allows without reading further and
**creates no state there** — no ledger, no `.gatekit/`, and no error log: a gate that fails there logs nothing, since creating `.gatekit/runs/` would make every later gate treat the project as managed. The one exception is
`compact`, which already writes nothing when no job exists.

- **prompt**: ensure ledger exists for `session_id`; detect `output_lang` from `prompt` (§8) and store it — for a slash command only the `<command-args>` content is the user's words, and empty args keep the stored language; **set `active_pipeline`** when the prompt invokes `/gatekit:<pipeline>`. Claude Code delivers a slash command as the tagged body `<command-message>…</command-message>` / `<command-name>/gatekit:<name></command-name>` / `<command-args>…</command-args>`; that tag, a bare `/gatekit:<name>` at the start of the prompt, and the `# /gatekit:<name>` title line of an expanded command body are recognised within the first 12 lines. A mid-sentence mention is not an invocation. `doctor` and `setup` clear it; an unknown name leaves it alone; a plain prompt keeps it. Entering a different pipeline resets `questions` to its defaults. Invoking `build` or `verify` — the same pipeline again included — also re-arms the Stop gate (ADR-0024): `stop` is reset to `{"block_count": 0, "final_verdict": null, "last_reasons": [], "stood_down": null, "deferred": []}` with a `stop_rearmed` event. This is the **only** production writer of `active_pipeline` — commands never set it by prose. Inject `additionalContext` (≤ 600 chars) with `output_lang`, question budget state, active pipeline, and unresolved gate count, plus `build=<job> n/m passed, next: <task>` while a job is unfinished — followed, while any of its tasks is `queued`, by ``; build job unfinished: N tasks queued — `jobs stop` ends judging`` in `output_lang` (ADR-0024 review: such a job never settles, so the Stop gate keeps judging) — and — while a Stop-gate stand-down applies (ADR-0024, `stop.stand_down_applies`) — one line in `output_lang`, placed right after `pipeline=` so the 600-char cut never drops it, naming what was judged (`turn-tier <verdict>` under `build`, `contract <verdict>` under `verify`), how many `verify`-tier criteria wait (`N deferred to /gatekit:verify`, when any), and that follow-up edits are not gated and `/gatekit:verify` re-checks the contract; while no stand-down applies and `stop.deferred` holds `budget` deferrals, the same slot names those ids as unjudged, run first at the next turn end; under `build` with a contract that has no `turn` criterion it says turn ends judge nothing and `/gatekit:verify` runs them (`stop.stand_down_line`) (ADR-0013 decision 1a: the session that returns from a compaction is told a build is live and reads `spec/PROGRESS.md` for the rest). The question field is `questions=<asked>/<max>`, followed by the ADR-0012 signals when any is non-zero — `questions=6/2 (2 unjustified, 1 repeat, impl-choice)` — printing only what is set so the 600-char budget holds. Never blocks.
- **write**: for `apply_patch`, apply the rules below to every file the patch header names (a patch naming no file is denied while a rule is active). Otherwise deny when (a) `config.enforce_spec_before_code` is true, `spec/` exists, `.gatekit/approvals.json` has no valid approval for `spec/05-gate.md`, the target lies inside the project root (after realpath; a target outside the root is not this project's code and rule (a) allows it, ADR-0018), and the target path is outside the allowlist `spec/**, .gatekit/**, docs/**, README*, *.md at root`; or (b) env `GATEKIT_TASK_ID` is set and the target is outside that task's `write_scope` (from the job's `task.json`). Reason text is in `output_lang`.
- **bash**: apply the write rules (a) and (b) to every file a Bash command would write, read statically from the command text: redirections (`>`, `>>`, `&>`, `>|`, `N>`), `tee`, `sed -i`/`perl -i`, `cp`/`mv`/`ln`/`install`/`rsync` destinations, `touch`/`rm`/`mkdir`/`truncate`/`chmod`/`chown` operands, `dd of=`, `sort -o`, `curl -o`, `wget -O`, `tar -C`/`-f`, `unzip -d`, `zip`, with `cd` tracked across `;`/`&&`/`||`/`|`/newlines, `VAR=`/`sudo`/`env`/`nohup` prefixes stripped, here-document bodies ignored, `/dev/*` targets ignored and `sh|bash|zsh -c "…"` parsed recursively. Fast path: when no rule could deny anything (no `GATEKIT_TASK_ID`, spec gate approved or absent) the command is allowed without parsing. When a rule is active and a write's target **cannot be determined** — `$VAR` or backticks in a path, `cd` to an unknown directory, `eval`, `xargs`, `patch`, `trap`, `find -exec/-delete`, working-tree `git` subcommands (`apply`, `checkout`, `restore`, `reset`, `merge`, `stash`, `init`, `clone`, …), inline interpreter code (`python3 -c`, `node -e`, `perl -e`, stdin scripts), `awk`, command-line editors (`ed`, `ex`, `vim`, `nano`), `busybox`, downloads that choose their own file name (`curl -O`, bare `wget`), process substitution, unbalanced quotes — **deny** with reason `opaque`: "could not tell" is never rounded to "allowed". Programs invoked by name (`npm run build`, `python3 script.py`) are outside its reach by design, with one exception: when `GATEKIT_TASK_ID` is set in the hook's environment (a worker session), a command that runs gatekit's own `approve` subcommand — `gatekit.py`/`gatekit`/`-m gatekit` followed by `approve`, in any simple command, behind `env -u …`/`VAR=` prefixes, inside `sh -c`/`eval` strings, by pattern when unlexable — is denied with reason `approve` before any other rule (ADR-0023); `approve check` and `approve list` stay allowed. Reason text is in `output_lang`.
- **spawn**: under Codex the tool is `collaborationspawn_agent` and its payload carries only a task name and an encrypted message, so the fence cannot be read: allow, record `spawn_unscoped` in the ledger, and rely on the write/bash gates that the subagent's own tool calls meet (they carry `agent_id`). Otherwise the spawn prompt must contain a fenced block ` ```gatekit-scope ` with JSON `{"write_scope": [globs] | "read-only", "stop_when": "…", "tools": [...] | "inherit"}`. Deny if missing/invalid, or if `write_scope` intersects any scope already recorded in the ledger for this session. On allow, record the scope in the ledger. No regex over prose: parse the fence as JSON.
- **compact** (PreCompact, ADR-0013): stamp the latest job's state — job id, execution mode, backend, and every task's state, gate tally and detail — into `spec/PROGRESS.md` between `<!-- gatekit:build-state -->` and its closing marker, replacing that block in place so repeated compactions leave one stamp and nothing outside it is touched. The heading belongs to neither language's canonical set, so `spec validate` is unaffected. Writes nothing when no job exists; an unwritable file is swallowed, since the job dir still holds every fact. Under host execution a build lives in one session, so a compaction is routine: this hook records the narrative, which is the only thing the files did not already hold.
- **question**: increment `ledger.questions.asked`; if `asked > budget.max_calls` (default 2 for interview, unlimited otherwise) record `budget_exceeded=true` (informational; commands read it). ADR-0012 adds four signals, all informational and all confined to the budgeted pipeline, because a raw count permits waste inside the budget and forbids value outside it. Past `max_calls` a call must arrive with `questions.justification` — one line naming what the command would write differently depending on the answer — which the call **consumes** (set to `null`); a call without one raises `unjustified`. A justified call sets `awaiting_write`, and if the next `AskUserQuestion` arrives with it still set, `unrealized` is raised: the claim that the answer changes what gets written did not come true. The same gate is therefore also registered on **PostToolUse for `Write|Edit|MultiEdit|NotebookEdit`**, where it only calls `note_write` (clearing `awaiting_write`) and never counts a question — PreToolUse could not serve, since a write it sees may still be denied. Independently of the budget, each question's `header` + `question` is reduced to a content-word fingerprint (noise words dropped, ≥ `REPEAT_MIN_WORDS` 3 words) and compared against `questions.asked_topics` (last 50): overlap ≥ `REPEAT_OVERLAP` (0.7) of the smaller set raises `repeated` and records `repeat_of`. A call whose options are **all** code tokens (path, `call()`, dotted filename, `snake_case`, `camelCase`) sets `implementation_choice` — a `warn`-grade signature of handing the user a decision the command owned, never a verdict, since a question about implementation is sometimes right.
- **stop**: if `.gatekit/contract.json` exists and the ledger's `active_pipeline` is `build` or `verify`: run the contract (§5) — unless nothing changed since the last recorded run (ADR-0020): `.gatekit/runs/contract-last.json` holds the last result with the contract's `source_sha256`, `signatures_sha256` (`runcheck.signatures_digest()`, the hash of `no-tests-signatures.json`; a record without it or with another hash is never reused, ADR-0022) and a fingerprint of the tree taken after that run (`contract.tree_fingerprint`: `(path, size, mtime_ns)` of every file except `.git`, `.gatekit`, `node_modules`, build output, `test-results`, `*.tsbuildinfo`, `spec/PROGRESS.md` and declared artifacts; none above 20 000 files). When both match, the gate judges that result again and says so (`stop_reused` event); otherwise it runs the contract with last run's `fail`/`unverified` criteria first. `contract run` never reuses but records its result, so the Stop ending a `/gatekit:verify` turn does not repeat it. On any `fail` or `unverified` criterion and `block_count < 3` and not `stop_hook_active`: block with a reason listing failing criteria; increment `block_count`. Otherwise allow and record `final_verdict` in the ledger (never a blank). **Stand-down (ADR-0024).** Under `build` the gate judges while the latest job (`jobs.latest_job_id`) is absent or unsettled — a job is settled when every task's `status.json` state is in `jobs.TERMINAL_STATES`, and a job with no tasks is not — and once more after it settles. When a settled job gets a recorded verdict (an allow with `ok`, an allow after `block_count >= 3`, or a run with `no_criteria_in_tier`), the gate sets `stop.stood_down = {"pipeline", "job_id", "verdict", "at", "skipped": 0}` and logs `stop_stood_down`. While it applies (same pipeline, same latest job, still settled) every Stop exits 0 without running a criterion or touching `final_verdict`, incrementing `skipped`; when it no longer applies it is cleared (`stop_stand_down_cleared` event) and the gate judges again. An allow under `stop_hook_active` is a recorded verdict only when `ok`. Under `verify` the same holds with no job condition. **Tiers and budget (ADR-0024).** Under `build` the gate calls `execute(tiers=("turn",), start_budget_s=config.stop_budget_s(cfg)[0])`; under `verify` it runs every tier with no start budget. Criteria the run left out (`deferred`, reason `tier` or `budget`) are named in the block message as "deferred to /gatekit:verify" or "deferred: Stop-gate budget", recorded in `stop.deferred`, never block and are never reported `ok`. A `no_criteria_in_tier` result allows and records `unverified`; any block message then carries a "no turn-tier criteria" line. Reuse compares the record's `scope` with the ids the current tier selection covers (`contract.covers`). **Budget deferral is not `ok` (ADR-0024 review).** A run whose only reason is `deferred_by_stop_budget` (everything that ran passed) allows without blocking and without counting toward `block_count`, records `final_verdict: "unverified"` with that reason in `last_reasons`, and never stands the gate down — also under `stop_hook_active` and after `block_count >= 3`. The next Stop passes the last record's budget-deferred ids as `deferred_first`, so each Stop judges at least one criterion it has not; when the last record is of the same tree (`contract.same_tree_record`), `contract.carry_forward` keeps its verdicts for criteria this run did not reach. The gate stands down only once every turn-tier criterion has a verdict from some run on the same tree (or the verdict is otherwise final), so a tree left alone converges within as many Stops as there are turn-tier criteria. **Unpassed tasks (ADR-0024 review).** At the handoff of a settled `build` job the gate also reads its tasks' states (`stop.UNPASSED_STATES` = `jobs.NOT_DONE_STATES` + `blocked`). With any `failed`/`timeout`/`blocked` task the outcome is never `ok` — `fail` if a task is in `NOT_DONE_STATES` or the contract failed, else `unverified` — and a `tasks not passed in <job>: <id> (<state>), …` line leads `reasons`: the gate blocks (naming them; counts toward `block_count`), and after `block_count >= 3` records `final_verdict` and stands down. Tasks that are only `stopped` (by `jobs stop`) give `fail` but, when the contract itself has nothing to fix, no block: the gate records and stands down. Under `stop_hook_active` such a run is never a recorded verdict.

## 4. Session ledger (`ledger.py`)

`.gatekit/runs/<session_id>.json`, written atomically (tmp + `os.replace`).
Resolution is **strictly by session_id**; there is no "most recent file"
fallback. Schema (version 1):

```json
{
  "version": 1,
  "session_id": "…",
  "created_at": "iso", "updated_at": "iso",
  "output_lang": "ko|en",
  "active_pipeline": null | "discover" | "interview" | "mockup" | "design" | "tasks" | "gate" | "build" | "verify",
  "questions": {"asked": 0, "max_calls": 2, "budget_exceeded": false,
                "justification": null, "awaiting_write": false,
                "unjustified": 0, "unrealized": 0,
                "repeated": 0, "repeat_of": null,
                "implementation_choice": false,
                "asked_topics": [["word", "word"]]},
  "scopes": [{"owner": "agent-label-or-prompt-hash", "write_scope": ["src/auth/**"], "declared_at": "iso"}],
  "stop": {"block_count": 0, "final_verdict": null, "last_reasons": [],
           "stood_down": null | {"pipeline": "build|verify", "job_id": "…|null", "verdict": "ok|fail|unverified", "at": "iso", "skipped": 0},
           "deferred": [{"id": "…", "tier": "turn|verify", "reason": "tier|budget"}]},
  "events": [{"ts": "iso", "kind": "…", "detail": {}}]
}
```

`events` is append-only, capped at 500 (oldest dropped).

Loading backfills any missing key from the blank ledger. A key whose blank
value is an object (`questions`, `stop`) but whose stored value is not one —
`"stop": null` in a hand-edited ledger — is replaced by the blank object; the
Stop gate checks the same before reading `stop`. Before this, `"stop": null`
made the Stop gate fail open, silently, at every turn end.

## 5. Completion contract (`contract.py`)

Criteria are declared in `spec/05-gate.md` as fenced JSON blocks:

````
```gatekit-criterion
{"id": "tests-pass", "argv": ["python3", "-m", "unittest", "discover"], "expect": {"exit": 0}, "timeout_s": 30, "artifacts": ["reports/junit.xml"]}
```
````

A criterion may carry `"tier": "turn" | "verify"` (ADR-0024; default
`"turn"`). Any other value is a `derive` error and a `spec validate` `fail`.
`spec validate` warns (`warn`, never `fail`; ADR-0024 review) when no
criterion is `turn` — the build's Stop gate would judge nothing — and when the
screenshot criterion (an `artifacts` entry matching
`spec/design/build-*.png`) is `verify`;
the normalised criterion in `contract.json` always has `tier`.
`execute(root, …, tiers=None, start_budget_s=None, deferred_first=None)`
runs the criteria whose tier is in `tiers` (`None` = every tier) and returns
the ids it actually judged as `scope` (sorted) and the rest as `deferred:
[{"id", "tier", "reason": "tier"}]`. With `start_budget_s`, a criterion not
yet started once that many seconds have passed since the run began — while
the run-wide budget still has time left — is not started either and joins
`deferred` with reason `budget`; one started in time runs to its own timeout.
Deferred criteria are not in `criteria`: they are not judged. A `tier`
deferral does not enter the aggregate. A `budget` deferral does: when every
criterion that ran is `ok`, the verdict is `unverified` with the reason
`deferred_by_stop_budget: <ids>` (`BUDGET_DEFERRED_REASON`), never `ok`; a
`fail` or `unverified` that ran keeps its own verdict. `deferred_first` ids
run before `first` ids, which run before the rest (each group in declared
order). `carry_forward(result, previous)` fills a result's budget-deferred
criteria with the verdicts `previous` gave them (marked `"carried": true`)
and re-aggregates; the caller passes only a record of the same tree. When
the tier selection covers no criterion, nothing runs and the result is
`unverified` with reason `no_criteria_in_tier`. Only the Stop gate passes
`tiers`/`start_budget_s`/`deferred_first`; `contract run` and `contract
baseline` run every tier with none. `save_last` records `scope`;
`same_tree_record(root)` returns the last record when the contract,
signatures and tree fingerprint still match; `covers(root, record, tiers)`
is true only when its `scope` equals the ids that `tiers` selects in the
current contract and it has no `budget` deferral; `reusable_last(root,
tiers=None)` is the two together (a record without `scope`, or cut by the
Stop budget, is never reused).

`gatekit contract derive` parses all fences into `.gatekit/contract.json`:

```json
{"version": 1, "source_sha256": "<sha of 05-gate.md>", "criteria": [ … ], "derived_at": "iso",
 "inputs": {"spec/02-screens.md": "<sha256 or \"\">", "spec/02-design.md": "<sha256 or \"\">", "spec/tokens.json": "<sha256 or \"\">"}}
```

Each criterion also carries `"grading": {relpath: sha256}` (ADR-0023): the
hashes, at derive time, of `runcheck.grading_files(argv, root)` — argv tokens
after `${CLAUDE_PLUGIN_ROOT}` expansion that name an existing regular file
inside the root and are either argv[0] given as a path (a script) or
test-shaped per `plugin/spec-kit/grading-patterns.json` (a `test`/`tests`/
`__tests__`/`spec`/`e2e` segment, or a `test_*`/`*_test.*`/`*.test.*`/
`*.spec.*`/`*_spec.*`/`conftest.py` basename; under the top-level `spec/`
only such a basename counts, so `spec/tokens.json` and `spec/02-design.md`
never do), never under a build-output or
dependency directory listed there. Options are skipped except the value of
`--opt=path`; a pytest node id counts by its part before `::`; `[param]` and
`:line[:col]` suffixes are dropped; resolved with `runcheck.relativize` and a
realpath that stays inside the root's; hashed in 1 MiB chunks. Directories
and globs are not grading files. A source file a check inspects
(`grep … src/app.py`, `sqlite3 app.db`) is not one either.

If the derived contract no longer records a file pinned by the approval of
`05-gate.md` (§7) with its approved hash (`contract.unapproved_grading`),
`execute` runs nothing and returns `unverified` with reason
`grading_unapproved` and `unapproved_grading: [paths]`; re-deriving does not
clear it, re-approving does. Otherwise, after a criterion runs, if any
recorded file now hashes differently or is missing, a would-be `ok` is
`unverified` with detail `grading file changed since approval (if intended,
re-run /gatekit:gate to re-approve; otherwise revert it): <paths>` and
`grading_changed: [paths]` — instruction first, since a reason line is cut at
120 characters; `fail` stays `fail`, an existing `unverified` keeps its
reason. Files absent at derive are not tracked. A command naming no file has
no grading files. The Stop gate's reuse needs no extra check: a changed file
changes the tree fingerprint.

`inputs` (ADR-0008) records the sha256 of the design files at derive time;
an absent file hashes to `""`. These are contract inputs, not the contract
itself: `contract status` is `ok` only when both `source_sha256` and every
entry in `inputs` still match the file on disk, and `fail` when any of them
differs, naming the changed file. There is no new verdict for this — a
changed design input makes the contract stale exactly as a changed
`05-gate.md` does, and the fix is the same: re-derive, then re-approve.

`gatekit contract run [--json]` executes each criterion with `subprocess.run`
(no shell), `cwd` = project root, after `paths.expand_argv` replaces the literal
`${CLAUDE_PLUGIN_ROOT}` in each argv element with the plugin directory — the
only expansion performed; `contract.json` keeps the unexpanded text (ADR-0018), per-criterion timeout = `min(timeout_s, remaining)`
within a run-wide budget. That budget defaults to 45 s and may be raised by a
single optional fence in `spec/05-gate.md`, capped at 600 s:

````
```gatekit-budget
{"total_budget_s": 180}
```
````

`derive` stores it as `total_budget_s` in `.gatekit/contract.json`; `execute`
uses it unless an explicit argument (`--budget`) overrides it. The cap exists
because the Stop gate runs this: a check that can outlast the user's patience
is worse than one that reports `unverified` and stands down. A declared budget
that is absent, non-numeric, zero, negative, duplicated, or above the cap is a
`derive` error. Result per criterion:
`{"id", "verdict": "ok|fail|unverified", "exit", "elapsed_s", "stdout_tail", "stderr_tail", "artifact_hashes": {path: sha256}}`.
`expect` may say more than the exit code: `stdout_contains` /
`stdout_not_contains` / `stderr_contains` / `stderr_not_contains` take a
string or a list of strings (all must hold), `stdout_regex` / `stderr_regex`
one pattern searched with `re.MULTILINE`. Output expectations are judged over
the whole stream, not the stored tail, after the exit code; an unmet one is
`fail` with the expectation named in `stderr_tail`. An unknown `expect` key, a
non-integer `exit`, a non-string value or an invalid regex is a `derive`
error and a `spec validate` `fail` — both call `contract.validate_expect`, so
they cannot disagree. This is how "no test was skipped" becomes a criterion
(`{"exit": 0, "stdout_not_contains": ["skipped", "SKIP"]}`) instead of prose.
Timeout or budget exhaustion → `unverified`, never `ok`. Missing artifact → `fail`.
**Ran no tests → `unverified` (ADR-0022).** A criterion that would be `ok`
(or, for a signature whose exit list holds it, exits non-zero with `expect.exit`
0) is `unverified` with `detail = "ran no tests (<id>)"` when
`runcheck.ran_no_tests(stdout, stderr, exit)` names a signature from
`plugin/spec-kit/no-tests-signatures.json`: some signature's anchored
multiline `pattern` matches the full output with the exit code in its
`exits`, and **no** signature's `positive` pattern (a non-zero count) matches
anywhere. Exits are `[0]` except pytest and unittest (`[0, 5]`, their
documented "no tests ran" code); `pytest-deselected` (`^=*\s*\d+
deselected\b`, every test deselected) lists `[5]` only. ANSI escapes are
stripped before matching. An unreadable signature file, or one that is not an
object with a `signatures` list, means no signatures; a malformed entry (not
an object, a non-string `id`/`pattern`/`positive`, a pattern that does not
compile, `exits` not a list of non-boolean integers) is skipped and the rest
apply. `jobs.run_gates` applies the same rule to task gates.

`gatekit contract baseline [--json] [--budget S]` (ADR-0022) runs the fresh
contract once via `execute` (same budget; it never writes
`runs/contract-last.json`) and classifies each criterion: `already_passes`
(`ok`), `not_yet_runnable` (a missing path, or a could-not-execute program
path, that a `spec/04-tasks.md` `write_scope` covers), `command_error`
(`jobs.classify_gate_result` says so, or a could-not-execute program no task
writes), `unverified` (timeout, budget, ran no tests, or a could-not-execute
program inside `node_modules`/`.venv`/`venv` whose manifest no task writes —
a manifest-writing task makes it `not_yet_runnable`) and `fails` (anything
else). It runs against the pre-work tree, and anything a criterion creates
there persists. It writes `.gatekit/baseline.json` — `{"version": 1, "recorded_at",
"source_sha256", "total_budget_s", "elapsed_s", "criteria": [{"id", "class",
"verdict", "exit", "elapsed_s", "detail"}]}` — prints one line per criterion
plus the total, and exits 0, or 4 when any criterion is `command_error`, or 1
when the contract is absent or stale.
Artifact paths must be relative, must not contain `..`, and after
`os.path.realpath` must stay inside the project root (symlink escape → `fail`).
If `source_sha256` no longer matches `05-gate.md`, the run verdict is
`unverified` with reason `contract_stale` (re-derive first).
Aggregate verdict follows `verdict.aggregate` (§11).

## 6. Task blocks in `spec/04-tasks.md`

````
```gatekit-task
{"id": "auth-token", "title": "JWT token helpers", "write_scope": ["src/auth/token.ts"],
 "instruction": "…self-contained brief…",
 "gates": [{"name": "typecheck", "argv": ["npx", "tsc", "--noEmit"]}],
 "depends_on": [], "round": 1}
```
````

`jobs.py` reads these; `spec.py` validates: unique ids, non-empty write_scope
(or `"read-only"`), every `depends_on` exists, no two tasks in the same round
with intersecting write_scope, every task has ≥ 1 gate. `spec.py` also
`warn`s when `spec/PROGRESS.md` is older than the latest terminal task
status under `.gatekit/jobs/`: a session that ended between the build and
the progress write leaves a file that reports the state before the tasks
finished.

A task gate is an `argv` command like any other in `gates`, run by
`jobs.py` after the worker exits (§10), with `${CLAUDE_PLUGIN_ROOT}` expanded
exactly as for criteria (§5, ADR-0018) — distinct from the hook-driven gates
in §3, which fire during the session rather than after a task. One ships in
the plugin: `plugin/gatekit/gates/tokens.py [--root DIR] [--lang ko|en]
[--json] GLOB...` (ADR-0008), which scans the files matching the given
globs (typically the task's own `write_scope`) for colour literals not
present in `spec/tokens.json`. Its exit code is the task-gate convention,
not the hook convention: `0` (`ok`, every literal found matches a token),
`1` (`fail`, a literal named with the file, line, and nearest token by
value), `3` (`unverified`, `tokens.json` absent or unparsable, or the task
wrote no file the gate knows how to scan). `/gatekit:tasks` adds it by
default to every task whose `write_scope` touches a stylesheet, component,
or template path when `spec/tokens.json` exists. The scan is deliberately
narrow — colours only at this version — so a `fail` from it stays
trustworthy. `--root` defaults to `.`, and `jobs.run_gates` always runs a
task gate with the project root as its `cwd`, which is why the fence in
`04-tasks.md` never needs `--root`; run it by hand from another directory
without `--root` and it reports `unverified`, not the project's real state.

A task gate must be able to fail before the work exists and must be a
command that runs as written: `jobs start` executes every gate once before
spawning any worker (ADR-0009, §10) and refuses a gate whose command itself
errors. Two runner-specific rules the trial exposed: `node --test` takes glob
patterns (`tests/rules/*.test.js`), a bare directory is loaded as a module and
fails with `Cannot find module`; `gates/tokens.py` takes globs too
(`src/**`), a bare directory scans zero files and exits 3.

### 6b. Screen spec and prototype confirmation gates (ADR-0017 decisions 3, 4)

`spec.validate` reports two more `fail` conditions against `04-tasks.md` (the
file whose command, `/gatekit:tasks`, must not proceed while either stands),
both exempted when `01-prd.md`'s Non-goals section contains the literal
marker `[non-ui]` (a pure-CLI or library spec with nothing to prototype):

- **`screens_required`** — `01-prd.md` exists and `02-screens.md` does not.
  `heading-map.json`'s `absent_ok` no longer covers `02-screens.md`
  unconditionally; this check replaces that blanket allowance with the
  `[non-ui]`-conditional one. `01-prd.md`'s own absence is reported once, by
  the existing required-file check, never doubled here.
- **`prototype_required`** — `02-screens.md` exists but carries no line
  matching `Prototype confirmed <date>` / `프로토타입 확정 <date>`
  (`YYYY-MM-DD`). This line is prose the validator scans for — not a
  hash-anchored approval like `05-gate.md`'s (§7) — because
  `/gatekit:mockup`'s live-prototype revision loop (Step 7b) has no single
  moment to pin a hash to before the loop's last accepted edit. Only the
  user's explicit confirmation writes this line; the command must never
  infer it from "the prototype looks finished."

## 6a. Discovery record in `spec/00-discovery.md` (ADR-0005)

The optional first stage for a user who does not yet know what to build.
`/gatekit:discover` writes it; `/gatekit:interview` reads it as facts. One
fence:

````
```gatekit-discovery
{"problem": "…", "deadline": "4 weeks|none", "user": "name · role",
 "current_way": ["step", "step"], "frequency_per_month": 8, "minutes_per_run": 40,
 "wait": "none|…", "why_chain": ["symptom", "why", "why", "why", "cause"],
 "failed_attempts": [{"tried": "…", "result": "failed|works-but-costly", "why": "…"}] | "not-applicable",
 "unpassed": ["<gate name>"]}
```
````

`spec.validate`: the file's absence is **silent** (it is listed in
`heading-map.json` `absent_ok`); when present, exactly one fence and a
non-empty `problem` are `fail` conditions, and each of the six deepening
gates (`user`, `current_way` ≥ 2 steps, numeric `frequency_per_month` and
`minutes_per_run`, `why_chain` of strings with ≥ 3 distinct whys after the symptom — a link whose word set overlaps an earlier link by ≥ 0.6 (Jaccard) is a restatement and does not count —
`failed_attempts` non-empty with a valid `result` or `"not-applicable"`) is
`warn` when unfilled — with a distinct message when the gate is declared in
`unpassed`. A gate is never filled by the validator; `unpassed` that is not a list, or names outside the gate list, is `fail`; a gate both filled and listed in `unpassed` is `warn`. Discovery questions are plain chat (not
`AskUserQuestion`), budgeted per gate by the command at three; the question
gate does not count them.

### 6a.1 The `pains` array (ADR-0017 decisions 1 and 2)

Additive to the fence above: a `pains` top-level key holding a list of
`{"summary": "…", "chosen": bool, "verdict_suggested": {"verdict": "build|reuse|eliminate|unknown", "why": "…"}|null, "verdict": "build|reuse|eliminate|unknown"|null}`.
A record with no `pains` key at all is untouched by every check below (the
pre-ADR-0017 fence shape stays valid forever).

Once `pains` is present, `spec.validate`:

- fails if `pains` is not a list;
- fails if fewer than `PAIN_FLOOR` (3) entries exist and the top-level
  `pain_floor_waived` is not truthy (the discovery command's record of a
  user stop signal);
- fails on any entry that is not an object, whose `verdict_suggested` is
  present but not `{"verdict": <one of the four>, "why": <non-empty string>}`,
  or whose `verdict` is present but not one of the four tokens;
- fails unless **exactly one** entry has `"chosen": true`;
- on the chosen entry: fails if its confirmed `verdict` is `eliminate` or
  `reuse` (mirrors `ai-dev-pm`'s `blocksPromote()` — `/gatekit:interview`
  must not draft a spec for a pain the pipeline itself judged should not be
  built); warns (never fails) if `verdict` is `null` while
  `verdict_suggested` exists (the interviewer proposed, the user has not
  confirmed — this is the exact shape of the failure `gk-trial2`'s
  Assumption 4 named: a mapping decided without ever being posed as a
  question); `unknown` never blocks, deliberately — see `spec.py`'s comment
  on why blocking "not sure yet" would be worse than the gap it closes.

## 7. Hash-anchored approvals (`approval.py`)

`.gatekit/approvals.json`:

```json
{"version": 1, "approvals": [
  {"target": "spec/05-gate.md", "sha256": "…", "approved_by": "user", "approved_at": "iso", "note": ""}
]}
```

`gatekit approve <path> [--note …]` records the current hash (asks nothing; the
command file is responsible for asking the user via AskUserQuestion before
calling it). `gatekit approve check <path>` prints `ok` when the file's current
hash matches an approval, `fail` when it differs (approval stale) and
`unverified` when no approval exists. Never overwrite a file to satisfy a hash.

ADR-0023: approving `spec/05-gate.md` also records `"grading": {criterion id:
{relpath: sha256}}` — `contract.json`'s per-criterion `grading` when it was
derived from the file being approved, else hashed from the file's criteria
then (`contract.approved_grading`). `approval.check_gate(root)` is `check` plus
`fail` with the paths when the derived contract no longer records a pinned
file with its pinned hash; `approve check spec/05-gate.md` and the prompt
context use it, and the CLI names the paths on stderr. Files absent at
approval are not pinned; an entry without `grading` (before 0.15.0) is judged
on the file hash alone. The write gate keeps `check` (file hash only), so this
never blocks a write. `approve` refuses with exit 1 when `GATEKIT_TASK_ID` is
set (a worker or the evaluator never approves); `check` and `list` still work.
The Bash gate denies a worker's command that runs `approve`, so `env -u
GATEKIT_TASK_ID` cannot hide the worker from this refusal (§3, bash).
The host session can still approve — the same boundary as any `05-gate.md`
approval.

## 8. Output language (`lang.py`)

`detect(text) -> "ko" | "en"`: count Hangul syllables/jamo vs Latin letters in
`text`, after dropping whitespace-delimited tokens that are paths or code
identifiers (containing `/`, `.`, `_`, `\` or a backtick inside them) — a
named file is not the user's language; `ko` if Hangul ≥ 30% of the remaining
letters, else `en`. Empty text, or only identifiers → `en`.
The prompt gate stores the result per session; commands read it from the ledger
and must emit **every** user-facing string (chat, AskUserQuestion labels, files
written under `spec/`) in that language. Identifiers (file names, JSON keys,
CLI flags, fence names) are never translated. Templates and heading maps exist
for `ko` and `en`; other languages fall back to `en` templates and the command
must say so once.

## 9. Config (`config.py`)

`.gatekit/config.json` with defaults:

```json
{"version": 1,
 "enforce_spec_before_code": true,
 "worker": {"default": "claude", "backends": {
   "claude": {"argv": ["claude", "-p", "--output-format", "json", "--permission-mode", "acceptEdits"],
              "read_only_argv": ["claude", "-p", "--output-format", "json", "--permission-mode", "plan"], "enabled": true},
   "codex":  {"argv": ["codex", "exec", "--sandbox", "workspace-write"],
              "read_only_argv": ["codex", "exec", "--sandbox", "read-only"], "enabled": false}
 }},
 "build": {"max_retries": 2, "parallel": 3, "task_timeout_s": 900},
 "questions": {"interview_max_calls": 2, "items_per_call": 4},
 "verify": {"evaluator": "agent"},
 "stop": {"budget_s": 120}}
```

`stop.budget_s` (ADR-0024) is how long the Stop gate under `build` keeps
starting criteria; criteria it does not start are deferred, never judged
by that run, and make it `unverified` (not `ok`); the next Stop runs them
first (§3 stop). `config.stop_budget_s(cfg)` returns
`(value, problem)`: a non-number, boolean, zero or negative value yields the
default 120, a value above 570 (`STOP_BUDGET_MAX_S`, the Stop gate's cap)
yields 570, each with a problem string that `doctor` reports as `warn`.

Sandboxing is never disabled by default; a backend with a bypass flag must set
`"unsafe": true` and the job receipt records it. `read_only_argv` is the
backend as an evaluator and must not be able to write; a backend without one
cannot grade, and its writable `argv` is never substituted. `verify.evaluator`
is `agent` (the host's own read-only subagent) or a backend name (ADR-0007).

## 10. Jobs and workers (`jobs.py`, `workers.py`)

Job dir `.gatekit/jobs/<job_id>/`: `job.json` (tasks, backend, started_at,
config snapshot), per task `tasks/<id>/{task.json,status.json,prompt.md,output.txt,stderr.txt,gates.json,attempt-N/}`.
**ADR-0023 — grading files changed after a failure.** `run_gates` records on
each gate `"grading": runcheck.grading_hashes(argv, root)` (same rule as §5),
taken just before the gate runs. `jobs.note_grading(root, jdir, task_id,
gates, passed)`, called by `preflight`, `execute_task` (so `redelegate`),
`complete_task` and `recheck` — before `record_attempt`, whose pass resets the
entry — sets `attempts.json.tasks[<id>].failed_grading[<gate>]` (under
`_ATTEMPTS_LOCK`) to the hashes of each gate that failed (most recent failure
in any job), and when the task passes compares them with that gate's hashes
now: every differing or vanished path joins this job's
`status.json.grading_changed_after_failure` (sorted, kept for the job) and
`failed_grading` is cleared. `--force-retry` keeps it (it resets only the
count, `repeats` and `last_failure_sha`), so a pass after a forced retry is
still compared with the failure. A test
absent at preflight hashes to nothing, so greenfield work is not flagged.
`redelegate` carries the flag into the next attempt's status. The verdict
stays `passed`; it is a report. `status` rows carry
`grading_changed_after_failure`, the table appends `(grading changed after
failure: <paths>)`, `results --compact` appends `grading-changed=<paths>`,
`status|results --all` cover every job oldest first (`--json`:
`{"jobs": [...]}`, exit from the latest job's verdict), and `/gatekit:verify`
lists the tasks flagged in any job as a warning.
All JSON writes atomic. Worker = argv list + the prompt on stdin, env includes
`GATEKIT_TASK_ID=<id>` and `GATEKIT_JOB_ID=<job_id>` so the write gate can
enforce `write_scope` inside the worker session. When `spec/tokens.json`
exists, `jobs.build_prompt` (§14) adds a `## Design` section to the prompt,
generated by code from `tokens.json`: the `P<n>` pattern rows whose
`applies_to` is `all` or names an `S<n>` the task's instruction mentions,
every token group as `name: value` lines, and a pointer to
`spec/02-design.md` and `spec/02-screens.md` for anything the section does
not carry (ADR-0008). When `tokens.json` is absent the section is omitted
and the prompt is unchanged from before ADR-0008. A `## Screens` block
follows it (ADR-0011): `jobs.parse_screens` reads the per-screen sections of
`spec/02-screens.md` — the `### S<n> — <name>` heading, the layout line, the
state table — and `jobs._screen_lines` emits, for each `S<n>` the task's
title or instruction names, that screen's layout and state rows. Matching is
the same `design.referenced_ids` scan the `P<n>` rows use, so a task naming
no screen carries no block and one naming several carries each; a named
screen the spec does not describe is skipped. An unreadable or malformed
`02-screens.md` yields no block and never fails the job. `status.json.state` ∈
`queued|running|gating|passed|failed|timeout|redelegated|stopped|blocked`
(the last two from ADR-0009, below). Gates run only after
the worker exits; a worker that exits 0 but fails a gate is `failed`, never
`passed`. `redelegate <task>` archives the attempt to `attempt-N/` and re-runs
with the failed gate output appended to the prompt, up to `max_retries`.
`results --compact` prints one line per task: `id state gates_passed/total`.

**ADR-0014 — attempts are counted per task, not per job.** `status.json.attempt`
resets to 1 on every `jobs start`, so on gk-trial2 one task failed eight times
across ten jobs and `max_retries` never fired even once — the counter climbed
to 3 and restarted three separate times. `.gatekit/attempts.json` now holds
`{"tasks": {id: {"failures", "last_job", "last_gate", "updated_at"}}}`
(ADR-0021 adds `last_failure_sha` and `repeats`, below).
`jobs.record_attempt(root, task_id, state, job_id, gate)` folds one terminal
outcome in: `passed` resets to 0, `failed`/`timeout` increment, `blocked` and
`stopped` are untouched (neither is a judgement of the work). `execute_task`
and `complete_task` both call it — a host attempt counts exactly as a worker's
does — and `recheck` does not, since re-running a gate against existing code is
not an attempt at the work. Both `start` (refusing to include an exhausted
task, `consecutive_failures(root, id) >= max_retries`) and `redelegate`
(refusing when the carried count would put the task past the budget,
`carried > max_retries`, alongside the existing in-job `attempt > max_retries`
check) now raise `RetryBudgetExceeded`, CLI exit 3. `jobs start --force-retry
<id>[,<id>...]` clears one or more tasks' entries first. `status()` rows carry
`consecutive_failures`, and the table prints `(n consecutive)` whenever it is
non-zero, so a task at "attempt 1" in a fresh job that has already failed
elsewhere does not read as untried. Replaying gk-trial2's actual job history
through this counter, `start` refuses before the run's third consecutive
`e2e-full-flow` failure — the real run's other seven attempts never happen.

**ADR-0021 — `jobs complete` is budgeted; an identical failure stops early.**
`complete_task` checks the budget at entry, before any gate runs: carried
consecutive failures `> max_retries` (read from `job.json`, as `redelegate`
does; `<= 0` disables) raise `RetryBudgetExceeded`, CLI exit 3, so host
execution gets the same three attempts by default that a worker gets (one plus
two redelegations). `execute_task` and `complete_task` pass the gates result to
`record_attempt(..., gates=)`, which on a failure also stores
`last_failure_sha` — sha256 of `json.dumps(sort_keys=True)` over the gates
whose verdict is not `ok`, sorted by name, each as `name`, `verdict`, `exit`,
and `stdout`/`stderr` from `normalize_gate_output(tail, root)` — and `repeats`,
the count of consecutive failures with that fingerprint (1 when it changes).
No failing gate, no gates result, or no output from any failing gate means no
fingerprint: both fields are dropped. Entries without them (pre-ADR-0021)
read as "no fingerprint". `normalize_gate_output` is pure and conservative —
a false "same" stops a converging task — and replaces only the absolute
project root (`<root>`), ISO-8601 date-times and `YYYYMMDDTHHMMSSZ` stamps
(`<time>`), `HH:MM:SS` clock times not preceded by a word character, dot or
colon (`<clock>`; `app.js:12:34:56` stays), a number followed, optionally
after one space or tab, by a duration unit
`ns|us|µs|ms|s|sec|secs|seconds|min|mins|minutes` with no word character or
hyphen after it (`<duration>`; never across a newline, and `2 us-east`
stays), `0x` plus six or more hex digits (`0x<addr>`), and trailing
whitespace; plain integers are kept, so "3 failed" and "2 failed" differ.
A tail at the `TAIL_BYTES` cap first drops everything through its first
newline, since the cut point moves with volatile tokens after it.
`record_attempt` and `clear_attempts` do their read-modify-write under
`_ATTEMPTS_LOCK` (per process; `_run_wave` threads lost entries without it),
with the fingerprint computed before the lock.
`redelegate`, `complete_task` and `start` all refuse a task with
`repeats >= 2` (`SAME_FAILURE_LIMIT`) whatever budget remains, unless
`max_retries <= 0`, with the same exception and exit 3 and a message saying
the last failures were identical, to fix the gate (`jobs recheck`) or the
instruction, and that `--force-retry <id>` clears the count (the entry's
`failed_grading`, ADR-0023, stays). `status()` rows
add `repeated_failures`; the table prints `(n consecutive, same failure)` when
it is 2 or more.

**ADR-0013 — who implements a task.** `build.execution` is `host` or `worker`
(`jobs.execution_mode`; an unset or unrecognised value means `host`, and
`config.DEFAULTS` carries `host` too — the hedge that kept `worker` as the
default, so projects predating the ADR would not change behaviour, left the
measured decision unapplied for every project that never edited its config,
and was dropped). Under `worker`, `start` runs as described above. Under `host`,
`start` prepares the job dir, runs preflight, writes `job.json.execution` and
`job.json.plan` — one `{id, round, parallel_candidate}` row per task, in wave
order, `parallel_candidate` true when its round holds ≥ `HOST_PARALLEL_HANDOFF`
(3) tasks — marks every task `queued` with detail `awaiting the host session`,
and **spawns nothing**. The calling session implements each task and calls
`jobs.complete_task(root, task_id)`, which runs that task's gates and writes
the same `gates.json` and `status.json` `execute_task` would; there is no
worker exit code to weigh, so the gates alone decide. Passing `--backend`
forces `worker`: naming a model is a request for that model. A worker is a
cold session of the same model, so spawning one per task buys a second opinion
from the model already present; reserve it for a differing model (adversarial
verification, a Codex host delegating to Claude) or a genuinely wide round.
Under `host`, `start` never calls `_finalise_job` — nothing drains a loop the
way `worker` mode's does — so `status()` stamps `job.json.finished_at` itself,
the first time every task in the job reads as terminal; found on a real
`gk-trial2` host-execution retrial where the job otherwise finished correctly
(`verdict=ok`, all nine tasks `passed`) but `finished_at` stayed empty.

`jobs.recheck(root, task_ids=None, job_id=None) -> {"job_id", "rechecked",
"missing"}` re-reads **the current** `spec/04-tasks.md`, runs the named tasks'
gates against the working tree, and records the same files with detail
`recheck: … (no worker)`. It is the answer to a gate that moved mid-build,
which is the normal case rather than a mistake: a gate names files and commands
that do not exist until the work is done. Tasks no longer in the file are
returned in `missing`, never silently skipped.

**ADR-0013 decision 4 — the shape is approved before it is written.** `jobs.shape(root)` reports `{tasks, rounds, waves, serial, unevidenced, rounds_if_pruned}` from `spec/04-tasks.md`, and `/gatekit:tasks` shows it — rounds as prominently as the count — before writing the file. A `depends_on` is evidenced when the depending task's title or instruction names the dependency's id or a leaf from its write scope, matched on identifier boundaries so a short id is not found inside a word and a shared ancestor like `src` never counts. `rounds_if_pruned` recomputes depth from the evidenced links alone, ignoring the declared `round`, since that field is a consequence of the links. Advisory only: deciding whether an instruction *needs* a dependency requires understanding both, so nothing refuses. On gk-trial2 this reports 9 tasks / 7 rounds with three unevidenced links and 3 rounds without them.

**ADR-0013 decision 5 — a verification task is not a task.** `spec.validate` warns when a task's `write_scope` holds only test material (a path segment in `_TEST_DIR_SEGMENTS`, or a test-runner config stem) **and** its transitive dependency reach is ≥ 2. A check that passes only once several tasks are done is a completion criterion in `05-gate.md`: as a task it fails on every attempt until the last dependency lands. Reach is transitive because a chain end names one dependency and waits on all of them — the real `e2e-full-flow` declared one and waited on seven. A `warn`, never a `fail`: a legitimate test-only task exists.

ADR-0009 adds four rules to the runner:

- **Preflight.** Unless `start --no-preflight`, every selected task's gates
  run once *before* any worker is spawned; the result is written to
  `tasks/<id>/preflight.json` (same shape as `gates.json`). A task whose
  gates all pass is recorded `passed` with `detail = "gates passed at
  preflight; no worker spawned"` and gets no worker; if nothing exists yet
  under its `write_scope` the detail also carries `warn: gate passed before
  any work existed …` and the line is listed in `job.json.preflight_warnings`
  (a gate that passes on an empty tree is the signature of one that always
  passes). `jobs.classify_gate_result(gate, argv, root=None, tasks=None)`
  sorts every failing gate into four kinds (ADR-0022 adds the fourth). `command_error` — the job is refused with
  `GatePreflightError` (CLI exit 4) naming the task and gate before any
  worker runs — only when the exit code is 126 or 127, or a line matching
  `COMMAND_ERROR_PATTERNS` (`Cannot find module`, `can't open file`, `No such
  file or directory`, `command not found`, `is a directory`) **also names one
  of the gate's own arguments** (or, for `command not found`, its program):
  the interpreter could not run what the fence points at. `suspicious` — the
  job starts and a warning line is printed and stored in
  `job.json.preflight_warnings` — for exit ≥ 2 on its own, a pattern line that
  names nothing from argv (a failing test that mentions a missing fixture),
  or a usage banner opening stderr. `expected` — silent start — for every
  other failure, and always for `ok`/`unverified` results. `--dry-run` skips
  preflight. Refusal is reserved for the named-argument and 126/127 cases;
  everything ambiguous starts.
  **ADR-0022 — `not_yet_runnable`.** `runcheck.missing_paths(text, argv)`
  extracts paths from `ENOENT: no such file or directory, <op> '<p>'`, `No
  such file or directory: '<p>'`, `<p>: No such file or directory` (`<p>`
  opening the line or following `<prog>: `, with no space — an ambiguous
  path with spaces is not extracted), `can't open file '<p>'`, pytest's
  `ERROR: file or directory not found: <p>` and node's `Cannot find module
  '<p>'` when `<p>` looks like a path (absolute, `./`/`../`, a slash and not
  `@scope/…`, or an argv token; never a bare package name) — never `No
  module named`. `runcheck.relativize(raw, root)` collapses `.`/`..`
  (`ntpath` rules for a Windows-shaped path, `posixpath` otherwise), strips
  the root (string and realpath forms of the root, and the realpath form of
  the path where it or its parent exists; either slash, case-insensitive
  drive) or keeps a relative path, and returns `None` outside the root.
  Exit 126/127 is `command_error` unless argv[0] is an interpreter
  (`runcheck.is_interpreter`: `sh bash zsh node python python3 ruby deno bun
  tsx ts-node`, ignoring a version suffix and `.exe`) and the owned missing
  path is one of its arguments (`bash scripts/e2e.sh` before the task writes
  it). A program that could not be executed (`OSError` in `run_gates`,
  recorded as `exit: null` with `stderr_tail = "could not run: <error>"`) is
  `not_yet_runnable` when argv[0] is a path a task writes
  (`runcheck.program_owner`). A program path inside a dependency directory
  (`runcheck.dependency_program`; `DEPENDENCY_MANIFESTS` maps `node_modules`
  → `package.json` and `.venv`/`venv` → `pyproject.toml`, `requirements.txt`,
  `requirements-dev.txt`, `setup.py`, `setup.cfg`, `Pipfile`, `poetry.lock`,
  `uv.lock`, the manifest beside the directory) is `not_yet_runnable` when a
  task writes that manifest, and otherwise `suspicious` (warn "cannot run
  yet … install dependencies" and start), never `command_error`. Anything
  else is `command_error` — the rule `contract baseline` applies. `runcheck.scope_owner(rel, tasks)` returns the
  first task whose `write_scope` glob matches under `gates/write.py:matches`.
  An owned path → `not_yet_runnable`: silent start, and the gate's entry in
  `preflight.json` gains `"preflight": "not_yet_runnable"` and
  `"preflight_detail": "needs <path>, which task <id> writes"`. No owner and
  npm's `Could not read package.json` → `command_error`; no owner and an argv
  token named → `command_error`; both refusal messages then name the missing
  path and say no task in this job writes it (`package.json` for the
  manifest case, whatever npm printed first). When the owned path is one of
  the gate's own arguments (a dependency-directory program covered through
  its manifest included), `jobs start` prints one `note: <task>: gate
  `<name>` runs <path>, which task <id> writes …` line per task and records
  it in `job.json.preflight_notices` (not a warning: a typo'd path inside a
  broad scope now starts and fails after that task). Otherwise ADR-0009's
  rules apply unchanged. `tasks` is the job's task list; without it nothing is owned.
  A gate whose result is `unverified` for "ran no tests" (§5) is not `ok`, so
  preflight never skips its task.
- **Dependency gating.** A task runs only when every `depends_on` id that
  is part of the same job is `passed`; otherwise it stays `queued` with
  `detail = "waiting on <id> (<state>)"` (the state is suffixed `, gates
  unverified` when the dependency's gates could not judge) and, when the job
  drains, becomes `blocked` (terminal). A blocked task was never run and never
  judged, so it is **not** in `NOT_DONE_STATES`: a job whose only non-passed
  tasks are `blocked` reports `unverified`, never `fail`. Dependencies outside
  the job never block. There is no automatic resume: the operator starts the
  blocked task with `start --tasks` once its dependency passes.
- **Re-read on redelegate.** `redelegate` parses the current
  `spec/04-tasks.md` before archiving the attempt; if the task's fence
  differs from the job's `task.json` snapshot the snapshot is replaced and
  the status detail says `task re-read from spec/04-tasks.md (gates changed
  | instruction changed | write_scope changed)`. A task id no longer in the
  file is refused with a `ValueError` naming the file. `start` still
  snapshots; edits during a run do not reach running workers. The
  redelegate prompt also carries a fixed paragraph telling the worker that
  a gate command which looks wrong is to be reported, not coded around.
- **Stop.** `_spawn_worker` records `pid` and `pid_started_at` in
  `status.json`; `execute_task` clears `pid` the moment the worker is reaped,
  before the task moves to `gating`. `jobs stop [--job ID]` writes `stop.json`
  in the job dir (the runner checks it before each task and after each worker
  returns), and for each task still in `running` — never `gating` — whose
  recorded pid is alive **and** whose `ps -o etime=` age agrees with
  `pid_started_at` within `STOP_PID_AGE_TOLERANCE_S`, calls
  `_terminate_pid` (SIGTERM, `STOP_GRACE_S` seconds, then SIGKILL). A pid
  that fails either check is listed in the result's `skipped`, never
  signalled. Every running or queued task is recorded `stopped` and
  `job.json.stopped_at` is written. `stopped` is terminal and not done.

`status.json.state` therefore ∈ `queued|running|gating|passed|failed|timeout|
redelegated|stopped|blocked`; `TERMINAL_STATES` and `NOT_DONE_STATES` in
`jobs.py` are the two sets every consumer uses. `status` reports `fail` when
any task is in a not-done state (`failed`, `timeout`, `stopped`), `unverified`
when the rest are not all `passed` (running, queued, or `blocked`), and
`done` when every task is terminal.

`jobs evaluate [--backend name] [--prompt FILE] [--lang ko|en]
[--force-read-only-evaluator]` runs one worker as the independent evaluator
(ADR-0007): job dir
`.gatekit/jobs/<job_id>/evaluate/{task.json,prompt.md,output.txt,stderr.txt,status.json}`,
`job.json.kind = "evaluate"`, env `GATEKIT_TASK_ID=evaluate` with
`task.json.write_scope = "read-only"` so the write gate refuses writes inside
the evaluator's own session regardless of backend. `state` ∈
`passed|failed|timeout`; anything but `passed` is `unverified` for every
criterion. Its stdout ends with the evaluator's reply tail, which is the
verdict table.

**ADR-0015 — the Codex evaluator's own sandbox.** For every backend except
Codex, `evaluate` resolves with `read_only=True` (the backend's
`read_only_argv`), which is the real protection beneath the write gate. Codex
is checked instead: `codex exec --sandbox read-only` blocks a test runner's
own scratch writes (Vitest's config cache, Playwright's `test-results/`) along
with source edits, so most criteria come back `unverified` for a reason
unrelated to the code under test. `evaluate` runs Codex's normal `argv`
(`--sandbox workspace-write`) instead, but only when
`hosts.codex_hooks_trusted(root)` confirms this project's `.codex/hooks.json`
has a matching `hooks.state` entry in Codex's own `$CODEX_HOME/config.toml`
(default `~/.codex`) — a project's own `trust_level` is a separate record and
does not imply hook trust, and an untrusted project hook is skipped by Codex
silently rather than refused, so a stray write from an untrusted hook would go
unwatched. When `.codex/hooks.json` is missing, `evaluate` installs it
(`hosts.install`, idempotent) before checking; installing a file never grants
trust, which only a human can do interactively. Untrusted and unforced raises
`jobs.EvaluatorSandboxError` (subclass of `ValueError`, CLI exit 2) naming the
one-time fix: run `codex exec --sandbox workspace-write "echo trust-check"` by
hand and approve the hook-trust prompt. `--force-read-only-evaluator` keeps
the stricter sandbox regardless. `hosts.codex_hooks_trusted` parses
`config.toml` with `tomllib` (3.11+) or a narrow hand-rolled reader scoped to
`[hooks.state."<key>"]` table headers only (3.9/3.10); any parse failure or
missing file reads as **not trusted** — "could not tell" never rounds to
"trusted".

`workers.py`: `list`, `check <name> [--probe]` (`shutil.which` on argv[0] →
ok/fail, `--version` probe → ok/unverified; with `--probe`, one trivial
prompt through `read_only_argv`: answered → ok, non-zero exit → `fail` with
the output tail, since a binary that cannot run a prompt here — not logged
in, or sandboxed away from its credentials — will fail every task; timed out
→ unverified), `set-default <name>`, `enable <name>`, `set-evaluator
<agent|name>`. `/gatekit:build` runs the live probe before `jobs start`.
`claude` is enabled by default; `codex` is disabled until `/gatekit:setup codex`
runs `check` and the user confirms.

## 11. Verdicts (`verdict.py`)

`OK, WARN, FAIL, UNVERIFIED`. `aggregate(list)`: any `fail` → `fail`; else any
`unverified` → `unverified`; else any `warn` → `warn`; else `ok`. Rendering:
`render(v, lang)` gives the localized label; JSON always uses the English token.

## 12. Doctor (`doctor.py`) — 8 axes

1 plugin files present (plugin.json, hooks.json, all gate scripts exist and are non-empty);
2 hooks registered in the running install (compare `~/.claude/plugins/…` cache when present, else `unverified`);
3 project state (`.gatekit/config.json` valid, approvals valid JSON; an out-of-range `stop.budget_s` is `warn` (ADR-0024); the detail names a Stop-gate stand-down recorded in the most recently updated session ledger);
4 spec set (`spec.validate` verdict, or `unverified` when no `spec/`);
5 contract freshness (`source_sha256` matches);
6 workers (default backend `check`);
7 python version ≥ 3.9;
8 host layer: a generated `.codex/hooks.json` (§15), when present, must point at gate scripts that exist (`fail` otherwise); absent is `ok`, since a Claude Code project needs none. A gatekit installed as a Codex plugin whose hooks have no `hooks.state` trust entry in `$CODEX_HOME/config.toml` is `warn` with the terminal `codex` → `/hooks` fix (ADR-0019); doctor never writes trust. Each axis returns `{axis, verdict, detail, fix}` where
`fix` is a copy-pasteable command or empty. Exit 1 iff any `fail`.

## 15. Host layers (`hosts.py`, ADR-0006)

Claude Code loads gatekit as a plugin. Codex CLI reads three things from a
project instead — `.codex/hooks.json`, `.agents/skills/<name>/SKILL.md`,
`AGENTS.md` — and `gatekit install --host codex` generates all three **from
`plugin/`**, which stays the single source:

- `.codex/hooks.json`: the six gates with `--host codex`; `apply_patch`
  joins the write matcher; the Stop timeout is copied from
  `plugin/hooks/hooks.json`.
- one skill per `commands/<name>.md`: `SKILL.md` is a ≤ 40-line shim (the
  plugin skill's trigger text plus the Codex differences: no
  `AskUserQuestion`, `$gatekit-<name>` invocation, project trust) and
  `command.md` is the command body with `${CLAUDE_PLUGIN_ROOT}` replaced by
  the checkout path and `/gatekit:<name>` rewritten to `$gatekit-<name>`.
- `AGENTS.md`: a managed block between `<!-- gatekit:begin -->` and
  `<!-- gatekit:end -->`; text outside it is never touched.

Writes are atomic, reinstalling is idempotent, `--dry-run` lists without
writing. `hosts.status` is `unverified` when absent, `fail` when a
registered gate script does not exist, `ok` otherwise — and says that whether
Codex loads project hooks depends on the user trusting `.codex/`, which is
not readable from here. Observed in a Codex 0.154 session (parity table in
the README): `apply_patch` and shell commands arrive as their own events and
are gated; `collaborationspawn_agent` hides the prompt, so the spawn gate
allows and records `spawn_unscoped` (the subagent's own writes are still
gated); there is no `AskUserQuestion`, so the question gate has nothing to
count.

**Codex plugin install (ADR-0019).** Codex also installs `plugin/` itself as
a plugin from this repository's marketplace (it accepts the Claude-format
manifests). No generated layer is involved: the plugin's `hooks/hooks.json`
serves both hosts (Codex tool names in the matchers, host from
`PLUGIN_ROOT`), and each `skills/gatekit-*/SKILL.md` shim tells a host
without slash commands to read `commands/<name>.md` two directories up and
apply `policy/codex.md` — which carries the Codex differences and the rule
that `${CLAUDE_PLUGIN_ROOT}` in command text means that plugin directory.
Plugin hooks run only after the user trusts them in a terminal `codex`
session (`/hooks`); the desktop app cannot record trust today
(openai/codex#47283). `gatekit install --host codex` remains for projects
already using the generated layer.

## 13. Testing convention

`cd plugin && python3 -m unittest discover -s tests -v` must pass with no network
and no external binaries. Tests that need a binary (`claude`, `codex`) use a
fake executable created in a temp dir and prepended to `PATH`. Every gate has at
least three tests: allow, deny/block, internal-error-still-exits-0. Fixtures
under `plugin/tests/fixtures/` are small text files only.

`jobs.py` (ADR-0009) additionally covers: preflight classification (already
passing → no worker; command error → `GatePreflightError` and CLI exit 4 with
the gate named; expected failure → worker spawned; `--no-preflight` and
`--dry-run` skip it), the early-pass warning on an empty write scope,
`looks_like_command_error` on each listed signature and on `ok`/`unverified`/
malformed input, redelegate re-reading a corrected gate and refusing a task
removed from the file, the redelegate prompt paragraph, `stop` ending a live
fake worker and marking queued tasks `stopped`, `stop` refusing to signal a
pid whose age does not match the recorded spawn time, `stopped`/`blocked`
counting as not done, and dependency gating (blocked on failure, run on pass,
out-of-job dependency ignored).

ADR-0013 adds: host execution preparing a job and spawning nothing while
recording `execution` and `plan`; `complete_task` writing the same status and
gates files worker execution does, with `unverified` not rounding; an unknown
task id refused; `--backend` forcing worker mode; a config without
`build.execution` still spawning; `recheck` passing a task whose gate was
narrowed, leaving a still-failing one `failed`, reading the current task file
rather than the job snapshot, naming tasks missing from it, and being
idempotent; and `_positionals` not mistaking an option's value for a task id. `shape` counting tasks and rounds, sharing a round between independent tasks, flagging a dependency with no evidence in the instruction while sparing one named there or named by id, and reporting the pruned round total; a task warned as verification-shaped when it writes only test paths and its **transitive** dependency reach is two or more, and not warned on one direct dependency, a source path in scope, a `read-only` scope, or a cycle; the finding staying a `warn`. The PreCompact hook: recording every task's state, naming the job, creating PROGRESS.md when absent, leaving human content intact, replacing its own block on a second compaction, writing nothing with no job, surviving a corrupt status file and an unwritable spec dir, exiting 0 as a subprocess, and leaving `spec validate` findings unchanged. ADR-0014: a failure incrementing the attempt ledger and a pass clearing it; `blocked`/`stopped` leaving it alone; `redelegate` and `start` both refusing at the budget with exit 3; `--force-retry` clearing exactly one task; `recheck` not counting while `complete_task` does; a corrupt or missing `attempts.json` reading as empty; the status row and table showing the carried count. ADR-0023: grading files from a script argv[0], a spec path argument and a pytest node id, never from a bare program, a path outside the root, a `..` escape, a symlink out, a directory or a missing file, with `${CLAUDE_PLUGIN_ROOT}` expanded; the reviewer's brownfield checks (`grep -q print src/app.py`, `eslint src/x.js`, `node --check src/app.js`, `tsc src/index.ts`, `sqlite3 app.db`, `dist/index.html`, an interpreter's non-test script) naming no grading file while every test shape does, gatekit's top-level `spec/` counting only by a test-shaped basename (`spec/tokens.json`, `spec/02-design.md` never; `spec/models/user_spec.rb` and a nested `app/spec/` still do) so a token update after approval and re-derive stays `ok`, nothing under build-output or dependency directories counting, `--opt=path`, `[param]` and `:line[:col]` handled, a 3 MiB file hashed in chunks; `derive` recording the hashes; a changed or deleted grading file turning a would-be `ok` criterion `unverified` with the instruction before the paths and surviving the 120-character cut, an unchanged one staying `ok`, a failing one staying `fail`, re-derive clearing it only without an approval, the Stop gate not reusing a stale `ok` and adding a hint line in English and Korean; approval pinning the derived grading (or hashing it when no matching contract exists), the reviewer's repro (approve, edit the test, derive: still `unverified` with `grading_unapproved`, `approve check` `fail` naming the path, prompt context STALE, Stop gate routing to `/gatekit:gate`; approve again: `ok`), a test written after approval not held back, an approval without `grading` judged on the file alone, the write gate still allowing writes, and `approve` refused under `GATEKIT_TASK_ID` while `check`/`list` work; the Bash gate under `GATEKIT_TASK_ID` denying `env -u GATEKIT_TASK_ID … gatekit.py approve`, `${CLAUDE_PLUGIN_ROOT}` and quoted paths, a bare `gatekit`, `-m gatekit`, `VAR=` prefixes, `&&` chains, `bash -c`, `eval`, `xargs` and unlexable text, with the reason in English and Korean, while allowing `approve check`/`approve list`, other subcommands and the host session, and exiting 0 on internal error; a task that failed and then passed with its test file changed flagged in `status.json`, the status table and `results --compact` through the worker/redelegate, host `complete` and `recheck` paths, a preflight failure counting, a failure in one job and a pass in the next (or at the next job's preflight) flagged, `--force-retry` keeping it so a pass after fail, loosen and a forced retry is still flagged (and dropping an entry with no failed hashes), `status --all --json` and `results --all --compact` covering every job, and one that passed without a change or with a test first written after preflight not flagged. ADR-0022: the study-gallery repro (npm ENOENT on `package.json`) as `not_yet_runnable` with a silent start and the owner named in `preflight.json` when another job task's scope covers it, and as `command_error` naming the path when none does; a path outside the root never owned; a Windows-style message relativized; 126/127 still `command_error`; `No module named` extracting nothing; each `no-tests-signatures.json` signature turning a would-be `ok` into `unverified` and its negative (a positive count) staying `ok`; mixed output with a positive count staying `ok`; pytest and unittest exit 5 as `unverified`; pytest all-deselected exit 5 as `unverified` and exit 0 untouched; go `coverage:` and `(cached)` lines counting as a real run while `[no tests to run]` does not, and the go pattern anchored; ANSI colour ignored; a structurally malformed signature file (top-level list, `signatures` an object, non-object entries, non-integer or boolean exits) never raising, one bad entry not disabling the rest, and the Stop hook still judging and recording under such a file; the reuse record ignored without a matching `signatures_sha256`; `bash`/`node` on a missing script a task writes as `not_yet_runnable` (127 and `Cannot find module`), argv[0] not found and an unnamed path at 127 staying `command_error`; a bare package name never a path; pytest's `file or directory not found`; an ambiguous path with spaces not extracted; `..` segments and a symlinked prefix relativized; a could-not-run program reaching the classifier, refused when no task writes it and started when one does, agreeing with `contract baseline`; `./node_modules/.bin/playwright` and `.venv/bin/pytest` not yet installed as `not_yet_runnable` with a manifest-writing task and as a warn-and-start without one (baseline: `not_yet_runnable` / `unverified`), `nonexistentprog` still refused, and every dependency directory one the tree fingerprint skips; an argv-named owned path printing one `note:` and no warning; the manifest refusal naming `package.json`; jest exit 1 staying `fail`; preflight not skipping a zero-test task; the contract runner applying the same rule; `contract baseline` producing every class, writing `baseline.json`, exiting 0/4/1, respecting the budget, and leaving `contract-last.json` untouched. ADR-0021: `complete_task` refusing past the budget with exit 3 before running any gate, and still running and counting under it; `record_attempt` storing `last_failure_sha` and `repeats`, incrementing `repeats` on identical output, resetting it to 1 on different output, dropping both with no failing-gate output, a pass clearing and `blocked`/`stopped` leaving them, and a pre-ADR-0021 entry still counting; `normalize_gate_output` replacing timestamps, clock times, durations, hex addresses, the project root and trailing whitespace while "3 failed" and "2 failed" still hash differently; `redelegate`, `complete_task` and `start` refusing on `repeats >= 2` with budget left, `max_retries = 0` disabling every refusal, `--force-retry` clearing the repeat; the status table showing `same failure`. Review probes: a duration never spanning a newline (`expected 3\nmin(x)`, `assert 2 == 3\ns`, `count 3\ns = 4` stay distinct), a unit followed by a hyphen not being a duration (`2 us-east`, `10 ms-heavy`), `(1.2 s)` and a tab before the unit still normalizing, `app.js:12:34:56` not being a clock while `12:34:56` is; 200 identical truncated pytest lines ending `in 1.23s` vs `in 12.34s` hashing the same while 199 vs 200 failures do not, and an uncut tail keeping its first line; eight threads recording distinct tasks all surviving, and a concurrent `clear_attempts` dropping no other task. Host execution: `finished_at` absent right after `start`, stamped by `status()` once the last task turns terminal, not stamped while one is still queued, and stamped once (idempotent on repeated calls). ADR-0015: `codex_hooks_trusted`
true for a matching `hooks.state` entry (any event, not only `pre_tool_use`),
false with no config file, no matching entry, malformed TOML, an empty
`[hooks.state]` table, or project-level `trust_level` alone with no
`hooks.state` entry (the real `gk-trial2` shape) — each pinned through both
`tomllib` and the 3.9/3.10 fallback parser, including one case with an escaped
quote in the key; `evaluate` refusing with `EvaluatorSandboxError` naming
`workspace-write` and the trust-check command when Codex hooks are untrusted;
installing the host layer first when `.codex/hooks.json` is absent;
proceeding with the writable `argv` once trusted; `--force-read-only-evaluator`
bypassing the refusal and keeping `read_only_argv`; a non-Codex backend never
triggering the check at all.

ADR-0024 adds: the Stop gate judging with no job and with an unsettled job (an `ok` there not standing down), one handoff run after the last task passes, no criterion executed and exit 0 on every later Stop with `skipped` counted, a new job (even one already settled) or a redelegated task clearing the stand-down, a job with no tasks counting as unsettled, `/gatekit:build` and `/gatekit:verify` prompts re-arming (`block_count` reset, `stop_rearmed`), a settled job with `failed`/`blocked` tasks blocking up to `MAX_BLOCKS` then recording `final_verdict` then standing down, `stop_hook_active` with a non-`ok` verdict not standing down, the verify pipeline standing down after its verdict, the `stop_stood_down` event and field, the prompt line in English and Korean within 600 chars, and the hook still exiting 0 on an internal error after a stand-down; `tier` validated by `derive` and `spec validate`, the Stop gate under `build` running only `turn` criteria and naming `verify` ones as deferred without blocking or `ok`, a contract with no `turn` criterion allowing with `unverified`, `contract run`, `baseline` and the verify-pipeline Stop running every tier, and reuse refusing a record of another scope or with no `scope`; `stop.budget_s` default, cap and invalid values, criteria past the budget deferred and non-blocking, a `fail` before the budget still blocking, a timed-out or ran-no-tests `unverified` that ran still blocking, and the contract's own budget running out still giving `unverified`, also when the Stop budget is spent too. The ADR-0024 review adds: a run cut by the Stop budget recorded as `unverified` (not `ok`) with the deferred ids named, no block spent and no stand-down — at a settled handoff and under `stop_hook_active`; the next Stop running the deferred criteria first and, on the same tree, converging to `ok` and standing down; an edit dropping what an earlier tree judged; a settled job with a `failed`, `timeout` or `blocked` task blocking with an `ok` contract (naming the tasks, English and Korean), recording `fail` (or `unverified` for `blocked` only) after `MAX_BLOCKS` and standing down, a `stopped` task recorded as `fail` without a block, and `stop_hook_active` with such tasks not standing down; `spec validate` warning (not failing) on a contract with no `turn` criterion (English and Korean) and on a `verify`-tier screenshot criterion, and the prompt line and block message saying so when nothing is in the turn tier; the prompt line naming queued tasks of an unfinished job and `jobs stop`, in English and Korean within 600 chars; a ledger with `"stop": null` (or another non-object) still judging, blocking and recording, and the prompt hook still answering; `scope` holding only judged ids; a budget-cut record never reused, by the verify-pipeline Stop included; the prompt line naming budget-deferred ids, and the stood-down line saying `turn-tier <verdict>` and `N deferred to /gatekit:verify`, in English and Korean.

ADR-0012 adds, in `gates/question.py`: a justified over-budget call consuming
its line and raising nothing; an unjustified one raising `unjustified`; the
line single-use across two calls; calls within budget needing none; a blank or
non-string line counting as absent; `budget_exceeded` keeping its meaning; an
unbudgeted pipeline carrying no signals; a repeated and a reworded-same topic
fingerprinting while a merely similar one and two short questions do not;
`repeat_of` naming the earlier call; an all-code option set warning while a
priority question and an option-less question do not; `unrealized` firing when
no write follows and not when one does; a write event clearing the watch,
never counting as a question, and never blocking; and in `gates/prompt.py`,
the signals appearing in `additionalContext` only when non-zero, a malformed
count not breaking the line, and the block staying within 600 chars.

ADR-0011 adds: the `## Screens` block present for a task naming `S2` and
absent for one naming none or naming a screen the spec lacks, only the named
screens carried, `S02` matching `S2` while `S12`/`S20` do not, the block's
layout and state rows matching the spec, ordering after `## Design` and
before `## Reporting`, an unreadable screen spec leaving the prompt usable,
the block reaching the written `prompt.md` through `start`; and in `spec.py`,
an evidence cell citing `preview-*.html` failing validation (in both
`02-screens.md` and `02-design.md`) while prose mentioning the preview and an
unrelated `*-preview.html` capture do not.

## 14. Module interfaces (exact signatures other modules may import)

```python
# paths.py
def project_root(cwd: str | None = None) -> pathlib.Path
def state_dir(root: pathlib.Path) -> pathlib.Path      # root / ".gatekit"
def spec_dir(root: pathlib.Path) -> pathlib.Path       # root / "spec"
def plugin_root() -> pathlib.Path                      # directory containing plugin.json (parent of gatekit/)
def expand_argv(argv: list[str]) -> list[str]           # copy with "${CLAUDE_PLUGIN_ROOT}" → plugin_root() (ADR-0018); bare argv[0] via shutil.which (ADR-0019)
def from_msys(path: str, windows: bool | None = None) -> str   # "/c/x" → "C:/x" on Windows (ADR-0019)

# config.py
DEFAULTS: dict
def load(root: pathlib.Path) -> dict                   # deep-merged with DEFAULTS; missing file → DEFAULTS
def save(root: pathlib.Path, cfg: dict) -> None        # atomic
def stop_budget_s(cfg: dict) -> tuple[float, str]      # ADR-0024: (value in force, problem or "")

# lang.py
def detect(text: str) -> str                           # "ko" | "en"
def run(argv: list[str]) -> int

# verdict.py
OK, WARN, FAIL, UNVERIFIED = "ok", "warn", "fail", "unverified"
ORDER: list[str]
def aggregate(verdicts) -> str
def render(verdict: str, lang: str) -> str

# ledger.py
class Ledger:
    data: dict
    @classmethod
    def load(cls, root: pathlib.Path, session_id: str) -> "Ledger"   # creates if missing
    def save(self) -> None                                          # atomic
    def append_event(self, kind: str, detail: dict | None = None) -> None
    def add_scope(self, owner: str, write_scope: list[str]) -> None
    def scope_conflicts(self, write_scope: list[str]) -> list[dict]  # existing scopes that intersect (glob-aware)
def run(argv: list[str]) -> int

# hookio.py
HOSTS: tuple[str, ...]                                 # ("claude", "codex")
def read_event() -> dict
def host_from_argv(argv: list[str] | None = None, env: dict | None = None) -> str   # "--host <name>"; else PLUGIN_ROOT set → "codex"; else "claude"
def adapt_output(payload: dict | None, host: str) -> dict | None   # render the Stop block / command names per host
def run(handler, stdin=None, exit_process=True, host: str | None = None) -> int   # never raises; always exit 0
def deny(reason: str) -> dict                          # PreToolUse deny payload
def block_stop(reason: str) -> dict                    # Stop block payload
def add_context(text: str) -> dict                     # UserPromptSubmit payload
def log_error(root: pathlib.Path, event_name: str, err: BaseException) -> None

# approval.py
def sha256_file(path: pathlib.Path) -> str
def check(root: pathlib.Path, relpath: str) -> str     # ok | fail | unverified
def check_gate(root: pathlib.Path) -> tuple            # (verdict, paths): check of 05-gate.md + pinned grading (ADR-0023)
def approve(root: pathlib.Path, relpath: str, note: str = "", by: str = "user") -> dict   # PermissionError under GATEKIT_TASK_ID
def run(argv: list[str]) -> int

# contract.py
EXPECT_KEYS: tuple[str, ...]
def validate_expect(expect, ident: str = "?") -> list[str]   # problems; empty when valid
def judge_output(expect: dict, stdout: str, stderr: str) -> list[str]   # unmet output expectations
def derive(root: pathlib.Path) -> dict                 # writes .gatekit/contract.json, returns it
def approved_grading(root, gate_sha256: str) -> dict   # ADR-0023: {criterion id: {relpath: sha256}} an approval pins
def unapproved_grading(root) -> list[str]              # ADR-0023: pinned files the derived contract no longer records as pinned
def status(root: pathlib.Path) -> str                  # ok (fresh) | fail (stale) | unverified (absent)
TIERS: tuple[str, ...]                                 # ("turn", "verify") — ADR-0024
NO_CRITERIA_IN_TIER_REASON: str                        # "no_criteria_in_tier"
def validate_tier(tier, ident: str = "?") -> list[str]  # problems; empty when valid (derive and spec validate share it)
def tier_scope(root: pathlib.Path, tiers: tuple[str, ...] | None = None) -> list[str]   # sorted ids the tiers select
BUDGET_DEFERRED_REASON: str                            # "deferred_by_stop_budget" — ADR-0024 review
def execute(root: pathlib.Path, total_budget_s: float | None = None, cap_s: float | None = None, first: list[str] | None = None, tiers: tuple[str, ...] | None = None, start_budget_s: float | None = None, deferred_first: list[str] | None = None) -> dict   # {"verdict", "criteria":[...], "reasons":[...], "total_budget_s", "scope" (ids judged), "deferred"}; cap_s lowers the applied budget
def budget_deferred_ids(result: dict) -> list[str]     # ids a result left unjudged for the Stop budget
def carry_forward(result: dict, previous: dict) -> dict   # fill budget-deferred criteria from a same-tree result, re-aggregate
def same_tree_record(root: pathlib.Path) -> dict | None   # last record when contract, signatures and tree are unchanged
def covers(root: pathlib.Path, record: dict | None, tiers: tuple[str, ...] | None = None) -> bool   # scope equals the tier selection and no budget deferral
def reusable_last(root: pathlib.Path, tiers: tuple[str, ...] | None = None) -> dict | None   # ADR-0020/0024: same_tree_record + covers
def baseline(root: pathlib.Path, total_budget_s: float | None = None) -> dict   # writes .gatekit/baseline.json (ADR-0022)
def run(argv: list[str]) -> int

# runcheck.py (ADR-0022)
def grading_files(argv: list, root) -> list[str]         # ADR-0023: relpaths of argv[0] scripts and test-shaped argv files in the root
def grading_hashes(argv: list, root) -> dict           # ADR-0023: {relpath: sha256} of grading_files, 1 MiB chunks
def grading_patterns() -> dict                         # ADR-0023: {"dirs","basenames","exclude_dirs"} from grading-patterns.json
def ran_no_tests(stdout: str, stderr: str, exit_code) -> str | None   # signature id, or None; ANSI stripped
def signatures_digest() -> str | None                  # sha256 of no-tests-signatures.json, None if unreadable
def missing_paths(text: str, argv=None) -> list[str]   # raw paths named as missing; argv admits a bare `Cannot find module` token
def is_missing_manifest(text: str) -> bool             # npm "Could not read package.json"
def relativize(raw: str, root) -> str | None            # POSIX path relative to root, None outside
def scope_owner(relpath: str, tasks: list[dict]) -> str | None   # first task whose write_scope covers relpath
def missing_path_owner(gate: dict, root, tasks, argv=None) -> dict | None   # {"path", "owner", "manifest", "argv_named"}: first owned path, else package.json (manifest) or the first extracted one
def is_interpreter(program) -> bool                    # argv[0] is sh/bash/zsh/node/python/python3/ruby/deno/bun/tsx/ts-node
def program_owner(program, root, tasks) -> tuple       # (relpath, owner) for a program given as a path; (None, None) for a bare name
def dependency_program(program, root, tasks) -> dict | None   # {"path", "dir", "manifest", "owner"} for a program under node_modules/.venv/venv

# spec.py
def validate(root: pathlib.Path, lang: str | None = None) -> dict      # {"verdict", "findings":[{"file","verdict","message"}], "lang"}
def parse_fences(text: str, name: str) -> list[dict]                   # all ```<name> JSON fences
def run(argv: list[str]) -> int

# jobs.py
def run(argv: list[str]) -> int                        # start / status / wait / results / complete / recheck / redelegate / stop / evaluate / clean
def start(root, task_ids=None, backend_name=None, parallel=None, dry_run=False, no_preflight=False) -> dict   # raises GatePreflightError (ADR-0009)
def preflight(root, jdir, tasks: list[dict]) -> dict   # {"passed": [ids], "warnings": [str], "notices": [str]}; raises GatePreflightError
def classify_gate_result(gate: dict, argv=None, root=None, tasks=None) -> str  # "command_error" | "not_yet_runnable" | "suspicious" | "expected" (ADR-0009, ADR-0022)
def looks_like_command_error(gate: dict, argv=None) -> bool   # classify_gate_result(...) == "command_error"
def stop(root, job_id: str | None = None) -> dict      # {"job_id", "stopped", "signalled", "skipped"}
def evaluate(root, backend_name=None, prompt_path=None, timeout_s=None, lang="en", force_read_only_evaluator=False) -> dict   # raises EvaluatorSandboxError (ADR-0015)
class EvaluatorSandboxError(ValueError)                # untrusted Codex hooks refuse workspace-write (ADR-0015)
def load_tasks(root: pathlib.Path) -> list[dict]       # from spec/04-tasks.md via spec.parse_fences
def parse_screens(text: str) -> dict                   # {"S2": {"name","layout","states"}} from 02-screens.md (ADR-0011)
def execution_mode(cfg: dict) -> str                   # "host" | "worker" (ADR-0013)
def complete_task(root, task_id: str, job_id: str | None = None) -> dict   # host-implemented task -> gates -> status.json
def recheck(root, task_ids=None, job_id: str | None = None) -> dict        # {"job_id","rechecked","missing"}; gates only, no worker
def note_grading(root, jdir, task_id: str, gates: dict, passed: bool) -> list    # ADR-0023: attempts.json failed_grading -> status.json grading_changed_after_failure, returns the latter
def all_job_ids(root) -> list                          # every job id, oldest first (`status --all`)
def shape(root, task_ids=None) -> dict                 # {tasks, rounds, waves, serial, unevidenced, rounds_if_pruned} (ADR-0013)
def record_attempt(root, task_id: str, state: str, job_id="", gate="", gates=None) -> int   # ADR-0014; gates -> fingerprint (ADR-0021)
def normalize_gate_output(text: str, root=None) -> str   # strips volatile tokens only (ADR-0021)
def failure_fingerprint(gates: dict, root=None) -> str | None   # sha256 of failing gates (cut tails drop their first line), None without evidence (ADR-0021)
def repeated_failures(root, task_id: str) -> int     # consecutive identical failures (ADR-0021)
def consecutive_failures(root, task_id: str) -> int    # ADR-0014
def clear_attempts(root, task_id: str) -> None         # --force-retry, ADR-0014
class GatePreflightError(ValueError)
TERMINAL_STATES, NOT_DONE_STATES                       # the two state sets every consumer of status.json uses

# workers.py
def resolve(root: pathlib.Path, name: str | None = None, read_only: bool = False) -> dict   # backend dict incl. name, argv, enabled, unsafe, read_only
def evaluator_name(root: pathlib.Path) -> str        # "agent" | backend name
def check(root: pathlib.Path, name: str) -> dict       # {"name","verdict","detail"}
def run(argv: list[str]) -> int

# doctor.py
def diagnose(root: pathlib.Path) -> dict               # {"verdict","axes":[{"axis","verdict","detail","fix"}]}

# hosts.py
INSTALLABLE_HOSTS: tuple[str, ...]                     # ("codex",)
def install(root: pathlib.Path, host: str, plugin_root: pathlib.Path | None = None, dry_run: bool = False) -> dict   # {"host","written":[relpaths]}
def status(root: pathlib.Path, host: str, plugin_root: pathlib.Path | None = None) -> dict   # {"verdict","detail","fix"}
def codex_hooks(plugin_root: pathlib.Path) -> dict     # the .codex/hooks.json document
def codex_hooks_trusted(root: pathlib.Path) -> bool    # ADR-0015: hooks.state entry present, not just project trust_level
def rewrite_command(text: str, plugin_root: pathlib.Path) -> str
def merged_agents_md(existing: str | None, plugin_root: pathlib.Path) -> str
def run(argv: list[str]) -> int
def run(argv: list[str]) -> int
```

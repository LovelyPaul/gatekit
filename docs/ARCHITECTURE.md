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
│   │   ├── mockup.md      /gatekit:mockup      → spec/02-screens.md, spec/tokens.json, gap entries in ledger
│   │   ├── tasks.md       /gatekit:tasks       → spec/04-tasks.md
│   │   ├── gate.md        /gatekit:gate        → spec/05-gate.md, .gatekit/contract.json, approvals
│   │   ├── build.md       /gatekit:build       → worker jobs over spec/04-tasks.md
│   │   ├── verify.md      /gatekit:verify      → independent E2E + report check
│   │   ├── doctor.md      /gatekit:doctor
│   │   └── setup.md       /gatekit:setup       → optional Codex backend, config
│   ├── skills/<name>/SKILL.md           # ≤ 40-line NL trigger shims that point at the command
│   ├── hooks/hooks.json                 # 6 hook registrations (see §3); auto-loaded, never listed in plugin.json
│   ├── gatekit/                         # kernel package (stdlib only)
│   │   ├── cli.py         dispatcher: python3 -m gatekit <sub>
│   │   ├── hookio.py      hook stdin/stdout contract, safe wrapper, host dialects (§3)
│   │   ├── hosts.py       generated host layers: `gatekit install --host codex` (§15)
│   │   ├── ledger.py      per-session run ledger
│   │   ├── lang.py        output_lang detection
│   │   ├── verdict.py     4-state vocabulary + aggregation
│   │   ├── contract.py    completion contract derive/validate/run
│   │   ├── approval.py    hash-anchored approvals
│   │   ├── spec.py        spec set validation
│   │   ├── jobs.py        job runner (job dir, atomic writes, spawn, gates, redelegate)
│   │   ├── workers.py     worker backends (claude default, codex optional, custom)
│   │   ├── doctor.py      8-axis diagnosis
│   │   ├── config.py      .gatekit/config.json loader with defaults
│   │   ├── paths.py       project root / state dir resolution
│   │   └── gates/         hook entry points: prompt.py write.py bash.py spawn.py question.py stop.py
│   ├── spec-kit/
│   │   ├── templates/{ko,en}/01-prd.md … 05-gate.md, RECOVERY.md, PROGRESS.md
│   │   └── heading-map.json             # canonical headings per file per language
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
│   ├── 03-architecture.md
│   ├── 04-tasks.md             # tasks as ```gatekit-task JSON fences (§6)
│   ├── 05-gate.md              # criteria as ```gatekit-criterion JSON fences (§5)
│   ├── RECOVERY.md
│   ├── PROGRESS.md
│   └── tokens.json             # optional, from mockup pipeline
└── .gatekit/
    ├── config.json             # committed. see §9
    ├── approvals.json          # committed. see §7
    ├── contract.json           # derived from 05-gate.md by `gatekit contract derive`
    ├── runs/<session_id>.json  # ignored. ledger (§4)
    ├── runs/hook-errors.log    # ignored
    └── jobs/<job_id>/          # ignored. see §10
```

`paths.project_root(cwd)` = nearest ancestor containing `.gatekit/` or `.git/`, else cwd.

## 3. Hook I/O contract (`hookio.py`)

Claude Code passes a JSON object on stdin. Codex CLI passes the same object
(same field names) to hooks registered in `.codex/hooks.json`; the gates
serve both hosts from one script, learning the host from `--host <name>` on
their own argv (`hookio.host_from_argv`, default `claude`). Only the Stop
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
PreToolUse `Write|Edit|MultiEdit|NotebookEdit`→`gates/write.py`,
PreToolUse `Bash`→`gates/bash.py` (ADR-0004),
PreToolUse `Agent|Task`→`gates/spawn.py`, PostToolUse `AskUserQuestion`→`gates/question.py`,
Stop→`gates/stop.py`.

Gate behaviour:

- **prompt**: ensure ledger exists for `session_id`; detect `output_lang` from `prompt` (§8) and store it — for a slash command only the `<command-args>` content is the user's words, and empty args keep the stored language; **set `active_pipeline`** when the prompt invokes `/gatekit:<pipeline>`. Claude Code delivers a slash command as the tagged body `<command-message>…</command-message>` / `<command-name>/gatekit:<name></command-name>` / `<command-args>…</command-args>`; that tag, a bare `/gatekit:<name>` at the start of the prompt, and the `# /gatekit:<name>` title line of an expanded command body are recognised within the first 12 lines. A mid-sentence mention is not an invocation. `doctor` and `setup` clear it; an unknown name leaves it alone; a plain prompt keeps it. Entering a different pipeline resets `questions` to its defaults. This is the **only** production writer of `active_pipeline` — commands never set it by prose. Inject `additionalContext` (≤ 600 chars) with `output_lang`, question budget state, active pipeline, and unresolved gate count. Never blocks.
- **write**: for `apply_patch`, apply the rules below to every file the patch header names (a patch naming no file is denied while a rule is active). Otherwise deny when (a) `config.enforce_spec_before_code` is true, `spec/` exists, `.gatekit/approvals.json` has no valid approval for `spec/05-gate.md`, and the target path is outside the allowlist `spec/**, .gatekit/**, docs/**, README*, *.md at root`; or (b) env `GATEKIT_TASK_ID` is set and the target is outside that task's `write_scope` (from the job's `task.json`). Reason text is in `output_lang`.
- **bash**: apply the write rules (a) and (b) to every file a Bash command would write, read statically from the command text: redirections (`>`, `>>`, `&>`, `>|`, `N>`), `tee`, `sed -i`/`perl -i`, `cp`/`mv`/`ln`/`install`/`rsync` destinations, `touch`/`rm`/`mkdir`/`truncate`/`chmod`/`chown` operands, `dd of=`, `sort -o`, `curl -o`, `wget -O`, `tar -C`/`-f`, `unzip -d`, `zip`, with `cd` tracked across `;`/`&&`/`||`/`|`/newlines, `VAR=`/`sudo`/`env`/`nohup` prefixes stripped, here-document bodies ignored, `/dev/*` targets ignored and `sh|bash|zsh -c "…"` parsed recursively. Fast path: when no rule could deny anything (no `GATEKIT_TASK_ID`, spec gate approved or absent) the command is allowed without parsing. When a rule is active and a write's target **cannot be determined** — `$VAR` or backticks in a path, `cd` to an unknown directory, `eval`, `xargs`, `patch`, `trap`, `find -exec/-delete`, working-tree `git` subcommands (`apply`, `checkout`, `restore`, `reset`, `merge`, `stash`, `init`, `clone`, …), inline interpreter code (`python3 -c`, `node -e`, `perl -e`, stdin scripts), `awk`, command-line editors (`ed`, `ex`, `vim`, `nano`), `busybox`, downloads that choose their own file name (`curl -O`, bare `wget`), process substitution, unbalanced quotes — **deny** with reason `opaque`: "could not tell" is never rounded to "allowed". Programs invoked by name (`npm run build`, `python3 script.py`) are outside its reach by design. Reason text is in `output_lang`.
- **spawn**: the spawn prompt must contain a fenced block ` ```gatekit-scope ` with JSON `{"write_scope": [globs] | "read-only", "stop_when": "…", "tools": [...] | "inherit"}`. Deny if missing/invalid, or if `write_scope` intersects any scope already recorded in the ledger for this session. On allow, record the scope in the ledger. No regex over prose: parse the fence as JSON.
- **question**: increment `ledger.questions.asked`; if `asked > budget.max_calls` (default 2 for interview, unlimited otherwise) record `budget_exceeded=true` (informational; commands read it).
- **stop**: if `.gatekit/contract.json` exists and the ledger's `active_pipeline` is `build` or `verify`: run the contract (§5). On any `fail` or `unverified` criterion and `block_count < 3` and not `stop_hook_active`: block with a reason listing failing criteria; increment `block_count`. Otherwise allow and record `final_verdict` in the ledger (never a blank).

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
  "active_pipeline": null | "discover" | "interview" | "mockup" | "tasks" | "gate" | "build" | "verify",
  "questions": {"asked": 0, "max_calls": 2, "budget_exceeded": false},
  "scopes": [{"owner": "agent-label-or-prompt-hash", "write_scope": ["src/auth/**"], "declared_at": "iso"}],
  "stop": {"block_count": 0, "final_verdict": null, "last_reasons": []},
  "events": [{"ts": "iso", "kind": "…", "detail": {}}]
}
```

`events` is append-only, capped at 500 (oldest dropped).

## 5. Completion contract (`contract.py`)

Criteria are declared in `spec/05-gate.md` as fenced JSON blocks:

````
```gatekit-criterion
{"id": "tests-pass", "argv": ["python3", "-m", "unittest", "discover"], "expect": {"exit": 0}, "timeout_s": 30, "artifacts": ["reports/junit.xml"]}
```
````

`gatekit contract derive` parses all fences into `.gatekit/contract.json`:

```json
{"version": 1, "source_sha256": "<sha of 05-gate.md>", "criteria": [ … ], "derived_at": "iso"}
```

`gatekit contract run [--json]` executes each criterion with `subprocess.run`
(no shell), `cwd` = project root, per-criterion timeout = `min(timeout_s, remaining)`
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
Timeout or budget exhaustion → `unverified`, never `ok`. Missing artifact → `fail`.
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
with intersecting write_scope, every task has ≥ 1 gate.

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

## 8. Output language (`lang.py`)

`detect(text) -> "ko" | "en"`: count Hangul syllables/jamo vs Latin letters in
`text`; `ko` if Hangul ≥ 30% of letters, else `en`. Empty text → `en`.
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
 "verify": {"evaluator": "agent"}}
```

Sandboxing is never disabled by default; a backend with a bypass flag must set
`"unsafe": true` and the job receipt records it. `read_only_argv` is the
backend as an evaluator and must not be able to write; a backend without one
cannot grade, and its writable `argv` is never substituted. `verify.evaluator`
is `agent` (the host's own read-only subagent) or a backend name (ADR-0007).

## 10. Jobs and workers (`jobs.py`, `workers.py`)

Job dir `.gatekit/jobs/<job_id>/`: `job.json` (tasks, backend, started_at,
config snapshot), per task `tasks/<id>/{task.json,status.json,prompt.md,output.txt,stderr.txt,gates.json,attempt-N/}`.
All JSON writes atomic. Worker = argv list + the prompt on stdin, env includes
`GATEKIT_TASK_ID=<id>` and `GATEKIT_JOB_ID=<job_id>` so the write gate can
enforce `write_scope` inside the worker session. `status.json.state` ∈
`queued|running|gating|passed|failed|timeout|redelegated`. Gates run only after
the worker exits; a worker that exits 0 but fails a gate is `failed`, never
`passed`. `redelegate <task>` archives the attempt to `attempt-N/` and re-runs
with the failed gate output appended to the prompt, up to `max_retries`.
`results --compact` prints one line per task: `id state gates_passed/total`.

`jobs evaluate [--backend name] [--prompt FILE] [--lang ko|en]` runs one
read-only worker as the independent evaluator (ADR-0007): job dir
`.gatekit/jobs/<job_id>/evaluate/{task.json,prompt.md,output.txt,stderr.txt,status.json}`,
`job.json.kind = "evaluate"`, backend resolved with `read_only=True`, env
`GATEKIT_TASK_ID=evaluate` with `task.json.write_scope = "read-only"` so the
write gate refuses writes inside the evaluator's own session on top of the
CLI sandbox. `state` ∈ `passed|failed|timeout`; anything but `passed` is
`unverified` for every criterion. Its stdout ends with the evaluator's reply
tail, which is the verdict table.

`workers.py`: `list`, `check <name>` (`shutil.which` on argv[0] → ok/fail,
`--version` probe → ok/unverified), `set-default <name>`, `enable <name>`,
`set-evaluator <agent|name>`.
`claude` is enabled by default; `codex` is disabled until `/gatekit:setup codex`
runs `check` and the user confirms.

## 11. Verdicts (`verdict.py`)

`OK, WARN, FAIL, UNVERIFIED`. `aggregate(list)`: any `fail` → `fail`; else any
`unverified` → `unverified`; else any `warn` → `warn`; else `ok`. Rendering:
`render(v, lang)` gives the localized label; JSON always uses the English token.

## 12. Doctor (`doctor.py`) — 8 axes

1 plugin files present (plugin.json, hooks.json, all gate scripts exist and are non-empty);
2 hooks registered in the running install (compare `~/.claude/plugins/…` cache when present, else `unverified`);
3 project state (`.gatekit/config.json` valid, approvals valid JSON);
4 spec set (`spec.validate` verdict, or `unverified` when no `spec/`);
5 contract freshness (`source_sha256` matches);
6 workers (default backend `check`);
7 python version ≥ 3.9;
8 host layer: a generated `.codex/hooks.json` (§15), when present, must point at gate scripts that exist (`fail` otherwise); absent is `ok`, since a Claude Code project needs none. Each axis returns `{axis, verdict, detail, fix}` where
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
not readable from here. Known gaps under Codex, stated in the parity table
in the README: the spawn gate's tool matcher and the question gate's
`AskUserQuestion` matcher are Claude Code tool names and are `unverified`
until observed in a Codex session.

## 13. Testing convention

`cd plugin && python3 -m unittest discover -s tests -v` must pass with no network
and no external binaries. Tests that need a binary (`claude`, `codex`) use a
fake executable created in a temp dir and prepended to `PATH`. Every gate has at
least three tests: allow, deny/block, internal-error-still-exits-0. Fixtures
under `plugin/tests/fixtures/` are small text files only.

## 14. Module interfaces (exact signatures other modules may import)

```python
# paths.py
def project_root(cwd: str | None = None) -> pathlib.Path
def state_dir(root: pathlib.Path) -> pathlib.Path      # root / ".gatekit"
def spec_dir(root: pathlib.Path) -> pathlib.Path       # root / "spec"
def plugin_root() -> pathlib.Path                      # directory containing plugin.json (parent of gatekit/)

# config.py
DEFAULTS: dict
def load(root: pathlib.Path) -> dict                   # deep-merged with DEFAULTS; missing file → DEFAULTS
def save(root: pathlib.Path, cfg: dict) -> None        # atomic

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
def read_event() -> dict
def run(handler) -> None                               # never raises; always exit 0
def deny(reason: str) -> dict                          # PreToolUse deny payload
def block_stop(reason: str) -> dict                    # Stop block payload
def add_context(text: str) -> dict                     # UserPromptSubmit payload
def log_error(root: pathlib.Path, event_name: str, err: BaseException) -> None

# approval.py
def sha256_file(path: pathlib.Path) -> str
def check(root: pathlib.Path, relpath: str) -> str     # ok | fail | unverified
def approve(root: pathlib.Path, relpath: str, note: str = "", by: str = "user") -> dict
def run(argv: list[str]) -> int

# contract.py
def derive(root: pathlib.Path) -> dict                 # writes .gatekit/contract.json, returns it
def status(root: pathlib.Path) -> str                  # ok (fresh) | fail (stale) | unverified (absent)
def execute(root: pathlib.Path, total_budget_s: float | None = None, cap_s: float | None = None) -> dict   # {"verdict", "criteria":[...], "reasons":[...], "total_budget_s"}; cap_s lowers the applied budget
def run(argv: list[str]) -> int

# spec.py
def validate(root: pathlib.Path, lang: str | None = None) -> dict      # {"verdict", "findings":[{"file","verdict","message"}], "lang"}
def parse_fences(text: str, name: str) -> list[dict]                   # all ```<name> JSON fences
def run(argv: list[str]) -> int

# jobs.py
def run(argv: list[str]) -> int                        # start / status / wait / results / redelegate / evaluate / clean
def evaluate(root: pathlib.Path, backend_name: str | None = None, prompt_path=None, timeout_s=None, lang: str = "en") -> dict
def load_tasks(root: pathlib.Path) -> list[dict]       # from spec/04-tasks.md via spec.parse_fences

# workers.py
def resolve(root: pathlib.Path, name: str | None = None, read_only: bool = False) -> dict   # backend dict incl. name, argv, enabled, unsafe, read_only
def evaluator_name(root: pathlib.Path) -> str        # "agent" | backend name
def check(root: pathlib.Path, name: str) -> dict       # {"name","verdict","detail"}
def run(argv: list[str]) -> int

# doctor.py
def diagnose(root: pathlib.Path) -> dict               # {"verdict","axes":[{"axis","verdict","detail","fix"}]}
def run(argv: list[str]) -> int
```

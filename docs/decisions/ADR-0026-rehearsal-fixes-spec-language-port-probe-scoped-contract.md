# ADR-0026: Language from the spec, a doctor port probe, a scoped contract field, evaluator scratch inside the project

Status: accepted 2026-10-03 (owner approval in session).

(ADR-0025 is held by a draft that is not part of this change; this ADR takes
the next free number.)

## Context

A rehearsal of 0.16.0 on a small Korean project (one `/gatekit:build`, three
follow-up turns, one `/gatekit:verify`) found four problems.

1. **The output language fell back to English.** The user's only prompt was
   `/gatekit:build`. Claude Code sends that as a tagged body with empty
   `<command-args>`, which carries no language signal, so the ledger kept its
   blank `en`. The spec was Korean (`gatekit lang "$(head -40
   spec/01-prd.md)"` prints `ko`). Build reports and Stop-gate block messages
   came out in English in a Korean project.
2. **Doctor missed a port clash.** Port 4173 was held by a long-running
   server from another project. With Playwright's `reuseExistingServer:
   true`, the e2e tests ran against that app and failed in ways that pointed
   nowhere near the cause.
3. **The context line overstated what was judged.** The Korean stand-down
   line mixed languages (`stop 게이트 해제`) instead of using the manual's
   terms, and the line showed `contract=ok` while the `verify`-tier criteria
   had not been judged yet. `contract=ok` means "the contract matches the
   approved gate file", but next to a stand-down it reads as "fully verified".
4. **The evaluator wrote outside the project.** The `agent` evaluator, whose
   scope is read-only, wrote its own driver script, a server log and
   screenshots to `/tmp/gkeval`.

## Decision

### 1. The spec decides the language until the user's own words do

The ledger gains `lang_source: null | "prompt" | "spec"`. When a prompt
carries a language signal (`lang.carries_signal` on `language_signal(text)`),
the prompt hook stores `detect(signal)` and sets `lang_source = "prompt"`, as
before. When it carries none and `lang_source` is not `"prompt"`, the hook
calls `lang.from_spec(root)`: the first 40 lines of `spec/01-prd.md`, else of
`spec/00-discovery.md`, the first one that carries a signal. If that gives an
answer, the hook stores it with `lang_source = "spec"`. With no spec, or no
signal in it, the stored value stays (`en` in a new ledger).

A later prompt with a real signal still wins, and from then on the spec is no
longer consulted in that session. Korean is still never a default: the
language comes from text the user wrote, either the prompt or the spec they
approved.

### 2. Doctor probes the dev-server port (axis 3, project state)

Axis 3 reads `playwright.config.{ts,js,mjs,cjs}` at the project root and any
under `spec/design/e2e/`. In the text after each `webServer` (the next 2000
characters), it takes the numbers in `port: <n>` and in
`url: '<scheme>://<host>:<n>…'`. This is a regex, not a parser. A port set
through a variable or computed is not found, and the manual says so.

For each port it tries a stdlib TCP connect to `127.0.0.1:<port>` (0.3 s
timeout). If something accepts, the axis is `warn` and names the port. On
POSIX, when `lsof` is on `PATH`, it also names the listener's PID, command
and working directory (`lsof -nP -iTCP:<port> -sTCP:LISTEN`, then `lsof -a
-p <pid> -d cwd`), and says whether that directory is inside this project.
The fix says to stop that process or change the port. The axis warns even
for this project's own server: `reuseExistingServer` tests whatever is
listening, and a stale server from an earlier build is the same trap. Doctor
never kills anything. On Windows only the socket probe runs. A probe that
raises is skipped. Axis 3 is never failed by the probe, and doctor still
exits normally.

This goes in axis 3 rather than a ninth axis. The listener is project state
that tests depend on, and "8 axes" stays true everywhere it is written.

### 3. The context line says what was judged, in the manual's words

The Korean stand-down line uses the manual's terms (`docs/manual/07-gates.md`):
`Stop 게이트` and `물러남`, with `turn 등급` for the tier, which is the
manual's own term and keeps the value `turn` as an identifier. It no longer
says `stop 게이트 해제`.

The `contract=` field adds scope when the last recorded result
(`.gatekit/runs/contract-last.json`) was written against the current contract
and did not judge every criterion:

- `contract=ok (turn tier; N deferred to /gatekit:verify)` when the unjudged
  criteria are `verify`-tier
- `M unjudged` for any other criterion it left out (a Stop-budget cut)

The Korean form is `contract=ok (turn 등급만; N개는 /gatekit:verify 로 미룸)`
/ `M개 미판정`. With no record, or a record for another contract, the field
is unchanged. The 600-character cap and the stand-down line's early position
hold.

### 4. Evaluator scratch stays under `.gatekit/eval/`

`spec-kit/evaluator-brief.md` tells the evaluator that scratch files (a
driver script, a server log, its own screenshots) go only under
`.gatekit/eval/` in the project, and nothing is written outside the project.
This is prose. It is not enforcement, and no new mechanism is built:

- The `agent` evaluator's Bash runs under the host's hooks. The write gate
  allows targets outside the project root by design (ADR-0018), and
  `read-only` is a spawn-time scope, not a shell sandbox. Enforcing it would
  need a new rule in the Bash gate.
- A Codex evaluator under `--sandbox workspace-write` (ADR-0015) is confined
  by Codex to the workspace plus its default writable temp roots. Codex's
  `sandbox_workspace_write.exclude_slash_tmp` / `exclude_tmpdir_env_var`
  would close those. That is noted here for a later decision and not wired
  in.

## Consequences

- A session started with a bare `/gatekit:build` in a Korean project reports
  in Korean. An English prompt still switches it to English.
- Doctor's axis 3 can be `warn` because of a process outside the project.
  The detail names that process.
- `docs/ARCHITECTURE.md` §3 (prompt), §4 (ledger `lang_source`), §8, §12 and
  §14 (`lang.from_spec`) are updated to match.

## Amendment, 0.16.2 (2026-10-03, owner approval in session)

A review of 0.16.1 found that some of the above did not hold. Each change
below replaces the matching part of the decision.

### A1. The evaluator's scratch directory is writable, and only for it

Decision 4 described the `agent` evaluator only. A CLI evaluator (`jobs
evaluate`, e.g. Codex) runs with `GATEKIT_TASK_ID=evaluate`, and under a task
id rule (b) of the write gate denies every path outside the task's scope and
every path outside the project root. Its scope is `read-only`, so the brief's
own instruction, scratch files under `.gatekit/eval/`, could not be followed:
Write and Bash were both denied there.

Rule (b) now allows `.gatekit/eval/**` inside the project root for the
evaluator only: task id `evaluate` *and* the evaluator's job layout
(`.gatekit/jobs/<job>/evaluate/task.json` with `"id": "evaluate"`), so a plan
task that happens to be called `evaluate` gains nothing. The Write gate,
`apply_patch` and the Bash gate share this path (`write.decide_path`). Every
other path stays denied for the evaluator, including anything outside the
root; every other task id is unchanged. For the `agent` evaluator, which runs
under no task id, the bullet is still an instruction only.

### A2. The spec's language is read from its prose, not its raw head

Decision 1 read the first 40 raw lines. A Korean PRD whose head is mostly an
English metric table and a TypeScript fence read as `en`. `lang.from_spec`
now reads the first 40 *prose* lines (`lang.prose_head`): headings,
paragraphs and list items. A leading YAML frontmatter block, fenced code
blocks, table rows (lines starting with `|`) and inline code spans are
skipped, and at most 1000 raw lines are scanned. An English PRD that names a
Korean product is still `en`. The commands' own `gatekit lang "$(head -40
spec/01-prd.md)"` calls are unchanged.

### A3. A resumed pre-0.16.1 session keeps its language

The prompt hook consults the spec while `lang_source` is not `"prompt"`. A
ledger written before 0.16.1 has no `lang_source` key; loading backfilled it
as `null`, so a resumed session whose language a prompt had set was switched
to the spec's on its next bare prompt. Loading now backfills a missing key as
`"prompt"` when the ledger's `output_lang` is `ko` or it holds a `prompt`
event (before ADR-0026 only a prompt could set the language), and as `null`
otherwise. A present key, `null` included, is left alone.

### A4. The contract field's suffix describes the last run on this tree

Decision 3 compared only `source_sha256`. After edits the suffix described an
older tree's run; `contract=ok (turn tier; …)` read as a passing verdict even
when that run had failed; and a record without `scope` (pre-ADR-0024) was
read as having judged nothing. The suffix is now shown only when
`contract.same_tree_record(root)` holds (same contract, no-tests signatures
and tree fingerprint) and the record has a `scope` list. It names the run and
its scope, never a verdict: `contract=ok (last run: turn tier, N deferred to
/gatekit:verify)` and `last run: M unjudged`, in Korean `contract=ok (마지막
실행: turn 등급만, N개는 /gatekit:verify 로 미룸)` and `M개 미판정`.
`contract=ok` keeps its meaning: the contract matches the approved gate file.

### A5. The port scan reads only the `webServer` value, without comments

Decision 2 read the 2000 characters after each `webServer`, so it reported
ports in comments and in later, unrelated blocks (`use`, `projects`), and it
missed `port: Number(process.env.PORT) || 3000`. Doctor now drops `//` and
`/* */` comments (string literals kept, so a URL's `//` survives), takes the
value after each `webServer:` up to its balanced closing brace or bracket
(strings respected, at most 8000 characters), and reads `port:` and `url:`
there, including the literal fallback after `||` or `??`. It is still a scan,
not a parser: a port set only from a variable is not found.

### Open question: each command appears twice in the slash menu

Every command has a trigger-shim skill, so Claude Code's menu shows both
`/gatekit:build` and `/gatekit:gatekit-build`. Claude Code's skill
frontmatter documents `user-invocable: false`, which hides a skill from the
`/` menu while Claude can still invoke it from its description. Codex's
skill documentation names only `name` and `description` in `SKILL.md` (with
`allow_implicit_invocation` in an optional `agents/openai.yaml`) and does not
say how it treats an unknown key. Under Codex the skills are also the user's
only entry point, since Codex has no slash commands, so hiding them there
would be wrong even if it were possible. The shims are left unchanged until
it is confirmed that Codex ignores the key, or the plugin can ship it for
Claude Code alone.

## Amendment, 0.16.3 (2026-10-03, owner approval in session)

A review of 0.16.2 found the following. Each change below replaces the
matching part of the decision or of the 0.16.2 amendment.

### B1. The port scan finds a `webServer` value that is not an object literal

A5 read a `webServer:` value only when it opened with `{` or `[`, so two
common shapes the 0.16.1 scan had found were missed:
`webServer: process.env.CI ? undefined : { port: 3100 }` and
`const webServer = { port: 3200 }; defineConfig({ webServer })`. The scan now
also matches `webServer = <value>` (not `==`, `===` or `=>`), and when a value
does not open with `{`/`[` it searches the value for the first one: up to a
`,` or `;`, a closing brace, bracket or parenthesis at depth 0, or a line
break at depth 0 that no operator (`?`, `:`, `||`, `&&`, `.` …) joins to the
next line, strings respected, at most 8000 characters. The balanced value is
read from there as before. A `webServer` match inside a value already read is
skipped, so a file of nested matches costs one read per 8000-character
window instead of one per match.

### B2. The contract field computes the tree fingerprint last

A4 called `contract.same_tree_record` first, so every prompt walked the tree
(up to 20 000 files) for the fingerprint, even when no record existed or the
record had judged every criterion. The prompt hook now reads the record
(`contract.load_last`), requires a `scope` list and at least one unjudged
criterion, and only then checks that the record is for this contract and
this tree. What the suffix says is unchanged.

### B3. The built-in evaluator brief names the scratch directory

A1 made `.gatekit/eval/**` writable for the CLI evaluator, but the brief
`jobs evaluate` writes when no `--prompt` is given (`jobs.EVALUATOR_BRIEF`)
still said any attempt to write is a finding. It now names `.gatekit/eval/`
in the project root as the one exception for scratch files and says nothing
is written outside the project, as `spec-kit/evaluator-brief.md` does.

### B4. Frontmatter is recognised after a BOM and only when it closes

A2 skipped frontmatter only when line 0 was exactly `---`, and once opened
skipped everything up to a closing `---`. A file saved with a UTF-8 BOM had
its English frontmatter read as prose, and a file starting with a thematic
break and no closing `---` was skipped whole. `lang.prose_head` now strips a
BOM from line 0 before the check, and treats the block as frontmatter only
when a closing `---` (or `...`) appears within the next 60 lines; otherwise
line 0 is read as a thematic break and the lines after it as usual.

## Amendment, 0.16.4 (2026-10-03, owner approval in session)

A review of 0.16.3 found the following. Each change below replaces the
matching part of the decision or of the earlier amendments.

### C1. The port scan reads typed declarations and quoted keys

B1 matched `webServer:` and `webServer =`, so in
`const webServer: PlaywrightTestConfig['webServer'] = { port: 3800 }` and
`const webServer: { command: string; port: number }[] = [ … ]` the colon of
the type annotation was taken for the key and the type was read as the
value; no port was found. After `const`, `let` or `var` a `webServer:` now
opens a type annotation: the scan skips it to the `=` that ends it (brackets,
braces, parentheses and `<>` nest, so a type literal may hold `;` and span
lines; `=>` belongs to a function type) and reads the value after that `=`
as before. A `;`, `,`, closing bracket or line break at depth 0 before any
`=` means a declaration without a value, and nothing after it is read. A key
in matching quotes (`'webServer':`, `"webServer":`) is recognised. A
`webServer` inside any other string literal (`console.log('webServer: {…}')`)
is not a key: string contents are blanked before matching, and values are
still read from the unblanked text so `url: '…:3000'` keeps its port. A
`'…'` or `"…"` literal ends at a line break (a JavaScript string cannot span
lines; template literals still do), so a lone quote outside a string — in a
regex literal such as `/'/g` or `/it's/` — blanks at most the rest of its
line. An earlier draft let it run to the end of the file, which blanked a
`webServer` key below it and hid its port.


### C2. The built-in brief puts the scratch exception on the write gate only

B3's wording said "the CLI sandbox and the write gate both refuse writes"
and named `.gatekit/eval/` as "the one exception", but only the write gate
has that exception: Codex under `--force-read-only-evaluator`, or another
backend's own sandbox, may refuse even the scratch directory. The built-in
brief now says the write gate refuses every write except scratch under
`.gatekit/eval/`, that the backend's own sandbox may refuse even those, and
that the evaluator then keeps scratch in memory or reports the step it was
for as `unverified`. The scratch bullet of `spec-kit/evaluator-brief.md`
says the same.

### C3. Commands read the spec's language the way the hook does

A2 left the commands' `gatekit lang "$(head -40 spec/01-prd.md)"` calls
unchanged, so `/gatekit:build`, `/gatekit:tasks`, `/gatekit:gate` and
`/gatekit:verify` still read a table-heavy Korean PRD (English frontmatter,
an English feature table) as `en` while the hook read it as `ko`. A new form
`gatekit lang --spec [--root PATH]` prints `lang.spec_lang(root)`, always
with exit 0. It applies the prompt hook's precedence, so the command and the
hook name the same language in the same turn: the `output_lang` of the most
recently updated session ledger when its `lang_source` is `"prompt"` (the
user signalled a language in a prompt; the ledger is read with the same
backfill the hook applies), else `from_spec` (the prose head of
`spec/01-prd.md`, else `spec/00-discovery.md`), else that ledger's
`output_lang`, else `en`. An earlier draft put the spec first, so an English
spec and a user writing Korean gave `ko` from the hook and `en` from the
command. A command does not know its session id, so it reads the newest
ledger: the hook saves the current session's on every prompt, so it is almost
always this session's, but two sessions prompting concurrently in one project
can read the other's. That residual risk is why every command file
(`build`, `tasks`, `gate`, `verify`) first uses the `output_lang=` value of
the context line the hook injected this turn, and runs
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang --spec` only if it is
absent. The language is the only thing read from the newest ledger — scopes
are still resolved by session id alone. The positional form
`gatekit lang <text...>` is unchanged.

### C4. Spec templates name the launcher, and CI checks them

The spec templates (`RECOVERY.md`, `PROGRESS.md`, `01-prd.md`, `04-tasks.md`,
`05-gate.md`, both languages) told the reader to run `python3 -m gatekit …`,
which does not run from a user's project. They now name
`python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" …`, as the commands and the
manual do, and `tools/gate_command_invocations.py` scans
`plugin/spec-kit/templates/**/*.md` as well as commands and policies.

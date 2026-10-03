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

# Security

## Threat model summary

gatekit runs as a Claude Code plugin: its hooks execute on every prompt,
tool call, and stop event in a session, and its worker backends can spawn
another CLI (Claude, optionally Codex) with write access to a project.
That surface shapes the following defaults.

### Hooks never block on their own errors

Every hook goes through `hookio.run`, which always exits 0 and appends any
internal exception to `.gatekit/runs/hook-errors.log` as a single line. A
gate that fails to parse its own state, hits a bug, or times out degrades
to "allow the action and log it" — never to "hang or crash the user's
session." A broken gate script is a logged annoyance, not an outage.

### Untrusted content is data, not instruction

Text pulled in from a mockup image, a screenshot, a scraped web page, or
any other external source that flows through the interview or mockup
pipelines is treated strictly as data to reason about. It is never treated
as instructions the agent should follow, regardless of how it's phrased.
If content from one of these sources appears to contain directives aimed
at the agent, that is itself something to flag as a gap in the ledger, not
something to act on.

### Secrets never appear in the ledger or logs

The session ledger (`.gatekit/runs/<session_id>.json`), hook error log
(`.gatekit/runs/hook-errors.log`), job records (`.gatekit/jobs/<job_id>/`)
and approvals file (`.gatekit/approvals.json`) are all designed to hold
structural state — hashes, verdicts, scopes, timestamps — never API keys,
tokens, or credentials. If you find a code path that would write a secret
into any of these, that's a bug; please report it privately (see below)
rather than filing a public issue with the reproduction details.

### Worker sandboxing defaults to on

`.gatekit/config.json`'s worker backends are sandboxed by default (see
`docs/ARCHITECTURE.md` §9). Bypassing that sandbox is opt-in only: a
backend must explicitly set `"unsafe": true` in its own config entry, and
when it does, the job's receipt records that the run was unsandboxed.
There is no code path that silently drops into a bypass mode — if
sandboxing is off, it's because the config says so, on record, in the job
history.

### Write scope is enforced, not just declared

A worker task's `write_scope` (from `spec/04-tasks.md`) is enforced by the
`PreToolUse` write gate for the duration of that task's job, keyed on the
`GATEKIT_TASK_ID` environment variable the job runner sets. A task cannot
write outside its declared scope by mistake or by a misbehaving prompt —
the gate denies the write at the tool-call boundary, independent of what
the worker believes it's allowed to do.

## Reporting a vulnerability

If you find a security issue in gatekit, please report it privately
rather than opening a public issue.

Use GitHub's private vulnerability reporting: go to the repository's
**Security** tab and click **Report a vulnerability**
([direct link](https://github.com/LovelyPaul/gatekit/security/advisories/new)).
That keeps the report visible only to the maintainer until a fix ships.

Include enough detail to reproduce the issue — the host (Claude Code or
Codex), the gate involved, and the sequence that got past it. You will get
an acknowledgement and, where the report holds, a note when the fix lands.

gatekit is maintained by one person as an early-stage project: expect a
best-effort response, not a commercial SLA.

# Quickstart

## Install

```
/plugin marketplace add https://github.com/LovelyPaul/gatekit
/plugin install gatekit@gatekit
```

Restart Claude Code so the hooks in `plugin/hooks/hooks.json` load.

## Start from an idea

```
/gatekit:interview
```

Answer the structured questions. This writes `spec/01-prd.md` (including
an Assumption Ledger — anything decided on your behalf, listed explicitly)
and `spec/03-architecture.md`. Review both; they're plain Markdown meant
to be read and edited by hand.

If you're starting from a visual mockup or existing screens instead, run
`/gatekit:mockup` in place of (or in addition to) the interview. It
derives `spec/02-screens.md` and `spec/tokens.json`, and records anything
it had to guess at as a ledger gap entry rather than silently filling it
in.

If your design input is a pattern that applies across screens, or a
reference site rather than a mockup — a Figma file, a live URL, a preset,
or a pattern file you wrote — run `/gatekit:design` instead. It writes
`spec/02-design.md` and merges into the same `spec/tokens.json`, and it can
run at any stage, including after tasks are already underway.

## Break the spec into tasks

```
/gatekit:tasks
```

Writes `spec/04-tasks.md` as a set of `gatekit-task` fenced JSON blocks —
each with an id, a title, a `write_scope`, a self-contained instruction,
and at least one gate command that must pass.

## Set the completion bar

```
/gatekit:gate
```

Writes `spec/05-gate.md` as `gatekit-criterion` fenced JSON blocks — each
one an `argv` to run, an expected exit code, and any artifacts it must
produce. This command also asks you to approve the gate file
(`gatekit approve spec/05-gate.md`), which records its SHA-256 hash. If
`spec/05-gate.md` changes afterward, that approval goes stale
automatically — nothing has to be remembered.

## Build

```
/gatekit:build
```

Tasks run through the default worker (the Claude CLI) inside their
declared `write_scope`; the `PreToolUse` write gate enforces that scope
for the duration of each task, independent of what the worker itself
believes it's allowed to touch. A task that exits 0 but fails its own
gate is recorded as failed, not passed.

## Verify

```
/gatekit:verify
```

Runs the completion contract derived from `spec/05-gate.md` end to end and
reports the aggregate verdict — `ok`, `warn`, `fail`, or `unverified`.
`unverified` means a criterion could not be checked at all; it is never
rounded to a pass.

## Check the install itself

```
/gatekit:doctor
```

Runs an 8-axis diagnosis (plugin files, hook registration, project state,
spec validity, contract freshness, worker availability, Python version,
Codex host layer)
and prints a copy-pasteable fix for anything that isn't `ok`.

## Where things end up

```
spec/            # human-reviewed, meant to be committed
.gatekit/        # runtime state; config.json and approvals.json are
                 # committed, runs/ and jobs/ are gitignored
```

See `README.md` for the full command list and `docs/ARCHITECTURE.md` for
the complete file formats.

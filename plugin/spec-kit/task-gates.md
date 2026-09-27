# Writing a task's gates

Read by `/gatekit:tasks` Step 4. Every task in `spec/04-tasks.md` carries
at least one gate; this file says what makes a gate trustworthy, which
runners need glob patterns, and the two gates added by default.

## Step 4 — write gates

Every task carries at least one gate: an argv list, run without a shell, that
fails when the task is not done.

```json
"gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "discover"]}]
```

The gate must be a command that exists in this repository, and you verify it
runs before writing it in. A gate that always passes is worse than no gate: it
manufactures false evidence.

Two runners need glob patterns, not directories: `node --test` loads a bare
directory as a module and fails with `Cannot find module`, so write
`tests/rules/*.test.js`; `gates/tokens.py` scans zero files for a bare
directory and exits 3, so write `src/**`. `jobs start` runs every gate once
before spawning a worker (ADR-0009) and refuses to start when a gate's
command itself errors — write the gate so that, with no code yet, it fails
the way the runner reports "tests failed" (exit 1), not a usage error.

**The token gate.** When `spec/tokens.json` exists, add this gate by default
to every task whose `write_scope` includes a stylesheet, component, or
template path — pass the task's own `write_scope` globs as the gate's
arguments so it scans only what that task writes:

```json
{"name": "tokens", "argv": ["python3", "${CLAUDE_PLUGIN_ROOT}/gatekit/gates/tokens.py", "--lang", "<output_lang>", "<write_scope glob>", "..."]}
```

No `--root` is needed here: `jobs.run_gates` runs every task gate with the
project root as its `cwd`, and `tokens.py --root` defaults to `.`. Running
the same fence by hand from another directory resolves `.` to the wrong
root and reports `unverified` unless you pass `--root` explicitly.

It scans the task's own files for colour literals that are not in
`tokens.json` and exits 0 (`ok`), 1 (`fail`, a literal named), or 3
(`unverified`, `tokens.json` absent or unparsable, or nothing the gate knows
how to scan). Treat exit 3 the same as any other `unverified` result:
never round it to a pass. Do not add it to a task whose write scope has no
such path (e.g. pure backend logic, `"read-only"` tasks) — the ADR keeps the
scan narrow so a `fail` from it stays trustworthy.

**The screenshot criterion (ADR-0017 decision 9).** For any task whose
`write_scope` includes a UI surface — same test as Step 2's "the surface a
user touches" — `/gatekit:gate` (not this command) will derive a completion
criterion requiring `spec/design/build-<task-id>.png` to exist, captured by
a standalone script (`npx playwright test` or whatever E2E runner
`spec/03-architecture.md` names — never an MCP tool call, which only exists
inside an interactive session and cannot be a criterion `argv`). This
command's job is only to make that possible: name the task so `<task-id>`
is stable and unique (it already must be, per Step 3's uniqueness rule),
and do not write anything to `spec/design/` yourselves — the screenshot is
captured once the task's own gates already pass, as evidence for `/gatekit:
verify`'s evaluator to look at later, not a gate this command or the worker
clears itself.


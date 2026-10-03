<!-- Read CONTRIBUTING.md first. 한국어 설명도 괜찮습니다; checklist items stay as they are. -->

## What and why

<!-- What changes, and why. The "why" is the part the diff cannot tell a reviewer. -->

## Linked issue / ADR

<!-- Closes #… · ADR-00NN if this changes the contract -->

## Checklist

- [ ] One logical change. Unrelated edits are left out of this PR.
- [ ] If this changes or extends the contract, an ADR in `docs/decisions/` comes first, and `docs/ARCHITECTURE.md` is updated to match (including §1 for any new top-level file or directory).
- [ ] Tests first: a failing test was written before the fix or feature (for a bug, a test that reproduces it).
- [ ] Standard library only. No new dependency in `plugin/` or `tools/`.
- [ ] Gates stay in hooks; no enforcement was moved into command or skill prose.
- [ ] Clean-room: no code copied from another project.
- [ ] No absolute personal paths, no file over 1 MB.
- [ ] If a command, subcommand or spec file was renamed, `docs/manual/` and both READMEs follow in this PR.

## Test and gate output

<!-- Paste the summary lines. Every gate must pass. -->

```text
$ python3 tools/run_tests.py

$ for g in tools/gate_*.py; do python3 "$g" || echo "FAILED: $g"; done

```

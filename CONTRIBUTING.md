# Contributing to gatekit

## Ground rules

- **Standard library only.** No `pip install`, no `npm`, anywhere in
  `plugin/` or `tools/`. If a change seems to need a third-party
  dependency, stop and write an ADR under `docs/decisions/` explaining why
  before writing code.
- **`docs/ARCHITECTURE.md` is the contract.** It is the single source of
  truth for module boundaries, file formats, and vocabulary. Read it
  before touching anything under `plugin/`. If your change needs the
  architecture to say something different than it currently does, update
  `ARCHITECTURE.md` first (with an ADR), then write the code to match.
- **TDD.** Write the failing test first, then the minimum implementation
  that makes it pass, then refactor. For a bug fix, the first commit-sized
  step is a test that reproduces the bug.
- **Clean-room.** Don't copy code from other projects into this one.
  Patterns (hook-enforced gates, hash-anchored approvals, and so on) are
  fair game; code is not.

## Running the tests and gates

```bash
# plugin's own unit tests
python3 -m unittest discover -s plugin/tests -v

# CI gate self-tests (fault-injection tests for tools/gate_*.py)
python3 tools/test_tools.py -v

# both of the above, with a one-line summary
python3 tools/run_tests.py

# each CI gate individually
python3 tools/gate_no_abs_paths.py
python3 tools/gate_skill_size.py
python3 tools/gate_blob_size.py
python3 tools/gate_forbidden_phrases.py
python3 tools/gate_manifest.py
python3 tools/gate_readme_sync.py
python3 tools/gate_command_invocations.py
python3 tools/gate_manual_accuracy.py
python3 tools/gate_clean_room.py
```

Every gate accepts `--root PATH` (defaults to the repo root, computed from
the gate script's own location) and `--json` for machine-readable output.
Exit code 0 means pass, 1 means at least one finding.

`.github/workflows/ci.yml` runs all of the above on Python 3.9 and 3.12 on
every push and pull request. A change that doesn't pass locally won't pass
in CI either — there's no network dependency to explain a difference.

## The ADR process

Architectural decisions that change or extend the contract in
`docs/ARCHITECTURE.md` get a short ADR in `docs/decisions/` before the
implementation, using the existing files there as the template:
Context, Decision, Consequences. An ADR is not a design doc — a few
paragraphs per section is normal. Once written, `ARCHITECTURE.md` itself
is updated to match, and only then does the code follow.

## Commit style

- One logical unit per commit. If a review comment says "this is really
  two changes," it probably is.
- The message says what changed and why — "why" is the part a diff can't
  tell you on its own.
- Run the tests and gates before committing, not after. A commit that
  breaks `tools/run_tests.py` or any `tools/gate_*.py` should not exist,
  even transiently.
- Don't push without the repo owner's instruction.

## Where things live

See `docs/ARCHITECTURE.md` §1 for the full repository layout. Two rules
worth restating here because they're easy to violate by accident:

- `SKILL.md` files are ≤ 40-line trigger shims that point at the matching
  command in `plugin/commands/`. Execution instructions belong in the
  command file, not the skill.
- Templates, heading maps, and presets are data files under
  `plugin/spec-kit/`, never embedded as prose inside a prompt.

`tools/gate_skill_size.py` and `tools/gate_forbidden_phrases.py` enforce
both of these in CI.

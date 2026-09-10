# gatekit — operating rules for agents working in this repo

- `docs/ARCHITECTURE.md` is the contract. Read it before editing anything under `plugin/`.
  Deviations require an ADR in `docs/decisions/` first.
- Standard library only. No `pip install`, no `npm`. If you think you need a dependency, stop and write an ADR.
- Gates live in hooks (`plugin/hooks/hooks.json` + `plugin/gatekit/gates/`). Prose in commands or skills is never an enforcement mechanism.
- Every hook exits 0 on internal error. Test that property.
- Verdict words: `ok / warn / fail / unverified`. Never round `unverified` to either side.
- `SKILL.md` files are ≤ 40-line trigger shims. Execution instructions live in `plugin/commands/*.md`.
- Templates, heading maps, presets: data files under `plugin/spec-kit/`, not prompt prose.
- No absolute personal paths. No files > 1 MB. CI enforces both.
- Output language follows the detected `output_lang`; never default to Korean.
- TDD: write the failing test first, then the minimum implementation. Run `python3 -m unittest discover -s plugin/tests` before claiming anything.
- Commits: one logical unit each, message states what and why. Do not push without the owner's instruction.
- Clean-room rule: do not copy code from other projects. Patterns are fine; code is not.

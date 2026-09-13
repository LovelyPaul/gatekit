# Design presets

A preset is one JSON file, `<name>.json`, in this directory. It holds exactly
what a project's `spec/tokens.json` holds at version 2: open token groups plus
`patterns`. `gatekit design merge-preset <name>` merges it into the project's
`spec/tokens.json`.

No preset ships with the plugin. This directory holds this README and nothing
else until one has been observed in a real build.

## Shape

```json
{
  "version": 2,
  "patterns": [
    {"id": "P1", "rule": "Destructive actions sit behind a confirm.", "applies_to": "all"}
  ],
  "color": {"primary": "#3366ff", "danger": "#cc2222"},
  "space": {"sm": "8px", "md": "16px"},
  "radius": {"md": "8px"}
}
```

Groups are open. Any top-level key mapping to an object of tokens is a group,
so `radius`, `shadow`, `breakpoint` and `motion` need no code change. Two
top-level keys are reserved and are not groups: `source` (a list) and
`patterns` (a list of rows with `id`, `rule`, `applies_to`, `evidence`).

A token value may be a string (`"#3366ff"`) or an object
(`{"value": "#3366ff", "evidence": "..."}`). Writing the string form in a
preset is enough; the merge fills in the evidence.

## What merging does

Merging never overwrites. Project values win, the preset fills gaps only:

- A token the project already defines is left exactly as it is, string or object.
- A token the preset adds is written as `{"value": <the preset's value>,
  "evidence": "preset:<name>"}`. A scalar in the preset is upgraded to that
  object form, so every token can say where it came from. An object in the
  preset keeps its `value` but gets `evidence: "preset:<name>"`, because for
  this project the preset *is* the origin.
- A pattern whose `id` the project already uses is skipped. A pattern the
  preset adds gets `"evidence": "preset:<name>"`.
- `source` gains `"preset:<name>"` once, however many times the merge runs.
- A version 1 file is upgraded to version 2 in place: its `source` string
  becomes a one-item list and `patterns` starts empty.

The result is that `spec/tokens.json` always distinguishes "from this
project's sources" from "from a preset", which is what the design report and
the assumption ledger rely on.

## Committing a new preset

A preset must be **observed in a real build before it is committed** — the same
rule ADR-0006 applies to host parity claims. Write it, merge it into a real
project, run the build, and only then add the file here. A preset that has
never produced a passing build is a guess with a filename.

# Policy: running a gatekit command under Codex (or any host without slash commands)

Read by every `skills/gatekit-*/SKILL.md` shim when the host is not Claude
Code (ADR-0019). Claude Code runs `/gatekit:<name>` directly and never needs
this file.

## Finding and running the command

- The command is `commands/<name>.md` in this plugin. The plugin directory
  is two levels above the skill's own folder
  (`<plugin>/skills/gatekit-<name>/SKILL.md` → `<plugin>/commands/<name>.md`).
  Read that file and follow it as the instruction for this turn.
- Everywhere the command text says `${CLAUDE_PLUGIN_ROOT}`, use that plugin
  directory as an absolute path. Codex does not substitute it in skill or
  command text, and the shell your commands run in does not set it. Example:
  `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate --json`
  becomes `python3 "/abs/path/to/plugin/bin/gatekit.py" spec validate --json`.
- `$ARGUMENTS` in the command text is the user's own words from the message
  that invoked the skill, unparaphrased; empty when they gave none.
- Commands are invoked as `$gatekit-<name>` (plugin skills may show as
  `gatekit:gatekit-<name>`), not `/gatekit:<name>`. Where a command tells the
  user to run another command next, name it that way.

## Differences from Claude Code

- Where the command says `AskUserQuestion`, ask the same options as a
  numbered list in plain chat and wait for the answer; Codex has no such tool.
  **A bare number in reply is the normal path**, so it never changes the
  output language — keep replying in the language the conversation started in.
- Where the command says to run `WebSearch`, use whatever web search this
  session has. **If it has none, say so and ask whether to skip that step or
  have the user paste findings** — never route around it by spawning a
  subagent to "research" from memory.
- Where the command says to spawn an `Agent` with a ```gatekit-scope fence,
  keep the fence in the prompt you give the subagent.
- Build workers and CLI evaluators are other agent CLIs (`claude`, `codex`)
  that need the user's login and network. Inside the Codex sandbox they fail
  with "Not logged in". Run `workers check <name> --probe` first, and run
  `jobs start`, `jobs redelegate` and `jobs evaluate` with escalated
  permissions when Codex asks; say so to the user before doing it.

## The gates only run once the user trusts them

Installing the plugin does not enable its hooks: Codex skips plugin hooks
until the user reviews and trusts them. The desktop app cannot record that
trust today; a terminal session can. If
`python3 "<plugin>/bin/gatekit.py" doctor` reports the plugin's hooks as
untrusted, tell the user plainly — the write, bash and stop gates are not
running — and give the fix: open a terminal, run `codex`, type `/hooks`,
review and trust the gatekit hooks, then start a new session. Trust is per
hook content, so it is needed again after each gatekit upgrade.

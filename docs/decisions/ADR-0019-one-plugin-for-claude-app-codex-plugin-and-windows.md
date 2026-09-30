# ADR-0019: One plugin tree for the Claude app, Codex's plugin system, and Windows

Status: accepted 2026-09-30 (owner approval in session: "응, 그대로 진행해줘";
Windows kept in the same repository and release, not a separate folder).

## Context

Study participants use three surfaces the plugin was not packaged for:

1. **The Claude desktop app.** It supports plugins (`+ → Plugins → Add
   plugin`), runs plugin hooks as the CLI does, and shares user-scope
   installs with the CLI (`code.claude.com/docs/en/desktop.md`,
   `…/plugins/install.md`). A participant who instead *opened the gatekit
   folder* as the app's project saw the commands "work" — the model read the
   command files as prose — while no hook was registered, so no gate ran.
   Nothing in the code is wrong here; the install path is undocumented.

2. **Codex's plugin system.** Codex now installs plugins from a marketplace
   and accepts Claude-format manifests. Observed on this machine with Codex
   CLI 0.157.1: `codex plugin marketplace add <gatekit repo>` read
   `.claude-plugin/marketplace.json`, `codex plugin add gatekit@gatekit`
   installed `plugin/` into `~/.codex/plugins/cache/gatekit/gatekit/0.11.3`,
   and a `codex exec` session listed all ten skills as
   `gatekit:gatekit-<name>`. Two things then break:
   - every `SKILL.md` shim says "invoke `/gatekit:<name>`", and Codex has no
     slash commands; the command bodies also say
     `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py"`, which Codex does not
     substitute in skill text;
   - `plugin/hooks/hooks.json` has no `--host codex` and no Codex tool
     names (`apply_patch`, `collaborationspawn_agent`), so the Stop gate
     would answer in Claude's dialect and file edits would pass ungated.
   Codex documents that plugin hooks receive `PLUGIN_ROOT` / `PLUGIN_DATA`
   (plus legacy `CLAUDE_PLUGIN_ROOT`) and that installing a plugin does not
   trust its hooks: the user must review and trust them. The desktop app
   cannot currently record that trust (openai/codex#47283, open); the
   terminal `codex` → `/hooks` can, and the trust is shared through
   `~/.codex/config.toml`.

3. **Windows.** Every hook is `python3 "…"`; on Windows `python3` is
   usually absent or the Microsoft Store stub. Claude Code runs hook commands
   through Git Bash (PowerShell without Git for Windows); Codex through CMD.
   Hook stdio uses the locale encoding (cp949 on Korean Windows), so Korean
   prompts garble. Criteria and task gates run `npm`/`npx` without a shell,
   which cannot find `npm.cmd`. `jobs.py` uses `os.kill(pid, 0)` as a liveness
   probe — on Windows that call **terminates** the process — plus
   `signal.SIGKILL` and `ps`, neither of which exist there. Git Bash reports
   paths as `/c/Users/…` while the project root is `C:\Users\…`. CI runs
   only on Ubuntu.

The standing constraints apply: one plugin, stdlib only, hooks are the
enforcement, every hook exits 0 on internal error, the verdict words.

## Decision

1. **Claude app: documentation only.** README (en/ko) and the manual gain an
   install path for the desktop app, and say plainly that opening the
   gatekit folder itself is not an install and runs no gate.

2. **`plugin/` is also a Codex plugin; no second tree.**
   a. `plugin/hooks/hooks.json` matchers add the Codex tool names
      (`apply_patch` on the write gate, `collaborationspawn_agent` on the
      spawn gate). A tool name that does not exist in a host never matches.
   b. `hookio.host_from_argv` keeps `--host` authoritative; with no flag it
      reads the environment: `PLUGIN_ROOT` set (Codex's plugin-hook
      variable, which Claude Code does not set) means `codex`, otherwise
      `claude`.
   c. `SKILL.md` shims become host-neutral: under Claude Code invoke
      `/gatekit:<name>`; under any other host read
      `commands/<name>.md` two directories above the skill's own folder, and
      treat `${CLAUDE_PLUGIN_ROOT}` in it as that plugin directory. Codex's
      own differences (no `AskUserQuestion`, `$gatekit-…` names) move from
      the generated host layer into one shared file,
      `plugin/policy/codex.md`, that the shim points to. Each shim stays
      ≤ 40 lines.
   d. `doctor` reports whether Codex has recorded hook trust for the
      installed plugin's `hooks.json`, and prints the terminal fix
      (`codex` → `/hooks`) when it has not. It never writes trust itself:
      that review belongs to the user.
   e. `gatekit install --host codex` stays for projects already using it;
      the README recommends the plugin install.

3. **Windows in the same repository, release and version.**
   a. Every hook command tries interpreters in order:
      `python3 "…" || python "…" || py -3 "…"`. The form is valid in bash,
      sh and CMD; a gate always exits 0, so the chain only advances when an
      interpreter is missing.
   b. `hookio` reads stdin and writes stdout as UTF-8 regardless of locale.
   c. `paths.expand_argv` also resolves `argv[0]` through `shutil.which`
      when it is a bare name, so `npm`/`npx` find `npm.cmd`/`npx.cmd`
      (`PATHEXT`); an unresolvable name is passed through unchanged, and
      the existing "could not run" handling still reports it.
   d. `jobs.py` process control branches on `os.name == "nt"`: liveness and
      age through `tasklist`, termination through `taskkill /T /F`. The
      POSIX path is unchanged.
   e. The Bash gate normalises MSYS paths (`/c/Users/x` → `C:\Users\x`)
      before comparing a target with the project root.
   f. CI adds `windows-latest`. Windows support is labelled **preview**
      in README and release notes until a participant has run a real
      session on Windows; CI proves the Python code, not that the host
      calls the hooks.

## Consequences

- One marketplace (`LovelyPaul/gatekit`) and one version serve Claude CLI,
  Claude app, Codex CLI and the Codex app, on macOS, Linux and Windows.
- Under Codex, gates run only after the user trusts the plugin's hooks in a
  terminal `codex` session, and again after each upgrade (trust is per
  content hash). `doctor` makes that state visible instead of silent.
- Hook commands get longer and less readable; the order and the reason are
  pinned by a test.
- Not verified by this ADR: Claude Code's and Codex's actual hook
  invocation on Windows (docs do not say whether a missing interpreter is
  reported), and the Codex desktop app's hook behaviour beyond the trust
  issue. Both are marked as open in the release notes.

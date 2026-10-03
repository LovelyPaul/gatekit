# ADR-0029: A compatibility layer for the rename to gatebound

Status: accepted 2026-10-04 (owner approval in session).

## Context

gatekit will be renamed **gatebound** once the current study cohort ends
(about a month from now); the repository already lives at
github.com/gatebound/gatebound. A rename that only changes strings would break
every project that already uses gatekit, because the name is part of several
on-disk and user contracts:

1. **Fences.** `spec/04-tasks.md` and `spec/05-gate.md` hold
   ```` ```gatekit-task ```` / ```` ```gatekit-criterion ```` fences, and
   `approvals.json` and `contract.json` pin the hash of `05-gate.md`
   (ADR-0023). Rewriting a user's fences voids their approval, so the old
   prefix must stay readable forever and nothing may ever rewrite `spec/`.
2. **State directory.** `.gatekit/` holds approvals, the contract, ledgers,
   jobs and attempts, and is partly committed.
3. **argv paths.** Real projects carry criteria and task gates such as
   `["python3", "${CLAUDE_PLUGIN_ROOT}/gatekit/gates/tokens.py", ...]`,
   `${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py`, and absolute paths into an old
   checkout or plugin cache (`<home>/Projects/gatekit/plugin/gatekit/gates/tokens.py`).
   After the rename the package directory is `gatebound/`, so every one of
   them would name a file that no longer exists.
4. **Environment.** Workers get `GATEKIT_TASK_ID` / `GATEKIT_JOB_ID`, and jobs
   strip every inherited `GATEKIT_*` variable.
5. **Matching.** The prompt hook arms the Stop gate on `/gatekit:build`
   (and Codex `$gatekit-build`); the Bash gate refuses `gatekit.py approve`
   inside a worker. A renamed launcher that is not recognised means the Stop
   gate silently never arms, or a worker can approve.
6. **Managed text.** `AGENTS.md` carries `<!-- gatekit:begin … -->` /
   `<!-- gatekit:end -->`; Codex caches the plugin under
   `plugins/cache/gatekit/gatekit`; Claude Code keys it `gatekit@gatekit`.
7. **Coexistence.** For a while a user can have both the old 0.16.x gatekit
   plugin and the new gatebound plugin enabled. Two Stop gates would judge the
   same contract twice and two question gates would count every question twice.
   The old plugin cannot be changed after the fact.

## Decision

This release ships **only the compatibility layer**, under the current name.
Everything user-facing still says gatekit; templates still write `gatekit-*`
fences; a new project still gets `.gatekit/`. The rename itself is a later
change that flips one constant.

### `names.py` is the single source of truth

`plugin/gatekit/names.py` holds `CURRENT = "gatekit"`, `FUTURE = "gatebound"`
and `LEGACY = ()`; `ALL` is every name, newest first. Every place the name is a
contract asks it: fence aliases, state directory names, launcher names, the
command and skill patterns, env variable names, `AGENTS.md` markers, plugin
keys. The rename sets `CURRENT = "gatebound"` and `LEGACY = ("gatekit",)`.

### Compatibility table

| Contract | Read | Written now | Removal |
|---|---|---|---|
| Fences `<name>-task/criterion/budget/discovery/scope` | either prefix, everywhere a fence is read (`spec`, `contract`, `jobs`, `design`, the spawn gate) | `gatekit-*` | **permanent** — approved specs are hash-pinned |
| State directory | `.gatebound/` if present, else `.gatekit/` if present, else the current name | the resolved one; a new project gets `.<CURRENT>/` | `.gatekit` read-through removed in **1.0** |
| Both state directories | hooks use the one holding `approvals.json`, else one holding other gatekit-written state (`contract.json`, `runs/`, `jobs/`, `attempts.json`, `baseline.json`), else the current name — never one that holds only the user's `config.json`/`eval/`, so a session cannot move the hooks off their ledgers; doctor axis 3 **fail** | — | — |
| Protected state (ADR-0027), write allowlist, evaluator scratch, opaque-text mentions | `.gatekit/` and `.gatebound/` alike (`config.json`, `eval/**` the user's under both) | — | with the read-through |
| argv `…/<name>/gates/<gate>.py`, `…/bin/<name>.py` that does not exist | mapped to this plugin's file at run time (`paths.expand_argv`) | — | **permanent** |
| Env `GATEKIT_TASK_ID`, `GATEKIT_JOB_ID` | current name first, then the other | both names; every inherited `GATEKIT_*` and `GATEBOUND_*` stripped | alias removed in **1.0** |
| Approve guard (ADR-0023) | `gatekit.py`, `gatekit`, `gatebound.py`, `gatebound` | — | **permanent** |
| Prompt arming | `/gatekit:<cmd>`, `/gatebound:<cmd>`, `$gatekit-<cmd>`, `$gatebound-<cmd>` | — | **permanent** |
| `AGENTS.md` block | either marker pair is replaced | current markers | permanent |
| Doctor | both plugins enabled (Claude settings, `installed_plugins.json`) or both in the Codex cache → axis 2 **fail** | — | — |

Permanent rows cost nothing at run time and protect artefacts users cannot
regenerate without re-approval; the read-through and env alias are migration
aids with a date.

### argv aliases are run-time only

`paths.expand_argv` rewrites a whole token whose path does not exist and whose
tail (with `\` read as `/`) is `<any name>/gates/<gate>.py` — `<gate>` being a
file that exists in this plugin's `gates/` — or `bin/<any name>.py`, to this
plugin's own file. It is applied after `${CLAUDE_PLUGIN_ROOT}` expansion, so it
also repairs absolute paths into a deleted checkout or cache. A path that
exists is never touched. `runcheck.grading_files` does not use it, so the
grading hashes pinned at approval (ADR-0023) and the `contract.json` source
hash are unchanged.

### `migrate`

`gatekit migrate [--root P] [--to NAME] [--apply] [--json]` is dry-run by
default. With `--apply` it renames the state directory to `.<NAME>/`
(`git mv` when anything under it is tracked), rewrites `.gitignore` lines that
name the old directory, and regenerates the Codex layer when
`.codex/hooks.json` or a managed `AGENTS.md` block is present. It never reads
or writes `spec/`, is a no-op when the directory already has the target name,
and refuses (exit 1) when both directories exist. `--to` defaults to
`CURRENT`, so until the rename it does nothing; `--to gatebound` rehearses.

### Coexistence: the newer plugin stands down

The old plugin cannot learn about the new one, so the new one yields: when a
plugin named in `LEGACY` is enabled in Claude Code (user settings under
`$CLAUDE_CONFIG_DIR` or `~/.claude`; a project's `.claude/settings.json` and
`.claude/settings.local.json` `enabledPlugins` can only switch it off — see
the amendment below), is listed in `installed_plugins.json`, has its plugin
cache directory, **and** the project's state directory carries that
legacy name, this plugin's **Stop** and **question** gates stand down and the
prompt hook adds a one-line warning once per session. The last condition
matters: an old plugin reads only `.gatekit/`, so in a project migrated to
`.gatebound/` it already stands down by itself, and this plugin must keep
judging or nothing would. The write, Bash and spawn gates keep running — two denies of the
same write are the same deny. With `LEGACY` empty (today) the check returns
before reading any file. ~/.claude is only ever read.

## Consequences

- Existing gatekit users see no change: same fences, same `.gatekit/`, same
  messages. Doctor gains two failure cases that cannot occur today unless a
  user creates `.gatebound/` or installs a gatebound build by hand.
- The rename becomes a mechanical change: flip `names.py`, rename the package
  and launcher, update prose and templates.
- After the rename, a project that still has `.gatekit/` keeps working until
  1.0; `migrate --apply` moves it.
- Out of scope here: the rename itself, any CHANGELOG or version change.

## Amendment (2026-10-04): a forged state directory is never read

Review finding, confirmed end to end: with restrictions off the PowerShell
gate allowed `New-Item -ItemType SymbolicLink -Path .gatebound -Target X`,
`New-Item -ItemType Junction -Path .gatebound -Value X` and
`Rename-Item X -NewName .gatebound` (the Bash forms `ln -s`, `mv` were already
denied by the copy rule). With a real `.gatekit/` and a `.gatebound` pointing
at a directory the session filled with its own `approvals.json`, both ranked
0 and the tie went to the newest name, so `paths.state_dir` returned the
forged one. Four layers, each sufficient for the reported forms:

1. **The PowerShell reader records renames and links as copies**
   (ADR-0028): `Rename-Item`/`ren` is a move (source removed, copied to the
   new name, like `Move-Item`), and `New-Item -ItemType
   SymbolicLink|Junction|HardLink` is a copy of its target to the created
   path, so `bash._copy_hit` judges both as it judges `mv` and `ln -s`.
2. **A state directory name is gatekit's to create.** Any write, link,
   rename or copy target whose final segment is a state directory name
   (`write.state_dir_name`: case-insensitive, after the Windows
   canonicalisation) is protected in the Bash, PowerShell and Write gates,
   before and after approval. Two forms stay allowed: a plain `mkdir` /
   `New-Item -ItemType Directory` of the **current** name while its parent
   holds no other state directory (harmless — an empty directory — and what
   `/gatekit:setup` creates anyway, in-process through `config.save`; no
   command or doc asks the model to run it), and a copy into an **existing**
   state directory, which the copy rule judges as before (`cp config.json
   .gatekit/`). A copy, move or link whose destination is a state directory
   name that does not exist yet becomes that directory, so it is denied
   whatever the source is called (`mv eval .gatebound`). `install -d` is
   read as creating its operands.
3. **`resolve_state_dir` ignores links and prefers the current name.** A
   candidate that is a symlink, junction or other reparse point
   (`st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT` on Windows,
   `os.path.isjunction` on 3.12+), or whose realpath is not directly in the
   project root's realpath, is not a candidate: a project whose only state
   directory is a link resolves to `.<CURRENT>/`. Among candidates of equal
   rank the **current** name wins (`.gatekit/` today, `.gatebound/` after the
   rename), then the newest. So with both holding `approvals.json`, the
   hooks read `.<CURRENT>/`.
4. **Two approvals files: the Stop gate judges neither.** When both state
   directories (links included) hold `approvals.json`
   (`names.approvals_in_several`), the Stop gate in `build`/`verify` records
   `unverified` and blocks with a reason naming `/gatekit:doctor` and
   `gatekit migrate`, under the usual `block_count` (at most `MAX_BLOCKS`)
   and `stop_hook_active` limits, so it never traps the session. An archive
   extracted at the root (`Expand-Archive x.zip .`, `tar -xf`, a documented
   trust boundary of ADR-0027/0028) can still lay down a second state
   directory; this is what makes that fail closed.

Doctor axis 3 is unchanged: both names present is still `fail`.

## Amendment (2026-10-04): the stand-down is the user's choice, taken once

Review finding (plausible once `LEGACY` is set): `legacy_plugin_enabled`
read the project's `.claude/settings.local.json`, which the session can
write, and the Stop and question gates re-read it at every call — so after
the rename a model could write `{"enabledPlugins": {"gatekit@gatekit": true}}`
there and make this plugin's Stop and question gates stand down.

1. **Only the user's settings enable it.** `enabledPlugins` true counts only
   in the user's `settings.json` (`$CLAUDE_CONFIG_DIR`, else `~/.claude`).
   A project settings file can still switch the legacy plugin **off** —
   that only makes this plugin judge, and matches Claude Code, where the
   old plugin then does not run either.
2. **The plugin must really be there.** Besides `installed_plugins.json`,
   its cache directory `<config>/plugins/cache/<marketplace>/<name>`
   (`names.plugin_cache_dir`) must exist.
3. **A snapshot per session.** The prompt hook stores the answer once, at
   the session's first prompt, in the ledger's `legacy_plugins` (protected
   state, ADR-0027). The Stop and question gates read only that snapshot,
   never the settings; with no snapshot yet (`null`) they judge. A settings
   file written mid-session changes nothing until a new session.

Anything that can write the user's own Claude Code settings can disable this
plugin outright, so the user scope is the user's trust domain, not a
boundary gatekit enforces.

### Checklist for the rename itself

Values computed at import from `names.py` follow the flip without edits
(`paths.STATE_DIRNAME`/`ROOT_MARKERS`, `hosts.BLOCK_BEGIN`,
`write.SPEC_ALLOWLIST`/`EVAL_SCRATCHES`, the Bash and prompt patterns). These
still spell the old name and must change with it: the package directory and
`bin/gatekit.py`, `approval.WORKER_ENV`, the `gatekit-` skill directory prefix
in `hosts.install` (old skill directories are then left beside the new ones
and should be removed), `/gatekit:` in `hookio`'s Codex rewrite, template
fences, and every user-facing message.

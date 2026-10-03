# ADR-0028: The PowerShell tool meets the same gate as Bash

Status: accepted 2026-10-04 (owner approval in session). Extends ADR-0004 (the
Bash write gate), ADR-0023 (a worker never approves) and ADR-0027 (protected
state) to Claude Code's `PowerShell` tool.

Origin: the idea comes from a study member's Windows fork,
github.com/yeoul9703/gatekit-cc-windows, which gated the PowerShell tool in
its own tree. Only the idea is taken; the reader here is written from this
repository's own modules (clean-room rule).

## Context

Claude Code has a `PowerShell` tool besides `Bash`. Per the official
documentation (code.claude.com/docs/en/hooks, "PreToolUse input → PowerShell";
code.claude.com/docs/en/tools-reference, "PowerShell tool"):

- its hook `tool_name` is `PowerShell`, and its `tool_input` has the Bash
  tool's fields — the command string in `tool_input.command`, plus
  `description`, `timeout`, `run_in_background`;
- on Windows it is on by default with Git Bash installed (claude.ai and
  Console accounts), always on without Git Bash — where Claude Code does not
  register the Bash tool at all — and opt-in elsewhere through
  `CLAUDE_CODE_USE_POWERSHELL_TOOL=1`; where it is on, "Claude treats
  PowerShell as the primary shell";
- the docs say to "match `Bash|PowerShell` in hooks that inspect shell
  commands": "a hook that matches only `Bash` never fires there".

gatekit registered PreToolUse `Bash` only. Reproduced on 0.16.5 (a temporary
project with `.gatekit/`, `spec/05-gate.md` unapproved):

```
$ printf '{"cwd":"<proj>","tool_name":"PowerShell","tool_input":{"command":"echo x > src/app.ts"}}' \
    | python3 plugin/gatekit/gates/bash.py; echo "exit=$?"
exit=0                       # nothing printed: allowed (the gate only reads tool_name "Bash")
$ grep -c PowerShell plugin/hooks/hooks.json
0                            # and no hook is registered for the tool anyway
```

The same holds for `Set-Content -Path .gatekit\approvals.json -Value x`
(ADR-0027's protected state), for a write outside a worker's `write_scope`,
and for `python …\bin\gatekit.py approve spec/05-gate.md` run by a worker.
Even routed to the Bash gate, PowerShell text is misread: `Set-Content` is a
program "invoked by name" to the Bash reader, so it would be allowed. On a
Windows session every rule ADR-0004, ADR-0023 and ADR-0027 enforce for the
shell was therefore a convention.

## Decision

1. **`gates/powershell.py`, registered as PreToolUse `PowerShell`.** A
   separate `hooks.json` entry beside `Bash`, so each gate reads one tool's
   syntax. The Codex host layer (`hosts.py`) is unchanged: Codex reports every
   shell call as `Bash` and has no `PowerShell` tool name.
2. **One decision, two readers.** A new module, `gatekit/pwsh.py`, reads
   PowerShell text statically into the same `bash.WriteTargets` record the
   Bash reader fills (targets, removed paths, copies, links, rewritten
   subtrees, working directories, variable paths and assignments, opaque +
   why). The gate then runs exactly the Bash gate's sequence on it:
   worker-approve refusal (ADR-0023) → `bash.protected_hit` (ADR-0027, always,
   also after approval) → nothing more while `write.restrictions_active` is
   false → `write.decide_path` per target (spec-before-code allowlist, task
   `write_scope`, the evaluator's `.gatekit/eval/**`) → `opaque` denial. A
   PowerShell redirect, a Bash redirect and a Write call get the same verdict
   for the same path. `bash.py` and `write.py` are not changed.
3. **What the reader understands.** Statements split at newlines, `;`, `&&`,
   `||`, `|` (the element after a pipe is "piped") and a trailing `&`; quoting
   (`'literal'` with `''`, `"expandable"` with backtick escapes and `""`,
   here-strings `@'…'@` and `@"…"@`), backtick escapes and line continuation,
   `#` and `<# #>` comments; redirections `>`, `>>`, `N>`, `N>>`, `*>`, `*>>`
   (`N>&1` merges and `$null` are not writes). Cmdlet and parameter names are
   case-insensitive, module-qualified names (`Microsoft.PowerShell.Management\Remove-Item`)
   and the default aliases are resolved, and a parameter may be any unique
   prefix (`-Pa` for `-Path`) or carry its value after a colon (`-Path:x`).
   Write cmdlets: `Set-Content`/`sc`, `Add-Content`/`ac`, `Clear-Content`/`clc`,
   `Out-File`, `Tee-Object`/`tee -FilePath`, `New-Item`/`ni`/`mkdir`/`md`
   (with `-Name`, and links: `-ItemType SymbolicLink|HardLink|Junction -Target|-Value`),
   `Copy-Item`/`copy`/`cp`/`cpi`, `Move-Item`/`move`/`mv`/`mi`,
   `Remove-Item`/`rm`/`del`/`erase`/`ri`/`rd`/`rmdir`, `Rename-Item`/`ren`/`rni`,
   `Set-Item`, `Clear-Item`, the `*-ItemProperty` and `Set-Acl` cmdlets,
   every `Export-*` cmdlet but `Export-ModuleMember`, `Start-Transcript`,
   `Compress-Archive`/`Expand-Archive`, `Invoke-WebRequest`/`Invoke-RestMethod
   -OutFile`, `Start-Process -RedirectStandardOutput|-RedirectStandardError`,
   `[IO.File]`/`[IO.Directory]` static write methods (`WriteAllText`,
   `AppendAllText`, `WriteAllBytes`, `Copy`, `Move`, `Delete`,
   `CreateDirectory`, …) with literal arguments. Paths are bound from named
   and positional parameters (comma lists included), resolved against the
   working directory, which `Set-Location`/`cd`/`sl`/`chdir`,
   `Push-Location`/`pushd` and `Pop-Location`/`popd` (a stack) track;
   `$PWD` and `~` resolve. Non-file provider paths (`Env:`, `Variable:`,
   `Function:`, `Alias:`, `HKLM:`/`HKCU:`, `Cert:`) are not file writes;
   `FileSystem::` prefixes are removed.
4. **Windows paths.** Backslashes, drive letters, `\\?\` and `\\.\` prefixes
   (`\\?\UNC\server\share` as `//server/share`), and — through
   `write._canonical`, the function the Write gate uses — NTFS stream
   suffixes (`::$DATA`) and trailing dots and spaces. Protected-state matching
   stays case-insensitive (`write.protected_state`); an 8.3 short name of a
   `.gatekit` directory (`GATEKI~1`) in a command's text counts as naming it.
5. **Programs.** Native commands and the PowerShell aliases that are also
   POSIX programs on Linux (`cp`, `mv`, `rm`, `rmdir`, `mkdir`, `tee`,
   `curl`, `wget`) are also handed — as an argument vector — to the Bash
   reader's own analysis of one simple command, so `git`, `tar`, `sed -i`,
   `python -c`, `node -e`, an interpreter fed through a pipe
   (`'code' | python`), `bash -c '…'` and `curl -o` classify as in Bash
   (`py` is read as `python`). `pwsh`/`powershell -Command '…'` (or a
   positional command string) and `Invoke-Expression`/`iex` with a literal
   string are parsed recursively; `-EncodedCommand` is decoded and parsed and
   is opaque as well. Script blocks `{…}` and sub-expressions `(…)`, `$(…)`,
   `@(…)` — also inside double-quoted strings — are read as code wherever they
   appear, since they may run.
6. **Opaque, same policy as Bash.** A write whose target cannot be read — a
   variable, sub-expression or splat (`@params`) in a path, a path from the
   pipeline, an unknown parameter of a write cmdlet, a cwd made unknown,
   `& $cmd`, `cmd /c`, `wsl`, `Start-Process` of a shell or interpreter,
   `iex` of a non-literal, `Add-Type`, COM objects (`New-Object -ComObject`),
   `New-Object`/`::new` of `System.IO`/`System.Net` types, reflection
   (`[Reflection.…]`, `[Activator]`, `.Invoke(`, `[ScriptBlock]::Create`),
   instance file methods (`.Delete()`, `.MoveTo()`, `.CopyTo()`,
   `.Create*()`, `.Open*()`, `.Save()`, `.DownloadFile()`, `.Write*()`),
   `--%`, nesting deeper than four levels — is **denied while a restriction
   is active**; after approval only the protected-state checks act on it: an
   opaque command whose text names gatekit's state (also after backticks,
   quotes and `+` concatenation are removed, and in a decoded
   `-EncodedCommand`) or that runs inside it is denied.
7. **A worker never approves, in PowerShell either.** With `GATEKIT_TASK_ID`
   set, a command that runs gatekit's `approve` (`gatekit.py`/`gatekit`
   followed by `approve`, options skipped, not `check`/`list`) in any
   statement, nested `-Command`/`iex`/`bash -c` string or `Start-Process`
   argument list — matched on the text with quotes, commas and backticks
   removed — is denied before any other rule.
8. **The Skill tool gets no matcher.** The fork registered `Skill` to record
   the active pipeline when the model starts a gatekit skill on its own; that
   is pipeline bookkeeping, not a write path, and is not decided here. As a
   write path, a `Skill` call writes nothing itself; a skill's `` !`command` ``
   lines run at render time and are checked against permission rules, not
   PreToolUse hooks (code.claude.com/docs/en/skills, "Permission checks on
   injected commands"), and the `Skill` call's input names only the skill, so
   a `Skill` matcher would see none of them. What a skill tells the model to
   run arrives as ordinary `Bash`/`PowerShell`/`Write` calls, which are gated.

9. **Review pass (same day).** A separate adversarial review of the
   reader found forms it allowed; each is now covered and tested:
   a `$`/`@` at the end of the text crashed the lexer (fail-open) and very
   deep `"$(…)"` nesting hit Python's recursion limit — `pwsh.read` now never
   raises (an unreadable command is opaque); `using namespace` with a short
   type name, a static call on a computed type (`([type]'IO.File')::`,
   `$t::`), a quoted or computed member name (`::'WriteAllText'(`), an
   assembly-qualified type literal and `[Environment]::CurrentDirectory`
   are opaque; `ForEach-Object`/`%` invoking a member that may write
   (`| % Delete`, `-MemberName MoveTo`) is opaque; aliases and functions
   made through the `Alias:`/`Function:` providers and `New-PSDrive`/`subst`
   are opaque; `--` ends a cmdlet's parameters; `Start-Transcript
   -OutputDirectory` writes inside that directory; a PowerShell wildcard
   segment that matches `.gatekit` (PowerShell has no leading-dot rule, so
   `Remove-Item *` reaches it) is also judged as `.gatekit`; `pwsh -wd`/
   `-WorkingDirectory` sets the cwd of the nested command, and
   `Start-Job`/`Invoke-Command -WorkingDirectory` is opaque;
   reassigning `$PWD` makes the cwd unknown; `-EncodedCommand:<b64>` and
   whitespace inside the operand are decoded as .NET does; `Start-Process`
   hands a program's argument list to the native reading (`git clean`,
   `tar -C`, `robocopy`), and versioned interpreters (`python3.12`) count as
   runners; a command that writes and also runs a script or interpreter
   script (`Set-Content x.ps1 …; & ./x.ps1`) is opaque; `Unblock-File`,
   `Save-Help`, `Save-Module`/`Save-Script`/`Save-PSResource`,
   `New-ModuleManifest`, `New-ScriptFileInfo`, `Set-AuthenticodeSignature`
   and the `epal` alias are writes. The worker-approve detector also reads
   the lexed words, so `ap''prove`, `<#…#>`, a backtick line continuation,
   `-mgatekit`, a computed subcommand (`('ap'+'prove')`, `$('approve')`), a
   launcher held in a variable, `-m gatekit.cli` and `-m gatekit.approval`
   are denied, and it is linear in the command's length.

## What remains (documented trust boundary)

- **Anything opaque after approval that does not spell a protected path**:
  a path assembled at run time (`-join`, `-f`, `-replace`, `[char]` codes,
  `[Convert]::FromBase64String`, environment variables set elsewhere) is
  denied while restrictions are active and allowed after approval — the same
  boundary the Bash gate has.
- **Programs and scripts invoked by name** (`.\build.ps1`, `npm run x`,
  `python script.py`, `Import-Module`, a profile): outside a static reader's
  reach, as in Bash.
- **COM, .NET and reflection** beyond the patterns above (a type loaded
  under another name, a delegate, `Invoke-CimMethod`, `Invoke-WmiMethod`):
  not modelled.
- **Parameter tables are finite.** An unknown parameter on a write cmdlet is
  opaque; a cmdlet outside the list (a module's own) is a program invoked by
  name.
- **Codex on Windows.** Codex reports every shell call as `Bash`; if its
  command text there is PowerShell, the Bash reader reads it as shell syntax.
  Not observed; not decided here.
- **Shared with the Bash gate** (review): `Expand-Archive -DestinationPath .`,
  `git clean -fdx`/`reset --hard`/`stash -u` after approval, a launcher
  copied under another name, and a program (not a script) written and run
  by name.
- **Conservative refusals**: a write to `$env:TEMP\…` is opaque, so it is
  refused while a restriction is active; `Get-ChildItem function:` is
  opaque too.
- **Injected skill commands** (`` !`…` ``) and `skill shell: powershell`
  blocks never reach a PreToolUse hook (decision 8).

## Integration with ADR-0029

ADR-0029 landed on main while this gate was built; the two meet here.

- Every name contract in `pwsh.py` and `gates/powershell.py` goes through
  `names.py`, so the PowerShell gate reads `gatebound` exactly as the Bash
  gate does: `Start-Process` of any launcher name (`names.launcher_names`)
  is opaque; a wildcard segment adds the path once per state directory name
  (`names.state_dirnames`: `.gatebound`, `.gatekit`); the 8.3 short names of
  both (`GATEBO~1`, `GATEKI~1`; `names.state_short_names`) are spelled out
  in targets, removed paths and `mention_text`; the worker test reads
  `names.task_id()` (`GATEKIT_TASK_ID` or `GATEBOUND_TASK_ID`).
- Both approve detectors ask one function, `names.entry_kind`, what a word
  starts: the CLI (a launcher, `-m <name>`, `-m <name>.cli`,
  `-m <name>.__main__`) or the approval module (`-m <name>.approval`, whose
  arguments are `approve`'s), for every name. A dotted module counts only
  after `-m` (attached, the previous word, or a computed previous word), so
  `grep gatekit.approval src` is not an approval. This closes the Bash
  gap recorded above as left to a Bash-gate change: `python3 -m
  gatekit.approval spec/05-gate.md` and `python -m gatekit.cli approve …`
  are now denied in a worker by the Bash gate too (also in its unlexable
  fallback pattern); `approve check`/`approve list` stay allowed.

## Consequences

- `hooks.json` gains one PreToolUse entry; `doctor` requires `powershell.py`.
- Tests are pure parsing and run on every OS; no `pwsh` is needed. The
  Windows CI job is the only run where `\`-paths resolve natively.

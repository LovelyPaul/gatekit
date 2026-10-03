# Uninstalling gatekit

Removing the plugin and cleaning up a project are separate steps. Removing the
plugin stops every gate everywhere; it does not touch any project's files.

## 1. Remove the plugin

### Claude Code (CLI)

```
/plugin uninstall gatekit@gatekit
/plugin marketplace remove gatekit
```

Restart Claude Code afterwards: a running session keeps the hooks it loaded.
In the Claude desktop app, remove gatekit from the same plugin screen you
installed it from, then start a new session.

### Codex (CLI and app)

```
codex plugin remove gatekit@gatekit
codex plugin marketplace remove gatekit
```

Start a new Codex session afterwards. If a project still has the older
generated layer (`gatekit install --host codex`), clean it up as in step 2;
that layer runs from the project, not from the plugin.

## 2. What stays in your projects

Nothing below is deleted by uninstalling. Decide per project.

| Path | What it is | Usually |
|---|---|---|
| `spec/` | your PRD, screens, architecture, tasks, completion contract, progress | **keep** — it is your project's documentation, committed like any other doc |
| `.gatekit/` | config, approvals, attempts, contract, baseline; `runs/` and `jobs/` are local logs | remove when you no longer want gatekit in this project; `config.json`, `approvals.json` and `attempts.json` may be committed team state — check with your team first |
| `AGENTS.md` block between `<!-- gatekit:begin … -->` and `<!-- gatekit:end -->` | Codex instructions from the generated layer | remove the block; keep the rest of the file |
| `.codex/hooks.json` | Codex hook registrations from the generated layer | delete it if gatekit wrote it and you added nothing; otherwise remove only the entries that run gatekit |
| `.agents/skills/gatekit-*` | Codex skills from the generated layer | delete these directories |

A safe order:

```bash
git status                       # start from a clean tree, so the removal is one reviewable diff
git rm -r --cached .gatekit      # if .gatekit/ files were committed
rm -rf .gatekit
rm -rf .agents/skills/gatekit-*  # only if you used the generated Codex layer
# edit AGENTS.md and .codex/hooks.json by hand as in the table above
git status                       # check that only gatekit's files are going
git commit -m "Remove gatekit state"
```

Leave `spec/` in place unless you are sure nothing else refers to it.

## Turning gatekit off without uninstalling

Every gate stands down in a project that has no `.gatekit/` directory: no
check runs and no state is created there. So with the plugin still
installed, deleting a project's `.gatekit/` turns gatekit off for that
project alone, and other projects keep their gates.

## 한국어 요약

1. **플러그인 제거.** Claude Code: `/plugin uninstall gatekit@gatekit`,
   `/plugin marketplace remove gatekit` 후 재시작. Codex: `codex plugin remove gatekit@gatekit`,
   `codex plugin marketplace remove gatekit` 후 새 세션.
2. **프로젝트에 남는 것.** 제거해도 프로젝트 파일은 지워지지 않습니다. `spec/`은 프로젝트 문서이므로
   보통 남깁니다. `.gatekit/`은 더 쓰지 않을 때 지웁니다(커밋돼 있었다면 `git rm -r --cached .gatekit`).
   생성된 Codex 레이어를 썼다면 `AGENTS.md`의 `gatekit:begin`~`gatekit:end` 블록,
   `.codex/hooks.json`의 gatekit 항목, `.agents/skills/gatekit-*`를 지웁니다.
3. **제거하지 않고 끄기.** `.gatekit/`이 없는 프로젝트에서는 모든 게이트가 물러납니다. 플러그인을
   둔 채 그 프로젝트의 `.gatekit/`만 지우면 그 프로젝트에서만 꺼집니다.

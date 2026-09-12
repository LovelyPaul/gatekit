# 설치와 진단

## 요구사항

| 항목 | 조건 | 확인 방법 |
|---|---|---|
| `python3` | 3.9 이상 | doctor 7번 축 |
| `claude` CLI | PATH에 있어야 함 | doctor 6번 축 |
| Claude Code | 플러그인 설치·활성화 가능한 버전 | doctor 2번 축 |

gatekit 커널은 파이썬 표준 라이브러리만 쓴다. `pip install`이 필요 없다. `codex` CLI는 선택이며 기본적으로 비활성이다.

## 설치

```bash
/plugin marketplace add https://github.com/LovelyPaul/gatekit
/plugin install gatekit@gatekit
```

설치 후 **Claude Code를 재시작**해야 `plugin/hooks/hooks.json`의 훅이 로드된다. 재시작하지 않으면 파일은 디스크에 있지만 게이트가 하나도 발화하지 않는다.

### Codex CLI 사용자

Codex에는 플러그인 형식이 없다. 저장소를 클론하고 프로젝트 루트에서 호스트 층을 생성한다.

```bash
git clone https://github.com/LovelyPaul/gatekit
python3 "gatekit/plugin/bin/gatekit.py" install --host codex
```

`.codex/hooks.json`(게이트 6개), `.agents/skills/gatekit-*`(커맨드별 스킬), `AGENTS.md`의 관리 블록이 생긴다. 생성 파일은 손으로 고치지 않고 `plugin/`을 고친 뒤 다시 `install`한다. Codex가 프로젝트의 `.codex/` 층을 신뢰하겠느냐고 물으면 승인하고 **새 세션을 연다**. 신뢰하지 않으면 훅은 파일로만 존재한다. doctor 8번 축이 이 층을 본다. 호스트별로 되는 것과 `unverified`인 것은 README의 동등성 표에 있다.

재시작한 다음 반드시 진단을 돌린다.

```bash
/gatekit:doctor
```

## 8축 doctor 판정표

`doctor`는 7개 축을 각각 `ok`/`warn`/`fail`/`unverified`로 판정하고, 축마다 복붙 가능한 `fix` 문자열을 낸다. 종료 코드는 `fail`이 하나라도 있을 때만 1이다. 종료 코드 0은 "아무것도 실패하지 않았다"는 뜻이지 "다 괜찮다"는 뜻이 아니다.

| # | 축 | 무엇을 보는가 | `fail`일 때 처방 |
|---|---|---|---|
| 1 | plugin files | `plugin.json`, `hooks.json`, 게이트 스크립트 6개가 존재하고 비어 있지 않은가 | `/plugin install gatekit` — 스크립트가 없으면 그 게이트는 아예 발화하지 않는다 |
| 2 | hooks registered | `installed_plugins.json`에 등재되고 `settings.json`의 `enabledPlugins`에서 활성인가 | `/plugin enable gatekit@gatekit` |
| 3 | project state | `.gatekit/config.json`과 `approvals.json`이 파싱되는가 | 해당 파일을 손으로 고치거나 삭제한다 |
| 4 | spec set | `spec validate` 판정 | 실패한 파일을 소유한 파이프라인으로 간다 |
| 5 | contract freshness | `.gatekit/contract.json`의 `source_sha256`가 `05-gate.md`와 일치하는가 | `contract derive` 재실행 |
| 6 | workers | 기본 백엔드 바이너리가 PATH에 있는가 | 해당 CLI를 설치하거나 `workers set-default <name>` |
| 7 | python | 인터프리터가 3.9 이상인가 | 파이썬 3.9 이상 설치 |
| 8 | host layer | Codex용 `.codex/hooks.json`이 있으면 그 안의 게이트 스크립트가 실제로 존재하는가. 없으면 `ok` (Claude Code 프로젝트는 필요 없다) | `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" install --host codex` |

### `unverified`가 나오는 정상적인 경우

- 2번 축: 소스 체크아웃에서 실행 중이라 설치 매니페스트가 없다. 문제가 아니다.
- 3번 축: 프로젝트에 `.gatekit/`이 아직 없다. `/gatekit:setup` 전이다.
- 4번 축: 프로젝트에 `spec/` 디렉터리가 없다. `/gatekit:interview` 전이다.
- 5번 축: `.gatekit/contract.json`이 아직 없다. `/gatekit:gate` 전이다.
- 6번 축: 바이너리는 있으나 `--version` 프로브가 응답하지 않았다. 빌드는 돌아간다.

`unverified`를 "이상 없음"으로 요약하면 안 된다. 검사하지 않았다는 뜻이다.

### 가장 위험한 실패

2번 축의 `fail`이다. 설치는 되었는데 `enabledPlugins`에서 비활성이면 디스크에는 모든 파일이 있고 훅은 하나도 발화하지 않는다. 하네스가 설치된 것처럼 보이면서 아무것도 강제하지 않는 상태다.

## 프로젝트 초기화

프로젝트 디렉터리에서 실행한다.

```bash
/gatekit:setup
```

`.gatekit/config.json`이 없으면 기본값으로 생성하고, 기본 워커(`claude`)를 점검한 뒤 백엔드 표를 보여준다. 이미 있으면 건드리지 않는다.

Codex 백엔드를 쓰려면 별도로 요청해야 한다.

```bash
/gatekit:setup codex
```

이 경우 `workers check codex`를 먼저 돌리고, 무엇이 바뀌는지 설명한 뒤 사용자 확인을 받고서야 활성화한다. 확인 전에는 아무것도 바꾸지 않는다.

## 업데이트

```bash
/plugin marketplace update gatekit
```

업데이트 후에도 Claude Code를 재시작한다. 현재 세션은 이미 로드된 구 버전을 계속 쓴다. 재시작 뒤 `/gatekit:doctor`로 1·2번 축을 확인한다.

## 제거

```bash
/plugin uninstall gatekit@gatekit
```

프로젝트의 `spec/`과 `.gatekit/`은 그대로 남는다. `spec/`은 커밋 대상 산출물이고, `.gatekit/` 안에서는 `config.json`과 `approvals.json`만 커밋 대상이며 `runs/`와 `jobs/`는 무시 대상이다. 플러그인을 지워도 이 파일들은 지워지지 않으므로 필요하면 직접 삭제한다.

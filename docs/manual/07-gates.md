# 훅 게이트 6개

`plugin/hooks/hooks.json`에 6개 훅이 등록된다. 이 파일은 Claude Code가 자동으로 읽으며 `plugin.json`에 나열하지 않는다. 중복 참조는 플러그인 로드를 실패시킨다.

| 게이트 | 이벤트 | 대상 도구 | 차단하는가 |
|---|---|---|---|
| prompt | `UserPromptSubmit` | 없음 | 아니오 |
| write | `PreToolUse` | `Write`, `Edit`, `MultiEdit`, `NotebookEdit` | 예 |
| bash | `PreToolUse` | `Bash` | 예 |
| spawn | `PreToolUse` | `Agent`, `Task` | 예 |
| question | `PostToolUse` | `AskUserQuestion` | 아니오 (채널이 없다) |
| stop | `Stop` | 없음 | 예 (최대 3회) |

![훅 게이트 개요](../assets/gates.svg)

## prompt 게이트

**언제**: 사용자가 프롬프트를 보낼 때마다.

**하는 일**: 세션 원장을 만들거나 불러오고, 프롬프트 텍스트에서 `output_lang`을 감지해 저장한다. 프롬프트가 `/gatekit:<파이프라인>` 호출이면(Claude Code는 슬래시 명령을 `<command-name>/gatekit:build</command-name>` 태그 본문으로 넘긴다) 원장의 `active_pipeline`을 그 값으로 기록한다(`doctor`·`setup`은 지운다). stop 게이트와 질문 예산은 이 값을 읽으므로, 파이프라인 기록은 커맨드 산문이 아니라 이 게이트가 코드로 한다. 다른 파이프라인으로 넘어가면 질문 예산은 0부터 다시 센다. 그리고 600자 이내의 컨텍스트 블록을 대화에 주입한다. 블록에는 출력 언어, 활성 파이프라인, 질문 예산 사용량, 게이트 승인 상태, 계약 상태가 들어간다.

**차단**: 하지 않는다.

**주의**: 빈 프롬프트는 언어 신호가 없으므로 저장된 언어를 그대로 둔다. 빈 줄 하나를 보냈다고 영어로 바뀌지 않는다.

## write 게이트

**언제**: `Write`·`Edit`·`MultiEdit`·`NotebookEdit` 호출 직전.

독립적인 두 규칙이 있고 각각이 단독으로 쓰기를 거부할 수 있다.

### 규칙 (a) 스펙 먼저

`enforce_spec_before_code`가 켜져 있고 `spec/` 디렉터리가 존재하는데 `spec/05-gate.md` 승인이 `ok`가 아니면, 아래 허용 목록 밖의 쓰기를 거부한다.

```text
spec/**
.gatekit/**
docs/**
README*
*.md   (루트 레벨만)
```

이 허용 목록이 있는 이유는 게이트를 열어줄 스펙 자체를 쓸 수 있어야 하기 때문이다.

**차단됐을 때 할 일**: `/gatekit:gate`를 실행해 완료 기준을 만들고 사용자가 승인한다. 급하면 `spec/`·`docs/`·루트 마크다운에 먼저 쓴다. 차단 메시지에 현재 승인 상태(`fail` 또는 `unverified`)와 막힌 경로가 나온다.

### 규칙 (b) 태스크 쓰기 범위

`GATEKIT_TASK_ID` 환경변수가 설정된 경우 — 즉 잡 러너가 띄운 워커 세션 안에서 — 그 태스크의 `task.json`에 적힌 `write_scope` 안에서만 쓸 수 있다. 규칙 (b)는 (a)보다 엄격해서 문서 허용 목록이 없다. `src/auth/**`를 배정받은 워커가 PRD를 다시 쓸 이유는 없다.

거부되는 네 가지 경우다.

| 상황 | 메시지 키 |
|---|---|
| 프로젝트 루트 밖 경로 | `outside_root` |
| `task.json`을 읽을 수 없어 범위 확인 불가 | `scope_missing` |
| 범위가 `"read-only"` | `scope_read_only` |
| 범위에 없는 경로 | `scope` |

범위를 확인할 수 없으면 거부한다. 범위를 확립할 수 없는 태스크 id를 주장하는 워커에게는 쓰기 권한을 주지 않는다.

**차단됐을 때 할 일**: 워커 안에서라면 그 태스크의 범위를 벗어난 것이다. `04-tasks.md`의 태스크 분해가 잘못되었다는 신호다. 범위를 넓히지 말고 태스크를 다시 자른다.

## bash 게이트

**언제**: `Bash` 도구가 실행되기 직전.

**하는 일**: 명령 문자열을 실행하지 않고 읽어서 그 명령이 쓸 파일을 뽑아낸 뒤, 각 경로를 write 게이트와 **같은 함수**로 판정한다. 리다이렉션(`>`, `>>`, `&>`), `tee`, `sed -i`, `perl -i`, `cp`/`mv`/`ln`/`install`/`rsync`의 목적지, `touch`/`rm`/`mkdir`/`truncate`/`chmod`/`chown`의 대상, `dd of=`, 그리고 `sort -o`·`curl -o`·`wget -O`·`tar -C`/`-f`·`unzip -d`·`zip`처럼 출력 경로가 인자에 그대로 보이는 도구를 인식한다. `cd`는 `;`, `&&`, `|`, 줄바꿈을 넘어 추적하고, `VAR=`·`sudo`·`env`·`nohup` 접두는 벗기며, 히어독 본문과 `/dev/*`는 무시하고, `sh -c "…"`는 재귀로 읽는다.

**빠른 경로**: 어떤 규칙도 거부할 수 없는 상태(`GATEKIT_TASK_ID` 없음, 게이트 승인됨 또는 `spec/` 없음)면 파싱 없이 통과시킨다. 평소 세션은 이 게이트의 비용을 내지 않는다.

**판별 불가는 거부**: 규칙이 살아 있는데 쓰기 대상을 알 수 없으면 거부한다. 경로 안의 `$VAR`나 백틱, 알 수 없는 디렉터리로 `cd`, `eval`, `xargs`, `patch`, `trap`, `find -exec`, 작업 트리를 바꾸는 `git` 하위 명령(`apply`, `checkout`, `restore`, `reset`, `merge`, `stash`, `init`, `clone` 등), 인라인 인터프리터 코드(`python3 -c`, `node -e`), `awk`, 명령줄 편집기(`ed`, `ex`, `vim`, `nano`), `busybox`, 파일명을 스스로 정하는 다운로드(`curl -O`, 옵션 없는 `wget`), 프로세스 치환, 짝이 안 맞는 따옴표가 여기 해당한다. 거부 메시지는 이유와 대안(Write/Edit 도구, 리터럴 경로)을 말한다. `unverified`를 `ok`로 반올림하지 않는 것과 같은 원칙이다.

**한계**: 이름으로 호출되는 프로그램(`npm run build`, `python3 script.py`)이 무엇을 쓰는지는 보지 않는다. 셸 문법을 읽는 게이트이지 모든 바이너리의 동작을 아는 게이트가 아니다. 근거는 `docs/decisions/ADR-0004-bash-write-gate.md`.

## spawn 게이트

**언제**: `Agent`나 `Task`로 서브에이전트를 띄우기 직전.

**요구하는 것**: spawn 프롬프트에 `gatekit-scope` 펜스가 있어야 하고, 그 안이 유효한 JSON 객체여야 한다.

```json
{"write_scope": ["src/auth/**"], "stop_when": "테스트 통과", "tools": "inherit"}
```

| 필드 | 규칙 |
|---|---|
| `write_scope` | 비어 있지 않은 글로브 문자열 리스트, 또는 정확히 `"read-only"` |
| `stop_when` | 비어 있지 않은 문자열. 필수 |
| `tools` | 리스트 또는 문자열 `"inherit"`. 기본값 `"inherit"` |

`stop_when`이 필수인 이유는 종료 조건을 말하지 않은 에이전트는 그 조건에 대해 검사할 수 없기 때문이다.

**거부하는 경우**: 펜스가 없거나, JSON이 아니거나, 필드 규칙 위반이거나, 선언한 범위가 이 세션에서 이미 활성인 범위와 겹칠 때.

**핵심 설계**: 펜스는 **JSON으로 파싱**하지 산문에 정규식을 돌리지 않는다. 프롬프트가 문장 안에서 `write_scope`를 언급하는 것만으로는 게이트를 만족시키지 못한다. 에이전트가 말로 강제를 우회할 수 없다.

**차단됐을 때 할 일**: 펜스를 추가한다. 범위 충돌이면 범위를 좁히거나 앞선 에이전트가 끝날 때까지 기다린다. 메시지에 겹치는 범위의 소유자 이름이 나온다.

## question 게이트

**언제**: `AskUserQuestion`이 실행된 **직후**.

**하는 일**: 세션의 질문 횟수를 센다. `interview` 파이프라인에서만 예산이 있고, 기본 2회이며 `questions.interview_max_calls`로 설정한다. 다른 파이프라인은 무제한이다. 예산을 넘으면 `budget_exceeded`를 참으로 기록한다.

**차단**: 하지 않는다. `PostToolUse`에는 차단 채널이 없다. 차단하는 척하면 그건 산문 강제다.

**그럼 무슨 소용인가**: 플래그는 정보성이고 커맨드가 읽어 스스로 행동을 바꾼다. 인터뷰 파이프라인은 질문을 멈추고 대신 가정을 원장에 쓴다.

## stop 게이트

**언제**: 세션이 끝나려 할 때.

**발동 조건**: `.gatekit/contract.json`이 존재하고 세션 원장의 `active_pipeline`이 `build`나 `verify`일 때만 계약을 실행한다. 그 외에는 통과시킨다.

**차단 조건**: 계약 실행 결과에 `fail`이나 `unverified` 기준이 하나라도 있고, `block_count`가 3 미만이고, `stop_hook_active`가 참이 아닐 때. 차단 메시지에 실패한 기준 목록이 들어가고 `block_count`가 1 증가한다.

계약이 stale이면 다른 메시지가 나간다. `contract derive`를 실행하고 작업을 마치라는 안내다.

### 3회 차단 후 해제 규칙

`block_count`가 3에 도달하면 게이트는 물러나고 세션 종료를 허용한다. 만족시킬 수 없는 게이트가 사용자를 인질로 잡으면 안 되기 때문이다. 다만 물러나면서도 통과하지 않았다는 사실은 그대로 기록한다. `stop.final_verdict`에 실제 판정이 들어가고, 그 값은 **절대 공란이 아니다**. 실행되지 않은 계약은 조용한 성공이 아니라 `unverified`로 기록된다.

`stop_hook_active`가 참이면 — Claude Code가 이미 stop 훅 연속 실행 안에 있다는 뜻 — 다시 차단하면 루프가 되므로 언제나 통과시킨다. 이때도 계약을 실행하고 결과를 기록한다.

**차단됐을 때 할 일**: 메시지에 나온 기준의 원인을 고치고 계약을 다시 실행한다. `unverified`가 원인이면 대개 타임아웃이며, 실측한 뒤 `gatekit-budget`을 선언하는 것이 정공법이다.

## 훅은 언제나 exit 0이다

모든 게이트는 `hookio.run(handler)`를 통과한다. 이 래퍼는 stdin을 읽고 핸들러를 부르고 반환된 JSON을 출력한 뒤 **항상 0으로 종료한다**. 예외는 `.gatekit/runs/hook-errors.log`에 `iso_ts event_name error` 한 줄로 추가된다.

차단은 종료 코드가 아니라 stdout의 JSON으로 표현된다. `PreToolUse`는 `permissionDecision: "deny"`, `Stop`은 `decision: "block"`이다.

**왜 이렇게 하는가**: 고장 난 훅이 사용자의 세션을 절대로 망가뜨리면 안 된다. 자기 상태를 파싱하지 못하거나 버그를 만나거나 시간이 초과된 게이트는 "허용하고 로그를 남긴다"로 격하되지, "멈추거나 죽는다"가 되지 않는다. 깨진 게이트 스크립트는 기록된 성가심이지 장애가 아니다.

성능 요구도 여기서 나온다. 각 게이트는 보통 프로젝트에서 5초 안에 끝나야 하고, Stop 게이트만 계약 실행 때문에 최대 45초까지 허용된다.

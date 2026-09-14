# CLI 레퍼런스

## 반드시 이 형식이어야 한다

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" <subcommand> [args]
```

### 왜 다른 형식은 안 되는가

커맨드는 **사용자의 프로젝트 디렉터리에서** 실행된다. 거기서는 `gatekit` 패키지가 `sys.path`에 없다. 그래서 모듈 실행 형식은 프로젝트 디렉터리에서 import 오류로 죽는다.

`bin/gatekit.py` 런처는 자기 위치에서 플러그인 루트를 계산해 `sys.path` 맨 앞에 넣은 뒤 디스패처를 부른다. 그 외에는 동작이 같다.

플러그인 루트로 `cd`한 뒤 실행하는 것도 안 된다. 작업 디렉터리가 바뀌면 프로젝트 루트 탐지와 상대 경로가 전부 플러그인 쪽을 가리키게 된다.

이 규칙은 CI 게이트 `tools/gate_command_invocations.py`가 강제한다. 커맨드나 정책 파일에 실행되지 않는 호출 형식이 들어가면 빌드가 실패한다.

## 서브커맨드 9개

`cli.py`의 `SUBCOMMANDS` 레지스트리가 전부다. 모듈은 지연 import되므로 하나가 깨져도 나머지는 동작한다.

| 서브커맨드 | 역할 |
|---|---|
| `doctor` | 설치·훅·상태·워커·호스트 8축 진단 |
| `spec` | 스펙 세트 검증 |
| `contract` | 완료 계약 파생·상태·실행 |
| `approve` | 해시 앵커 승인 |
| `jobs` | 워커 잡 실행과 관리 |
| `workers` | 워커 백엔드 관리 |
| `ledger` | 세션 원장 조회·파이프라인 설정 |
| `install` | Codex 호스트 층 생성 (`--host codex`) |
| `lang` | 출력 언어 감지 |

인자 없이 부르면 사용법을 출력하고 종료 코드 1을 낸다. `-h`·`--help`·`help`는 0을 낸다. 없는 서브커맨드는 2다.

## doctor

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" doctor [--root PATH] [--json]
```

7개 축을 각각 판정하고 축마다 `fix` 문자열을 낸다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | `fail` 축이 하나도 없음 |
| 1 | `fail` 축이 하나 이상 |

## spec

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" spec validate [--root PATH] [--json] [--lang ko|en]
```

`validate`가 유일한 하위 명령이다. `--root`를 주면 그 경로를 프로젝트 루트로 직접 지정한다. 주지 않으면 상위로 걸어 올라가며 탐지한다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 판정이 `fail`이 아님 |
| 1 | 판정이 `fail` |
| 2 | `validate` 외의 하위 명령 |

## contract

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract derive [--root PATH] [--json]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract status [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract run [--root PATH] [--json] [--budget SECONDS]
```

| 동작 | 하는 일 |
|---|---|
| `derive` | `05-gate.md`의 펜스를 `.gatekit/contract.json`으로 파생. 소스 해시와 예산을 함께 기록 |
| `status` | `ok`(최신) / `fail`(stale) / `unverified`(없음) 중 하나를 출력 |
| `run` | 각 기준을 실행하고 집계 판정을 낸다 |

`--budget`은 계약에 선언된 예산을 덮어쓴다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | `derive` 성공, 또는 `status`/`run`이 `ok` |
| 1 | `derive` 실패, 또는 `status`/`run`이 `ok`가 아님 |
| 2 | 인자 오류 |

## approve

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve <path> [--note "..."] [--by NAME] [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve check <path> [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve list [--root PATH]
```

`approve <path>`는 아무것도 묻지 않고 현재 해시를 기록한다. 사용자에게 `AskUserQuestion`으로 묻는 것은 커맨드 파일의 책임이다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 승인 성공, `list` 성공, 또는 `check`가 `ok` |
| 1 | 대상 파일 없음, 또는 `check`가 `fail`/`unverified` |
| 2 | 인자 누락 |

## jobs

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs start [--tasks id,id] [--backend name] [--parallel N] [--dry-run] [--no-preflight]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs status [--job ID] [--json]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs wait [--job ID] [--timeout S]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs results [--job ID] [--compact|--json]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs redelegate <task_id> [--job ID]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs stop [--job ID]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs evaluate [--backend name] [--prompt FILE] [--lang ko|en] [--json]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs clean [--all]
```

`results --compact`는 태스크당 한 줄로 `id state gates_passed/total`을 출력한다. `clean`은 기본적으로 가장 최근 잡을 남기고, `--all`은 전부 지운다. `evaluate`는 `verify.evaluator`(또는 `--backend`)가 가리키는 백엔드를 `read_only_argv`로 한 번 실행해 평가자로 쓴다. `.gatekit/jobs/<잡>/evaluate/`에 기록하고 응답 꼬리(판정표)를 출력한다. 상태가 `passed`가 아니면 모든 기준이 `unverified`다.

`start`는 워커를 띄우기 전에 태스크마다 게이트를 한 번 먼저 돌린다(ADR-0009). 이미 통과하면 워커 없이 `passed`로 기록하고, 쓰기 범위에 파일이 하나도 없는데 통과했다면 `warn`을 붙인다(항상 통과하는 게이트일 수 있다). 게이트 명령 자체가 오류이면(종료 코드 126·127, 또는 `Cannot find module`·`No such file or directory` 같은 출력이 게이트 인자 중 하나를 직접 가리킬 때) 잡을 시작하지 않고 종료 코드 4로 태스크와 게이트 이름을 알린다. 종료 코드 2 이상이나 인자를 가리키지 않는 비슷한 출력은 의심만 하고 경고를 남긴 채 시작한다. `--no-preflight`는 이 단계를 건너뛴다. `redelegate`는 현재 `spec/04-tasks.md`에서 태스크를 다시 읽고, 게이트·지시·쓰기 범위가 바뀌었으면 상태 줄에 `task re-read … (gates changed)`라고 적는다. `stop`은 이 잡이 띄운 워커만 종료하고(pid와 시작 시각을 함께 확인한다) 실행 중·대기 중 태스크를 `stopped`로 기록한다.

태스크 상태는 `queued` / `running` / `gating` / `passed` / `failed` / `timeout` / `redelegated` / `stopped` / `blocked`다. `blocked`는 같은 잡 안의 의존 태스크가 `passed`가 아니어서 실행하지 않은 것이다. `stopped`와 `blocked`는 종료 상태이며 완료가 아니다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 판정이 `fail`이 아님 |
| 1 | 판정이 `fail` |
| 2 | 인자 오류, 알 수 없는 명령 |
| 3 | 재시도 예산 소진 (`build.max_retries` 초과) |

## workers

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers list [--json] [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers check <name> [--probe] [--json]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers set-default <name>
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers enable <name>
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" workers set-evaluator <agent|name>
```

`check`의 판정 기준이다.

| 판정 | 조건 |
|---|---|
| `ok` | PATH에 있고 `argv[0] --version`이 0으로 종료 |
| `unverified` | PATH에는 있으나 버전 프로브가 실패·오류·시간 초과 |
| `fail` | PATH에 없거나, 백엔드가 없거나, `argv`가 유효하지 않음 |

`enable`은 argv에 샌드박스 bypass 플래그가 있는데 설정 항목에 `"unsafe": true`가 없으면 거부한다.

`check --probe`는 백엔드의 `read_only_argv`로 한 문장짜리 프롬프트를 실제로 보낸다. 바이너리는 있는데 답을 못 하는 상태(로그인 안 됨, 샌드박스가 자격증명을 가림)를 빌드 전에 잡는 유일한 검사다. 답하면 `ok`, 0이 아닌 종료 코드면 출력 꼬리와 함께 `fail`, 시간 초과면 `unverified`다. `/gatekit:build`가 잡을 시작하기 전에 이 검사를 돌린다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 성공, 또는 `check`가 `ok`/`unverified` |
| 1 | `check`가 `fail` |
| 2 | 이름 누락, 없는 백엔드, unsafe 거부, 알 수 없는 명령 |

## ledger

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" ledger show --session <id> [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" ledger init --session <id> [--root PATH]
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" ledger set-pipeline <interview|mockup|tasks|gate|build|verify|none> --session <id> [--root PATH]
```

`--session`은 필수다. `show`는 원장 JSON 전체를, `init`은 생성된 파일 경로를 출력한다. `set-pipeline`은 `active_pipeline`을 기록한다. 평소에는 prompt 게이트가 `/gatekit:<파이프라인>` 호출을 보고 자동으로 기록하므로 손으로 부를 일은 디버깅뿐이다. 다른 파이프라인으로 바뀌면 질문 예산이 초기화된다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 성공 |
| 1 | 해당 세션의 원장 없음 |
| 2 | `set-pipeline`에 알 수 없는 이름 |
| 2 | 인자 오류 |

## install

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" install --host codex [--root PATH] [--dry-run]
```

프로젝트에 Codex 호스트 층을 생성한다. `.codex/hooks.json`, `.agents/skills/gatekit-<커맨드>/{SKILL.md,command.md}`, `AGENTS.md`의 관리 블록. 원본은 `plugin/`이며 생성물은 다시 만들 수 있다. 두 번 실행해도 같은 결과다. `--dry-run`은 쓸 파일 목록만 보여준다.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 성공 |
| 2 | 알 수 없는 호스트 (`claude`는 플러그인으로 설치하므로 여기서 받지 않는다) |

## lang

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" lang "감지할 텍스트"
```

`ko` 또는 `en` 한 단어를 출력한다. 언제나 종료 코드 0이다.

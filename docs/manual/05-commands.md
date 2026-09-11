# 커맨드 레퍼런스

## 요약

| 커맨드 | 인자 | 산출물 | AskUserQuestion 횟수 |
|---|---|---|---|
| `/gatekit:discover` | 선택. 거친 아이디어나 빈 인자 | `spec/00-discovery.md` | 0 (평문 질문, 게이트당 최대 3개) |
| `/gatekit:interview` | 만들려는 것에 대한 설명 | `spec/01-prd.md`, `spec/03-architecture.md` | 최대 2 + 확인 1 |
| `/gatekit:mockup` | Figma URL, HTML 경로, 스크린샷 경로 | `spec/02-screens.md`, `spec/tokens.json` | 최대 1 |
| `/gatekit:tasks` | 선택적 제약 (예: "round 1만") | `spec/04-tasks.md` | 0 |
| `/gatekit:gate` | 선택적 추가 기준 | `spec/05-gate.md`, `.gatekit/contract.json`, 승인 | 승인 1 (수정 시 반복) |
| `/gatekit:build` | 선택적 태스크 id 목록 | 잡 디렉터리, `spec/PROGRESS.md` | 0 |
| `/gatekit:verify` | 선택적 기준 id | 판정표, `spec/PROGRESS.md` | 0 |
| `/gatekit:doctor` | 선택적 `--json` | 진단 표 | 0 |
| `/gatekit:setup` | 선택적 `codex` | `.gatekit/config.json` | codex일 때만 최대 2 |

## /gatekit:discover

**언제**: 뭘 만들지 모를 때, 또는 "챗봇 같은 거"처럼 만들 것만 있고 실사용자와 불편이 없을 때. 선택 단계이며, 이 파일이 없어도 나머지 파이프라인은 그대로 돈다.

**읽는 것**: 정책 파일 2종(언어·질문), 언어별 `00-discovery.md` 템플릿, 이미 있으면 `spec/00-discovery.md`(첫 빈 게이트부터 이어간다).

**쓰는 것**: `spec/00-discovery.md` 하나. 산문 절 5개와 `gatekit-discovery` JSON 펜스 하나. 게이트를 하나 채울 때마다 파일을 갱신하므로 도중에 끊겨도 기록이 남는다.

**질문**: 평문 채팅으로 한 번에 하나, 모든 질문에 추천 답을 붙인다. 과거에 실제로 일어난 일만 묻고, 해법이나 추상어가 나오면 마지막 사건으로 되돌린다. 게이트 하나에 질문 3개가 상한이고, 그래도 못 채우면 `unpassed`에 적고 넘어간다. 중단 신호("알아서 해줘")가 오면 지금까지 것으로 파일을 쓰고 멈춘다.

**심화 게이트 6개**: 실사용자 1명(이름·역할), 현재 방식(번호 순서 2단계 이상), 빈도(숫자), 1회 소요(숫자), 원인(바꿔 말하기를 뺀 서로 다른 "왜" 3칸 이상, 첫 답과 달라야 하고 사용자가 확인), 실패한 대안(`failed` / `works-but-costly` 구분, 없으면 `not-applicable`). `spec validate`가 빈 게이트를 `warn`으로 잡고, 펜스 누락이나 빈 문제 문장은 `fail`이다.

**다음**: `/gatekit:interview`가 이 파일을 사실로 읽어 열린 질문을 건너뛴다. `unpassed`에 적힌 게이트는 가정 원장 행이 된다.

## /gatekit:interview

**언제**: 아이디어만 있고 문서가 없을 때. `spec/01`이 이미 있으면 개정 모드로 동작한다. 인자에 실사용자와 불편이 없으면 `/gatekit:discover`로 보낸다.

**읽는 것**: 정책 파일 3종, `heading-map.json`, 언어별 템플릿, 기존 `spec/`, 레포의 언어·프레임워크·테스트 러너, `README*`·`package.json`·`pyproject.toml`·락파일·CI 설정.

**쓰는 것**: `spec/01-prd.md`, `spec/03-architecture.md`. 템플릿의 `{{...}}` 자리표시자를 하나도 남기지 않는다.

**질문**: 과거 행동에 대한 열린 질문 1개를 평문 채팅으로 던진다. 사용자 텍스트가 이미 답하거나 "알아서 해줘" 같은 중단 신호가 있으면 건너뛴다. 이후 사용자만 결정할 수 있는 사안에 대해 `AskUserQuestion`을 최대 2회, 마지막에 확인 질문 1회를 한다.

**실패하면**: `spec validate`가 `fail`이면 실패한 파일을 버리고 템플릿에서 다시 쓴다. 이해하지 못한 지적을 우회 수정하지 않는다. 3회 재작성에도 실패하면 멈추고 남은 지적을 정확히 보고한다.

## /gatekit:mockup

**언제**: 디자인 산출물이 있을 때. 선택 단계다.

**읽는 것**: Figma MCP 도구(`get_metadata`, `get_design_context`, `get_variable_defs`, `get_screenshot`), 또는 HTML 파일, 또는 이미지. 각 추출 항목은 근거(프레임 이름·파일 경로·셀렉터)를 함께 기록한다.

**쓰는 것**: `spec/02-screens.md`, `spec/tokens.json`, 그리고 `spec/01-prd.md`의 가정 원장에 gap 행 추가.

**질문**: 최대 1회. 틀렸을 때 대가가 가장 큰 단일 gap에 대해서만 묻는다.

**실패하면**: Figma MCP 도구를 쓸 수 없으면 그 사실을 말하고 내보내기나 스크린샷을 요청한 뒤 멈춘다. URL만 보고 디자인을 추측하지 않는다.

**주의**: 목업은 정상·빈·오류·로딩 4개 상태를 거의 다 보여주지 않는다. 빠진 상태는 설계해서 쓰되 전부 가정으로 표시한다. `## 근거 없는 영역` 절이 비어 있으면 제대로 읽지 않은 것이다.

## /gatekit:tasks

**언제**: `01-prd.md`가 있고 아직 작업 분해가 없을 때. `01-prd.md`가 없으면 멈추고 `/gatekit:interview`로 보낸다.

**읽는 것**: `01`의 기능 `F<n>`과 수용 기준, `02`의 화면 `S<n>`, `03`의 스택과 제약, 그리고 실제 레포 구조(디렉터리, 테스트 명령, 파일 명명 규칙).

**쓰는 것**: `spec/04-tasks.md`. 각 작업은 `gatekit-task` 펜스 하나다.

**질문**: 없다.

**규칙**: 작업은 수직 슬라이스여야 한다. "폼을 제출하면 저장된 값이 보인다"는 맞고, "DB 모델 전부 만들기"는 틀리다. 같은 라운드의 두 작업은 쓰기 범위가 겹칠 수 없다. 모든 작업은 게이트를 최소 1개 갖는다.

**실패하면**: 범위 충돌은 다시 자르지 넓히지 않는다. `01`의 기능 중 담당 작업이 없는 것은 gap으로 보고한다.

## /gatekit:gate

**언제**: `04-tasks.md`가 완성된 뒤. 없으면 멈추고 `/gatekit:tasks`로 보낸다.

**읽는 것**: `01`의 수용 기준, `04`의 모든 작업.

**쓰는 것**: `spec/05-gate.md`, 그리고 승인 시 `.gatekit/contract.json`과 `.gatekit/approvals.json`.

**질문**: 승인 여부 1회. 사용자가 수정이나 추가를 선택하면 반영 후 다시 파생하고 다시 묻는다.

**핵심**: 모든 기준은 지금 이 레포에서 실행 가능해야 한다. 쓰기 전에 각각 실행해본다. 실행해보지 않은 기준은 추측이며 Stop 훅이 실제로 실행한다.

**승인이 바꾸는 것**: 파일 해시가 고정된다. 쓰기 게이트가 `spec/` 밖 편집을 막는 것을 멈춘다. Stop 훅이 이 명령들을 실행하고 하나라도 `fail`이나 `unverified`면 완료를 막는다. 이후 파일을 고치면 승인이 만료된다.

**실패하면**: 사용자가 승인하지 않으면 그 사실을 명시하고 쓰기 게이트가 여전히 닫혀 있다고 말한다. 대신 승인하지 않는다.

## /gatekit:build

**언제**: `05-gate.md`가 승인된 뒤.

**전제 조건 2가지**: `spec validate`가 `fail`이 아닐 것, `approve check spec/05-gate.md`가 `ok`일 것. 그리고 기본 워커 백엔드가 실제로 있을 것. 워커 점검이 `fail`이면 멈추고 `/gatekit:setup`으로 보낸다. `unverified`는 차단 사유가 아니며 한 번 알리고 계속한다.

**읽는 것**: `jobs status`와 `jobs results --compact`의 표. `output.txt`와 `stderr.txt`는 워커 전사 전체라 절대 컨텍스트로 읽지 않는다. 특정 게이트 이름이 필요할 때만 그 태스크의 `gates.json`을 읽는다.

**쓰는 것**: 잡 디렉터리와 `spec/PROGRESS.md`. **이 커맨드는 소스 코드를 쓰지 않는다.** 워커가 쓴다.

**질문**: 없다.

**실패하면**: `failed`나 `timeout`인 태스크는 `jobs redelegate <task_id>`로 재위임한다. 종료 코드 3은 재시도 소진이다. 같은 태스크가 3회 실패하면 재위임을 멈추고 `spec/RECOVERY.md`에 진단을 쓴 뒤 파이프라인을 정지한다. 직접 고치지 않고, 다른 잡을 시작하지도 않는다.

## /gatekit:verify

**언제**: 모든 태스크가 `passed`인 뒤. 빌드 통과와 계약 통과는 다르다.

**핵심 원칙**: producer ≠ evaluator. 코드를 만든 세션은 채점하지 않는다. 읽고 실행할 수는 있지만 쓸 수 없는 별도 평가자 에이전트를 띄운다.

**읽는 것**: `.gatekit/contract.json`, `spec/05-gate.md`의 E2E 단계.

**쓰는 것**: `spec/PROGRESS.md`의 마지막 검증 절. 평가자에게 이 파일은 read-only의 유일한 예외다.

**질문**: 없다.

**절차**: 먼저 `contract derive`로 재파생한다. 그다음 평가자를 띄우는데, 그 프롬프트에는 `gatekit-scope` 펜스가 반드시 들어가야 한다. 평가자가 돌아오면 메인 세션이 `contract run --json`을 한 번 더 돌린다. 두 실행이 어긋나면 그 자체가 발견 사항이며, 더 나은 쪽을 고르지 않고 불일치를 보고한다.

**실패하면**: 집계가 `ok`가 아니면 무엇이 바뀌어야 하는지 나열하고 멈춘다. 여기서 코드를 고치지 않고 `/gatekit:build`로 되돌린다.

## /gatekit:doctor

**언제**: 설치 직후, 훅이 안 먹히는 것 같을 때, 상태가 의심스러울 때.

**읽는 것**: 플러그인 파일, `installed_plugins.json`, `settings.json`, `.gatekit/`, `spec/`, `contract.json`, 워커 바이너리, 파이썬 버전.

**쓰는 것**: 없다. 진단만 한다.

**질문**: 없다. 다만 처방을 실행하기 전에 물어본다. `05-gate.md`를 다시 쓰거나 승인을 기록하거나 unsafe 백엔드를 켜는 처방은 절대 대신 실행하지 않는다.

**주의**: 종료 코드 0은 "아무것도 실패하지 않았다"이지 "다 괜찮다"가 아니다. `unverified` 축이 있으면 "이상 없음"으로 요약하면 안 된다.

## /gatekit:setup

**언제**: 프로젝트에서 처음 gatekit을 쓸 때. Codex를 켜고 싶을 때.

**읽는 것**: `.gatekit/config.json`의 존재 여부, 워커 바이너리.

**쓰는 것**: `.gatekit/config.json`(없을 때만). 이미 있으면 건드리지 않고 그렇게 말한다. 파일을 손으로 쓰지 않고 CLI가 만들게 한다.

**질문**: 인자가 없으면 0회. `codex`일 때 활성화 여부 1회, 기본 백엔드로 삼을지 1회.

**Codex 활성화 전 설명 의무**: 무엇이 실행되는지(`codex exec --sandbox workspace-write`), 샌드박스가 켜진 채라는 것, gatekit이 bypass 플래그를 넘기지 않는다는 것, 활성화가 기본 지정과 별개라는 것, 되돌릴 수 있다는 것을 먼저 말한다. 답이 오기 전에는 아무것도 켜지 않는다.

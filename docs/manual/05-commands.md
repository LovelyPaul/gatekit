# 커맨드 레퍼런스

## 요약

| 커맨드 | 인자 | 산출물 | AskUserQuestion 횟수 |
|---|---|---|---|
| `/gatekit:discover` | 선택. 거친 아이디어나 빈 인자 | `spec/00-discovery.md` | 0 (평문 채팅, 개수 상한 없음) |
| `/gatekit:interview` | 만들려는 것에 대한 설명 | `spec/01-prd.md`, `spec/03-architecture.md` | 0 (평문 채팅, 개수 상한 없음) + 확인 1 |
| `/gatekit:mockup` | Figma URL, HTML 경로, 스크린샷 경로 | `spec/02-screens.md`, `spec/tokens.json`, 확정 프로토타입 | 최대 1 + 프로토타입 확정 (필수) |
| `/gatekit:design` | Figma URL, 스크린샷·HTML 경로, 라이브 사이트 URL, 프리셋 이름, 패턴 파일 | `spec/02-design.md`, `spec/tokens.json` | 최대 1 |
| `/gatekit:tasks` | 선택적 제약 (예: "round 1만") | `spec/04-tasks.md` | 0 |
| `/gatekit:gate` | 선택적 추가 기준 | `spec/05-gate.md`, `.gatekit/contract.json`, 승인 | 승인 1 (수정 시 반복) |
| `/gatekit:build` | 선택적 태스크 id 목록 | 잡 디렉터리, `spec/PROGRESS.md` | 0 |
| `/gatekit:verify` | 선택적 기준 id | 판정표, `spec/PROGRESS.md` | 0 |
| `/gatekit:doctor` | 선택적 `--json` | 진단 표 | 0 |
| `/gatekit:setup` | 선택적 `codex` | `.gatekit/config.json` | codex일 때만 최대 2 |

## /gatekit:discover

**언제**: 뭘 만들지 모를 때, 또는 "챗봇 같은 거"처럼 만들 것만 있고 실사용자와 불편이 없을 때. 선택 단계이며, 이 파일이 없어도 나머지 파이프라인은 그대로 돈다.

**읽는 것**: 정책 파일 2종(언어·질문), 언어별 `00-discovery.md` 템플릿, 이미 있으면 `spec/00-discovery.md`(이어서 대화를 계속한다).

**쓰는 것**: `spec/00-discovery.md` 하나. 발굴한 개선과제들과 각각의 `verdict_suggested`/`verdict`.

**질문**: 이름 붙은 게이트도, 진행률 표시도, 정해진 질문 개수도 없다. 하나의 자유로운 대화로 진행하며, 한 번에 질문 하나를 던지고 실제 답을 받을 때까지 기다린다(`policy/questioning.md`의 "ask one, then stop and wait"). 과거에 실제로 일어난 일만 묻고, 해법이나 추상어가 나오면 마지막 사건으로 되돌린다. 대화가 더 이상 새로운 것을 만들어내지 못하면 그렇게 말하고 계속할지 여기서 멈출지 직접 물은 뒤에만 요약으로 넘어간다 — 스스로 판단해서 넘어가지 않는다. 중단 신호("알아서 해줘")가 오면 지금까지 것으로 바로 요약한다.

**요약과 확정**: 대화가 끝나면 사후에 개선과제들을 요약하고(`insights_count`로 이 대화가 얼마나 실질적이었는지 정직하게 기록), 요약이 실제로 맞는지 사용자에게 직접 확인받는다. 하나를 고르면 모델이 `verdict_suggested`를 제안하고 사용자가 `verdict`를 확정한다. 확정된 verdict가 `eliminate`나 `reuse`면 `spec validate`가 `pain_verdict_blocks`를 내고 `/gatekit:interview` 진행을 막는다.

**다음**: `/gatekit:interview`가 `chosen: true`인 개선과제를 사실로 읽어 다시 확인하지 않고 그대로 이어받는다.

## /gatekit:interview

**언제**: 문제(또는 discovery가 고른 개선과제)는 정해졌지만 구현 형태(페이지·기능·데이터)가 아직 안 정해졌을 때. `spec/01`이 이미 있으면 개정 모드로 동작한다. 인자에 실사용자와 불편이 없으면 `/gatekit:discover`로 보낸다.

**읽는 것**: 정책 파일 3종, `heading-map.json`, 언어별 템플릿, 기존 `spec/`, `spec/00-discovery.md`(있으면 그 `chosen` 개선과제와 `notes`를 그대로 받아들인다), 레포의 언어·프레임워크·테스트 러너, `README*`·`package.json`·`pyproject.toml`·락파일·CI 설정.

**쓰는 것**: `spec/01-prd.md`, `spec/03-architecture.md`. 템플릿의 `{{...}}` 자리표시자를 하나도 남기지 않는다.

**질문 (Step 2)**: 페이지가 몇 개인지, 각 페이지에서 뭘 할 수 있는지, 각 기능이 뭘 필요로 하는지, 빈 목록·실패·경합 같은 갈라지는 경우를 정해진 개수 없이 하나씩 묻는다. 각 기능이 화면 동작으로 어떻게 옮겨지는지도 그 자리에서 바로 확인한다 — 나중에 몰아서 확인하지 않는다.

**리서치 (Step 2.5, ADR-0017 결정 24)**: 대화가 정리되면, 대화에서 나온 기능들을 먼저 변경 불가한 확정 목록(차별점)으로 고정한다. 그다음 이 제품이 속한 카테고리를 놓고 `WebSearch`로 네 방향(표준 기능, 사용자 불만/리뷰, 최신 사례, 기술적 실패담)을 조사해, 대화가 스스로 꺼내지 않은 카테고리 표준 기능을 찾아낸다. 2개 이상 독립 출처가 겹치는 것만 "기본기 후보"로, 나머지는 "참고 아이디어"로 분리해 사용자에게 제시하고, 사용자는 빼거나 고치는 식으로 반응한다(양식을 채우는 게 아니라 제안된 것을 쳐내는 방식). 채택된 항목마다 출처(리서치/사용자 경험)를 한 줄로 남긴다.

**확인 (Step 5)**: 대화로 나온 기능과 리서치로 추가된 기능을 하나의 목록으로 합쳐 보여주고, 이대로 만들 것인지 최종 확인을 받는다.

**실패하면**: `spec validate`가 `fail`이면 실패한 파일을 버리고 템플릿에서 다시 쓴다. 이해하지 못한 지적을 우회 수정하지 않는다. 3회 재작성에도 실패하면 멈추고 남은 지적을 정확히 보고한다.

## /gatekit:mockup

**언제**: 디자인 산출물이 있을 때, 또는 새로 디자인 방향을 정해야 할 때. 선택 단계지만, UI가 있는 프로젝트라면 이 안의 프로토타입 확정 없이는 `/gatekit:tasks`로 못 넘어간다.

**읽는 것**: Figma MCP 도구(`get_metadata`, `get_design_context`, `get_variable_defs`, `get_screenshot`), 또는 HTML 파일, 또는 이미지. 디자인 소스가 없으면 `plugin/spec-kit/presets/design/`의 프리셋 중 하나를 먼저 고르게 한다. 각 추출 항목은 근거(프레임 이름·파일 경로·셀렉터)를 함께 기록한다.

**쓰는 것**: `spec/02-screens.md`, `spec/tokens.json`, 정적 프리뷰(선택), 그리고 실제로 클릭 가능한 프로토타입 `spec/design/prototype-<name>.html`.

**프로토타입 게이트(ADR-0017 결정 4, 건너뛸 수 없음)**: `02-screens.md`가 정한 모든 화면·모든 상태를 실제로 눌러볼 수 있는 HTML/CSS로 만든다. 모든 기능을 그럴듯한 샘플 데이터로 채워서, 빈 폼이 아니라 완성된 제품의 실제 화면처럼 보이게 한다. 사용자가 열어보고 고칠 부분을 말하면 HTML과 `02-screens.md`를 같이 고치는 왕복을 반복한다. 확정 직전에 "이 프로토타입이 원하는 걸 충분히 담고 있는지, 빠진 기능이 있는지"를 명시적으로 물어 — 빠졌다고 답하면 `/gatekit:interview`로 돌아가 그 기능을 제대로 정의한 뒤 프로토타입을 다시 만든다. 사용자가 명시적으로 확정해야 `02-screens.md`에 `프로토타입 확정 <날짜>` 줄이 생기고, 이 줄이 없으면 `spec validate`가 `prototype_required`로 `/gatekit:tasks`를 막는다.

**실패하면**: Figma MCP 도구를 쓸 수 없으면 그 사실을 말하고 내보내기나 스크린샷을 요청한 뒤 멈춘다. URL만 보고 디자인을 추측하지 않는다.

**주의**: 목업은 정상·빈·오류·로딩 4개 상태를 거의 다 보여주지 않는다. 빠진 상태는 설계해서 쓰되 전부 가정으로 표시한다. `## 근거 없는 영역` 절이 비어 있으면 제대로 읽지 않은 것이다.

## /gatekit:design

**언제**: 목업이 아니라 화면을 가로지르는 디자인 패턴이나 레퍼런스 사이트가 입력일 때. 선택 단계이며, 파이프라인의 어느 단계에서든, `build` 도중에도 실행할 수 있다.

**읽는 것**: Figma MCP 도구, 스크린샷·HTML 파일, 라이브 사이트 URL(`WebFetch`로 먼저 읽고 클라이언트 렌더링 셸이면 Chrome 도구로 캡처), 프리셋 이름, 또는 사용자가 쓴 패턴 파일. 각 추출 항목은 근거(프레임 이름·파일 경로·프리셋 이름)를 함께 기록하고, URL 캡처는 모두 `spec/design/`에 저장한 뒤 그 파일을 근거로 인용한다.

**쓰는 것**: `spec/02-design.md`, `spec/tokens.json`(`/gatekit:mockup`과 공유, 있으면 병합), 그리고 `spec/01-prd.md`의 가정 원장에 gap 행 추가. 이미 두 파일이 있으면 개정 모드로 동작한다: 기존 `S<n>`·`P<n>` id는 그대로 두고 새 행만 추가하며, 새 출처가 기존 행과 모순되면 지우지 않고 가정 원장에 `supersedes A<n>: <출처>` 행을 덧붙인다.

**질문**: 최대 1회. 틀렸을 때 대가가 가장 큰 단일 gap에 대해서만 묻는다.

**실패하면**: `WebFetch`나 Chrome 도구를 쓸 수 없으면(Codex 등) 그 사실을 말하고 로컬 캡처를 요청한 뒤 멈춘다. URL만 보고 디자인을 추측하지 않는다. 스크린샷은 1MB를 넘으면 줄이거나 거절한다.

**주의**: `active_pipeline`이 `build`였다면 `04-tasks.md`나 `05-gate.md`를 직접 고치지 않고 `design impact`로 영향받는 작업 목록만 보고한다. 재위임은 `/gatekit:tasks`와 `/gatekit:gate`를 다시 거쳐야 하며, 그동안 계약은 stale이다.

## /gatekit:tasks

**언제**: `01-prd.md`가 있고 아직 작업 분해가 없을 때. `01-prd.md`가 없으면 멈추고 `/gatekit:interview`로 보낸다. UI가 있는 프로젝트라면 `02-screens.md`에 `프로토타입 확정 <날짜>` 줄이 없으면 `spec validate`가 `prototype_required`를 내며 멈춘다 — `/gatekit:mockup`에서 사용자가 실제로 프로토타입을 확정해야 한다.

**읽는 것**: `01`의 기능 `F<n>`과 수용 기준, `02`의 화면 `S<n>`, `03`의 스택과 제약, 그리고 실제 레포 구조(디렉터리, 테스트 명령, 파일 명명 규칙).

**쓰는 것**: `spec/04-tasks.md`. 각 작업은 `gatekit-task` 펜스 하나다. UI를 다루는 작업은 `spec/design/build-<task-id>.png` 스크린샷을 산출물로 요구하는 게이트를 함께 갖는다 — `verify`가 이 스크린샷을 읽고 디자인 안티패턴과 대조해 `-visual` 판정을 낸다.

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

**실패하면**: `failed`나 `timeout`인 태스크는 `jobs redelegate <task_id>`로 재위임한다. 재위임 전에 `gates.json`의 실패 출력을 읽고, 게이트 명령 자체가 틀렸으면(태스크가 만들 일 없는 경로를 가리키거나, 워커 코드와 무관하게 같은 식으로 실패하면) 먼저 `spec/04-tasks.md`를 고친다. `redelegate`는 그 파일을 다시 읽는다(ADR-0009). `blocked`인 태스크는 의존 태스크가 통과하지 못해 실행되지 않은 것이라 재위임 대상이 아니다. 잡을 중단해야 하면 `jobs stop`을 쓴다. 종료 코드 3은 재시도 소진이다. 같은 태스크가 3회 실패하면 재위임을 멈추고 `spec/RECOVERY.md`에 진단을 쓴 뒤 파이프라인을 정지한다. 직접 고치지 않고, 다른 잡을 시작하지도 않는다.

## /gatekit:verify

**언제**: 모든 태스크가 `passed`인 뒤. 빌드 통과와 계약 통과는 다르다.

**핵심 원칙**: producer ≠ evaluator. 코드를 만든 세션은 채점하지 않는다. 읽고 실행할 수는 있지만 쓸 수 없는 별도 평가자를 띄운다. 평가자는 `.gatekit/config.json`의 `verify.evaluator`로 정한다. `agent`(기본)면 호스트의 읽기 전용 서브에이전트이고, 백엔드 이름(`claude`, `codex`)이면 그 CLI가 `read_only_argv`로 실행된다. 즉 Claude Code로 만든 코드를 Codex가, Codex로 만든 코드를 Claude가 채점할 수 있다. `workers set-evaluator <이름>`으로 바꾼다.

**읽는 것**: `.gatekit/contract.json`, `spec/05-gate.md`의 E2E 단계.

**쓰는 것**: `spec/PROGRESS.md`의 마지막 검증 절. 평가자에게 이 파일은 read-only의 유일한 예외다.

**질문**: 없다.

**절차**: 먼저 `contract derive`로 재파생한다. 그다음 평가자를 띄운다. 서브에이전트면 그 프롬프트에 `gatekit-scope` 펜스가 반드시 들어가야 하고, 백엔드면 `jobs evaluate --prompt <파일>`이 읽기 전용 워커로 실행해 판정표를 출력한다. 평가자가 돌아오면 메인 세션이 `contract run --json`을 한 번 더 돌린다. 두 실행이 어긋나면 그 자체가 발견 사항이며, 더 나은 쪽을 고르지 않고 불일치를 보고한다.

**실패하면**: 집계가 `ok`가 아니면 무엇이 바뀌어야 하는지 나열하고 멈춘다. 여기서 코드를 고치지 않고 `/gatekit:build`로 되돌린다.

**`-visual` 판정(ADR-0017 결정 9, 22)**: 스크린샷을 산출물로 요구하는 기준이 `ok`로 통과하면, 평가자는 그 이미지를 실제로 읽고 디자인 방향과 안티패턴 목록(`plugin/spec-kit/design-antipatterns.json`)에 대조해 별도 판정(`<기준id>-visual`)을 낸다. **`contract run`의 집계는 코드 기준만 세므로 이 판정을 절대 포함하지 않는다** — 집계가 `ok`여도 `-visual` 판정 중 하나라도 `fail`이면 "계약을 통과했다"고 보고하지 않는다. `-visual` 판정은 다른 기준과 같은 무게로 보고에 각각의 행을 갖는다.

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

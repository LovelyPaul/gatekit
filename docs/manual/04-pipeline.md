# 파이프라인 전체 흐름

![gatekit 파이프라인](../assets/pipeline.svg)

## 전체 다이어그램

```text
                    [ /gatekit:doctor ]  ← 아무 때나. 설치·상태 8축 진단
                    [ /gatekit:setup  ]  ← 프로젝트 최초 1회. config·워커 점검
                              │
   한 문장 아이디어           ▼
        │            ┌──────────────────┐
        └───────────▶│ 1. interview     │──▶ spec/01-prd.md
                     │                  │    spec/03-architecture.md
   목업·스크린샷      └──────────────────┘
        │                     │
        │            ┌──────────────────┐
        └───────────▶│ 2. mockup (선택) │──▶ spec/02-screens.md
                     │                  │    spec/tokens.json
                     └──────────────────┘    01의 가정 원장에 gap 행 추가
                              │
                              ▼
                     ┌──────────────────┐
                     │ 3. tasks         │──▶ spec/04-tasks.md
                     └──────────────────┘    (gatekit-task 펜스)
                              │
                              ▼
                     ┌──────────────────┐
                     │ 4. gate          │──▶ spec/05-gate.md
                     │   ★ 사람 승인    │    .gatekit/contract.json
                     └──────────────────┘    .gatekit/approvals.json
                              │
              [쓰기 게이트가 여기서 열린다]
                              │
                              ▼
                     ┌──────────────────┐
                     │ 5. build         │──▶ .gatekit/jobs/<job_id>/
                     │   워커가 코드 작성│    spec/PROGRESS.md
                     └──────────────────┘
                              │
                              ▼
                     ┌──────────────────┐
                     │ 6. verify        │──▶ 독립 평가자 판정
                     │   producer≠evaluator│  spec/PROGRESS.md 마지막 검증
                     └──────────────────┘
                              │
                   [Stop 게이트가 계약을 실행]
```

## 단계별 입력·출력·게이트

| 단계 | 커맨드 | 입력 | 출력 | 관련 게이트 |
|---|---|---|---|---|
| 0 | `/gatekit:discover` | 아무것도 없어도 된다. 최근 2주의 불편 | `00-discovery.md` | `spec validate`가 심화 게이트 6개의 빈 칸을 `warn`으로 표시. 선택 단계 |
| 1 | `/gatekit:interview` | 사용자의 한 문장 설명, 기존 레포, 있으면 `00-discovery.md` | `01-prd.md`, `03-architecture.md` | question 게이트가 질문 2회로 예산 관리 |
| 2 | `/gatekit:mockup` | Figma URL, HTML, 스크린샷 | `02-screens.md`, `tokens.json`, 원장 gap 행 | question 게이트 |
| 3 | `/gatekit:tasks` | `01`, `02`, `03`, 실제 레포 구조 | `04-tasks.md` | 없음. 계획만 한다 |
| 4 | `/gatekit:gate` | `01`의 수용 기준, `04`의 작업 | `05-gate.md`, `contract.json`, 승인 | 승인이 쓰기 게이트를 연다 |
| 5 | `/gatekit:build` | `04-tasks.md`, 승인된 `05-gate.md` | 잡 디렉터리, `PROGRESS.md` | write 게이트가 `write_scope` 강제 |
| 6 | `/gatekit:verify` | `contract.json`, `05-gate.md` | 판정표, `PROGRESS.md` 마지막 검증 | spawn 게이트가 평가자 범위 검사, stop 게이트가 계약 실행 |

`doctor`와 `setup`은 이 순서에 속하지 않는다. `setup`은 프로젝트 최초 1회, `doctor`는 문제가 의심될 때 언제든 실행한다.

## 각 단계에서 무엇이 막히는가

### 1단계 이전

`spec/` 디렉터리가 아직 없으면 쓰기 게이트는 아무것도 막지 않는다. 규칙 (a)는 `spec/`이 존재할 때만 발동한다.

### 1~3단계 중

`spec/`이 생겼고 `05-gate.md`가 승인되지 않았으므로, 쓰기 게이트가 소스 파일 수정을 거부한다. `spec/**`, `.gatekit/**`, `docs/**`, `README*`, 루트의 `*.md`만 쓸 수 있다. 이 허용 목록이 없으면 게이트를 열어줄 스펙 자체를 쓸 수 없다.

### 4단계 승인 시점

사용자가 `05-gate.md`를 읽고 승인하면 해시가 고정된다. 그 순간부터 쓰기 게이트 규칙 (a)가 통과되어 소스 파일을 쓸 수 있다. 동시에 Stop 게이트가 이 계약을 실행 대상으로 삼는다.

### 5단계 중

워커 세션에는 `GATEKIT_TASK_ID`가 설정되어 있고, 쓰기 게이트 규칙 (b)가 발동한다. 규칙 (b)는 (a)보다 엄격해서 문서 허용 목록이 없다. `src/auth/**`를 배정받은 워커는 PRD를 고칠 수 없다.

### 6단계와 종료

`build`가 전부 `passed`여도 완료 계약 통과와는 다르다. `verify`만 그것을 보고한다. 세션을 끝내려 하면 Stop 게이트가 계약을 실행하고, `fail`이나 `unverified`가 있으면 최대 3회까지 종료를 막는다.

## 되돌아가는 경로

- `05-gate.md`를 고치면 승인이 만료되고 계약이 stale이 된다. `contract derive` 후 다시 승인해야 한다.
- 태스크가 3회 연속 실패하면 `build`는 재위임을 멈추고 `spec/RECOVERY.md`에 진단을 쓴 뒤 파이프라인을 정지한다. 코드를 직접 고치지 않는다.
- `verify`가 `ok`가 아니면 무엇이 바뀌어야 하는지 나열하고 멈춘다. 수정은 `/gatekit:build`로 되돌린다.

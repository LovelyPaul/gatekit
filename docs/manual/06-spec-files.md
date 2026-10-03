# 스펙 파일 형식

`spec/` 아래 문서들의 필수 H2 제목은 `plugin/spec-kit/heading-map.json`이 정한다. `spec validate`는 여기 나열된 제목이 전부 존재하는지, 그리고 다른 언어 제목이 섞이지 않았는지를 검사한다. 순서는 강제하지 않고 존재 여부만 본다. 아래 제목은 한국어(`ko`) 기준이며 영어(`en`) 세트도 따로 있다.

## 00-discovery.md (선택)

이름 붙은 게이트나 정해진 순서 없이, 하나의 자유로운 대화에서 발굴한 개선과제들을 사후에 요약한 것이다. 각 개선과제는 `summary`(해법을 빼고 문제나 원하는 것만 한 문장), `notes`(정형 필드에 안 들어가는 것 전부), 그리고 아는 만큼의 `user`/`current_way`/`frequency_per_month`/`minutes_per_run`/`why_chain`/`failed_attempts`를 담는다. 하나가 `chosen: true`가 되면 모델이 제안하는 `verdict_suggested`와 사용자가 확정하는 `verdict`(`build`/`reuse`/`eliminate`/`unknown`)를 갖는다.

확정된 `verdict`가 `eliminate`나 `reuse`면 `spec validate`가 `pain_verdict_blocks`를 내고 `/gatekit:interview`를 막는다. `unknown`은 절대 막지 않는다.

`insights_count`는 대화가 실제로 얼마나 실질적이었는지(다른 사실·분기 개수)를 정직하게 기록하는 값이다. 상한은 없고, 지나치게 낮으면 `spec validate`가 `warn`만 낸다.

## 01-prd.md (필수)

무엇을 왜 만드는지. 이 파일이 없으면 `spec validate`가 실패한다.

| 필수 제목 | 담는 것 |
|---|---|
| `## 문제` | 지금 무엇이 불편한가 |
| `## 현재 상태 (측정값)` | 측정한 값. 없으면 "측정 안 됨"이라 쓰고 원장에 올린다 |
| `## 목표` | 달성하려는 것 |
| `## 목표가 아닌 것` | 명시적으로 하지 않을 것 |
| `## 사용자` | 누가 쓰는가 |
| `## 기능` | `F<n>` id가 붙은 기능 목록 |
| `## 수용 기준` | 각 기능이 충족해야 할 조건 |
| `## 가정 원장` | 확인받지 않은 판단 전부 |

가정 원장은 표로 쓰고, `Blocking`/`Confirmed`(`y`/`n`) 두 컬럼을 끝에 더 갖는다. `Blocking: y`는 "이 행이 틀리면 전체 계획이 무너지는가"가 아니라 **"이 행이 틀리면 핵심 기능의 체감 품질이 직접 나빠지는가"**로 판단한다 — 계획은 살아남아도 기능 자체의 품질을 좌우하는 판단(친밀도 계산 방식처럼 기능의 존재 이유 자체)은 `Blocking: y`다. `Blocking: y`이면서 `Confirmed: n`인 행이 있으면 `spec validate`가 `fail`을 내고, `/gatekit:gate`가 이 행이 풀릴 때까지 진행을 거부한다. 본문에서 그 가정에 기댄 자리에는 같은 번호의 인라인 표기를 남긴다. 플레이그라운드 실제 예시다.

```markdown
| # | 가정 | 근거 | 틀렸을 때의 영향 | 확인 방법 | Blocking | Confirmed |
|---|---|---|---|---|---|---|
| 3 | 목록은 수정 시각 내림차순, 페이지 나눔 없음 | 목표 규모가 100개라 한 화면에 충분함 | 노트가 수백 개로 늘면 첫 화면이 느려짐 | 노트 수 상한을 사용자와 재확인 | n | n |
```

## 02-screens.md

`## 화면 목록` / `## 화면 흐름` / `## 화면별 상태` / `## 컴포넌트` / `## 디자인 토큰` / `## 근거 없는 영역`

화면마다 정상·빈·오류·로딩 4개 상태를 전부 쓴다. 목업에 없어서 설계한 상태는 가정으로 표시한다. `## 근거 없는 영역`은 목업이 다루지 **않은** 것을 쓴다. 오프라인, 권한, 긴 목록, 긴 문자열, 오류 복구, 최초 실행 등을 찾아본다.

`## 근거 없는 영역` 다음에, 사용자가 실제 클릭 가능한 프로토타입을 확정하면 `프로토타입 확정 <날짜>`(영어는 `Prototype confirmed <date>`) 줄이 추가된다. UI가 있는 프로젝트에서 이 줄이 없으면 `spec validate`가 `prototype_required`를 내고 `/gatekit:tasks`가 진행을 거부한다.

## 02-design.md (선택)

`## 소스` / `## 디자인 패턴` / `## 컴포넌트` / `## 디자인 토큰` / `## 다루지 않은 것`

`/gatekit:mockup`이 화면 단위 정보를 담는 것과 달리, 이 파일은 화면을 가로지르는 디자인 패턴(`P<n>`)과 컴포넌트의 시각 사양을 담는다. `spec/tokens.json`을 `mockup`과 공유하며 병합한다.

## 03-architecture.md

`## 스택` / `## 데이터 모델` / `## 식별자와 토큰` / `## 외부 연동` / `## 제약`

`04-tasks.md`의 게이트 명령과 `write_scope`가 여기 적힌 스택·경로와 맞아야 한다.

## 04-tasks.md

`## 작업 목록` / `## 실행 순서` / `## 범위 규칙`

작업은 `gatekit-task` 펜스 하나에 JSON 객체 하나로 쓴다.

### gatekit-task 스키마

| 필드 | 타입 | 규칙 |
|---|---|---|
| `id` | 문자열 | 파일 안에서 고유 |
| `title` | 문자열 | 사람이 읽는 제목 |
| `write_scope` | 글로브 리스트 또는 `"read-only"` | 비어 있을 수 없다 |
| `instruction` | 문자열 | 자기 완결적. 워커는 이 문자열과 범위만 본다 |
| `gates` | 객체 리스트 | 최소 1개. 각각 `name`과 `argv` |
| `depends_on` | id 리스트 | 모든 id가 이 파일에 존재해야 한다 |
| `round` | 정수 | 같은 라운드의 작업끼리 `write_scope`가 겹칠 수 없다 |

```json
{"id": "task-db-schema",
 "title": "Note 저장소(db.py) 생성과 기본 CRUD",
 "write_scope": ["db.py", "tests/test_db.py"],
 "instruction": "표준 라이브러리 sqlite3만 사용해 db.py에 NoteStore 클래스를 만든다. ...",
 "gates": [{"name": "test", "argv": ["python3", "-m", "unittest", "tests.test_db", "-v"]}],
 "depends_on": [],
 "round": 1}
```

`instruction`은 짧으면 안 된다. 워커는 이 대화를 보지 못한다. 플레이그라운드의 실제 `instruction`은 스키마·메서드 시그니처·검증 규칙·테스트 항목까지 한 문단에 다 담고 있다.

## 05-gate.md (필수)

`## 완료 기준` / `## 완료로 보지 않는 조건` / `## 증거 수집 방법`

기준은 `gatekit-criterion` 펜스 하나에 JSON 객체 하나다.

### gatekit-criterion 스키마

| 필드 | 타입 | 규칙 |
|---|---|---|
| `id` | 문자열 | 고유. 검증하는 작업 id를 포함시키면 추적성 경고가 사라진다 |
| `argv` | 문자열 리스트 | 비어 있지 않음. 셸 없이 실행되므로 `&&`·파이프·리다이렉션 불가 |
| `expect` | 객체 | `exit`(정수, 기본 0) 외에 `stdout_contains` / `stdout_not_contains` / `stderr_contains` / `stderr_not_contains`(문자열 또는 문자열 리스트, 전부 성립해야 함), `stdout_regex` / `stderr_regex`(패턴 하나). 출력 검사는 저장된 꼬리가 아니라 전체 스트림에 대해 한다. 모르는 키·잘못된 타입·잘못된 정규식은 `derive` 오류이자 `validate` `fail` |
| `timeout_s` | 숫자 | 이 기준의 상한 |
| `artifacts` | 상대 경로 리스트 | 실행 후 존재해야 한다. 없으면 `fail` |
| `tier` | `"turn"` 또는 `"verify"` | 선택, 기본 `"turn"`(ADR-0024). `turn`은 빌드를 판정하는 동안 Stop 게이트가 매 턴 끝에 실행하고, `verify`는 `/gatekit:verify`·`contract run`·`contract baseline`에서만 실행한다. 다른 값은 `derive` 오류이자 `validate` `fail` |

```json
{"id": "task-note-search-works",
 "argv": ["python3", "-m", "unittest", "tests.test_notes_search", "-v"],
 "expect": {"exit": 0},
 "timeout_s": 45,
 "artifacts": []}
```

"skip 없음"을 산문이 아니라 기준으로 만들려면 출력 기대를 쓴다.

```json
{"id": "task-note-search-no-skips",
 "argv": ["python3", "-m", "unittest", "tests.test_notes_search", "-v"],
 "expect": {"exit": 0, "stdout_not_contains": ["skipped", "SKIP"], "stderr_not_contains": ["skipped"]},
 "timeout_s": 45}
```

`artifacts` 경로는 상대 경로여야 하고 `..`를 포함할 수 없으며, `realpath` 해석 후에도 프로젝트 루트 안에 있어야 한다. 심볼릭 링크로 탈출하면 `fail`이다.

### gatekit-budget 스키마

전체 실행 예산이다. `05-gate.md`에 **최대 하나만** 둘 수 있다.

| 필드 | 타입 | 규칙 |
|---|---|---|
| `total_budget_s` | 숫자 | 기본 45, 상한 600 |

```json
{"total_budget_s": 180}
```

없거나, 숫자가 아니거나, 0이거나, 음수이거나, 두 개 이상이거나, 600을 넘으면 `derive` 오류다. 상한이 있는 이유는 Stop 게이트가 이것을 실행하기 때문이다. 사용자의 인내심보다 오래 걸리는 검사는 `unverified`를 보고하고 물러나는 검사보다 나쁘다.

측정 먼저, 선언은 나중이다. 들여다보지 않은 느린 테스트를 감추려고 예산을 올리면 안 된다.

### 완료로 보지 않는 조건

이 절이 이 파일의 핵심이다. 그럴듯해 보이는 통과를 무효로 만드는 조건을 쓴다. 최소한 다음을 포함한다.

- 테스트를 건너뛰거나 비활성화하거나 좁혀서 통과시킨 경우
- 기준이 시간 초과된 경우 — `unverified`이며 통과가 아니다
- 명령은 0으로 끝났는데 선언한 산출물이 없는 경우
- TODO·스텁·빈 구현이 남은 경우
- 이 파일을 고쳐서 실패하는 기준을 삭제한 경우
- 실제로 실행해보지 않고 성공을 보고한 경우

여기에 `03-architecture.md`의 제약에서 나온 프로젝트별 조건을 더한다.

### 스크린샷 기준과 `-visual` 판정

UI를 다루는 작업의 기준은 `spec/design/build-<task-id>.png`를 `artifacts`로 요구한다(Playwright 등으로 캡처, `argv`가 subprocess로 직접 실행). 이 기준이 `ok`면 `verify`의 평가자가 그 이미지를 실제로 읽고, 기록된 디자인 방향 및 `design-antipatterns.json`과 대조해 별도 판정 `<기준id>-visual`을 낸다. **이 판정은 `contract run`의 집계에 포함되지 않는다** — 집계는 코드 기준(exit code, 산출물 존재)만 세기 때문이다. 집계가 `ok`여도 `-visual` 판정 중 `fail`이 있으면 완료로 보고하지 않는다.

## RECOVERY.md

`## 진단 루프` / `## 재시도 한도` / `## 범위 잠금` / `## 롤백 절차`

`build`가 같은 태스크에서 3회 실패하면 이 파일을 읽고, 태스크 이름을 제목으로 삼아 진단을 여기 쓴다.

## PROGRESS.md

`## 현재 상태` / `## 마일스톤` / `## 실패한 시도` / `## 마지막 검증`

`build`와 `verify`가 쓴다. 템플릿의 제목을 그대로 유지해야 한다. `spec validate`는 다른 언어의 제목이 섞이는 것을 교차 언어 잔재로 보고 실패시킨다. `verify`의 평가자는 `## 마지막 검증` 아래에만 쓴다.

## tokens.json

`mockup`과 `design` 둘 다 만들거나 병합하는 선택 산출물이다. 종류별로 묶은 기계 판독 값이다.

```json
{"version": 1, "source": "mockup.html",
 "color": {"accent": "#0E5C55", "danger": "#B3382C"},
 "space": {"md": "12px", "lg": "16px"}}
```

`design`이 쓰면 v2로, 화면을 가로지르는 패턴을 함께 담는다.

```json
{"version": 2, "source": ["mockup.html", "preset:shadcn-neutral"],
 "patterns": [{"id": "P1", "rule": "카드는 그림자 없이 1px 테두리만 쓴다", "applies_to": ["all"], "evidence": "preset:shadcn-neutral"}],
 "color": {"accent": "#0E5C55"}, "space": {"md": "12px"}}
```

토큰 이름은 식별자다. 디자인 시스템이 쓰는 철자를 그대로 둔다. 값을 지어내느니 그룹 전체를 빼는 편이 낫다. 두 커맨드 모두 기존 파일이 있으면 덮어쓰지 않고 병합한다.

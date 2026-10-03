# 문제 해결

## 먼저 — 차단은 대부분 고장이 아니다

gatekit을 쓰다 보면 **막히는 일이 자주 생긴다.** 그게 이 도구의 목적이다. 그래서 문제를 찾기 전에 먼저 구분할 게 있다.

| 이런 건 정상이다 (의도된 차단) | 이건 고장이다 |
|---|---|
| 소스 파일을 못 쓴다 → 아직 `/gatekit:gate` 승인 전 | 훅이 **하나도** 발화하지 않는다 |
| `/gatekit:tasks`가 거부한다 → 프로토타입 미확정 | `/gatekit:doctor`의 2번 항목이 `fail` |
| 세션을 못 끝낸다 → 완료 조건에 `fail`/`unverified`가 있다 | CLI가 `ModuleNotFoundError`로 죽는다 |
| 판정이 `unverified`다 → 검사를 **못 한** 것이지 틀린 게 아니다 | 훅 오류 로그에 예외가 쌓인다 |

의도된 차단은 **메시지에 무엇이 빠졌는지와 다음에 뭘 하면 되는지가 함께 나온다.** 메시지 없이 그냥 안 되는 경우가 진짜 문제다.

막혔을 때 가장 먼저 할 일은 `/gatekit:doctor`다. 어느 항목이 `fail`인지 보면 위 두 열 중 어느 쪽인지 바로 갈린다.

## 증상 → 원인 → 처방

| 증상 | 원인 | 처방 |
|---|---|---|
| 훅이 전혀 안 먹힘 | 플러그인이 설치되지 않았거나 `settings.json`의 `enabledPlugins`에서 비활성 | `/gatekit:doctor` 2번 축 확인 후 `/plugin install gatekit` 또는 `/plugin enable gatekit@gatekit`. 그다음 Claude Code 재시작 |
| 설치했는데 여전히 안 먹힘 | 현재 세션이 구 버전을 로드한 상태 | Claude Code 재시작 |
| 소스 파일 수정이 차단됨 | `spec/05-gate.md`가 승인되지 않음 (`unverified`) 또는 승인 만료 (`fail`) | `/gatekit:gate` 실행 후 사용자가 승인. 급하면 `spec/`·`docs/`·루트 `*.md`에 먼저 쓴다 |
| 스펙 검증 실패 — 제목 누락 | 템플릿의 H2 제목을 지우거나 바꿈 | `heading-map.json`의 해당 언어 제목을 그대로 복원. 06번 문서에 전체 목록이 있다 |
| 스펙 검증 실패 — 다른 언어 제목 혼입 | 한 파일에 `## 목표`와 `## Goals`가 섞임 | 한 언어로 통일. 특히 `PROGRESS.md`에 프리핸드 제목을 쓸 때 자주 생긴다. 템플릿에서 복사한다 |
| 스펙 검증 실패 — 가정 원장 번호 불일치 | 인라인 표시 번호와 원장 행 번호가 안 맞음 | 인라인에 있고 행이 없으면 `fail`이니 행을 추가. 행만 있고 인라인이 없으면 `warn` |
| 계약이 stale | `05-gate.md`가 파생 이후 변경됨, 또는 디자인 입력(`02-screens.md`, `02-design.md`, `tokens.json`)이 바뀜 — `contract status`가 바뀐 파일명을 알려준다 | `/gatekit:tasks` 후 `/gatekit:gate` 재실행 (디자인이 바뀐 경우), 또는 `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract derive` 재실행 (05만 바뀐 경우). 승인도 만료됐으면 다시 승인 |
| `approve check`가 `fail` | 승인 후 파일이 바뀜 | 사용자가 다시 읽고 다시 승인. 해시를 맞추려고 파일을 되돌리면 안 된다 |
| `approve check`가 `unverified` | 승인 기록 자체가 없음 | `/gatekit:gate`를 처음부터 실행 |
| `approve check`가 `fail`이고 stderr에 `grading files changed` | 승인한 기준의 테스트 파일이 바뀐 채 다시 derive됨 (`grading_unapproved`) | 의도한 변경이면 `/gatekit:gate`로 재승인, 아니면 테스트 변경을 되돌린다 (ADR-0023) |
| 워커 없음 (`workers check`가 `fail`) | 기본 백엔드 바이너리가 PATH에 없음 | 해당 CLI 설치, 또는 `workers set-default <name>`으로 다른 백엔드 지정 |
| codex가 비활성 | 기본값이 `"enabled": false` | `/gatekit:setup codex` 실행. 설명을 읽고 확인해야 켜진다 |
| `workers enable`이 거부됨 | argv에 샌드박스 bypass 플래그가 있는데 `"unsafe": true`가 없음 | gatekit은 사용자를 대신해 `unsafe`를 설정하지 않는다. bypass 없는 백엔드를 쓴다 |
| 태스크 write_scope 충돌 | 같은 라운드의 두 태스크가 같은 파일을 씀 | 라운드를 나누거나 파일 경계가 다르게 태스크를 다시 자른다. **범위를 넓히지 않는다** |
| 워커 안에서 쓰기가 거부됨 | 그 태스크의 `write_scope` 밖 경로 | `04-tasks.md`의 분해가 잘못된 신호다. 태스크를 다시 자른다 |
| 전체 예산 초과로 `unverified` | 기준 합계가 45초 기본 예산보다 큼 | 실측한 뒤 `gatekit-budget` 펜스로 `total_budget_s` 선언 (상한 600). 측정 없이 올리지 않는다 |
| 정지 게이트가 반복 차단 | 계약에 `fail`이나 `unverified` 기준이 있음 | 메시지에 나온 기준의 원인을 고친다. 3회 차단 후에는 자동으로 물러나지만 판정은 실패로 기록된다 |
| 한국어로 물었는데 영어로 출력됨 | 프롬프트의 한글 비율이 30% 미만이거나 원장에 `en`이 저장됨 | 한국어 문장으로 다시 프롬프트를 보낸다. `lang` 서브커맨드로 감지 결과를 직접 확인할 수 있다 |
| CLI 실행 시 `ModuleNotFoundError: gatekit` | 모듈 실행 형식을 썼고, 프로젝트 디렉터리에서는 패키지가 `sys.path`에 없음 | 런처 형식 `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" <sub>` 을 쓴다 |
| spawn이 거부됨 | 프롬프트에 `gatekit-scope` 펜스가 없거나 JSON이 잘못됨 | 펜스를 추가한다. `write_scope`와 `stop_when`은 필수다 |
| spawn 범위 충돌 | 이미 활성인 에이전트의 범위와 겹침 | 범위를 좁히거나 그 에이전트가 끝날 때까지 기다린다. 메시지에 소유자 이름이 나온다 |
| 빌드는 통과했는데 완료가 아니라고 함 | 빌드 통과와 계약 통과는 다름 | `/gatekit:verify`가 계약을 판정한다 |

## 훅 오류 로그 위치

```text
.gatekit/runs/hook-errors.log
```

훅 내부에서 예외가 나면 여기에 한 줄이 추가된다.

```text
<iso 타임스탬프> <이벤트 이름> <오류>
```

훅은 이런 상황에서도 exit 0으로 끝나고 동작을 허용한다. 그래서 "게이트가 이상하게 통과시킨다" 싶으면 이 파일을 먼저 본다. 파일이 비어 있거나 없으면 훅은 정상 동작한 것이다.

## 세션 원장 직접 보기

게이트들이 무엇을 기록했는지 확인할 때 쓴다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" ledger show --session <session_id>
```

출력에서 확인할 것들이다.

- `output_lang` — 감지된 언어가 기대와 다른가
- `active_pipeline` — Stop 게이트가 계약을 실행하려면 `build`나 `verify`여야 한다
- `questions.asked` / `budget_exceeded` — 인터뷰가 질문을 몇 번 했는가
- `scopes` — 어떤 에이전트가 어떤 범위를 잡고 있는가
- `stop.block_count` / `final_verdict` — 몇 번 차단됐고 최종 판정이 무엇인가
- `stop.stood_down` — Stop 게이트가 끝난 잡의 판정을 기록하고 물러났는가(ADR-0024). 값이 있으면 이후 턴 끝에서는 계약을 실행하지 않는다. `skipped`는 판정 없이 넘긴 턴 끝 수다. 다시 확인하려면 `/gatekit:verify`
- `stop.deferred` — 마지막 판정에서 미룬 기준(`tier`: verify 등급, `budget`: `stop.budget_s` 소진)

## 잡 상태 직접 보기

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs results --compact
```

특정 게이트의 실패 이유가 필요하면 그 태스크의 `gates.json`만 읽는다.

```text
.gatekit/jobs/<job_id>/tasks/<task_id>/gates.json
```

`output.txt`와 `stderr.txt`는 워커 전사 전체다. 컨텍스트로 읽지 않는다.

## 잡 디렉터리 정리

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs clean        # 최근 잡만 남김
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs clean --all  # 전부 삭제
```

## 진단이 막힐 때 순서

1. `/gatekit:doctor` — 8축 중 무엇이 `fail`인가
2. `.gatekit/runs/hook-errors.log` — 훅이 조용히 죽고 있는가
3. `spec validate --json` — 어떤 파일의 어떤 지적인가
4. `contract status` — `ok` / `fail`(stale) / `unverified`(없음)
5. `approve check spec/05-gate.md` — 승인이 살아 있는가
6. `jobs results --compact` — 어떤 태스크가 어디서 멈췄는가

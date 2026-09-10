# 실전 예제 — Quicknote

실제로 완주한 실행 기록이다. 한 문장 아이디어에서 시작해 8개 태스크와 8개 기준을 거쳐 완료 계약 `ok`까지 갔다. 여기 나오는 수치는 전부 `.gatekit/` 실제 상태 파일에서 가져온 것이다.

## 출발점

사용자는 짧은 메모를 여러 텍스트 파일에 흩어 적어두고, 지난주 회의 메모를 찾는 데 20분이 걸렸다고 말했다.

## 1단계 — interview

```bash
/gatekit:interview 메모를 적고 나중에 빨리 찾을 수 있는 개인용 노트 앱
```

`spec/01-prd.md`와 `spec/03-architecture.md`가 나왔다. 측정하지 못한 값은 지어내지 않고 "미측정"으로 표에 넣고 가정 원장 1번 행에 올렸다.

```markdown
| 지표 | 현재 값 | 출처 | 측정일 |
|---|---|---|---|
| 지난주 회의 메모를 찾는 데 걸린 시간 | 20분 | 사용자 진술(사례 1건) | 2026-09-10 |
| 흩어져 있는 메모 파일 수 | 미측정 | — | 2026-09-10 |
```

가정 원장에는 6개 행이 들어갔다. 제목 길이 상한, 목록 정렬 방식, 삭제 복구 없음, 검색 방식, DB 파일 위치 등 사용자가 말하지 않은 판단이 전부 기록됐다.

## 2단계 — mockup

```bash
/gatekit:mockup mockup.html
```

`mockup.html`에서 화면과 CSS 커스텀 속성을 추출해 `spec/02-screens.md`와 `spec/tokens.json`을 만들었다. 토큰은 목업이 실제로 쓴 값 그대로다.

```json
{"version": 1, "source": "mockup.html",
 "color": {"accent": "#0E5C55", "danger": "#B3382C"}}
```

## 3단계 — tasks

```bash
/gatekit:tasks
```

`spec/04-tasks.md`에 태스크 8개가 나왔다. 전부 수직 슬라이스이고, 각각 게이트를 1개씩 갖는다.

| 태스크 id | 라운드 | write_scope |
|---|---|---|
| `task-db-schema` | 1 | `db.py`, `tests/test_db.py` |
| `task-note-create` | 2 | `app.py`, `tests/test_notes_create.py` |
| `task-note-list` | 3 | `app.py`, `tests/test_notes_list.py` |
| `task-note-update` | 4 | `app.py`, `tests/test_notes_update.py` |
| `task-note-delete` | 5 | `app.py`, `tests/test_notes_delete.py` |
| `task-note-search` | 6 | `app.py`, `tests/test_notes_search.py` |
| `task-static-frontend` | 7 | `static/`, `tests/test_static.py` |
| `task-full-suite-gate` | 8 | 전체 스위트 확인 |

`app.py`를 여러 태스크가 건드리므로 라운드를 다르게 배정했다. 범위를 넓혀 충돌을 없애는 대신 순차화한 것이다.

## 4단계 — gate

```bash
/gatekit:gate
```

`spec/05-gate.md`에 기준 8개가 나왔다. 태스크 8개와 1:1로 대응하도록 id에 태스크 id를 넣었다. `## 완료로 보지 않는 조건`에는 일반 조항 6개에 더해 프로젝트별 조항이 들어갔다. 표준 라이브러리 밖 패키지를 import한 경우, 서버가 `127.0.0.1` 밖에 바인딩된 경우, 검색 성능 기준을 실측 없이 통과 보고한 경우 등이다.

승인 후 계약이 파생됐다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract derive
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve spec/05-gate.md
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve check spec/05-gate.md
```

## 5단계 — build

```bash
/gatekit:build
```

잡 `20260910T060008Z-b1dc`가 시작됐다. 백엔드 `claude`, 병렬 3, 태스크 타임아웃 900초, 최대 재시도 2회.

### 게이트가 잡은 것 — 워커는 exit 0이었다

`task-note-delete`의 첫 시도에서 워커는 **종료 코드 0으로 성공을 보고**했다. 그런데 게이트가 테스트를 실행하자 실패했다.

```text
File "tests/test_notes_delete.py", line 148
    </content>
    ^
SyntaxError: invalid syntax
```

워커가 테스트 파일 끝에 `</content>` 문자열을 남겼다. 파이썬 파일이 아예 import되지 않는 상태였다. 워커의 자기 보고만 믿었다면 이 태스크는 통과로 기록됐을 것이다.

같은 파일이 깨져 있었으므로 `task-full-suite-gate`의 `python3 -m unittest discover`도 함께 실패했다. 67개 테스트를 돌리고 수집 오류 1건으로 exit 1이었다.

잡 상태에는 이렇게 남았다.

```json
{"state": "failed", "exit": 0, "gates_verdict": "fail",
 "gates_passed": 0, "gates_total": 1,
 "detail": "worker exited 0 but gates verdict is fail (0/1 ok)"}
```

### 재위임

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs redelegate task-note-delete
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" jobs redelegate task-full-suite-gate
```

이전 시도는 `attempt-1/`로 보관되고, 실패한 게이트의 출력이 프롬프트에 덧붙어 다시 실행됐다. 두 태스크 모두 재위임 2회차에서 통과했다. `task-full-suite-gate`의 최종 상태는 73개 테스트 전부 OK, 게이트 1/1이다.

최종 결과는 8/8 `passed`다.

## 6단계 — verify와 예산 문제

```bash
/gatekit:verify
```

독립 평가자가 계약을 실행했다. 집계 판정은 `ok`가 아니라 **`unverified`**였다. 기준 8개 중 6개가 `ok`, 2개가 타임아웃으로 `unverified`였다.

| 기준 | 판정 | 실측 | 당시 예산 |
|---|---|---|---|
| `task-note-update-works` | `unverified` | 6.61~6.65초 (3회 측정) | 5초 |
| `task-full-suite-gate-works` | `unverified` | 24.5초 | 10초 |

중요한 점은 이것이 **구현 결함이 아니었다**는 것이다. 두 테스트 모두 손으로 돌리면 통과했다. 예산이 실측보다 작았을 뿐이다. 그런데 gatekit은 이것을 통과로 반올림하지 않았다. 검사가 끝나지 못했으므로 `unverified`다.

평가자는 E2E 단계도 손으로 전부 실행했다. 임시 DB와 포트로 서버를 띄우고 실제 HTTP 요청을 보냈다.

```bash
QUICKNOTE_DB=/tmp/e2e_notes.db QUICKNOTE_PORT=8099 python3 app.py
```

10개 E2E 단계가 전부 `ok`였다. 노트 101건을 API로 시드한 뒤 측정한 검색 왕복 시간은 0.0115초로, 수용 기준 1초를 충족했다.

## 7단계 — 예산 상향과 재승인

실측값을 근거로 개별 `timeout_s`를 15초·45초로 올리고, 전체 예산을 `gatekit-budget` 펜스로 선언했다.

```json
{"total_budget_s": 180}
```

전체 스위트 실측 49초에 여유를 둔 값이다. 추측이 아니라 측정 후 선언이다.

`05-gate.md`를 고쳤으므로 승인이 만료되고 계약이 stale이 됐다. 다시 파생하고 다시 승인했다.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract derive
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" approve spec/05-gate.md --note "budget fence added after measuring 49s total"
python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" contract run --json
```

이번에는 8/8 `ok`, 총 소요 49.4초였다.

## 최종 상태

| 항목 | 값 |
|---|---|
| 태스크 | 8/8 `passed` |
| 완료 계약 기준 | 8/8 `ok` |
| 재위임된 태스크 | 2개 (`task-note-delete`, `task-full-suite-gate`) |
| 선언 예산 | 180초 |
| 실측 총 소요 | 49.4초 |
| 가장 긴 기준 | 24.5초 |

## 이 실행이 보여준 것

1. **워커의 exit 0은 근거가 아니다.** SyntaxError가 남은 파일을 두고 워커는 성공을 보고했다. 게이트가 잡았다.
2. **`unverified`가 통과로 반올림되지 않았다.** 두 기준이 실제로는 통과 가능했지만 예산 안에서 확인되지 않았다. 도구는 그 사실을 그대로 보고했다.
3. **예산은 측정 후에 선언했다.** 느린 테스트를 감추려고 올린 것이 아니라 실측 49초를 근거로 180초를 선언했다.
4. **파일을 고치자 승인이 만료됐다.** 게이트 파일 수정은 자동으로 재승인을 요구했다.
5. **평가자가 만든 쪽이 아니었다.** E2E 10단계를 별도 read-only 에이전트가 실제 서버에 대고 손으로 실행했다.

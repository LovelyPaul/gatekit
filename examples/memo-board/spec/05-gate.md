---
title: "메모 보드 — 완료 게이트"
date: "2026-10-03"
status: "확정"
---

# 메모 보드 — 완료 게이트

이 파일은 "끝났다"의 정의다. 사람이 승인하면 해시가 고정되고, Stop 훅이
여기 적힌 `turn` 등급 명령을 실제로 실행해 판정한다. `verify` 등급은 `/gatekit:verify`에서만 돈다.

## 완료 기준

빠른 정적 검사 → 단위 → 여정 → 스크린샷 순(느린 것을 뒤에). 전체 E2E 스위트는 `verify` 등급.

```gatekit-criterion
{"id": "server-syntax",
 "tier": "turn",
 "argv": ["node", "--check", "server.js"],
 "expect": {"exit": 0},
 "timeout_s": 10}
```

```gatekit-criterion
{"id": "unit-all",
 "tier": "turn",
 "argv": ["node", "--test", "tests/*.test.js"],
 "expect": {"exit": 0, "stdout_not_contains": ["# skipped 1", "# todo 1"]},
 "timeout_s": 30}
```

```gatekit-criterion
{"id": "journey-task-add-note-task-delete-note-task-note-count",
 "tier": "turn",
 "argv": ["npx", "playwright", "test", "e2e/journey.spec.ts", "--project", "mobile"],
 "expect": {"exit": 0, "stdout_not_contains": ["skipped"]},
 "timeout_s": 60}
```

```gatekit-criterion
{"id": "screenshots",
 "tier": "turn",
 "argv": ["npx", "playwright", "test", "e2e/screenshots.spec.ts", "--project", "mobile"],
 "expect": {"exit": 0},
 "timeout_s": 60,
 "artifacts": ["spec/design/build-task-add-note.png", "spec/design/build-task-delete-note.png", "spec/design/build-task-note-count.png"]}
```

```gatekit-criterion
{"id": "e2e-suite",
 "tier": "verify",
 "argv": ["npx", "playwright", "test", "--project", "mobile"],
 "expect": {"exit": 0, "stdout_not_contains": ["skipped"]},
 "timeout_s": 120}
```

필드 규칙은 템플릿과 같다. `e2e-suite`는 task-add-note, task-delete-note, task-note-count의
작업별 E2E(add/delete/count)와 여정·스크린샷 스펙을 한 번에 다시 돌리는 회귀 스위트다.

## 완료로 보지 않는 조건

- 테스트를 건너뛰거나(`skip`, `only`) 비활성화해서 통과시킨 경우
- 기준 명령이 시간 초과된 경우 — `unverified`이며 통과로 반올림하지 않는다
- 산출물 파일(`spec/design/build-*.png`)이 없는데 명령만 0으로 끝난 경우
- 구현 없이 TODO·스텁·빈 함수만 남긴 경우
- `05-gate.md`나 채점 파일(`e2e/journey.spec.ts`, `e2e/screenshots.spec.ts`, `playwright.config.ts`)을 고쳐서 기준을 약하게 만든 경우
- 사람이 직접 실행해보지 않은 채 "동작한다"고 보고한 경우

## 증거 수집 방법

| 기준 | 실행 방법 | 남는 증거 |
|---|---|---|
| server-syntax | `gatekit contract run` | 종료 코드 |
| unit-all | `gatekit contract run` | 종료 코드, TAP 요약 |
| journey-… | `gatekit contract run` | 종료 코드, Playwright 요약 |
| screenshots | `gatekit contract run` | `spec/design/build-task-*.png` 3장 |
| e2e-suite | `/gatekit:verify` (tier verify) | 종료 코드, Playwright 요약 |

승인 절차: 이 문서를 사람이 읽고 동의하면 `gatekit approve spec/05-gate.md`를 실행한다.

## 실행 예산 (선택)

```gatekit-budget
{"total_budget_s": 300}
```

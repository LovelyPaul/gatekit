---
title: "메모 보드 — 아키텍처"
date: "2026-10-03"
status: "확정"
---

# 메모 보드 — 아키텍처

## 스택

| 층 | 선택 | 이유 | 대안과 기각 사유 |
|---|---|---|---|
| 런타임 | Node 24 (`node:http`, 의존성 없음) | 정적 파일만 내보내면 된다 | Express — 의존성이 필요 없음 |
| 프레임워크 | 없음 — 순수 HTML + ES 모듈 JS | 화면 하나, 빌드 단계 불필요 | React/Vite — 리허설 규모에 과함 |
| 저장소 | 브라우저 localStorage, 키 `memo-board.notes` | 가정 1 | 서버 DB — 목표가 아닌 것 |
| 테스트 | 단위 `node --test`, E2E Playwright 1.63 (`playwright.config.ts`, 프로젝트 `mobile` 하나, 360×740) | 이미 설치되어 있음 | Jest — 추가 의존성 |

서버: `server.js`가 `node:http`로 프로젝트 루트의 정적 파일을 내보낸다. 포트는 환경변수
`PORT`, 없으면 **4183**. `/`는 `index.html`. `.js`는 `text/javascript`, `.css`는 `text/css`,
`.html`은 `text/html; charset=utf-8`. 없는 파일은 404. 루트 밖 경로(`..`)는 403.

Playwright 설정(`playwright.config.ts`, 게이트 단계에서 이미 작성됨, 수정 금지):
`webServer: { command: "node server.js", port: 4183, reuseExistingServer: true }`,
`use.baseURL = "http://localhost:4183"`, 프로젝트 `mobile` 하나.

## 데이터 모델

### Note

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| id | string | 예 | `Date.now().toString(36)` + 난수 접미사 |
| text | string | 예 | 앞뒤 공백을 제거한 메모 글, 빈 문자열 불가 |

관계: 없음. 저장 형태는 `Note[]`를 JSON으로 직렬화해 localStorage `memo-board.notes`에 둔다.

## 식별자와 토큰

| 종류 | 규칙 | 예시 |
|---|---|---|
| 파일·디렉터리 | kebab-case | `delete-ui.js` |
| 타입·클래스 | PascalCase | `Note` |
| 함수·변수 | camelCase | `addNote`, `removeNote`, `countNotes` |
| 환경변수 | SCREAMING_SNAKE | `PORT` |
| API 경로 | 없음 (정적 파일만) | — |

모듈 구성 — 각 작업이 자기 파일만 쓴다:

- `notes.js` (task-add-note): 순수 함수 `addNote(notes, text)` → 새 배열 (공백만이면 원본 그대로 반환).
- `remove.js` (task-delete-note): 순수 함수 `removeNote(notes, id)` → 새 배열.
- `count.js` (task-note-count): 순수 함수 `countNotes(notes)` → 정수.
- `app.js` (task-add-note): 화면 상태·렌더·저장. 렌더 후 확장 모듈 `./delete-ui.js`, `./count-ui.js`를
  `import()`로 불러 `install(board)`를 호출한다 (없으면 조용히 건너뜀).
  `board = { getNotes(), setNotes(notes) /* 저장+재렌더 */, onRender(fn) /* 매 렌더 후 fn(root) */, root }`.
- `delete-ui.js` (task-delete-note), `count-ui.js` (task-note-count): `export function install(board)`.

`data-testid`는 02-screens.md S1에 적힌 이름 그대로 쓴다.

## 외부 연동

| 서비스 | 용도 | 인증 방식 | 실패 시 동작 |
|---|---|---|---|
| 없음 | — | — | — |

## 제약

- 의존성 추가 금지 (`@playwright/test`만 devDependency로 이미 있음).
- 모든 모듈은 브라우저와 Node 양쪽에서 import 가능한 ES 모듈 (`.js`, `package.json`에 `"type": "module"`).

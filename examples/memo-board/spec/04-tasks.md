---
title: "메모 보드 — 작업 목록"
date: "2026-10-03"
status: "확정"
---

# 메모 보드 — 작업 목록

각 작업은 아래 형식의 `gatekit-task` 블록 하나로 표현한다.

## 작업 목록

```gatekit-task
{"id": "task-add-note",
 "title": "F1 메모 추가 — 서버, 화면 뼈대, 추가 기능",
 "write_scope": ["server.js", "index.html", "style.css", "app.js", "notes.js", "tests/notes.test.js", "e2e/add.spec.ts"],
 "instruction": "메모 보드의 뼈대와 F1(메모 추가)을 만든다. (1) server.js: node:http 정적 서버, 프로젝트 루트의 파일을 내보냄, 포트 process.env.PORT || 4183, '/'는 index.html, .html/.js/.css 콘텐츠 타입, 없는 파일 404, '..' 경로 403. ES 모듈(package.json type=module). (2) index.html: lang=ko, <h1>메모 보드</h1>, <p data-testid=\"note-count\"></p> 자리(내용은 task-note-count가 채움), 입력창 data-testid=note-input(placeholder '메모를 입력하세요') + 버튼 data-testid=add-note('추가'), <ul data-testid=note-list>, 빈 상태 <p data-testid=empty-state>메모가 없습니다</p>, 오류 상태 <p data-testid=error-state hidden>저장된 메모를 읽지 못했습니다</p>, <script type=module src=/app.js>. style.css는 #2563eb 강조색, 16px 간격, 360px 폭에서 깨지지 않게. (3) notes.js: export function addNote(notes, text) — text.trim()이 비면 원본 배열 그대로 반환, 아니면 {id, text: trimmed}를 끝에 붙인 새 배열 반환(원본 불변). id는 Date.now().toString(36)+난수. (4) app.js: localStorage 'memo-board.notes'에서 Note[] 로드(깨졌으면 [] + error-state 표시), 렌더(li data-testid=note-item data-id=<note.id> 안에 span data-testid=note-text와 버튼 data-testid=delete-note '삭제' — 삭제 동작은 붙이지 않음, task-delete-note가 붙임), 0개면 empty-state 표시. 추가 버튼/Enter로 addNote 후 저장·재렌더·입력창 비우기. board = {getNotes, setNotes(notes) 저장+재렌더, onRender(fn) 매 렌더 후 fn(root) 호출(등록 즉시 한 번 호출), root}를 만들고 ['./delete-ui.js','./count-ui.js'] 각각 import(m).then(x => x.install(board)).catch(() => {}). (5) tests/notes.test.js: node:test로 addNote의 추가·trim·공백 거부·원본 불변 검사. (6) e2e/add.spec.ts: '/' 열고 localStorage 비운 뒤 '장보기' 입력·추가 → note-item 1개, note-text '장보기'; 새로고침 후에도 1개; 공백만 추가하면 변화 없음. playwright.config.ts는 이미 있으니 수정하지 않는다. 두 게이트가 통과하면 끝.",
 "gates": [
   {"name": "unit", "argv": ["node", "--test", "tests/notes.test.js"]},
   {"name": "e2e", "argv": ["npx", "playwright", "test", "e2e/add.spec.ts", "--project", "mobile"]}
 ],
 "depends_on": [],
 "round": 1}
```

```gatekit-task
{"id": "task-delete-note",
 "title": "F2 메모 삭제",
 "write_scope": ["remove.js", "delete-ui.js", "tests/remove.test.js", "e2e/delete.spec.ts"],
 "instruction": "F2(메모 삭제)를 만든다. app.js·index.html은 task-add-note 소유이므로 고치지 않는다. (1) remove.js: export function removeNote(notes, id) — 그 id만 뺀 새 배열 반환(원본 불변, 없는 id면 같은 내용의 새 배열). (2) delete-ui.js: export function install(board) — root(문서)에서 data-testid=note-list에 click 위임 리스너를 한 번 등록; 눌린 버튼이 data-testid=delete-note면 가장 가까운 li[data-testid=note-item]의 data-id(app.js가 li에 data-id를 넣는다; 없으면 목록 내 순서로 board.getNotes()에서 찾음)로 board.setNotes(removeNote(board.getNotes(), id)). (3) tests/remove.test.js: node:test로 removeNote의 제거·원본 불변·없는 id 검사. (4) e2e/delete.spec.ts: localStorage 비운 뒤 '하나','둘' 추가 → 첫 항목 삭제 → note-item 1개, note-text '둘'; 새로고침 후에도 1개. 두 게이트가 통과하면 끝.",
 "gates": [
   {"name": "unit", "argv": ["node", "--test", "tests/remove.test.js"]},
   {"name": "e2e", "argv": ["npx", "playwright", "test", "e2e/delete.spec.ts", "--project", "mobile"]}
 ],
 "depends_on": ["task-add-note"],
 "round": 2}
```

```gatekit-task
{"id": "task-note-count",
 "title": "F3 메모 개수 표시",
 "write_scope": ["count.js", "count-ui.js", "tests/count.test.js", "e2e/count.spec.ts"],
 "instruction": "F3(메모 개수 표시)를 만든다. app.js·index.html은 task-add-note 소유이므로 고치지 않는다. (1) count.js: export function countNotes(notes) — 배열 길이(배열이 아니면 0). (2) count-ui.js: export function install(board) — board.onRender(root => { root의 [data-testid=note-count] 텍스트를 `메모 ${countNotes(board.getNotes())}개`로 }). (3) tests/count.test.js: node:test로 0개·2개·배열 아님 검사. (4) e2e/count.spec.ts: localStorage 비우면 '메모 0개'; 두 개 추가하면 '메모 2개'. 삭제 동작에 기대지 않는다(task-delete-note와 같은 라운드). 두 게이트가 통과하면 끝.",
 "gates": [
   {"name": "unit", "argv": ["node", "--test", "tests/count.test.js"]},
   {"name": "e2e", "argv": ["npx", "playwright", "test", "e2e/count.spec.ts", "--project", "mobile"]}
 ],
 "depends_on": ["task-add-note"],
 "round": 2}
```

## 실행 순서

| 라운드 | 작업 | 병렬 가능 이유 |
|---|---|---|
| 1 | task-add-note | 서버·화면 뼈대·확장 지점을 만든다 |
| 2 | task-delete-note, task-note-count | 둘 다 task-add-note의 확장 지점에만 붙고 파일이 겹치지 않음 |

## 범위 규칙

- 같은 라운드의 두 작업은 `write_scope`가 겹칠 수 없다.
- 워커는 자기 `write_scope` 밖을 쓸 수 없다.
- 범위를 넓혀야 하면 작업을 다시 나눈다.

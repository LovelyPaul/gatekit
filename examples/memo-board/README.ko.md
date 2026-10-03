# 예제: 메모 보드

[English](README.md)

360px 모바일 화면용 메모 보드입니다. 작업은 세 개(메모 추가, 메모 삭제, 메모 개수 표시)이고
메모는 `localStorage`에 남습니다. 0.16.0 리허설에서 실제로 헤드리스 `/gatekit:build`를
돌려 나온 결과물을 스펙과 함께 옮겨 왔습니다. 작은 프로젝트 하나가 끝까지 갔을 때 gatekit의
입력과 출력이 어떤 모습인지 보고, 직접 파이프라인을 돌려 볼 수 있습니다.

## 리허설에서 잰 값

| 단계 | 결과 |
|---|---|
| `/gatekit:build` (host 실행, 의존 순서대로 작업 3개) | 123초, 세 작업 모두 첫 시도에 `passed` |
| 빌드 뒤 후속 턴 | 턴마다 6–24초. 끝난 빌드를 판정한 뒤 Stop 게이트가 물러나서 매 턴 계약을 다시 돌리지 않음 |
| `/gatekit:verify` | 132초, 계약 5/5 `ok` |

검증 때 시각 판정 `warn` 3건도 나왔고, 그대로 두었습니다. 제목이 `메모 보드 v2`인데
(물러난 Stop 게이트를 확인하려고 후속 턴에서 바꿈) `spec/02-screens.md`에는 `메모 보드`로
적혀 있고, 모든 글자가 한 글꼴이며, 화면 아래쪽이 비어 있습니다. `warn`은 통과로도 실패로도
반올림하지 않고 그대로 보고합니다. 캡처는 [`screenshots/`](screenshots/)에 있습니다.

## 들어 있는 것

| 경로 | 내용 |
|---|---|
| `spec/01-prd.md` … `spec/05-gate.md`, `spec/RECOVERY.md` | 리허설에서 승인된 스펙 세트(`RECOVERY.md`는 초안 그대로): 가정 원장이 있는 PRD, 화면, 아키텍처, `gatekit-task` 펜스 3개, 완료 계약 |
| `index.html`, `style.css`, `app.js`, `server.js` | 화면과 `node:http` 정적 서버(포트 **4183**) |
| `notes.js`, `remove.js`, `count.js` | 작업마다 하나씩, 단위 테스트가 붙은 순수 함수 |
| `delete-ui.js`, `count-ui.js` | 삭제·개수 기능. 다른 작업이 소유한 파일을 고치지 않고 화면에 붙음 |
| `tests/` | `node:test` 단위 테스트 |
| `e2e/` | Playwright 스펙: 작업별 하나, 세 작업을 잇는 여정 하나, 스크린샷 기준 하나 |
| `package.json`, `package-lock.json`, `playwright.config.ts` | 의존성은 `@playwright/test` 하나 |
| `screenshots/` | 리허설 검증에서 찍은 캡처 3장. 리허설의 스크린샷 스펙이 두 작업에 같은 마지막 화면을 찍어서 메모 추가와 메모 개수 캡처가 똑같습니다(이 예제 스펙의 알려진 결함) |

`.gatekit/` 디렉터리는 없습니다. 승인은 내 사본 파일의 해시이므로 직접 기록해야 합니다.
`spec/PROGRESS.md`도 뺐습니다. 빌드가 새로 씁니다.

## 해 보기

Node.js 22 이상(`unit-all` 기준이 `tests/*.test.js`를 펼치지 않은 채 `node --test`에 넘기므로 그 glob 지원이 필요), Claude Code에 설치한 gatekit(Codex라면 `/gatekit:<이름>` 대신
`$gatekit-<이름>`), Playwright Chromium이 필요합니다.

1. **폴더를 이 저장소 밖으로 복사합니다.** gatekit은 가장 가까운 `.gatekit/`이나 `.git/`으로
   프로젝트를 찾기 때문에, 이 체크아웃 안에서는 gatekit 저장소 전체를 프로젝트로 봅니다.

   ```bash
   cp -R examples/memo-board ~/memo-board
   cd ~/memo-board
   git init
   npm install
   npx playwright install chromium
   ```

2. **계약을 승인합니다.** 호스트에서 프로젝트를 열고 `/gatekit:gate`를 실행합니다. PRD와
   작업에서 기준을 뽑아 하나씩 실제로 돌려 보고 보여 준 뒤, 승인하면 `spec/05-gate.md`의
   해시를 고정합니다. 그전까지는 쓰기 게이트가 코드 변경을 막습니다.

3. **빌드합니다.** `/gatekit:build`를 실행합니다. 소스가 이미 있으므로 세 작업이 바로 게이트를
   통과할 것입니다. 처음부터 만드는 과정을 보고 싶다면 먼저 소스와 테스트를 지우고 `spec/`,
   `package.json`, `package-lock.json`, `playwright.config.ts`만 남깁니다(첫 작업의 지시에
   Playwright 설정은 이미 있다고 적혀 있습니다).

   ```bash
   rm -f index.html style.css app.js server.js notes.js remove.js count.js \
         delete-ui.js count-ui.js tests/*.js e2e/add.spec.ts e2e/delete.spec.ts e2e/count.spec.ts
   ```

   `e2e/journey.spec.ts`와 `e2e/screenshots.spec.ts`는 계약이 이름으로 가리키는 채점
   파일이므로 남겨 둡니다.

4. **검증합니다.** `/gatekit:verify`로 전체 E2E 스위트를 포함한 독립 검증을 돌립니다.

포트 4183은 `playwright.config.ts`에 고정돼 있습니다. 다른 프로세스가 쓰고 있다면 설정을
고치지 말고(채점 파일입니다) 그 프로세스를 멈추세요. `/gatekit:doctor`가 빌드 전에 포트
충돌을 알려 줍니다.

## 기준 등급

`spec/05-gate.md`의 기준 다섯 개는 언제 도는지에 따라 나뉩니다.

| 기준 | 등급 | 도는 때 |
|---|---|---|
| `server-syntax` (`node --check server.js`) | `turn` | Stop 게이트, 매 턴 끝 |
| `unit-all` (`node --test tests/*.test.js`) | `turn` | Stop 게이트, 매 턴 끝 |
| `journey-…` (세 작업을 잇는 Playwright 여정) | `turn` | Stop 게이트, 매 턴 끝 |
| `screenshots` (`spec/design/build-task-*.png` 생성) | `turn` | Stop 게이트, 매 턴 끝 |
| `e2e-suite` (모든 Playwright 스펙) | `verify` | `/gatekit:verify`에서만 |

`turn` 기준은 `/gatekit:build` 중 매 턴 끝에 판정할 만큼 빠릅니다. 빌드가 끝나 판정을 받으면
Stop 게이트가 물러나므로 위의 후속 턴이 몇 분이 아니라 몇 초 만에 끝났습니다.
`/gatekit:verify`는 모든 등급을 돌립니다. 전체 스위트는 작업 게이트가 이미 돌린 것을 반복하므로
verify까지 기다립니다.

`gatekit-budget` 펜스는 계약 한 번 실행을 300초로 제한합니다. build 중에는 Stop 게이트가
`stop.budget_s`(기본 120초) 안에서 시작하며, 들어가지 못한 기준은 "미룸"으로 표시되어 다음
Stop이나 verify에서 판정됩니다. `ok`로 세지 않습니다.

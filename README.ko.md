# gatekit

상태: 0.16.3 — 초기 단계. 라이선스: MIT.

> **이름이 바뀔 예정입니다.** gatekit은 이번 스터디가 끝나면 **gatebound**로
> 이름이 바뀝니다. 그때까지는 달라지는 것이 없습니다. 지금 설치,
> `/gatekit:` 명령어, 프로젝트의 `spec/`과 `.gatekit/`은 그대로 동작합니다.
> 저장소는 이미 [gatebound/gatebound](https://github.com/gatebound/gatebound)로
> 옮겼고, 예전 주소 `LovelyPaul/gatekit`은 이곳으로 자동 연결됩니다.
> 옮기는 방법은 이름 변경과 함께 안내합니다.

gatekit은 [Claude Code](https://claude.com/claude-code)에서 AI 보조 개발을
게이트(hook)로 강제하는 하네스입니다. `CLAUDE.md`나 슬래시 커맨드에 적어두는
프롬프트 지침을, 실제로 매번 실행되는 훅으로 바꿔줍니다.

## 왜 필요한가

프롬프트 지침은 비결정적으로 발화됩니다. "테스트부터 작성하라"거나
"`src/`를 건드리기 전에 승인을 받으라"는 `CLAUDE.md`의 문장은, 그 턴에서
모델이 얼마나 주의를 기울였는지에만 의존합니다. gatekit은 중요한 부분을
훅이 강제하는 형태로 옮깁니다.

- **게이트는 훅이지 프롬프트가 아닙니다.** `PreToolUse`, `PostToolUse`,
  `Stop`, `UserPromptSubmit` 훅이 구조화된 상태를 읽고 동작합니다. 모델이
  기억해서 따라야 하는 지침이 아닙니다.
- **가정 원장(Assumption Ledger).** 모든 스펙은 사용자를 대신해 내린
  가정을 명시적으로 기록합니다. 아무것도 조용히 결정되지 않습니다.
- **해시 고정 승인.** 스펙 파일을 승인하면 그 시점의 SHA-256 해시가
  기록됩니다. 이후 파일이 바뀌면 승인은 즉시 stale 상태가 되고, 누군가
  재검토를 기억해야 할 필요가 없습니다.
- **실행 가능한 완료 계약.** "완료"는 명령어 목록(`gatekit-criterion`
  블록)입니다. exit 0이고 기대한 산출물을 만들어내거나, 그렇지 않거나
  둘 중 하나입니다. 자기 신고로 완료를 주장할 수 없습니다.
- **4단계 판정.** 모든 검사는 `ok`, `warn`, `fail`, `unverified` 중
  하나를 보고합니다. `unverified`("확인 안 됨")는 절대 통과나 실패로
  반올림되지 않습니다. 검사를 못 했다면 못 했다고 있는 그대로 말합니다.
- **워커는 모델이 달라야 할 때만.** 기본적으로는 빌드를 실행하는 세션이
  작업을 직접 구현합니다. 워커는 같은 모델의 새 세션이라, 이미 맥락을
  가진 모델에게서 "두 번째 의견"을 얻으려고 작업마다 프로젝트를 처음부터
  다시 파악하는 비용을 치릅니다. 모델이 실제로 달라야 하거나(적대적 검증,
  Codex 호스트가 Claude에 위임) 병렬성이 값을 할 만큼 작업이 많을 때만
  띄웁니다. 기본 백엔드는 Claude CLI이고 Codex는 선택입니다.

## 요구 사항

- **유료 플랜의 Claude Code** — Claude Code는 무료 플랜에 포함되지 않습니다.
  또는 Codex 앱·CLI([Codex](#codex-앱과-cli) 참고).
- **Python 3.9 이상**, `python3`·`python`·`py -3` 중 하나로 실행되면
  됩니다 — 훅이 이 순서로 차례대로 시도합니다. 그 외에 필요한 것은
  없습니다 — gatekit은 표준 라이브러리만 쓰고 `pip install` 단계가 없습니다.
- **Windows (미리보기).** 같은 릴리스에서 네이티브 Windows를 지원하지만,
  아직 실제 세션을 끝까지 돌려본 사용자가 없습니다. CI는 `windows-latest`에서
  파이썬 코드가 도는 것까지만 증명하고, 호스트가 훅을 실제로 부르는지는
  증명하지 못합니다. Claude Code에서는 Git for Windows를 설치하십시오
  (그러면 Claude Code가 Git Bash로 훅을 실행합니다). WSL에서도 리눅스와
  똑같이 동작합니다. 실제 Windows 사용 보고를 환영합니다.

## 설치

```
/plugin marketplace add https://github.com/LovelyPaul/gatekit
/plugin install gatekit@gatekit
```

설치 후 Claude Code를 재시작해야 `plugin/hooks/hooks.json`의 훅이
반영됩니다.

**Claude 데스크톱 앱.** 앱에서도 플러그인이 동작하고, 훅도 CLI와 똑같이
실행됩니다. **+ → Plugins → Add plugin**을 눌러 마켓플레이스
`https://github.com/LovelyPaul/gatekit`를 추가하고 `gatekit`을 설치한 뒤,
*자기 프로젝트 폴더*를 여십시오. 터미널에서 사용자 범위로 설치한 플러그인은
앱에서도 그대로 보이고, 그 반대도 같습니다. gatekit 저장소 자체를 앱의
프로젝트로 여는 것은 설치가 아닙니다 — 모델이 커맨드 파일을 읽을 수는 있지만
훅이 등록되지 않아 게이트가 하나도 돌지 않습니다.

플러그인은 전역으로 설치되므로 훅은 여는 모든 프로젝트에서 로드됩니다.
다만 `.gatekit/` 디렉터리가 없는 프로젝트에서는 게이트가 물러납니다 —
아무것도 막지 않고 상태 파일도 만들지 않습니다. 그 프로젝트에서 `/gatekit:`
커맨드를 처음 실행하는 순간부터 gatekit이 관여합니다.

### Codex (앱과 CLI)

Codex도 같은 마켓플레이스에서 같은 플러그인을 설치합니다.

```
codex plugin marketplace add LovelyPaul/gatekit
codex plugin add gatekit@gatekit
```

스킬은 `$gatekit-discover`, `$gatekit-interview` 등으로 나타납니다
(`gatekit:gatekit-<이름>`으로 표시). **플러그인 훅을 신뢰하기 전까지 게이트는
돌지 않습니다.** 그리고 Codex 데스크톱 앱은 지금 그 신뢰를 기록하지 못합니다
(openai/codex#47283). 터미널을 한 번 열어 `codex`를 실행하고 `/hooks`에서
gatekit 훅을 검토·신뢰한 뒤, 앱이나 CLI에서 새 세션을 시작하십시오. 신뢰는
훅 내용 단위라서 gatekit을 업그레이드할 때마다 다시 해야 합니다. 그 전까지는
`$gatekit-doctor`가 플러그인 훅을 `warn`으로 알려줍니다.

예전 방식(생성된 호스트 층)으로 설정한 프로젝트는 그대로 동작합니다.

```
git clone https://github.com/LovelyPaul/gatekit
python3 "gatekit/plugin/bin/gatekit.py" install --host codex
```

`.codex/hooks.json`, 커맨드별 스킬 `.agents/skills/gatekit-*`, `AGENTS.md`의
관리 블록을 씁니다. Codex가 물으면 프로젝트의 `.codex/` 층을 신뢰하십시오.

### 호스트 동등성

| | Claude Code | Codex CLI |
|---|---|---|
| 커널 CLI, 템플릿, `spec validate`, 계약 | ok | ok |
| write 게이트 (스펙 우선, 태스크 범위) | ok | ok — 관측: `apply_patch`가 패치 본문과 함께 별도 이벤트로 도착해 승인 전 거부됨 |
| bash 게이트 | ok | ok — 관측: code-mode `exec`가 셸 명령 하나당 `Bash` 이벤트로 풀려서 전달됨 |
| stop 게이트 (세션 종료 시 계약 실행) | ok | ok — Codex Stop 형식 |
| prompt 게이트 (`active_pipeline`, 언어) | ok | ok — `$gatekit-<name>` 호출 인식 |
| spawn 게이트 (서브에이전트 범위 펜스) | ok | warn — `collaborationspawn_agent`는 프롬프트를 훅에 숨겨 펜스를 검사할 수 없음. 서브에이전트의 쓰기는 write·bash 게이트를 그대로 거침(관측됨) |
| question 게이트 (질문 예산) | ok | n/a — Codex에 `AskUserQuestion` 없음, 질문은 평문이라 세지 않음 |
| compact 게이트 (압축 직전 빌드 상태 기록) | ok | 설치 안 됨 — Codex에 `PreCompact` 상당 이벤트가 알려져 있지 않아 레이어는 훅 7개가 아니라 6개를 설치함. 빌드 상태 자체는 잡 디렉터리와 `spec/PROGRESS.md`에 그대로 남고, 서사 기록만 빠짐 |
| 커맨드의 `AskUserQuestion` | 기본 선택 UI | 평문 번호 선택지 |
| `/gatekit:design` 라이브 사이트 분기 (`WebFetch`, Chrome 도구) | ok | unverified — 실제 Codex 세션에서 아직 관측되지 않음. 이 경우 커맨드는 URL로 추측하지 않고 로컬 캡처를 요청함 |
| `/gatekit:interview` 도메인 리서치 (`WebSearch`) | ok | warn — 관측: `WebSearch`가 없자 Codex가 서브에이전트를 띄워 기억에서 "조사"하는 식으로 우회함. 이제 스킬이 그럴 때 없다고 말하고 사용자에게 묻도록 지시함 — 출처 없는 제안은 이 단계의 존재 이유를 무너뜨림 |
| 빌드 워커를 다른 CLI로 | ok (`codex`) | ok (`claude`) |
| 평가자를 다른 CLI로 | ok (`workers set-evaluator codex`) | ok (`workers set-evaluator claude`) |

`unverified`는 말 그대로 실제 세션에서 아직 관측하지 못했다는 뜻입니다.
관측 보고를 환영합니다. Antigravity는 이번 릴리스에서 지원하지 않습니다.

워커나 평가자로 다른 CLI를 쓰려면 그 CLI가 설치되어 있고 자기 구독으로
로그인돼 있어야 합니다. gatekit은 CLI를 실행할 뿐 API 키를 갖지 않습니다.

## 세 가지 흐름

gatekit은 아이디어에서 검증된 변경까지 가는 세 가지 경로를 중심으로
구성됩니다.

1. **발굴/인터뷰 → 스펙.** 아직 무엇을 만들지 모른다면
   `/gatekit:discover`가 정해진 질문 목록 없이 자유롭게 대화하며 풀
   만한 문제를 찾아 정리합니다. 이어서 `/gatekit:interview`가 구현
   형태 — 화면, 동작, 데이터 — 를 깊이 파고들고, 알려진 제품
   카테고리라면 실시간으로 조사해서(네 방향 검색, 복수 출처 교차
   확인) 대화에서 한 번도 나오지 않은 표준 기능까지 제안합니다.
   사용자가 직접 말한 차별점과는 분리해서 보여주므로, 빈 양식을
   채우는 대신 제안된 목록을 쳐내는 방식으로 진행됩니다. 결과로
   가정 원장을 포함한 `spec/00-discovery.md`, `spec/01-prd.md`,
   `spec/03-architecture.md`가 나옵니다.
2. **목업 또는 디자인 → 스펙.** 시각적 목업이나 기존 화면에서 시작하면,
   gatekit이 `spec/02-screens.md`와 `spec/tokens.json`을 도출합니다.
   추측이 필요한 부분은 조용히 채우지 않고 원장에 갭 항목으로 기록합니다.
   `/gatekit:design`은 목업이 다루지 않는 디자인 입력을 처리합니다 —
   화면을 가로지르는 디자인 패턴이나 레퍼런스 사이트(Figma, 라이브
   URL, 스크린샷, HTML, 프리셋, 또는 직접 쓴 패턴 파일)입니다.
   `spec/02-design.md`를 쓰고 같은 `spec/tokens.json`에 병합하며,
   빌드 도중을 포함해 파이프라인 어느 단계에서든 실행할 수 있습니다.
3. **빌드 → 검증.** 스펙이 승인되면 gatekit이 이를 작업으로 쪼개고
   완료 계약을 도출한 뒤, 선언된 쓰기 범위 안에서 워커에게 작업을
   맡깁니다. 이후 독립적으로 검증합니다 — 무언가를 만든 에이전트가
   그것을 승인하는 에이전트가 되는 일은 없습니다.

## 커맨드

| 커맨드 | 산출물 |
|---|---|
| `/gatekit:discover` | `spec/00-discovery.md` — 아직 뭘 만들지 모르는 사용자를 위한 발굴 단계 |
| `/gatekit:interview` | `spec/01-prd.md`, `spec/03-architecture.md` |
| `/gatekit:mockup` | `spec/02-screens.md`, `spec/tokens.json`, 원장 갭 항목 |
| `/gatekit:design` | `spec/02-design.md`, `spec/tokens.json`, 원장 갭 항목 |
| `/gatekit:tasks` | `spec/04-tasks.md` |
| `/gatekit:gate` | `spec/05-gate.md`, `.gatekit/contract.json`, 승인 기록 |
| `/gatekit:build` | `spec/04-tasks.md` 기준 잡 실행: 기본은 이 세션이 태스크를 구현, 요청 시 워커. 판정은 게이트가 |
| `/gatekit:verify` | 완료 계약 기준 독립 종단 간(E2E) 검증 |
| `/gatekit:doctor` | 설치 상태 8축 진단 리포트 |
| `/gatekit:setup` | 선택적 Codex 백엔드, 기타 설정 |

## `spec/` 구조

기획 단계에서 gatekit이 만드는 모든 것은 사람이 검토하는 평범한
Markdown/JSON이며, 커밋되는 것을 전제로 합니다.

```
spec/
├── 01-prd.md            # 가정 원장 포함
├── 02-screens.md
├── 02-design.md         # 선택적 — 패턴, 컴포넌트, 토큰 요약
├── 03-architecture.md
├── 04-tasks.md          # gatekit-task JSON 블록으로 표현된 작업들
├── 05-gate.md           # gatekit-criterion JSON 블록으로 표현된 완료 기준
├── RECOVERY.md
├── PROGRESS.md
├── tokens.json          # 목업 또는 디자인 흐름에서 나온 선택적 산출물
└── design/              # 선택적 — 02-design.md가 근거로 인용하는 캡처
```

## 상태 저장 구조

런타임 상태는 프로젝트 안 `.gatekit/`에 저장됩니다. `config.json`과
`approvals.json`은 커밋 대상이고, `runs/`와 `jobs/` 아래는 세션별
상태로 gitignore 처리됩니다.

```
.gatekit/
├── config.json          # 커밋 대상
├── approvals.json        # 커밋 대상 — 해시 고정 승인
├── contract.json         # spec/05-gate.md에서 도출
├── runs/<session_id>.json   # gitignore — 세션 원장
├── runs/hook-errors.log     # gitignore
└── jobs/<job_id>/           # gitignore — 워커 작업 상태
```

## 설정

`.gatekit/config.json`은 스펙 승인 없이는 코드 변경을 막을지
(`enforce_spec_before_code`, 기본값 켜짐), 빌드가 어떤 워커 백엔드를
쓸지, 재시도/병렬 처리 한도, 인터뷰 질문 예산, 그리고 `stop.budget_s` —
빌드 중 턴이 끝날 때 Stop 훅이 완료 기준을 새로 시작하는 시간(기본 120초,
나머지는 다음 턴 끝에 먼저 실행하며 그때까지 그 턴은 `ok`가 아니라
`unverified`)을 제어합니다. 전체
스키마와 기본값은 `docs/ARCHITECTURE.md` §9를 참고하세요.

## 보안 태세

- 워커 샌드박스는 **기본적으로 켜져** 있으며 조용히 꺼지지 않습니다.
  샌드박스를 우회하는 백엔드는 설정 항목에 `"unsafe": true`를 명시적으로
  선언해야 하고, 이는 작업 결과 기록에 남습니다.
- 훅은 내부 오류로 세션을 막지 않습니다. 게이트 스크립트가 깨지면
  "허용하고 로그를 남기는" 쪽으로 안전하게 저하되며, 세션이 멈추지
  않습니다.
- 목업, 스크린샷, 웹에서 가져온 콘텐츠는 항상 데이터로 취급되며,
  따라야 할 지시로 취급되지 않습니다.
- 전체 위협 모델과 취약점 제보 방법은 `SECURITY.md`를 참고하세요.

## 문서

- `docs/manual/` — 사용자 매뉴얼. 설치, 핵심 개념, 커맨드, 스펙 문서,
  게이트, CLI, 실전 예제, 문제 해결, 설계 결정을 담았습니다.
  `docs/manual/00-index.md`부터 읽으시면 되고, 빨리 감을 잡고 싶다면
  `docs/manual/01-what-and-why.md`의 "첫 30분" 절부터 보고 바로
  실행해도 됩니다.
- `docs/QUICKSTART.md` — 설치부터 첫 실행까지의 최단 경로.
- `docs/ARCHITECTURE.md` — 모든 모듈이 지켜야 하는 계약.
- `docs/decisions/` — 아키텍처 결정 기록.
- `docs/retros/` — 실제 시험 빌드의 회고. 각 회고는 발견된 도구 결함과
  마찰을 근거 경로와 함께 나열합니다.
- [`ROADMAP.md`](ROADMAP.md) — 지금·다음·나중에 할 일과 하지 않을 일(영문, 한국어 요약 포함).

## 상태

**0.16.3 — 초기 단계.** 게이트/원장/계약/승인 커널, 워커 실행(호스트
세션 또는 다른 모델의 워커), Codex 평가자 지원, CI 강제 도구가 모두
갖춰져 있으나, 아직 거친 부분이 있을 수 있습니다. 무엇이 출시되었는지는
`CHANGELOG.md`를, 현재 구조의 배경이 된 아키텍처 결정은
`docs/decisions/`를 참고하세요.

## 라이선스

MIT — `LICENSE` 참고.

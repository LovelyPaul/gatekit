# 설치와 진단

## 요구사항

| 항목 | 조건 | 확인 방법 |
|---|---|---|
| Python | 3.9 이상을 **직접 설치**한다. 훅은 `python3` → `python` → `py -3` 순으로, 각 이름이 진짜 파이썬 3.9+인지 조용히 확인한 뒤에만 실행한다(ADR-0030). Windows가 기본으로 깔아 두는 `python`/`python3`는 Microsoft Store 안내용 자리표시자이지 파이썬이 아니다 | doctor 7번 축. 자리표시자가 PATH에 있으면 `warn` |
| `claude` CLI | PATH에 있어야 함 | doctor 6번 축 |
| Claude Code | 플러그인 설치·활성화 가능한 버전 | doctor 2번 축 |

gatekit 커널은 파이썬 표준 라이브러리만 쓴다. `pip install`이 필요 없다. `codex` CLI는 선택이며 기본적으로 비활성이다.

**Windows는 미리보기다.** 같은 릴리스에서 네이티브 Windows를 지원하지만 실제 세션으로 끝까지 검증되지 않았다. CI(`windows-latest`)는 파이썬 코드가 도는 것까지만 증명한다. Claude Code에서는 Git for Windows를 설치한다(훅이 Git Bash로 실행된다). 파이썬은 Windows에 기본으로 없다. `winget install Python.Python.3.12`로 설치하거나 `py -3 --version`이 응답하는지 확인한다. 소유자 PC(2026-10-04)에서 `tools/smoke_fresh_clone.py`로 한글 사용자 폴더·공백 경로·훅 7종·Codex 층 설치까지 확인했고, Claude Code 실세션이 훅을 부르는 것은 아직 관측하지 못했다. Windows에서 Claude Code가 셸 명령을 `PowerShell` 도구로 실행해도 bash 게이트와 같은 규칙이 적용된다(powershell 게이트, ADR-0028). WSL에서는 리눅스와 같다.

## Windows에서 처음부터

Windows PC에는 gatekit이 전제하는 것이 하나도 깔려 있지 않다. Claude Code도, Git도, 파이썬도 없고, `python`이라고 치면 Microsoft Store 안내용 자리표시자가 `Python`이라는 글자만 찍고 끝난다. **PowerShell**(관리자 권한 아님)에서 한 줄이면 된다(ADR-0033). 관리자로 연 창이면 설치 스크립트가 멈추고 다시 열라고 안내한다.

```powershell
irm https://raw.githubusercontent.com/loganmakes/gatekit/v0.16.21/install/install.ps1 | iex
```

스크립트는 이미 있는 것은 건너뛰고 없는 것만 설치한다. Git, 진짜 파이썬 3.9 이상(Store 자리표시자는 치지 않는다), Claude Code, Node.js LTS를 `winget`과 공식 설치기로 깔고, 사용자 PATH를 고친다(자리표시자보다 앞에 진짜 파이썬, `.local\bin` 추가). 지금 창의 PATH를 새로 읽고, `PYTHONUTF8=1`을 설정한 뒤 플러그인을 설치하거나 업데이트한다. 끝에 항목마다 `ok`/`warn`/`fail`/`unverified`가 나온다. 시스템 PATH와 관리자 권한은 건드리지 않고, 다시 실행해도 안전하다. 업데이트도 같은 줄이다.

그다음 PowerShell을 새로 열고 프로젝트 폴더에서 `claude`를 실행해 로그인한 뒤 `/gatekit:doctor`를 돌린다. 바꾸지 않고 계획만 보려면 `& ([scriptblock]::Create((irm <url>))) -DryRun`. Node.js는 따로 붙이지 않아도 없으면 설치한다(예전 안내의 `-WithNode`는 붙여도 무방하다, ADR-0033 결정 13). Codex도 쓰려면 아래 한 줄을 쓴다.

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/loganmakes/gatekit/v0.16.21/install/install.ps1))) -WithCodex
```

Codex CLI를 `npm.cmd`로 설치하고, 마지막 `codex-hooks` 줄이 프로젝트마다 남은 두 단계(`install --host codex`, `/hooks`에서 신뢰)를 `warn`으로 알려 준다. Codex 플러그인(`codex plugin add`)은 설치하지 않는다(ADR-0033 결정 12).

### 설치 스크립트를 쓸 수 없을 때 (수동)

`winget`이 없는 오래된 Windows이거나 스크립트 실행이 막힌 환경이면 아래 순서를 **PowerShell**에서 그대로 따른다(관리자 권한은 필요 없다. 관리자로 열면 작업 폴더가 `system32`로 잡혀 헷갈리기만 한다).

1. 네 가지를 설치한다. 이미 있는 것은 `winget`이 그렇다고 알려준다. Node.js는 gatekit 자체에는 필요 없지만 스터디에서 웹 앱을 만들고 배포할 때 쓴다(설치 스크립트도 기본으로 설치한다, ADR-0033 결정 13).

   ```powershell
   winget install Git.Git
   winget install Python.Python.3.12
   winget install OpenJS.NodeJS.LTS
   irm https://claude.ai/install.ps1 | iex
   ```

   Claude Code 설치기는 `$HOME\.local\bin\claude.exe`를 두고 "PATH에 없다"는 안내를 남길 수 있다(소유자 PC에서 그랬다). 그때는 다음 한 줄로 사용자 PATH에 추가한다. 그래픽 설정 창을 열 필요가 없다.

   ```powershell
   [Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";$HOME\.local\bin", "User")
   ```

2. **PowerShell 창을 닫고 새로 연다.** PATH는 새 창에서만 갱신된다. 그 다음 넷이 모두 버전을 찍는지 확인한다.

   ```powershell
   git --version
   py -3 --version
   node --version
   claude --version
   ```

   `python --version`이 버전 없이 `Python`만 찍으면 자리표시자다. 훅은 그 이름을 건너뛰고 `py -3`를 쓰므로(ADR-0030) 그대로 두어도 동작하지만, doctor 7번 축이 `warn`으로 알려준다.

3. `claude`를 한 번 실행해 브라우저로 로그인하고 종료한다.

4. 플러그인을 설치한다.

   ```powershell
   claude plugin marketplace add https://github.com/loganmakes/gatekit
   claude plugin install gatekit@gatekit
   ```

5. 프로젝트 폴더로 가서 Claude Code를 열고 진단한다. 폴더 이름에 한글과 공백이 있어도 된다. 탐색기의 "문서"는 실제 경로가 `Documents`이므로, 헷갈리면 `$HOME\study\my-app`처럼 영문 폴더를 새로 만드는 쪽이 안전하다.

   ```powershell
   mkdir $HOME\study\my-app
   cd $HOME\study\my-app
   claude
   ```

   세션 안에서 `/gatekit:doctor`. 1·2번 축이 `ok`이면 훅이 등록된 것이다. 7번 축의 `warn`은 자리표시자 안내이고 동작에는 영향이 없다.

이 절차는 소유자의 Windows 10 PC(한글 사용자 폴더, 파이썬 3.9.10)에서 2026-10-04에 밟은 순서다. 설치 전 상태에서는 `claude`가 "인식되지 않는 용어"라고 나오고, 파이썬 없이 `python`을 치면 `Python`만 찍히는 것이 정상이다.

## macOS·Linux에서 처음부터

설치 스크립트 없이 터미널에서 세 줄이면 된다.

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude plugin marketplace add loganmakes/gatekit
claude plugin install gatekit@gatekit
```

첫 줄은 Claude Code 공식 설치기이고, 나머지 두 줄이 gatekit을 설치한다. `git`과 `python3`(3.9 이상)가 필요하다. macOS는 `xcode-select --install`이 둘 다 설치하고(`git --version`이 설치를 물으면 그때 실행), Linux는 대개 이미 있다(Debian/Ubuntu: `sudo apt install -y git python3`). 설치 후 터미널을 새로 열고 프로젝트 폴더에서 `claude` → `/gatekit:doctor`를 돌린다.

Node.js LTS도 처음에 함께 설치한다. gatekit 자체에는 필요 없지만 스터디에서 웹 앱을 만들고 배포할 때 쓰고, Windows 설치 스크립트도 기본으로 설치한다(ADR-0033 결정 13). macOS는 nodejs.org의 설치기나 `brew install node`, Linux는 nodejs.org의 안내를 따른다(배포판 기본 패키지는 버전이 낡은 경우가 많다). `node --version`이 버전을 찍으면 된다.

Codex도 쓰려면 `npm install -g @openai/codex`를 한 뒤 아래 "Codex 사용자" 절을 따른다. 훅이 sh로 실행되므로 Windows의 `commandWindows` 같은 조치는 필요 없다.

Windows에 설치 스크립트가 필요했던 이유(Store 자리표시자 Python, 설치 직후 갱신되지 않는 PATH, cp949, PowerShell로 실행되는 훅, `codex.ps1` 실행 정책)는 이 시스템들에 없어서 스크립트를 두지 않는다. 다만 2026-10-05의 Windows 실측은 macOS·Linux를 다루지 않았으니, 설치 후 [프로젝트 초기화](#프로젝트-초기화) 전에 게이트 점검을 한 번 한다. `spec/`에 스펙 파일이 있고 승인 전인 상태에서 코드 쓰기가 막혀야 한다.

## 설치

```bash
/plugin marketplace add https://github.com/loganmakes/gatekit
/plugin install gatekit@gatekit
```

설치 후 **Claude Code를 재시작**해야 `plugin/hooks/hooks.json`의 훅이 로드된다. 재시작하지 않으면 파일은 디스크에 있지만 게이트가 하나도 발화하지 않는다.

### Claude 데스크톱 앱 사용자

앱에서도 플러그인과 훅이 CLI와 똑같이 동작한다. **+ → Plugins → Add plugin**에서 마켓플레이스 `https://github.com/loganmakes/gatekit`를 추가하고 `gatekit`을 설치한 뒤 **자기 프로젝트 폴더**를 연다. 터미널에서 사용자 범위로 설치했다면 앱에도 이미 있다. gatekit 저장소 폴더 자체를 앱으로 여는 것은 설치가 아니다 — 모델이 커맨드 파일을 읽어 흉내는 내지만 훅이 등록되지 않아 게이트가 하나도 돌지 않는다.

### Codex 사용자 (앱·CLI)

Codex도 같은 마켓플레이스에서 같은 플러그인을 설치한다.

```bash
codex plugin marketplace add loganmakes/gatekit
codex plugin add gatekit@gatekit
```

스킬은 `$gatekit-<이름>`으로 부른다. **플러그인 훅은 사용자가 신뢰하기 전까지 돌지 않는다.** Codex 데스크톱 앱은 지금 신뢰를 기록하지 못하므로(openai/codex#47283), 터미널에서 `codex` → `/hooks`로 gatekit 훅을 검토·신뢰한 뒤 새 세션을 연다. 신뢰는 훅 내용 단위라 업그레이드할 때마다 다시 한다. 그 전까지 doctor 8번 축이 `warn`을 낸다.

**Windows의 Codex는 플러그인 방식과 아래 호스트 층 방식이 모두 동작한다.** Codex는 Windows에서 훅 명령을 PowerShell 5.1로 실행하는데, 플러그인의 `hooks/hooks.json`(ADR-0038)과 `install --host codex`가 만드는 `.codex/hooks.json`(ADR-0034) 모두 Windows용 `commandWindows`를 갖고 있다. 훅 신뢰(`/hooks`)는 똑같이 필요하다. 신뢰하지 않은 훅을 Codex는 아무 메시지 없이 건너뛴다.

Windows에서 Codex를 처음부터 준비하는 순서는 이렇다.

1. PowerShell(관리자 아님)에서 위의 Codex 한 줄 설치를 실행한다. 결과표의 `codex-hooks` 줄에 이 PC에 맞는 `install --host codex` 명령이 나온다.
2. 프로젝트 폴더에서 그 명령을 실행한다. `.codex/hooks.json`, `.agents/skills/gatekit-*`, `AGENTS.md` 관리 블록이 생긴다.
3. 같은 폴더에서 `codex`를 실행한다(`os error 5`로 멈추면 `codex --no-daemon`). `/hooks`를 입력하고, 새 훅(`[!] … new`)마다 `t`를 눌러 신뢰한다. 이미 신뢰한 훅(`[x]`)에서 Space나 Enter를 누르면 신뢰가 풀리니 주의한다.
4. `/quit`로 나가 `codex`를 다시 실행한다. 신뢰는 새 세션부터 적용된다.
5. gatekit을 업데이트하면 2~4를 다시 한다. 훅 내용이 바뀌면 신뢰도 새로 해야 한다.

예전 방식(프로젝트마다 호스트 층 생성)도 계속 동작한다.

```bash
git clone https://github.com/loganmakes/gatekit
python3 "gatebound/plugin/bin/gatekit.py" install --host codex
```

`.codex/hooks.json`, `.agents/skills/gatekit-*`(커맨드별 스킬), `AGENTS.md`의 관리 블록이 생긴다. 생성 파일은 손으로 고치지 않고 `plugin/`을 고친 뒤 다시 `install`한다. Codex가 프로젝트의 `.codex/` 층을 신뢰하겠느냐고 물으면 승인하고 **새 세션을 연다**. 호스트별로 되는 것과 `unverified`인 것은 README의 동등성 표에 있다.

재시작한 다음 반드시 진단을 돌린다.

```bash
/gatekit:doctor
```

## 8축 doctor 판정표

`doctor`는 8개 축을 각각 `ok`/`warn`/`fail`/`unverified`로 판정하고, 축마다 복붙 가능한 `fix` 문자열을 낸다. 종료 코드는 `fail`이 하나라도 있을 때만 1이다. 종료 코드 0은 "아무것도 실패하지 않았다"는 뜻이지 "다 괜찮다"는 뜻이 아니다.

| # | 축 | 무엇을 보는가 | `fail`일 때 처방 |
|---|---|---|---|
| 1 | plugin files | `plugin.json`, `hooks.json`, 게이트 스크립트 9개(prompt·write·bash·powershell·skill·spawn·question·compact·stop)가 존재하고 비어 있지 않은가 | `/plugin install gatekit` — 스크립트가 없으면 그 게이트는 아예 발화하지 않는다 |
| 2 | hooks registered | `installed_plugins.json`에 등재되고 `settings.json`의 `enabledPlugins`에서 활성인가 | `/plugin enable gatekit@gatekit` |
| 3 | project state | `.gatekit/config.json`과 `approvals.json`이 파싱되는가. Playwright 설정(`playwright.config.{ts,js,mjs,cjs}`, `spec/design/e2e/` 아래 포함)의 `webServer` 포트(`webServer:`·`'webServer':`·`const webServer: 타입 =` 값의 중괄호·대괄호 안에서 주석을 뺀 `port:`·`url:` 숫자와 `process.env.PORT \|\| 3000` 같은 `\|\|` 뒤 기본값. 파서가 아니라 간단한 스캔이므로 변수로만 지정한 포트는 못 찾음)에 이미 무언가 떠 있으면 `warn`. POSIX에서 `lsof`가 있으면 그 프로세스의 PID·명령·작업 디렉터리와 이 프로젝트 안인지 밖인지를 적는다(ADR-0026) | 해당 파일을 손으로 고치거나 삭제한다. 포트 충돌이면 그 프로세스를 직접 멈추거나 포트를 바꾼다. doctor는 아무것도 종료하지 않는다 |
| 4 | spec set | `spec validate` 판정 | 실패한 파일을 소유한 파이프라인으로 간다 |
| 5 | contract freshness | `.gatekit/contract.json`의 `source_sha256`가 `05-gate.md`와 일치하는가 | `contract derive` 재실행 |
| 6 | workers | 기본 백엔드 바이너리가 PATH에 있는가 | 해당 CLI를 설치하거나 `workers set-default <name>` |
| 7 | python | 인터프리터가 3.9 이상인가 | 파이썬 3.9 이상 설치 |
| 8 | host layer | Codex용 `.codex/hooks.json`이 있으면 그 안의 게이트 스크립트가 실제로 존재하는가(없으면 `ok`). Codex 플러그인으로 설치됐는데 훅 신뢰 기록이 없으면 `warn` | 층이 깨졌으면 `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" install --host codex`, 신뢰가 없으면 터미널에서 `codex` → `/hooks` |

### `unverified`가 나오는 정상적인 경우

- 2번 축: 소스 체크아웃에서 실행 중이라 설치 매니페스트가 없다. 문제가 아니다.
- 3번 축: 프로젝트에 `.gatekit/`이 아직 없다. `/gatekit:setup` 전이다.
- 4번 축: 프로젝트에 `spec/` 디렉터리가 없다. `/gatekit:interview` 전이다.
- 5번 축: `.gatekit/contract.json`이 아직 없다. `/gatekit:gate` 전이다.
- 6번 축: 바이너리는 있으나 `--version` 프로브가 응답하지 않았다. 빌드는 돌아간다.

`unverified`를 "이상 없음"으로 요약하면 안 된다. 검사하지 않았다는 뜻이다.

### 가장 위험한 실패

2번 축의 `fail`이다. 설치는 되었는데 `enabledPlugins`에서 비활성이면 디스크에는 모든 파일이 있고 훅은 하나도 발화하지 않는다. 하네스가 설치된 것처럼 보이면서 아무것도 강제하지 않는 상태다.

## 프로젝트 초기화

프로젝트 디렉터리에서 실행한다.

```bash
/gatekit:setup
```

`.gatekit/config.json`이 없으면 기본값으로 생성하고, 기본 워커(`claude`)를 점검한 뒤 백엔드 표를 보여준다. 이미 있으면 건드리지 않는다.

Codex 백엔드를 쓰려면 별도로 요청해야 한다.

```bash
/gatekit:setup codex
```

이 경우 `workers check codex`를 먼저 돌리고, 무엇이 바뀌는지 설명한 뒤 사용자 확인을 받고서야 활성화한다. 확인 전에는 아무것도 바꾸지 않는다.

## 업데이트

터미널에서 두 줄을 실행한다. 첫 줄은 마켓플레이스 목록만 새로 받아 오고, 설치된 플러그인을 새 버전으로 바꾸는 것은 둘째 줄이다. Claude Code 세션 안에서는 `/plugin marketplace update gatekit`, `/plugin update gatekit@gatekit`로 같은 일을 한다.

```bash
claude plugin marketplace update gatekit
claude plugin update gatekit@gatekit
```

업데이트 후에도 Claude Code를 재시작한다. 현재 세션은 이미 로드된 구 버전을 계속 쓴다. 재시작 뒤 `/gatekit:doctor`로 1·2번 축을 확인한다. Windows에서 설치 스크립트로 설치했다면 그 한 줄을 다시 실행해도 업데이트된다.

Codex 플러그인도 쓰고 있다면 따로 업데이트한다.

```bash
codex plugin marketplace upgrade gatekit
codex plugin add gatekit@gatekit
```

그다음 터미널에서 `codex` → `/hooks`를 열어, 바뀐 것으로 표시된 gatekit 훅마다 `t`를 눌러 다시 신뢰하고 새 세션을 연다. 신뢰는 훅 내용 단위라 훅이 바뀐 릴리스에서는 다시 해야 한다. doctor 8번 축이 신뢰한 훅 수를 센다.

## 제거

```bash
/plugin uninstall gatekit@gatekit
```

프로젝트의 `spec/`과 `.gatekit/`은 그대로 남는다. `spec/`은 커밋 대상 산출물이고, `.gatekit/` 안에서는 `config.json`과 `approvals.json`만 커밋 대상이며 `runs/`와 `jobs/`는 무시 대상이다. 플러그인을 지워도 이 파일들은 지워지지 않으므로 필요하면 직접 삭제한다.

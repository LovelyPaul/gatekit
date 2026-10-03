# gatekit 사용 설명서

gatekit은 Claude Code 플러그인이다. `CLAUDE.md`에 산문으로 적던 규칙을 실제로 실행되는 훅으로 바꾼다. 이 매뉴얼은 12개 문서로 구성되며, 모든 내용은 `docs/ARCHITECTURE.md` 계약과 실제 코드에서 확인한 것만 담았다.

## 문서 목록

| 문서 | 한 줄 소개 |
|---|---|
| `01-what-and-why.md` | gatekit이 무엇이고 어떤 문제를 푸는가, 핵심 철학 4개, **첫 30분 빠른 시작** |
| `02-install.md` | 설치·요구사항·8축 doctor 판정표·제거와 업데이트 |
| `03-concepts.md` | 판정 어휘, 스펙 세트, 가정 원장, 완료 계약, 해시 앵커 승인 등 핵심 개념 |
| `04-pipeline.md` | 7단계 파이프라인 흐름도와 각 단계의 입력·출력·게이트 |
| `05-commands.md` | 커맨드 10개 레퍼런스 |
| `06-spec-files.md` | 스펙 문서들의 필수 섹션과 펜스 JSON 스키마 |
| `07-gates.md` | 훅 게이트 7개가 각각 무엇을 막는가 |
| `08-cli.md` | CLI 레퍼런스, 서브커맨드와 종료 코드 |
| `09-worked-example.md` | Quicknote 실전 예제 — 한 문장에서 완성까지 |
| `10-troubleshooting.md` | 증상 → 원인 → 처방 표 |
| `11-security.md` | 보안·운영 자세 |
| `12-design-decisions.md` | 대표 ADR 요약과 아키텍처 계약의 핵심 규칙 |

## 읽는 순서

### 처음 쓰는 사람

빨리 감을 잡고 싶다면 **`01-what-and-why.md`의 "첫 30분" 절부터 보고 바로 실행**해도 된다. 개념은 막혔을 때 찾아 읽어도 늦지 않다.

차근히 읽고 싶다면 이 순서다.

1. `01-what-and-why.md` — 왜 이 도구가 필요한지 먼저 이해한다. 이걸 건너뛰면 게이트가 차단할 때 도구가 방해한다고 느끼게 된다.
2. `02-install.md` — 설치하고 `/gatekit:doctor`로 실제로 훅이 붙었는지 확인한다.
3. `03-concepts.md` — `unverified`가 왜 통과가 아닌지, 승인이 왜 해시에 묶이는지 익힌다.
4. `04-pipeline.md` — 파이프라인 단계의 순서를 본다.
5. `09-worked-example.md` — 실제로 돌아간 예제를 따라 읽는다.
6. 막히면 `10-troubleshooting.md`.

### 참조용

- 커맨드 인자가 궁금할 때 → `05-commands.md`
- 스펙 파일에 무슨 제목을 써야 하는지 → `06-spec-files.md`
- 왜 차단됐는지 → `07-gates.md`
- CLI를 직접 칠 때 → `08-cli.md`
- 왜 이렇게 설계됐는지 → `12-design-decisions.md`

## 전제

- 이 매뉴얼의 모든 CLI 예시는 `python3 "${CLAUDE_PLUGIN_ROOT}/bin/gatekit.py" <서브커맨드>` 형식이다. 이유는 `08-cli.md`에 있다. **대부분의 작업은 CLI를 직접 칠 필요 없이 `/gatekit:<커맨드>` 슬래시 커맨드로 끝난다** — CLI는 커맨드가 내부에서 부르는 것이고, 직접 칠 일은 상태를 들여다볼 때 정도다.
- 식별자(파일명·명령·플래그·JSON 키·펜스 이름·`ok`/`warn`/`fail`/`unverified`)는 번역하지 않는다.
- 현재 버전은 0.16.5이다.

## 노션으로 내보내기

이 매뉴얼을 노션에 넣으려면 임포트 번들을 만든다.

```bash
python3 tools/build_manual_bundle.py
```

`dist/gatekit 사용자 매뉴얼.zip`이 생기고, 노션에서 Import → Markdown & CSV로
올리면 부모 페이지 1개와 하위 페이지 12개 트리로 들어간다.

저장소가 정본이다. 내용을 고칠 때는 `docs/manual/`을 고치고 번들을 다시 만들어
재임포트한다. 노션 쪽만 고치면 두 사본이 갈라진다.

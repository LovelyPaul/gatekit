# Roadmap

This is gatekit's public roadmap. It says what is being worked on, what comes
next, and what is deliberately out of scope. It is a plan, not a promise:
items move when a real session shows a different priority. Every item that
grew out of a recorded decision links its ADR; the ADR's "Open questions"
section has the detail.

gatekit will be renamed **gatebound** once the current study cohort ends
(about a month from 2026-10-03). Until then everything user-facing stays
`gatekit`.

Want to influence the order? Open a thread in
[Discussions](https://github.com/gatebound/gatebound/discussions) or a
feature request.

## Now — during the study

The cohort is using gatekit on real projects, so the priority is that it does
not break under them.

- **Stability.** Fix what the cohort hits, in point releases, each with a
  review pass and a `CHANGELOG.md` entry. No contract changes without an ADR.
- **Examples.** Small, complete projects that went through the whole pipeline
  for real, starting with [`examples/memo-board/`](examples/memo-board/).
- **Releases.** Regular tagged releases so a cohort member can say exactly
  which version they ran when they report a problem.
- **Windows: confirm the PowerShell gate.** Since 0.16.6 Claude Code's
  `PowerShell` tool meets the same gates as Bash
  ([ADR-0028](docs/decisions/ADR-0028-powershell-tool-gate.md)), but the gate
  has only been tested by parsing; it has not yet been observed in a live
  Windows session, so the README host table marks it `unverified`. A cohort
  member on Windows running one gated build would settle it.

## Shipped in 0.16.6 — the compatibility layer for the rename

Everything a project needs to survive the rename is already in, under the
current name ([ADR-0029](docs/decisions/ADR-0029-rename-compatibility-layer.md)).
`plugin/gatekit/names.py` holds `CURRENT = "gatekit"` and
`FUTURE = "gatebound"`, and every place the name is a contract asks it.

- **Spec fences.** `gatebound-task/criterion/budget/discovery/scope` are read
  as aliases of the `gatekit-*` fences, permanently. A spec written today
  keeps working.
- **State directory.** `.gatekit/` or `.gatebound/` is resolved and both are
  protected; `gatekit migrate` (dry run unless `--apply`) moves it, approvals
  included, and never touches `spec/`.
- **Paths in argv.** A criterion or task argv naming a missing
  `…/gatekit|gatebound/gates/<gate>.py` or `bin/gatekit|gatebound.py` runs
  this plugin's file, at run time only; approval hashes do not change.
- **Environment.** Workers get both `GATEKIT_*` and `GATEBOUND_*`; gates read
  either.
- **Old plugin detection.** `doctor` fails when gatekit and gatebound are both
  enabled or both cached, and when both state directories exist.

## Next — 0.17.0: the rename to gatebound

What remains is the rename itself and its documentation.

- **Flip the name.** Set `CURRENT = "gatebound"` and `LEGACY = ("gatekit",)`
  in `names.py` and work through the
  [ADR-0029 checklist](docs/decisions/ADR-0029-rename-compatibility-layer.md#checklist-for-the-rename-itself):
  the package directory and launcher, `approval.WORKER_ENV`, the skill
  directory prefix in `hosts.install`, the Codex command rewrite, template
  fences and every user-facing message.
- **English manual.** `docs/manual/` gets an English edition; today it is
  Korean only.
- **Migration guide.** One page: what changes, what keeps working, and the
  commands to run (`migrate --apply`), in English and Korean.
- **README and URLs.** README (en/ko), the marketplace manifest and links move
  to the new name and repository.
- **Demo recording.** A short recording of the pipeline under the new name.

## Later

Roughly in order of how often the gap has cost time in real sessions.

| Item | Why | Decision record |
|---|---|---|
| Cost and token tracking per task | A job shows elapsed time but not what each task cost; a long build cannot be budgeted by spend. Remaining context is visible only to the statusline today. | [ADR-0013](docs/decisions/ADR-0013-workers-only-for-other-models.md) (open question on context-aware thresholds) |
| Live job view | `status` answers "is it moving" once; a streamed view (`stream-json` for the claude backend, a files-touched count, `jobs status --watch` as proposed in ADR-0010 — not implemented) would answer it continuously. | [ADR-0010](docs/decisions/ADR-0010-build-visibility.md) |
| Resume after a crash or a blocked dependency | A `blocked` task does not resume when its dependency later passes in the same job; resume is manual. | [ADR-0009](docs/decisions/ADR-0009-gate-preflight.md) |
| Worker evidence receipts with typed blockers | A worker's report should carry what it ran and why it stopped as typed data, not prose, so a silent failure (no output, timeout) still says something. | [ADR-0021](docs/decisions/ADR-0021-host-budget-and-failure-fingerprint.md) (evidence-less failures never fingerprint) |
| Brownfield mode | The pipeline assumes a new project; an existing codebase needs a way to gate changes without re-specifying what already exists. | no ADR yet |
| Detect runs where every test was skipped | `3 skipped`, exit 0 proves nothing, like zero tests, but is not detected yet. | [ADR-0022](docs/decisions/ADR-0022-not-yet-runnable-zero-tests-and-gate-baseline.md) |
| Count worker timeouts as attempts | A worker timeout returns before the attempt is recorded, although a timeout is a failure state. Known bug, low impact: it only affects builds with `execution: worker` or `--backend`; the default is `host` ([ADR-0013](docs/decisions/ADR-0013-workers-only-for-other-models.md)), where no worker runs. | [ADR-0021](docs/decisions/ADR-0021-host-budget-and-failure-fingerprint.md), [ADR-0014](docs/decisions/ADR-0014-attempts-outlive-the-job.md) |
| Cross-process lock on `attempts.json` | Two gatekit processes updating it at once can lose an update; the stdlib lock needs Windows testing first. | [ADR-0021](docs/decisions/ADR-0021-host-budget-and-failure-fingerprint.md) |
| More hosts | Added as each host's hook support allows the gates to actually run, not before. Codex has no `PreCompact` equivalent yet. | [ADR-0019](docs/decisions/ADR-0019-one-plugin-for-claude-app-codex-plugin-and-windows.md), [ADR-0013](docs/decisions/ADR-0013-workers-only-for-other-models.md) |
| Opt-in telemetry | Only with published privacy rules first: what is collected, where it goes, how to turn it off. Off by default, never secrets or paths. | no ADR yet |

### Smaller open questions from the decision records

These are recorded, not scheduled. Each is a candidate for a point release
once a real session shows it matters.

- Run a mechanical dry run of the criteria at `/gatekit:gate` time, and move
  the command-error patterns into a data file —
  [ADR-0009](docs/decisions/ADR-0009-gate-preflight.md).
- Carry each screen's component table into worker briefs, and redraw the
  preview when `tokens.json` changes —
  [ADR-0011](docs/decisions/ADR-0011-design-preview.md).
- Report unjustified questions in `/gatekit:verify`, and budget the discover
  pipeline's questions —
  [ADR-0012](docs/decisions/ADR-0012-question-justification.md).
- Keep `max_retries` across jobs; decide whether `gates recheck` refreshes
  `preflight.json` —
  [ADR-0013](docs/decisions/ADR-0013-workers-only-for-other-models.md).
- Report a task that passed after a long failure history as a quality signal —
  [ADR-0014](docs/decisions/ADR-0014-attempts-outlive-the-job.md).
- A narrower evaluator sandbox that does not depend on Codex hook trust, and
  checking whether Codex build workers hit the same trust gap —
  [ADR-0015](docs/decisions/ADR-0015-evaluator-sandbox-vs-write-gate.md).
- Tune the discovery floor, saturation thresholds and prototype rounds against
  measured sessions, and decide what a prototype gate means for CLI tools and
  libraries — [ADR-0017](docs/decisions/ADR-0017-branch-floor-and-verdict-gate.md).
- Let a passing `recheck` clear the failure entry, and decide whether
  `recheck` counts against the host budget —
  [ADR-0021](docs/decisions/ADR-0021-host-budget-and-failure-fingerprint.md).
- Use `baseline.json` in `/gatekit:verify` to flag criteria that passed before
  any work and were never seen failing —
  [ADR-0022](docs/decisions/ADR-0022-not-yet-runnable-zero-tests-and-gate-baseline.md).
- Decide whether `/gatekit:verify` fails rather than warns when grading files
  changed and nobody looked at the diff —
  [ADR-0023](docs/decisions/ADR-0023-grading-files-changed-after-approval-or-failure.md).

## Non-goals

Things gatekit will not become, so that nobody spends a pull request on them.

- **No evolutionary spec loop.** gatekit does not rewrite the spec by itself
  until something passes. A human approves the spec and the completion
  contract; a failing build is reported, not quietly re-specified.
- **No multi-model voting.** A different model may build or evaluate
  (ADR-0013, ADR-0007), but verdicts come from commands that ran, not from a
  panel of models agreeing.
- **A small, stdlib-only core.** Python 3.9+ standard library, one plugin, no
  package installs ([ADR-0002](docs/decisions/ADR-0002-stdlib-only.md)).
  Features that need a dependency stay outside the core.
- **Hooks enforce, prompts do not.** A rule that matters is a hook that runs
  every time. Prose in a command or skill explains; it never enforces.

## 한국어 요약

- **지금 (스터디 기간):** 안정성 수정, 실제 파이프라인을 끝까지 돈 예제
  ([`examples/memo-board/`](examples/memo-board/)), 버전을 특정할 수 있는 정기 릴리스.
  0.16.6의 PowerShell 게이트(ADR-0028)는 파싱 테스트만 거쳤고 실제 Windows 세션에서는
  아직 확인하지 못했다(`unverified`).
- **0.16.6에 이미 들어감:** 이름 변경 호환 계층(ADR-0029) — `gatebound-*` 펜스 별칭,
  `.gatekit/`·`.gatebound/` 해석과 `migrate` 명령, argv 경로·환경 변수 별칭, doctor의
  두 플러그인·두 상태 디렉터리 감지.
- **다음 (0.17.0):** 이름을 실제로 gatebound로 바꾼다 — `names.py`를 뒤집고 ADR-0029
  체크리스트를 처리, 영어 매뉴얼, 한 쪽짜리 마이그레이션 가이드(영어·한국어),
  README·URL 갱신, 데모 녹화.
- **나중:** 작업별 비용·토큰 추적, 실시간 작업 보기(ADR-0010), 중단 후 재개(ADR-0009),
  타입이 있는 차단 사유를 담은 워커 증거 영수증, 기존 코드베이스(브라운필드) 모드,
  전부 건너뛴 테스트 감지(ADR-0022), 워커 타임아웃 미집계 버그(`execution: worker`·`--backend`
  빌드에만 해당, 기본값 `host`에서는 영향 없음)와 프로세스 간 잠금(ADR-0021),
  훅 지원에 맞춘 호스트 추가(ADR-0019), 개인정보 규칙을 먼저 공개한 옵트인 텔레메트리.
- **하지 않을 것:** 스펙을 스스로 고쳐 가며 통과시키는 루프, 여러 모델의 투표 판정,
  표준 라이브러리 밖 의존성, 프롬프트 문장에 의한 강제. 강제는 훅이 한다.

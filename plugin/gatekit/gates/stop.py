"""Stop gate — the session does not end while the contract is unmet.

When a build or verify pipeline is active and ``.gatekit/contract.json`` exists,
this gate runs the completion contract (:mod:`gatekit.contract`) and blocks the
stop if any criterion is ``fail`` or ``unverified``, naming the offending ids.

Three safety valves keep the block from becoming a trap:

* **``stop_hook_active``** — Claude Code sets this when it is already inside a
  stop-hook continuation. Blocking again would loop, so this gate always allows.
* **``block_count < 3``** — after three blocks the gate steps aside and lets the
  session end. A gate that can never be satisfied must not hold a user hostage.
* **Any internal error allows.** The wrapper in :mod:`gatekit.hookio` catches
  everything and exits 0.

Whenever the gate lets the session stop it records ``stop.final_verdict``, and
that value is **never blank**: an unrun contract is recorded as ``unverified``,
not silently as success.

ADR-0024 bounds what the gate judges:

* **Stand-down.** Under ``build`` it judges while the latest job is absent or
  unsettled, and once more after every task is terminal (the handoff check).
  Once that settled job has a recorded verdict (``ok``, or ``final_verdict``
  after ``MAX_BLOCKS``) it stands down: later Stops run nothing until
  ``/gatekit:build`` or ``/gatekit:verify`` re-arms it. ``verify`` is the same
  without the job.
* **Tiers.** Under ``build`` only ``turn`` criteria run; ``verify`` ones are
  deferred to ``/gatekit:verify``, never judged, never ``ok``.
* **Budget.** Under ``build`` no criterion starts once ``stop.budget_s`` is
  spent; those are deferred too. What did run is judged as before. A run
  with a budget deferral is never ``ok``: when what ran passed, the Stop is
  allowed (no block spent), ``unverified`` is recorded and the gate does not
  stand down. The next Stop runs the deferred ones first and keeps what the
  same tree already judged, so it converges.

ADR-0027: before judging, the gate checks the approval and the contract
themselves (:func:`gatekit.contract.integrity`): an approval of
``spec/05-gate.md`` that is not ``ok`` is ``gate_not_approved``, and a
``contract.json`` that is not what ``05-gate.md`` derives is
``contract_mismatch``. Both are ``unverified`` and block like any other
``unverified``; neither is recorded or reused.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import config, contract, hookio, jobs, ledger, names, paths, verdict  # noqa: E402

#: Pipelines whose completion is contract-enforced.
ENFORCED_PIPELINES = ("build", "verify")

#: How many times this gate may block one session before standing down.
MAX_BLOCKS = 3

#: The Stop hook's ``timeout`` in ``hooks/hooks.json``. 600 s is the largest
#: value the Claude Code hook documentation shows; no higher value is
#: documented as supported, so gatekit does not rely on one.
STOP_HOOK_TIMEOUT_S = 600.0

#: The contract run inside this gate is capped below the hook timeout so the
#: interpreter start-up, the ledger write and the subprocess teardown fit. A
#: declared ``gatekit-budget`` above this runs in full under ``contract run``
#: but is cut here — and a cut run is ``unverified``, which is honest, where a
#: hook killed by Claude Code would record no verdict and no log line at all.
STOP_BUDGET_CAP_S = config.STOP_BUDGET_MAX_S

#: ADR-0024: the tiers the gate runs under ``build``. Under ``verify`` it runs
#: every tier, as ``contract run`` does.
BUILD_TIERS = ("turn",)

_MESSAGES = {
    "en": {
        "blocked": (
            "gatekit: the completion contract is not met, so this work is not done "
            "({count} of {total} criteria failing or unverified):\n{reasons}\n"
            "Fix the causes and let the contract run again. "
            "'unverified' means it was never checked — that is not a pass."
        ),
        "reused": (
            "  (no file changed since the run at {at}; that result is reused. "
            "Change the code to run the contract again.)"
        ),
        "deferred_tier": (
            "  deferred to /gatekit:verify — not judged here, does not block: {ids}"
        ),
        "deferred_budget": (
            "  deferred: Stop-gate budget ({budget:g} s) spent — not judged here, "
            "does not block; /gatekit:verify runs them: {ids}"
        ),
        "stood_down": (
            "stop gate stood down ({subject} {scope} {verdict} recorded{extra}): "
            "follow-up edits are not gated; /gatekit:verify re-checks the contract"
        ),
        "stood_down_tier": "turn-tier",
        "stood_down_all": "contract",
        "stood_down_extra": ", {count} deferred to /gatekit:verify",
        "two_states": (
            "gatekit: both {dirs} hold approvals.json, so it is unclear which approval "
            "and contract this project is under; the Stop gate judges neither and "
            "records 'unverified' (not a pass). Run /gatekit:doctor, then "
            "`gatekit migrate` (or remove the directory you did not create) so only "
            "one state directory remains."
        ),
        "no_turn_tier": (
            "  no turn-tier criteria: the Stop gate judges nothing at turn end "
            "during the build; /gatekit:verify runs them"
        ),
        "no_turn_tier_line": (
            "stop gate: no turn-tier criteria — turn ends during the build judge "
            "nothing; /gatekit:verify runs them"
        ),
        "budget_pending": (
            "stop gate: Stop-gate budget left criteria unjudged (unverified, not ok): "
            "{ids} — the next turn end runs them first"
        ),
        "tasks_unpassed": (
            "gatekit: build job {job} has settled, but not every task passed, so this "
            "work is not done:\n{reasons}\n"
            "Fix those tasks and run them again — `jobs complete <task>` under host "
            "execution, `jobs redelegate <task>` under worker execution — or start "
            "a new job. A task that is `blocked` never ran: that is not a pass."
        ),
        "tasks_line": "tasks not passed in {job}: {tasks}",
        "stale": (
            "gatekit: .gatekit/contract.json no longer matches spec/05-gate.md, so "
            "completion cannot be judged (contract_stale). "
            "Run `" + paths.cli_invocation() + " contract derive`, then finish the work."
        ),
        "grading_hint": (
            "  A file that grades the work changed since approval: {paths}\n"
            "  If the change is intended, re-run /gatekit:gate to re-approve; "
            "otherwise revert it."
        ),
        "not_approved": (
            "gatekit: spec/05-gate.md is not approved as it stands (approval: "
            "{status}), so completion cannot be judged (gate_not_approved). "
            "If the gate or its approval was changed, restore it and fix the code "
            "against the approved criteria; if the gate must change, re-run "
            "/gatekit:gate for a new approval."
        ),
        "mismatch": (
            "gatekit: .gatekit/contract.json is not what spec/05-gate.md declares "
            "({diff}), so completion cannot be judged (contract_mismatch). Only "
            "`contract derive` writes it: run `" + paths.cli_invocation() +
            " contract derive` to restore it from the approved gate and fix the "
            "code; if the criteria must change, re-run /gatekit:gate for a new "
            "approval."
        ),
        "unapproved": (
            "gatekit: grading files changed after spec/05-gate.md was approved and "
            "the contract was re-derived, so completion cannot be judged "
            "(grading_unapproved): {paths}\n"
            "If the change is intended, re-run /gatekit:gate to re-approve; "
            "otherwise revert it."
        ),
    },
    "ko": {
        "blocked": (
            "gatekit: 완료 계약을 충족하지 못했으므로 아직 끝난 것이 아닙니다 "
            "(기준 {total}개 중 {count}개 실패 또는 미검증):\n{reasons}\n"
            "원인을 고친 뒤 계약을 다시 실행하세요. "
            "'unverified' 는 검증하지 않았다는 뜻이며 통과가 아닙니다."
        ),
        "reused": (
            "  ({at} 실행 이후 바뀐 파일이 없어 그 결과를 다시 썼습니다. "
            "코드를 고치면 계약을 다시 실행합니다.)"
        ),
        "deferred_tier": (
            "  /gatekit:verify 로 미룸 — 여기서 판정하지 않으며 차단 사유가 아님: {ids}"
        ),
        "deferred_budget": (
            "  Stop 게이트 예산({budget:g}초) 소진으로 미룸 — 여기서 판정하지 않으며 "
            "차단 사유가 아님, /gatekit:verify 가 실행: {ids}"
        ),
        "stood_down": (
            "Stop 게이트 물러남({subject} {scope} 판정 {verdict} 기록됨{extra}): 이후 "
            "수정은 게이트를 거치지 않음, 계약 재확인은 /gatekit:verify"
        ),
        "stood_down_tier": "turn 등급",
        "stood_down_all": "계약",
        "stood_down_extra": ", {count}개는 /gatekit:verify 로 미룸",
        "two_states": (
            "gatekit: {dirs} 모두에 approvals.json 이 있어 이 프로젝트가 어느 승인과 "
            "계약 아래 있는지 알 수 없습니다. Stop 게이트는 어느 쪽도 판정하지 않고 "
            "'unverified'(통과 아님)로 기록합니다. /gatekit:doctor 를 실행한 뒤 "
            "`gatekit migrate` 로(또는 직접 만들지 않은 디렉터리를 지워) 상태 디렉터리를 "
            "하나만 남기세요."
        ),
        "no_turn_tier": (
            "  turn 등급 기준 없음: 빌드 중 Stop 게이트는 턴 끝에서 아무것도 "
            "판정하지 않음, /gatekit:verify 가 실행"
        ),
        "no_turn_tier_line": (
            "Stop 게이트: turn 등급 기준 없음 — 빌드 중 턴 끝은 아무것도 판정하지 "
            "않음, /gatekit:verify 가 실행"
        ),
        "budget_pending": (
            "Stop 게이트: Stop 예산 소진으로 판정하지 못한 기준(미검증, ok 아님): "
            "{ids} — 다음 턴 끝에 먼저 실행"
        ),
        "tasks_unpassed": (
            "gatekit: 빌드 잡 {job} 은 끝났지만 통과하지 못한 태스크가 있어 아직 끝난 "
            "것이 아닙니다:\n{reasons}\n"
            "그 태스크를 고친 뒤 다시 실행하거나(호스트 실행이면 `jobs complete <task>`, "
            "워커 실행이면 `jobs redelegate <task>`) 새 잡을 시작하세요. `blocked` 태스크는 실행되지 않았으며 통과가 아닙니다."
        ),
        "tasks_line": "{job} 에서 통과하지 못한 태스크: {tasks}",
        "stale": (
            "gatekit: .gatekit/contract.json 이 spec/05-gate.md 와 더 이상 일치하지 "
            "않아 완료 여부를 판정할 수 없습니다 (contract_stale). "
            "`" + paths.cli_invocation() + " contract derive` 를 실행한 뒤 작업을 마치세요."
        ),
        "grading_hint": (
            "  승인 이후 작업을 채점하는 파일이 바뀌었습니다: {paths}\n"
            "  의도한 변경이면 /gatekit:gate 를 다시 실행해 재승인하고, 아니면 "
            "변경을 되돌리세요."
        ),
        "not_approved": (
            "gatekit: spec/05-gate.md 가 현재 상태로 승인되어 있지 않아(승인: "
            "{status}) 완료 여부를 판정할 수 없습니다 (gate_not_approved). "
            "게이트나 승인이 바뀌었다면 되돌린 뒤 승인된 기준에 맞게 코드를 고치고, "
            "게이트를 바꿔야 한다면 /gatekit:gate 를 다시 실행해 새로 승인받으세요."
        ),
        "mismatch": (
            "gatekit: .gatekit/contract.json 이 spec/05-gate.md 가 선언한 내용과 "
            "다르므로({diff}) 완료 여부를 판정할 수 없습니다 (contract_mismatch). "
            "이 파일은 `contract derive` 만 씁니다: `" + paths.cli_invocation() +
            " contract derive` 로 승인된 게이트에서 다시 만든 뒤 코드를 고치고, "
            "기준을 바꿔야 한다면 /gatekit:gate 를 다시 실행해 새로 승인받으세요."
        ),
        "unapproved": (
            "gatekit: spec/05-gate.md 승인 이후 채점 파일이 바뀐 채 계약이 다시 "
            "파생되어 완료 여부를 판정할 수 없습니다 (grading_unapproved): {paths}\n"
            "의도한 변경이면 /gatekit:gate 를 다시 실행해 재승인하고, 아니면 "
            "변경을 되돌리세요."
        ),
    },
}


def _message(lang: str, key: str, **fields: Any) -> str:
    table = _MESSAGES.get(lang, _MESSAGES["en"])
    return table.get(key, _MESSAGES["en"][key]).format(**fields)


def _subject(root, pipeline: Optional[str]) -> Tuple[bool, Optional[str]]:
    """``(settled, job_id)`` for what the gate is judging (ADR-0024).

    Under ``verify`` there is no job: the subject is always settled. Under
    ``build`` it is the latest job, settled when every task's state is
    terminal; no job, or a job with no tasks, is not settled.
    """
    if pipeline != "build":
        return True, None
    job_id = jobs.latest_job_id(root)
    if not job_id:
        return False, None
    jdir = jobs.job_dir(root, job_id)
    job = jobs.read_json(jdir / "job.json", {}) or {}
    task_ids = [str(t) for t in (job.get("tasks") or [])] if isinstance(job, dict) else []
    if not task_ids:
        return False, job_id
    for task_id in task_ids:
        status = jobs.read_json(jdir / "tasks" / task_id / "status.json", {}) or {}
        state = status.get("state") if isinstance(status, dict) else None
        if state not in jobs.TERMINAL_STATES:
            return False, job_id
    return True, job_id


#: Task states that keep a settled job from being a handoff `ok`. `stopped`
#: is among them but does not block: `jobs stop` ended the job on purpose.
UNPASSED_STATES = tuple(jobs.NOT_DONE_STATES) + ("blocked",)


def _unpassed_tasks(root, job_id: Optional[str]) -> List[Tuple[str, str]]:
    """``[(task_id, state)]`` of a job's tasks that ended without passing."""
    if not job_id:
        return []
    jdir = jobs.job_dir(root, job_id)
    job = jobs.read_json(jdir / "job.json", {}) or {}
    task_ids = [str(t) for t in (job.get("tasks") or [])] if isinstance(job, dict) else []
    found = []
    for task_id in task_ids:
        status = jobs.read_json(jdir / "tasks" / task_id / "status.json", {}) or {}
        state = status.get("state") if isinstance(status, dict) else None
        if state in UNPASSED_STATES:
            found.append((task_id, str(state)))
    return found


def stand_down_applies(root, led: "ledger.Ledger") -> Optional[Dict[str, Any]]:
    """The recorded stand-down when it still applies, else ``None``.

    It applies while the pipeline is the one it was recorded under, the
    latest job is the same one and it is still settled. A new job or a
    redelegated task means the gate judges again.
    """
    stood = (led.data.get("stop") or {}).get("stood_down")
    pipeline = led.data.get("active_pipeline")
    if not isinstance(stood, dict) or pipeline not in ENFORCED_PIPELINES:
        return None
    if stood.get("pipeline") != pipeline:
        return None
    settled, job_id = _subject(led.root, pipeline)
    if not settled or stood.get("job_id") != job_id:
        return None
    return stood


def stand_down_line(root, led: "ledger.Ledger") -> str:
    """The prompt hook's context line about the Stop gate, else "".

    While a stand-down applies it names what was judged (the turn tier under
    ``build``) and how many criteria wait for ``/gatekit:verify``. Otherwise,
    while criteria the Stop budget left unjudged are on record, it names them.
    """
    lang = led.output_lang
    stood = stand_down_applies(root, led)
    if stood is None:
        stop_state = led.data.get("stop") if isinstance(led.data.get("stop"), dict) else {}
        pending = contract.budget_deferred_ids({"deferred": stop_state.get("deferred")})
        if pending and led.data.get("active_pipeline") in ENFORCED_PIPELINES:
            return _message(lang, "budget_pending", ids=", ".join(pending))
        if (led.data.get("active_pipeline") == "build" and contract.tier_scope(root)
                and not contract.tier_scope(root, BUILD_TIERS)):
            return _message(lang, "no_turn_tier_line")
        return ""
    extra = ""
    if stood.get("pipeline") == "build":
        scope = _message(lang, "stood_down_tier")
        held = len(contract.tier_scope(root)) - len(contract.tier_scope(root, BUILD_TIERS))
        if held > 0:
            extra = _message(lang, "stood_down_extra", count=held)
    else:
        scope = _message(lang, "stood_down_all")
    return _message(lang, "stood_down",
                    subject=stood.get("job_id") or stood.get("pipeline") or "?",
                    scope=scope, extra=extra,
                    verdict=stood.get("verdict") or verdict.UNVERIFIED)


def _stand_down(led: "ledger.Ledger", pipeline: str, job_id: Optional[str], final: str) -> None:
    """Record that the gate judges nothing more for this job (ADR-0024)."""
    stop_state = led.data.setdefault("stop", {})
    stop_state["stood_down"] = {"pipeline": pipeline, "job_id": job_id,
                                "verdict": final or verdict.UNVERIFIED,
                                "at": ledger._now(), "skipped": 0}
    led.append_event("stop_stood_down", {"pipeline": pipeline, "job_id": job_id,
                                         "verdict": final or verdict.UNVERIFIED})
    led.save()


def _nothing_in_scope(result: Dict[str, Any]) -> bool:
    return contract.NO_CRITERIA_IN_TIER_REASON in (result.get("reasons") or [])


def _only_budget_deferred(result: Dict[str, Any]) -> bool:
    """Everything that ran passed; the Stop budget left the rest unjudged."""
    reasons = result.get("reasons") or []
    return bool(reasons) and all(
        str(r).startswith(contract.BUDGET_DEFERRED_REASON) for r in reasons)


def _deferred_lines(lang: str, result: Dict[str, Any], budget_s: Optional[float]) -> List[str]:
    lines = []
    if _nothing_in_scope(result):
        lines.append(_message(lang, "no_turn_tier"))
    deferred = result.get("deferred") or []
    by_tier = [str(d.get("id")) for d in deferred if d.get("reason") == "tier"]
    by_budget = [str(d.get("id")) for d in deferred if d.get("reason") == "budget"]
    if by_tier:
        lines.append(_message(lang, "deferred_tier", ids=", ".join(by_tier)))
    if by_budget:
        lines.append(_message(lang, "deferred_budget", ids=", ".join(by_budget),
                              budget=float(budget_s or 0)))
    return lines


def _finish(led: "ledger.Ledger", final: str, reasons: Optional[List[str]] = None) -> None:
    """Record the outcome and allow the stop. ``final`` is never blank."""
    if not isinstance(led.data.get("stop"), dict):
        led.data["stop"] = ledger._blank_stop()
    stop_state = led.data["stop"]
    stop_state["final_verdict"] = final or verdict.UNVERIFIED
    if reasons is not None:
        stop_state["last_reasons"] = reasons
    led.append_event("stop_allowed", {"final_verdict": stop_state["final_verdict"]})
    led.save()


def _plan(root, pipeline: Optional[str]) -> Tuple[Optional[Tuple[str, ...]], Optional[float]]:
    """``(tiers, start_budget_s)`` for this pipeline (ADR-0024)."""
    if pipeline == "build":
        return BUILD_TIERS, config.stop_budget_s(config.load(root))[0]
    return None, None


def _judge(root, led: "ledger.Ledger", pipeline: Optional[str] = None) -> Dict[str, Any]:
    """Run the contract, or reuse the last result for an unchanged tree.

    ADR-0020: a Stop with no file changed since the last run judges that run
    again instead of re-proving it; any change runs the contract, last run's
    failures first. Only this gate reuses; `contract run` always executes.
    ADR-0024: under ``build`` only the turn tier runs, within
    ``stop.budget_s``; reuse needs a record of the same scope.
    """
    tiers, start_budget_s = _plan(root, pipeline)
    result = _judge_raw(root, led, tiers, start_budget_s)
    result["start_budget_s"] = start_budget_s
    led.data.setdefault("stop", {})["deferred"] = list(result.get("deferred") or [])
    return result


def _judge_raw(root, led: "ledger.Ledger", tiers, start_budget_s) -> Dict[str, Any]:
    # ADR-0027: the approval and the contract first, before any reuse.
    refused = contract.integrity(root)
    if refused is not None:
        return refused
    same_tree = contract.same_tree_record(root)
    if contract.covers(root, same_tree, tiers):
        result = dict(same_tree["result"])
        result["reused_from"] = same_tree.get("recorded_at")
        led.append_event("stop_reused", {"recorded_at": same_tree.get("recorded_at"),
                                         "verdict": result.get("verdict")})
        return result
    previous = contract.load_last(root) or {}
    data = contract.load(root) or {}
    first: List[str] = []
    deferred_first: List[str] = []
    if previous.get("source_sha256") == data.get("source_sha256"):
        last_result = previous.get("result") or {}
        first = [c.get("id") for c in (last_result.get("criteria") or [])
                 if c.get("verdict") in (verdict.FAIL, verdict.UNVERIFIED)]
        # Review of ADR-0024: what the budget left unjudged goes first, so
        # every Stop judges at least one criterion it has not judged yet.
        deferred_first = contract.budget_deferred_ids(last_result)
    result = contract.execute(root, cap_s=STOP_BUDGET_CAP_S, first=first,
                              tiers=tiers, start_budget_s=start_budget_s,
                              deferred_first=deferred_first)
    if same_tree is not None and contract.budget_deferred_ids(result):
        # Same tree as the last record: its verdicts for criteria this run
        # did not reach still hold.
        result = contract.carry_forward(result, same_tree["result"])
    if result.get("criteria"):
        try:
            contract.save_last(root, result)
        except OSError:  # a missing record only costs a re-run next time
            pass
    return result


def legacy_snapshot(led: "ledger.Ledger") -> List[str]:
    """The legacy plugin keys the session's first prompt recorded (ADR-0029
    amendment); ``[]`` before any prompt or for a malformed record."""
    keys = led.data.get("legacy_plugins")
    return [k for k in keys if isinstance(k, str)] if isinstance(keys, list) else []


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Run the contract when a build/verify pipeline is active and judge it."""
    root = hookio.event_root(event)
    # The plugin installs globally, so this hook fires in every project the
    # user opens. A project with no `.gatekit/` never asked gatekit to govern
    # it: stand down without creating state there.
    if not paths.state_dir(root).is_dir():
        return hookio.allow()
    led = ledger.Ledger.load(root, hookio.session_id(event))
    # ADR-0029: an older plugin of another name is enabled and runs its own
    # Stop gate on the same contract; this one yields. Only the snapshot the
    # prompt hook took at the session's first prompt counts (amendment): a
    # settings file written mid-session changes nothing, and no snapshot yet
    # means judge.
    if legacy_snapshot(led):
        return hookio.allow()
    lang = led.output_lang

    pipeline = led.data.get("active_pipeline")
    contract_present = paths.contract_file(root).is_file()

    # Nothing to enforce: allow, but still record a non-blank verdict.
    if pipeline not in ENFORCED_PIPELINES or not contract_present:
        _finish(led, verdict.UNVERIFIED)
        return hookio.allow()

    if not isinstance(led.data.get("stop"), dict):
        led.data["stop"] = ledger._blank_stop()
    stop_state = led.data["stop"]

    # ADR-0029 amendment: two state directories both hold approvals.json —
    # one may be forged (an archive, a link, a rename). Judge neither: block
    # with `unverified` (at most MAX_BLOCKS times, never trapping the session).
    several = names.approvals_in_several(root)
    if several:
        reason = _message(lang, "two_states", dirs=", ".join(d.name + "/" for d in several))
        _finish(led, verdict.UNVERIFIED, [reason])
        if bool(event.get("stop_hook_active")):
            return hookio.allow()
        try:
            block_count = int(stop_state.get("block_count", 0))
        except (TypeError, ValueError):
            block_count = 0
        if block_count >= MAX_BLOCKS:
            return hookio.allow()
        stop_state["block_count"] = block_count + 1
        led.append_event("stop_blocked", {"verdict": verdict.UNVERIFIED,
                                          "block_count": stop_state["block_count"],
                                          "why": "two_states"})
        led.save()
        return hookio.block_stop(reason)

    # ADR-0024: the job this gate was armed for already has its verdict.
    # Judge nothing; `final_verdict` keeps what was recorded.
    stood = stand_down_applies(root, led)
    if stood is not None:
        try:
            stood["skipped"] = int(stood.get("skipped", 0) or 0) + 1
        except (TypeError, ValueError):
            stood["skipped"] = 1
        led.save()
        return hookio.allow()
    if stop_state.get("stood_down"):
        # A new job, a redelegated task or another pipeline: judge again.
        stop_state["stood_down"] = None
        led.append_event("stop_stand_down_cleared", {"pipeline": pipeline})

    settled, job_id = _subject(root, pipeline)
    result: Dict[str, Any] = {"reasons": []}

    def settle(final: str, recorded: bool) -> None:
        """Allow, and stand down when a settled subject got its verdict."""
        _finish(led, final, result["reasons"])
        if recorded and settled:
            _stand_down(led, pipeline, job_id, final)

    result = _judge(root, led, pipeline)
    contract_clear = (result["verdict"] == verdict.OK or _nothing_in_scope(result)
                      or _only_budget_deferred(result))
    outcome = result["verdict"]

    # Review of ADR-0024: the handoff of a settled job is not `ok` while a task
    # in it ended without passing, whatever the contract says. `fail` when a
    # task failed, timed out or was stopped; `unverified` when it only has
    # tasks that never ran (`blocked`).
    gaps = _unpassed_tasks(root, job_id) if (settled and pipeline == "build") else []
    if gaps:
        if outcome == verdict.FAIL or any(st in jobs.NOT_DONE_STATES for _, st in gaps):
            outcome = verdict.FAIL
        else:
            outcome = verdict.UNVERIFIED
        result["reasons"] = [_message(
            lang, "tasks_line", job=job_id,
            tasks=", ".join("%s (%s)" % gap for gap in gaps))] + list(result["reasons"])
    blocking_gaps = [gap for gap in gaps if gap[1] != "stopped"]

    # Already inside a stop-hook continuation: never block again. Only an
    # `ok` here counts as the verdict, or one retry would end the judging.
    if bool(event.get("stop_hook_active")):
        settle(outcome, not gaps and (outcome == verdict.OK or _nothing_in_scope(result)))
        return hookio.allow()

    try:
        block_count = int(stop_state.get("block_count", 0))
    except (TypeError, ValueError):
        block_count = 0

    # Nothing in the selected tier: there is nothing here to fix, so blocking
    # would only stall. Recorded as `unverified`, never as `ok`.
    if not gaps and (outcome == verdict.OK or _nothing_in_scope(result)):
        settle(outcome, True)
        return hookio.allow()

    # Review of ADR-0024: the Stop budget left criteria unjudged and what ran
    # passed. There is nothing to fix, so no block (and no block spent), but
    # it is not `ok` either: `unverified` is recorded and the gate keeps
    # judging. The next Stop runs the deferred ones first, keeping what this
    # tree already judged, so it reaches a verdict in as many Stops as there
    # are criteria at most.
    if not gaps and _only_budget_deferred(result):
        settle(outcome, False)
        return hookio.allow()

    # A job ended with `jobs stop`: recorded as not done, but not blocked —
    # the user ended it on purpose and there is nothing left to run.
    if gaps and not blocking_gaps and contract_clear:
        settle(outcome, True)
        return hookio.allow()

    # Out of blocks: stand down rather than trap the session, but say plainly
    # that the work did not pass.
    if block_count >= MAX_BLOCKS:
        settle(outcome, True)
        return hookio.allow()

    stop_state["block_count"] = block_count + 1
    stop_state["last_reasons"] = result["reasons"]
    led.append_event(
        "stop_blocked",
        {"verdict": outcome, "block_count": stop_state["block_count"]},
    )
    led.save()

    if contract.STALE_REASON in result["reasons"]:
        return hookio.block_stop(_message(lang, "stale"))
    if contract.GRADING_UNAPPROVED_REASON in result["reasons"]:
        return hookio.block_stop(_message(
            lang, "unapproved", paths=", ".join(result.get("unapproved_grading") or [])))
    if contract.GATE_NOT_APPROVED_REASON in result["reasons"]:
        return hookio.block_stop(_message(
            lang, "not_approved", status=result.get("approval") or verdict.UNVERIFIED))
    if contract.CONTRACT_MISMATCH_REASON in result["reasons"]:
        diff = "; ".join(result.get("mismatch") or []) or "?"
        if len(diff) > 160:
            diff = diff[:159] + "…"
        return hookio.block_stop(_message(lang, "mismatch", diff=diff))
    if gaps and contract_clear:
        lines = [f"  - {line}" for line in result["reasons"]]
        lines += _deferred_lines(lang, result, result.get("start_budget_s"))
        return hookio.block_stop(_message(lang, "tasks_unpassed", job=job_id,
                                          reasons="\n".join(lines)))

    unmet = [
        item
        for item in result["criteria"]
        if item.get("verdict") in (verdict.FAIL, verdict.UNVERIFIED)
    ]
    reasons_text = "\n".join(f"  - {line}" for line in result["reasons"]) or "  - (no detail)"
    changed = sorted({str(p) for item in unmet
                      if str(item.get("detail") or "").startswith(contract.GRADING_MARKER)
                      for p in (item.get("grading_changed") or [])})
    if changed:
        # The reason line is cut at 120 characters; the instruction and the
        # full path list stand on their own here.
        reasons_text += "\n" + _message(lang, "grading_hint", paths=", ".join(changed))
    for line in _deferred_lines(lang, result, result.get("start_budget_s")):
        reasons_text += "\n" + line
    if result.get("reused_from"):
        reasons_text += "\n" + _message(lang, "reused", at=result["reused_from"])
    return hookio.block_stop(
        _message(
            lang,
            "blocked",
            count=len(unmet) or len(result["reasons"]),
            total=len(result["criteria"]) or len(result["reasons"]),
            reasons=reasons_text,
        )
    )


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()

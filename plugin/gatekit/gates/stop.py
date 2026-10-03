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
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import contract, hookio, ledger, paths, verdict  # noqa: E402

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
STOP_BUDGET_CAP_S = 570.0

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


def _finish(led: "ledger.Ledger", final: str, reasons: Optional[List[str]] = None) -> None:
    """Record the outcome and allow the stop. ``final`` is never blank."""
    stop_state = led.data.setdefault(
        "stop", {"block_count": 0, "final_verdict": None, "last_reasons": []}
    )
    stop_state["final_verdict"] = final or verdict.UNVERIFIED
    if reasons is not None:
        stop_state["last_reasons"] = reasons
    led.append_event("stop_allowed", {"final_verdict": stop_state["final_verdict"]})
    led.save()


def _judge(root, led: "ledger.Ledger") -> Dict[str, Any]:
    """Run the contract, or reuse the last result for an unchanged tree.

    ADR-0020: a Stop with no file changed since the last run judges that run
    again instead of re-proving it; any change runs the contract, last run's
    failures first. Only this gate reuses; `contract run` always executes.
    """
    last = contract.reusable_last(root)
    if last is not None:
        result = dict(last["result"])
        result["reused_from"] = last.get("recorded_at")
        led.append_event("stop_reused", {"recorded_at": last.get("recorded_at"),
                                         "verdict": result.get("verdict")})
        return result
    previous = contract.load_last(root) or {}
    data = contract.load(root) or {}
    first: List[str] = []
    if previous.get("source_sha256") == data.get("source_sha256"):
        first = [c.get("id") for c in ((previous.get("result") or {}).get("criteria") or [])
                 if c.get("verdict") in (verdict.FAIL, verdict.UNVERIFIED)]
    result = contract.execute(root, cap_s=STOP_BUDGET_CAP_S, first=first)
    if result.get("criteria"):
        try:
            contract.save_last(root, result)
        except OSError:  # a missing record only costs a re-run next time
            pass
    return result


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Run the contract when a build/verify pipeline is active and judge it."""
    root = hookio.event_root(event)
    # The plugin installs globally, so this hook fires in every project the
    # user opens. A project with no `.gatekit/` never asked gatekit to govern
    # it: stand down without creating state there.
    if not paths.state_dir(root).is_dir():
        return hookio.allow()

    led = ledger.Ledger.load(root, hookio.session_id(event))
    lang = led.output_lang

    pipeline = led.data.get("active_pipeline")
    contract_present = paths.contract_file(root).is_file()

    # Nothing to enforce: allow, but still record a non-blank verdict.
    if pipeline not in ENFORCED_PIPELINES or not contract_present:
        _finish(led, verdict.UNVERIFIED)
        return hookio.allow()

    # Already inside a stop-hook continuation: never block again.
    if bool(event.get("stop_hook_active")):
        result = _judge(root, led)
        _finish(led, result["verdict"], result["reasons"])
        return hookio.allow()

    stop_state = led.data.setdefault(
        "stop", {"block_count": 0, "final_verdict": None, "last_reasons": []}
    )
    try:
        block_count = int(stop_state.get("block_count", 0))
    except (TypeError, ValueError):
        block_count = 0

    result = _judge(root, led)
    outcome = result["verdict"]

    if outcome == verdict.OK:
        _finish(led, outcome, result["reasons"])
        return hookio.allow()

    # Out of blocks: stand down rather than trap the session, but say plainly
    # that the work did not pass.
    if block_count >= MAX_BLOCKS:
        _finish(led, outcome, result["reasons"])
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

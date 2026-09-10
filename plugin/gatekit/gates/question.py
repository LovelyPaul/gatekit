"""PostToolUse gate for AskUserQuestion — count questions against a budget.

An interview that keeps asking is an interview that never delivers. The gate
counts every AskUserQuestion call in the session and raises
``questions.budget_exceeded`` once the count passes the pipeline's allowance.

The flag is **informational**. PostToolUse has no block channel, and pretending
otherwise would be prose enforcement. Commands read the flag and change their
own behaviour: the interview pipeline is expected to stop asking and write its
assumptions into the ledger instead.

Only the ``interview`` pipeline is budgeted (2 calls by default, configurable
via ``questions.interview_max_calls``). Other pipelines ask as needed.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import config, hookio, ledger  # noqa: E402

#: The only pipeline with a question ceiling.
BUDGETED_PIPELINE = "interview"

#: The ledger schema default; a ledger holding this value has not been
#: deliberately overridden by a command.
DEFAULT_MAX_CALLS = 2


def budget_for(
    cfg: Dict[str, Any],
    pipeline: Optional[str],
    session_limit: Optional[Any] = None,
) -> Optional[int]:
    """Maximum AskUserQuestion calls for *pipeline*, or ``None`` for unlimited.

    A ``max_calls`` already recorded in the ledger wins over the configured
    default: a command may tighten (or loosen) the budget for one session, and
    recomputing it from config on every call would silently erase that.
    """
    if pipeline != BUDGETED_PIPELINE:
        return None
    if session_limit is not None:
        try:
            return int(session_limit)
        except (TypeError, ValueError):
            pass
    try:
        return int(cfg.get("questions", {}).get("interview_max_calls", 2))
    except (TypeError, ValueError):
        return 2


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Increment the counter and flag a blown budget. Never blocks."""
    root = hookio.event_root(event)
    led = ledger.Ledger.load(root, hookio.session_id(event))

    questions = led.data.setdefault(
        "questions", {"asked": 0, "max_calls": 2, "budget_exceeded": False}
    )
    try:
        asked = int(questions.get("asked", 0)) + 1
    except (TypeError, ValueError):
        asked = 1
    questions["asked"] = asked

    pipeline = led.data.get("active_pipeline")
    # A blank ledger carries the schema default (2); only a value a command
    # deliberately changed counts as a session override.
    recorded = questions.get("max_calls")
    session_limit = recorded if recorded != DEFAULT_MAX_CALLS else None
    limit = budget_for(config.load(root), pipeline, session_limit)
    if limit is not None:
        questions["max_calls"] = limit
        if asked > limit:
            questions["budget_exceeded"] = True

    led.append_event(
        "question_asked",
        {"asked": asked, "pipeline": pipeline, "max_calls": limit},
    )
    led.save()
    return hookio.allow()


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()

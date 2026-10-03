"""UserPromptSubmit gate — bootstrap the session and tell Claude the rules.

This gate never blocks. It does two things on every prompt:

1. **Ensures a ledger exists** for the session and refreshes ``output_lang``
   from the prompt text, so the language decision is made once, from the user's
   own words, and every later gate and command reads the same answer.
2. **Injects a short context block** (≤ 600 characters) naming the output
   language, the active pipeline, the question budget and the number of
   unresolved gate items — the state Claude would otherwise have to guess at.

3. **Records the active pipeline.** A prompt that invokes ``/gatekit:<name>``
   sets ``active_pipeline`` in the ledger; that field is what arms the stop
   gate (build/verify) and the question budget (interview). It is set here, by
   code, because a command's prose asking Claude to "remember" the pipeline
   is exactly the kind of instruction that fires nondeterministically.

An empty prompt leaves the stored language alone: submitting a blank line is
not evidence that the user switched to English. Until some prompt in the
session carries a signal, the spec's language stands in (ADR-0026).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import approval, contract, hookio, lang, ledger, paths  # noqa: E402


#: Pipelines whose invocation re-arms the Stop gate (ADR-0024).
STOP_ARMING_PIPELINES = ("build", "verify")

#: Commands that are not pipelines. Invoking one clears ``active_pipeline`` so
#: a stop gate armed by an earlier ``/gatekit:build`` does not outlive it.
NON_PIPELINE_COMMANDS = ("doctor", "setup")

#: A ``/gatekit:<name>`` invocation is recognised only where Claude Code puts
#: it. For a slash command the prompt body is the tagged form
#: ``<command-message>…</command-message>\n<command-name>/gatekit:<name></command-name>\n<command-args>…``
#: (observed in session transcripts); the bare ``/gatekit:<name>`` at the
#: start of a prompt, the ``# /gatekit:<name>`` title line of an expanded
#: command body, and Codex's ``$gatekit-<name>`` skill invocation are
#: accepted too. A mention mid-sentence is conversation, not
#: an invocation.
_INVOCATION_RE = re.compile(
    r"(?:<command-name>\s*/gatekit:([a-z-]+)\s*</command-name>)"
    r"|(?:^\s*(?:#\s+)?/gatekit:([a-z-]+)\b)"
    r"|(?:^\s*(?:#\s+)?\$gatekit-([a-z-]+)\b)",
    re.MULTILINE,
)
#: Only the leading lines of the prompt are inspected.
_HEAD_LINES = 12


_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
_SKILL_PREFIX_RE = re.compile(r"^\s*\$gatekit-[a-z-]+\b")


def language_signal(text: str) -> str:
    """The part of *text* that is the user's own words.

    For a slash command Claude Code sends a tagged body; the tags and the
    command name are Latin letters that would drag a Korean session to
    English. Only the ``<command-args>`` content is the user's language.
    """
    if "<command-name>" in text:
        match = _ARGS_RE.search(text)
        return match.group(1) if match else ""
    # Codex skill syntax: the name is an identifier, the rest is the user's.
    return _SKILL_PREFIX_RE.sub("", text, count=1)


def detect_command(text: str) -> Optional[str]:
    """Return the ``/gatekit:<name>`` command this prompt invokes, if any."""
    head = "\n".join(text.splitlines()[:_HEAD_LINES])
    match = _INVOCATION_RE.search(head)
    if not match:
        return None
    return match.group(1) or match.group(2) or match.group(3)


def apply_command(led: "ledger.Ledger", text: str) -> None:
    """Update ``active_pipeline`` from the command the prompt invokes.

    Pipelines set it, ``doctor``/``setup`` clear it, an unknown name is left
    alone (a typo must not disarm a running build), and a plain prompt keeps
    whatever was active.
    """
    name = detect_command(text)
    if name is None:
        return
    if name in ledger.PIPELINES:
        led.set_pipeline(name)
        if name in STOP_ARMING_PIPELINES:
            # ADR-0024: invoking build/verify — again included — is the user
            # asking for a judgement, so a stand-down from an earlier verdict
            # and its spent blocks do not carry over.
            led.rearm_stop()
    elif name in NON_PIPELINE_COMMANDS:
        led.set_pipeline(None)


def _gate_state(root) -> str:
    """One-word summary of whether the completion gate is settled."""
    gate_md = paths.spec_dir(root) / "05-gate.md"
    if not gate_md.is_file():
        return "no gate spec"
    status = approval.check_gate(root)[0]
    if status == "ok":
        return "gate approved"
    if status == "fail":
        return "gate approval STALE (re-approve)"
    return "gate NOT approved"


def build_context(root, led: "ledger.Ledger") -> str:
    """Compose the ≤600 char context block injected into the conversation."""
    questions = led.data.get("questions", {})
    asked = questions.get("asked", 0)
    max_calls = questions.get("max_calls", 2)
    pipeline = led.data.get("active_pipeline") or "none"

    # ADR-0012: the raw count is the weakest of the question signals, so the
    # ones that mean something ride alongside it when they are non-zero.
    flags = []
    for key, word in (("unjustified", "unjustified"), ("repeated", "repeat"),
                      ("unrealized", "unrealized")):
        try:
            count = int(questions.get(key, 0) or 0)
        except (TypeError, ValueError):
            continue
        if count:
            flags.append(f"{count} {word}")
    if questions.get("implementation_choice"):
        flags.append("impl-choice")
    question_line = f"questions={asked}/{max_calls}"
    if flags:
        question_line += " (" + ", ".join(flags) + ")"

    parts: List[str] = [
        f"gatekit: output_lang={led.output_lang} (reply in this language;"
        " never translate identifiers)",
        f"pipeline={pipeline}",
    ]
    # ADR-0024: say so while the Stop gate judges nothing. Early in the line,
    # so the 600-character cut never drops it.
    stood_down = _stand_down_line(root, led)
    if stood_down:
        parts.append(stood_down)
    parts += [question_line, _gate_state(root)]

    contract_status = contract.status(root)
    if contract_status != "unverified":
        scope = _contract_scope(root, led.output_lang) if contract_status == "ok" else ""
        parts.append(f"contract={contract_status}{scope}")

    # ADR-0013 decision 1a: a build under host execution lives in this session,
    # so a compaction can take the narrative with it. Name the live job and the
    # next task; spec/PROGRESS.md holds the rest (written by the PreCompact
    # hook). An unfinished job is the only one worth reporting.
    build = _live_build(root, led.output_lang)
    if build:
        parts.append(build)

    return " | ".join(parts)


#: ADR-0026: what the last recorded result left unjudged. `contract=ok` alone
#: says the contract matches the approved gate file; next to a stand-down it
#: read as "fully verified" while verify-tier criteria had not run.
_SCOPE = {
    "en": {"tier": "turn tier; {count} deferred to /gatekit:verify",
           "other": "{count} unjudged"},
    "ko": {"tier": "turn 등급만; {count}개는 /gatekit:verify 로 미룸",
           "other": "{count}개 미판정"},
}


def _contract_scope(root, lang: str = "en") -> str:
    """`` (turn tier; N deferred to /gatekit:verify)`` when the last recorded
    result for this contract did not judge every criterion, else ""."""
    try:
        last = contract.load_last(root)
        data = contract.load(root)
        if not last or not data or last.get("source_sha256") != data.get("source_sha256"):
            return ""
        judged = {str(i) for i in (last.get("scope") or [])}
        unjudged = [i for i in contract.tier_scope(root) if i not in judged]
        if not unjudged:
            return ""
        verify_tier = set(contract.tier_scope(root, ("verify",)))
        held = sum(1 for i in unjudged if i in verify_tier)
        other = len(unjudged) - held
        table = _SCOPE.get(lang, _SCOPE["en"])
        pieces = []
        if held:
            pieces.append(table["tier"].format(count=held))
        if other:
            pieces.append(table["other"].format(count=other))
        return " (" + "; ".join(pieces) + ")"
    except Exception:
        # The context line is a convenience; never let it break the hook.
        return ""


def _lang_from_spec(root, led: "ledger.Ledger") -> None:
    try:
        found = lang.from_spec(root)
    except Exception:
        # A convenience; never let it break the hook.
        return
    if found:
        led.set_output_lang(found, source="spec")


def _stand_down_line(root, led: "ledger.Ledger") -> str:
    try:
        from gatekit.gates import stop as stop_gate

        return stop_gate.stand_down_line(root, led)
    except Exception:
        # The context line is a convenience; never let it break the hook.
        return ""


#: Review of ADR-0024: a host job whose tasks stay `queued` never settles, so
#: the Stop gate keeps judging every turn. Say how to end it.
_UNFINISHED = {
    "en": "build job unfinished: {count} tasks queued — `jobs stop` ends judging",
    "ko": "빌드 잡 미완료: 대기 {count}개 — `jobs stop` 으로 판정 종료",
}


def _live_build(root, lang: str = "en") -> str:
    """``build=<job> n/m passed, next: <task>`` for an unfinished job, else ""."""
    try:
        from gatekit import jobs

        job_id = jobs.latest_job_id(root)
        if not job_id:
            return ""
        jdir = jobs.job_dir(root, job_id)
        job = jobs.read_json(jdir / "job.json", None)
        if not isinstance(job, dict) or job.get("finished_at"):
            return ""
        task_ids = [str(t) for t in (job.get("tasks") or [])]
        if not task_ids:
            return ""
        passed, queued, next_task = 0, 0, ""
        for task_id in task_ids:
            state = str((jobs.read_json(
                jdir / "tasks" / task_id / "status.json", {}) or {}).get("state", "queued"))
            if state == "passed":
                passed += 1
            elif not next_task:
                next_task = task_id
            if state == "queued":
                queued += 1
        line = "build=%s %d/%d passed" % (job_id, passed, len(task_ids))
        if next_task:
            line += ", next: %s" % next_task
        if queued:
            line += "; " + _UNFINISHED.get(lang, _UNFINISHED["en"]).format(count=queued)
        return line
    except Exception:
        # The context line is a convenience; never let it break the hook.
        return ""


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Refresh the ledger from this prompt and return the context payload."""
    root = hookio.event_root(event)
    # The plugin installs globally, so this hook fires in every project the
    # user opens. A project with no `.gatekit/` never asked gatekit to govern
    # it: stand down without creating state there.
    if not paths.state_dir(root).is_dir():
        return hookio.allow()

    session = hookio.session_id(event)
    text = event.get("prompt")
    text = text if isinstance(text, str) else ""

    led = ledger.Ledger.load(root, session)

    # Keep the stored language unless this prompt actually says something
    # about which language the user is writing in. An empty prompt carries no
    # signal; neither does "1", "2." or a bare path, which are the same
    # keystrokes in either language. That last case is not an edge case under
    # Codex: with no `AskUserQuestion` there, commands ask their options as
    # numbered plain chat, so a Korean interview answered "1" used to flip to
    # English and stay there (observed on a real Codex run, 2026-09-27).
    # A slash command's tag body is not the user's words either: only the
    # <command-args> content counts.
    signal = language_signal(text)
    if lang.carries_signal(signal):
        led.set_output_lang(lang.detect(signal), source="prompt")
    elif led.data.get("lang_source") != "prompt":
        # ADR-0026: no prompt has said anything yet — a bare `/gatekit:build`
        # left a Korean project reporting in English. The spec the user wrote
        # stands in until their own words arrive.
        _lang_from_spec(root, led)

    apply_command(led, text)

    led.append_event("prompt", {"chars": len(text)})
    led.save()

    return hookio.add_context(build_context(root, led))


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()

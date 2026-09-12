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
not evidence that the user switched to English.
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
    elif name in NON_PIPELINE_COMMANDS:
        led.set_pipeline(None)


def _gate_state(root) -> str:
    """One-word summary of whether the completion gate is settled."""
    gate_md = paths.spec_dir(root) / "05-gate.md"
    if not gate_md.is_file():
        return "no gate spec"
    status = approval.check(root, "spec/05-gate.md")
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

    parts: List[str] = [
        f"gatekit: output_lang={led.output_lang} (reply in this language;"
        " never translate identifiers)",
        f"pipeline={pipeline}",
        f"questions={asked}/{max_calls}",
        _gate_state(root),
    ]

    contract_status = contract.status(root)
    if contract_status != "unverified":
        parts.append(f"contract={contract_status}")

    return " | ".join(parts)


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Refresh the ledger from this prompt and return the context payload."""
    root = hookio.event_root(event)
    session = hookio.session_id(event)
    text = event.get("prompt")
    text = text if isinstance(text, str) else ""

    led = ledger.Ledger.load(root, session)

    # An empty prompt carries no language signal, so keep what we had. A
    # slash command's tag body is not the user's words either: only the
    # <command-args> content counts, and empty args keep the stored language.
    signal = language_signal(text)
    if signal.strip():
        led.set_output_lang(lang.detect(signal))

    apply_command(led, text)

    led.append_event("prompt", {"chars": len(text)})
    led.save()

    return hookio.add_context(build_context(root, led))


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()

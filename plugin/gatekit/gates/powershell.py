"""PreToolUse gate for Claude Code's PowerShell tool (ADR-0028).

The PowerShell tool's calls do not match the ``Bash`` matcher, and its text is
not shell syntax, so without this gate every rule the Bash gate enforces was a
convention on Windows, where PowerShell is the primary shell. This gate reads
the command with :mod:`gatekit.pwsh` into the record the Bash reader fills and
runs the Bash gate's sequence on it, in the same order:

1. inside a worker (``GATEKIT_TASK_ID`` set), a command that runs gatekit's
   ``approve`` is denied (ADR-0023);
2. gatekit's protected state is checked always, also after approval
   (ADR-0027, :func:`gatekit.gates.bash.protected_hit`);
3. while no restriction is active nothing else is judged;
4. otherwise each target goes to :func:`gatekit.gates.write.decide_path`
   (spec before code, task ``write_scope``, the evaluator's scratch), and a
   command whose writes cannot be read is denied as ``opaque``.

Denial reasons are written in the session's ``output_lang``.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import hookio, pwsh  # noqa: E402
from gatekit.gates import bash, write  # noqa: E402

#: The tool name Claude Code sends in ``tool_name`` (code.claude.com/docs/en/hooks).
TOOL_NAME = "PowerShell"

_MESSAGES = {
    "en": {
        "opaque": (
            "gatekit: cannot determine which files this PowerShell command writes "
            "({why}), and writes are currently restricted. Use the Write/Edit tool, "
            "or a plain cmdlet whose -Path is literal. Command: {cmd}"
        ),
        "approve": (
            "gatekit: a worker never approves. This PowerShell command runs gatekit's "
            "'approve' subcommand inside a worker session (GATEKIT_TASK_ID={task}); "
            "approval is the user's decision, taken in the host session through "
            "/gatekit:gate. 'approve check' and 'approve list' are allowed. Command: {cmd}"
        ),
    },
    "ko": {
        "opaque": (
            "gatekit: 이 PowerShell 명령이 어떤 파일을 쓰는지 판별할 수 없고({why}) "
            "현재 쓰기가 제한된 상태입니다. Write/Edit 도구를 쓰거나 -Path 가 리터럴인 "
            "cmdlet 을 사용하세요. 명령: {cmd}"
        ),
        "approve": (
            "gatekit: 워커는 승인하지 않습니다. 이 PowerShell 명령은 워커 세션"
            "(GATEKIT_TASK_ID={task}) 안에서 gatekit의 'approve' 하위 명령을 "
            "실행합니다. 승인은 사용자의 결정이며 호스트 세션에서 /gatekit:gate로 "
            "합니다. 'approve check'와 'approve list'는 허용됩니다. 명령: {cmd}"
        ),
    },
}


def _message(lang: str, key: str, **fields: Any) -> str:
    table = _MESSAGES.get(lang, _MESSAGES["en"])
    return table.get(key, _MESSAGES["en"][key]).format(**fields)


def _shown(command: str) -> str:
    shown = command.strip().replace("\r", " ").replace("\n", " ")
    return shown if len(shown) <= 120 else shown[:119] + "…"


def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Judge every file this PowerShell command would write."""
    if event.get("tool_name") != TOOL_NAME:
        return hookio.allow()
    tool_input = event.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return hookio.allow()

    root = hookio.event_root(event)
    task_id = os.environ.get("GATEKIT_TASK_ID")
    if task_id and pwsh.invokes_gatekit_approve(command):
        return hookio.deny(_message(write.session_lang(root, event), "approve",
                                    task=task_id, cmd=_shown(command)))

    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    found = pwsh.read(command, cwd or str(root))
    hit = bash.protected_hit(root, pwsh.mention_text(command, found), found)
    if hit:
        return write.deny_protected(hit, write.session_lang(root, event))

    if not write.restrictions_active(root):
        return hookio.allow()

    lang = write.session_lang(root, event)
    for target in found.targets:
        decision = write.decide_path(root, target, lang)
        if decision is not None:
            return decision
    if found.opaque:
        return hookio.deny(_message(lang, "opaque", why=found.why, cmd=_shown(command)))
    return hookio.allow()


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()

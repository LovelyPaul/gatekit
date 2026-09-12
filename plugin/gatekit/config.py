"""Project configuration: ``.gatekit/config.json`` with defaults.

A missing or corrupt config file must never stop a gate, so :func:`load` always
returns a complete, usable dictionary: the file is deep-merged onto
:data:`DEFAULTS` and anything unparseable falls back to the defaults entirely.

Sandboxing is never disabled by default. A backend that passes a bypass flag has
to say so explicitly with ``"unsafe": true``, and the job receipt records it.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import tempfile
from typing import Any, Dict

from . import paths

DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "enforce_spec_before_code": True,
    "worker": {
        "default": "claude",
        "backends": {
            "claude": {
                "argv": [
                    "claude",
                    "-p",
                    "--output-format",
                    "json",
                    "--permission-mode",
                    "acceptEdits",
                ],
                "enabled": True,
            },
            "codex": {
                "argv": ["codex", "exec", "--sandbox", "workspace-write"],
                "enabled": False,
            },
        },
    },
    "build": {"max_retries": 2, "parallel": 3, "task_timeout_s": 900},
    "questions": {"interview_max_calls": 2, "items_per_call": 4},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge *override* onto a copy of *base*.

    Dictionaries merge key by key; every other value (lists included) is
    replaced wholesale. Replacing lists is deliberate: a user who writes an
    ``argv`` means that exact command line, not the default with extras.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load(root: pathlib.Path) -> Dict[str, Any]:
    """Return the effective config for the project at *root*.

    Always a fresh deep copy, so callers may mutate the result without
    poisoning :data:`DEFAULTS` for the rest of the process.
    """
    target = paths.config_file(root)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        return copy.deepcopy(DEFAULTS)
    return _deep_merge(DEFAULTS, raw)


def save(root: pathlib.Path, cfg: Dict[str, Any]) -> None:
    """Write *cfg* to ``.gatekit/config.json`` atomically."""
    target = paths.config_file(root)
    write_json_atomic(target, cfg)


def write_json_atomic(target: pathlib.Path, payload: Any) -> None:
    """Serialize *payload* to *target* via a temp file plus ``os.replace``.

    Shared by every module that persists JSON state. A crash mid-write leaves
    the previous file intact rather than a truncated one; the temp file is
    created in the destination directory so the replace stays on one filesystem.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    write_text_atomic(target, text + "\n")


def write_text_atomic(target: pathlib.Path, text: str) -> None:
    """Write *text* to *target* via a temp file plus ``os.replace``."""
    target = pathlib.Path(target)
    paths.ensure_dir(target.parent)
    handle, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp_name, str(target))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

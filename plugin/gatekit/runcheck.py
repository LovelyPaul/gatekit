"""What a command's output says about whether it could judge anything (ADR-0022).

Two questions the gate runners ask of a finished command, kept here so that
`jobs.run_gates`, the preflight classifier and `contract` answer them the same
way:

* **Did it run any tests?** A runner that found nothing to run often exits 0.
  :func:`ran_no_tests` names the matching signature from
  ``plugin/spec-kit/no-tests-signatures.json``, and the caller reports
  ``unverified`` instead of ``ok``.
* **Is the path it could not find one a task will write?** :func:`missing_paths`
  extracts paths named as missing, :func:`relativize` maps them into the
  project, and :func:`scope_owner` names the task whose ``write_scope`` covers
  one, using the write gate's own glob matcher.

Pure functions over strings and task dicts; nothing here runs a command.
"""
from __future__ import annotations

import functools
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional

from gatekit import paths

SIGNATURES_FILE = "no-tests-signatures.json"


@functools.lru_cache(maxsize=1)
def _signatures() -> tuple:
    """Compiled signatures; an unreadable or malformed file means none."""
    try:
        path = paths.plugin_root() / "spec-kit" / SIGNATURES_FILE
        data = json.loads(path.read_text(encoding="utf-8"))
        compiled = []
        for sig in data.get("signatures") or []:
            exits = tuple(int(e) for e in sig.get("exits") or [0])
            compiled.append((str(sig["id"]),
                             re.compile(sig["pattern"], re.MULTILINE),
                             re.compile(sig["positive"], re.MULTILINE),
                             exits))
        return tuple(compiled)
    except (OSError, ValueError, KeyError, TypeError, re.error):
        return ()


def ran_no_tests(stdout: Any, stderr: Any, exit_code: Any) -> Optional[str]:
    """The id of the "ran no tests" signature this output matches, or None.

    A match needs one signature's pattern with *exit_code* in its exits, and
    no signature's positive-count pattern anywhere in the output — so a run
    that reports any real tests is never called empty.
    """
    sigs = _signatures()
    if not sigs or not isinstance(exit_code, int):
        return None
    text = "%s\n%s" % (stdout or "", stderr or "")
    if any(positive.search(text) for _, _, positive, _ in sigs):
        return None
    for sig_id, pattern, _, exits in sigs:
        if exit_code in exits and pattern.search(text):
            return sig_id
    return None


#: Lines that name a path the command could not find. Each has one group, the
#: path. `No module named` names a module, not a path, and is not here.
_MISSING_PATH_PATTERNS = (
    re.compile(r"ENOENT: no such file or directory, (?:open|stat|lstat|scandir|access|"
               r"realpath|readlink|opendir|chdir|uv_cwd) '([^']+)'", re.IGNORECASE),
    re.compile(r"can't open file '([^']+)'"),
    re.compile(r"No such file or directory: '([^']+)'"),
    re.compile(r"(?:^|\s)([^\s:'\"\[\]]+): No such file or directory", re.MULTILINE),
)
#: npm's own message when the project has no manifest: the runner cannot start.
_MISSING_MANIFEST = re.compile(r"Could not read package\.json")


def missing_paths(text: Any) -> List[str]:
    """Paths *text* names as missing, in order of appearance, each once."""
    text = str(text or "")
    hits = []
    for pattern in _MISSING_PATH_PATTERNS:
        for match in pattern.finditer(text):
            # Python prints paths through repr(), doubling each backslash.
            raw = match.group(1).replace("\\\\", "\\").strip()
            if raw:
                hits.append((match.start(1), raw))
    ordered: List[str] = []
    for _, raw in sorted(hits):
        if raw not in ordered:
            ordered.append(raw)
    return ordered


def is_missing_manifest(text: Any) -> bool:
    """True when npm says it cannot read the project's package.json."""
    return bool(_MISSING_MANIFEST.search(str(text or "")))


_DRIVE = re.compile(r"^[A-Za-z]:/")


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def relativize(raw: str, root: Any) -> Optional[str]:
    """*raw* as a POSIX path relative to *root*, or None outside it.

    Textual, so a Windows message is understood on any host: backslashes
    become slashes and a drive letter compares case-insensitively. A relative
    *raw* is already relative to the root, which is every gate's cwd.
    """
    path = _norm(str(raw or "").strip())
    if not path:
        return None
    if path.startswith("/") or _DRIVE.match(path):
        roots = {_norm(str(root)).rstrip("/")}
        try:
            roots.add(_norm(os.path.realpath(str(root))).rstrip("/"))
        except (OSError, ValueError):
            pass
        for base in sorted(roots, key=len, reverse=True):
            if not base:
                continue
            if _DRIVE.match(base):
                if path.lower().startswith(base.lower() + "/"):
                    path = path[len(base) + 1:]
                    break
            elif path.startswith(base + "/"):
                path = path[len(base) + 1:]
                break
        else:
            return None
    while path.startswith("./"):
        path = path[2:]
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def _scope_globs(task: Dict[str, Any]) -> List[str]:
    scope = task.get("write_scope") if isinstance(task, dict) else None
    if isinstance(scope, str):
        return [] if scope == "read-only" else [scope]
    if isinstance(scope, list):
        return [g for g in scope if isinstance(g, str) and g.strip()]
    return []


def scope_owner(relpath: str, tasks: Optional[Iterable[Dict[str, Any]]]) -> Optional[str]:
    """The id of the first task whose write_scope covers *relpath*.

    Uses the write gate's matcher, so "covered" means exactly what the write
    gate would let that task write.
    """
    from gatekit.gates import write  # lazy: the hook module pulls in more

    for task in tasks or []:
        for glob in _scope_globs(task):
            if write.matches(relpath, glob):
                return str(task.get("id"))
    return None


def missing_path_owner(gate: Dict[str, Any], root: Any,
                       tasks: Optional[Iterable[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """``{"path", "owner", "manifest"}`` for a failing gate's missing path.

    The first extracted path that a task covers wins; otherwise the first
    extracted path is reported with ``owner`` None (relative when inside the
    root, as printed when not). None when the output names no missing path.
    """
    text = "%s\n%s" % (gate.get("stdout_tail") or "", gate.get("stderr_tail") or "")
    raws = missing_paths(text)
    if not raws:
        return None
    manifest = is_missing_manifest(text)
    tasks = list(tasks or [])
    first = None
    for raw in raws:
        rel = relativize(raw, root)
        shown = rel if rel is not None else raw
        if first is None:
            first = shown
        owner = scope_owner(rel, tasks) if rel is not None else None
        if owner:
            return {"path": rel, "owner": owner, "manifest": manifest}
    return {"path": first, "owner": None, "manifest": manifest}

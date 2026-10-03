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
import hashlib
import json
import ntpath
import os
import posixpath
import re
from typing import Any, Dict, Iterable, List, Optional

from gatekit import paths

SIGNATURES_FILE = "no-tests-signatures.json"


def _signatures_path():
    return paths.plugin_root() / "spec-kit" / SIGNATURES_FILE


def _compile_signature(sig: Any) -> Optional[tuple]:
    """One entry as ``(id, pattern, positive, exits)``, or None when malformed.

    Exits must be a list of integers (``true`` is not an exit code); a missing
    list means ``[0]``.
    """
    if not isinstance(sig, dict):
        return None
    sig_id, pattern, positive = sig.get("id"), sig.get("pattern"), sig.get("positive")
    if not (isinstance(sig_id, str) and sig_id and isinstance(pattern, str) and pattern
            and isinstance(positive, str) and positive):
        return None
    exits = sig.get("exits", [0])
    if exits is None:
        exits = [0]
    if not isinstance(exits, list) or not exits or not all(
            isinstance(e, int) and not isinstance(e, bool) for e in exits):
        return None
    try:
        return (sig_id, re.compile(pattern, re.MULTILINE),
                re.compile(positive, re.MULTILINE), tuple(exits))
    except (re.error, TypeError, ValueError, OverflowError):
        return None


@functools.lru_cache(maxsize=1)
def _signatures() -> tuple:
    """Compiled signatures. An unreadable or structurally malformed file means
    none; a malformed entry is skipped and the rest still apply."""
    try:
        data = json.loads(_signatures_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ()
    entries = data.get("signatures") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return ()
    return tuple(c for c in (_compile_signature(e) for e in entries) if c is not None)


def signatures_digest() -> Optional[str]:
    """SHA-256 of the signature file's bytes, or None when it cannot be read.

    Recorded with the Stop gate's last result so a result judged under other
    signatures (e.g. before 0.14.0) is never reused.
    """
    try:
        return hashlib.sha256(_signatures_path().read_bytes()).hexdigest()
    except (OSError, ValueError):
        return None


#: Terminal colour and cursor escapes; runners add them under a TTY or when
#: forced (FORCE_COLOR, --color=yes), and they split the anchored patterns.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: Any) -> str:
    return _ANSI.sub("", str(text or ""))


def ran_no_tests(stdout: Any, stderr: Any, exit_code: Any) -> Optional[str]:
    """The id of the "ran no tests" signature this output matches, or None.

    A match needs one signature's pattern with *exit_code* in its exits, and
    no signature's positive-count pattern anywhere in the output — so a run
    that reports any real tests is never called empty. ANSI escapes are
    stripped first.
    """
    sigs = _signatures()
    if not sigs or not isinstance(exit_code, int) or isinstance(exit_code, bool):
        return None
    text = strip_ansi("%s\n%s" % (stdout or "", stderr or ""))
    if any(positive.search(text) for _, _, positive, _ in sigs):
        return None
    for sig_id, pattern, _, exits in sigs:
        if exit_code in exits and pattern.search(text):
            return sig_id
    return None


#: Lines that name a path the command could not find. Each has one group, the
#: path. `No module named` names a module, not a path, and is not here. The
#: shell form (`<prog>: <path>: No such file or directory`) needs the path to
#: open the line or follow a `<prog>: ` prefix and to hold no space: a path
#: with spaces is ambiguous in that form, and no extraction beats a wrong one.
_MISSING_PATH_PATTERNS = (
    re.compile(r"ENOENT: no such file or directory, (?:open|stat|lstat|scandir|access|"
               r"realpath|readlink|opendir|chdir|uv_cwd) '([^']+)'", re.IGNORECASE),
    re.compile(r"can't open file '([^']+)'"),
    re.compile(r"No such file or directory: '([^']+)'"),
    re.compile(r"(?:^|:[ \t])([^\s:'\"\[\]]+): No such file or directory", re.MULTILINE),
    re.compile(r"ERROR: file or directory not found: (\S+)"),
)
#: node's message for a missing entry script or relative require. It also names
#: missing packages, so a capture counts only when it looks like a path.
_CANNOT_FIND_MODULE = re.compile(r"Cannot find module '([^']+)'")
#: npm's own message when the project has no manifest: the runner cannot start.
_MISSING_MANIFEST = re.compile(r"Could not read package\.json")
_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def _looks_like_path(raw: str, argv: Optional[Iterable[Any]]) -> bool:
    """A `Cannot find module` capture is a path when it is absolute, explicitly
    relative, or holds a slash and is not a scoped package (``@scope/pkg``) —
    or when it is one of the command's own arguments. ``express`` is not."""
    if argv and raw in {str(a) for a in argv}:
        return True
    if raw.startswith(("/", "./", "../", ".\\", "..\\")) or _DRIVE.match(raw):
        return True
    return ("/" in raw or "\\" in raw) and not raw.startswith("@")


def missing_paths(text: Any, argv: Optional[Iterable[Any]] = None) -> List[str]:
    """Paths *text* names as missing, in order of appearance, each once.

    *argv*, when given, lets a bare ``Cannot find module 'x'`` count as a path
    because the command itself named ``x``.
    """
    text = str(text or "")
    argv = list(argv) if argv else None
    hits = []
    for pattern in _MISSING_PATH_PATTERNS:
        for match in pattern.finditer(text):
            # Python prints paths through repr(), doubling each backslash.
            raw = match.group(1).replace("\\\\", "\\").strip()
            if raw:
                hits.append((match.start(1), raw))
    for match in _CANNOT_FIND_MODULE.finditer(text):
        raw = match.group(1).strip()
        if raw and _looks_like_path(raw, argv):
            hits.append((match.start(1), raw))
    ordered: List[str] = []
    for _, raw in sorted(hits):
        if raw not in ordered:
            ordered.append(raw)
    return ordered


def is_missing_manifest(text: Any) -> bool:
    """True when npm says it cannot read the project's package.json."""
    return bool(_MISSING_MANIFEST.search(str(text or "")))


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def _windows_shaped(path: str) -> bool:
    return bool(_DRIVE.match(path)) or "\\" in path


def _normalize(path: str) -> str:
    """Collapse ``.`` and ``..`` segments, with the rules of the platform the
    path looks like, and return it with forward slashes."""
    if _windows_shaped(path):
        return _norm(ntpath.normpath(path))
    return posixpath.normpath(path)


def _real_forms(path: str) -> List[str]:
    """*path*, plus its resolved form when it or its parent exists here, so a
    symlinked prefix (``/var`` vs ``/private/var``) still matches the root."""
    forms = [path]
    if _windows_shaped(path) and os.name != "nt":
        return forms
    try:
        if os.path.exists(path):
            forms.append(_norm(os.path.realpath(path)))
        else:
            parent, name = os.path.split(path)
            if parent and os.path.isdir(parent):
                forms.append(_norm(os.path.join(os.path.realpath(parent), name)))
    except (OSError, ValueError):
        pass
    return forms


def relativize(raw: str, root: Any) -> Optional[str]:
    """*raw* as a POSIX path relative to *root*, or None outside it.

    Textual first, so a Windows message is understood on any host:
    backslashes become slashes, ``..`` collapses, and a drive letter compares
    case-insensitively. Then the resolved forms of both are compared where
    they exist on this host. A relative *raw* is already relative to the
    root, which is every gate's cwd.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    path = _normalize(text)
    if path.startswith("/") or _DRIVE.match(path):
        root_text = str(root)
        roots = {_normalize(root_text).rstrip("/")}
        try:
            roots.add(_norm(os.path.realpath(root_text)).rstrip("/"))
        except (OSError, ValueError):
            pass
        rest = None
        for form in _real_forms(path):
            for base in sorted(roots, key=len, reverse=True):
                if not base:
                    continue
                if _DRIVE.match(base):
                    if form.lower().startswith(base.lower() + "/"):
                        rest = form[len(base) + 1:]
                elif form.startswith(base + "/"):
                    rest = form[len(base) + 1:]
                if rest is not None:
                    break
            if rest is not None:
                break
        if rest is None:
            return None
        path = rest
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


#: Programs that run a file named in their arguments. When one of these exits
#: 126/127 because that file is missing, the file — not the program — is what
#: could not be found (ADR-0022).
INTERPRETERS = frozenset(("sh", "bash", "zsh", "node", "python", "python3", "ruby", "deno",
                          "bun", "tsx", "ts-node"))
_VERSION_SUFFIX = re.compile(r"(?<=[a-z])[\d.]+$")


def is_interpreter(program: Any) -> bool:
    """True when *program* (a path or a bare name) is one of `INTERPRETERS`;
    ``python3.12`` and ``python.exe`` count as ``python``."""
    name = ntpath.basename(_norm(str(program or "")).rsplit("/", 1)[-1]).lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if not name:
        return False
    return name in INTERPRETERS or _VERSION_SUFFIX.sub("", name) in INTERPRETERS


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


def _argv_paths(argv: Optional[Iterable[Any]], root: Any) -> set:
    """Each argument as relativized into the project (options skipped)."""
    found = set()
    for arg in argv or []:
        tok = str(arg).strip()
        if not tok or tok.startswith("-"):
            continue
        rel = relativize(tok, root)
        if rel is not None:
            found.add(rel)
    return found


def missing_path_owner(gate: Dict[str, Any], root: Any,
                       tasks: Optional[Iterable[Dict[str, Any]]],
                       argv: Optional[Iterable[Any]] = None) -> Optional[Dict[str, Any]]:
    """``{"path", "owner", "manifest", "argv_named"}`` for a failing gate's
    missing path.

    The first extracted path that a task covers wins; otherwise the path is
    reported with ``owner`` None — ``package.json`` when npm says it cannot
    read the manifest, else the first extracted path (relative when inside the
    root, as printed when not). ``argv_named`` says the reported path is one
    of the gate's own arguments. None when the output names no missing path.
    """
    text = "%s\n%s" % (gate.get("stdout_tail") or "", gate.get("stderr_tail") or "")
    argv = list(argv) if isinstance(argv, list) else None
    raws = missing_paths(text, argv=argv)
    if not raws:
        return None
    manifest = is_missing_manifest(text)
    named = _argv_paths(argv, root)
    tasks = list(tasks or [])
    first = None
    for raw in raws:
        rel = relativize(raw, root)
        shown = rel if rel is not None else raw
        if first is None:
            first = shown
        owner = scope_owner(rel, tasks) if rel is not None else None
        if owner:
            return {"path": rel, "owner": owner, "manifest": manifest,
                    "argv_named": rel in named}
    if manifest:
        first = "package.json"
    return {"path": first, "owner": None, "manifest": manifest,
            "argv_named": first in named}


def program_owner(program: Any, root: Any,
                  tasks: Optional[Iterable[Dict[str, Any]]]) -> "tuple":
    """``(relpath, owner)`` for a program that could not be executed at all.

    Only a program given as a path (holding a slash) can be one a task
    writes; a bare name is looked up on PATH and gives ``(None, None)``.
    """
    text = str(program or "")
    if "/" not in text and "\\" not in text:
        return None, None
    rel = relativize(text, root)
    return rel, (scope_owner(rel, tasks) if rel else None)


#: Directories a package manager fills from a manifest, and the manifests
#: that can fill each. A program under one is missing until dependencies are
#: installed, which is not a broken command. Each name is also skipped by
#: `contract.tree_fingerprint` (FINGERPRINT_SKIP_DIRS).
DEPENDENCY_MANIFESTS = {
    "node_modules": ("package.json",),
    ".venv": ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "setup.py",
              "setup.cfg", "Pipfile", "poetry.lock", "uv.lock"),
    "venv": ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "setup.py",
             "setup.cfg", "Pipfile", "poetry.lock", "uv.lock"),
}


def dependency_program(program: Any, root: Any,
                       tasks: Optional[Iterable[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """For a program path inside a dependency directory (``node_modules``,
    ``.venv``, ``venv``): ``{"path", "dir", "manifest", "owner"}``.

    ``manifest`` sits beside the directory (``web/node_modules/.bin/x`` →
    ``web/package.json``); ``owner`` is the first task whose write_scope
    covers one of that directory's manifests, and ``manifest`` is then that
    one, else the first candidate. None for a bare name or any other path.
    """
    text = str(program or "")
    if "/" not in text and "\\" not in text:
        return None
    rel = relativize(text, root)
    if rel is None:
        return None
    parts = rel.split("/")
    for index, part in enumerate(parts[:-1]):
        names = DEPENDENCY_MANIFESTS.get(part)
        if not names:
            continue
        base = "/".join(parts[:index])
        candidates = ["%s/%s" % (base, n) if base else n for n in names]
        tasks = list(tasks or [])
        for candidate in candidates:
            owner = scope_owner(candidate, tasks)
            if owner:
                return {"path": rel, "dir": part, "manifest": candidate, "owner": owner}
        return {"path": rel, "dir": part, "manifest": candidates[0], "owner": None}
    return None

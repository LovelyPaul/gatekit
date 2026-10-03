"""Filesystem layout resolution for gatekit.

Every other module asks this one where things live so that the layout in
ARCHITECTURE.md section 2 is stated exactly once. Two roots matter:

* the **project root** — the user's repository, found by walking up from a
  starting directory to the nearest ancestor holding ``.gatekit/`` or ``.git/``;
* the **plugin root** — the installed plugin directory (the one holding
  ``.claude-plugin/plugin.json``), which is wherever Claude Code unpacked us.

No absolute personal path is ever hardcoded: both roots are derived at runtime.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
from typing import List, Optional

from gatekit import names

#: Every state directory name, newest first (ADR-0029): ``.gatebound``,
#: ``.gatekit``. Protected-state rules apply to each.
STATE_DIRNAMES = names.state_dirnames()

#: Directory names that mark a project root, in priority order. The state
#: directories come first so a gatekit-managed subproject inside a larger git
#: repository wins over the outer repository.
ROOT_MARKERS = STATE_DIRNAMES + (".git",)

#: The state directory a project with none yet gets.
STATE_DIRNAME = names.state_dirname()
SPEC_DIRNAME = "spec"


def project_root(cwd: Optional[str] = None) -> pathlib.Path:
    """Return the nearest ancestor of *cwd* containing a root marker.

    Falls back to *cwd* itself when no marker is found, which keeps gates
    working in a scratch directory instead of escaping to the filesystem root.
    """
    start = pathlib.Path(cwd) if cwd else pathlib.Path.cwd()
    try:
        start = start.resolve()
    except OSError:  # pragma: no cover - unreadable path
        start = start.absolute()

    for candidate in (start, *start.parents):
        for marker in ROOT_MARKERS:
            if (candidate / marker).is_dir():
                return candidate
    return start


def state_dir(root: pathlib.Path) -> pathlib.Path:
    """``<root>/.gatekit`` — machine state, mostly git-ignored.

    ADR-0029: ``.gatebound/`` if present, else ``.gatekit/`` if present, else
    the current name; with both present, the one holding ``approvals.json``.
    """
    return names.resolve_state_dir(root)


def spec_dir(root: pathlib.Path) -> pathlib.Path:
    """``<root>/spec`` — human-reviewed, committed specification set."""
    return pathlib.Path(root) / SPEC_DIRNAME


def runs_dir(root: pathlib.Path) -> pathlib.Path:
    """``<root>/.gatekit/runs`` — per-session ledgers and the hook error log."""
    return state_dir(root) / "runs"


def jobs_dir(root: pathlib.Path) -> pathlib.Path:
    """``<root>/.gatekit/jobs`` — worker job directories."""
    return state_dir(root) / "jobs"


def hook_error_log(root: pathlib.Path) -> pathlib.Path:
    """One-line-per-failure diagnostic log written by :mod:`gatekit.hookio`."""
    return runs_dir(root) / "hook-errors.log"


def config_file(root: pathlib.Path) -> pathlib.Path:
    return state_dir(root) / "config.json"


def approvals_file(root: pathlib.Path) -> pathlib.Path:
    return state_dir(root) / "approvals.json"


def contract_file(root: pathlib.Path) -> pathlib.Path:
    return state_dir(root) / "contract.json"


def plugin_root() -> pathlib.Path:
    """Return the installed plugin directory.

    Walks up from this file looking for ``.claude-plugin/plugin.json``. When
    Claude Code runs a gate it exports ``CLAUDE_PLUGIN_ROOT``; that value is
    trusted first, since a symlinked install can make ``__file__`` point
    somewhere other than the real plugin directory.
    """
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        candidate = pathlib.Path(env_root)
        if (candidate / ".claude-plugin" / "plugin.json").is_file():
            return candidate

    here = pathlib.Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".claude-plugin" / "plugin.json").is_file():
            return candidate
    # Fall back to the package's parent: gatekit/paths.py -> gatekit/ -> plugin/
    return here.parents[1]


#: The one variable gatekit expands inside a criterion or task-gate argv.
PLUGIN_ROOT_TOKEN = "${CLAUDE_PLUGIN_ROOT}"


def expand_argv(argv: List[str]) -> List[str]:
    """Return a copy of *argv* with ``${CLAUDE_PLUGIN_ROOT}`` made concrete.

    Criteria and task gates run with no shell (ADR-0018), so the token that
    ``spec-kit/task-gates.md`` documents would otherwise reach the program
    literally. Nothing else is expanded: no other ``$VAR``, no ``~``, no
    globs — the fence stays portable and the argv stays shell-free.
    """
    root = str(plugin_root())
    out = [alias_path(str(a).replace(PLUGIN_ROOT_TOKEN, root)) for a in argv]
    # ADR-0019: without a shell, Windows cannot find `npm` as `npm.cmd`;
    # shutil.which applies PATHEXT. Only a bare name is looked up, and an
    # unresolvable one is left as written for the caller to report.
    if out and not any(sep in out[0] for sep in ("/", "\\")):
        found = shutil.which(out[0])
        if found:
            out[0] = found
    return out


_ABS_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _alias_re():
    pattern = names.names_pattern()
    return re.compile(r"(?:^|/)(?:%s/gates/(?P<gate>[A-Za-z0-9][A-Za-z0-9_]*\.py)"
                      r"|bin/%s\.py)$" % (pattern, pattern))


def alias_path(token: str) -> str:
    """*token* mapped to this plugin's own file when it is an absolute path
    that does not exist and ends in ``<name>/gates/<gate>.py`` (a gate this
    plugin has) or ``bin/<name>.py``, for any of the plugin's names.

    ADR-0029: argv written against an older name, an old checkout or a
    deleted plugin cache keeps running. Run time only — what is pinned and
    hashed is the argv as written. Anything else is returned as is.
    """
    try:
        if not token or not (os.path.isabs(token) or _ABS_DRIVE_RE.match(token)):
            return token
        if os.path.exists(token) or os.path.exists(from_msys(token)):
            return token
        match = _alias_re().search(token.replace("\\", "/"))
        if not match:
            return token
        proot = plugin_root()
        if match.group("gate"):
            target = proot / names.CURRENT / "gates" / match.group("gate")
        else:
            target = proot / "bin" / (names.CURRENT + ".py")
        return str(target) if target.is_file() else token
    except (OSError, ValueError):
        return token


_MSYS_DRIVE_RE = re.compile(r"^/([A-Za-z])(/.*)?$")


def from_msys(path: str, windows: Optional[bool] = None) -> str:
    """``/c/work/app`` → ``C:/work/app`` on Windows (Git Bash's form).

    ADR-0019. Anything else, and every path off Windows, is returned as is.
    """
    if not (os.name == "nt" if windows is None else windows):
        return path
    match = _MSYS_DRIVE_RE.match(path or "")
    if not match:
        return path
    return "%s:%s" % (match.group(1).upper(), match.group(2) or "/")


def ensure_dir(path: pathlib.Path) -> pathlib.Path:
    """Create *path* (and parents) if absent. Returns *path* for chaining."""
    pathlib.Path(path).mkdir(parents=True, exist_ok=True)
    return pathlib.Path(path)


def relative_to_root(root: pathlib.Path, target: pathlib.Path) -> Optional[str]:
    """Return *target* as a POSIX path relative to *root*, or ``None``.

    ``None`` means the target lies outside the project root. Both sides are
    realpath-resolved first so symlinks cannot smuggle a path back in.
    """
    try:
        real_root = pathlib.Path(os.path.realpath(str(root)))
        real_target = pathlib.Path(os.path.realpath(str(target)))
        return real_target.relative_to(real_root).as_posix()
    except (ValueError, OSError):
        return None


def cli_invocation() -> str:
    """The one CLI form that works from a user's project directory.

    Used for every user-facing fix string so a copy-pasted remedy runs
    without PYTHONPATH: ``python3 "<plugin>/bin/gatekit.py"``.
    """
    return 'python3 "%s"' % (plugin_root() / "bin" / "gatekit.py")

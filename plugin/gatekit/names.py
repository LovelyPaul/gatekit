"""The plugin's name, and every name it has had or will have (ADR-0029).

The name is part of on-disk and user contracts — fence prefixes, the state
directory, launcher and command names, environment variables, managed
markers, plugin keys — so it is stated here once and every other module asks.
The rename to gatebound flips :data:`CURRENT` (and moves ``gatekit`` into
:data:`LEGACY`); nothing else should need to know which name is in force.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
from typing import Dict, List, Optional, Tuple

#: The name this build is published under.
CURRENT = "gatekit"
#: The name this plugin will carry after the rename.
FUTURE = "gatebound"
#: Names an *older*, separately installed plugin may still carry. A plugin of
#: one of these names enabled next to this one makes this one's Stop and
#: question gates stand down (ADR-0029). Empty until the rename.
LEGACY: Tuple[str, ...] = ()


def all_names() -> Tuple[str, ...]:
    """Every name, newest first, each once."""
    out: List[str] = []
    for name in (FUTURE, CURRENT) + tuple(LEGACY):
        if name and name not in out:
            out.append(name)
    return tuple(out)


# ------------------------------------------------------------------ fences
#: The fence kinds a spec file can carry.
FENCE_KINDS = ("task", "criterion", "budget", "discovery", "scope")


def fence_names(name: str) -> Tuple[str, ...]:
    """Every spelling of fence *name* (``gatekit-task`` → both prefixes).

    A name that is not ``<known prefix>-<kind>`` is returned alone.
    """
    for prefix in all_names():
        if name.startswith(prefix + "-"):
            kind = name[len(prefix) + 1:]
            return tuple("%s-%s" % (p, kind) for p in all_names())
    return (name,)


def fence(kind: str) -> str:
    """The fence name new files are written with, e.g. ``gatekit-task``."""
    return "%s-%s" % (CURRENT, kind)


# --------------------------------------------------------------- state dir
def state_dirname() -> str:
    """The state directory a project with none yet gets: ``.gatekit``."""
    return "." + CURRENT


def state_dirnames() -> Tuple[str, ...]:
    """Every state directory name, newest first: ``.gatebound``, ``.gatekit``."""
    return tuple("." + n for n in all_names())


def existing_state_dirs(root) -> List[pathlib.Path]:
    """The state directories present under *root*, newest name first."""
    base = pathlib.Path(root)
    return [base / d for d in state_dirnames() if (base / d).is_dir()]


#: Entries only gatekit writes; a state directory holding one is in use.
#: ``config.json`` and ``eval/`` are the user's and do not count, or a session
#: could move the hooks away from their ledgers by writing a settings file.
_OWNED_ENTRIES = ("contract.json", "runs", "jobs", "attempts.json", "baseline.json")


def _state_rank(candidate: pathlib.Path) -> int:
    if (candidate / "approvals.json").is_file():
        return 0
    if any((candidate / e).exists() for e in _OWNED_ENTRIES):
        return 1
    if candidate.name == state_dirname():
        return 2
    return 3


def resolve_state_dir(root) -> pathlib.Path:
    """``<root>/.gatebound`` if present, else ``.gatekit`` if present, else the
    current name. When several are present: the one holding
    ``approvals.json``, else one holding other gatekit-written state, else
    the current name, else the newest (ADR-0029)."""
    found = existing_state_dirs(root)
    if not found:
        return pathlib.Path(root) / state_dirname()
    if len(found) > 1:
        return min(found, key=_state_rank)  # stable: newest first among ties
    return found[0]


# ----------------------------------------------------------------- argv
def launcher_names() -> Tuple[str, ...]:
    """Base names that run this CLI: ``gatekit.py``, ``gatekit`` and the rest."""
    out: List[str] = []
    for n in all_names():
        out.extend((n + ".py", n))
    return tuple(out)


#: ``python -m`` (``-m``, or short options ending in it such as ``-Im``).
_MODULE_FLAG = re.compile(r"^-[A-Za-z]*m$")


def entry_kind(word: str, prev: Optional[str] = "-m") -> Optional[str]:
    """What running *word* starts, for the approve guards of the Bash and
    PowerShell gates (ADR-0023, ADR-0028), under every name:

    * ``"cli"`` — the CLI, whose next argument is the subcommand: a launcher
      (``bin/gatebound.py``, ``gatekit``) or the module ``<name>``,
      ``<name>.cli``, ``<name>.__main__``;
    * ``"approval"`` — the approval module itself (``-m <name>.approval``),
      whose arguments are ``approve``'s;
    * ``None`` — anything else.

    A dotted module counts only after ``-m`` — attached (``-mgatekit.cli``),
    as *prev*, or when *prev* is computed (holds ``$``) — so ``grep
    gatekit.approval src`` is no approval. Case is ignored."""
    base = word.replace("\\", "/").lower().rsplit("/", 1)[-1]
    if base in launcher_names():
        return "cli"
    if base.startswith("-m"):
        base = base[2:]
    elif prev is None or not (_MODULE_FLAG.match(prev) or "$" in prev):
        return None
    for name in all_names():
        if base in (name, name + ".cli", name + ".__main__"):
            return "cli"
        if base == name + ".approval":
            return "approval"
    return None


# --------------------------------------------------------------- 8.3 names
def state_short_names() -> Tuple[Tuple[str, str], ...]:
    """``(stem, dirname)`` per state directory: Windows gives ``.gatebound``
    the 8.3 short name ``GATEBO~1`` (``.gatekit``: ``GATEKI~1``) — the first
    six characters without the dot, ``~`` and a digit."""
    return tuple((d[1:7], d) for d in state_dirnames())


def names_pattern() -> str:
    """A regex alternation of every name."""
    return "(?:%s)" % "|".join(re.escape(n) for n in all_names())


# ------------------------------------------------------------------- env
def env_names(suffix: str) -> Tuple[str, ...]:
    """``TASK_ID`` → ``("GATEKIT_TASK_ID", "GATEBOUND_TASK_ID")``, current first."""
    order = [CURRENT] + [n for n in all_names() if n != CURRENT]
    return tuple("%s_%s" % (n.upper(), suffix) for n in order)


def env_prefixes() -> Tuple[str, ...]:
    return tuple(n.upper() + "_" for n in all_names())


def env_var_set(suffix: str, environ=None) -> Optional[str]:
    """The name of the first non-empty variable among :func:`env_names`."""
    environ = os.environ if environ is None else environ
    for key in env_names(suffix):
        if environ.get(key):
            return key
    return None


def env_get(suffix: str, environ=None) -> Optional[str]:
    """The first non-empty value among :func:`env_names`, else ``None``."""
    environ = os.environ if environ is None else environ
    for key in env_names(suffix):
        value = environ.get(key)
        if value:
            return value
    return None


def task_id(environ=None) -> Optional[str]:
    return env_get("TASK_ID", environ)


def job_id(environ=None) -> Optional[str]:
    return env_get("JOB_ID", environ)


def worker_env(task: str, job: str) -> Dict[str, str]:
    """The variables a worker gets, under every name."""
    out: Dict[str, str] = {}
    for key in env_names("TASK_ID"):
        out[key] = task
    for key in env_names("JOB_ID"):
        out[key] = job
    return out


# --------------------------------------------------------------- plugins
def plugin_key(name: str) -> str:
    """The key Claude Code uses for a plugin from its own marketplace."""
    return "%s@%s" % (name, name)


def _read_json(path) -> object:
    try:
        with open(str(path), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def claude_config_dir(home: Optional[str] = None) -> Optional[pathlib.Path]:
    """``$CLAUDE_CONFIG_DIR``, else ``<home>/.claude``; ``None`` without either."""
    if home is None:
        configured = os.environ.get("CLAUDE_CONFIG_DIR")
        if configured:
            return pathlib.Path(configured)
        home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    return pathlib.Path(home) / ".claude" if home else None


def installed_plugin_keys(home: Optional[str] = None) -> Optional[List[str]]:
    """Keys in Claude Code's ``plugins/installed_plugins.json``, or ``None``
    when it cannot be read. Only ever reads."""
    base = claude_config_dir(home)
    data = _read_json(base / "plugins" / "installed_plugins.json") if base else None
    if not isinstance(data, dict):
        return None
    table = data.get("plugins") if isinstance(data.get("plugins"), dict) else data
    return [k for k in table if isinstance(k, str)]


def settings_files(root=None, home: Optional[str] = None) -> List[pathlib.Path]:
    """Claude Code settings that can enable a plugin: the user's, then the
    project's shared and local ones."""
    out: List[pathlib.Path] = []
    base = claude_config_dir(home)
    if base:
        out.append(base / "settings.json")
    if root is not None:
        out.append(pathlib.Path(root) / ".claude" / "settings.json")
        out.append(pathlib.Path(root) / ".claude" / "settings.local.json")
    return out


def enabled_plugins(root=None, home: Optional[str] = None,
                    candidates: Optional[Tuple[str, ...]] = None) -> Dict[str, List[str]]:
    """``{name: [keys]}`` for every name in *candidates* (default: all) that
    some Claude Code settings file enables. A later file's explicit ``false``
    overrides an earlier ``true`` for the same key. Only ever reads."""
    wanted = tuple(candidates) if candidates is not None else all_names()
    state: Dict[str, bool] = {}
    for path in settings_files(root, home):
        data = _read_json(path)
        table = data.get("enabledPlugins") if isinstance(data, dict) else None
        if not isinstance(table, dict):
            continue
        for key, value in table.items():
            if isinstance(key, str) and key.split("@", 1)[0] in wanted and isinstance(value, bool):
                state[key] = value
    out: Dict[str, List[str]] = {}
    for key, on in sorted(state.items()):
        if on:
            out.setdefault(key.split("@", 1)[0], []).append(key)
    return out


def legacy_plugin_enabled(root=None, home: Optional[str] = None) -> List[str]:
    """Keys of plugins carrying a :data:`LEGACY` name that will gate *root*
    alongside this one, else ``[]``: enabled in some settings file, listed in
    ``installed_plugins.json``, and — when *root* is given — this project's
    state directory carries that legacy name (an older plugin reads only its
    own; in a migrated project it stands down by itself, so this one must
    not).

    With no legacy name (before the rename) this returns at once, reading
    nothing. Never raises."""
    if not LEGACY:
        return []
    try:
        legacy = tuple(n for n in LEGACY if n != CURRENT)
        if root is not None:
            state = resolve_state_dir(root).name
            legacy = tuple(n for n in legacy if "." + n == state)
            if not legacy:
                return []
        installed = installed_plugin_keys(home)
        if installed is None:
            return []
        found = enabled_plugins(root, home, candidates=legacy)
        return [key for keys in found.values() for key in keys if key in installed]
    except Exception:  # pragma: no cover - defensive; settings are user files
        return []


# --------------------------------------------------------------- markers
def agents_markers(name: Optional[str] = None) -> Tuple[str, str]:
    """``AGENTS.md`` managed block markers for *name* (default: current)."""
    name = name or CURRENT
    return ("<!-- %s:begin (managed; edit plugin/ and re-run install) -->" % name,
            "<!-- %s:end -->" % name)

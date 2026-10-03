"""8-axis diagnosis (§12).

Each axis returns `{"axis", "verdict", "detail", "fix"}` where `fix` is a
copy-pasteable command or "". The overall verdict is `verdict.aggregate` over
the axes, so a single `unverified` axis never rounds the report to `ok`.
Exit code is 1 iff any axis is `fail`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys

from gatekit import paths, verdict

#: Gate scripts that must exist and be non-empty for axis 1.
GATE_SCRIPTS = ("prompt.py", "write.py", "bash.py", "spawn.py", "question.py", "stop.py")

#: Hook events axis 2 expects to find registered in the running install.
EXPECTED_HOOK_EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")

MIN_PYTHON = (3, 9)


def _axis(name, v, detail, fix=""):
    return {"axis": name, "verdict": v, "detail": detail, "fix": fix}


# ------------------------------------------------------------------- axis 1


def axis_plugin_files(root) -> dict:
    try:
        proot = paths.plugin_root()
    except Exception as exc:
        return _axis("plugin files", verdict.FAIL,
                     "could not locate the plugin root: %s" % exc, "")
    missing = []
    if not (proot / ".claude-plugin" / "plugin.json").is_file():
        missing.append(".claude-plugin/plugin.json")
    if not (proot / "hooks" / "hooks.json").is_file():
        missing.append("hooks/hooks.json")
    gates = proot / "gatekit" / "gates"
    for script in GATE_SCRIPTS:
        path = gates / script
        if not path.is_file():
            missing.append("gatekit/gates/%s" % script)
        elif path.stat().st_size == 0:
            missing.append("gatekit/gates/%s (empty)" % script)
    if missing:
        return _axis(
            "plugin files", verdict.FAIL,
            "missing or empty: %s" % ", ".join(missing),
            "reinstall the plugin: /plugin install gatekit",
        )
    return _axis("plugin files", verdict.OK,
                 "plugin.json, hooks.json and %d gate scripts present" % len(GATE_SCRIPTS))


# ------------------------------------------------------------------- axis 2


def _installed_plugins_path():
    home = os.environ.get("HOME")
    if not home:
        return None
    return os.path.join(home, ".claude", "plugins", "installed_plugins.json")


def _settings_path():
    home = os.environ.get("HOME")
    if not home:
        return None
    return os.path.join(home, ".claude", "settings.json")


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _installed_keys(data) -> list:
    """Return the plugin keys (``name@marketplace``) that name gatekit.

    ``installed_plugins.json`` nests entries under ``plugins`` in current
    Claude Code releases; older layouts kept them at the top level. Both are
    read structurally — never by searching the serialized text — so a plugin
    whose description merely mentions gatekit does not count as installed.
    """
    if not isinstance(data, dict):
        return []
    table = data.get("plugins") if isinstance(data.get("plugins"), dict) else data
    keys = []
    for key in table:
        if not isinstance(key, str):
            continue
        name = key.split("@", 1)[0]
        if name == "gatekit":
            keys.append(key)
    return keys


def axis_hooks_registered(root) -> dict:
    path = _installed_plugins_path()
    if not path:
        return _axis("hooks registered", verdict.UNVERIFIED,
                     "HOME is not set; cannot inspect the running install", "")
    if not os.path.isfile(path):
        return _axis("hooks registered", verdict.UNVERIFIED,
                     "no installed_plugins.json under ~/.claude/plugins; "
                     "running from a source checkout?",
                     "/plugin install gatekit")
    try:
        data = _read_json(path)
    except (OSError, ValueError) as exc:
        return _axis("hooks registered", verdict.UNVERIFIED,
                     "installed_plugins.json unreadable: %s" % exc, "")
    keys = _installed_keys(data)
    if not keys:
        return _axis("hooks registered", verdict.FAIL,
                     "gatekit is not listed in installed_plugins.json; "
                     "hooks will not fire",
                     "/plugin install gatekit")

    # Installed is not enabled. A disabled plugin has files on disk and no
    # hooks firing — the state that looks healthy while enforcing nothing.
    settings_path = _settings_path()
    enabled = None
    if settings_path and os.path.isfile(settings_path):
        try:
            settings = _read_json(settings_path)
        except (OSError, ValueError) as exc:
            return _axis("hooks registered", verdict.UNVERIFIED,
                         "installed as %s but settings.json unreadable: %s" % (keys[0], exc), "")
        table = settings.get("enabledPlugins") if isinstance(settings, dict) else None
        if isinstance(table, dict):
            enabled = any(table.get(k) is True for k in keys)
    if enabled is None:
        return _axis("hooks registered", verdict.UNVERIFIED,
                     "installed as %s but no enabledPlugins entry found in settings.json" % keys[0],
                     "/plugin enable %s" % keys[0])
    if not enabled:
        return _axis("hooks registered", verdict.FAIL,
                     "installed as %s but disabled in settings.json enabledPlugins; "
                     "hooks will not fire" % keys[0],
                     "/plugin enable %s" % keys[0])
    return _axis("hooks registered", verdict.OK,
                 "gatekit installed and enabled as %s" % keys[0])


# ------------------------------------------------------------------- axis 3


def axis_project_state(root) -> dict:
    state = paths.state_dir(root)
    if not state.is_dir():
        return _axis("project state", verdict.UNVERIFIED,
                     "no .gatekit/ in this project yet",
                     paths.cli_invocation() + " doctor --root <project>  # after /gatekit:setup")
    problems = []
    warnings = []
    cfg = state / "config.json"
    if cfg.is_file():
        try:
            with cfg.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict):
                problems.append("config.json is not a JSON object")
            else:
                from gatekit import config as config_mod
                problem = config_mod.stop_budget_s(loaded)[1]
                if problem:
                    warnings.append(problem)
        except (OSError, ValueError) as exc:
            problems.append("config.json invalid: %s" % exc)
    approvals = state / "approvals.json"
    if approvals.is_file():
        try:
            with approvals.open(encoding="utf-8") as handle:
                loaded = json.load(handle)
            if not isinstance(loaded, dict) or not isinstance(loaded.get("approvals"), list):
                problems.append("approvals.json has no `approvals` list")
        except (OSError, ValueError) as exc:
            problems.append("approvals.json invalid: %s" % exc)
    if problems:
        return _axis("project state", verdict.FAIL, "; ".join(problems),
                     "fix or delete the offending file under .gatekit/")
    fixes = []
    if warnings:
        fixes.append("edit stop.budget_s in .gatekit/config.json (seconds, at most 570)")
    for message, fix in _port_clashes(root):
        warnings.append(message)
        fixes.append(fix)
    detail = ".gatekit/ present and parseable"
    note = _stand_down_note(state)
    if note:
        detail += "; " + note
    if warnings:
        return _axis("project state", verdict.WARN, "; ".join(warnings) + "; " + detail,
                     "; ".join(fixes))
    return _axis("project state", verdict.OK, detail)


# ADR-0026: a server already listening on the Playwright webServer port. With
# `reuseExistingServer: true` the e2e tests run against whatever answers
# there — in the 0.16.0 rehearsal, another project's app. The port is found
# by a small scan, not by parsing JS/TS: comments are dropped, the value after
# each `webServer:` is taken up to its balanced closing brace or bracket
# (strings respected), and in it `port: <n>` / `url: '<scheme>://<host>:<n>'`
# are read, also as the fallback after `||` or `??` (`process.env.PORT ||
# 3000`). A port set only from a variable is not found.
PLAYWRIGHT_CONFIGS = tuple("playwright.config." + ext for ext in ("ts", "js", "mjs", "cjs"))
#: Also searched (recursively) for Playwright configs.
E2E_CONFIG_DIR = ("spec", "design", "e2e")
#: Most characters of one `webServer` value read; an unbalanced value stops here.
WEBSERVER_WINDOW = 8000
_WEBSERVER_RE = re.compile(r"\bwebServer\s*:\s*")
_FALLBACK = r"(?:[^,;{}\[\]\n]*?(?:\|\||\?\?)\s*)?"
_PORT_RE = re.compile(r"\bport\s*:\s*" + _FALLBACK + r"(\d{1,5})\b")
_URL_PORT_RE = re.compile(
    r"\burl\s*:\s*" + _FALLBACK
    + r"['\"`][A-Za-z][A-Za-z0-9+.-]*://(?:\[[^\]]*\]|[^'\"`/\s:]+):(\d{1,5})")
PROBE_TIMEOUT_S = 0.3
LSOF_TIMEOUT_S = 3


def _strip_js_comments(text: str) -> str:
    """*text* without ``//`` and ``/* */`` comments; string literals (where
    ``//`` is part of a URL) are kept as they are."""
    out = []
    i, n = 0, len(text)
    quote = None
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "'\"`":
            quote = ch
            out.append(ch)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            out.append(" ")
            i = n if end < 0 else end + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _balanced_value(text: str, start: int) -> str:
    """The ``{…}`` or ``[…]`` value opening at *start*, up to its matching
    close (strings respected), at most :data:`WEBSERVER_WINDOW` characters;
    "" when no object or array opens there."""
    if start >= len(text) or text[start] not in "{[":
        return ""
    depth = 0
    quote = None
    limit = min(len(text), start + WEBSERVER_WINDOW)
    i = start
    while i < limit:
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return text[start:limit]


def _playwright_configs(root) -> list:
    found = [root / name for name in PLAYWRIGHT_CONFIGS if (root / name).is_file()]
    e2e = root.joinpath(*E2E_CONFIG_DIR)
    if e2e.is_dir():
        found += sorted(p for p in e2e.rglob("playwright.config.*")
                        if p.name in PLAYWRIGHT_CONFIGS and p.is_file())
    return found


def webserver_ports(root) -> list:
    """Sorted ports named in the ``webServer`` values of the Playwright configs."""
    import pathlib

    ports = set()
    for path in _playwright_configs(pathlib.Path(root)):
        try:
            text = _strip_js_comments(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for match in _WEBSERVER_RE.finditer(text):
            window = _balanced_value(text, match.end())
            for regex in (_PORT_RE, _URL_PORT_RE):
                for found in regex.findall(window):
                    port = int(found)
                    if 0 < port < 65536:
                        ports.add(port)
    return sorted(ports)


def _listening(port: int) -> bool:
    """Whether something accepts a TCP connection on the loopback *port*.

    127.0.0.1 first; ::1 too, since a dev server bound to ``localhost`` may
    listen on IPv6 only."""
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(PROBE_TIMEOUT_S)
                if sock.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def _lsof_fields(args: list) -> list:
    """``lsof -F`` output as ``(field, value)`` pairs; [] when unavailable."""
    if os.name == "nt":
        return []
    exe = shutil.which("lsof")
    if not exe:
        return []
    try:
        proc = subprocess.run([exe] + args, capture_output=True, text=True,
                              timeout=LSOF_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return []
    return [(line[0], line[1:]) for line in proc.stdout.splitlines() if line]


def _listener(port: int, root) -> str:
    """``pid N (command), cwd X — inside/outside this project`` or ""."""
    pid = command = ""
    for field, value in _lsof_fields(["-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-Fpc"]):
        if field == "p" and not pid:
            pid = value
        elif field == "c" and pid and not command:
            command = value
    if not pid.isdigit():
        return ""
    text = "pid %s" % pid
    if command:
        text += " (%s)" % command
    cwd = ""
    for field, value in _lsof_fields(["-a", "-p", pid, "-d", "cwd", "-Fn"]):
        if field == "n":
            cwd = value
            break
    if cwd:
        real_root = os.path.realpath(str(root))
        real_cwd = os.path.realpath(cwd)
        inside = real_cwd == real_root or real_cwd.startswith(real_root.rstrip(os.sep) + os.sep)
        text += ", cwd %s — %s this project" % (cwd, "inside" if inside else "outside")
    return text


def _port_clashes(root) -> list:
    """``(message, fix)`` per webServer port something already listens on.

    Never stops a process. A probe that raises is skipped: a diagnosis must
    not crash doctor."""
    try:
        ports = webserver_ports(root)
    except Exception:  # noqa: BLE001
        return []
    clashes = []
    for port in ports:
        try:
            if not _listening(port):
                continue
            who = _listener(port, root)
        except Exception:  # noqa: BLE001
            continue
        message = ("port %d (Playwright webServer) is already in use%s; with "
                   "reuseExistingServer the e2e tests run against whatever answers there"
                   % (port, (" by " + who) if who else ""))
        fix = ("stop the process listening on port %d, or change the webServer port "
               "in playwright.config (doctor stops nothing)" % port)
        clashes.append((message, fix))
    return clashes


def _stand_down_note(state) -> str:
    """ADR-0024: name a Stop-gate stand-down in the most recently updated
    session ledger, so "why did the Stop hook not run?" has an answer."""
    try:
        runs = state / "runs"
        ledgers = [p for p in runs.glob("*.json") if p.name != "contract-last.json"]
        if not ledgers:
            return ""
        latest = max(ledgers, key=lambda p: p.stat().st_mtime)
        with latest.open(encoding="utf-8") as handle:
            data = json.load(handle)
        stood = ((data.get("stop") or {}).get("stood_down")
                 if isinstance(data, dict) else None)
        if not isinstance(stood, dict):
            return ""
        return ("Stop gate stood down in session %s after %s (verdict %s, %s turn end(s) "
                "not judged): follow-up edits are not gated; /gatekit:verify re-checks"
                % (data.get("session_id") or latest.stem,
                   stood.get("job_id") or stood.get("pipeline") or "?",
                   stood.get("verdict") or verdict.UNVERIFIED, stood.get("skipped", 0)))
    except Exception:  # noqa: BLE001 — a diagnosis must never crash doctor
        return ""


# ------------------------------------------------------------------- axis 4


def axis_spec_set(root) -> dict:
    if not paths.spec_dir(root).is_dir():
        return _axis("spec set", verdict.UNVERIFIED, "no spec/ directory in this project",
                     "/gatekit:interview")
    try:
        from gatekit import spec as spec_mod
        result = spec_mod.validate(root)
    except Exception as exc:
        return _axis("spec set", verdict.UNVERIFIED,
                     "spec validation could not run: %s" % exc, "")
    v = result.get("verdict", verdict.UNVERIFIED)
    findings = result.get("findings") or []
    bad = [f for f in findings if f.get("verdict") in (verdict.FAIL, verdict.WARN)]
    detail = "%d finding(s)" % len(findings)
    if bad:
        detail += ": " + "; ".join(
            "%s %s" % (f.get("file", "?"), f.get("message", "")) for f in bad[:3]
        )
    return _axis("spec set", v, detail,
                 (paths.cli_invocation() + " spec validate") if v != verdict.OK else "")


# ------------------------------------------------------------------- axis 5


def axis_contract_freshness(root) -> dict:
    try:
        from gatekit import contract as contract_mod
        v = contract_mod.status(root)
    except Exception as exc:
        return _axis("contract freshness", verdict.UNVERIFIED,
                     "contract status could not run: %s" % exc, "")
    if v == verdict.OK:
        return _axis("contract freshness", verdict.OK,
                     ".gatekit/contract.json matches spec/05-gate.md")
    if v == verdict.UNVERIFIED:
        return _axis("contract freshness", verdict.UNVERIFIED,
                     "no .gatekit/contract.json yet",
                     paths.cli_invocation() + " contract derive")
    try:
        changed = contract_mod.stale_inputs(root)
    except Exception:  # noqa: BLE001 — a diagnosis must never crash doctor
        changed = []
    if changed:
        detail = "contract is stale: %s changed since it was derived" % ", ".join(changed)
    else:
        detail = "contract is stale: spec/05-gate.md changed since it was derived"
    return _axis("contract freshness", verdict.FAIL, detail,
                 paths.cli_invocation() + " contract derive")


# ------------------------------------------------------------------- axis 6


def axis_workers(root) -> dict:
    try:
        from gatekit import workers as workers_mod
        name = workers_mod.default_name(root)
        result = workers_mod.check(root, name)
    except Exception as exc:
        return _axis("workers", verdict.UNVERIFIED,
                     "worker check could not run: %s" % exc, "")
    v = result.get("verdict", verdict.UNVERIFIED)
    fix = ""
    if v == verdict.FAIL:
        fix = "install the %s CLI, or: %s workers set-default <name>" % (name, paths.cli_invocation())
    return _axis("workers", v, "default backend %s — %s" % (name, result.get("detail", "")), fix)


# ------------------------------------------------------------------- axis 7


def axis_python(root) -> dict:
    info = sys.version_info
    current = "%d.%d.%d" % (info.major, info.minor, info.micro)
    if (info.major, info.minor) < MIN_PYTHON:
        return _axis("python", verdict.FAIL,
                     "python %s is below the required %d.%d" % (current, *MIN_PYTHON),
                     "install python 3.9 or newer")
    return _axis("python", verdict.OK, "python %s" % current)


# ------------------------------------------------------------------- axis 8


def axis_host_layer(root) -> dict:
    """A generated Codex host layer, when present, must point at real gates.

    Absent is ``ok``: a Claude Code project needs none. Present but broken is
    ``fail``. Whether Codex trusts the project and loads the hooks cannot be
    read from here, and the detail says so.
    """
    from gatekit import hosts

    # ADR-0019: a gatekit installed as a Codex plugin runs no gate until the
    # user trusts its hooks, and nothing else would say so.
    plugin_trust = hosts.codex_plugin_trust()
    result = hosts.status(root, "codex")
    if result["verdict"] != verdict.FAIL and plugin_trust is False:
        return _axis(
            "host layer",
            verdict.WARN,
            "codex plugin installed but its hooks are not trusted: no gate runs under Codex",
            hosts.CODEX_PLUGIN_TRUST_FIX,
        )
    if result["verdict"] == verdict.UNVERIFIED:
        detail = "no Codex host layer (Claude Code plugin serves this project)"
        if plugin_trust:
            detail = "codex plugin hooks trusted; no per-project Codex host layer needed"
        return _axis("host layer", verdict.OK, detail, "")
    return _axis("host layer", result["verdict"], "codex: " + result["detail"], result.get("fix", ""))


AXES = (
    axis_plugin_files,
    axis_hooks_registered,
    axis_project_state,
    axis_spec_set,
    axis_contract_freshness,
    axis_workers,
    axis_python,
    axis_host_layer,
)


def diagnose(root) -> dict:
    axes = []
    for index, fn in enumerate(AXES, start=1):
        try:
            result = fn(root)
        except Exception as exc:  # an axis must never abort the report
            result = _axis(getattr(fn, "__name__", "axis %d" % index),
                           verdict.UNVERIFIED, "axis raised %s" % exc, "")
        result["n"] = index
        axes.append(result)
    return {"verdict": verdict.aggregate([a["verdict"] for a in axes]), "axes": axes}


# --------------------------------------------------------------------------- CLI


def run(argv: list) -> int:
    argv = list(argv)
    root_arg = None
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            root_arg = argv[i + 1]
    root = paths.project_root(root_arg)
    report = diagnose(root)

    if "--json" in argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("gatekit doctor — %s (root: %s)" % (report["verdict"], root))
        for axis in report["axes"]:
            print("  %d. %-11s %-10s %s" % (
                axis["n"], axis["verdict"], axis["axis"], axis["detail"]))
            if axis.get("fix"):
                print("       fix: %s" % axis["fix"])
    return 1 if any(a["verdict"] == verdict.FAIL for a in report["axes"]) else 0

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

from gatekit import names, paths, verdict

#: Gate scripts that must exist and be non-empty for axis 1.
GATE_SCRIPTS = ("prompt.py", "write.py", "bash.py", "powershell.py", "spawn.py", "question.py",
                "stop.py")

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
    return _installed_name_keys(data, (names.CURRENT,))


def _installed_name_keys(data, wanted) -> list:
    """Plugin keys in *data* whose name is one of *wanted*."""
    if not isinstance(data, dict):
        return []
    table = data.get("plugins") if isinstance(data.get("plugins"), dict) else data
    keys = []
    for key in table:
        if not isinstance(key, str):
            continue
        name = key.split("@", 1)[0]
        if name in wanted:
            keys.append(key)
    return keys


def _dual_plugin(root, installed):
    """ADR-0029: ``(detail, fix)`` when plugins of more than one of this
    plugin's names are active at once, else ``None``. Claude Code: enabled in
    the user's or the project's settings (and, when ``installed_plugins.json``
    was readable, listed there). Codex: cached under more than one name. Only
    reads."""
    # Same ~/.claude as the rest of this axis.
    enabled = names.enabled_plugins(root, home=os.environ.get("HOME") or "")
    if installed is not None:
        listed = set(_installed_name_keys(installed, names.all_names()))
        enabled = {n: [k for k in ks if k in listed] for n, ks in enabled.items()}
        enabled = {n: ks for n, ks in enabled.items() if ks}
    if len(enabled) > 1:
        keys = sorted(k for ks in enabled.values() for k in ks)
        others = [k for k in keys if k.split("@", 1)[0] != names.CURRENT] or keys[1:]
        return ("more than one plugin of this name family is enabled in Claude Code "
                "(%s); both would gate every session" % ", ".join(keys),
                "; ".join("/plugin disable %s" % k for k in others))
    from gatekit import hosts
    cached = hosts.codex_cached_names()
    if len(cached) > 1:
        others = [n for n in cached if n != names.CURRENT] or cached[1:]
        return ("Codex has more than one of this plugin's names cached (%s); "
                "both would gate every session" % ", ".join(cached),
                "uninstall %s from Codex (its cache: %s)"
                % (", ".join(others), ", ".join(str(hosts.codex_plugin_cache(n)) for n in others)))
    return None


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
    dual = _dual_plugin(root, data)
    if dual:
        return _axis("hooks registered", verdict.FAIL, dual[0], dual[1])
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
    found = names.existing_state_dirs(root)
    if len(found) > 1:
        # ADR-0029: hooks use the one holding approvals.json.
        unused = [p.name + "/" for p in found if p != state]
        return _axis("project state", verdict.FAIL,
                     "both %s exist; hooks use %s/ and ignore %s"
                     % (" and ".join(p.name + "/" for p in found), state.name, ", ".join(unused)),
                     "copy anything you still need from %s into %s/, then delete %s "
                     "(`migrate` refuses while both exist)"
                     % (", ".join(unused), state.name, ", ".join(unused)))
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
    detail = "%s/ present and parseable" % state.name
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
# by a small scan, not by parsing JS/TS: one pass drops comments and blanks
# string literals (a template literal's `${…}` expressions are followed while
# they close on their own line, so a quote inside one does not end it); then the value after each `webServer:`
# key (quoted or not, after `{` or `,`) or `webServer =` (also
# `const webServer: <type> =`, the annotation skipped) is taken from its first
# `{` or `[` up to the balanced closing brace or bracket, and in it
# `port: <n>` / `url: '<scheme>://<host>:<n>'` outside strings are read, also
# as the fallback after `||` or `??` (`process.env.PORT || 3000`). A value
# that does not open with `{`/`[` (`process.env.CI ? undefined : { … }`) is
# searched for one up to its end; a `webServer` inside a value already read
# is not read again. A port set only from a variable is not found.
PLAYWRIGHT_CONFIGS = tuple("playwright.config." + ext for ext in ("ts", "js", "mjs", "cjs"))
#: Also searched (recursively) for Playwright configs.
E2E_CONFIG_DIR = ("spec", "design", "e2e")
#: Most characters of one `webServer` value read; an unbalanced value stops here.
WEBSERVER_WINDOW = 8000
#: `webServer: <value>` in an object (the key may be quoted), `webServer =
#: <value>` in a declaration (not `==`, `===` or `=>`), and `const webServer:
#: <type> = <value>` — there the `:` opens a type annotation, not the value.
_WEBSERVER_RE = re.compile(
    r"(?:\b(?P<decl>const|let|var)\s+)?(?P<q>['\"]?)\bwebServer(?P=q)"
    r"\s*(?P<sep>:|=(?![=>]))\s*")
#: A line break at depth 0 continues the value only next to these (a
#: ternary or `||` chain split over lines); otherwise it ends it.
_CONTINUES_BEFORE = frozenset("?:|&=(+-*/,")
_CONTINUES_AFTER = frozenset("?:|&.")
_NEXT_CHAR_RE = re.compile(r"\s*(\S)")
#: In a type annotation a line break at depth 0 continues it only after
#: ``:``/``|``/``&`` or before ``|``/``&``/``=`` (a union, an intersection or
#: the value's ``=`` wrapped onto the next line, as Prettier does).
_ANNOTATION_CONTINUES_BEFORE = frozenset(":|&")
_ANNOTATION_CONTINUES_AFTER = frozenset("|&=")
#: At most this many characters between `port:`/`url:` and `||`/`??`, so
#: each match attempt is bounded and a window is read in linear time.
FALLBACK_SPAN = 200
_FALLBACK = r"(?:[^,;{}\[\]\n]{0,%d}?(?:\|\||\?\?)\s*)?" % FALLBACK_SPAN
_PORT_RE = re.compile(r"\bport\s*:\s*" + _FALLBACK + r"(\d{1,5})\b")
_URL_PORT_RE = re.compile(
    r"\burl\s*:\s*" + _FALLBACK
    + r"['\"`][A-Za-z][A-Za-z0-9+.-]*://(?:\[[^\]]*\]|[^'\"`/\s:]+):(\d{1,5})")
PROBE_TIMEOUT_S = 0.3
LSOF_TIMEOUT_S = 3


def _balanced_value(text: str, start: int) -> str:
    """The ``{…}`` or ``[…]`` value opening at *start* of the blanked *text*
    (see :func:`_scan_js`), up to its matching close, at most
    :data:`WEBSERVER_WINDOW` characters; "" when no object or array opens
    there."""
    if start >= len(text) or text[start] not in "{[":
        return ""
    depth = 0
    limit = min(len(text), start + WEBSERVER_WINDOW)
    i = start
    while i < limit:
        ch = text[i]
        if ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
        i += 1
    return text[start:limit]


#: A '...' or "..." literal stops at a line break (JS does not let one span
#: lines), so a quote in a regex literal such as ``/'/g`` blanks at most the
#: rest of its line, not the rest of the file. Template literals span lines.
_QUOTED_RE = {
    "'": re.compile(r"'(?:[^'\\\n]|\\.)*'?", re.S),
    '"': re.compile(r'"(?:[^"\\\n]|\\.)*"?', re.S),
}
#: Template text up to its closing backtick or a ``${``.
_TEMPLATE_TEXT_RE = re.compile(r"(?:[^`\\$]|\\.|\$(?!\{))*", re.S)
#: A whole template read plainly, to the first unescaped backtick.
_PLAIN_TEMPLATE_RE = re.compile(r"`(?:[^`\\]|\\.)*`?", re.S)
#: The next character that changes state, outside and inside a ``${…}``.
_CODE_STOP_RE = re.compile(r"['\"`]|//|/\*")
_EXPR_STOP_RE = re.compile(r"['\"`{}\n]|//|/\*")
_NOT_NEWLINE_RE = re.compile(r"[^\n]")


def _scan_js(text: str) -> tuple:
    """``(code, blanked)`` for JS/TS *text*, both of the same length.

    *code* is *text* without ``//`` and ``/* */`` comments; *blanked* is
    *code* with every string literal blanked after its opening quote (line
    breaks kept), so that ``webServer`` or ``port:`` in a message is not
    taken for a key. A literal that is exactly ``webServer`` in matching
    quotes (a quoted key) is kept.

    A template literal ends at its own closing backtick: each ``${…}`` in it
    is followed to its matching ``}``, with the strings, templates and
    comments inside, and blanked with the template. A ``${…}`` must close on
    the line it opened on. When a line ends inside one — a regex literal's
    quote, ``{`` or ``//`` read as code, or an expression wrapped over lines
    — the outermost template is read again plainly, from its backtick to the
    next one, and so is every template opening on the rest of that line. So
    an unread regex literal costs at most that template, never the rest of
    the file, and each character is read at most three times."""
    code: list = []
    blanked: list = []

    def emit(part: str, blank: bool) -> None:
        code.append(part)
        blanked.append(_NOT_NEWLINE_RE.sub(" ", part) if blank else part)

    depths: list = []  # one brace depth per open `${`, innermost last
    in_text = False    # inside template text (not in a `${…}`)
    opened_at = opened_out = 0  # the outermost template: text index, output chunks
    plain_until = -1   # templates opening before this index are read plainly
    i, n = 0, len(text)
    while i < n:
        line_end = -1
        if in_text:
            end = _TEMPLATE_TEXT_RE.match(text, i).end()
            if depths:
                line_end = text.find("\n", i, end)
            if line_end < 0:
                emit(text[i:end], True)
                i = end
                if i >= n:
                    break
                if text[i] == "`":
                    emit("`", True)
                    i += 1
                else:  # `${`
                    emit("${", True)
                    i += 2
                    depths.append(0)
                in_text = False
                continue
        else:
            inside = bool(depths)
            found = (_EXPR_STOP_RE if depths else _CODE_STOP_RE).search(text, i)
            if not found:
                emit(text[i:], inside)
                break
            emit(text[i:found.start()], inside)
            i = found.start()
            token = found.group(0)
            if token == "\n":
                line_end = i
            elif token == "//":
                end = text.find("\n", i)
                i = n if end < 0 else end
            elif token == "/*":
                end = text.find("*/", i + 2)
                end = n if end < 0 else end + 2
                if inside:
                    line_end = text.find("\n", i, end)
                if line_end < 0:
                    emit(" ", inside)
                    i = end
            elif token in _QUOTED_RE:
                literal = _QUOTED_RE[token].match(text, i).group(0)
                if inside:
                    line_end = text.find("\n", i, i + len(literal))
                    if line_end < 0:
                        emit(literal, True)
                elif literal[1:-1] == "webServer" and literal[-1] == literal[0]:
                    emit(literal, False)
                else:
                    emit(literal[0], False)
                    emit(literal[1:], True)
                if line_end < 0:
                    i += len(literal)
            elif token == "`":
                if not inside and i < plain_until:
                    literal = _PLAIN_TEMPLATE_RE.match(text, i).group(0)
                    emit("`", False)
                    emit(literal[1:], True)
                    i += len(literal)
                    continue
                if not inside:
                    opened_at, opened_out = i, len(code)
                emit("`", inside)
                in_text = True
                i += 1
            elif token == "{":
                depths[-1] += 1
                emit("{", True)
                i += 1
            else:  # "}" inside `${…}`
                if depths[-1]:
                    depths[-1] -= 1
                else:
                    depths.pop()
                    in_text = True
                emit("}", True)
                i += 1
        if line_end >= 0:
            # A line ended inside a `${…}`: read the template plainly.
            del code[opened_out:], blanked[opened_out:]
            literal = _PLAIN_TEMPLATE_RE.match(text, opened_at).group(0)
            emit("`", False)
            emit(literal[1:], True)
            i = opened_at + len(literal)
            depths, in_text = [], False
            plain_until = line_end + 1
    return "".join(code), "".join(blanked)


def _is_key(blanked: str, start: int) -> bool:
    """Whether the ``webServer`` match at *start* stands where an object key
    can: after ``{`` or ``,`` (spaces between), or at the start of the text.
    After ``?`` it is a ternary's value, not a key."""
    i = start - 1
    while i >= 0 and blanked[i].isspace():
        i -= 1
    return i < 0 or blanked[i] in "{,"


def _annotation_end(text: str, start: int) -> tuple:
    """``(value, end)`` for the type annotation of ``const webServer: <type>``
    starting at *start*: the index just after the ``=`` that ends it (-1 when
    the declaration has no value) and how far the search read. Brackets,
    braces, parentheses and ``<>`` nest (a type literal spans lines and holds
    ``;``); ``=>`` is part of a function type. At depth 0 a ``;``, ``,`` or
    closing bracket ends the declaration without a value, and so does a line
    break unless :data:`_ANNOTATION_CONTINUES_BEFORE` /
    :data:`_ANNOTATION_CONTINUES_AFTER` join it to the next line (the rule
    :func:`_value_open` applies, with the annotation's operators)."""
    depth = 0
    last = ""
    limit = min(len(text), start + WEBSERVER_WINDOW)
    i = start
    while i < limit:
        ch = text[i]
        if ch == "=":
            if text.startswith("=>", i):
                i += 2
                continue
            if depth == 0 and not text.startswith("==", i):
                return i + 1, i + 1
        elif ch in "{[(<":
            depth += 1
        elif ch in "}])>":
            if depth == 0:
                return -1, i
            depth -= 1
        elif depth == 0 and ch in ";,":
            return -1, i
        elif depth == 0 and ch == "\n":
            after = _NEXT_CHAR_RE.match(text, i)
            if last not in _ANNOTATION_CONTINUES_BEFORE and not (
                    after and after.group(1) in _ANNOTATION_CONTINUES_AFTER):
                return -1, i
        if not ch.isspace():
            last = ch
        i += 1
    return -1, limit


def _value_open(text: str, start: int) -> tuple:
    """``(open, end)`` for the ``webServer`` value starting at *start*: the
    index of the first ``{``/``[`` in it (-1 when there is none) and how far
    the search read. The value ends at a ``,`` or ``;`` or a closing
    brace, bracket or parenthesis at depth 0, or at a line break at depth 0
    that no operator joins to the next line; *text* is blanked
    (:func:`_scan_js`), so no string holds one of these. At most
    :data:`WEBSERVER_WINDOW` characters are read."""
    depth = 0
    last = ""
    limit = min(len(text), start + WEBSERVER_WINDOW)
    i = start
    while i < limit:
        ch = text[i]
        if ch in "{[":
            return i, i
        elif ch == "(":
            depth += 1
        elif ch in ")}]":
            if depth == 0:
                return -1, i
            depth -= 1
        elif depth == 0 and ch in ",;":
            return -1, i
        elif depth == 0 and ch == "\n":
            after = _NEXT_CHAR_RE.match(text, i)
            if last not in _CONTINUES_BEFORE and not (
                    after and after.group(1) in _CONTINUES_AFTER):
                return -1, i
        if not ch.isspace():
            last = ch
        i += 1
    return -1, limit


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
            code, blanked = _scan_js(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        read_to = 0
        for match in _WEBSERVER_RE.finditer(blanked):
            if match.start() < read_to:
                # Inside a value already read: reading it again finds
                # nothing new and, nested, costs a window per match.
                continue
            start = match.end()
            if match.group("decl") and match.group("sep") == ":":
                start, read_to = _annotation_end(blanked, start)
                if start < 0:
                    continue
            elif match.group("sep") == ":" and not _is_key(blanked, match.start()):
                continue
            opened, read_to = _value_open(blanked, start)
            if opened < 0:
                continue
            window = _balanced_value(blanked, opened)
            read_to = opened + len(window)
            source = code[opened:read_to]
            # Matched in the comment-free text so a URL keeps its port; a
            # match counts only where the key (and a bare port) is code.
            for regex, outside in ((_PORT_RE, (0, 1)), (_URL_PORT_RE, (0,))):
                for found in regex.finditer(source):
                    if any(window[found.start(g)] != source[found.start(g)] for g in outside):
                        continue
                    port = int(found.group(1))
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

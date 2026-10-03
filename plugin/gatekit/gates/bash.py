"""PreToolUse gate for Bash — shell writes obey the same rules as Write.

The Write gate (:mod:`gatekit.gates.write`) decides whether a path may be
written. Without this gate that decision is trivially bypassed: ``cat > x``,
``sed -i``, ``tee``, ``git apply`` all create or change files through the Bash
tool, which the Write gate never sees. A rule that only binds the honest
tool is a convention, not a gate.

This module extracts the files a shell command **would write** and hands each
one to :func:`write.decide_path`. It is a static reading of the command text —
no execution — and it is deliberately conservative:

* When nothing could be denied anyway (no active task scope, spec gate
  approved or absent) only the protected-state check below acts on the
  parse; nothing else is judged.
* When a write's target **cannot be determined** — a variable in the path,
  ``eval``, ``xargs``, ``git apply``, inline interpreter code such as
  ``python3 -c``, an interpreter reading its script from stdin
  (``python3 <<PY``, ``echo … | node``) — and a restriction is active, the
  command is **denied**.
  "Could not tell" is not rounded to "allowed", by the same rule that keeps
  ``unverified`` from being rounded to ``ok``.
* Programs invoked by name (``npm run build``, ``python3 script.py``) are
  outside its reach: it reads shell syntax, not what every binary does.
  One program is the exception: inside a worker session (``GATEKIT_TASK_ID``
  set) a command that runs gatekit's own ``approve`` subcommand is denied
  (ADR-0023), because ``env -u GATEKIT_TASK_ID`` would otherwise hide the
  worker from the refusal in :func:`gatekit.approval.approve`. ``approve
  check`` and ``approve list`` stay allowed; they record nothing.
* gatekit's state — everything under ``.gatekit/`` but ``config.json`` and
  ``eval/**`` — is protected always (ADR-0027 and its amendment), so every
  command is read for it, also when nothing else could be denied: a write
  target there, a removed path (``rm``, ``mv`` sources) that is or contains
  it, a copy or link into a ``.gatekit`` directory, a link to it (``ln``,
  ``cp -l``/``-s``), a path built from a variable assigned a ``.gatekit``
  directory, a ``git checkout`` / ``restore`` / ``reset`` / ``stash push``
  pathspec, a ``tar -C`` / ``unzip -d`` directory or a ``find -exec`` start
  point that is or holds it, or an opaque command whose text names it or
  that runs inside it is denied. Nothing else is judged while no
  restriction is active.

Denial reasons are written in the session's ``output_lang``.
"""
from __future__ import annotations

import fnmatch
import os
import posixpath
import re
import shlex
from typing import Any, Dict, List, Optional, Tuple

if __name__ == "__main__" or __package__ in (None, ""):  # pragma: no cover
    from _bootstrap import ensure_package_path

    ensure_package_path()
else:
    from ._bootstrap import ensure_package_path

    ensure_package_path()

from gatekit import hookio, paths  # noqa: E402
from gatekit.gates import write  # noqa: E402

#: Tokens that end one simple command and start the next.
_SEPARATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", ";;"}

#: Shell wrappers whose real command follows after their own options.
_WRAPPERS = {"sudo", "doas", "env", "nohup", "time", "nice", "command", "exec", "builtin"}

#: Commands that rewrite the working tree at paths we cannot read off argv.
_GIT_OPAQUE = {
    "apply", "am", "checkout", "restore", "switch", "reset", "merge", "rebase",
    "pull", "cherry-pick", "revert", "stash", "clean", "mv", "rm", "worktree",
    "submodule", "filter-branch", "read-tree", "checkout-index", "init", "clone",
}

#: Editors and languages that write wherever their own script says.
_OPAQUE_PROGRAMS = {
    "eval", "xargs", "patch", "trap", "awk", "gawk", "mawk", "nawk",
    "ed", "ex", "vi", "vim", "nvim", "nano", "emacs", "busybox",
}

#: Interpreters that take inline code; with such code we cannot see the writes.
_INTERPRETERS = {
    "python", "python2", "python3", "node", "ruby", "perl", "php", "deno", "bun",
    "ts-node", "tsx", "pwsh",
}
_INLINE_FLAGS = {"-c", "-e", "-E", "-"}

#: Nested shells whose ``-c`` string is parsed recursively.
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}

#: Devices that are never a project write.
_DEVICE_PREFIXES = ("/dev/", "/proc/")

#: ``<<EOF`` … ``EOF`` bodies are data, not commands.
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

_MESSAGES = {
    "en": {
        "opaque": (
            "gatekit: cannot determine which files this shell command writes "
            "({why}), and writes are currently restricted. Use the Write/Edit "
            "tool, or a plain command whose target paths are literal. Command: {cmd}"
        ),
        "approve": (
            "gatekit: a worker never approves. This command runs gatekit's "
            "'approve' subcommand inside a worker session (GATEKIT_TASK_ID={task}); "
            "approval is the user's decision, taken in the host session through "
            "/gatekit:gate. 'approve check' and 'approve list' are allowed. Command: {cmd}"
        ),
    },
    "ko": {
        "opaque": (
            "gatekit: 이 셸 명령이 어떤 파일을 쓰는지 판별할 수 없고({why}) "
            "현재 쓰기가 제한된 상태입니다. Write/Edit 도구를 쓰거나 대상 경로가 "
            "리터럴인 명령을 사용하세요. 명령: {cmd}"
        ),
        "approve": (
            "gatekit: 워커는 승인하지 않습니다. 이 명령은 워커 세션"
            "(GATEKIT_TASK_ID={task}) 안에서 gatekit의 'approve' 하위 명령을 "
            "실행합니다. 승인은 사용자의 결정이며 호스트 세션에서 /gatekit:gate로 "
            "합니다. 'approve check'와 'approve list'는 허용됩니다. 명령: {cmd}"
        ),
    },
}


def _message(lang: str, key: str, **fields: Any) -> str:
    table = _MESSAGES.get(lang, _MESSAGES["en"])
    return table.get(key, _MESSAGES["en"][key]).format(**fields)


class WriteTargets:
    """Result of :func:`extract_write_targets`."""

    __slots__ = ("targets", "opaque", "why", "removed", "copies", "cwds", "unresolved",
                 "linked", "subtrees", "dollar", "assigns")

    def __init__(self) -> None:
        self.targets: List[str] = []
        #: ADR-0027: paths a command deletes or moves away (``rm``, ``mv`` sources).
        self.removed: List[str] = []
        #: ADR-0027: ``(sources, destination, raw sources)`` of ``cp``/``mv``/
        #: ``ln``/``install``/``rsync``; sources and raw sources pair up.
        self.copies: List[Tuple[List[str], str, List[str]]] = []
        #: ADR-0027: every working directory the command may write from.
        self.cwds: List[str] = []
        #: ADR-0027: targets left unresolved (unknown cwd, or a variable in an
        #: earlier segment) whose last segment is literal.
        self.unresolved: List[str] = []
        #: ADR-0027 amendment: what ``ln`` (or ``cp -l``/``-s``) links to.
        self.linked: List[str] = []
        #: ADR-0027 amendment: paths whose contents a command rewrites — git
        #: pathspecs, an archive's extraction directory, ``find`` start points.
        self.subtrees: List[str] = []
        #: ADR-0027 amendment: raw targets that contain a variable, and the
        #: ``VAR=value`` assignments seen earlier in the command.
        self.dollar: List[str] = []
        self.assigns: Dict[str, str] = {}
        self.opaque: bool = False
        self.why: str = ""

    def mark_opaque(self, why: str) -> None:
        if not self.opaque:
            self.opaque = True
            self.why = why


# --------------------------------------------------------------------------
# lexing
# --------------------------------------------------------------------------
def _strip_heredocs(text: str) -> str:
    """Remove here-document bodies so their lines are not read as commands."""
    lines = text.split("\n")
    out: List[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        out.append(line)
        index += 1
        for match in _HEREDOC_RE.finditer(line):
            terminator = match.group(2)
            while index < len(lines) and lines[index].strip() != terminator:
                index += 1
            index += 1  # the terminator line itself
    return "\n".join(out)


def _newlines_to_separators(text: str) -> str:
    """Turn unquoted newlines into ``;`` so lines are separate commands."""
    out: List[str] = []
    quote: Optional[str] = None
    escaped = False
    for ch in text:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\" and quote != "'":
            out.append(ch)
            escaped = True
            continue
        if quote:
            if ch == quote:
                quote = None
            out.append(ch)
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        out.append(";" if ch == "\n" else ch)
    return "".join(out)


def _tokens(command: str) -> Optional[List[str]]:
    """Tokenize with shell operators kept as their own tokens; ``None`` if unlexable."""
    prepared = _newlines_to_separators(_strip_heredocs(command))
    lexer = shlex.shlex(prepared, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _is_operator(token: str) -> bool:
    return bool(token) and all(ch in "();<>|&" for ch in token)


def _split_simple(tokens: List[str], piped: Optional[List[bool]] = None) -> List[List[str]]:
    """Split a token stream into simple commands at control operators.

    When *piped* is given it receives, per command, whether the command
    reads the output of a pipe (the operator before it was ``|`` or ``|&``).
    """
    commands: List[List[str]] = []
    current: List[str] = []
    after_pipe = False
    for token in tokens:
        if _is_operator(token) and ">" not in token and "<" not in token:
            if current:
                commands.append(current)
                if piped is not None:
                    piped.append(after_pipe)
                current = []
            after_pipe = token in ("|", "|&")
            continue
        current.append(token)
    if current:
        commands.append(current)
        if piped is not None:
            piped.append(after_pipe)
    return commands


# --------------------------------------------------------------------------
# path resolution
# --------------------------------------------------------------------------
def _resolve(target: str, cwd: Optional[str]) -> Optional[str]:
    """Resolve *target* against *cwd*; ``None`` when it cannot be known."""
    if "$" in target or "`" in target:
        return None
    if target.startswith("~"):
        target = os.path.expanduser(target)
    if posixpath.isabs(target):
        return posixpath.normpath(target)
    if cwd is None:
        return None
    return posixpath.normpath(posixpath.join(cwd, target))


def _is_device(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _DEVICE_PREFIXES)


def _add(result: WriteTargets, raw: str, cwd: Optional[str], why: str) -> None:
    if raw.startswith("("):
        result.mark_opaque("process substitution")
        return
    resolved = _resolve(raw, cwd)
    if resolved is None:
        if "$" in raw or "`" in raw:
            result.dollar.append(raw)
        last = raw.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        if last and "$" not in last and "`" not in last:
            result.unresolved.append(raw)
        result.mark_opaque(why)
        return
    if _is_device(resolved):
        return
    if resolved not in result.targets:
        result.targets.append(resolved)


# --------------------------------------------------------------------------
# one simple command
# --------------------------------------------------------------------------
def _pull_redirects(words: List[str], result: WriteTargets, cwd: Optional[str]) -> List[str]:
    """Record write redirections and return the remaining argument words."""
    rest: List[str] = []
    index = 0
    while index < len(words):
        token = words[index]
        if _is_operator(token) and ">" in token:
            if "(" in token:
                result.mark_opaque("process substitution")
                index += 1
                continue
            # A bare fd number right before the operator belongs to it.
            if rest and rest[-1].isdigit():
                rest.pop()
            target = words[index + 1] if index + 1 < len(words) else None
            index += 2
            if target is None:
                continue
            if token.endswith("&") and (target.isdigit() or target == "-"):
                continue  # fd duplication such as 2>&1
            if _is_operator(target):
                result.mark_opaque("process substitution")
                continue
            _add(result, target, cwd, "variable in redirect target")
            continue
        if _is_operator(token):  # input redirects: skip operator and operand
            index += 2
            continue
        rest.append(token)
        index += 1
    return rest


#: Reserved words that may precede a simple command (``{ cd x; }``, ``then cd x``).
_KEYWORDS = {"{", "}", "!", "if", "then", "else", "elif", "fi", "do", "done",
             "while", "until"}


#: Builtins whose operands may be ``VAR=value`` assignments.
_DECLARERS = {"export", "local", "declare", "typeset", "readonly"}
_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)


def _record_assignments(words: List[str], result: WriteTargets) -> None:
    """Remember ``VAR=value`` words (prefix assignments and ``export`` & co.)."""
    index = 0
    while index < len(words) and words[index] in _KEYWORDS:
        index += 1
    declaring = index < len(words) and words[index] in _DECLARERS
    for word in words[index + 1:] if declaring else words[index:]:
        match = _ASSIGN_RE.match(word)
        if match:
            result.assigns[match.group(1)] = match.group(2)
        elif not declaring and not word.startswith("-"):
            break


def _strip_wrappers(words: List[str]) -> List[str]:
    """Drop ``sudo``/``env``/``VAR=x`` prefixes and reserved words to reach
    the real command."""
    index = 0
    while index < len(words):
        word = words[index]
        if word in _KEYWORDS:
            index += 1
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", word):
            index += 1
            continue
        if word in _WRAPPERS:
            index += 1
            while index < len(words) and words[index].startswith("-"):
                index += 1
            continue
        break
    return words[index:]


def _positional(args: List[str], consuming: Tuple[str, ...] = ()) -> List[str]:
    """Arguments that are not options; *consuming* options eat their operand."""
    out: List[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in consuming:
            skip = True
            continue
        if arg.startswith("-") and arg != "-":
            continue
        out.append(arg)
    return out


def _sed_in_place(args: List[str]) -> bool:
    for arg in args:
        if arg.startswith("--in-place"):
            return True
        if re.match(r"^-[a-zA-Z]*i", arg):
            return True
    return False


def _flagged_output(
    args: List[str], flags: Tuple[str, ...], result: WriteTargets, cwd: Optional[str], name: str
) -> None:
    """Record the operand of an output flag (``-o file``, ``-o=file``, ``-ofile``)."""
    index = 0
    while index < len(args):
        arg = args[index]
        for flag in flags:
            if arg == flag and index + 1 < len(args):
                _add(result, args[index + 1], cwd, "variable in %s output" % name)
                index += 1
                break
            if arg.startswith(flag + "="):
                _add(result, arg[len(flag) + 1:], cwd, "variable in %s output" % name)
                break
            if len(flag) == 2 and arg.startswith(flag) and len(arg) > 2 and not arg.startswith("--"):
                _add(result, arg[2:], cwd, "variable in %s output" % name)
                break
        index += 1


def _subtree(result: WriteTargets, raw: Optional[str], cwd: Optional[str]) -> None:
    """Record a directory whose contents the command rewrites (ADR-0027
    amendment); the cwd itself (``tar -xf a.tar``) is not recorded."""
    if raw:
        resolved = _resolve(raw, cwd)
        if resolved:
            result.subtrees.append(resolved)


def _archive(name: str, args: List[str], result: WriteTargets, cwd: Optional[str]) -> None:
    """``tar``/``unzip`` extraction writes into a directory; ``zip`` writes an archive."""
    if name == "zip":
        positional = _positional(args)
        if positional:
            _add(result, positional[0], cwd, "variable in zip target")
        return
    if name == "unzip":
        if any(a in ("-l", "-t", "-z", "-p", "-c") for a in args):
            return  # listing / testing / to stdout
        target = None
        for index, arg in enumerate(args):
            if arg == "-d" and index + 1 < len(args):
                target = args[index + 1]
            elif arg.startswith("-d") and len(arg) > 2:
                target = arg[2:]
        _add(result, target or ".", cwd, "variable in unzip directory")
        _subtree(result, target, cwd)
        return
    # tar: the mode lives in the first bare word (``xzf``) or a dashed
    # cluster (``-xf``) or a long option (``--extract``).
    mode_words = [a for i, a in enumerate(args) if a.startswith("-") or i == 0]
    letters = "".join(a.lstrip("-") for a in mode_words if not a.startswith("--"))
    extracting = "x" in letters or any(a in ("--extract", "--get") for a in mode_words)
    creating = "c" in letters or "--create" in mode_words
    if creating:
        _flagged_output(args, ("--file",), result, cwd, name)
        for index, arg in enumerate(args):
            cluster = arg.lstrip("-")
            if not arg.startswith("--") and cluster.endswith("f") and (index == 0 or arg.startswith("-")):
                if index + 1 < len(args):
                    _add(result, args[index + 1], cwd, "variable in tar archive")
        return
    if extracting:
        target = None
        for index, arg in enumerate(args):
            if arg in ("-C", "--directory") and index + 1 < len(args):
                target = args[index + 1]
            elif arg.startswith("--directory="):
                target = arg.split("=", 1)[1]
        _add(result, target or ".", cwd, "variable in tar directory")
        _subtree(result, target, cwd)


def _target_directory(args: List[str]) -> Optional[str]:
    """The operand of ``-t DIR`` / ``-tDIR`` / ``--target-directory[=]DIR``."""
    for index, arg in enumerate(args):
        if arg in ("-t", "--target-directory"):
            return args[index + 1] if index + 1 < len(args) else ""
        if arg.startswith("--target-directory="):
            return arg.split("=", 1)[1]
        if arg.startswith("-t") and len(arg) > 2 and not arg.startswith("--"):
            return arg[2:]
    return None


#: Interpreter options that take an operand (``-W ignore``, ``-r module``).
_INTERPRETER_OPERAND_OPTIONS = {"-W", "-X", "-Q", "-r", "--require", "-I", "--import",
                                "--loader", "--experimental-loader"}


def _script_operand(args: List[str]) -> bool:
    """True when an interpreter's arguments name its script: a file operand,
    or a module (``-m mod``, ``-mmod``)."""
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg == "--":
            return True
        if arg.startswith("-m"):
            return True
        if arg in _INTERPRETER_OPERAND_OPTIONS:
            skip = True
            continue
        if arg.startswith("-"):
            continue
        return True
    return False


def _cp_links(args: List[str]) -> bool:
    """``cp -l``/``-s`` (and clusters such as ``-al``) make links, not copies."""
    for arg in args:
        if arg in ("--link", "--symbolic-link"):
            return True
        if arg.startswith("-") and not arg.startswith("--") and re.search(r"[ls]", arg[1:]):
            return True
    return False


#: ``git`` options before the subcommand that take an operand.
_GIT_OPERAND_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                        "--super-prefix", "--config-env"}
#: Subcommands whose pathspec operands rewrite those paths.
_GIT_PATHSPEC = {
    "checkout": ("-b", "-B", "--orphan"),
    "restore": ("-s", "--source"),
    "reset": (),
    "stash": ("-m", "--message", "--pathspec-from-file"),
}
_STASH_NO_PATHS = {"pop", "apply", "list", "show", "drop", "clear", "branch", "create",
                   "store"}


def _git(rest: List[str], result: WriteTargets, cwd: Optional[str]) -> None:
    index = 0
    while index < len(rest) and rest[index].startswith("-"):
        option = rest[index]
        if option in _GIT_OPERAND_OPTIONS:
            if option == "-C" and index + 1 < len(rest):
                cwd = _resolve(rest[index + 1], cwd)
            index += 2
            continue
        index += 1
    sub = rest[index] if index < len(rest) else ""
    args = rest[index + 1:]
    if sub in _GIT_OPAQUE:
        result.mark_opaque("git %s" % sub)
    if sub not in _GIT_PATHSPEC:
        return
    if sub == "stash":
        if args and args[0] in _STASH_NO_PATHS:
            return
        if args and args[0] in ("push", "save"):
            args = args[1:]
    for spec in _positional(args, consuming=_GIT_PATHSPEC[sub]):
        resolved = _resolve(spec, cwd)
        if resolved:
            result.subtrees.append(resolved)
        elif "$" in spec or "`" in spec:
            result.dollar.append(spec)


def _linked(positional: List[str], target_dir: Optional[str], result: WriteTargets,
            cwd: Optional[str]) -> None:
    """Record what a link points to: relative to the cwd, and (a symlink's
    own rule) relative to the directory the link lands in."""
    if target_dir is not None:
        sources, dest = positional, target_dir
    elif len(positional) == 1:
        sources, dest = positional, "."
    else:
        sources, dest = positional[:-1], positional[-1]
    dest_abs = _resolve(dest, cwd)
    for raw in sources:
        candidates = [_resolve(raw, cwd)]
        if dest_abs and not posixpath.isabs(raw) and "$" not in raw:
            candidates.append(posixpath.normpath(posixpath.join(dest_abs, raw)))
            candidates.append(posixpath.normpath(
                posixpath.join(posixpath.dirname(dest_abs), raw)))
        result.linked.extend(c for c in candidates if c)


def _analyze(words: List[str], result: WriteTargets, cwd: Optional[str],
             piped: bool = False) -> Optional[str]:
    """Inspect one simple command. Returns the new cwd (or ``None`` = unknown)."""
    # ADR-0027 amendment: stdin is fed by a pipe, a here-document or here-string,
    # or an input redirect.
    stdin = piped or any(_is_operator(t) and "<" in t and ">" not in t for t in words)
    _record_assignments(words, result)
    args = _pull_redirects(words, result, cwd)
    args = _strip_wrappers(args)
    if not args:
        return cwd
    name = posixpath.basename(args[0])
    rest = args[1:]

    if name in ("cd", "pushd"):
        operands = [a for a in rest if not (a.startswith("-") and a != "-")]
        if not operands:
            return None  # $HOME — unknown to us
        new = _resolve(operands[0], cwd)
        if new:
            result.cwds.append(new)
        return new
    if name == "popd":
        return None

    if name in _SHELLS:
        if "-c" in rest:
            script = rest[rest.index("-c") + 1] if rest.index("-c") + 1 < len(rest) else ""
            nested = extract_write_targets(script, cwd)
            result.targets.extend(t for t in nested.targets if t not in result.targets)
            result.removed.extend(nested.removed)
            result.copies.extend(nested.copies)
            result.cwds.extend(nested.cwds)
            result.unresolved.extend(nested.unresolved)
            result.linked.extend(nested.linked)
            result.subtrees.extend(nested.subtrees)
            result.dollar.extend(nested.dollar)
            result.assigns.update(nested.assigns)
            if nested.opaque:
                result.mark_opaque(nested.why)
        return cwd

    if name in _OPAQUE_PROGRAMS:
        result.mark_opaque(name)
        return cwd

    if name == "sort":
        _flagged_output(rest, ("-o", "--output"), result, cwd, name)
        return cwd

    if name == "curl":
        if any(a in ("-O", "--remote-name", "-J", "--remote-header-name") for a in rest):
            result.mark_opaque("curl remote file name")
        _flagged_output(rest, ("-o", "--output"), result, cwd, name)
        return cwd

    if name == "wget":
        if "--spider" in rest:
            return cwd
        if any(a in ("-O", "--output-document") or a.startswith(("-O", "--output-document=")) for a in rest):
            _flagged_output(rest, ("-O", "--output-document"), result, cwd, name)
        else:
            result.mark_opaque("wget default file name")
        return cwd

    if name in ("tar", "unzip", "zip"):
        _archive(name, rest, result, cwd)
        return cwd

    if name == "find":
        if any(a in ("-exec", "-execdir", "-ok", "-okdir", "-delete") or a.startswith("-fprint") for a in rest):
            result.mark_opaque("find -exec/-delete")
            for start in rest:
                if start.startswith(("-", "(", "!")):
                    break
                _subtree(result, start, cwd)
        return cwd

    if name == "git":
        _git(rest, result, cwd)
        return cwd

    if name == "tee":
        for target in _positional(rest):
            _add(result, target, cwd, "variable in tee target")
        return cwd

    if name == "sed":
        if _sed_in_place(rest):
            files = [f for f in _positional(rest, consuming=("-e", "-f", "--expression", "--file")) if f]
            if not any(a in ("-e", "-f") or a.startswith("--expression") or a.startswith("--file") for a in rest):
                files = files[1:]  # first positional is the script
            for target in files:
                _add(result, target, cwd, "variable in sed target")
        return cwd

    if name == "perl":
        # Any option cluster ending in e/E takes the script as its operand
        # (``-e``, ``-pe``, ``-pie``); ``-i`` anywhere in a cluster is in-place.
        script_flags = tuple(a for a in rest if re.match(r"^-[a-zA-Z]*[eE]$", a))
        if any(re.match(r"^-[a-zA-Z]*i", a) for a in rest):
            for target in _positional(rest, consuming=script_flags):
                _add(result, target, cwd, "variable in perl target")
        elif script_flags or "-" in rest:
            result.mark_opaque("inline perl code")
        elif stdin and not _script_operand(rest):
            result.mark_opaque("perl script on stdin")
        return cwd

    if name in _INTERPRETERS or re.match(r"^python\d", name):
        if any(a in _INLINE_FLAGS for a in rest):
            result.mark_opaque("inline %s code" % name)
        elif stdin and not _script_operand(rest):
            result.mark_opaque("%s script on stdin" % name)
        return cwd

    if name in ("cp", "mv", "ln", "install", "rsync"):
        positional = _positional(rest, consuming=("-t", "--target-directory", "-m", "-o", "-g"))
        target_dir = _target_directory(rest)
        if name == "ln" or (name == "cp" and _cp_links(rest)):
            _linked(positional, target_dir, result, cwd)
        if target_dir is None and len(positional) >= 2:
            _add(result, positional[-1], cwd, "variable in destination")
            dest_raw, source_raws = positional[-1], positional[:-1]
        elif target_dir is not None:
            result.mark_opaque("%s target directory" % name)
            dest_raw, source_raws = target_dir, positional
        else:
            return cwd
        pairs = [(r, a) for r, a in ((_resolve(a, cwd), a) for a in source_raws) if r]
        dest = _resolve(dest_raw, cwd)
        if dest:
            result.copies.append(([r for r, _ in pairs], dest, [a for _, a in pairs]))
        if name == "mv":
            result.removed.extend(r for r, _ in pairs)
        return cwd

    if name in ("touch", "rm", "rmdir", "unlink", "mkdir", "truncate", "chmod", "chown"):
        consuming = ("-s", "--size") if name == "truncate" else ()
        positional = _positional(rest, consuming=consuming)
        if name in ("chmod", "chown"):
            positional = positional[1:]  # first positional is the mode/owner
        for target in positional:
            _add(result, target, cwd, "variable in %s target" % name)
            if name in ("rm", "rmdir", "unlink"):
                resolved = _resolve(target, cwd)
                if resolved:
                    result.removed.append(resolved)
        return cwd

    if name == "dd":
        for arg in rest:
            if arg.startswith("of="):
                _add(result, arg[3:], cwd, "variable in dd output")
        return cwd

    return cwd


def extract_write_targets(command: str, cwd: Optional[str]) -> WriteTargets:
    """Statically list the paths *command* would write, resolved against *cwd*.

    ``cwd`` may be ``None`` when the working directory is itself unknown, in
    which case every relative target makes the result opaque.
    """
    result = WriteTargets()
    tokens = _tokens(command)
    if tokens is None:
        result.mark_opaque("unbalanced quotes")
        return result
    current = cwd
    if cwd:
        result.cwds.append(cwd)
    piped: List[bool] = []
    for simple, after_pipe in zip(_split_simple(tokens, piped), piped):
        current = _analyze(simple, result, current, after_pipe)
    return result


# --------------------------------------------------------------------------
# a worker never approves (ADR-0023)
# --------------------------------------------------------------------------
#: ``gatekit approve`` options that take an operand.
_APPROVE_OPERAND_OPTIONS = ("--root", "--note", "--by")

#: Fallback for text the lexer cannot split: ``gatekit… approve`` not followed
#: by ``check`` or ``list``.
_APPROVE_RE = re.compile(
    r"gatekit(?:\.py)?['\"]?\s+approve\b(?!\s+(?:check|list)\b)")


def _is_gatekit_entry(words: List[str], index: int) -> bool:
    """True when ``words[index]`` names the gatekit CLI (script, binary or module)."""
    word = words[index]
    base = posixpath.basename(word.replace("\\", "/"))
    return base in ("gatekit.py", "gatekit")


def _approve_records(args: List[str]) -> bool:
    """Arguments after ``approve``: True unless the action is ``check``/``list``."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in _APPROVE_OPERAND_OPTIONS:
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return arg not in ("check", "list")
    return True  # no action: treat as an approval attempt, never round it down


def _words_invoke_approve(words: List[str], depth: int) -> bool:
    for index, word in enumerate(words):
        # Strings handed to ``bash -c``, ``eval`` and the like are commands too.
        if depth < 4 and "approve" in word and (" " in word or "\t" in word):
            if invokes_gatekit_approve(word, depth + 1):
                return True
        if not _is_gatekit_entry(words, index):
            continue
        rest = [w for w in words[index + 1:] if not _is_operator(w)]
        if rest and rest[0] == "approve" and _approve_records(rest[1:]):
            return True
    return False


def invokes_gatekit_approve(command: str, depth: int = 0) -> bool:
    """True when *command* runs ``gatekit approve <path>`` anywhere in it.

    Reads every simple command (wrappers such as ``env -u VAR`` included, since
    the gatekit entry is searched for, not assumed at position 0), nested
    shell and ``eval`` strings, and falls back to a pattern match when the text
    cannot be lexed.
    """
    if "approve" not in command or "gatekit" not in command:
        return False
    tokens = _tokens(command)
    if tokens is None:
        return bool(_APPROVE_RE.search(command))
    for simple in _split_simple(tokens):
        if _words_invoke_approve(simple, depth):
            return True
        if simple and posixpath.basename(simple[0]) == "eval":
            if invokes_gatekit_approve(" ".join(simple[1:]), depth + 1):
                return True
    return False


# --------------------------------------------------------------------------
# protected state (ADR-0027)
# --------------------------------------------------------------------------
#: A path that names ``.gatekit``: what follows decides whether it is the
#: user's (``config.json``, ``eval/``) or gatekit's.
_STATE_MENTION_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])\.gatekit(?![A-Za-z0-9_-])((?:[\\/]+[^\s'\"\\/;|&)<>]*)*)",
    re.IGNORECASE)


def _mentions_state(command: str) -> Optional[str]:
    """The first gatekit-owned path an (opaque) command's text spells — a
    ``.gatekit`` directory itself or anything below it but the user's."""
    for match in _STATE_MENTION_RE.finditer(command):
        rest = [p for p in re.split(r"[\\/]+", match.group(1).lower()) if p and p != "."]
        if not write.user_owned(rest):
            return _STATE + ("/" + "/".join(rest) if rest else "")
    return None


def _lower_abs(path: str) -> str:
    return os.path.normpath(write._canonical(path)).replace("\\", "/").lower().rstrip("/")


_GLOB_CHARS = frozenset("*?[{")
_STATE = paths.STATE_DIRNAME


def _base(path: str) -> str:
    return _lower_abs(path).rsplit("/", 1)[-1]


def _state_path(root) -> str:
    """This project's state directory, realpath'd, lowered, canonical."""
    return _lower_abs(os.path.realpath(str(paths.state_dir(root))))


def _segment_match(name: str, pattern: str) -> bool:
    """Glob match of one segment; braces are read as ``*`` (a superset), and
    a leading dot must be matched literally, as the shell does by default."""
    pattern = re.sub(r"\{[^}]*\}", "*", pattern)
    if name.startswith(".") and not pattern.startswith("."):
        return False
    return fnmatch.fnmatchcase(name, pattern)


def _glob_segments(path: str) -> List[str]:
    """*path* (absolute) as lowered segments, the glob-free prefix realpath'd."""
    parts = _lower_abs(path).split("/")
    first = next((i for i, p in enumerate(parts) if _GLOB_CHARS & set(p)), len(parts))
    prefix = "/".join(parts[:first]) or "/"
    real = _lower_abs(os.path.realpath(prefix)) if first else ""
    return [p for p in real.split("/") if p] + [p for p in parts[first:] if p]


def _glob_hits(path: str, candidates: List[str]) -> bool:
    if not (_GLOB_CHARS & set(path)):
        return False
    pats = _glob_segments(path)
    for cand in candidates:
        segs = [p for p in cand.split("/") if p]
        if len(segs) == len(pats) and all(_segment_match(n, p) for n, p in zip(segs, pats)):
            return True
    return False


def _glob_state_hit(path: str, whole: bool = False) -> bool:
    """A glob that can match something of gatekit's below a ``.gatekit``
    directory in any project (or, with *whole*, the directory itself)."""
    if not (_GLOB_CHARS & set(path)):
        return False
    segs = _glob_segments(path)
    for index, seg in enumerate(segs):
        if not _segment_match(_STATE, seg):
            continue
        rest = segs[index + 1:]
        if not rest:
            if whole:
                return True
            continue
        if _GLOB_CHARS & set(rest[0]) or not write.user_owned(rest):
            return True
    return False


def _contains_protected(root, removed: str) -> bool:
    """True when deleting, moving or linking *removed* takes gatekit's state
    with it: it is a ``.gatekit`` directory, or an ancestor of this project's."""
    state = _state_path(root)
    ancestors = [state]
    while "/" in ancestors[-1].strip("/"):
        ancestors.append(ancestors[-1].rsplit("/", 1)[0])
    if _glob_hits(removed, ancestors) or _glob_state_hit(removed, whole=True):
        return True
    for candidate in {_lower_abs(removed), _lower_abs(os.path.realpath(removed))}:
        if candidate.rsplit("/", 1)[-1] == _STATE:
            return True
        if state.startswith(candidate + "/") or candidate in ("", "/"):
            return True
    return False


def _is_state_dir(path: str) -> bool:
    """True when *path* (absolute) is a ``.gatekit`` directory, as written or
    after realpath."""
    for candidate in (_lower_abs(path), _lower_abs(os.path.realpath(path))):
        if candidate.rsplit("/", 1)[-1] == _STATE:
            return True
    return False


def _state_dir_text(text: str) -> bool:
    """True when *text* (a variable's value, possibly with variables in it)
    spells a ``.gatekit`` directory or a gatekit-owned path below one."""
    segs = [s for s in write._canonical(text).lower().split("/") if s and s != "."]
    for index, seg in enumerate(segs):
        if seg == _STATE and not write.user_owned(segs[index + 1:]):
            return True
    return False


def _copy_hit(root, sources: List[str], dest: str, raws: List[str]) -> Optional[str]:
    """A copy, move or link that lands something in gatekit's state: into a
    ``.gatekit`` directory any source but ``config.json``/``eval`` (and any
    directory copied by contents), into the directory holding ours a
    ``.gatekit`` directory."""
    state = _state_path(root)
    dests = {_lower_abs(dest), _lower_abs(os.path.realpath(dest))}
    into_state = any(d.rsplit("/", 1)[-1] == _STATE for d in dests)
    into_parent = state.rsplit("/", 1)[0] in dests
    for source, raw in zip(sources, raws):
        base = _base(source)
        by_contents = raw.endswith("/") or raw.endswith("/.")
        if into_state and (by_contents or _GLOB_CHARS & set(base)
                           or not write.user_owned([base])):
            return _STATE + "/"
        if into_parent and (_segment_match(_STATE, base)
                            or (by_contents and _dir_holds(source, {_STATE}))):
            return _STATE + "/"
    return None


def _dir_holds(path: str, names) -> bool:
    """True when directory *path* has an entry named one of *names* (any case)."""
    try:
        return os.path.isdir(path) and any(e.lower() in names for e in os.listdir(path))
    except OSError:
        return False


def _gatekit_cwd(root, found: WriteTargets) -> bool:
    """True when one of the command's working directories is gatekit's state:
    a ``.gatekit`` directory or a gatekit-owned directory below one."""
    for cwd in found.cwds:
        if _is_state_dir(cwd) or write.protected_state(root, cwd):
            return True
    return False


def _in_state_cwd(root, command: str, found: WriteTargets) -> bool:
    """True when the command may run from gatekit's state: one of its
    working directories is there (after realpath), or its text names one."""
    return _STATE in command.lower() or _gatekit_cwd(root, found)


def protected_hit(root, command: str, found: WriteTargets) -> Optional[str]:
    """The gatekit-owned path this command would write, remove or replace,
    else ``None`` (ADR-0027 and its amendment). Never raises."""
    try:
        return _protected_hit(root, command, found)
    except (OSError, ValueError, TypeError):
        return None


def _protected_hit(root, command: str, found: WriteTargets) -> Optional[str]:
    for target in found.targets:
        hit = write.protected_state(root, target)
        if hit:
            return hit
        if _glob_state_hit(target):
            return _STATE + "/"
    for removed in found.removed:
        hit = write.protected_state(root, removed)
        if hit:
            return hit
        if _contains_protected(root, removed):
            return _STATE + "/"
    for sources, dest, raws in found.copies:
        hit = _copy_hit(root, sources, dest, raws)
        if hit:
            return hit
    # A link made to gatekit's state, or to a directory holding it, is a
    # second name for it that the rest of the command (or the next) can write.
    for source in found.linked:
        hit = write.protected_state(root, source)
        if hit:
            return hit
        if _contains_protected(root, source):
            return _STATE + "/"
    # Paths whose contents the command rewrites: git pathspecs, an archive's
    # extraction directory, the start points of `find -exec/-delete`.
    for tree in found.subtrees:
        hit = write.protected_state(root, tree)
        if hit:
            return hit
        if _is_state_dir(tree) or _glob_state_hit(tree, whole=True):
            return _STATE + "/"
    # A path built from a variable assigned a .gatekit directory earlier.
    for raw in found.dollar:
        for var, value in found.assigns.items():
            if _state_dir_text(value) and re.search(
                    r"\$\{?%s(?![A-Za-z0-9_])" % re.escape(var), raw):
                return _STATE + "/"
    # A cwd we may have misread (a conditional `cd`, an unknown one): a
    # target named like a file gatekit writes counts when .gatekit is in play.
    for target in list(found.targets) + list(found.unresolved) + list(found.removed):
        if _base(target) in write.PROTECTED_NAMES and _in_state_cwd(root, command, found):
            return _STATE + "/" + _base(target)
    if found.opaque:
        mention = _mentions_state(command)
        if mention:
            return mention
        if _gatekit_cwd(root, found):
            return _STATE + "/"
    return None


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------
def handle(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Judge every file this Bash command would write."""
    if event.get("tool_name") != "Bash":
        return hookio.allow()
    tool_input = event.get("tool_input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return hookio.allow()

    root = hookio.event_root(event)
    task_id = os.environ.get("GATEKIT_TASK_ID")
    if task_id and invokes_gatekit_approve(command):
        return hookio.deny(_message(
            write.session_lang(root, event), "approve", task=task_id, cmd=_shown(command)))

    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    found = extract_write_targets(command, cwd or str(root))
    hit = protected_hit(root, command, found)
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


def _shown(command: str) -> str:
    shown = command.strip().replace("\n", " ")
    if len(shown) > 120:
        shown = shown[:119] + "…"
    return shown


def main() -> None:  # pragma: no cover - exercised via subprocess tests
    hookio.run(handle)


if __name__ == "__main__":  # pragma: no cover
    main()

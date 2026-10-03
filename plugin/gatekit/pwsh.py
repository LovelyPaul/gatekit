"""A static reader of PowerShell command text (ADR-0028).

Claude Code's ``PowerShell`` tool sends its command in ``tool_input.command``,
exactly as the Bash tool does, but the text is PowerShell. This module reads
that text — without running anything — into the record the Bash reader
fills (:class:`gatekit.gates.bash.WriteTargets`), so the PowerShell gate can
hand it to the very same decisions: protected state (ADR-0027), spec before
code and the task's ``write_scope`` (:func:`gatekit.gates.write.decide_path`),
and the ``opaque`` refusal.

It is conservative in the same way the Bash reader is. A write whose target
it cannot read — a variable, a sub-expression or a splat in a path, a path
from the pipeline, an unknown parameter of a write cmdlet, code it cannot see
(``iex $code``, ``cmd /c``, COM objects, reflection) — marks the result
*opaque*, which is denied while a restriction is active. Programs invoked by
name are outside its reach, except that native commands (and the aliases that
are POSIX programs on Linux) are also read by the Bash reader's own analysis
of one simple command, so ``git``, ``tar``, ``sed -i``, ``python -c`` and an
interpreter fed through a pipe classify as they do in Bash.

Public surface: :func:`read`, :func:`invokes_gatekit_approve`,
:func:`mention_text`.
"""
from __future__ import annotations

import base64
import binascii
import os
import posixpath
import re
from typing import Dict, List, Optional, Sequence, Tuple

from gatekit import names as _names  # local variables are called names
from gatekit.gates import bash, write

#: How deep code inside strings (``iex '…'``, ``pwsh -Command '…'``,
#: ``-EncodedCommand``) is followed before the command counts as opaque.
MAX_STRING_DEPTH = 4
#: How deep script blocks and sub-expressions nest before the same.
MAX_BLOCK_DEPTH = 32


class PSWriteTargets(bash.WriteTargets):
    """:class:`bash.WriteTargets` plus the code texts found inside the command
    (decoded ``-EncodedCommand`` strings, ``iex`` and ``-Command`` strings),
    which the protected-state mention check also reads."""

    __slots__ = ("texts",)

    def __init__(self) -> None:
        super().__init__()
        self.texts: List[str] = []


class _Unlexable(ValueError):
    pass


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------
class _Tok:
    """One token. ``kind`` is ``word``, ``group`` (``(…)``, ``$(…)``, ``@(…)``),
    ``block`` (``{…}``, ``@{…}``), ``redir``, ``sep``, ``pipe``, ``comma``,
    ``call`` (``&`` or ``.``) or ``stop`` (``--%``). A word is a *param*
    when it starts with an unquoted ``-`` (``-Path:'x'`` is one)."""

    __slots__ = ("kind", "value", "dynamic", "quoted", "splat", "param")

    def __init__(self, kind: str, value: str = "", dynamic: bool = False,
                 quoted: bool = False, splat: bool = False, param: bool = False) -> None:
        self.kind = kind
        self.value = value
        self.dynamic = dynamic
        self.quoted = quoted
        self.splat = splat
        self.param = param

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "_Tok(%s, %r%s)" % (self.kind, self.value, ", dyn" if self.dynamic else "")


_WS = " \t\r\f\v\u00a0"
_WORD_END = set(_WS) | set("\n;|&,(){}<>")
_VAR_CHARS = re.compile(r"[A-Za-z0-9_:?]")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "a": "\a", "b": "\b",
            "f": "\f", "v": "\v", "e": "\x1b"}


def _skip_single(text: str, i: int) -> int:
    """*i* is just past an opening ``'``; return the index past its close."""
    n = len(text)
    while i < n:
        if text[i] == "'":
            if i + 1 < n and text[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    raise _Unlexable("unterminated single quote")


def _skip_double(text: str, i: int) -> int:
    """*i* is just past an opening ``"``; return the index past its close."""
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "`":
            i += 2
            continue
        if ch == "$" and i + 1 < n and text[i + 1] == "(":
            i = _balanced_end(text, i + 1)
            continue
        if ch == '"':
            if i + 1 < n and text[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    raise _Unlexable("unterminated double quote")


def _here_string_end(text: str, i: int) -> Optional[Tuple[int, int, int]]:
    """When ``text[i:]`` opens a here-string (``@'`` or ``@"`` then a newline),
    return ``(body_start, body_end, index past the close)``."""
    if not (text.startswith("@'", i) or text.startswith('@"', i)):
        return None
    quote = text[i + 1]
    j = i + 2
    while j < len(text) and text[j] in _WS:
        j += 1
    if j >= len(text) or text[j] != "\n":
        return None
    body_start = j + 1
    pattern = re.compile(r"(?m)^" + re.escape(quote) + "@")
    match = pattern.search(text, body_start)
    if not match:
        raise _Unlexable("unterminated here-string")
    body_end = match.start()
    if body_end > body_start and text[body_end - 1] == "\n":
        body_end -= 1
        if body_end > body_start and text[body_end - 1] == "\r":
            body_end -= 1
    return body_start, body_end, match.end()


def _balanced_end(text: str, i: int) -> int:
    """*i* is at ``(`` or ``{``; return the index past the matching close,
    skipping strings, here-strings, comments and escapes."""
    closers = {"(": ")", "{": "}", "[": "]"}
    stack = [closers[text[i]]]
    j = i + 1
    n = len(text)
    while j < n:
        ch = text[j]
        if ch == "`":
            j += 2
            continue
        here = _here_string_end(text, j) if ch == "@" else None
        if here:
            j = here[2]
            continue
        if ch == "'":
            j = _skip_single(text, j + 1)
            continue
        if ch == '"':
            j = _skip_double(text, j + 1)
            continue
        if text.startswith("<#", j):
            end = text.find("#>", j + 2)
            if end < 0:
                raise _Unlexable("unterminated block comment")
            j = end + 2
            continue
        if ch == "#" and (j == 0 or text[j - 1] in _WS + "\n;"):
            end = text.find("\n", j)
            j = n if end < 0 else end
            continue
        if ch in "({":
            stack.append(closers[ch])
        elif ch in ")}":
            if not stack or stack[-1] != ch:
                raise _Unlexable("unbalanced brackets")
            stack.pop()
            if not stack:
                return j + 1
        j += 1
    raise _Unlexable("unbalanced brackets")


def _expandable(body: str, nested: List[str]) -> Tuple[str, bool]:
    """Read the contents of a double-quoted string or ``@" "@`` body: the
    value with escapes applied, and whether it holds a variable or a
    sub-expression (whose code goes to *nested*)."""
    out: List[str] = []
    dynamic = False
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == "`" and i + 1 < n:
            out.append(_ESCAPES.get(body[i + 1], body[i + 1]))
            i += 2
            continue
        if ch == '"' and i + 1 < n and body[i + 1] == '"':
            out.append('"')
            i += 2
            continue
        if ch == "$" and i + 1 < n:
            nxt = body[i + 1]
            if nxt == "(":
                end = _balanced_end(body, i + 1)
                nested.append(body[i + 2:end - 1])
                out.append(body[i:end])
                dynamic = True
                i = end
                continue
            if nxt == "{":
                end = body.find("}", i)
                end = n if end < 0 else end + 1
                out.append(body[i:end])
                dynamic = True
                i = end
                continue
            if _VAR_CHARS.match(nxt) or nxt == "$" or nxt == "^":
                j = i + 1
                while j < n and _VAR_CHARS.match(body[j]):
                    j += 1
                if j == i + 1:
                    j += 1
                out.append(body[i:j])
                dynamic = True
                i = j
                continue
        out.append(ch)
        i += 1
    return "".join(out), dynamic


def _lex(text: str, nested: List[str]) -> List[_Tok]:
    """Split *text* into tokens; code found inside double-quoted strings goes
    to *nested*. Raises :class:`_Unlexable`."""
    toks: List[_Tok] = []
    i = 0
    n = len(text)

    def at_start() -> bool:
        if not toks:
            return True
        last = toks[-1]
        return last.kind in ("sep", "pipe") or (last.kind == "word" and not last.quoted
                                                and last.value.endswith("="))

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else "\0"
        if ch in _WS:
            i += 1
            continue
        if ch == "`" and nxt in ("\n", "\r"):
            i += 2 if nxt == "\n" else 3
            continue
        if ch == "\n":
            toks.append(_Tok("sep", "\n"))
            i += 1
            continue
        if text.startswith("<#", i):
            end = text.find("#>", i + 2)
            if end < 0:
                raise _Unlexable("unterminated block comment")
            i = end + 2
            continue
        if ch == "#":
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if ch == ";":
            toks.append(_Tok("sep", ";"))
            i += 1
            continue
        if ch == "|":
            if nxt == "|":
                toks.append(_Tok("sep", "||"))
                i += 2
            else:
                toks.append(_Tok("pipe", "|"))
                i += 1
            continue
        if ch == "&":
            if nxt == "&":
                toks.append(_Tok("sep", "&&"))
                i += 2
                continue
            rest = text[i + 1:].lstrip(_WS)
            if not rest or rest[0] in "\n;)}":
                toks.append(_Tok("sep", "&"))  # a background job
            else:
                toks.append(_Tok("call", "&"))
            i += 1
            continue
        if ch == ",":
            toks.append(_Tok("comma", ","))
            i += 1
            continue
        if ch in ")}":
            raise _Unlexable("unbalanced brackets")
        if ch in "({" or (ch in "$@" and nxt in "({"):
            start = i if ch in "({" else i + 1
            end = _balanced_end(text, start)
            inner = text[start + 1:end - 1]
            kind = "group" if text[start] == "(" else "block"
            toks.append(_Tok(kind, inner, dynamic=True))
            i = end
            continue
        if ch == ">" or (ch in "123456*" and nxt == ">"):
            j = i if ch == ">" else i + 1
            op = text[i:j + 1]
            j += 1
            if j < n and text[j] == ">":
                op += ">"
                j += 1
            if j + 1 < n and text[j] == "&" and text[j + 1] in "123456":
                op += text[j:j + 2]
                j += 2
            toks.append(_Tok("redir", op))
            i = j
            continue
        if ch == "<":
            i += 1  # reserved in PowerShell; never a write
            continue
        if ch == "." and nxt in _WS and at_start():
            toks.append(_Tok("call", "."))
            i += 1
            continue
        if text.startswith("--%", i) and (i + 3 >= n or text[i + 3] in _WS + "\n"):
            toks.append(_Tok("stop", "--%"))
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        here = _here_string_end(text, i) if ch == "@" else None
        if here:
            body = text[here[0]:here[1]]
            if text[i + 1] == "'":
                toks.append(_Tok("word", body, quoted=True))
            else:
                value, dyn = _expandable(body, nested)
                toks.append(_Tok("word", value, dynamic=dyn, quoted=True))
            i = here[2]
            continue
        if ch == "@" and (nxt.isalnum() or nxt == "_"):
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            toks.append(_Tok("word", text[i:j], dynamic=True, splat=True))
            i = j
            continue
        tok, i = _word(text, i, nested)
        toks.append(tok)
    return toks


def _word(text: str, i: int, nested: List[str]) -> Tuple[_Tok, int]:
    """Read one bareword (with any quoted parts) starting at *i*."""
    parts: List[str] = []
    dynamic = False
    quoted = False
    param = text[i] == "-"
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in _WORD_END:
            break
        if ch == "`":
            if i + 1 < n and text[i + 1] in "\r\n":
                break
            if i + 1 < n:
                parts.append(text[i + 1])
            i += 2
            continue
        if ch == "'":
            end = _skip_single(text, i + 1)
            parts.append(text[i + 1:end - 1].replace("''", "'"))
            quoted = True
            i = end
            continue
        if ch == '"':
            end = _skip_double(text, i + 1)
            value, dyn = _expandable(text[i + 1:end - 1], nested)
            parts.append(value)
            dynamic = dynamic or dyn
            quoted = True
            i = end
            continue
        if ch == "$" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "(":
                end = _balanced_end(text, i + 1)
                nested.append(text[i + 2:end - 1])
                parts.append(text[i:end])
                dynamic = True
                i = end
                continue
            if nxt == "{":
                end = text.find("}", i)
                end = n if end < 0 else end + 1
                parts.append(text[i:end])
                dynamic = True
                i = end
                continue
            if _VAR_CHARS.match(nxt) or nxt in "$^":
                j = i + 1
                while j < n and _VAR_CHARS.match(text[j]):
                    j += 1
                if j == i + 1:
                    j += 1
                parts.append(text[i:j])
                dynamic = True
                i = j
                continue
        parts.append(ch)
        i += 1
    return _Tok("word", "".join(parts), dynamic=dynamic, quoted=quoted, param=param), i


# --------------------------------------------------------------------------
# masking: code text with strings and comments blanked (for pattern checks)
# --------------------------------------------------------------------------
def _mask(text: str) -> str:
    """*text* with string contents and comments replaced by spaces, same length."""
    out = list(text)
    i = 0
    n = len(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    try:
        while i < n:
            ch = text[i]
            if ch == "`":
                i += 2
                continue
            here = _here_string_end(text, i) if ch == "@" else None
            if here:
                blank(here[0], here[1])
                i = here[2]
                continue
            if ch == "'":
                end = _skip_single(text, i + 1)
                blank(i + 1, end - 1)
                i = end
                continue
            if ch == '"':
                end = _skip_double(text, i + 1)
                blank(i + 1, end - 1)
                i = end
                continue
            if text.startswith("<#", i):
                end = text.find("#>", i + 2)
                end = n if end < 0 else end + 2
                blank(i, end)
                i = end
                continue
            if ch == "#" and (i == 0 or text[i - 1] in _WS + "\n;"):
                end = text.find("\n", i)
                end = n if end < 0 else end
                blank(i, end)
                i = end
                continue
            i += 1
    except _Unlexable:
        pass
    return "".join(out)


#: Code that writes where no argument says, or runs code we cannot see.
_OPAQUE_PATTERNS = (
    (re.compile(r"\[\s*(?:system\.)?reflection\.", re.I), "reflection"),
    (re.compile(r"\[\s*(?:system\.)?activator\s*\]", re.I), "reflection"),
    (re.compile(r"\[\s*(?:system\.(?:management\.automation\.)?)?scriptblock\s*\]\s*::", re.I),
     "script block from a string"),
    (re.compile(r"\.\s*invoke(?:member|script|command)?\s*\(", re.I), "reflection"),
    (re.compile(r"\$executioncontext\b", re.I), "engine invocation"),
    (re.compile(r"\[\s*(?:system\.)?net\.", re.I), ".NET network type"),
    (re.compile(r"\[\s*(?:system\.)?io\.(?!(?:path|file|directory)\s*\])[\w.]+\s*\]", re.I),
     ".NET I/O type"),
    (re.compile(r"\[\s*(?:system\.)?io\.(?:file|directory)\s*\]\s*::\s*new\b", re.I),
     ".NET I/O type"),
    (re.compile(r"(?im)^\s*using\s+namespace\b"), "using namespace"),
    (re.compile(r"(?:\)|\$[\w:{}]+)\s*::"), "static call on a computed type"),
    (re.compile(r"::\s*['\"(]"), "computed member name"),
    (re.compile(r"\[[^\]\n]*,[^\]\n]*\]\s*::"), "assembly-qualified type"),
    (re.compile(r"\[\s*(?:system\.)?environment\s*\]\s*::\s*currentdirectory", re.I),
     "process current directory"),
    (re.compile(r"(?i)(?<![\w-])(?:alias|function):"), "alias or function through a provider"),
    (re.compile(r"(?<![:\w])\.\s*(?:delete|moveto|copyto|create|createtext|appendtext|"
                r"createsubdirectory|open|openwrite|encrypt|decrypt|save|downloadfile|"
                r"downloadfileasync|downloadstring|write|writeline|writealltext|"
                r"writeallbytes|writealllines|appendalltext|setaccesscontrol)\s*\(", re.I),
     "method call that may write"),
)

#: ``[IO.File]::…`` / ``[IO.Directory]::…`` static calls.
_STATIC_RE = re.compile(r"\[\s*(?:system\.)?io\.(file|directory)\s*\]\s*::\s*([a-z]+)\s*\(", re.I)
_STATIC_READS = {
    "exists", "readalltext", "readalllines", "readallbytes", "readlines", "openread",
    "opentext", "getattributes", "getcreationtime", "getcreationtimeutc", "getlastwritetime",
    "getlastwritetimeutc", "getlastaccesstime", "getlastaccesstimeutc", "getfiles",
    "getdirectories", "getfilesystementries", "enumeratefiles", "enumeratedirectories",
    "enumeratefilesystementries", "getcurrentdirectory", "getparent", "getdirectoryroot",
    "getlogicaldrives", "readalltextasync", "readalllinesasync", "readallbytesasync",
    "getunixfilemode", "resolvelinktarget",
}
#: Methods whose second argument is the destination and first the source.
_STATIC_COPY = {"copy", "move", "replace"}


# --------------------------------------------------------------------------
# path resolution
# --------------------------------------------------------------------------
class _NonFile:
    pass


_NONFILE = _NonFile()
_PROVIDER_DRIVES = ("env", "variable", "function", "alias", "hklm", "hkcu", "cert", "wsman")
_DEVICES = {"nul", "con", "prn", "aux", "/dev/null", "\\\\.\\nul", "$null"}
_DRIVE_ABS = re.compile(r"^[A-Za-z]:/")
_PWD_RE = re.compile(r"^\$\{?pwd\}?(?=$|[\\/])", re.I)


def _resolve(value: str, dynamic: bool, cwd: Optional[str]):
    """Absolute, canonical (``/``-separated) form of *value*; ``None`` when it
    cannot be known, :data:`_NONFILE` when it is not a file at all."""
    v = value.strip()
    low = v.lower()
    if not v or low in _DEVICES:
        return _NONFILE
    if dynamic:
        match = _PWD_RE.match(v)
        if not match or "$" in v[match.end():] or cwd is None:
            return None
        v = cwd + v[match.end():]
        low = v.lower()
    v = re.sub(r"^(?:microsoft\.powershell\.core\\)?filesystem::", "", v, flags=re.I)
    low = v.lower()
    drive = re.match(r"^([A-Za-z][A-Za-z0-9_]+):", v)
    if drive and drive.group(1).lower() in _PROVIDER_DRIVES:
        return _NONFILE
    if low.startswith("registry::"):
        return _NONFILE
    if drive:
        return None  # another PowerShell drive (Temp:, a mapped name): unknown to us
    if low.startswith(("\\\\?\\unc\\", "//?/unc/")):
        v = "//" + v[8:]
    elif v[:4] in ("\\\\?\\", "\\\\.\\", "//?/", "//./"):
        v = v[4:]
    if v == "~" or v.startswith(("~/", "~\\")):
        v = os.path.expanduser("~") + v[1:]
    text = write._canonical(v)
    if _DRIVE_ABS.match(text) or text.startswith("//"):
        return posixpath.normpath(text)
    if re.match(r"^[A-Za-z]:", text):
        return None  # drive-relative (C:foo)
    if text.startswith("/"):
        base = write._canonical(cwd) if cwd else ""
        if re.match(r"^[A-Za-z]:", base):
            return posixpath.normpath(base[:2] + text)
        return posixpath.normpath(text)
    if cwd is None:
        return None
    return posixpath.normpath(write._canonical(cwd).rstrip("/") + "/" + text)


# --------------------------------------------------------------------------
# cmdlets
# --------------------------------------------------------------------------
_COMMON = {
    "verbose": "switch", "vb": "switch", "debug": "switch", "db": "switch",
    "whatif": "switch", "wi": "switch", "confirm": "switch", "cf": "switch",
    "erroraction": "value", "ea": "value", "warningaction": "value", "wa": "value",
    "informationaction": "value", "infa": "value", "progressaction": "value",
    "proga": "value", "errorvariable": "value", "ev": "value", "warningvariable": "value",
    "wv": "value", "informationvariable": "value", "iv": "value", "outvariable": "value",
    "ov": "value", "outbuffer": "value", "ob": "value", "pipelinevariable": "value",
    "pv": "value", "usetransaction": "switch", "usetx": "switch",
}
_PATHS = {"path": "path", "literalpath": "path", "pspath": "path", "lp": "path"}
_SOURCES = {"path": "source", "literalpath": "source", "pspath": "source", "lp": "source"}
_FILTERS = {"filter": "value", "include": "value", "exclude": "value", "credential": "value",
            "force": "switch"}


def _spec(kind: str, positional: Sequence[str], *tables: Dict[str, str],
          lenient: bool = False) -> dict:
    params: Dict[str, str] = dict(_COMMON)
    for table in tables:
        params.update(table)
    return {"kind": kind, "positional": tuple(positional), "params": params, "lenient": lenient}


_CONTENT = dict(_PATHS, value="value", passthru="switch", nonewline="switch",
                encoding="value", asbytestream="switch", stream="value", **_FILTERS)
_ITEM_PROPERTY = dict(_PATHS, name="value", value="value", propertytype="value", type="value",
                      inputobject="value", passthru="switch", newname="value",
                      destination="value", **_FILTERS)
_EXPORT = dict(_PATHS, filepath="path", inputobject="value", force="switch",
               noclobber="switch", encoding="value", append="switch", depth="value",
               delimiter="value", usecu="switch", useculture="switch",
               notypeinformation="switch", nti="switch", includetypeinformation="switch",
               quotefields="value", usequotes="value", noheader="switch", name="value",
               description="value", scope="value", passthru="switch",
               typename="value", outputmodule="value")

CMDLETS: Dict[str, dict] = {
    "set-content": _spec("write", ("path", "value"), _CONTENT),
    "add-content": _spec("write", ("path", "value"), _CONTENT),
    "clear-content": _spec("write", ("path",), _PATHS, _FILTERS, {"stream": "value"}),
    "out-file": _spec("write", ("path", "encoding"), _PATHS, {
        "filepath": "path", "encoding": "value", "append": "switch", "force": "switch",
        "noclobber": "switch", "nc": "switch", "width": "value", "nonewline": "switch",
        "inputobject": "value"}),
    "tee-object": _spec("tee", ("path",), _PATHS, {
        "filepath": "path", "append": "switch", "encoding": "value", "variable": "variable",
        "inputobject": "value"}),
    "new-item": _spec("new", ("path",), _PATHS, {
        "name": "name", "itemtype": "itemtype", "type": "itemtype", "value": "target",
        "target": "target", "force": "switch", "credential": "value"}),
    "copy-item": _spec("copy", ("source", "dest"), _SOURCES, _FILTERS, {
        "destination": "dest", "container": "switch", "passthru": "switch",
        "recurse": "switch", "tosession": "value", "fromsession": "value"}),
    "move-item": _spec("move", ("source", "dest"), _SOURCES, _FILTERS, {
        "destination": "dest", "passthru": "switch"}),
    "remove-item": _spec("remove", ("path",), _PATHS, _FILTERS, {
        "recurse": "switch", "stream": "value"}),
    "rename-item": _spec("rename", ("path", "newname"), _PATHS, {
        "newname": "newname", "force": "switch", "passthru": "switch", "credential": "value"}),
    "set-item": _spec("write", ("path", "value"), _PATHS, _FILTERS, {
        "value": "value", "passthru": "switch"}),
    "clear-item": _spec("write", ("path",), _PATHS, _FILTERS),
    "set-itemproperty": _spec("write", ("path", "name", "value"), _ITEM_PROPERTY),
    "new-itemproperty": _spec("write", ("path", "name", "value"), _ITEM_PROPERTY),
    "clear-itemproperty": _spec("write", ("path", "name"), _ITEM_PROPERTY),
    "remove-itemproperty": _spec("write", ("path", "name"), _ITEM_PROPERTY),
    "rename-itemproperty": _spec("write", ("path", "name", "newname"), _ITEM_PROPERTY),
    "copy-itemproperty": _spec("write", ("path", "destination", "name"), _ITEM_PROPERTY),
    "move-itemproperty": _spec("write", ("path", "destination", "name"), _ITEM_PROPERTY),
    "set-acl": _spec("write", ("path", "aclobject"), _PATHS, _FILTERS, {
        "aclobject": "value", "inputobject": "value", "passthru": "switch",
        "clearcentralaccesspolicy": "switch"}),
    "export-csv": _spec("write", ("path", "delimiter"), _EXPORT),
    "export-clixml": _spec("write", ("path",), _EXPORT),
    "start-transcript": _spec("transcript", ("path",), _PATHS, {
        "outputdirectory": "outdir", "append": "switch", "force": "switch",
        "noclobber": "switch", "includeinvocationheader": "switch",
        "useminimalheader": "switch"}),
    "compress-archive": _spec("write", ("source", "path"), _SOURCES, {
        "destinationpath": "path", "compressionlevel": "value", "update": "switch",
        "force": "switch", "passthru": "switch"}),
    "expand-archive": _spec("expand", ("source", "path"), _SOURCES, {
        "destinationpath": "path", "force": "switch", "passthru": "switch"}),
    "invoke-webrequest": _spec("download", (), {"outfile": "path"}, lenient=True),
    "invoke-restmethod": _spec("download", (), {"outfile": "path"}, lenient=True),
    "start-bitstransfer": _spec("download", ("value", "path"),
                                {"source": "value", "destination": "path"}, lenient=True),
    "start-process": _spec("process", ("program", "arglist"), {
        "filepath": "program", "argumentlist": "arglist", "args": "arglist",
        "redirectstandardoutput": "path", "rso": "path", "redirectstandarderror": "path",
        "rse": "path", "redirectstandardinput": "value", "rsi": "value",
        "workingdirectory": "wd", "verb": "value", "windowstyle": "value",
        "credential": "value", "environment": "value", "wait": "switch",
        "nonewwindow": "switch", "nnw": "switch", "passthru": "switch",
        "loaduserprofile": "switch", "lup": "switch", "usenewenvironment": "switch"},
        lenient=True),
    "invoke-expression": _spec("iex", ("command",), {"command": "command"}),
    "invoke-command": _spec("icm", ("scriptblock",), {"scriptblock": "command", "workingdirectory": "wd",
                                          "filepath": "script"}, lenient=True),
    "start-job": _spec("icm", ("scriptblock",), {"scriptblock": "command", "workingdirectory": "wd",
                                          "filepath": "script"}, lenient=True),
    "start-threadjob": _spec("icm", ("scriptblock",), {"scriptblock": "command", "workingdirectory": "wd",
                                          "filepath": "script"}, lenient=True),
    "new-object": _spec("newobj", ("typename", "arglist"), {
        "typename": "typename", "comobject": "com", "argumentlist": "value", "args": "value",
        "property": "value", "strict": "switch"}, lenient=True),
    "add-type": _spec("opaque", (), lenient=True),
    "new-psdrive": _spec("opaque", (), lenient=True),
    "foreach-object": _spec("foreach", ("member",), {
        "membername": "member", "process": "value", "begin": "value", "end": "value",
        "remainingscripts": "value", "argumentlist": "value", "inputobject": "value",
        "parallel": "value", "throttlelimit": "value", "timeoutseconds": "value",
        "asjob": "switch"}, lenient=True),
    "unblock-file": _spec("write", ("path",), _PATHS),
    "save-help": _spec("write", ("path",), {"destinationpath": "path", "literalpath": "path"},
                       lenient=True),
    "save-module": _spec("write", (), _PATHS, lenient=True),
    "save-script": _spec("write", (), _PATHS, lenient=True),
    "save-psresource": _spec("write", (), _PATHS, lenient=True),
    "new-modulemanifest": _spec("write", ("path",), {"path": "path"}, lenient=True),
    "new-scriptfileinfo": _spec("write", ("path",), {"path": "path"}, lenient=True),
    "set-authenticodesignature": _spec("write", ("path",), {
        "filepath": "path", "literalpath": "path"}, lenient=True),
    "set-alias": _spec("opaque", (), lenient=True),
    "new-alias": _spec("opaque", (), lenient=True),
    "import-alias": _spec("opaque", (), lenient=True),
    "set-location": _spec("cd", ("path",), _PATHS, {"passthru": "switch", "stackname": "value"}),
    "push-location": _spec("pushd", ("path",), _PATHS, {"passthru": "switch",
                                                        "stackname": "value"}),
    "pop-location": _spec("popd", (), {"passthru": "switch", "stackname": "value"}),
    "set-variable": _spec("setvar", ("name", "value"), {"name": "name", "value": "value"},
                          lenient=True),
    "new-variable": _spec("setvar", ("name", "value"), {"name": "name", "value": "value"},
                          lenient=True),
}

ALIASES = {
    "sc": "set-content", "ac": "add-content", "clc": "clear-content", "tee": "tee-object",
    "ni": "new-item", "mkdir": "mkdir", "md": "mkdir",
    "copy": "copy-item", "cp": "copy-item", "cpi": "copy-item",
    "move": "move-item", "mv": "move-item", "mi": "move-item",
    "rm": "remove-item", "del": "remove-item", "erase": "remove-item", "ri": "remove-item",
    "rd": "remove-item", "rmdir": "remove-item",
    "ren": "rename-item", "rni": "rename-item", "si": "set-item", "cli": "clear-item",
    "sp": "set-itemproperty", "clp": "clear-itemproperty", "rp": "remove-itemproperty",
    "rnp": "rename-itemproperty", "cpp": "copy-itemproperty", "mp": "move-itemproperty",
    "epcsv": "export-csv", "iwr": "invoke-webrequest", "curl": "invoke-webrequest",
    "wget": "invoke-webrequest", "irm": "invoke-restmethod", "saps": "start-process",
    "start": "start-process", "iex": "invoke-expression", "icm": "invoke-command",
    "sajb": "start-job", "ndr": "new-psdrive", "%": "foreach-object", "foreach": "foreach-object",
    "epal": "export-alias", "sal": "set-alias", "nal": "new-alias", "ipal": "import-alias", "cd": "set-location", "chdir": "set-location", "sl": "set-location",
    "pushd": "push-location", "popd": "pop-location", "sv": "set-variable",
    "set": "set-variable", "nv": "new-variable",
}
#: Aliases that are POSIX programs on Linux and macOS, where PowerShell 7
#: runs the program instead.
DUAL = {"cp", "mv", "rm", "rmdir", "mkdir", "tee", "curl", "wget"}
CMDLETS["mkdir"] = dict(CMDLETS["new-item"], kind="mkdir")

_KEYWORDS = {"if", "elseif", "else", "foreach", "for", "while", "do", "until", "switch",
             "try", "catch", "finally", "function", "filter", "param", "return", "throw",
             "trap", "begin", "process", "end", "class", "enum", "exit", "break", "continue",
             "data", "dynamicparam", "workflow", "parallel", "sequence", "inlinescript",
             "using", "clean"}

#: Programs that run code given to them, for ``Start-Process``.
_RUNNERS = {"pwsh", "powershell", "cmd", "bash", "sh", "zsh", "wsl", "python", "python3",
            "py", "node", "ruby", "perl", "php", "deno", "bun", "ts-node", "tsx", "wscript",
            "cscript", "mshta", "rundll32", "regsvr32"}
#: Native programs whose effect the reader does not model.
_NATIVE_OPAQUE = {"cmd": "cmd /c", "subst": "subst", "wsl": "wsl", "fsutil": "fsutil", "certutil": "certutil",
                  "wscript": "wscript", "cscript": "cscript", "mshta": "mshta",
                  "rundll32": "rundll32", "regsvr32": "regsvr32", "msiexec": "msiexec",
                  "expand": "expand", "makecab": "makecab", "mklink": "mklink"}
_SHELL_NAMES = {"pwsh", "powershell"}
_VERSIONED_RUNNER = re.compile(r"^(?:python|pypy|node|ruby|perl|php)[\d.]*$")
_WRITE_MEMBER = re.compile(
    r"(?i)^(?:delete|moveto|copyto|create\w*|open\w*|write\w*|append\w*|save|encrypt|"
    r"decrypt|replace|setaccesscontrol|clear|remove\w*|set\w*|invoke\w*|refresh)$")
_LINK_TYPES = {"symboliclink", "hardlink", "junction"}
_PATH_KINDS = ("path", "source", "dest", "target", "name", "newname", "program")


# --------------------------------------------------------------------------
# the reading context
# --------------------------------------------------------------------------
class _Ctx:
    __slots__ = ("result", "cwd", "stack", "string_depth", "block_depth", "ran_script")

    def __init__(self, result: PSWriteTargets, cwd: Optional[str]) -> None:
        self.result = result
        self.cwd = cwd
        self.stack: List[Optional[str]] = []
        self.string_depth = 0
        self.block_depth = 0
        #: a script file or interpreter script runs; one written by the same
        #: command could do anything (ADR-0028 review)
        self.ran_script = False


class _Value:
    """One argument value: a string and whether it is only known at run time."""

    __slots__ = ("text", "dynamic", "splat", "code")

    def __init__(self, text: str, dynamic: bool, splat: bool = False,
                 code: Optional[str] = None) -> None:
        self.text = text
        self.dynamic = dynamic
        self.splat = splat
        self.code = code  # the inner code of a group or block token


def _value_of(tok: _Tok) -> _Value:
    if tok.kind == "group":
        return _Value("$(%s)" % tok.value, True, code=tok.value)
    if tok.kind == "block":
        return _Value("${%s}" % tok.value, True, code=tok.value)
    return _Value(tok.value, tok.dynamic, tok.splat)


def _target(ctx: _Ctx, value: _Value, why: str) -> Optional[str]:
    """Record *value* as a write target; returns its resolved path."""
    result = ctx.result
    if value.splat:
        result.mark_opaque("splatted parameters")
        return None
    path = _resolve(value.text, value.dynamic, ctx.cwd)
    if path is _NONFILE:
        return None
    if path is None:
        raw = value.text
        if value.dynamic:
            result.dollar.append(raw.lower())
        last = raw.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        if last and "$" not in last and "(" not in last:
            result.unresolved.append(raw)
        result.mark_opaque(why)
        return None
    if path not in result.targets:
        result.targets.append(path)
    return path


def _resolved(ctx: _Ctx, value: _Value) -> Optional[str]:
    path = _resolve(value.text, value.dynamic, ctx.cwd)
    return path if isinstance(path, str) else None


# --------------------------------------------------------------------------
# reading text
# --------------------------------------------------------------------------
def _read_text(text: str, ctx: _Ctx) -> None:
    """Read *text* (a whole command, or code found inside one) into *ctx*."""
    nested: List[str] = []
    try:
        toks = _lex(text, nested)
    except _Unlexable as err:
        ctx.result.mark_opaque(str(err))
        return
    masked = _mask(text)
    for pattern, why in _OPAQUE_PATTERNS:
        if pattern.search(masked):
            ctx.result.mark_opaque(why)
    _static_calls(text, masked, ctx)
    for code in nested:
        _read_nested(code, ctx)
    statement: List[_Tok] = []
    for tok in toks + [_Tok("sep", ";")]:
        if tok.kind == "sep":
            if statement:
                _statement(statement, ctx)
            statement = []
            continue
        statement.append(tok)


def _read_nested(code: str, ctx: _Ctx) -> None:
    """Read code found inside a block, sub-expression or double-quoted string;
    a location change inside it leaves the cwd unknown afterwards."""
    if ctx.block_depth >= MAX_BLOCK_DEPTH:
        ctx.result.mark_opaque("nested too deep")
        return
    before = ctx.cwd
    ctx.block_depth += 1
    try:
        _read_text(code, ctx)
    finally:
        ctx.block_depth -= 1
    if ctx.cwd != before:
        ctx.cwd = None


def _read_string(code: str, ctx: _Ctx) -> None:
    """Read code handed over as a string (``iex``, ``-Command``)."""
    if ctx.string_depth >= MAX_STRING_DEPTH:
        ctx.result.mark_opaque("nested too deep")
        return
    ctx.result.texts.append(code)
    ctx.string_depth += 1
    try:
        _read_text(code, ctx)
    finally:
        ctx.string_depth -= 1


def _static_calls(text: str, masked: str, ctx: _Ctx) -> None:
    """``[IO.File]::WriteAllText('x', …)`` and the like."""
    for match in _STATIC_RE.finditer(masked):
        method = match.group(2).lower()
        if method in _STATIC_READS:
            continue
        try:
            end = _balanced_end(text, match.end() - 1)
            args = _call_args(text[match.end():end - 1])
        except _Unlexable:
            ctx.result.mark_opaque("unreadable .NET call")
            continue
        if method == "setcurrentdirectory":
            ctx.cwd = None
            ctx.result.mark_opaque(".NET current directory")
            continue
        if not args or any(a is None for a in args[:2 if method in _STATIC_COPY else 1]):
            ctx.result.mark_opaque(".NET call with a computed path")
            continue
        if method in _STATIC_COPY and len(args) >= 2:
            source, dest = args[0], args[1]
            dest_path = _target(ctx, dest, ".NET destination")
            src_path = _resolved(ctx, source)
            if dest_path and src_path:
                ctx.result.copies.append(([src_path], dest_path, [source.text.replace("\\", "/")]))
            if method in ("move", "replace") and src_path:
                ctx.result.removed.append(src_path)
                if src_path not in ctx.result.targets:
                    ctx.result.targets.append(src_path)
            continue
        if method == "createsymboliclink" and len(args) >= 2 and args[1] is not None:
            linked = _resolved(ctx, args[1])
            if linked:
                ctx.result.linked.append(linked)
        path = _target(ctx, args[0], ".NET call with a computed path")
        if path and method == "delete":
            ctx.result.removed.append(path)


def _call_args(inner: str) -> List[Optional[_Value]]:
    """Comma-separated arguments of a .NET call; ``None`` for one that is not
    a single literal string."""
    toks = _lex(inner, [])
    args: List[List[_Tok]] = [[]]
    for tok in toks:
        if tok.kind == "comma":
            args.append([])
        else:
            args[-1].append(tok)
    out: List[Optional[_Value]] = []
    for arg in args:
        if len(arg) == 1 and arg[0].kind == "word" and arg[0].quoted and not arg[0].dynamic:
            out.append(_Value(arg[0].value, False))
        else:
            out.append(None)
    return out


def _statement(toks: List[_Tok], ctx: _Ctx) -> None:
    elements: List[List[_Tok]] = [[]]
    for tok in toks:
        if tok.kind == "pipe":
            elements.append([])
        else:
            elements[-1].append(tok)
    for index, element in enumerate(elements):
        if element:
            _element(element, ctx, piped=index > 0)


_ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "??="}
_VAR_WORD = re.compile(r"^(?:\[[^\]]*\])*\$\{?([A-Za-z_][\w:]*)\}?$")
_VAR_ASSIGN = re.compile(r"^(?:\[[^\]]*\])*\$\{?([A-Za-z_][\w:]*)\}?\s*[-+*/%?]?\??=(.*)$", re.S)


def _element(toks: List[_Tok], ctx: _Ctx, piped: bool) -> None:
    """One pipeline element: redirections, nested code, then the command."""
    rest: List[_Tok] = []
    index = 0
    while index < len(toks):
        tok = toks[index]
        if tok.kind == "stop":
            ctx.result.mark_opaque("--% stop-parsing token")
            break
        if tok.kind == "redir":
            index += 1
            if "&" in tok.value:
                continue  # stream merge such as 2>&1
            if index < len(toks) and toks[index].kind in ("word", "group", "block"):
                _target(ctx, _value_of(toks[index]), "variable in redirect target")
                index += 1
            continue
        rest.append(tok)
        index += 1
    for tok in rest:
        if tok.kind in ("group", "block"):
            _read_nested(tok.value, ctx)
    _command(rest, ctx, piped)


def _command(toks: List[_Tok], ctx: _Ctx, piped: bool) -> None:
    if not toks:
        return
    call = None
    if toks[0].kind == "call":
        call = toks[0].value
        toks = toks[1:]
        if not toks:
            return
    head = toks[0]
    if call is None and head.kind == "word" and head.value == "." and not head.quoted:
        call, toks = ".", toks[1:]  # `.(…)`: dot-sourcing what follows
        if not toks:
            return
        head = toks[0]
    if head.kind == "group" and call is not None:
        ctx.result.mark_opaque("command from a sub-expression")
        return
    if head.kind != "word":
        return  # a block or sub-expression: already read
    if call is None:
        assigned = _assignment(toks, ctx)
        if assigned is not None:
            _command(assigned, ctx, piped)
            return
        if head.quoted or head.dynamic or head.value[:1] in "[0123456789-+!":
            return  # an expression, not a command
        if head.value.lower() in _KEYWORDS and not (piped and head.value.lower() == "foreach"):
            _command(toks[1:], ctx, piped)
            return
    elif head.dynamic or head.splat:
        ctx.result.mark_opaque("command from a variable")
        return
    raw = head.value
    args = _args(toks[1:])
    if raw.lower().endswith(".ps1"):
        ctx.ran_script = True
        return  # a script: a program invoked by name
    _dispatch(raw, args, ctx, piped)


def _assignment(toks: List[_Tok], ctx: _Ctx) -> Optional[List[_Tok]]:
    """For ``$x = …``: record the value and return the tokens of its right side."""
    head = toks[0]
    right = _assignment_right(toks, ctx)
    if right is not None and "pwd" in ctx.result.assigns:
        ctx.cwd = None  # $PWD reassigned: it no longer names the location
    return right


def _assignment_right(toks: List[_Tok], ctx: _Ctx) -> Optional[List[_Tok]]:
    head = toks[0]
    match = _VAR_ASSIGN.match(head.value) if not head.quoted else None
    if match and head.dynamic:
        name, value = match.group(1), match.group(2)
        right = toks[1:]
        if value:
            ctx.result.assigns[name.lower()] = value
        elif right and right[0].kind == "word":
            ctx.result.assigns[name.lower()] = right[0].value
        return right
    match = _VAR_WORD.match(head.value) if head.dynamic and not head.quoted else None
    if match and len(toks) > 1 and toks[1].kind == "word" and toks[1].value in _ASSIGN_OPS:
        right = toks[2:]
        if right and right[0].kind == "word":
            ctx.result.assigns[match.group(1).lower()] = right[0].value
        return right
    return None


def _args(toks: List[_Tok]) -> List[List[_Tok]]:
    """Arguments: each a list of tokens joined by commas (an array)."""
    args: List[List[_Tok]] = []
    joining = False
    for tok in toks:
        if tok.kind == "comma":
            joining = True
            continue
        if tok.kind == "call":
            continue
        if joining and args:
            args[-1].append(tok)
        else:
            args.append([tok])
        joining = False
    return args


def _canonical_name(raw: str) -> Tuple[str, bool]:
    """``(name, native)``: the lowered command name with any directory and
    module qualifier removed; *native* when it names an executable file."""
    base = re.split(r"[\\/]", raw)[-1].lower()
    match = re.match(r"^(.*)\.(exe|com|cmd|bat)$", base)
    if match:
        return match.group(1), True
    if re.search(r"[\\/]", raw) and "-" not in base:
        return base, True  # a path to a program
    return base, False


def _dispatch(raw: str, args: List[List[_Tok]], ctx: _Ctx, piped: bool) -> None:
    name, native = _canonical_name(raw)
    if not native:
        cmdlet = ALIASES.get(name, name)
        spec = CMDLETS.get(cmdlet)
        if spec is None and cmdlet.startswith("export-") and cmdlet != "export-modulemember":
            spec = _spec("write", ("path",), _EXPORT, lenient=True)
        if spec is not None:
            if name in DUAL and _bind(spec, args).unknown:
                # PowerShell would refuse the parameter; on Linux and macOS
                # the name is the POSIX program, so read it as that.
                _native(name, args, ctx, piped)
                return
            _run_cmdlet(cmdlet, spec, args, ctx, piped)
            return
        if "-" in name:
            return  # another cmdlet or function: invoked by name
    _native(name, args, ctx, piped)


# --------------------------------------------------------------------------
# parameter binding
# --------------------------------------------------------------------------
class _Binding:
    __slots__ = ("named", "unknown", "extra")

    def __init__(self) -> None:
        self.named: Dict[str, List[_Value]] = {}
        self.unknown: Optional[str] = None
        self.extra = False

    def values(self, kind: str) -> List[_Value]:
        return self.named.get(kind, [])


_PARAM_RE = re.compile(r"^-([A-Za-z_][\w-]*)(:?)(.*)$", re.S)


def _param_kind(spec: dict, given: str) -> Optional[Tuple[str, str]]:
    """``(canonical name, kind)`` for a parameter spelled *given* (lowered),
    by exact name or unique prefix; an ambiguous prefix that could be a path
    is read as the path (the conservative side)."""
    params = spec["params"]
    if given in params:
        return given, params[given]
    candidates = [(p, k) for p, k in params.items() if p.startswith(given)]
    if not candidates:
        return None
    kinds = {k for _, k in candidates}
    if len(kinds) == 1:
        return candidates[0]
    for wanted in _PATH_KINDS + ("command", "arglist", "variable", "itemtype", "typename",
                                 "com", "value"):
        for p, k in candidates:
            if k == wanted:
                return p, k
    return candidates[0]


def _bind(spec: dict, args: List[List[_Tok]]) -> _Binding:
    binding = _Binding()
    positional: List[List[_Tok]] = []
    index = 0
    while index < len(args):
        arg = args[index]
        first = arg[0]
        if len(arg) == 1 and first.kind == "word" and first.param and first.value == "--":
            positional.extend(args[index + 1:])  # `--` ends the parameters
            break
        match = _PARAM_RE.match(first.value) if (
            len(arg) == 1 and first.kind == "word" and first.param) else None
        if match and not first.value.startswith("--"):
            found = _param_kind(spec, match.group(1).lower())
            if found is None:
                if binding.unknown is None:
                    binding.unknown = match.group(1)
                index += 1
                continue
            _, kind = found
            if kind == "switch":
                index += 1
                continue
            if match.group(3):
                values = [_Value(match.group(3), first.dynamic and "$" in match.group(3))]
            elif index + 1 < len(args):
                index += 1
                values = [_value_of(t) for t in args[index]]
            else:
                values = []
            binding.named.setdefault(kind, []).extend(values)
            index += 1
            continue
        positional.append(arg)
        index += 1
    slots = [k for k in spec["positional"]]
    for arg in positional:
        while slots and slots[0] in binding.named:
            slots.pop(0)
        if not slots:
            binding.extra = True
            break
        kind = slots.pop(0)
        binding.named.setdefault(kind, []).extend(_value_of(t) for t in arg)
    return binding


# --------------------------------------------------------------------------
# cmdlet effects
# --------------------------------------------------------------------------
def _run_cmdlet(cmdlet: str, spec: dict, args: List[List[_Tok]], ctx: _Ctx, piped: bool) -> None:
    binding = _bind(spec, args)
    kind = spec["kind"]
    result = ctx.result
    if (binding.unknown or binding.extra) and not spec["lenient"]:
        if kind not in ("cd", "pushd", "popd", "setvar"):
            result.mark_opaque("unknown parameter of %s" % cmdlet if binding.unknown
                               else "unexpected argument of %s" % cmdlet)
            return
    why = "variable in %s target" % cmdlet

    if kind in ("cd", "pushd"):
        paths = binding.values("path")
        if kind == "pushd":
            ctx.stack.append(ctx.cwd)
        if not paths:
            ctx.cwd = ctx.cwd if kind == "pushd" else None
            return
        value = paths[0]
        if not value.dynamic and value.text in ("-", "+"):
            ctx.cwd = None
            return
        new = _resolve(value.text, value.dynamic, ctx.cwd)
        ctx.cwd = new if isinstance(new, str) else None
        if ctx.cwd:
            result.cwds.append(ctx.cwd)
        return
    if kind == "popd":
        ctx.cwd = ctx.stack.pop() if ctx.stack else None
        return
    if kind == "setvar":
        names, values = binding.values("name"), binding.values("value")
        if names and values and not names[0].dynamic:
            result.assigns[names[0].text.lower()] = values[0].text
        return
    if kind == "opaque":
        result.mark_opaque(cmdlet)
        return
    if kind == "iex":
        commands = binding.values("command")
        if not commands:
            result.mark_opaque("%s of the pipeline" % cmdlet)
        for value in commands:
            if value.dynamic or value.splat:
                result.mark_opaque("%s of a computed string" % cmdlet)
            else:
                _read_string(value.text, ctx)
        return
    if kind == "icm":
        if binding.values("wd"):
            result.mark_opaque("%s in another working directory" % cmdlet)
        if binding.values("script"):
            ctx.ran_script = True
        for value in binding.values("command"):
            if value.code is None and (value.dynamic or value.splat):
                result.mark_opaque("%s of a variable" % cmdlet)
        return
    if kind == "foreach":
        for value in binding.values("member"):
            if value.code is not None:
                continue
            if value.dynamic or value.splat or _WRITE_MEMBER.match(value.text):
                result.mark_opaque("method call that may write")
        return
    if kind == "newobj":
        if binding.values("com"):
            result.mark_opaque("COM object")
            return
        for value in binding.values("typename"):
            if value.dynamic or re.search(
                    r"(^|\.)(io|net)\.|streamwriter|filestream|webclient|fileinfo|"
                    r"directoryinfo|zipfile|xmlwriter|xmldocument", value.text, re.I):
                result.mark_opaque(".NET object that may write")
        return
    if kind == "process":
        for value in binding.values("path"):
            _target(ctx, value, "variable in Start-Process redirect")
        programs = binding.values("program")
        if not programs:
            return
        program = programs[0]
        if program.dynamic:
            result.mark_opaque("Start-Process of a variable")
            return
        name = _canonical_name(program.text)[0]
        if name.endswith(".ps1"):
            ctx.ran_script = True
            return
        if name in _RUNNERS or _VERSIONED_RUNNER.match(name) or name in _names.launcher_names():
            result.mark_opaque("Start-Process %s" % name)
            return
        values: List[_Value] = []
        for value in binding.values("arglist"):
            if value.dynamic or value.splat:
                result.mark_opaque("Start-Process arguments from a variable")
                return
            values.extend(_Value(part, False) for part in value.text.split())
        saved = ctx.cwd
        for wd in binding.values("wd"):
            new = _resolve(wd.text, wd.dynamic, ctx.cwd)
            ctx.cwd = new if isinstance(new, str) else None
        try:
            _native_values(name, values, ctx, False)
        finally:
            ctx.cwd = saved
        return
    if kind == "download":
        for value in binding.values("path"):
            _target(ctx, value, "variable in download target")
        return
    if kind == "transcript":
        paths = binding.values("path")
        for value in binding.values("outdir"):
            paths.append(_Value(value.text.rstrip("\\/") + "/PowerShell_transcript.txt",
                                value.dynamic, value.splat))
        if not paths:
            result.mark_opaque("transcript to the default location")
        for value in paths:
            _target(ctx, value, why)
        return
    if kind == "tee":
        if binding.values("variable") and not binding.values("path"):
            return
        _write_paths(binding.values("path"), ctx, piped, why)
        return
    if kind == "write":
        _write_paths(binding.values("path"), ctx, piped, why)
        return
    if kind == "remove":
        for path in _write_paths(binding.values("path"), ctx, piped, why):
            result.removed.append(path)
        return
    if kind == "expand":
        dests = binding.values("path")
        if not dests:
            sources = binding.values("source")
            stem = sources[0].text.replace("\\", "/").rsplit("/", 1)[-1] if sources else ""
            stem = re.sub(r"\.zip$", "", stem, flags=re.I)
            dests = [_Value(stem, bool(sources and sources[0].dynamic) or not stem)]
        for value in dests:
            path = _target(ctx, value, why)
            if path:
                result.subtrees.append(path)
        return
    if kind in ("new", "mkdir"):
        _new_item(binding, ctx, piped, why, kind)
        return
    if kind in ("copy", "move"):
        _copy_move(binding, ctx, piped, why, kind)
        return
    if kind == "rename":
        paths, names = binding.values("path"), binding.values("newname")
        if not paths and piped:
            result.mark_opaque("path from the pipeline")
            return
        for value in paths:
            source = _resolved(ctx, value) if not value.dynamic else None
            if source is None:
                _target(ctx, value, why)
                continue
            result.removed.append(source)
            for new in names:
                if new.dynamic:
                    result.mark_opaque("variable in the new name")
                    continue
                parent = posixpath.dirname(source)
                _target(ctx, _Value(parent + "/" + new.text.replace("\\", "/"), False), why)
        return


def _write_paths(values: List[_Value], ctx: _Ctx, piped: bool, why: str) -> List[str]:
    if not values:
        ctx.result.mark_opaque("path from the pipeline" if piped else "no path given")
        return []
    out = []
    for value in values:
        path = _target(ctx, value, why)
        if path:
            out.append(path)
    return out


def _new_item(binding: _Binding, ctx: _Ctx, piped: bool, why: str, kind: str) -> None:
    paths = binding.values("path")
    names = binding.values("name")
    if not paths:
        if not names:
            ctx.result.mark_opaque("path from the pipeline" if piped else "no path given")
            return
        paths = [_Value(".", False)]
    created: List[str] = []
    for value in paths:
        if not names:
            path = _target(ctx, value, why)
            if path:
                created.append(path)
            continue
        for name in names:
            joined = _Value(value.text.rstrip("\\/") + "/" + name.text,
                            value.dynamic or name.dynamic, value.splat or name.splat)
            path = _target(ctx, joined, why)
            if path:
                created.append(path)
    itemtypes = [v.text.lower() for v in binding.values("itemtype")]
    if kind == "new" and any(t in _LINK_TYPES for t in itemtypes):
        for value in binding.values("target"):
            if value.dynamic:
                ctx.result.mark_opaque("variable in link target")
                continue
            linked = _resolved(ctx, value)
            if linked:
                ctx.result.linked.append(linked)
            text = value.text.replace("\\", "/")
            if not posixpath.isabs(text) and not re.match(r"^[A-Za-z]:", text):
                for link in created:
                    ctx.result.linked.append(posixpath.normpath(
                        posixpath.join(posixpath.dirname(link), text)))


def _copy_move(binding: _Binding, ctx: _Ctx, piped: bool, why: str, kind: str) -> None:
    result = ctx.result
    sources = binding.values("source")
    dests = binding.values("dest") or [_Value(".", False)]
    if not sources:
        if not piped:
            result.mark_opaque("no path given")
            return
        result.mark_opaque("path from the pipeline")
        sources = [_Value("*", False)]
    for dest_value in dests:
        dest = _target(ctx, dest_value, "variable in destination")
        pairs = []
        for value in sources:
            if value.splat:
                result.mark_opaque("splatted parameters")
                continue
            path = _resolved(ctx, value) if not value.dynamic else None
            if path is None:
                if value.dynamic:
                    result.dollar.append(value.text.lower())
                result.mark_opaque("variable in source")
                continue
            pairs.append((path, value.text.replace("\\", "/")))
        if dest:
            result.copies.append(([p for p, _ in pairs], dest, [r for _, r in pairs]))
        if kind == "move":
            for path, _ in pairs:
                result.removed.append(path)


# --------------------------------------------------------------------------
# native programs
# --------------------------------------------------------------------------
def _native(name: str, args: List[List[_Tok]], ctx: _Ctx, piped: bool) -> None:
    _native_values(name, [_value_of(t) for arg in args for t in arg], ctx, piped)


def _native_values(name: str, flat: List[_Value], ctx: _Ctx, piped: bool) -> None:
    result = ctx.result
    if name in _SHELL_NAMES:
        _nested_powershell(flat, ctx, piped)
        return
    if name in _NATIVE_OPAQUE:
        result.mark_opaque(_NATIVE_OPAQUE[name])
        return
    if name in ("xcopy", "robocopy"):
        operands = [v for v in flat if not v.text.startswith("/")]
        if len(operands) >= 2:
            path = _target(ctx, operands[1], "variable in %s destination" % name)
            if path:
                result.subtrees.append(path)
                src = _resolved(ctx, operands[0])
                if src:
                    result.copies.append(([src], path, [operands[0].text.replace("\\", "/")]))
        else:
            result.mark_opaque("%s destination" % name)
        return
    if name == "py":
        name = "python"
    if (name in _RUNNERS or _VERSIONED_RUNNER.match(name)) and any(
            not v.text.startswith("-") for v in flat) and not any(
            v.text in bash._INLINE_FLAGS for v in flat):
        ctx.ran_script = True
    keep = name in bash._SHELLS  # a POSIX script: leave its text alone
    words = [name]
    for value in flat:
        if value.splat:
            result.mark_opaque("splatted parameters")
            return
        text = value.text
        if value.dynamic and "$" not in text:
            text = "$" + text
        if not keep:
            text = text.replace("\\", "/")
        words.append(text)
    found = bash.WriteTargets()
    base = write._canonical(ctx.cwd) if ctx.cwd else None
    bash._analyze(words, found, base, piped)
    _merge(result, found)


_EMBEDDED_DRIVE = re.compile(r"(?:^|/)([A-Za-z]:/.*)$")


def _fix(path: str) -> str:
    """A path the POSIX reader joined onto the cwd although it was a
    drive-absolute Windows path (``/proj/C:/x``) becomes ``C:/x``."""
    match = _EMBEDDED_DRIVE.search(path)
    if match and match.start(1) > 0:
        return posixpath.normpath(match.group(1))
    return path


def _merge(into: PSWriteTargets, found: bash.WriteTargets) -> None:
    for path in found.targets:
        path = _fix(path)
        if path not in into.targets:
            into.targets.append(path)
    into.removed.extend(_fix(p) for p in found.removed)
    into.copies.extend(([_fix(s) for s in srcs], _fix(dest), raws)
                       for srcs, dest, raws in found.copies)
    into.cwds.extend(_fix(p) for p in found.cwds)
    into.unresolved.extend(found.unresolved)
    into.linked.extend(_fix(p) for p in found.linked)
    into.subtrees.extend(_fix(p) for p in found.subtrees)
    into.dollar.extend(d.lower() for d in found.dollar)
    into.assigns.update({k.lower(): v for k, v in found.assigns.items()})
    if found.opaque:
        into.mark_opaque(found.why)


#: ``pwsh``/``powershell`` options that take an operand.
_PS_VALUED = ("executionpolicy", "ep", "ex", "windowstyle", "w", "workingdirectory", "wd",
              "outputformat", "o", "of", "inputformat", "if", "configurationname", "config",
              "custompipename", "settingsfile", "settings", "version", "v", "psconsolefile",
              "encodedarguments", "ea", "encodeda")


def _nested_powershell(flat: List[_Value], ctx: _Ctx, piped: bool) -> None:
    """``pwsh -Command '…'``, ``-EncodedCommand``, ``-File``, stdin."""
    result = ctx.result
    saved = ctx.cwd
    try:
        _powershell_args(flat, ctx, piped)
    finally:
        ctx.cwd = saved


def _powershell_args(flat: List[_Value], ctx: _Ctx, piped: bool) -> None:
    result = ctx.result
    index = 0
    while index < len(flat):
        value = flat[index]
        text = value.text
        low = text.lower()
        if value.dynamic and not low.startswith("-"):
            result.mark_opaque("PowerShell code from a variable")
            return
        if low.startswith(("-", "/")) and len(low) > 1:
            option, colon, attached = low.lstrip("-/").partition(":")
            if option == "":
                break
            operand = text.split(":", 1)[1] if colon else (
                flat[index + 1].text if index + 1 < len(flat) else None)
            if option in ("e", "ec") or (len(option) >= 2 and "encodedcommand".startswith(option)):
                if operand is None:
                    result.mark_opaque("encoded command")
                    return
                _encoded(operand, ctx)
                return
            if option in ("wd",) or (len(option) >= 2 and "workingdirectory".startswith(option)):
                if operand is not None:
                    new = _resolve(operand, flat[index + 1].dynamic if not colon else False,
                                   ctx.cwd)
                    ctx.cwd = new if isinstance(new, str) else None
                index += 1 if colon else 2
                continue
            if option == "c" or (len(option) >= 2 and "command".startswith(option)):
                code = flat[index + 1:]
                if not code or (len(code) == 1 and code[0].text == "-"):
                    result.mark_opaque("PowerShell script on stdin")
                    return
                if any(v.dynamic or v.splat for v in code):
                    result.mark_opaque("PowerShell code from a variable")
                    return
                _read_string(" ".join(v.text for v in code), ctx)
                return
            if option == "f" or (len(option) >= 2 and "file".startswith(option)):
                if operand == "-":
                    result.mark_opaque("PowerShell script on stdin")
                ctx.ran_script = True
                return  # a script file: a program invoked by name
            if option in _PS_VALUED:
                index += 2
                continue
            index += 1
            continue
        if low == "-":
            result.mark_opaque("PowerShell script on stdin")
            return
        if low.endswith(".ps1"):
            ctx.ran_script = True
            return
        _read_string(" ".join(v.text for v in flat[index:]), ctx)
        return
    if piped:
        result.mark_opaque("PowerShell script on stdin")


def _encoded(blob: str, ctx: _Ctx) -> None:
    ctx.result.mark_opaque("encoded command")
    try:
        code = _b64(blob)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return
    _read_string(code, ctx)


def _b64(blob: str) -> str:
    """Decode an ``-EncodedCommand`` operand; .NET ignores whitespace in it."""
    return base64.b64decode(re.sub(r"\s+", "", blob), validate=True).decode("utf-16-le")


# --------------------------------------------------------------------------
# public surface
# --------------------------------------------------------------------------
#: PowerShell reads typographic quotes and dashes as their ASCII forms.
_TYPOGRAPHIC = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u2013": "-", "\u2014": "-", "\u2015": "-",
})


def _normal(text: str) -> str:
    return text.translate(_TYPOGRAPHIC)


def read(command: str, cwd: Optional[str]) -> PSWriteTargets:
    """Statically list what PowerShell *command* would write, resolved
    against *cwd* (``None`` = unknown; every relative target is then opaque)."""
    result = PSWriteTargets()
    base = posixpath.normpath(write._canonical(cwd)) if cwd else None
    if base:
        result.cwds.append(base)
    ctx = _Ctx(result, base)
    try:
        _read_text(_normal(command), ctx)
    except (RecursionError, IndexError, ValueError, KeyError, TypeError) as err:
        result.mark_opaque("unreadable command (%s)" % type(err).__name__)
    if ctx.ran_script and result.targets:
        result.mark_opaque("a script runs in the command that writes")
    _dot_globs(result)
    _short_names(result)
    return result


def _dot_globs(result: PSWriteTargets) -> None:
    """PowerShell wildcards match names that start with a dot (``*`` matches
    ``.gatekit`` and ``.gatebound``), which the shell-glob checks do not
    assume: add each target or removed path once more per state directory
    name, with such segments spelled as it (ADR-0029)."""
    from fnmatch import fnmatchcase
    for paths in (result.targets, result.removed):
        for path in list(paths):
            segs = path.split("/")
            if not any(c in seg for seg in segs for c in "*?["):
                continue
            for state in _names.state_dirnames():
                variant = [seg if not any(c in seg for c in "*?[")
                           or not fnmatchcase(state, seg.lower()) else state
                           for seg in segs]
                joined = "/".join(variant)
                if joined != path and joined not in paths:
                    paths.append(joined)


def _short_names(result: PSWriteTargets) -> None:
    """Windows 8.3 short names reach the state directory too (``GATEKI~1``,
    ``GATEBO~1``): add each target or removed path once more with them
    spelled out."""
    for paths in (result.targets, result.removed):
        for path in list(paths):
            joined = _SHORT_STATE_RE.sub(_spell_short, path)
            if joined != path and joined not in paths:
                paths.append(joined)


_ENCODED_RE = re.compile(
    r"(?i)(?:^|\s)[-/](?:e|ec|en\w*)(?::|\s+)(?:'([^']*)'|\"([^\"]*)\"|([A-Za-z0-9+/=]+))")


def _decoded_texts(command: str) -> List[str]:
    out = []
    for match in _ENCODED_RE.finditer(command):
        try:
            out.append(_b64(match.group(1) or match.group(2) or match.group(3) or ""))
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
    return out


def _flatten(text: str) -> str:
    """*text* with backticks, quotes, commas and brackets removed."""
    return re.sub(r"[`]", "", re.sub(r"['\",()\[\]{}]", " ", text))


#: The fallback reading: a launcher or module of any name (ADR-0029).
_GATEKIT_RE = re.compile(r"(?i)(?:^|[\s\\/=:])(?:-m)?%s(?:\.py|\.cli|\.__main__)?(?=\s)"
                         % _names.names_pattern())
_APPROVE_OPERANDS = ("--root", "--note", "--by")


def invokes_gatekit_approve(command: str) -> bool:
    """True when *command* runs gatekit's ``approve`` (not ``check``/``list``)
    anywhere in it — any statement, a nested string, a decoded
    ``-EncodedCommand`` (ADR-0023, ADR-0028 decision 7)."""
    command = _normal(command)
    texts = [command]
    frontier = [command]
    for _ in range(MAX_STRING_DEPTH):
        decoded = [d for t in frontier for d in _decoded_texts(t)]
        if not decoded:
            break
        texts.extend(decoded)
        frontier = decoded
    for text in texts:
        if _approve_in_code(text, 0):
            return True
        flat = _flatten(text)
        for match in _GATEKIT_RE.finditer(flat):
            tail = re.split(r"[;|&\n]", flat[match.end():match.end() + 400], maxsplit=1)[0]
            if _approves(tail.split()):
                return True
    return False


def _approve_in_code(text: str, depth: int) -> bool:
    """The lexed reading: quotes, comments and continuations resolved as
    PowerShell does; a computed word where the subcommand goes counts."""
    if depth > MAX_STRING_DEPTH:
        return False
    nested: List[str] = []
    try:
        toks = _lex(text, nested)
    except (_Unlexable, RecursionError, IndexError):
        return False
    element: List[_Tok] = []
    for tok in toks + [_Tok("sep", ";")]:
        if tok.kind in ("sep", "pipe"):
            if _element_approves(element):
                return True
            element = []
            continue
        if tok.kind in ("group", "block") and _approve_in_code(tok.value, depth + 1):
            return True
        if tok.kind == "word" and " " in tok.value and "approv" in tok.value.lower() \
                and _approve_in_code(tok.value, depth + 1):
            return True
        if tok.kind in ("word", "group", "block"):
            element.append(tok)
    return any(_approve_in_code(code, depth + 1) for code in nested)


def _element_approves(toks: List[_Tok]) -> bool:
    computed_before = False
    for index, tok in enumerate(toks):
        if tok.kind != "word" or tok.dynamic:
            computed_before = computed_before or index > 0
            continue
        # Every name, as the Bash gate reads it (ADR-0029); a computed word
        # before a module counts as ``-m``.
        prev = None
        if index:
            before = toks[index - 1]
            prev = "$" if before.kind != "word" or before.dynamic else before.value
        kind = _names.entry_kind(tok.value, prev)
        if kind == "approval" and _approve_rest(toks, index + 1, seen=True):
            return True
        if kind == "cli" and _approve_rest(toks, index + 1, seen=False):
            return True
        base = re.split(r"[\\/]", tok.value.lower())[-1]
        if base == "approve" and computed_before and _approve_rest(toks, index, seen=False):
            return True
    return False


def _approve_rest(toks: List[_Tok], index: int, seen: bool) -> bool:
    """From *index*: the gatekit arguments run ``approve`` (not check/list);
    stops at the first word that decides it."""
    while index < len(toks):
        tok = toks[index]
        computed = tok.kind != "word" or tok.dynamic or tok.splat
        word = tok.value.lower()
        if not computed and word in _APPROVE_OPERANDS:
            index += 2
            continue
        if not computed and word.startswith("-"):
            index += 1
            continue
        if computed:
            return True  # a computed subcommand or action: never round it down
        if not seen:
            if word != "approve":
                return False
            seen = True
            index += 1
            continue
        return word not in ("check", "list")
    return seen


def _approves(words: List[str]) -> bool:
    index = 0
    seen_approve = False
    while index < len(words):
        word = words[index].lower()
        if word in _APPROVE_OPERANDS:
            index += 2
            continue
        if word.startswith("-"):
            index += 1
            continue
        if not seen_approve:
            if word != "approve":
                return False
            seen_approve = True
            index += 1
            continue
        return word not in ("check", "list")
    return seen_approve


#: 8.3 short names of every state directory (``GATEKI~1``, ``GATEBO~1``).
_SHORT_STATE_RE = re.compile(
    r"(?i)(%s)~\d" % "|".join(re.escape(stem) for stem, _ in _names.state_short_names()))


def _spell_short(match: "re.Match[str]") -> str:
    stem = match.group(1).lower()
    for short, dirname in _names.state_short_names():
        if short == stem:
            return "/" + dirname
    return match.group(0)  # pragma: no cover - the pattern holds only known stems


def mention_text(command: str, found: PSWriteTargets) -> str:
    """The text the protected-state mention check reads for an opaque command:
    the command and every code string found inside it, each also with
    backticks, quotes and ``+`` concatenation removed and 8.3 short names of
    the state directories (``GATEKI~1``, ``GATEBO~1``) spelled out."""
    command = _normal(command)
    texts = [command] + list(found.texts) + _decoded_texts(command)
    out: List[str] = []
    for text in texts:
        out.append(text)
        joined = re.sub(r"\s*\+\s*", "", re.sub(r"['\"`]", "", text))
        out.append(joined)
        out.append(_flatten(text))
    return _SHORT_STATE_RE.sub(_spell_short, "\n".join(out))

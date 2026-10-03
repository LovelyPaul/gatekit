"""Output language detection.

gatekit is open source and must never default to Korean. This module answers a
single question — "which language did the user write in?" — from the text of
their prompt, and the answer is stored once per session in the ledger. Every
user-facing string a command emits follows it.

Detection counts letters only: Hangul syllables and jamo against Latin letters.
Digits and punctuation are ignored, and so are whitespace-delimited tokens that
are paths or code identifiers (they contain ``/``, ``.``, ``_``, ``\\`` or a
backtick inside them), so ``src/auth/token.ts 를 고쳐줘`` is Korean even though
most of its characters are ASCII. A session observed in Codex switched to
English on ``src/hello.ts 만들어줘`` before this rule existed.
"""
from __future__ import annotations

import itertools
import re
import sys
import unicodedata
from typing import List, Optional

KO = "ko"
EN = "en"

#: Hangul share of all counted letters at or above which the text is Korean.
HANGUL_THRESHOLD = 0.30

# Unicode blocks holding Hangul: syllables, compatibility jamo (ㅇㅋ), the
# original jamo block, and the two extended-jamo blocks.
_HANGUL_RANGES = (
    (0xAC00, 0xD7A3),  # Hangul syllables
    (0x1100, 0x11FF),  # Hangul jamo
    (0x3130, 0x318F),  # Hangul compatibility jamo
    (0xA960, 0xA97F),  # Hangul jamo extended-A
    (0xD7B0, 0xD7FF),  # Hangul jamo extended-B
)


def _is_hangul(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _HANGUL_RANGES)


#: Characters that mark a whitespace-delimited token as a path or a code
#: identifier once its surrounding punctuation is stripped: ``src/hello.ts``,
#: ``user_id``, ``foo.bar``, ```code```. Such tokens are named, not written,
#: and must not drag a short Korean request to English.
_IDENTIFIER_CHARS = set("/._\\`")
_EDGE_PUNCT = "\"'()[]{}<>,;:!?…"


def prose_only(text: str) -> str:
    """*text* with path and identifier tokens removed."""
    kept = []
    for token in str(text).split():
        core = token.strip(_EDGE_PUNCT)
        if not core:
            continue
        if any(ch in _IDENTIFIER_CHARS for ch in core.rstrip(".")):
            continue
        kept.append(core)
    return " ".join(kept)


def _letter_counts(text: Optional[str]) -> tuple:
    """Return ``(hangul, letters)`` for the prose part of *text*."""
    if not text:
        return (0, 0)

    hangul = 0
    letters = 0
    for char in prose_only(text):
        if not char.isalpha():
            continue
        # Guard against scripts we do not classify (Han, Cyrillic, ...) being
        # counted as "not Korean" and skewing the ratio: only Hangul and Latin
        # participate in the denominator.
        if _is_hangul(char):
            hangul += 1
            letters += 1
        elif "LATIN" in unicodedata.name(char, ""):
            letters += 1
    return (hangul, letters)


def carries_signal(text: Optional[str]) -> bool:
    """Whether *text* says anything about which language the user is writing in.

    `"1"`, `"2."`, `"ok 3"` and a bare path carry none: they are the same
    keystrokes in either language. Answering a numbered list that way is the
    *normal* path under Codex, which has no `AskUserQuestion` and asks its
    options as plain-chat numbers — so treating those replies as an English
    signal silently switched a Korean session to English mid-interview
    (observed on a real Codex run, 2026-09-27).

    A caller that refreshes a stored language must ask this first; `detect`
    alone cannot tell "no evidence" from "evidence of English", because it
    has to return one of the two either way.
    """
    return _letter_counts(text)[1] > 0


def detect(text: Optional[str]) -> str:
    """Return ``"ko"`` or ``"en"`` for *text*.

    Korean when Hangul letters are at least 30% of all letters. Empty text, or
    text with no letters at all, is English — callers that must not overwrite
    a known language with that fallback check :func:`carries_signal` first.
    """
    hangul, letters = _letter_counts(text)
    if letters == 0:
        return EN
    return KO if (hangul / letters) >= HANGUL_THRESHOLD else EN


#: Spec files whose language stands in for the user's while no prompt in the
#: session has said anything (ADR-0026), in order of preference.
SPEC_LANG_FILES = ("01-prd.md", "00-discovery.md")
#: Only the head of the file is read: the title and the first sections are
#: the user's words; later sections may quote code or English sources. The
#: head is counted in prose lines (headings, paragraphs, list items), not raw
#: lines: YAML frontmatter, fenced code, table rows and inline code are often
#: English in a Korean spec and say nothing about the user's language.
SPEC_LANG_LINES = 40
#: Raw lines scanned at most while collecting the head, so a file that is
#: nearly all code or tables is never read to the end.
SPEC_LANG_SCAN_LINES = 1000
#: A leading `---` opens YAML frontmatter only when a closing `---` (or
#: `...`) follows within this many lines; a UTF-8 BOM before it is ignored.
SPEC_FRONTMATTER_LINES = 60
_INLINE_CODE_RE = re.compile(r"`+[^`\n]*`+")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def prose_head(lines, limit: int = SPEC_LANG_LINES) -> str:
    """The first *limit* prose lines of a Markdown file's *lines*.

    Skips a leading YAML frontmatter block (closed within
    :data:`SPEC_FRONTMATTER_LINES` lines; a BOM before it is ignored), fenced
    code blocks, table rows (lines starting with ``|``) and blank lines, and
    drops inline code spans from what is kept.
    """
    lines = iter(lines)
    head = list(itertools.islice(lines, SPEC_FRONTMATTER_LINES + 1))
    if head and head[0].startswith("\ufeff"):
        head[0] = head[0][1:]
    start = 0
    if head and head[0].strip() == "---":
        # Frontmatter only when it closes in time; otherwise the `---` is a
        # thematic break and the lines after it are read as usual.
        for index in range(1, len(head)):
            if head[index].strip() in ("---", "..."):
                start = index + 1
                break
    kept = []
    fence = None
    for line in itertools.chain(head[start:], lines):
        stripped = line.strip()
        match = _FENCE_RE.match(line)
        if fence is not None:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
                fence = None
            continue
        if match:
            fence = match.group(1)
            continue
        if not stripped or stripped.startswith("|"):
            continue
        kept.append(_INLINE_CODE_RE.sub(" ", line.rstrip("\n")))
        if len(kept) >= limit:
            break
    return "\n".join(kept)


def from_spec(root) -> Optional[str]:
    """``"ko"``/``"en"`` from the project's spec, else ``None``.

    The first of :data:`SPEC_LANG_FILES` under ``spec/`` whose first
    :data:`SPEC_LANG_LINES` prose lines (:func:`prose_head`) carry a signal
    decides. A missing or unreadable file, or one with no letters in its
    prose, gives no answer — never a default.
    """
    from gatekit import paths

    for name in SPEC_LANG_FILES:
        try:
            with open(paths.spec_dir(root) / name, encoding="utf-8",
                      errors="replace") as handle:
                head = prose_head(
                    line for _, line in zip(range(SPEC_LANG_SCAN_LINES), handle))
        except (OSError, ValueError):
            continue
        if carries_signal(head):
            return detect(head)
    return None


def _latest_ledger_lang(root) -> Optional[str]:
    """``output_lang`` of the most recently updated session ledger, else
    ``None``. Used only by ``lang --spec`` when the spec gives no answer: a
    command does not know its session id, and the language is the one thing
    read this way — never scopes (``ledger.py`` resolves those by id only)."""
    import json

    from gatekit import paths

    try:
        ledgers = [p for p in paths.runs_dir(root).glob("*.json")
                   if p.name != "contract-last.json"]
        if not ledgers:
            return None
        latest = max(ledgers, key=lambda p: p.stat().st_mtime)
        with latest.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    value = data.get("output_lang") if isinstance(data, dict) else None
    return value if value in (KO, EN) else None


def spec_lang(root) -> str:
    """What ``lang --spec`` prints: :func:`from_spec`, else the latest
    session ledger's ``output_lang``, else ``en``."""
    try:
        return from_spec(root) or _latest_ledger_lang(root) or EN
    except Exception:  # noqa: BLE001 — a language answer must never crash a command
        return EN


def run(argv: List[str]) -> int:
    """``python3 -m gatekit lang <text...>`` — print the detected language.

    ``lang --spec [--root PATH]`` prints :func:`spec_lang` for the project
    (root found from the working directory by default) instead."""
    if argv[:1] == ["--spec"]:
        from gatekit import paths

        rest = argv[1:]
        root_arg = None
        if len(rest) >= 2 and rest[0] == "--root":
            root_arg = rest[1]
        print(spec_lang(paths.project_root(root_arg)))
        return 0
    text = " ".join(argv)
    print(detect(text))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))

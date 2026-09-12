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


def detect(text: Optional[str]) -> str:
    """Return ``"ko"`` or ``"en"`` for *text*.

    Korean when Hangul letters are at least 30% of all letters. Empty text, or
    text with no letters at all, is English.
    """
    if not text:
        return EN

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

    if letters == 0:
        return EN
    return KO if (hangul / letters) >= HANGUL_THRESHOLD else EN


def run(argv: List[str]) -> int:
    """``python3 -m gatekit lang <text...>`` — print the detected language."""
    text = " ".join(argv)
    print(detect(text))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run(sys.argv[1:]))

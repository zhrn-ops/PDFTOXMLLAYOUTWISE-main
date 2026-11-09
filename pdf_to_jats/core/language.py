"""Infer a coarse language code for a title from the script it is printed in."""

from __future__ import annotations

import re


_ARABIC_SCRIPT = re.compile(
    r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]"
)
_PERSIAN_LETTERS = re.compile(r"[پچژگکی]")
_ARABIC_LETTERS = re.compile(r"[ةىكي]")
_LATIN = re.compile(r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff]")
_CYRILLIC = re.compile(r"[\u0400-\u04ff]")
_KANA = re.compile(r"[\u3040-\u30ff]")
_HANGUL = re.compile(r"[\uac00-\ud7af]")
_HAN = re.compile(r"[\u4e00-\u9fff]")


def detect_language_code(text: str, default: str = "UND") -> str:
    """Return a best-effort language code for *text*.

    The title-capture screen has no language field, so this distinguishes the
    scripts the application can recognize reliably.  Persian is separated from
    generic Arabic script only when a Persian-specific letter is present; an
    ambiguous Arabic-script title stays ``UND`` until the user chooses a code in
    the correction workspace.  Latin script defaults to English, matching the
    generator's existing default.
    """

    value = str(text or "")
    if not value.strip():
        return default

    # Count scripts in first-seen order so a tie follows the script that starts
    # the title instead of a fixed preference.
    counts: dict[str, int] = {}
    for char in value:
        if _ARABIC_SCRIPT.match(char):
            key = "arabic"
        elif _LATIN.match(char):
            key = "latin"
        elif _CYRILLIC.match(char):
            key = "cyrillic"
        elif _KANA.match(char):
            key = "kana"
        elif _HANGUL.match(char):
            key = "hangul"
        elif _HAN.match(char):
            key = "han"
        else:
            continue
        counts[key] = counts.get(key, 0) + 1

    if not counts:
        return default
    script = max(counts, key=lambda key: counts[key])

    if script == "arabic":
        if _PERSIAN_LETTERS.search(value):
            return "FAS"
        if _ARABIC_LETTERS.search(value):
            return "ARA"
        return default
    return {
        "latin": "ENG",
        "cyrillic": "RUS",
        "kana": "JPN",
        "hangul": "KOR",
        "han": "ZHO",
    }.get(script, default)

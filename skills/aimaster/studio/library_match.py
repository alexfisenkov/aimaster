"""`library match`: which library entries an idea text names.

Spec 2026-09-23 §3: an entry matches when its `label` or one of its
`aliases` occurs in the text, ignoring case and Russian endings by a simple
stem rule. A word longer than 4 letters also stands for itself minus its
last one or two letters, never shorter than 4 letters: «Артёмом» and
«Артём» share «артем», «Александром» and «Александр» share «александр»,
while «Артист» does not reach «Артём» (a 3-letter stem is never used).
Every word of a name must be present. A voice entry also matches when the
character it belongs to (`voice_of`) matched.
"""

from __future__ import annotations

import re

from .library import read_entries

_WORD = re.compile(r"[0-9a-zа-я]+")
_NAME_SPLIT = re.compile(r"\s+[—–-]\s+")
_MIN_STEM = 4


def _words(text: str) -> list[str]:
    return _WORD.findall(text.casefold().replace("ё", "е"))


def stems(word: str) -> frozenset[str]:
    forms = {word}
    for cut in (1, 2):
        if len(word) > _MIN_STEM and len(word) - cut >= _MIN_STEM:
            forms.add(word[:-cut])
    return frozenset(forms)


def name_part(label: str) -> str:
    """«Артём — второй персонаж» → «Артём»: the part before a spaced dash."""

    return _NAME_SPLIT.split(label.strip(), maxsplit=1)[0].strip()


def _name_matches(name: str, text_stems: list[frozenset[str]]) -> bool:
    words = _words(name_part(name))
    if not words:
        return False
    return all(any(stems(word) & candidate for candidate in text_stems) for word in words)


def match(workspace, text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    text_stems = [stems(word) for word in _words(text)]
    entries = read_entries(workspace)
    matched: dict[str, dict] = {}
    for entry in entries:
        for name in (entry["label"], *entry["aliases"]):
            if _name_matches(name, text_stems):
                matched[entry["library_id"]] = {**entry, "matched_name": name}
                break
    for entry in entries:
        owner = entry.get("voice_of")
        if entry["kind"] == "voice" and owner in matched and entry["library_id"] not in matched:
            matched[entry["library_id"]] = {**entry, "matched_name": matched[owner]["matched_name"],
                                            "matched_via": "voice_of"}
    ordered = [matched[entry["library_id"]] for entry in entries if entry["library_id"] in matched]
    return {"text": text, "count": len(ordered), "matches": ordered}

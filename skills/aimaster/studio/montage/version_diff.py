"""Что изменилось с версии: модель её снимка и строки diff — общее для сборки
(`render.py`) и `service.diff`. Потерянный или повреждённый снимок (state
версию знает, а на диске модели нет или она не читается) не блокирует ни
сборку, ни diff: сравниваем «ни с чем» и прямо говорим, что случилось."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Mapping

from . import MontageError
from .index_io import read_index
from .model import Model
from .model_diff import diff_models
from .montage_format import clips_count, fmt_len
from .paths import VERSION_ID
from .versions import read_version_model

MISSING, CORRUPT = "missing", "corrupt"
INLINE_SCRIPT_CHANGE = "изменена анимация или положение элементов в монтажном столе"


class _InlineScripts(HTMLParser):
    """Only authored inline JS, not Studio's HTML IDs or external script tags."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sources: list[str] = []
        self.active = False

    def handle_starttag(self, tag, attrs):
        if tag == "script" and not any(name == "src" for name, _value in attrs):
            self.sources.append("")
            self.active = True

    def handle_data(self, data):
        if self.active:
            self.sources[-1] += data

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False


def _inline_sources(text: str) -> tuple[str, ...]:
    parser = _InlineScripts()
    parser.feed(text)
    parser.close()
    return tuple(source.strip() for source in parser.sources)


def inline_script_changed(paths, version_id: str | None, *, current_text: str | None = None) -> bool:
    """Compare working animation source with the immutable version HTML.

    Studio may normalize doctype, meta tags and data-hf-id on open. Those are
    outside inline scripts and must not make an unchanged legacy version dirty.
    The version snapshot is already on disk; no model/schema migration or JS
    execution is needed. A lost snapshot cannot prove that the MP4 is current.
    """

    if not version_id:
        return False
    try:
        previous = read_index(paths.version_dir(version_id) / "index.html")
        current = current_text if current_text is not None else read_index(paths.index)
    except (MontageError, ValueError):
        return True
    return _inline_sources(previous) != _inline_sources(current)


def include_inline_script_change(changes: list[str], changed: bool) -> list[str]:
    """Add a truthful fallback when model-level diff omits a Studio-only edit."""

    return changes if changes or not changed else [INLINE_SCRIPT_CHANGE]


def base_model(paths, version_id: str | None) -> tuple[Model | None, str | None]:
    """(модель снимка версии, беда со снимком: None | MISSING | CORRUPT)."""

    if version_id is None:
        return None, None
    if not VERSION_ID.fullmatch(str(version_id)):
        return None, CORRUPT
    if not (paths.version_dir(version_id) / "model.json").is_file():
        return None, MISSING
    try:
        return read_version_model(paths, version_id), None
    except MontageError:
        return None, CORRUPT


def changes_since(version_id: str | None, old: Model | None, problem: str | None, model: Model,
                  names: Mapping[str, str]) -> list[str]:
    if problem is None:
        return diff_models(old, model, names=names)
    what = (f"снимка прежней версии {version_id} нет на диске" if problem == MISSING
            else f"снимок прежней версии {version_id} повреждён")
    return [f"{what} — изменения сравнить не с чем; "
            f"в монтаже {clips_count(len(model.clips))}, {fmt_len(model.duration)}"]

"""«Скачать» (`GET /assets/<id>?download=1`): имя файла и Content-Disposition.

Ролик монтажа (`media/<проект>/montage/vNNN.mp4`) сохраняется как
«<название проекта>-vNNN.mp4», любой другой файл — под своим именем; длинное
имя укорачивается, но расширение остаётся (без него система не узнает, чем
открыть файл). Имя
в заголовке дважды: `filename*` (UTF-8, RFC 6266/8187) — для кириллицы,
`filename` — только латиница, цифры и «._-» — для старых программ. Знаки,
запрещённые в именах файлов Windows и macOS, и переводы строк выбрасываются:
заголовок не разорвать, файл сохранится на любой системе."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Callable
from urllib.parse import quote

_MONTAGE = re.compile(r"media/([^/]+)/montage/(v\d{3,})\.mp4")
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')
_NOT_LATIN = re.compile(r"[^A-Za-z0-9._-]+")
_SUFFIX = re.compile(r"\.[A-Za-z0-9]{1,8}")
MAX_STEM = 80


def _clean(text: str) -> str:
    return " ".join(_FORBIDDEN.sub(" ", text).split())[:MAX_STEM].strip(" .")


def _latin(text: str) -> str:
    return _NOT_LATIN.sub("-", text).strip("-.")


def download_names(relative_path: str, title_of: Callable[[str], str | None]) -> tuple[str, str]:
    """(имя для сохранения, запасное имя латиницей)."""

    match = _MONTAGE.fullmatch(relative_path)
    if match is None:
        original = PurePosixPath(relative_path)
        suffix = original.suffix if _SUFFIX.fullmatch(original.suffix) else ""
        stem = original.name[: len(original.name) - len(suffix)]
        name = (_clean(stem) or "file") + suffix
        return name, (_latin(_clean(stem)) or "file") + suffix
    project_id, version = match.groups()
    title = _clean(title_of(project_id) or "") or _clean(project_id) or "montage"
    return f"{title}-{version}.mp4", f"{_latin(project_id) or 'montage'}-{version}.mp4"


def content_disposition(name: str, fallback: str) -> str:
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"

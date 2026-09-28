"""Медиа композиции: жёсткая ссылка на файл из <workspace>/media в current/assets.

Файлы из <workspace>/media попадают в current/assets жёсткой ссылкой (тот же
файл, место на диске не тратится), а если ссылка невозможна (другой диск,
файловая система без ссылок) — копией. Симлинки не используются: на Windows
они требуют прав. Имя в assets — id ассета: уникально и не меняется.

Проверка ссылок композиции (внешние/выходящие за пределы current/) — в
`composition_refs.py`, отдельно: это про содержимое HTML, а не про то, как
файл попадает на диск.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable

from . import MontageError
from .index_io import new_file_mode
from .replace_target import clear_link, replace_via_temp

ASSETS_DIR = "assets"


def asset_filename(asset_id: str, source: Path) -> str:
    return f"{asset_id}{Path(source).suffix.lower()}"


def link_or_copy(source: Path, target: Path) -> str:
    """'link' | 'copy' | 'exists'. Другой файл с тем же именем — отказ."""

    source, target = Path(source), Path(target)
    if not source.is_file():
        raise MontageError(f"источника для монтажа нет: {source.name}")
    try:  # симлинк на месте файла — долой сам, не глядя, куда он ведёт (replace_target)
        existing = clear_link(target)
        same = existing is not None and (os.path.samefile(source, target)
                                         or existing.st_size == source.stat().st_size)
    except OSError as error:
        raise MontageError(f"не удалось проверить {target.name} в assets") from error
    if same:
        return "exists"
    if existing is not None or os.path.lexists(target):
        raise MontageError(f"в assets уже лежит другой файл {target.name}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise MontageError(f"не удалось создать папку {target.parent.name} монтажа") from error
    try:
        os.link(source, target)
        return "link"
    except OSError:
        pass
    try:
        copy_via_temp(source, target)
    except OSError as error:
        raise MontageError(f"не удалось скопировать {source.name} в assets") from error
    return "copy"


def copy_via_temp(source: Path, target: Path, *, keep_mode: bool = True) -> None:
    """Копия `source` на место `target` через `replace_via_temp`.
    `keep_mode=False` — содержимое без прав источника (файлы пакета навыка
    бывают только для чтения): права 0644 − umask."""

    copy = shutil.copy2 if keep_mode else shutil.copyfile
    replace_via_temp(target, lambda temporary: copy(source, temporary),
                     mode=None if keep_mode else new_file_mode(), suffix=".part")


def sync_media(items: Iterable[tuple[str, Path]], assets_dir: Path) -> dict[str, dict]:
    """{asset_id: {"src": "assets/<файл>", "method": link|copy|exists}}."""

    result: dict[str, dict] = {}
    for asset_id, source in items:
        if asset_id in result:
            continue
        name = asset_filename(asset_id, source)
        method = link_or_copy(Path(source), Path(assets_dir) / name)
        result[asset_id] = {"src": f"{ASSETS_DIR}/{name}", "method": method}
    return result

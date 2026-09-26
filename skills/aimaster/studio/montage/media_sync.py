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
import tempfile
from pathlib import Path
from typing import Iterable

from ..platform_compat import replace_file
from . import MontageError
from .index_io import new_file_mode

ASSETS_DIR = "assets"


def asset_filename(asset_id: str, source: Path) -> str:
    return f"{asset_id}{Path(source).suffix.lower()}"


def link_or_copy(source: Path, target: Path) -> str:
    """'link' | 'copy' | 'exists'. Другой файл с тем же именем — отказ."""

    source, target = Path(source), Path(target)
    if not source.is_file():
        raise MontageError(f"источника для монтажа нет: {source.name}")
    if target.exists():
        try:
            same = (os.path.samefile(source, target)
                    or target.stat().st_size == source.stat().st_size)
        except OSError as error:
            raise MontageError(f"не удалось проверить {target.name} в assets") from error
        if same:
            return "exists"
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
    """Копия через временный файл mkstemp рядом с целью (не фиксированное
    «.имя.part»: его мог занять параллельный вызов или остаток прошлого) и
    атомарную замену; сбой — временный файл убран, OSError наружу.
    `keep_mode=False` — содержимое без прав источника (файлы пакета навыка
    бывают только для чтения — копия и её замена не должны от этого ломаться,
    на Windows замена файла «только чтение» отказывает): права 0644 − umask."""

    descriptor, name = tempfile.mkstemp(dir=Path(target).parent, prefix=f".{Path(target).name}.",
                                        suffix=".part")
    os.close(descriptor)
    temporary = Path(name)
    try:
        if keep_mode:
            shutil.copy2(source, temporary)
        else:
            shutil.copyfile(source, temporary)
            os.chmod(temporary, new_file_mode())
            if Path(target).exists():
                os.chmod(target, new_file_mode())  # прежняя копия «только чтение» — снять
        replace_file(temporary, target)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass  # уборка — best effort, не подменяет исходную ошибку
        raise


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

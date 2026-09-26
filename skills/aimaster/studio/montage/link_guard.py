"""Папка монтажа без ссылок наружу и без своего ffmpeg — до любой работы с ней.

Проект могли собрать чужими руками. Ссылка внутри montage/ (симлинк, на Windows
ещё и junction) уводит чтение и запись монтажа в чужие места: current/index.html
— на чужой файл, который потом уйдёт в .undo и версии; .cache или assets — в
чужую папку, куда лягут наши файлы. Поэтому `open_context` (все команды, кроме
закрытия стола — своё Studio остановить нужно всегда) сперва обходит montage/
через os.scandir, не заходя по ссылкам, и отказывает, если нашёл хоть одну.
Прочие точки повторной обработки Windows (заглушки облачных дисков) — обычные
файлы, не ссылки. Выше montage/ и media/<проект>/montage не смотрим: там свои
законные ссылки (рабочие папки рендера HyperFrames).

HyperFrames ищет ffmpeg ещё и в папке запуска — current/ (на Windows до PATH,
и в current/.hyperframes/bin): программа с таким именем там — чужая, отказ.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from ..platform_compat import IS_WINDOWS
from . import MontageError

# IO_REPARSE_TAG_SYMLINK и IO_REPARSE_TAG_MOUNT_POINT (junction): имена в модуле
# stat есть только в сборках для Windows, os.path.isjunction — только с 3.12.
LINK_TAGS = (0xA000000C, 0xA0000003)
PROGRAMS = ("ffmpeg", "ffprobe")
SHOWN = 3


def _is_link(info) -> bool:
    if stat.S_ISLNK(info.st_mode):
        return True
    return IS_WINDOWS and getattr(info, "st_reparse_tag", 0) in LINK_TAGS


def _unreadable(folder: Path, root: Path) -> MontageError:
    return MontageError(f"не удалось проверить папку монтажа {folder.relative_to(root.parent).as_posix()}")


def _links(folder: Path, root: Path, found: list[str]) -> None:
    """Ссылки под `folder` (пути от папки проекта); по ссылкам не заходит. Что
    убрали параллельно (сборка сносит свою staging) — пропускается."""

    try:
        entries = list(os.scandir(folder))
    except (FileNotFoundError, NotADirectoryError):
        return
    except OSError as error:
        raise _unreadable(folder, root) from error
    for entry in entries:
        try:
            info = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise _unreadable(folder, root) from error
        if entry.is_symlink() or _is_link(info):
            found.append((folder / entry.name).relative_to(root.parent).as_posix())
        elif stat.S_ISDIR(info.st_mode):
            _links(folder / entry.name, root, found)


def _programs(current: Path) -> list[str]:
    try:
        names = [entry.name for entry in os.scandir(current)]
    except OSError:
        names = []
    found = [f"montage/current/{name}" for name in sorted(names)
             if name.casefold().split(".")[0] in PROGRAMS]
    if os.path.lexists(current / ".hyperframes" / "bin"):
        found.append("montage/current/.hyperframes/bin")
    return found


def check_montage_folder(root: Path) -> None:
    """`root` — папка montage проекта; её нет — проверять нечего."""

    root = Path(root)
    try:
        info = os.lstat(root)
    except FileNotFoundError:
        return
    except OSError as error:
        raise MontageError("не удалось проверить папку montage проекта") from error
    if _is_link(info):
        raise MontageError("папка montage проекта — ссылка на другое место; монтаж не трогаю")
    if not stat.S_ISDIR(info.st_mode):
        return  # не папка — черновик сам откажет, создавая её
    found: list[str] = []
    _links(root, root, found)
    if found:
        more = f" и ещё {len(found) - SHOWN}" if len(found) > SHOWN else ""
        raise MontageError("в папке монтажа есть ссылки на другие места: "
                           f"{', '.join(found[:SHOWN])}{more}; монтаж не трогаю")
    programs = _programs(root / "current")
    if programs:
        raise MontageError(f"в папке монтажа лежит {', '.join(programs[:SHOWN])} — HyperFrames "
                           "взял бы оттуда ffmpeg вместо системного; монтаж не трогаю")

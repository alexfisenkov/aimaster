"""Место под запись файла монтажа — без перехода по симлинку.

Папку проекта могли собрать чужими руками: на месте файла в montage/ — ссылка на
файл вне проекта (закрытый ключ, чужой документ). stat, chmod, чтение и запись
по такой ссылке трогают её цель: chmod сделал бы ключ читаемым всем, запись
затёрла бы чужой файл, а права цели перешли бы на наш. Поэтому цель смотрим
только через lstat: ссылку (и любую запись, кроме обычного файла и папки)
удаляем саму — не то, на что она указывает; папку не трогаем (замена файлом на
ней откажет сама); обычный файл «только чтение» делаем записываемым только на
Windows — там его замена отказывает, а на POSIX rename права цели не смотрит.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from ..platform_compat import IS_WINDOWS, open_nofollow


def regular_stat(path) -> os.stat_result | None:
    """lstat, если на месте обычный файл; ссылка, папка, ничего — None."""

    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def clear_link(path) -> os.stat_result | None:
    """Ссылку (и прочую запись, кроме обычного файла и папки) на месте `path`
    удаляет саму; возвращает lstat обычного файла, иначе None."""

    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    if stat.S_ISREG(info.st_mode):
        return info
    if not stat.S_ISDIR(info.st_mode):
        os.unlink(path)
    return None


def make_replaceable(path) -> None:
    """Перед атомарной заменой `path`: ссылки нет, файл «только чтение» на
    Windows снят с защиты от записи (chmod — только обычного файла)."""

    info = clear_link(path)
    if info is not None and IS_WINDOWS and not info.st_mode & stat.S_IWRITE:
        os.chmod(path, stat.S_IMODE(info.st_mode) | stat.S_IWRITE)


def open_fresh(path):
    """Файл с чистого листа («wb») не по симлинку: ссылка на месте удаляется
    сама, O_NOFOLLOW — на случай подложенной между проверкой и открытием."""

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    clear_link(path)
    descriptor = open_nofollow(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    return os.fdopen(descriptor, "wb")

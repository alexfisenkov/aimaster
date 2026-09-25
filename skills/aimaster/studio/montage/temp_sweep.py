"""Уборка своих временных папок, оставшихся от оборванных прошлых операций:
закачки скиллов в кеш (scripts/install_montage_fetch.py) и копии скилла в
рабочую папку (workspace_skills.py). Одна реализация на оба места — раньше их
было две почти одинаковых, и каждую правку приходилось вносить дважды.

Правила:
- имя целиком (fullmatch, не `^…$`: тот пропускает перевод строки в конце)
  совпадает с тем, что создаёт tempfile.mkdtemp(prefix=...) — префикс и ровно
  8 знаков из «a-z0-9_»; чужая «.aimaster-tmp-download-notes» не совпадёт;
- только настоящая папка: символическая ссылка, junction и любая другая точка
  повторной обработки Windows пропускаются — по ссылкам уборка не ходит;
- только не моложе часа: свежая может быть рабочей папкой параллельного запуска;
- уборка — забота, а не обязанность: ошибка доступа (папка не читается, не
  открывается для поиска, исчезла посреди прохода) наружу не выходит никогда.
"""

from __future__ import annotations

import re
import shutil
import stat
import time
from pathlib import Path

MIN_AGE_SECONDS = 3600
# tempfile._RandomNameSequence: 8 знаков из «abcdefghijklmnopqrstuvwxyz0123456789_»
# (CPython 3.11–3.14); test_montage_temp_sweep сверяет это с настоящим mkdtemp.
MKDTEMP_TAIL = r"[a-z0-9_]{8}"


def _removable(path: Path, now: float, min_age: float) -> bool:
    try:
        info = path.lstat()  # сама запись, не то, на что она ссылается
    except OSError:
        return False
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_reparse_tag", 0):
        return False
    return now - info.st_mtime >= min_age


def sweep_stale(parent, prefix: str, *, min_age: float = MIN_AGE_SECONDS) -> None:
    """Удаляет в parent старые временные папки вида `<prefix>XXXXXXXX`.

    Звать до того, как операция создаст СВОЮ рабочую папку. Не бросает
    исключений: parent может не существовать, не читаться или не открываться."""

    pattern = re.compile(re.escape(prefix) + MKDTEMP_TAIL)
    try:
        children = list(Path(parent).iterdir())
    except OSError:
        return
    now = time.time()
    for path in children:
        if pattern.fullmatch(path.name) and _removable(path, now, min_age):
            shutil.rmtree(path, ignore_errors=True)

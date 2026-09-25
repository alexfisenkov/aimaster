"""Проверка «эта рабочая папка — случайно не сама домашняя?» для
workspace_skills.py: скиллы HyperFrames никогда не должны попасть в
настоящие ~/.claude/skills или ~/.agents/skills (решение владельца
2026-09-25). Отдельный модуль — чтобы держать это узкое, легко
тестируемое сравнение путей в стороне от копирования (разбор 1/5 → 2/5,
находка A).
"""

from __future__ import annotations

import os
from pathlib import Path

AGENT_DIRS = ((".claude", "skills"), (".agents", "skills"))


def same_dir(a, b) -> bool:
    """a и b — один и тот же каталог на диске.

    os.path.samefile сравнивает (st_dev, st_ino), поэтому правильно узнаёт
    один и тот же каталог и при разном регистре на регистронезависимой ФС
    (APFS по умолчанию), и когда где-то по пути символическая ссылка (в т.ч.
    сама «домашняя» ~/.claude, что типично для управления дотфайлами) — stat
    сам её раскрывает. Нужен хотя бы один существующий путь; если оба ещё не
    созданы (например, целевая ~/.claude/skills), падаем на сравнение
    полностью резолвнутых путей — оно тоже раскрывает существующие
    промежуточные симлинки (регистронезависимость тут уже не гарантирована —
    отдельно ловим на уровне родительских папок, см. would_write_into_home).
    Цикл символических ссылок — RuntimeError на Python 3.11/3.12 у
    Path.resolve(), OSError (ELOOP) у os.path.samefile и на 3.13+ — не
    должен ронять проверку, только сказать «не совпало»."""

    try:
        return os.path.samefile(a, b)
    except OSError:
        pass
    try:
        return Path(a).resolve() == Path(b).resolve()
    except (OSError, RuntimeError):
        return False


def would_write_into_home(workspace) -> bool:
    """Рабочая папка — сама домашняя, либо <ws>/.claude или <ws>/.agents
    (сам корень агента, ДО подпапки skills — она может ещё не существовать
    ни с той, ни с другой стороны, тогда самого симлинка не видно), либо
    <ws>/.claude/skills / <ws>/.agents/skills ведут (в т.ч. через
    символическую ссылку где-то по пути) в настоящую глобальную папку
    агента."""

    try:
        home = Path.home()
    except RuntimeError:
        return False  # HOME не определить — не можем сказать, что это она
    workspace = Path(workspace).expanduser()
    if same_dir(workspace, home):
        return True
    for parts in AGENT_DIRS:
        root = parts[:-1]  # (".claude",) или (".agents",) — сам корень агента
        if same_dir(workspace.joinpath(*root), home.joinpath(*root)):
            return True
        if same_dir(workspace.joinpath(*parts), home.joinpath(*parts)):
            return True
    return False

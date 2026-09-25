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
    промежуточные симлинки, просто не умеет регистронезависимость."""

    try:
        return os.path.samefile(a, b)
    except OSError:
        pass
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def would_write_into_home(workspace) -> bool:
    """Рабочая папка — сама домашняя, либо <ws>/.claude/skills или
    <ws>/.agents/skills ведёт (в т.ч. через символическую ссылку где-то по
    пути) в настоящую глобальную папку агента."""

    try:
        home = Path.home()
    except RuntimeError:
        return False  # HOME не определить — не можем сказать, что это она
    workspace = Path(workspace).expanduser()
    if same_dir(workspace, home):
        return True
    return any(same_dir(workspace.joinpath(*parts), home.joinpath(*parts)) for parts in AGENT_DIRS)

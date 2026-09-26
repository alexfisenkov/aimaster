"""Столы, запущенные этим процессом. Дашборд (план Б) держит столы нескольких
проектов сразу, поэтому свой Popen — доказательство только для своего
проекта: ключ — (папка montage проекта, pid), и время запуска процесса из
записи стола должно совпасть с запомненным при запуске. Завершившийся Popen
выбрасывается, как только это замечено."""

from __future__ import annotations

import os
import subprocess

RUNNING, EXITED = "running", "exited"
_children: dict[tuple[str, int], tuple[subprocess.Popen, str | None]] = {}


def _key(paths, pid: int) -> tuple[str, int]:
    return os.path.normcase(os.path.realpath(str(paths.root))), pid


def remember(paths, process, started: str | None) -> None:
    _children[_key(paths, process.pid)] = (process, started)


def own(paths, record: dict) -> str | None:
    """RUNNING — наш живой Popen этого проекта с тем же временем запуска, что
    в записи; EXITED — наш Popen с этим pid уже завершился (номер мог
    достаться чужому); None — доказательства нет."""

    key = _key(paths, record["pid"])
    entry = _children.get(key)
    if entry is None:
        return None
    child, started = entry
    if child.poll() is not None:
        forget(paths, record["pid"])
        return EXITED
    return RUNNING if started == record.get("process_started") else None


def forget(paths, pid: int) -> None:
    """Убрать из реестра и прибрать процесс (без зомби в долгоживущем дашборде)."""

    entry = _children.pop(_key(paths, pid), None)
    if entry is None:
        return
    try:
        entry[0].wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        pass

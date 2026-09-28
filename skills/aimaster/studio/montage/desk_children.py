"""Столы, запущенные этим процессом. Дашборд держит столы нескольких
проектов сразу и отвечает на запросы из разных потоков, поэтому реестр — под
замком, а свой Popen — доказательство только для своего проекта: ключ —
(папка montage проекта, pid), и время запуска процесса из записи стола должно
совпасть с запомненным при запуске. Завершившийся Popen выбрасывается, как
только это замечено; `sweep` (хранитель столов дашборда) прибирает реестр
целиком. Ждать завершения процесса и останавливать его — всегда вне замка;
запись, которую останавливают, сперва забирается из реестра под замком —
две уборки одновременно не остановят один стол дважды."""

from __future__ import annotations

import os
import subprocess
import threading

from . import MontageError

RUNNING, EXITED = "running", "exited"
_children: dict[tuple[str, int], tuple[subprocess.Popen, str | None]] = {}
_lock = threading.Lock()


def root_key(paths) -> str:
    """Папка montage проекта в одном виде — ключ реестра и отметка в записи стола."""

    return os.path.normcase(os.path.realpath(str(paths.root)))


def _key(paths, pid: int) -> tuple[str, int]:
    return root_key(paths), pid


def remember(paths, process, started: str | None) -> None:
    with _lock:
        _children[_key(paths, process.pid)] = (process, started)


def own(paths, record: dict) -> str | None:
    """RUNNING — наш живой Popen этого проекта с тем же временем запуска, что
    в записи; EXITED — наш Popen с этим pid уже завершился (номер мог
    достаться чужому); None — доказательства нет."""

    key = _key(paths, record["pid"])
    with _lock:
        entry = _children.get(key)
    if entry is None:
        return None
    child, started = entry
    if child.poll() is not None:
        _reap(_take(key, child))
        return EXITED
    return RUNNING if started == record.get("process_started") else None


def forget(paths, pid: int) -> None:
    """Убрать из реестра и прибрать процесс (без зомби в долгоживущем дашборде)."""

    _reap(_take(_key(paths, pid)))


def _take(key: tuple[str, int], child=None):
    """Забрать Popen из реестра под замком (только тот самый `child`, если
    задан); его уже забрали — None."""

    with _lock:
        entry = _children.get(key)
        if entry is None or (child is not None and entry[0] is not child):
            return None
        return _children.pop(key)[0]


def _reap(child) -> None:
    if child is None:
        return
    try:
        child.wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        pass


def sweep(*, kill, all_live: bool = False) -> list[int]:
    """Прибрать реестр: завершившиеся — забыть; живые, чья папка montage
    исчезла или переименована (или все живые при `all_live` — выход
    дашборда), — остановить `kill(child)` и забыть. Это свой Popen: пока он не
    прибран, его номер не достанется чужому процессу. Не остановился (отказ
    `kill`) — остаётся в реестре до следующей уборки. Ответ — pid остановленных."""

    with _lock:
        items = list(_children.items())
    stopped = []
    for key, (child, started) in items:
        if not all_live and child.poll() is None and os.path.isdir(key[0]):
            continue
        if _take(key, child) is None:
            continue  # его уже прибрала другая уборка или остановка стола
        if child.poll() is None:
            try:
                kill(child)
            except (MontageError, OSError):
                with _lock:
                    _children.setdefault(key, (child, started))
                continue
            stopped.append(key[1])
        _reap(child)
    return stopped

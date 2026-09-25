"""Управление узлом процессов node → Chrome/ffmpeg — POSIX и Windows.

node запускает Chrome (через puppeteer) и ffmpeg как своих детей. Начиная с
puppeteer-core ^25.10 / @puppeteer/browsers ^3.2.2 (версии, закреплённые в
HyperFrames 0.8.75), их `launch.js` ставит `detached ??= process.platform
!== 'win32'` — на POSIX Chrome становится лидером СВОЕЙ собственной сессии,
а не остаётся в группе node. Поэтому `killpg(node_pgid, …)` его не достаёт:
нужно явно обойти дерево потомков (через `ps`, а не `/proc` — так же на
macOS и Linux) и разослать сигналы каждому найденному отдельно.

Порядок на POSIX: SIGTERM группе node и каждому потомку (дать puppeteer/
Chrome шанс на штатное закрытие — как обычно и работает Ctrl+C), недолгая
пауза, затем SIGKILL всем, кто не отреагировал. Windows: `taskkill /T /F`
сразу останавливает всё дерево одной командой — своей эскалации не нужно.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from ..platform_compat import IS_WINDOWS

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
GRACE_SECONDS = 3.0
TASKKILL_TIMEOUT = 10.0


def group_kwargs() -> dict:
    """Popen-флаги, под которыми node становится корнем отдельной группы
    процессов (POSIX) или группы + скрытой консоли (Windows)."""

    return ({"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW} if IS_WINDOWS
           else {"start_new_session": True})


def _taskkill_path() -> str:
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    return str(Path(root) / "System32" / "taskkill.exe")


def _descendants(root_pid: int, *, run=subprocess.run) -> list[int]:
    """Все потомки root_pid (обход дерева ppid из `ps -A`), собранный ДО
    убийства — после SIGTERM/SIGKILL дерево читать уже поздно."""

    try:
        proc = run(["/bin/ps", "-A", "-o", "pid=,ppid="], stdin=subprocess.DEVNULL,
                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, text=True)
    except (OSError, subprocess.SubprocessError):
        return []
    children_of: dict[int, list[int]] = {}
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        children_of.setdefault(ppid, []).append(pid)
    found: list[int] = []
    seen: set[int] = set()
    frontier = [root_pid]
    while frontier:
        for child in children_of.get(frontier.pop(), ()):
            if child not in seen:
                seen.add(child)
                found.append(child)
                frontier.append(child)
    return found


def _signal_group(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


def _signal_pid(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


def kill_tree(proc) -> None:
    """Останавливает node и весь узел процессов, который он породил.

    Вызывающий код (engine_cli.default_runner) сам решает, когда: по
    таймауту, по Ctrl+C или любой другой ошибке — в обоих случаях цель одна:
    ничего от HyperFrames не должно продолжать работать после возврата."""

    if IS_WINDOWS:
        try:
            subprocess.run([_taskkill_path(), "/T", "/F", "/PID", str(proc.pid)],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=TASKKILL_TIMEOUT,
                           creationflags=CREATE_NO_WINDOW)
        except (OSError, subprocess.SubprocessError):
            pass  # лучшее, что можно сделать — не дать чистке уронить вызывающего
        return
    descendants = _descendants(proc.pid)
    _signal_group(proc.pid, signal.SIGTERM)
    for pid in descendants:
        _signal_pid(pid, signal.SIGTERM)
    deadline = time.monotonic() + GRACE_SECONDS
    while time.monotonic() < deadline and proc.poll() is None:
        time.sleep(0.05)
    _signal_group(proc.pid, signal.SIGKILL)
    for pid in descendants:
        _signal_pid(pid, signal.SIGKILL)

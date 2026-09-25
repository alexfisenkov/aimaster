"""Жив ли процесс монтажного стола — по номеру из montage/.desk.json.

Остановка — только `proc_tree.kill_tree` (обход потомков: Chrome, которого
puppeteer запускает отдельной сессией, группой не достаётся); здесь — лишь
проверки «жив» и объект с `pid`/`poll()`, который этой функции нужен, когда
Popen-объекта нет (стол открывал другой вызов CLI).
"""

from __future__ import annotations

import os

from ..platform_compat import IS_WINDOWS

STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5


def _windows_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED  # есть, но чужой по правам
    try:
        code = wintypes.DWORD()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return bool(ok) and code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def process_alive(pid) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if IS_WINDOWS:
        return _windows_alive(pid)
    try:
        reaped, _status = os.waitpid(pid, os.WNOHANG)  # свой завершившийся ребёнок — прибрать
        if reaped == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def own_session_alive(pid) -> bool:
    """Жив и всё ещё лидер своей сессии — так стол запускает `popen_engine`
    (start_new_session). Чужой процесс, получивший тот же номер после смерти
    стола, лидером своей сессии почти никогда не бывает — его не тронем.
    Windows сессий процессов не знает: там — просто «жив»."""

    if not process_alive(pid):
        return False
    if IS_WINDOWS:
        return True
    try:
        return os.getsid(pid) == pid
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # проверить нельзя — считаем живым, как process_alive


class PidHandle:
    """`pid` + `poll()` для `proc_tree.kill_tree`, когда Popen-объекта нет."""

    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        return None if process_alive(self.pid) else 0

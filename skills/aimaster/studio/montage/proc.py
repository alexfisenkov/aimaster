"""Жив ли процесс монтажного стола и тот ли это процесс — по номеру из montage/.desk.json.

Остановка — только `proc_tree.kill_tree` (обход потомков: Chrome, которого
puppeteer запускает отдельной сессией, группой не достаётся); здесь — проверки
«жив», отпечаток времени запуска процесса (номер процесса ОС выдаёт заново,
а время запуска у чужого процесса с тем же номером другое) и объект с
`pid`/`poll()`, который `kill_tree` нужен, когда Popen-объекта нет.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from pathlib import Path

from ..platform_compat import IS_WINDOWS

STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5
MAX_PID = 2 ** 31 - 1
PS = "/bin/ps"


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
    kernel32.GetProcessTimes.argtypes = (ctypes.c_void_p,) + (ctypes.POINTER(_FileTime),) * 4
    return kernel32


def _windows_query(pid: int, kernel32, ask):
    """Открыть процесс только на чтение сведений и спросить `ask(handle)`.
    Нет доступа (чужой по правам) или нет процесса — None: не наш."""

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        return ask(handle)
    finally:
        kernel32.CloseHandle(handle)


def _windows_alive(pid: int, kernel32=None, last_error=None) -> bool:
    """Жив. Нет доступа (ERROR_ACCESS_DENIED) — процесс есть, но чужой: жив,
    а «наш ли» решит время запуска (его без доступа не прочитать — не наш)."""

    kernel32 = kernel32 or _kernel32()
    last_error = last_error or ctypes.get_last_error  # есть только на Windows

    def still_active(handle):
        code = ctypes.c_uint32()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
    answer = _windows_query(pid, kernel32, still_active)
    if answer is None:
        return last_error() == ERROR_ACCESS_DENIED
    return bool(answer)


def _windows_started(pid: int, kernel32=None) -> str | None:
    kernel32 = kernel32 or _kernel32()

    def creation(handle):
        times = [_FileTime() for _ in range(4)]
        if not kernel32.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
            return None
        return f"win:{(times[0].high << 32) | times[0].low}"
    return _windows_query(pid, kernel32, creation)


def _linux_started(stat_text: str) -> str | None:
    """/proc/PID/stat, поле 22 (starttime, такты с загрузки). Имя процесса
    (поле 2) в скобках может содержать пробелы и скобки — режем по последней «)»."""

    fields = stat_text.rsplit(")", 1)[-1].split()
    return f"linux:{fields[19]}" if len(fields) > 19 else None


def _posix_started(pid: int, *, run=subprocess.run, proc_root: Path = Path("/proc")) -> str | None:
    try:
        return _linux_started((proc_root / str(pid) / "stat").read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError):
        pass
    try:  # macOS и прочие без /proc: время запуска от ps (секунды), без локали
        proc = run([PS, "-o", "lstart=", "-p", str(pid)], stdin=subprocess.DEVNULL,
                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, text=True,
                   env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"})
    except (OSError, subprocess.SubprocessError):
        return None
    started = " ".join((proc.stdout or "").split())
    return f"ps:{started}" if proc.returncode == 0 and started else None


def process_started(pid) -> str | None:
    """Отпечаток времени запуска процесса; None — процесса нет или прочитать нельзя."""

    if not _valid_pid(pid):
        return None
    return _windows_started(pid) if IS_WINDOWS else _posix_started(pid)


def _valid_pid(pid) -> bool:
    """Номер из файла записи уходит в waitpid/kill/OpenProcess: вне диапазона — OverflowError."""

    return isinstance(pid, int) and not isinstance(pid, bool) and 0 < pid <= MAX_PID


def process_alive(pid) -> bool:
    if not _valid_pid(pid):
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


class PidHandle:
    """`pid` + `poll()` для `proc_tree.kill_tree`, когда Popen-объекта нет."""

    def __init__(self, pid: int):
        self.pid = pid

    def poll(self):
        return None if process_alive(self.pid) else 0

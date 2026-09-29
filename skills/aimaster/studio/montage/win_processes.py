"""Windows: процессы через kernel32 (ctypes, стандартная библиотека).

- `process_pairs()` — снимок всех процессов (CreateToolhelp32Snapshot):
  пары (pid, pid родителя) — из них `proc_tree.descendants` строит дерево.
- `kill_on_close_job()` и `assign(job, pid)` — Job Object с
  JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: когда закрывается последний дескриптор
  задания (процесс-владелец завершился как угодно — Ctrl+Break,
  TerminateProcess, закрытое окно), ОС завершает все процессы задания и их
  потомков, запущенных после включения в задание (`desk_job.py`).

Сигнатуры объявлены полностью: 64-битные дескрипторы не должны проходить через
преобразование ctypes к C `int` по умолчанию. Модуль импортируется только на
Windows (лениво); на macOS и Linux из него ничего не вызывается."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache

TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE = ctypes.c_void_p(-1).value
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


class ProcessEntry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


class BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _declare(function, restype, *argtypes):
    function.restype = restype
    function.argtypes = list(argtypes)


@lru_cache(maxsize=1)
def kernel32():
    lib = ctypes.WinDLL("kernel32", use_last_error=True)
    handle, dword, boolean = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
    _declare(lib.CreateToolhelp32Snapshot, handle, dword, dword)
    _declare(lib.Process32FirstW, boolean, handle, ctypes.POINTER(ProcessEntry))
    _declare(lib.Process32NextW, boolean, handle, ctypes.POINTER(ProcessEntry))
    _declare(lib.CloseHandle, boolean, handle)
    _declare(lib.CreateJobObjectW, handle, ctypes.c_void_p, wintypes.LPCWSTR)
    _declare(lib.SetInformationJobObject, boolean, handle, ctypes.c_int, ctypes.c_void_p, dword)
    _declare(lib.OpenProcess, handle, dword, boolean, dword)
    _declare(lib.AssignProcessToJobObject, boolean, handle, handle)
    return lib


def process_pairs(lib=None) -> list[tuple[int, int]]:
    """(pid, pid родителя) всех процессов; снимок не сделался — пустой список."""

    lib = lib or kernel32()
    snapshot = lib.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE:
        return []
    pairs = []
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        more = lib.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            pairs.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID)))
            more = lib.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        lib.CloseHandle(snapshot)
    return pairs


def kill_on_close_job(lib=None):
    """Новое задание с KILL_ON_JOB_CLOSE (дескриптор не наследуется); не
    вышло — OSError."""

    lib = lib or kernel32()
    job = lib.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not lib.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                                       ctypes.byref(limits), ctypes.sizeof(limits)):
        error = ctypes.WinError(ctypes.get_last_error())
        lib.CloseHandle(job)
        raise error
    return job


def assign(job, pid: int, lib=None) -> None:
    """Включить процесс в задание; не вышло — OSError."""

    lib = lib or kernel32()
    process = lib.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    if not process:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not lib.AssignProcessToJobObject(job, process):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        lib.CloseHandle(process)

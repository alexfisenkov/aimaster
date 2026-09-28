"""«Показать в папке»: файловый менеджер компьютера с выделенным файлом.

macOS — Finder: `/usr/bin/open -R <файл>`. Windows — Проводник:
`%SystemRoot%\\explorer.exe /select,"<файл>"` одной командной строкой для
CreateProcess, без cmd.exe: Проводник разбирает `/select,` сам и не понимает
кавычки вокруг всего аргумента, которые ставит list2cmdline; кавычки в имени
файла на Windows не бывает; имя переменной SystemRoot — в любом регистре,
как её видит Windows. Linux — `xdg-open <папка>`: выделять файл он не умеет,
а на части рабочих столов не возвращается, пока файловый менеджер открыт, —
поэтому он запускается отдельно (своя сессия): завершился с кодом 0 или ещё
работает через `LINUX_WAIT` с — успех, его завершение приберёт фоновый
поток. Программа — всегда по полному пути, оболочки нет. Проводник отвечает
кодом 1 и при успехе — поэтому код не проверяется только у него."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path, PurePath, PureWindowsPath
from typing import Mapping

from .montage import MontageError
from .platform_compat import IS_WINDOWS, find_program

MAC_OPEN = "/usr/bin/open"
TIMEOUT_SECONDS = 15
LINUX_WAIT = 5
FAILED = "не удалось открыть папку с роликом"
NO_PROGRAM = {
    "mac": "на этом компьютере нет программы open — откройте папку с роликом сами",
    "windows": "не найден Проводник (explorer.exe) — откройте папку с роликом сами",
    "linux": "на этом компьютере нет программы xdg-open — откройте папку с роликом сами",
}


def current_system() -> str:
    if IS_WINDOWS:
        return "windows"
    return "mac" if sys.platform == "darwin" else "linux"


def _variable(environ: Mapping[str, str], name: str) -> str:
    """Переменная окружения Windows: имя без учёта регистра."""

    if environ.get(name):
        return environ[name]
    folded = name.casefold()
    return next((value for key, value in environ.items()
                 if isinstance(key, str) and key.casefold() == folded and value), "")


def reveal_command(target: PurePath, *, system: str, environ: Mapping[str, str],
                   find=find_program, is_file=os.path.isfile) -> list[str] | str | None:
    """Чем показать `target` на этой ОС; нечем — None."""

    if system == "mac":
        return [MAC_OPEN, "-R", str(target)] if is_file(MAC_OPEN) else None
    if system == "windows":
        root = _variable(environ, "SystemRoot") or _variable(environ, "windir")
        if not PureWindowsPath(root).is_absolute():
            return None
        explorer = str(PureWindowsPath(root) / "explorer.exe")
        return f'"{explorer}" /select,"{target}"' if is_file(explorer) else None
    program = find("xdg-open", environ=environ)
    return [program, str(target.parent)] if program else None


def reveal_available(*, system=None, environ=None, find=find_program, is_file=os.path.isfile) -> bool:
    system = system or current_system()
    environ = os.environ if environ is None else environ
    return reveal_command(Path("ролик.mp4"), system=system, environ=environ, find=find,
                          is_file=is_file) is not None


def _open_detached(command: list[str], *, popen, wait: float) -> None:
    try:
        process = popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise MontageError(FAILED) from error
    try:
        code = process.wait(timeout=wait)
    except subprocess.TimeoutExpired:  # файловый менеджер открыт и ждёт человека
        threading.Thread(target=process.wait, name="aimaster-reveal", daemon=True).start()
        return
    if code != 0:
        raise MontageError(FAILED)


def reveal_file(target: PurePath, *, system=None, environ=None, run=subprocess.run,
                popen=subprocess.Popen, find=find_program, is_file=os.path.isfile,
                wait: float = LINUX_WAIT) -> None:
    system = system or current_system()
    environ = os.environ if environ is None else environ
    command = reveal_command(target, system=system, environ=environ, find=find, is_file=is_file)
    if command is None:
        raise MontageError(NO_PROGRAM[system])
    if system == "linux":
        _open_detached(command, popen=popen, wait=wait)
        return
    try:
        result = run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, timeout=TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise MontageError(FAILED) from error
    if system != "windows" and result.returncode != 0:
        raise MontageError(FAILED)

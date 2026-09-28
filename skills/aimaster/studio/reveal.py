"""«Показать в папке»: файловый менеджер компьютера с выделенным файлом.

macOS — Finder: `/usr/bin/open -R <файл>`. Windows — Проводник:
`%SystemRoot%\\explorer.exe /select,"<файл>"` одной командной строкой для
CreateProcess, без cmd.exe: Проводник разбирает `/select,` сам и не понимает
кавычки вокруг всего аргумента, которые ставит list2cmdline; кавычки в имени
файла на Windows не бывает. Linux — `xdg-open <папка>`: выделять файл он не
умеет. Программа — всегда по полному пути, оболочки нет. Проводник отвечает
кодом 1 и при успехе — поэтому код не проверяется только у него."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path, PurePath, PureWindowsPath
from typing import Mapping

from .montage import MontageError
from .platform_compat import IS_WINDOWS, find_program

MAC_OPEN = "/usr/bin/open"
TIMEOUT_SECONDS = 15
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


def reveal_command(target: PurePath, *, system: str, environ: Mapping[str, str],
                   find=find_program, is_file=os.path.isfile) -> list[str] | str | None:
    """Чем показать `target` на этой ОС; нечем — None."""

    if system == "mac":
        return [MAC_OPEN, "-R", str(target)] if is_file(MAC_OPEN) else None
    if system == "windows":
        root = environ.get("SystemRoot") or environ.get("windir") or ""
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


def reveal_file(target: PurePath, *, system=None, environ=None, run=subprocess.run,
                find=find_program, is_file=os.path.isfile) -> None:
    system = system or current_system()
    environ = os.environ if environ is None else environ
    command = reveal_command(target, system=system, environ=environ, find=find, is_file=is_file)
    if command is None:
        raise MontageError(NO_PROGRAM[system])
    try:
        result = run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, timeout=TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise MontageError(FAILED) from error
    if system != "windows" and result.returncode != 0:
        raise MontageError(FAILED)

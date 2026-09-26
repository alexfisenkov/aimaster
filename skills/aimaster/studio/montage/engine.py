"""Где стоит движок HyperFrames и готов ли он к работе.

Движок ставит scripts/install_montage.py в <user_data_dir>/tools/hyperframes:
`npm install --prefix`, свой HOME (home/) для кэшей и браузера и запись
aimaster-engine.json с путём к скачанному браузеру (раскладка папки —
prefix_layout.py, её имена доступны и отсюда). Переменная
AIMASTER_HYPERFRAMES_DIR подменяет папку — для CI и смоука.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..platform_compat import IS_WINDOWS, find_program, user_data_dir
from . import MontageError
from .prefix_layout import (  # noqa: F401 — прежние имена engine.* (интерфейс плана)
    RECORD_NAME, browser_inside_home, entry_script, gsap_problem, installed_version,
    package_version, read_record, recorded_browser, write_record)

PIN_FILE = Path(__file__).with_name("engine.json")
INSTALL_PY = Path(__file__).resolve().parents[2] / "scripts" / "install.py"
PREFIX_ENV = "AIMASTER_HYPERFRAMES_DIR"
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def load_pin() -> dict:
    return json.loads(PIN_FILE.read_text(encoding="utf-8"))


def tools_prefix(*, home=None, environ=None) -> Path:
    environ = os.environ if environ is None else environ
    override = environ.get(PREFIX_ENV)
    if override and Path(override).is_absolute():
        return Path(override)
    return user_data_dir(home=home, environ=environ) / "tools" / "hyperframes"


def install_argv() -> list[str]:
    """argv установки без какой-либо кавычки под конкретную оболочку.

    Для прямого запуска (Popen без shell=True) — самый надёжный вид команды;
    install_command() ниже строит из него ЧЕЛОВЕКУ читаемую строку."""

    return [sys.executable, str(INSTALL_PY), "--install-deps"]


def install_command() -> str:
    """Точная команда установки монтажа на этой машине — для показа человеку
    (автопилот запускает не строку, а install_argv() напрямую).

    На Windows list2cmdline кавычит путь к python.exe, если в нём пробел
    (типично для "C:\\Program Files\\Python312\\python.exe"). Такая строка
    работает в cmd.exe как есть, но PowerShell воспринимает ведущую кавычку
    как текстовый литерал, а не вызов команды — нужен оператор вызова `&`."""

    argv = install_argv()
    if not IS_WINDOWS:
        return shlex.join(argv)
    command = subprocess.list2cmdline(argv)
    return f"& {command}" if command.startswith('"') else command


def find_node(*, environ=None) -> str | None:
    environ = os.environ if environ is None else environ
    found = find_program("node", environ=environ)
    if found or not IS_WINDOWS:
        return found
    # winget ставит Node в Program Files; PATH этого процесса про него ещё не знает
    for base in (environ.get("ProgramFiles"), environ.get("ProgramW6432")):
        candidate = Path(base) / "nodejs" / "node.exe" if base else None
        if candidate is not None and candidate.is_file():
            return str(candidate)
    return None


def node_major(node: str, *, run=subprocess.run) -> int | None:
    try:
        proc = run([node, "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION.search((proc.stdout or b"").decode("utf-8", errors="replace"))
    return int(match.group(1)) if proc.returncode == 0 and match else None


@dataclass(frozen=True)
class Engine:
    node: str
    script: Path
    prefix: Path
    version: str
    browser: str | None


def locate(*, home=None, environ=None, run=subprocess.run) -> tuple[Engine | None, str]:
    """(движок, "") если всё на месте, иначе (None, причина по-русски)."""

    pin = load_pin()
    prefix = tools_prefix(home=home, environ=environ)
    node = find_node(environ=environ)
    if node is None:
        return None, "не найден Node.js"
    major = node_major(node, run=run)
    if major is None or major < pin["node_min_major"]:
        return None, (f"нужен Node.js {pin['node_min_major']} или новее "
                      f"(найден {major if major is not None else 'неизвестной версии'})")
    script = entry_script(prefix)
    version = installed_version(prefix)
    if not script.is_file() or version is None:
        return None, f"HyperFrames не установлен в {prefix}"
    if version != pin["version"]:
        return None, f"стоит HyperFrames {version}, нужен {pin['version']}"
    # Та же проверка, что у check_browser установщика (round 4/5): оба
    # согласны, иначе автопилот крутил бы команду установки по кругу.
    browser = recorded_browser(prefix, version=pin["version"])
    if browser is None:
        return None, "не скачан браузер для сборки видео"
    gsap = gsap_problem(prefix, pin["gsap_version"])  # без него черновик откажет (vendor.py)
    if gsap:
        return None, gsap
    return Engine(node=node, script=script, prefix=prefix, version=version, browser=browser), ""


def engine_status(*, home=None, environ=None, run=subprocess.run) -> dict:
    found, reason = locate(home=home, environ=environ, run=run)
    return {"state": "installed" if found else "missing",
            "version": found.version if found else None,
            "wanted": load_pin()["version"], "reason": reason,
            "prefix": str(tools_prefix(home=home, environ=environ)),
            "install": install_command(), "install_argv": install_argv()}


def require_engine(**kwargs) -> Engine:
    found, reason = locate(**kwargs)
    if found is None:
        raise MontageError(f"Монтажный движок не готов: {reason}. Поставьте его командой: "
                           f"{install_command()}")
    return found

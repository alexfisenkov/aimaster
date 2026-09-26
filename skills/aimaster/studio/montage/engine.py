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
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..platform_compat import IS_WINDOWS, find_program, user_data_dir
from . import MontageError
from .prefix_layout import (  # noqa: F401 — прежние имена engine.* (интерфейс плана)
    RECORD_NAME, browser_inside_home, entry_script, gsap_problem, hyperframes_problem,
    installed_version, package_problem, package_version, read_record, recorded_browser,
    write_record)
from .shell_line import command_line

PIN_FILE = Path(__file__).with_name("engine.json")
INSTALL_PY = Path(__file__).resolve().parents[2] / "scripts" / "install.py"
PREFIX_ENV = "AIMASTER_HYPERFRAMES_DIR"
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
INSTALL_HINT = "Команда установки — engine.install в ответе montage status"


def load_pin() -> dict:
    return json.loads(PIN_FILE.read_text(encoding="utf-8"))


def tools_prefix(*, home=None, environ=None) -> Path:
    environ = os.environ if environ is None else environ
    override = environ.get(PREFIX_ENV)
    if override and Path(override).is_absolute():
        return Path(override)
    return user_data_dir(home=home, environ=environ) / "tools" / "hyperframes"


def install_argv() -> list[str]:
    """argv установки — список без кавычек под какую-либо оболочку. Самый
    надёжный вид команды: агент, чей инструмент запускает программу со
    списком аргументов, берёт его (`engine.install_argv` в montage status)."""

    return [sys.executable, str(INSTALL_PY), "--install-deps"]


def install_command() -> str:
    """Точная команда установки монтажа на этой машине — строкой, для показа
    и для оболочки (`engine.install` в montage status; вид — shell_line)."""

    return command_line(install_argv(), windows=IS_WINDOWS)


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
    """(движок, "") если всё на месте, иначе (None, причина по-русски, без
    абсолютных путей). Пакеты проверяются теми же `hyperframes_problem` и
    `gsap_problem`, что и у установщика (`package_problem`): установщик не
    сочтёт готовым движок, которому здесь откажут, и наоборот."""

    pin = load_pin()
    prefix = tools_prefix(home=home, environ=environ)
    node = find_node(environ=environ)
    if node is None:
        return None, "не найден Node.js"
    major = node_major(node, run=run)
    if major is None or major < pin["node_min_major"]:
        return None, (f"нужен Node.js {pin['node_min_major']} или новее "
                      f"(найден {major if major is not None else 'неизвестной версии'})")
    problem = hyperframes_problem(prefix, pin["version"])
    if problem:
        return None, problem
    # Та же проверка, что у check_browser установщика: оба согласны, иначе
    # автопилот крутил бы команду установки по кругу.
    browser = recorded_browser(prefix, version=pin["version"])
    if browser is None:
        return None, "не скачан браузер для сборки видео"
    gsap = gsap_problem(prefix, pin["gsap_version"])  # без него черновик откажет (vendor.py)
    if gsap:
        return None, gsap
    return Engine(node=node, script=entry_script(prefix), prefix=prefix, version=pin["version"],
                  browser=browser), ""


def engine_view(found: Engine | None, reason: str) -> dict:
    """`engine` в ответе montage status: одна форма на все места, где её
    показывают. `install`/`install_argv` — только когда движка нет."""

    return {"state": "installed" if found else "missing",
            "version": found.version if found else None,
            "wanted": load_pin()["version"], "reason": reason,
            "install": None if found else install_command(),
            "install_argv": None if found else install_argv()}


def not_ready(reason: str) -> MontageError:
    """Отказ «движок не готов». Без самой команды: в ней абсолютные пути (python,
    навык), а отказ показывают человеку; команда — в `engine.install`."""

    return MontageError(f"Монтажный движок не готов: {reason}. {INSTALL_HINT}")


def require_engine(**kwargs) -> Engine:
    found, reason = locate(**kwargs)
    if found is None:
        raise not_ready(reason)
    return found

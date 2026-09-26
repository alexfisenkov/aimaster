#!/usr/bin/env python3
"""HyperFrames и GSAP закреплённых версий — часть установщика монтажа
(install_montage.py). npm запускается как `node <npm-cli.js> install --prefix
<папка движка>`. Браузер для сборки — install_montage_browser.py (имена
browser_install/check_browser доступны и отсюда, как в плане задачи 4).

`install_missing` (--install-deps) ставит то, чего нет вовсе; `install_missing`
или `update` (--update) переустанавливают на закреплённую версию то, что уже
стоит, но разошлось с pin — pin в engine.json всегда источник истины (правило
владельца 2026-09-25). `--update` один, без --install-deps, ничего не ставит с
нуля на чистой машине."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS), str(_SCRIPTS.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install  # noqa: E402
from install_montage_node import item, npm_cli_js  # noqa: E402
from studio.montage import engine  # noqa: E402
from studio.montage.engine_cli import default_runner  # noqa: E402
from install_montage_browser import browser_install, check_browser  # noqa: E402,F401 — прежние имена


def _pinned(prefix: Path, pin: dict) -> bool:
    """Пакеты готовы ровно тогда, когда их примет engine.locate(): входной
    скрипт HyperFrames, версии обоих пакетов и файлы GSAP для черновика."""

    return not engine.package_problem(prefix, pin)


def _repair_message(prefix: Path, pin: dict) -> str:
    """Что не так с уже стоящими пакетами и как это починить."""

    return f"{engine.package_problem(prefix, pin)}: запустите install.py --install-deps"


NPM_MISSING_HINT = {
    "linux": ("рядом с Node.js нет npm — на Debian/Ubuntu он ставится отдельным пакетом: "
             "sudo apt install npm (или возьмите Node.js вместе с npm с "
             "https://nodejs.org/en/download)"),
    "macos": "рядом с Node.js нет npm — переустановите Node.js: brew reinstall node",
    "windows": ("рядом с Node.js нет npm — переустановите Node.js: "
               "winget install -e --id OpenJS.NodeJS.LTS"),
}


def _npm_runner(argv, cwd=None, timeout=None, env=None):
    """Как install._run, но при таймауте останавливает весь узел процессов npm
    (POSIX: /bin/ps + SIGTERM/SIGKILL; Windows: taskkill /T /F), а не только
    сам npm — иначе сборка нативных зависимостей оставляет висеть node."""

    try:
        proc = default_runner(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        decode = lambda raw: (raw or b"").decode("utf-8", errors="replace")  # noqa: E731
        return install.TIMEOUT_CODE, decode(error.output), decode(error.stderr)
    except OSError as error:
        return 127, "", str(error)
    decode = lambda raw: (raw or b"").decode("utf-8", errors="replace")  # noqa: E731
    return proc.returncode, decode(proc.stdout), decode(proc.stderr)


def engine_install(node: str, prefix: Path, pin: dict, *, kind: str, install_missing: bool,
                   update: bool, run=None) -> dict:
    """HyperFrames и GSAP (локальный файл для анимаций из скиллов HyperFrames) — одним npm.

    Ничего не стоит (`have is None`): ставит только с install_missing. Что-то
    стоит, но разошлось с pin (версия HyperFrames или GSAP): чинит с
    install_missing ИЛИ update — оба источника; pin всегда побеждает."""

    run = run or _npm_runner
    have = engine.installed_version(prefix)
    if _pinned(prefix, pin):
        return item("found", version=have, path=str(prefix))
    if have is None:
        if not install_missing:
            return item("missing", "HyperFrames не установлен: поставить install.py --install-deps",
                         path=str(prefix))
    elif not (install_missing or update):
        return item("missing", _repair_message(prefix, pin), version=have, path=str(prefix))
    npm = npm_cli_js(node)
    if npm is None:
        return item("failed", NPM_MISSING_HINT.get(kind, NPM_MISSING_HINT["linux"]),
                    blocker="npm_missing")
    Path(prefix).mkdir(parents=True, exist_ok=True)
    argv = [node, str(npm), "install", "--prefix", str(prefix),
            f"{pin['package']}@{pin['version']}", f"gsap@{pin['gsap_version']}", "--no-audit",
            "--no-fund", "--omit=dev", "--save-exact"]
    env = dict(os.environ)
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    timeout = pin["timeouts"]["npm_install"]
    code, out, err = run(argv, cwd=str(prefix), timeout=timeout, env=env)
    if code == install.TIMEOUT_CODE:
        return item("timeout", f"npm не уложился в {timeout // 60} мин; повторите позже")
    if code != 0:
        return item("failed", (err or out).strip()[-400:] or f"npm завершился с кодом {code}")
    if not _pinned(prefix, pin):
        return item("failed", f"npm отработал, но {engine.package_problem(prefix, pin)}")
    return item("installed", version=engine.installed_version(prefix), path=str(prefix))


def check_package(prefix: Path, pin: dict) -> dict:
    """Проверка без установки. Всё, что не примет engine.locate() (не та
    версия HyperFrames, нет GSAP или его файла), — missing: report["ok"]
    не станет True для движка, которому монтаж откажет."""

    have = engine.installed_version(prefix)
    if have is None:
        return item("missing", "поставить: install.py --install-deps", path=str(prefix))
    if not _pinned(prefix, pin):
        return item("missing", _repair_message(prefix, pin), version=have, path=str(prefix))
    return item("found", version=have, path=str(prefix))

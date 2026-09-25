#!/usr/bin/env python3
"""HyperFrames закреплённой версии и браузер для сборки видео — часть установщика
монтажа (install_montage.py). npm запускается как `node <npm-cli.js> install
--prefix <папка движка>`, браузер качает сам HyperFrames (`browser ensure`) в HOME
движка; путь к нему пишется в aimaster-engine.json — иначе `browser path` молча
отдал бы системный Chrome.

`install_missing` (--install-deps) ставит то, чего нет вовсе; `install_missing`
или `update` (--update) переустанавливают на закреплённую версию то, что уже
стоит, но разошлось с pin — pin в engine.json всегда источник истины (правило
владельца 2026-09-25, разбор 1/5). `--update` один, без --install-deps, ничего
не ставит с нуля на чистой машине."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS), str(_SCRIPTS.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install  # noqa: E402
from install_montage_node import item, npm_cli_js  # noqa: E402
from studio.montage import engine  # noqa: E402
from studio.montage.engine_cli import default_runner, run_engine  # noqa: E402


def _pinned(prefix: Path, pin: dict) -> bool:
    return engine.installed_version(prefix) == pin["version"] \
        and engine.package_version(prefix, "gsap") == pin["gsap_version"]


def _gsap_message(prefix: Path, pin: dict) -> str:
    """Различает «GSAP нет вовсе» и «GSAP не той версии» — вызывать только
    когда HyperFrames уже на закреплённой версии, а _pinned всё равно False
    (иначе расхождение может быть в HyperFrames, а не в GSAP)."""

    gsap_have = engine.package_version(prefix, "gsap")
    if gsap_have is None:
        return "нет GSAP для анимаций: запустите install.py --install-deps"
    return (f"стоит GSAP {gsap_have}, нужна {pin['gsap_version']}: "
            f"запустите install.py --install-deps")


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
        # have уже мог совпасть с pin["version"] — тогда расхождение только в
        # GSAP (нет вовсе или не той версии), и писать «стоит 0.8.75, нужна
        # 0.8.75» было бы бессмысленно.
        if have != pin["version"]:
            message = f"стоит {have}, нужна {pin['version']}: запустите install.py --install-deps"
        else:
            message = _gsap_message(prefix, pin)
        return item("found", message, version=have, path=str(prefix))
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
    if code != 0 or not _pinned(prefix, pin):
        return item("failed", (err or out).strip()[-400:] or f"npm завершился с кодом {code}")
    return item("installed", version=engine.installed_version(prefix), path=str(prefix))


def browser_install(node: str, prefix: Path, pin: dict, *, install_missing: bool, update: bool,
                    runner=None) -> dict:
    """Тот же принцип, что и у engine_install: ничего не скачано — только с
    install_missing; скачан, но для другой версии pin — install_missing ИЛИ
    update чинят, --update один на пустом месте ничего не качает."""

    record = engine.read_record(prefix)
    have_browser = bool(record.get("browser")) and Path(record["browser"]).is_file()
    if record.get("version") == pin["version"] and have_browser:
        return item("found", path=record["browser"])
    if not have_browser and not install_missing:
        return item("missing", "браузер для сборки не скачан: поставить install.py --install-deps")
    if have_browser and not (install_missing or update):
        return item("found", f"стоит браузер для версии {record.get('version')}, нужна {pin['version']}: "
                     "запустите install.py --install-deps", path=record["browser"])
    eng = engine.Engine(node=node, script=engine.entry_script(prefix), prefix=Path(prefix),
                        version=pin["version"], browser=None)
    kwargs = {} if runner is None else {"runner": runner}
    print("Качаю компонент для сборки видео (~100 МБ)…", file=sys.stderr, flush=True)
    ensured = run_engine(eng, ["browser", "ensure"], cwd=prefix,
                         timeout=pin["timeouts"]["browser"], **kwargs)
    if ensured.timed_out:
        return item("timeout", "браузер для сборки не скачался за отведённое время; повторите позже")
    located = run_engine(eng, ["browser", "path"], cwd=prefix, timeout=pin["timeouts"]["cli"],
                         **kwargs)
    lines = located.stdout.strip().splitlines()
    path = lines[-1].strip() if lines else ""
    inside = bool(path) and install._inside(path, str(Path(prefix) / "home"))
    if ensured.code != 0 or located.code != 0 or not inside or not Path(path).is_file():
        detail = (ensured.stderr or ensured.stdout).strip()[-400:]
        return item("failed", detail or "после загрузки браузер для сборки не найден в папке движка")
    record.update(browser=path, version=pin["version"], node=node,
                  updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    engine.write_record(prefix, record)
    return item("installed", "скачан браузер для сборки видео (~100 МБ)", path=path)


def check_package(prefix: Path, pin: dict) -> dict:
    have = engine.installed_version(prefix)
    if have is None:
        return item("missing", "поставить: install.py --install-deps", path=str(prefix))
    if have != pin["version"]:
        return item("found", f"стоит {have}, нужна {pin['version']}: запустите install.py --install-deps",
                     version=have, path=str(prefix))
    if engine.package_version(prefix, "gsap") != pin["gsap_version"]:
        # различает «GSAP нет вовсе» и «GSAP не той версии» — статус missing
        # у обоих (report["ok"] должен стать False), а текст — нет.
        return item("missing", _gsap_message(prefix, pin), version=have, path=str(prefix))
    return item("found", version=have, path=str(prefix))


def check_browser(prefix: Path, pin: dict) -> dict:
    record = engine.read_record(prefix)
    if record.get("version") == pin["version"] and record.get("browser") \
            and Path(record["browser"]).is_file():
        return item("found", path=record["browser"])
    return item("missing", "скачается при install.py --install-deps")

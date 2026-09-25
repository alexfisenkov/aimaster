#!/usr/bin/env python3
"""HyperFrames закреплённой версии и браузер для сборки видео — часть установщика
монтажа (install_montage.py). npm запускается как `node <npm-cli.js> install
--prefix <папка движка>`, браузер качает сам HyperFrames (`browser ensure`) в HOME
движка; путь к нему пишется в aimaster-engine.json — иначе `browser path` молча
отдал бы системный Chrome."""

from __future__ import annotations

import os
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
from studio.montage.engine_cli import run_engine  # noqa: E402


def _pinned(prefix: Path, pin: dict) -> bool:
    return engine.installed_version(prefix) == pin["version"] \
        and engine.package_version(prefix, "gsap") == pin["gsap_version"]


def engine_install(node: str, prefix: Path, pin: dict, *, update: bool, run=None) -> dict:
    """HyperFrames и GSAP (локальный файл для анимаций из скиллов HyperFrames) — одним npm."""

    run = run or install._run
    have = engine.installed_version(prefix)
    if _pinned(prefix, pin):
        return item("found", version=have, path=str(prefix))
    if have and have != pin["version"] and not update:
        return item("found", f"стоит {have}, нужна {pin['version']}: запустите install.py --update",
                     version=have, path=str(prefix))
    npm = npm_cli_js(node)
    if npm is None:
        return item("failed", "рядом с Node.js нет npm — переустановите Node.js")
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


def browser_install(node: str, prefix: Path, pin: dict, *, runner=None) -> dict:
    record = engine.read_record(prefix)
    if record.get("version") == pin["version"] and record.get("browser") \
            and Path(record["browser"]).is_file():
        return item("found", path=record["browser"])
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
        return item("found", f"стоит {have}, нужна {pin['version']}: запустите install.py --update",
                     version=have, path=str(prefix))
    if engine.package_version(prefix, "gsap") != pin["gsap_version"]:
        return item("found", "нет GSAP для анимаций: поставить install.py --install-deps",
                    version=have, path=str(prefix))
    return item("found", version=have, path=str(prefix))


def check_browser(prefix: Path, pin: dict) -> dict:
    record = engine.read_record(prefix)
    if record.get("version") == pin["version"] and record.get("browser") \
            and Path(record["browser"]).is_file():
        return item("found", path=record["browser"])
    return item("missing", "скачается при install.py --install-deps")

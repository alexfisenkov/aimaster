#!/usr/bin/env python3
"""Браузер для сборки видео — часть установщика монтажа (install_montage.py).
Качает его сам HyperFrames (`browser ensure`) в HOME движка; путь пишется в
aimaster-engine.json — иначе `browser path` молча отдал бы системный Chrome.

Тот же принцип, что у install_montage_engine.engine_install: ничего не скачано —
качает только с `install_missing` (--install-deps); скачан, но для другой
версии pin — чинят `install_missing` ИЛИ `update` (--update); --update один на
пустом месте ничего не качает (правило владельца 2026-09-25, разбор 1/5).

Звать только с найденным Node.js 22+ и HyperFrames закреплённой версии —
это проверяет install_montage.montage_report (разбор 4/5, находка 1)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS), str(_SCRIPTS.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install  # noqa: E402
from install_montage_node import item  # noqa: E402
from studio.montage import engine  # noqa: E402
from studio.montage.engine_cli import run_engine  # noqa: E402


def _failure_detail(ensured, located, path: str, *, inside: bool, is_file: bool) -> str:
    """Раньше сообщение об отказе показывало только хвост УСПЕШНОГО вывода
    `ensure` — выглядело как «всё скачалось», хотя отказал отдельный шаг
    `browser path` (разбор round 1/5, находка CI Windows: `ensure` печатает
    «Ready to render.», код 0, а браузер всё равно «failed»). Называем
    конкретную причину, а не только последний экран `ensure`."""

    reasons = []
    if ensured.code != 0:
        reasons.append(f"ensure вышел с кодом {ensured.code}")
    if located.code != 0:
        tail = (located.stderr or located.stdout).strip()[-300:]
        reasons.append(f"path вышел с кодом {located.code}" + (f": {tail!r}" if tail else ""))
    elif not path:
        reasons.append(f"path ничего не вывел: {located.stdout!r}")
    elif not inside:
        reasons.append(f"путь вне папки движка: {path!r}")
    elif not is_file:
        reasons.append(f"файла нет на диске: {path!r}")
    detail = "; ".join(reasons) or "после загрузки браузер для сборки не найден в папке движка"
    tail = (ensured.stderr or ensured.stdout).strip()[-300:]
    return f"{detail}\n{tail}" if tail else detail


def browser_install(node: str, prefix: Path, pin: dict, *, install_missing: bool, update: bool,
                    runner=None) -> dict:
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
    is_file = bool(path) and Path(path).is_file()
    if ensured.code != 0 or located.code != 0 or not inside or not is_file:
        return item("failed", _failure_detail(ensured, located, path, inside=inside, is_file=is_file))
    record.update(browser=path, version=pin["version"], node=node,
                  updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    engine.write_record(prefix, record)
    return item("installed", "скачан браузер для сборки видео (~100 МБ)", path=path)


def check_browser(prefix: Path, pin: dict) -> dict:
    record = engine.read_record(prefix)
    if record.get("version") == pin["version"] and record.get("browser") \
            and Path(record["browser"]).is_file():
        return item("found", path=record["browser"])
    return item("missing", "скачается при install.py --install-deps")

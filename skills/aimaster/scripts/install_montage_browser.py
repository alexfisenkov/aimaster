#!/usr/bin/env python3
"""Браузер для сборки видео — часть установщика монтажа (install_montage.py).
Качает его сам HyperFrames (`browser ensure`) в HOME движка; путь пишется в
aimaster-engine.json — иначе `browser path` молча отдал бы системный Chrome.

Тот же принцип, что у install_montage_engine.engine_install: ничего не скачано —
качает только с `install_missing` (--install-deps); скачан, но для другой
версии pin — чинят `install_missing` ИЛИ `update` (--update); --update один на
пустом месте ничего не качает (правило владельца 2026-09-25, разбор 1/5).

Звать только с найденным Node.js 22+ и HyperFrames закреплённой версии —
это проверяет install_montage.montage_report (разбор 4/5, находка 1).

Браузер — только скачанный chrome-headless-shell в HOME движка, записанный в
aimaster-engine.json; HYPERFRAMES_BROWSER_PATH человека не читается и в
запуски движка не наследуется (round 4/5): иначе установщик говорил бы
«найден», а engine.locate — «не скачан», и автопилот крутил бы установку."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS), str(_SCRIPTS.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install_montage_browser_win  # noqa: E402
from install_montage_node import item  # noqa: E402
from studio.montage import engine  # noqa: E402
from studio.montage.engine_cli import run_engine  # noqa: E402
from studio.platform_compat import IS_WINDOWS  # noqa: E402

# При отказе браузера HyperFrames советует HYPERFRAMES_BROWSER_PATH и `npx … browser
# ensure --force` — у нас нет ни того, ни другого: показываем свою команду.
_MISLEADING_HINT = ("Select a working Chrome/Chromium binary for this OS and architecture with "
                    "HYPERFRAMES_BROWSER_PATH, or reinstall with: npx hyperframes browser ensure --force")
_HINT_FIX = "переустановите браузер движка: install.py --install-deps"


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
        # Путь пишем как есть (не repr): на Windows repr() удваивает «\» и
        # ассертам/логам, читающим сообщение как обычный текст, только мешает.
        reasons.append(f"путь вне папки движка: {path}")
    elif not is_file:
        reasons.append(f"файла нет на диске: {path}")
    detail = "; ".join(reasons) or "после загрузки браузер для сборки не найден в папке движка"
    tail = (ensured.stderr or ensured.stdout).replace(_MISLEADING_HINT, _HINT_FIX).strip()[-300:]
    return f"{detail}\n{tail}" if tail else detail


def _locate_after_ensure(eng, prefix: Path, pin: dict, kwargs: dict):
    """`browser path` после уже отработавшего `ensure` — резолвит путь и
    проверяет, что он внутри папки движка и существует на диске."""

    located = run_engine(eng, ["browser", "path"], cwd=prefix, timeout=pin["timeouts"]["cli"], **kwargs)
    lines = located.stdout.strip().splitlines()
    path = lines[-1].strip() if lines else ""
    inside = bool(path) and engine.browser_inside_home(path, prefix)
    is_file = bool(path) and inside and Path(path).is_file()
    return located, path, inside, is_file


def _preseed_on_windows(prefix: Path, budget: float) -> tuple[str, float]:
    """round 2/5 (run 36141827389): у не-ASCII префикса штатная распаковка
    оставляет пустую папку — качаем сами (install_montage_browser_win). Не
    вышло — продолжаем обычным `ensure`, причину сохраняем. Возвращает
    (причина, таймаут `ensure`): бюджет общий на оба шага — расчёт в
    install_montage_browser_win (download_deadline, ensure_timeout)."""

    win = install_montage_browser_win
    started = time.monotonic()
    result = win.preseed(prefix, deadline=win.download_deadline(budget))
    spent = time.monotonic() - started
    return ("" if result.ok else result.reason), win.ensure_timeout(budget, spent)


def browser_install(node: str, prefix: Path, pin: dict, *, install_missing: bool, update: bool,
                    runner=None) -> dict:
    record = engine.read_record(prefix)
    have_browser = engine.recorded_browser(prefix) is not None
    if have_browser and record.get("version") == pin["version"]:
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
    budget = pin["timeouts"]["browser"]
    preseed_reason, ensure_timeout = _preseed_on_windows(prefix, budget) if IS_WINDOWS else ("", budget)
    also = f"\nсвой скачиватель тоже не справился: {preseed_reason}" if preseed_reason else ""
    ensured = run_engine(eng, ["browser", "ensure"], cwd=prefix, timeout=ensure_timeout, **kwargs)
    if ensured.timed_out:
        return item("timeout", "браузер для сборки не скачался за отведённое время; повторите позже" + also)
    located, path, inside, is_file = _locate_after_ensure(eng, prefix, pin, kwargs)
    if ensured.code != 0 or located.code != 0 or not inside or not is_file:
        return item("failed", _failure_detail(ensured, located, path, inside=inside, is_file=is_file) + also)
    record.update(browser=path, version=pin["version"], node=node,
                  updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    engine.write_record(prefix, record)
    return item("installed", "скачан браузер для сборки видео (~100 МБ)", path=path)


def check_browser(prefix: Path, pin: dict) -> dict:
    """Та же проверка, что у engine.locate() — оба согласны (round 4/5)."""

    browser = engine.recorded_browser(prefix, version=pin["version"])
    if browser is not None:
        return item("found", path=browser)
    return item("missing", "скачается при install.py --install-deps")

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

import os
import sys
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

# HyperFrames сам подсказывает при отказе браузера «HYPERFRAMES_BROWSER_PATH
# → chrome.exe» — на Windows это неверный совет (round 2/5, H2: обычный
# Chrome не отвечает на --version и не годится для рендера, run 36141827389).
# Не показываем человеку чужую подсказку, которая заведёт его не туда.
_MISLEADING_HINT = ("Select a working Chrome/Chromium binary for this OS and architecture with "
                    "HYPERFRAMES_BROWSER_PATH, or reinstall with: npx hyperframes browser ensure --force")
_HINT_FIX = ("переустановите движок (install.py --install-deps) — chrome-headless-shell скачается "
            "и распакуется заново; обычный Chrome для рендера на Windows не годится (H2)")


def _scrub_windows_hint(text: str) -> str:
    return text.replace(_MISLEADING_HINT, _HINT_FIX) if IS_WINDOWS else text


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
    tail = _scrub_windows_hint((ensured.stderr or ensured.stdout).strip()[-300:])
    return f"{detail}\n{tail}" if tail else detail


def _env_browser_override(environ):
    """Явное `HYPERFRAMES_BROWSER_PATH` — механизм самого HyperFrames. На
    Windows обычный (не headless-shell) браузер отклоняем: H2 прямым замером
    показал, что `chrome.exe --version` не отвечает и не завершается (run
    36141827389) — молча принять такой путь означало бы тот же тупик.

    (путь, None) — пригоден; (None, причина) — явно непригоден; (None, None)
    — не задан или файла нет (не override). round 3/5: вызывающий код НЕ
    пишет путь в aimaster-engine.json — исчезнувшая переменная не должна
    оставить устаревшую запись «найден»."""

    path = (environ or os.environ).get("HYPERFRAMES_BROWSER_PATH")
    if not path or not Path(path).is_file():
        return None, None
    if IS_WINDOWS and Path(path).name.lower() != "chrome-headless-shell.exe":
        return None, (f"HYPERFRAMES_BROWSER_PATH указывает на {path} — не chrome-headless-shell.exe. "
                      "На Windows обычный Chrome/Edge/Firefox не отвечает на проверку версии и не "
                      "годится для рендера HyperFrames (round 2/5, H2, run 36141827389) — укажите "
                      "путь к chrome-headless-shell.exe или не задавайте переменную вовсе.")
    return path, None


def _locate_after_ensure(eng, prefix: Path, pin: dict, kwargs: dict):
    """`browser path` после уже отработавшего `ensure` — резолвит путь и
    проверяет, что он внутри папки движка и существует на диске."""

    located = run_engine(eng, ["browser", "path"], cwd=prefix, timeout=pin["timeouts"]["cli"], **kwargs)
    lines = located.stdout.strip().splitlines()
    path = lines[-1].strip() if lines else ""
    inside = bool(path) and engine.browser_inside_home(path, prefix)
    is_file = bool(path) and inside and Path(path).is_file()
    return located, path, inside, is_file


def browser_install(node: str, prefix: Path, pin: dict, *, install_missing: bool, update: bool,
                    runner=None, environ=None) -> dict:
    override, override_error = _env_browser_override(environ)
    if override_error:
        return item("failed", override_error)
    if override:
        return item("found", "браузер задан через HYPERFRAMES_BROWSER_PATH — скачивание пропущено",
                    path=override)
    record = engine.read_record(prefix)
    have_browser = (bool(record.get("browser")) and Path(record["browser"]).is_file()
                    and engine.browser_inside_home(record["browser"], prefix))
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
    preseed_reason = ""
    if IS_WINDOWS:
        # round 2/5, H1 подтверждён CI-экспериментом (run 36141827389):
        # не-ASCII путь назначения оставляет пустую версийную папку у
        # штатной распаковки @puppeteer/browsers — качаем и распаковываем
        # сами (install_montage_browser_win.py, round 3/5: атомарно). Не
        # вышло — не беда, продолжаем обычным `ensure`, как раньше; причину
        # сохраняем на случай, если и он не справится.
        result = install_montage_browser_win.preseed(prefix, timeout=pin["timeouts"]["browser"])
        if not result.ok:
            preseed_reason = result.reason
    ensured = run_engine(eng, ["browser", "ensure"], cwd=prefix,
                         timeout=pin["timeouts"]["browser"], **kwargs)
    if ensured.timed_out:
        return item("timeout", "браузер для сборки не скачался за отведённое время; повторите позже")
    located, path, inside, is_file = _locate_after_ensure(eng, prefix, pin, kwargs)
    if ensured.code != 0 or located.code != 0 or not inside or not is_file:
        detail = _failure_detail(ensured, located, path, inside=inside, is_file=is_file)
        if preseed_reason:
            detail = f"{detail}\nсвой скачиватель тоже не справился: {preseed_reason}"
        return item("failed", detail)
    record.update(browser=path, version=pin["version"], node=node,
                  updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    engine.write_record(prefix, record)
    return item("installed", "скачан браузер для сборки видео (~100 МБ)", path=path)


def check_browser(prefix: Path, pin: dict, *, environ=None) -> dict:
    override, override_error = _env_browser_override(environ)
    if override_error:
        return item("failed", override_error)
    if override:
        return item("found", path=override)
    record = engine.read_record(prefix)
    if (record.get("version") == pin["version"] and record.get("browser")
            and Path(record["browser"]).is_file()
            and engine.browser_inside_home(record["browser"], prefix)):
        return item("found", path=record["browser"])
    return item("missing", "скачается при install.py --install-deps")

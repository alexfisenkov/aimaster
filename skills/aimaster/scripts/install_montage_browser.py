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
import time
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

# round 1/5, находка CI windows-latest: два отдельных процесса Node (`ensure`
# своим «Path: …», затем `browser path` своим `existsSync`) согласились, что
# файл на диске есть — Python в третьем процессе тут же получил на ТОТ ЖЕ
# путь `Path.is_file() is False` (OSError внутри pathlib проглочен). Классика
# антивируса на Windows: Defender ставит только что скачанный .exe (~30+ МБ,
# без подписи) на реал-тайм проверку и на секунду-другую держит хэндл. Опрос
# с паузой вместо одного взгляда — не бесконечный, ограниченный.
IS_FILE_ATTEMPTS = 10
IS_FILE_DELAY = 0.5


def _wait_until_file(path: str, *, attempts=IS_FILE_ATTEMPTS, delay=IS_FILE_DELAY, sleep=time.sleep) -> bool:
    for attempt in range(attempts):
        if Path(path).is_file():
            return True
        if attempt < attempts - 1:
            sleep(delay)
    return False


def _walk_up_diagnostic(path: str) -> str:
    """Защита от антивируса (ci.yml) не решила находку CI windows-latest до
    конца — сам родитель файла тоже «не читается» (WinError 3, путь не
    существует). Идём от файла вверх, пока не найдём первый СУЩЕСТВУЮЩИЙ
    уровень — показывает, на чём именно расходится путь, который назвал
    Node, с тем, что реально есть на диске, вместо одной строки без опоры."""

    current = Path(path)
    missing = []
    while True:
        if current.exists():
            try:
                names = sorted(entry.name for entry in current.iterdir())
            except OSError as error:
                return f"первый существующий уровень {current} не читается: {error}"
            return (f"первый существующий уровень: {current} (внутри: {names}); "
                    f"не существуют вложенные {list(reversed(missing))}")
        missing.append(current.name)
        parent = current.parent
        if parent == current:  # дошли до корня диска — дальше подниматься некуда
            return f"ни один уровень пути не существует, дошли до {current}"
        current = parent


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
        # ассертам/логам, читающим сообщение как обычный текст, только мешает
        # (round 1/5: `!r` тут же сломал собственный юнит-тест на Windows).
        reasons.append(f"путь вне папки движка: {path}")
    elif not is_file:
        reasons.append(f"файла нет на диске за {IS_FILE_ATTEMPTS} попыток по {IS_FILE_DELAY} с: {path}"
                       f" | сырой вывод path: {located.stdout!r}"
                       f" | {_walk_up_diagnostic(path)}")
    detail = "; ".join(reasons) or "после загрузки браузер для сборки не найден в папке движка"
    tail = (ensured.stderr or ensured.stdout).strip()[-300:]
    return f"{detail}\n{tail}" if tail else detail


def _locate_after_ensure(eng, prefix: Path, pin: dict, kwargs: dict, sleep):
    """`browser path` после уже отработавшего `ensure` — резолвит путь,
    проверяет, что он внутри папки движка, и ждёт файл на диске (с retry)."""

    located = run_engine(eng, ["browser", "path"], cwd=prefix, timeout=pin["timeouts"]["cli"], **kwargs)
    lines = located.stdout.strip().splitlines()
    path = lines[-1].strip() if lines else ""
    inside = bool(path) and install._inside(path, str(Path(prefix) / "home"))
    is_file = bool(path) and inside and _wait_until_file(path, sleep=sleep)
    return located, path, inside, is_file


def browser_install(node: str, prefix: Path, pin: dict, *, install_missing: bool, update: bool,
                    runner=None, sleep=time.sleep) -> dict:
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
    located, path, inside, is_file = _locate_after_ensure(eng, prefix, pin, kwargs, sleep)
    if ensured.code == 0 and located.code == 0 and inside and not is_file:
        # round 1/5, CI windows-latest (runs 36133902583, 36134495655): `ensure`
        # отчитался кодом 0 и своей строкой «Path: …», отдельный `browser path`
        # согласился с тем же путём — а на диске оказалась пустая папка нужной
        # версии (└ вложенный chrome-headless-shell-win64/…exe вообще не
        # появился). Ни _wait_until_file (истёк тем же результатом), ни
        # исключение из Windows Defender в ci.yml это не поправили — похоже на
        # незавершённую/битую распаковку архива, а не на замок или карантин.
        # Один принудительный перекач с нуля («ensure --force» чистит кэш и
        # качает заново) — до того, как сдаться финально.
        ensured = run_engine(eng, ["browser", "ensure", "--force"], cwd=prefix,
                             timeout=pin["timeouts"]["browser"], **kwargs)
        if ensured.timed_out:
            return item("timeout", "браузер для сборки не скачался за отведённое время; повторите позже")
        located, path, inside, is_file = _locate_after_ensure(eng, prefix, pin, kwargs, sleep)
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

"""GSAP закреплённой версии из установленного движка → current/assets/.

Черновик несёт локальный GSAP ради звука на монтажном столе (задача 10b):
у композиции без таймлайна Studio 0.8.75 после правки берёт плеер с длиной 0
и переходит на воспроизведение перемоткой, без звука — «Audio will not play
in preview». Таймлайн на паузе длиной во весь ролик (draft_html) этого не
допускает, а для него нужен GSAP.

Файлы — из `<prefix>/node_modules/gsap/dist` (ставит установщик рядом с
движком, версия — engine.json → gsap_version, сверяется по package.json
пакета); в композиции ссылка только локальная, внешний скрипт — ошибка
проверки сборки. MotionPathPlugin — тоже локально: если на странице есть GSAP,
а плагина нет, Studio при каждой загрузке превью сама тянет его с jsDelivr.
Лицензия GSAP — стандартная бесплатная (gsap.com/standard-license); файлы не
меняем. `montage gsap` (`vendor_gsap`) кладёт сюда же плагины по запросу.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from ..platform_compat import replace_file
from . import MontageError
from .composition_refs import references
from .draft_html import script_tag
from .engine import Engine, install_command, load_pin, package_version
from .index_io import read_index
from .media_sync import ASSETS_DIR
from .paths import MontagePaths
from .replace_target import make_replaceable, regular_stat

DRAFT_SCRIPTS = ("gsap", "MotionPathPlugin")
_PLUGIN = re.compile(r"[A-Z][A-Za-z0-9]{1,40}")
# Правила для агента, который добавляет анимации из скиллов HyperFrames.
RULES = (
    "GSAP и плагины — только локальные файлы из assets/: недостающие теги (missing_tags) — "
    "в <head> после assets/gsap.min.js; ссылку на CDN проверка сборки отклонит",
    'анимации — в уже существующий скрипт таймлайна черновика (window.__timelines["main"]): '
    'второй таймлайн "main" и второй встроенный скрипт GSAP не заводить — превью Studio '
    "после правки перезагружается только с одним",
    "таймлайн остаётся на паузе (gsap.timeline({ paused: true })) и не короче ролика",
    "у корня #root не ставить data-no-timeline — иначе превью Studio играет без звука",
    "текст — только шрифтом «AM Inter»",
)


def gsap_dist(prefix: Path) -> Path:
    return Path(prefix) / "node_modules" / "gsap" / "dist"


def gsap_sources(prefix: Path, names=DRAFT_SCRIPTS) -> list[Path]:
    """Файлы `<имя>.min.js` закреплённой версии GSAP в папке движка; нет
    пакета, не та версия или нет файла — MontageError с командой установки.
    Ничего не пишет: черновик зовёт её до первой записи в current/."""

    wanted, found = load_pin()["gsap_version"], package_version(prefix, "gsap")
    if found != wanted:
        have = f"стоит {found}" if found else "не установлен"
        raise MontageError(f"Монтажный движок не готов: GSAP {wanted} для черновика {have} "
                           f"в папке движка. Поставьте его командой: {install_command()}")
    sources = [gsap_dist(prefix) / f"{name}.min.js" for name in names]
    missing = [source.name for source in sources if not source.is_file()]
    if missing:
        raise MontageError(f"Монтажный движок не готов: в GSAP движка нет {', '.join(missing)}. "
                           f"Поставьте его командой: {install_command()}")
    return sources


def _copy_if_changed(source: Path, target: Path) -> bool:
    """Копия через временный файл mkstemp рядом с целью (не фиксированное имя:
    два параллельных вызова не пишут в один .part) и атомарную замену. Цель
    сравнивается, только если это обычный файл: симлинк (хоть на тот же GSAP)
    заменяется своим файлом, не читается и не меняется (`replace_target`)."""

    temporary = None
    try:
        data = source.read_bytes()
        if regular_stat(target) is not None and target.read_bytes() == data:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".part")
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.chmod(temporary, 0o644)  # mkstemp даёт 0600; скрипт монтажа читают Studio и рендер
        make_replaceable(target)
        replace_file(temporary, target)
    except OSError as error:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # чистка — best effort, не подменяет исходную ошибку
        raise MontageError(f"не удалось положить {source.name} в assets монтажа") from error
    return True


def copy_gsap(prefix: Path, assets_dir: Path, names=DRAFT_SCRIPTS) -> list[str]:
    """Копирует GSAP (и плагины `names`) в `assets_dir`, если там не тот же
    файл; возвращает локальные ссылки для `<script src>` в порядке `names`."""

    sources = gsap_sources(prefix, names)
    for source in sources:
        _copy_if_changed(source, Path(assets_dir) / source.name)
    return [f"{ASSETS_DIR}/{source.name}" for source in sources]


def vendor_gsap(engine: Engine, paths: MontagePaths, *, plugins=()) -> dict:
    """`montage gsap`: GSAP черновика и плагины `plugins` (имя — как у файла
    в dist, например SplitText) → current/assets/. `script_tags` — все теги
    по порядку загрузки, `missing_tags` — каких ещё нет в index.html."""

    gsap_sources(engine.prefix)  # закреплённый GSAP стоит — иначе отказ с командой установки
    if not paths.index.is_file():
        raise MontageError("черновика ещё нет: сначала montage draft")
    names, dist = list(DRAFT_SCRIPTS), gsap_dist(engine.prefix)
    for plugin in plugins:
        if not _PLUGIN.fullmatch(str(plugin)) or not (dist / f"{plugin}.min.js").is_file():
            raise MontageError(f"нет плагина GSAP «{plugin}» в движке "
                               "(имя — как у файла в gsap/dist, например SplitText)")
        if plugin not in names:
            names.append(plugin)
    files, copied = [], []
    for source in gsap_sources(engine.prefix, names):
        rel = f"{ASSETS_DIR}/{source.name}"
        if _copy_if_changed(source, paths.assets / source.name):
            copied.append(rel)
        files.append(rel)
    present = set(references(read_index(paths.index)))
    return {"version": package_version(engine.prefix, "gsap"), "files": files, "copied": copied,
            "script_tags": [script_tag(rel) for rel in files],
            "missing_tags": [script_tag(rel) for rel in files if rel not in present],
            "rules": list(RULES)}

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
меняем. Задача 17 (`montage gsap`) расширяет этот модуль, а не дублирует.
"""

from __future__ import annotations

from pathlib import Path

from ..platform_compat import replace_file
from . import MontageError
from .engine import install_command, load_pin, package_version
from .media_sync import ASSETS_DIR

DRAFT_SCRIPTS = ("gsap", "MotionPathPlugin")


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
                           f"в {prefix}. Поставьте его командой: {install_command()}")
    sources = [gsap_dist(prefix) / f"{name}.min.js" for name in names]
    missing = [source.name for source in sources if not source.is_file()]
    if missing:
        raise MontageError(f"Монтажный движок не готов: в {gsap_dist(prefix)} нет "
                           f"{', '.join(missing)}. Поставьте его командой: {install_command()}")
    return sources


def _copy_if_changed(source: Path, target: Path) -> bool:
    temporary = target.with_name(f".{target.name}.part")
    try:
        data = source.read_bytes()
        if target.is_file() and target.read_bytes() == data:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(data)
        replace_file(temporary, target)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass  # чистка — best effort, не подменяет исходную ошибку
        raise MontageError(f"не удалось положить {source.name} в assets: {error}") from error
    return True


def copy_gsap(prefix: Path, assets_dir: Path, names=DRAFT_SCRIPTS) -> list[str]:
    """Копирует GSAP (и плагины `names`) в `assets_dir`, если там не тот же
    файл; возвращает локальные ссылки для `<script src>` в порядке `names`."""

    sources = gsap_sources(prefix, names)
    for source in sources:
        _copy_if_changed(source, Path(assets_dir) / source.name)
    return [f"{ASSETS_DIR}/{source.name}" for source in sources]

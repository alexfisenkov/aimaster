"""Медиа композиции и её ссылки.

Файлы из <workspace>/media попадают в current/assets жёсткой ссылкой (тот же
файл, место на диске не тратится), а если ссылка невозможна (другой диск,
файловая система без ссылок) — копией. Симлинки не используются: на Windows
они требуют прав. Имя в assets — id ассета: уникально и не меняется.

Проверка внешних ссылок делегирует `external_urls.external_urls`/`is_external`
— тот же разбор HTML/CSS (все виды кавычек, srcset, url(), @import,
image-set), что и у `scripts/montage_ci_check.py`; второй параллельный
сканер здесь не заводим. Список путей *внутри* монтажа (для проверки «файла
нет» и «ссылка вне папки») этим модулем не покрыт — `external_urls`
намеренно отбрасывает локальные ссылки, поэтому здесь свой лёгкий разбор
HTML (тоже через HTMLParser) плюс лексическая проверка выхода за current/:
диск Windows (`C:…`), абсолютный путь (`/…`, `\…`) или `..` — без опоры на
то, как их поймёт файловая система текущего хоста.
"""

from __future__ import annotations

import os
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Iterable

from ..platform_compat import replace_file
from . import MontageError
from .external_urls import external_urls, is_external

ASSETS_DIR = "assets"
_URL_ATTRS = frozenset({"src", "href", "poster", "data-src"})
_CSS_URL = re.compile(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)|@import\s+(['\"])([^'\"]+)\3", re.I)
# Диск Windows ("C:", "D:a.mp4") синтаксически похож на схему URL, но
# `external_urls._EXTERNAL` (и его is_external) уже отличает их — там схема
# от одной буквы не считается. Свою «похожую» проверку здесь не заводим.
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def asset_filename(asset_id: str, source: Path) -> str:
    return f"{asset_id}{Path(source).suffix.lower()}"


def link_or_copy(source: Path, target: Path) -> str:
    """'link' | 'copy' | 'exists'. Другой файл с тем же именем — отказ."""

    source, target = Path(source), Path(target)
    if not source.is_file():
        raise MontageError(f"источника для монтажа нет: {source}")
    if target.exists():
        try:
            same = (os.path.samefile(source, target)
                    or target.stat().st_size == source.stat().st_size)
        except OSError as error:
            raise MontageError(f"не удалось проверить {target.name} в assets: {error}") from error
        if same:
            return "exists"
        raise MontageError(f"в assets уже лежит другой файл {target.name}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise MontageError(f"не удалось создать папку {target.parent}: {error}") from error
    try:
        os.link(source, target)
        return "link"
    except OSError:
        pass
    temporary = target.with_name(f".{target.name}.part")
    try:
        shutil.copy2(source, temporary)
        replace_file(temporary, target)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise MontageError(f"не удалось скопировать {source.name} в assets: {error}") from error
    return "copy"


def sync_media(items: Iterable[tuple[str, Path]], assets_dir: Path) -> dict[str, dict]:
    """{asset_id: {"src": "assets/<файл>", "method": link|copy|exists}}."""

    result: dict[str, dict] = {}
    for asset_id, source in items:
        if asset_id in result:
            continue
        name = asset_filename(asset_id, source)
        method = link_or_copy(Path(source), Path(assets_dir) / name)
        result[asset_id] = {"src": f"{ASSETS_DIR}/{name}", "method": method}
    return result


def _css_urls(css: str) -> list[str]:
    return [(match.group(2) or match.group(4) or "").strip() for match in _CSS_URL.finditer(css)]


class _Refs(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            name = name.lower()
            if name in _URL_ATTRS and value:
                self.refs.append(value.strip())
            elif name == "srcset" and value:
                self.refs.extend(part.split()[0] for part in value.split(",") if part.strip())
            elif name == "style" and value:
                self.refs.extend(_css_urls(value))
        self._in_style = tag == "style"

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.refs.extend(_css_urls(data))


def references(html_text: str) -> list[str]:
    """Все локальные и внешние ссылки композиции (для missing_sources); порядок — как в документе."""

    parser = _Refs()
    parser.feed(html_text)
    parser.close()
    return [ref for ref in parser.refs if ref and not ref.startswith("#")]


def external_references(html_text: str) -> list[str]:
    """Всё со схемой или «//хост»; встроенные data: — не ссылка наружу.

    Делегирует общему сканеру `external_urls` (используется и CI-проверкой
    сборки), а не разбирает HTML/CSS заново."""

    return external_urls(html_text)


def _local_path(ref: str) -> str:
    """Ref без query/fragment, «\\» приведён к «/» — так «..\\media\\x» и
    «C:\\x» разбираются как путь, а не как одна причудливая часть имени
    (`PurePosixPath` иначе бэкслеш не считает разделителем)."""

    return ref.split("?", 1)[0].split("#", 1)[0].replace("\\", "/")


def _escapes_current(local: str) -> bool:
    if _DRIVE_PREFIX.match(local) or local.startswith("/"):
        return True
    return ".." in PurePosixPath(local).parts


def escaping_sources(html_text: str) -> list[str]:
    """Локальные ссылки, которые указывают вне current/: диск Windows
    (C:…/C:\\…/D:a.mp4), абсолютный путь (/…, \\…) или подъём через «..».
    Внешние (http:, data:) сюда не входят — у них external_references."""

    return [ref for ref in references(html_text)
            if not is_external(ref) and not ref.lower().startswith("data:")
            and _escapes_current(_local_path(ref))]


def missing_sources(html_text: str, current_dir: Path) -> list[str]:
    """Ссылки внутри current/, для которых нет файла. Ссылка, уходящая за
    пределы current/ (см. escaping_sources), сюда не попадает — у неё своё
    сообщение: «файла нет» и «ссылка вне папки» значат разное."""

    missing = []
    for ref in references(html_text):
        if is_external(ref) or ref.lower().startswith("data:"):
            continue
        local = _local_path(ref)
        if _escapes_current(local):
            continue
        if not (Path(current_dir) / PurePosixPath(local)).is_file():
            missing.append(ref)
    return missing


def check_composition(html_text: str, current_dir: Path) -> list[str]:
    """Что мешает собрать ролик без сети; пустой список — всё в порядке."""

    problems = [f"внешняя ссылка: {ref}" for ref in external_references(html_text)]
    problems += [f"ссылка вне папки монтажа: {ref}" for ref in escaping_sources(html_text)]
    problems += [f"файла нет в папке монтажа: {ref}"
                 for ref in missing_sources(html_text, current_dir)]
    return problems

"""Ссылки композиции: что уходит наружу и что уходит за пределы current/.

Проверка внешних ссылок делегирует `external_urls.external_urls`/`is_external`
— тот же разбор HTML/CSS (все виды кавычек, srcset, url(), @import,
image-set), что и у `scripts/montage_ci_check.py`; второй параллельный
сканер здесь не заводим. Список путей *внутри* монтажа (для проверки «файла
нет» и «ссылка вне папки») этим модулем не покрыт — `external_urls`
намеренно отбрасывает локальные ссылки, поэтому здесь свой лёгкий разбор
HTML (тоже через HTMLParser) плюс лексическая проверка выхода за current/:
диск Windows (`C:…`), абсолютный путь (`/…`, `\\…`) или подъём через `..` —
без опоры на то, как их поймёт файловая система текущего хоста. Процентная
запись (`%2e%2e/`) раскодируется перед этой проверкой — иначе она прячет
подъём от лексического разбора, хотя браузер её раскодирует и подставит.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from .external_urls import external_urls, is_external

_URL_ATTRS = frozenset({"src", "href", "poster", "data-src"})
_CSS_URL = re.compile(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)|@import\s+(['\"])([^'\"]+)\3", re.I)
# Диск Windows ("C:", "D:a.mp4") синтаксически похож на схему URL, но
# `external_urls._EXTERNAL` (и его is_external) уже отличает их — там схема
# от одной буквы не считается. Свою «похожую» проверку здесь не заводим.
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


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
    # unquote — «%2e%2e/» и «%5c» не должны обмануть лексическую проверку:
    # то, что реально откроет рендерер после раскодирования, и есть то, что
    # надо проверять, а не то, что написано буквально.
    decoded = unquote(local)
    if _DRIVE_PREFIX.match(decoded) or decoded.startswith("/"):
        return True
    return ".." in PurePosixPath(decoded).parts


def escaping_sources(html_text: str) -> list[str]:
    """Локальные ссылки, которые указывают вне current/: диск Windows
    (C:…/C:\\…/D:a.mp4), абсолютный путь (/…, \\…) или подъём через «..»
    (буквально или через %2e%2e). Внешние (http:, data:) сюда не входят —
    у них external_references."""

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

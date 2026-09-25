"""Папка движка на диске: где что лежит и что установщик уже записал.

`<prefix>/node_modules/…` — пакеты npm закреплённых версий, `<prefix>/home` —
HOME движка (кэши и скачанный chrome-headless-shell), `aimaster-engine.json` —
запись установщика с путём к этому браузеру. Запись — единственный источник
правды о браузере: переменную HYPERFRAMES_BROWSER_PATH из окружения человека
ни установщик, ни поиск движка не читают (round 4/5). Имена отсюда
переэкспортирует engine.py — снаружи их зовут как `engine.<имя>`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

RECORD_NAME = "aimaster-engine.json"


def entry_script(prefix: Path) -> Path:
    return Path(prefix) / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"


def package_version(prefix: Path, name: str) -> str | None:
    manifest = Path(prefix) / "node_modules" / name / "package.json"
    try:
        version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return version if isinstance(version, str) else None


def installed_version(prefix: Path) -> str | None:
    return package_version(prefix, "hyperframes")


def read_record(prefix: Path) -> dict:
    try:
        data = json.loads((Path(prefix) / RECORD_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_record(prefix: Path, record: dict) -> None:
    Path(prefix).mkdir(parents=True, exist_ok=True)
    (Path(prefix) / RECORD_NAME).write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def browser_inside_home(browser, prefix) -> bool:
    """`browser` реально лежит в HOME движка (`<prefix>/home`), а не осевший в
    записи чужой браузер (запись прошлых версий установщика, ручная правка).
    Одна проверка на всех: `engine.locate()`, `check_browser()` и
    `browser_install()` не расходятся в том, что считать готовым браузером.
    `normcase`+`realpath` раскрывают регистр и символьные ссылки, а не просто
    сравнивают текст пути."""

    home = Path(prefix) / "home"
    browser_norm = os.path.normcase(os.path.realpath(str(browser)))
    home_norm = os.path.normcase(os.path.realpath(str(home)))
    return browser_norm == home_norm or browser_norm.startswith(home_norm.rstrip(os.sep) + os.sep)


def recorded_browser(prefix: Path, *, version: str | None = None) -> str | None:
    """Браузер из записи, если он годится: строка, файл на диске, внутри HOME
    движка и (если задана `version`) записан для этой версии HyperFrames."""

    record = read_record(prefix)
    browser = record.get("browser")
    if not isinstance(browser, str) or not browser or not Path(browser).is_file():
        return None
    if not browser_inside_home(browser, prefix):
        return None
    if version is not None and record.get("version") != version:
        return None
    return browser

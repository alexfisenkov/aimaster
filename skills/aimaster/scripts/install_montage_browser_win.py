#!/usr/bin/env python3
"""chrome-headless-shell для Windows в обход штатной распаковки @puppeteer/browsers.

Доказано CI-экспериментом round 2/5 (run 36141827389, джобы `H1 experiment ·
ascii` / `· cyrillic` в одном пуше): не-ASCII путь назначения («AI
Мастерская» — дефолтная папка движка) оставляет у штатного распаковщика
@puppeteer/browsers пустую версийную папку; тот же .zip на ASCII-пути рядом
распаковался целиком. Почему — не установлено; установлен только этот факт.

Поэтому качаем и распаковываем сами: URL и раскладка кэша — из исходников
@puppeteer/browsers (`DefaultProvider.js`, `Cache.js` — браузер находится
сканированием каталогов), версия — из `cli.js` закреплённого HyperFrames,
распаковка — `zipfile`; что он справляется с таким путём, показал зелёный
run 36143116532 на дефолтном кириллическом префиксе. Итоговая папка
появляется только целиком (временная папка рядом, проверка .exe, одно
переименование); `preseed()` не бросает исключений — отказ идёт причиной.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS.parent), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from install_montage_download import READ_TIMEOUT, download  # noqa: E402
from studio.montage.temp_sweep import sweep_stale  # noqa: E402
from studio.platform_compat import replace_file  # noqa: E402

BASE_URL = "https://storage.googleapis.com/chrome-for-testing-public"
EXE_RELATIVE = Path("chrome-headless-shell-win64") / "chrome-headless-shell.exe"
# Вид имени, который studio/montage/temp_sweep.py подметает у оборванных попыток.
EXTRACT_TEMP_PREFIX = ".aimaster-tmp-extract-"
# Антивирус может ненадолго держать свежераспакованные файлы: переименование
# повторяем на PermissionError (только Windows), всего RENAME_ATTEMPTS раз.
RENAME_ATTEMPTS, RENAME_DELAY = 10, 0.5
# Бюджет шага браузера на Windows (round 4/5) — timeouts.browser (B = 900 с) на
# preseed и `ensure` вместе. Скачивание обрывается на B − RESERVE (плюс не
# больше одного чтения сокета, READ_TIMEOUT); `ensure` получает остаток B, но
# не меньше ENSURE_MIN. Итого ≤ B, пока распаковка на диске укладывается в
# RESERVE − READ_TIMEOUT − ENSURE_MIN = 60 с; дольше — B плюс этот излишек.
ENSURE_MIN = 120
RESERVE = READ_TIMEOUT + 60 + ENSURE_MIN
# (?<!\w): не хвост `MACOS_12_CHROME_VERSION` (round 3/5).
_CHROME_VERSION_RE = re.compile(r'(?<!\w)CHROME_VERSION\s*=\s*"([0-9]+(?:\.[0-9]+){2,3})"')


@dataclass(frozen=True)
class PreseedResult:
    ok: bool
    reason: str = ""


def download_deadline(budget: float) -> float:
    return max(budget - RESERVE, READ_TIMEOUT)


def ensure_timeout(budget: float, preseed_seconds: float) -> float:
    return max(budget - preseed_seconds, ENSURE_MIN)


def pinned_chrome_headless_shell_version(prefix: Path) -> str | None:
    cli_js = Path(prefix) / "node_modules" / "hyperframes" / "dist" / "cli.js"
    try:
        text = cli_js.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = _CHROME_VERSION_RE.search(text)
    return match.group(1) if match else None


def cache_target(prefix: Path, version: str) -> Path:
    """Где `Cache.js::getInstalledBrowsers()` ищет браузер в HOME движка."""
    return (Path(prefix) / "home" / ".cache" / "hyperframes" / "chrome"
            / "chrome-headless-shell" / f"win64-{version}")


def executable_path(prefix: Path, version: str) -> Path:
    return cache_target(prefix, version) / EXE_RELATIVE


def _extract(zip_path: Path, dest: Path) -> str:
    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(dest)
    except (zipfile.BadZipFile, zlib.error, EOFError, ValueError, OSError) as error:
        return f"chrome-headless-shell.zip повреждён или не распаковался: {error}"
    return "" if (dest / EXE_RELATIVE).is_file() else f"после распаковки не нашёлся {EXE_RELATIVE.name}"


def _rename(source: Path, target: Path) -> None:
    replace_file(source, target, attempts=RENAME_ATTEMPTS, delay=RENAME_DELAY)


def _move_into_place(fresh: Path, final_dir: Path, aside: Path) -> PreseedResult:
    """Готовый браузер параллельной установки не трогаем — проверяем до и
    после переноса. Протухшая папка без .exe уходит в сторону целиком (в
    рабочую папку, её убирает preseed), свежая встаёт одним переименованием:
    наполовину удалённой или распакованной папки на итоговом пути не бывает."""

    exe = final_dir / EXE_RELATIVE
    if exe.is_file():
        return PreseedResult(True)
    try:
        if final_dir.exists():
            _rename(final_dir, aside)
        _rename(fresh, final_dir)
    except OSError as error:
        return (PreseedResult(True) if exe.is_file() else
                PreseedResult(False, f"не удалось поставить браузер на место {final_dir.name}: {error}"))
    return PreseedResult(True) if exe.is_file() else PreseedResult(False, "файла нет на месте после переноса")


def preseed(prefix: Path, *, deadline: float = 900 - RESERVE, opener=urllib.request.urlopen,
            clock=time.monotonic) -> PreseedResult:
    """`deadline` — срок скачивания; вызывающий передаёт download_deadline(B)."""
    version = pinned_chrome_headless_shell_version(prefix)
    if not version:
        return PreseedResult(False, "версия chrome-headless-shell не прочиталась из cli.js HyperFrames")
    final_dir = cache_target(prefix, version)
    sweep_stale(final_dir.parent, EXTRACT_TEMP_PREFIX)  # и при уже готовом браузере
    if executable_path(prefix, version).is_file():
        return PreseedResult(True)
    try:
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=EXTRACT_TEMP_PREFIX, dir=str(final_dir.parent)))
    except OSError as error:
        return PreseedResult(False, f"не удалось создать папку кэша браузера: {error}")
    try:
        archive = work / "chrome-headless-shell-win64.zip"
        reason = download(f"{BASE_URL}/{version}/win64/{archive.name}", archive, deadline=deadline,
                          opener=opener, clock=clock)
        if reason:
            return PreseedResult(False, f"chrome-headless-shell напрямую {reason}")
        reason = _extract(archive, work / "extracted")
        if reason:
            return PreseedResult(False, reason)
        return _move_into_place(work / "extracted", final_dir, work / "stale")
    finally:
        shutil.rmtree(work, ignore_errors=True)

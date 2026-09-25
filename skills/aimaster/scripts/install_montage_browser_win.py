#!/usr/bin/env python3
"""chrome-headless-shell для Windows в обход битой распаковки @puppeteer/browsers.

round 2/5, H1 подтверждён прямым CI-экспериментом (владелец, 2026-09-25,
run 36141827389, джобы `H1 experiment · ascii` / `· cyrillic` в одном пуше):
не-ASCII путь назначения («AI Мастерская» — реальный путь движка) даёт
пустую версийную папку у штатного `@puppeteer/browsers`' `extractZipWithCli`
на win32 (`%SystemRoot%\\System32\\tar.exe`, при неудаче `powershell.exe
Expand-Archive`) — тот же .zip, тот же код, тот же ASCII-путь рядом отработал
целиком. Причина внутри `tar.exe` не установлена (закрытый бинарник) — важен
только доказанный факт: не-ASCII назначение → пустая папка у чужого
распаковщика.

Качаем и распаковываем chrome-headless-shell сами: URL и точная структура
кэша — из исходников @puppeteer/browsers (`DefaultProvider.js`,
`browser-data/chrome-headless-shell.js`, `Cache.js`), версия — из уже
собранного `cli.js` закреплённого HyperFrames (сама студия её не хранит —
не дублируем руками, значение меняется вместе с пином HyperFrames).
`zipfile` — из стандартной библиотеки Python, Unicode-safe на Windows:
CPython обращается к широким (`W`) Win32-вызовам, а не к узкому `main()`.
`Cache.js::getInstalledBrowsers()` — чистое сканирование каталогов вида
`<кэш>/<браузер>/<платформа>-<версия>/…`, файл `.metadata` не обязателен —
штатный `browser ensure` находит уже готовый браузер и не перекачивает его
заново.

round 3/5: атомарность (распаковка — во временную папку рядом с целью,
подтверждение .exe, затем `os.replace` на место) — HyperFrames и
@puppeteer/browsers доверяют «папка есть + .exe внутри есть» без сверки
контрольной суммы; наполовину распакованная папка на конечном пути не
должна существовать никогда, иначе следующий `browser ensure` примет её за
готовую. `preseed()` не бросает исключений ни при каких сетевых, файловых
и архивных сбоях — возвращает причину отказа, а не проглатывает её в
одном `print`."""

from __future__ import annotations

import http.client
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from install_montage_fetch import ssl_context  # noqa: E402
from studio.montage.temp_sweep import sweep_stale  # noqa: E402

BASE_URL = "https://storage.googleapis.com/chrome-for-testing-public"
DEFAULT_DOWNLOAD_TIMEOUT = 180
# общая уборка оборванных прошлых попыток с install_montage_fetch.py —
# studio/montage/temp_sweep.py узнаёт свои папки по этому же виду имени.
EXTRACT_TEMP_PREFIX = ".aimaster-tmp-extract-"
# (?<!\w) — не часть более длинного идентификатора: без этого якоря
# `MACOS_12_CHROME_VERSION = "150.…"` тоже совпадает (это подстрока), и
# при другом порядке объявлений в минификации можно было бы прочитать не
# ту версию (round 3/5, Minor).
_CHROME_VERSION_RE = re.compile(r'(?<!\w)CHROME_VERSION\s*=\s*"([0-9]+(?:\.[0-9]+){2,3})"')


@dataclass(frozen=True)
class PreseedResult:
    ok: bool
    reason: str = ""


def pinned_chrome_headless_shell_version(prefix: Path) -> str | None:
    """Версия зашита в собранном `cli.js` самого HyperFrames — читаем оттуда,
    а не задаём отдельной константой: значение переезжает вместе с пином
    HyperFrames в engine.json, а этот файл про него ничего не знает."""

    cli_js = Path(prefix) / "node_modules" / "hyperframes" / "dist" / "cli.js"
    try:
        text = cli_js.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = _CHROME_VERSION_RE.search(text)
    return match.group(1) if match else None


def cache_target(prefix: Path, version: str) -> Path:
    """Путь, который ждёт `Cache.js::getInstalledBrowsers()`: <кэш браузера
    в HOME движка>/chrome-headless-shell/win64-<версия>."""

    return (Path(prefix) / "home" / ".cache" / "hyperframes" / "chrome"
            / "chrome-headless-shell" / f"win64-{version}")


def executable_path(prefix: Path, version: str) -> Path:
    return cache_target(prefix, version) / "chrome-headless-shell-win64" / "chrome-headless-shell.exe"


def preseed(prefix: Path, *, opener=urllib.request.urlopen,
           timeout: float = DEFAULT_DOWNLOAD_TIMEOUT) -> PreseedResult:
    """Качает и Unicode-safe распаковывает chrome-headless-shell в обход
    битой на Windows встроенной распаковки — атомарно: собирает во временной
    папке рядом с целью, подтверждает .exe и только тогда переносит на
    итоговое место (`os.replace`). Никогда не бросает исключений: сетевые,
    файловые и архивные отказы возвращаются как `PreseedResult(False, …)` —
    вызывающий код продолжает обычным `browser ensure`, как до этой правки
    (тот путь остаётся сломанным для не-ASCII префикса — просто отсутствие
    ускорения, не новый отказ)."""

    version = pinned_chrome_headless_shell_version(prefix)
    if not version:
        return PreseedResult(False, "версия chrome-headless-shell не прочиталась из cli.js "
                             "закреплённого HyperFrames")
    target = executable_path(prefix, version)
    if target.is_file():
        return PreseedResult(True)

    final_dir = cache_target(prefix, version)
    try:
        final_dir.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return PreseedResult(False, f"не удалось создать папку кэша браузера: {error}")
    sweep_stale(final_dir.parent, EXTRACT_TEMP_PREFIX)
    try:
        work = Path(tempfile.mkdtemp(prefix=EXTRACT_TEMP_PREFIX, dir=str(final_dir.parent)))
    except OSError as error:
        return PreseedResult(False, f"не удалось создать временную папку для распаковки: {error}")

    try:
        url = f"{BASE_URL}/{version}/win64/chrome-headless-shell-win64.zip"
        zip_path = work / "chrome-headless-shell-win64.zip"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "aimaster-install"})
            with opener(request, timeout=timeout, context=ssl_context()) as response:
                with open(zip_path, "wb") as handle:
                    shutil.copyfileobj(response, handle)  # поток на диск, не ~100 МБ в памяти
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError) as error:
            return PreseedResult(False, f"chrome-headless-shell напрямую не скачался: {error}")

        extract_dir = work / "extracted"
        try:
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
        except (zipfile.BadZipFile, zlib.error, EOFError, ValueError, OSError) as error:
            return PreseedResult(False, f"chrome-headless-shell.zip повреждён или не распаковался: {error}")

        extracted_exe = extract_dir / "chrome-headless-shell-win64" / "chrome-headless-shell.exe"
        if not extracted_exe.is_file():
            return PreseedResult(False, f"после распаковки не нашёлся {extracted_exe.name}")

        try:
            if final_dir.exists():
                shutil.rmtree(final_dir, ignore_errors=True)  # протухшая незавершённая попытка
            os.replace(extract_dir, final_dir)
        except OSError as error:
            return PreseedResult(False, f"не удалось перенести распакованный браузер на место: {error}")
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)

    return (PreseedResult(True) if target.is_file()
            else PreseedResult(False, "файла нет на месте после переноса"))

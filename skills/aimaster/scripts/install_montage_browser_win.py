#!/usr/bin/env python3
"""chrome-headless-shell для Windows в обход битой распаковки @puppeteer/browsers.

round 2/5, H1 подтверждён прямым CI-экспериментом (владелец, 2026-09-25,
run 36141827389): @puppeteer/browsers 3.2.3 на win32 распаковывает .zip
через `%SystemRoot%\\System32\\tar.exe`, затем `powershell.exe Expand-Archive`
(fileUtil.js::extractZipWithCli) — ДО Unicode-safe yauzl-фолбэка. Windows
`tar.exe` — порт с узким `main()`: его argv идёт через ANSI-кодовую страницу
процесса (не UTF-8 по умолчанию на EN-US образе windows-latest), поэтому
путь назначения с кириллицей и пробелом («AI Мастерская» — реальный путь
движка) молча не резолвится: Node создаёт папку версии (`mkdir` — Unicode-
safe), а сам .zip внутрь не распаковывается, без исключения и без ненулевого
кода. Прямая проверка: ASCII-префикс (`C:\\hf-ascii`) — качается и рендерит
целиком; тот же кириллический путь рядом в том же прогоне — та же пустая
папка (run 36141827389, джобы `H1 experiment · ascii` / `· cyrillic`).

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
заново."""

from __future__ import annotations

import io
import re
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from install_montage_fetch import ssl_context  # noqa: E402

BASE_URL = "https://storage.googleapis.com/chrome-for-testing-public"
DOWNLOAD_TIMEOUT = 180
_CHROME_VERSION_RE = re.compile(r'CHROME_VERSION\s*=\s*"([0-9]+(?:\.[0-9]+){2,3})"')


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


def preseed(prefix: Path, *, opener=urllib.request.urlopen) -> bool:
    """Качает и Unicode-safe распаковывает chrome-headless-shell в обход
    битой на Windows встроенной распаковки. True — файл на месте (уже был
    или свежескачан), False — не вышло (сеть, версия не прочиталась из
    cli.js): вызывающий код продолжает обычным `browser ensure`, как до
    этой правки (тот путь остаётся сломанным для не-ASCII префикса — это
    просто отсутствие ускорения, не новый отказ)."""

    version = pinned_chrome_headless_shell_version(prefix)
    if not version:
        return False
    target = executable_path(prefix, version)
    if target.is_file():
        return True
    url = f"{BASE_URL}/{version}/win64/chrome-headless-shell-win64.zip"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "aimaster-install"})
        with opener(request, timeout=DOWNLOAD_TIMEOUT, context=ssl_context()) as response:
            data = response.read()
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        print(f"chrome-headless-shell напрямую не скачался: {error}", file=sys.stderr)
        return False
    destination = cache_target(prefix, version)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            archive.extractall(destination)
    except zipfile.BadZipFile as error:
        print(f"chrome-headless-shell.zip повреждён: {error}", file=sys.stderr)
        return False
    return target.is_file()

"""Страница-переходник монтажного стола: выключает аналитику интерфейса Studio
до её первой загрузки.

Studio HyperFrames 0.8.75 шлёт события интерфейса в PostHog, пока в
localStorage её origin нет ключа `hyperframes-studio:telemetryDisabled` = "1"
(или `hf-studio-telemetry-opt-out` = "1"); переменные окружения на страницу не
действуют. Origin — 127.0.0.1:<порт стола>, а порт у каждого запуска новый,
поэтому ключи ставятся при каждом открытии.

Studio отдаёт любой файл папки проекта по `GET /api/projects/<имя>/preview/<путь>`
с типом по расширению и без CSP — на своём же origin. Страница лежит в
`current/.hyperframes/`: эту папку HyperFrames композицией не считает (lint и
поиск композиций смотрят index.html и compositions/, скрытые папки
пропускают), наблюдатель файлов её не слушает, в версии монтажа она не
попадает. Проба 2026-09-28 (0.8.75, Chromium): через страницу — оба ключа
стоят, Studio открылась, 250 загрузок, ни одной мимо 127.0.0.1; без ключей —
два POST на us.i.posthog.com/batch/."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from .desk import TELEMETRY_STORAGE_KEY
from .index_io import write_text_atomic
from .paths import MontagePaths

OPENER_RELATIVE = ".hyperframes/aimaster-desk-open.html"
TELEMETRY_KEYS = (TELEMETRY_STORAGE_KEY, "hf-studio-telemetry-opt-out")
OPENER_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Монтажный стол</title>
<script>
(function () {
  var keys = ["hyperframes-studio:telemetryDisabled", "hf-studio-telemetry-opt-out"];
  for (var i = 0; i < keys.length; i += 1) {
    try { window.localStorage.setItem(keys[i], "1"); } catch (error) { /* хранилища нет — дальше */ }
  }
  var found = new RegExp("^/api/projects/([^/]+)/preview/").exec(window.location.pathname);
  window.location.replace("/#project/" + (found ? found[1] : ""));
})();
</script>
</head>
<body>Открываю монтажный стол…</body>
</html>
"""


def opener_file(paths: MontagePaths) -> Path:
    return paths.current / OPENER_RELATIVE


def ensure_opener(paths: MontagePaths) -> None:
    """Страница на месте и та самая — ничего; иначе записать (атомарно).
    Не записалась — MontageError: стол без неё открылся бы с аналитикой."""

    target = opener_file(paths)
    try:
        if target.read_text(encoding="utf-8") == OPENER_HTML:
            return
    except (OSError, UnicodeDecodeError):
        pass
    write_text_atomic(target, OPENER_HTML)


def opener_url(studio_url: str) -> str | None:
    """Адрес страницы на origin стола по его `studioUrl` 0.8.75
    (`http://127.0.0.1:<порт>/#project/<имя>`); имени в адресе нет — None."""

    parts = urlsplit(studio_url)
    head, _, rest = parts.fragment.partition("/")
    name = unquote(rest.split("?", 1)[0])
    if head != "project" or not name or "/" in name or not parts.netloc:
        return None
    return (f"{parts.scheme}://{parts.netloc}/api/projects/{quote(name, safe='')}"
            f"/preview/{OPENER_RELATIVE}")

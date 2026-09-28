# Монтаж на HyperFrames, план Б (экран «Сборка» в дашборде) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Этап 3 спецификации: экран «Сборка» дашборда для проектов `video` и `mixed` (браузер, ширины 1400 и 390 px) — плеер текущей версии, «Скачать», «Показать в папке», путь к файлу, листалка версий с «Сделать текущей», схема слоёв, плашка «Есть несобранные правки», «Открыть монтажный стол» (HyperFrames Studio в новой вкладке через страницу, выключающую её аналитику) и «Собрать ролик → чат»; сервер — эндпоинты `/api/projects/<id>/montage…`, потоковая отдача файлов, стол под присмотром дашборда.

**Architecture:** Сервер дашборда получает `MontageScreen` (`studio/montage_screen.py`) — тонкую прослойку над новым входом `studio/montage/service_screen.py`, который, как весь `service`, открывает проект заново через `open_context` (проверка ссылок). Состояние делится на дешёвую часть (опрос раз в 5 с) и схему слоёв (только когда сменился ключ текста `index.html`). Столы, открытые дашбордом, ведёт `DeskKeeper`: одно действие со столом проекта за раз, остановка после 60 минут без признаков жизни и при выходе сервера, уборка реестра своих процессов. Файлы `/assets/<id>` отдаются потоком с проверкой sha256 один раз на отпечаток файла; `?download=1` добавляет `Content-Disposition`. Экран v2 собран из чистых моделей (`montage-model.js`, `montage-layers-model.js`, `montage-feed.js` — покрыты `node --test`) и небольших DOM-модулей; стили — `styles/v2/montage.css` на токенах хэндоффа.

**Tech Stack:** Python 3.11+ (только стандартная библиотека: `http.server`, `threading`, `subprocess`, `hashlib`), unittest; ES-модули без сборки, `node:test` (Node ≥ 22); CSS на токенах `styles/v2/tokens-v2.css`; HyperFrames Studio 0.8.75 (движок плана А, не меняется).

**Spec:** `docs/superpowers/specs/2026-09-25-montage-hyperframes-design.md` (разделы «Как это выглядит для человека», «Дашборд: экран «Сборка»», «Телефон» — в части браузера и шлюза, «Ошибки», «Уточнения 2026-09-25»). Реальное API плана А и его ловушки — `.superpowers/sdd/2026-09-25-montage-plan-a-engine-and-core/plan-b-contract-deltas.md` (главнее раздела «Контракт для плана Б» в файле плана А).

## Global Constraints

- Никакой оболочки: программы запускаются списком аргументов (`shell=False`) и по полному пути (`/usr/bin/open`, `%SystemRoot%\explorer.exe`, `xdg-open` из `find_program` — только абсолютные элементы PATH). Исключение одно и намеренное: Проводник Windows получает готовую командную строку для CreateProcess (строкой, без `cmd.exe`) — он сам разбирает `/select,` и не понимает кавычки вокруг всего аргумента.
- Windows, macOS и Linux; ветки ОС проверяются подменой (`system=`, `IS_WINDOWS`, `environ=`), пути — `pathlib`.
- Python 3.11+, только стандартная библиотека; никаких новых зависимостей ни в Python, ни в браузере.
- Весь текст интерфейса — по-русски, простыми короткими фразами владельца («Скачать», «Показать в папке», «Сделать текущей», «Собрать ролик → чат», «Открыть монтажный стол», «Установить → чат», «Есть несобранные правки»).
- На экран и в ответы эндпоинтов не попадают абсолютные пути: файл ролика показывается путём от папки над рабочей (`рабочая папка/media/<проект>/montage/v001.mp4`); `engine.install`/`engine.install_argv` (в них пути к python и навыку) браузеру не отдаются; `restore.backup`, `draft.current`, `render.path` — тоже.
- Любая запись (`POST /api/projects/<id>/montage/…`) — только после `StudioApplication._authorize_write` (Origin дашборда + `X-CSRF-Token`); шлюз Mini App не пускает к столу и к «Показать в папке» (`…/montage/desk`, `…/montage/desk/close`, `…/montage/reveal`) ни в каком написании пути.
- Дашборд сам не собирает ролик: «Собрать ролик → чат» — промпт агенту; `montage render` из запроса дашборда не вызывается.
- CSP страницы (`style-src 'self'`) не ослабляется: атрибут `style` запрещён; единственное динамическое оформление — CSS-переменные через CSSOM (`element.style.setProperty`), проверено на том же CSP.
- Модули — около 60–150 строк, одна ответственность; существующие большие файлы (`http_app.py`, `server.py`, `mini_app.py`, `assets.py`, `viewer.js`) правятся точечно, без перестройки.
- Движок закреплён: HyperFrames 0.8.75. Страница-переходник проверена на 0.8.75; при смене закреплённой версии проба из задачи 20 (шаг «аналитика Studio») повторяется до выпуска.
- Не трогать: `/Users/AlexFisenkov/Documents/aimaster-public`, проекты владельца, `~/.claude`, `~/.agents`, `…/scratchpad/plan-verify` (движок из него только копируется). Реальных генераций и платных сервисов нет.
- Каждая задача заканчивается зелёными (команды из корня worktree `/Users/AlexFisenkov/Documents/aimaster-montage`):
  - `python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'`
  - `python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'`
  - `python3 -m compileall -q skills/aimaster`
  - `node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs`
  - `node --test skills/aimaster/studio/static/ui/v2/*.test.mjs`
  - `git diff --check`

---

## Факты, на которые опирается план (проверено 2026-09-28)

| Факт | Как проверено | Что из него следует |
|---|---|---|
| Studio 0.8.75 отдаёт любой файл папки проекта: `GET /api/projects/<имя>/preview/<путь>` → 200, `Content-Type: text/html` (без charset) для `.html`, `Cache-Control: no-store`, **без CSP**; выход за папку (`..%2F`) → 404 | чтение `dist/cli.js` (маршрут `projects/:id/preview/*`, `isWithinProjectRoot`); `curl` к запущенной Studio (копия движка plan-verify, свой HOME, порт 52508) | страница-переходник — файл в папке монтажа, отдаётся на origin самой Studio; `<meta charset="utf-8">` обязателен |
| Имя проекта Studio — basename папки запуска: `studioUrl` = `http://127.0.0.1:<порт>/#project/current` | строка готовности `preview --json` пробы | адрес переходника выводится из `studioUrl` |
| Аналитика интерфейса Studio: `Sa()` ставит событие в очередь и шлёт `POST https://us.i.posthog.com/batch/`, если ключ `phc_…` и нет ни `localStorage['hyperframes-studio:telemetryDisabled']==='1'`, ни `localStorage['hf-studio-telemetry-opt-out']==='1'`, ни `navigator.doNotTrack==='1'`; проверка — на каждом событии; переменные окружения на страницу не влияют | бандл `dist/studio/assets/index-BlUYw1MB.js` (`JNe`, `BNe`, `UNe`, `XNe`, `CRe`, `ERe`) | переходник ставит оба ключа до загрузки Studio |
| Через переходник на новом origin: оба ключа = `"1"`, переход на `/#project/current?…`, записки «Anonymous studio usage analytics enabled» нет; после вкладки Code и Play — 250 загрузок (Resource Timing), **ни одной** мимо `127.0.0.1`. Контроль на том же origin без ключей: записка в консоли и два `https://us.i.posthog.com/batch/` | Browser pane (Chromium), Studio из копии движка, 2026-09-28 | переходник работает; «честная запись в README» нужна только о прямом `url` |
| `.hyperframes/` Studio не считает композицией (`filterCompositionFiles` пропускает скрытые папки; `lint` смотрит только `index.html` и `compositions/`), наблюдатель файлов её исключает (`WATCHER_EXCLUDED_DIRS`), в «Compositions» остаётся один `index`; во вкладке Code папка `.hyperframes` видна | `dist/cli.js`; скриншот Studio | страница лежит в `current/.hyperframes/aimaster-desk-open.html` и не мешает lint, сборке и Studio |
| `buildRuntimeEnvScript` вставляет `VITE_STUDIO_*` в `<script>` страницы через `JSON.stringify` без экранирования `</script>` | `dist/cli.js` | этот путь отклонён: он держится на ошибке экранирования |
| При CSP `default-src 'none'; script-src 'self'; style-src 'self'` атрибут `style` (через `setAttribute`) не применяется (`left: 0px`), а CSSOM `style.setProperty('--at', '25')` при `left: calc(var(--at) * 1%)` применяется (`100px` из `400px`) | страница с тем же CSP в Browser pane | блоки схемы слоёв ставятся CSS-переменными через CSSOM |
| `AssetIndex.resolve` читает файл целиком и считает sha256 при каждом вызове; `_asset` читает его ещё раз (`path.read_bytes()`) — на каждый Range-запрос плеера | `studio/assets.py:1068-1091`, `studio/http_app.py:431-446` | потоковая отдача, sha256 — кусками и раз на отпечаток файла |
| `_path` пускает query только на `/` и только `project` | `studio/http_app.py:253-274` | `?download=1` разрешается явно и только для `/assets/<id>` |
| Шлюз Mini App пересылает POST с `Origin` дашборда и CSRF клиента, путь — `urlsplit(path).path` (без query) без декодирования; дашборд декодирует путь сам | `studio/mini_app.py:134-163`, `http_app._path` | запрет в шлюзе — по декодированному пути; `download=1` через шлюз не доходит (это план В) |
| `desk_children._children` — общий словарь без замка; стол запускается своей сессией/группой и переживает родителя | `studio/montage/desk_children.py`, `engine_cli.popen_engine` | замок в реестре; дашборд останавливает свои столы сам |
| `AuthoringError` (например «этап «assembly» уже одобрен — montage его не меняет») — наследник `ValueError`: `StudioApplication.handle` превратил бы его в немой 400 | `studio/authoring_support.py:67,250` | маршруты монтажа ловят его сами и отвечают 422 с текстом |
| Снимок проекта уже несёт `active_project.montage` (версии с `asset_url`, текущая, `canvas`) с шага `assembly` | `studio/projection.py:914-950,1244` | листалка версий берётся из снимка, живое — из эндпоинта |

## Раскладка файлов

Сервер (Python):

| Файл | Ответственность |
|---|---|
| `studio/montage/desk_opener.py` (новый) | страница-переходник: текст, запись в `current/.hyperframes/`, адрес на origin стола |
| `studio/montage/status_screen.py` (новый) | дешёвое состояние и схема слоёв для экрана; ключ текста `index.html`; путь файла от папки над рабочей |
| `studio/montage/service_screen.py` (новый) | вход `service` для экрана: состояние, схема, открыть стол, «Сделать текущей» от имени человека, файл текущей версии |
| `studio/montage/status.py` | `_stale`/`_model_part` → публичные `stale_part`/`model_part` |
| `studio/montage/service.py` | `open_desk` кладёт переходник и отдаёт `opener_url` |
| `studio/montage/desk_children.py` | замок реестра, `sweep` |
| `studio/assets.py` | `AssetIndex.stored`, `AssetIndex.locate` — запись и путь без чтения файла |
| `studio/asset_stream.py` (новый) | открыть зарегистрированный файл, сверка отпечатка/sha256, тело кусками |
| `studio/http_write.py` (новый) | запись ответа в сокет (байты или поток) — одна на оба сервера |
| `studio/asset_download.py` (новый) | имя файла для «Скачать» и `Content-Disposition` |
| `studio/reveal.py` (новый) | «Показать в папке»: Finder / Проводник / `xdg-open` |
| `studio/desk_keeper.py` (новый) | столы дашборда: замки проектов, простой, выход, уборка реестра |
| `studio/montage_screen.py` (новый) | `EngineLookup`, `MontageScreen` — ответы эндпоинтов |
| `studio/montage_routes.py` (новый) | разбор `/api/projects/<id>/montage…`, коды ответов |
| `studio/http_app.py` | `Response.stream`, поток в `/assets/`, `?download=1`, маршруты монтажа |
| `studio/server.py` | запись ответа через `http_write`, `MontageScreen` и `DeskKeeper` в `serve()`/`close()` |
| `studio/mini_app.py` | запись ответа через `http_write`, запрет стола и папки |

Тесты (Python, `skills/aimaster/scripts/`): `montage_built.py` (заготовка «проект с v001», не `test_*`), `test_montage_desk_opener.py`, `test_montage_status_screen.py`, `test_montage_service_screen.py`, `test_montage_desk_sweep.py`, `test_asset_stream.py`, `test_http_stream.py`, `test_asset_download.py`, `test_reveal.py`, `test_desk_keeper.py`, `test_montage_screen.py`, `test_montage_http.py`; дополнения в `test_montage_service.py`, `test_mini_app.py`, `test_montage_docs.py`.

Экран (`studio/static/ui/v2/`):

| Файл | Ответственность |
|---|---|
| `screen-prompts.js` | «Собрать ролик → чат» по канону, «Установить → чат», «Обновить клипы → чат» |
| `responsive.js` | `inTelegram()` |
| `montage-model.js` (новый, чистый) | версии, флаги экрана, плашки, ориентация кадра, длина |
| `montage-layers-model.js` (новый, чистый) | дорожки и блоки схемы, подписи по нажатию |
| `montage-api.js` (новый, без DOM) | запросы к эндпоинтам, текст отказа |
| `montage-feed.js` (новый) | опрос, пока открыт экран; ядро без DOM |
| `montage-notices.js`, `montage-file.js`, `montage-desk.js`, `montage-versions.js`, `montage-layers.js` (новые, DOM) | плашки; файл; главные кнопки и стол; версии; схема |
| `assembly-parts.js` (новый, DOM) | превью, карточка «Финальный ролик», история, плашка «принят» — вынесены из `screen-assembly.js` |
| `screen-assembly.js` | фото — как было; видео и смешанный — монтаж |
| `shell.js`, `boot.js`, `viewer.js`, `../actions.js`, `README.md` | остановка опроса, перерисовка по событию, стили, надпись кнопки, `postJson`, описание модулей |
| `styles/v2/montage.css` (новый) | вёрстка монтажа, телефон `@media (max-width: 759px)` |

Документы: `references/montage.md` (задачи 1 и 19), `README.md` репозитория (задача 19).

## Порядок задач

1–4 — монтаж для экрана (пакет `studio/montage/`); 5–7 — отдача файлов; 8–12 — «Показать в папке», стол под присмотром, эндпоинты, шлюз; 13–18 — экран; 19 — канон; 20 — проверка контроллером в браузере. Задачи 1–12 не зависят от статики, 13–16 — от сервера (только от формы ответов, описанной здесь).

---
### Task 1: Страница-переходник монтажного стола и `opener_url`

**Files:**
- Create: `skills/aimaster/studio/montage/desk_opener.py`
- Modify: `skills/aimaster/studio/montage/service.py` (`open_desk`, импорты)
- Modify: `skills/aimaster/studio/montage/desk.py:1-9` (докстринг — план Б сделан)
- Modify: `skills/aimaster/scripts/montage_replies.py:75`
- Modify: `skills/aimaster/references/montage.md` (строка `montage open` в таблице, шаг 2 «Guided flow», начало «Montage desk», пункт об аналитике в «Known limitations»)
- Test: `skills/aimaster/scripts/test_montage_desk_opener.py` (новый), `skills/aimaster/scripts/test_montage_service.py` (два теста)

**Interfaces:**
- Consumes: `studio.montage.desk.TELEMETRY_STORAGE_KEY`; `index_io.write_text_atomic(path, text)`; `paths.MontagePaths.current`; `service.open_desk(workspace, project_id, *, engine=None, desk=None)` плана А.
- Produces:
  - `desk_opener.OPENER_RELATIVE: str` = `".hyperframes/aimaster-desk-open.html"`, `TELEMETRY_KEYS: tuple[str, str]`, `OPENER_HTML: str`
  - `desk_opener.opener_file(paths: MontagePaths) -> Path`
  - `desk_opener.ensure_opener(paths: MontagePaths) -> None` (отказ записи — `MontageError`)
  - `desk_opener.opener_url(studio_url: str) -> str | None`
  - `service.open_desk(...)` → прежние поля + `"opener_url": str | None`

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_desk_opener.py`:

```python
#!/usr/bin/env python3
"""Страница-переходник монтажного стола: ставит оба ключа отказа от аналитики
Studio и уходит в Studio того же адреса; лежит в current/.hyperframes/."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage.desk_opener import (  # noqa: E402
    OPENER_HTML, OPENER_RELATIVE, TELEMETRY_KEYS, ensure_opener, opener_file, opener_url)
from studio.montage.link_guard import check_montage_folder  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402

PAGE = "/api/projects/current/preview/.hyperframes/aimaster-desk-open.html"


class OpenerPageTests(unittest.TestCase):
    def test_page_sets_both_keys_before_it_goes_to_studio(self):
        self.assertEqual(TELEMETRY_KEYS, ("hyperframes-studio:telemetryDisabled",
                                          "hf-studio-telemetry-opt-out"))
        for key in TELEMETRY_KEYS:
            self.assertIn(f'"{key}"', OPENER_HTML)
        self.assertLess(OPENER_HTML.index("localStorage.setItem"),
                        OPENER_HTML.index("location.replace"))

    def test_page_goes_nowhere_but_its_own_origin(self):
        self.assertNotRegex(OPENER_HTML, r"https?://")
        self.assertIn('location.replace("/#project/"', OPENER_HTML)

    def test_page_declares_its_charset(self):
        # Studio отдаёт .html как «text/html» без charset — русский текст иначе ломается
        self.assertIn('<meta charset="utf-8">', OPENER_HTML)


class EnsureOpenerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.paths = montage_paths(Path(temp.name).resolve() / "папка с пробелом" / "p")
        self.paths.current.mkdir(parents=True)

    def test_page_goes_into_the_hidden_service_folder_of_the_montage(self):
        ensure_opener(self.paths)
        self.assertEqual(opener_file(self.paths), self.paths.current / ".hyperframes" / "aimaster-desk-open.html")
        self.assertEqual(opener_file(self.paths).read_text(encoding="utf-8"), OPENER_HTML)
        self.assertEqual(OPENER_RELATIVE, ".hyperframes/aimaster-desk-open.html")

    def test_same_page_is_not_written_again(self):
        ensure_opener(self.paths)
        with mock.patch("studio.montage.desk_opener.write_text_atomic") as write:
            ensure_opener(self.paths)
        write.assert_not_called()

    def test_changed_page_is_put_back(self):
        ensure_opener(self.paths)
        opener_file(self.paths).write_text("<p>чужое</p>", encoding="utf-8")
        ensure_opener(self.paths)
        self.assertEqual(opener_file(self.paths).read_text(encoding="utf-8"), OPENER_HTML)

    def test_page_does_not_trip_the_link_guard(self):
        ensure_opener(self.paths)
        check_montage_folder(self.paths.root)  # обычный файл — не ссылка и не ffmpeg


class OpenerUrlTests(unittest.TestCase):
    def test_address_is_on_the_desk_origin(self):
        self.assertEqual(opener_url("http://127.0.0.1:52508/#project/current"),
                         "http://127.0.0.1:52508" + PAGE)

    def test_studio_state_after_the_name_is_ignored(self):
        self.assertEqual(opener_url("http://127.0.0.1:1/#project/current?v=1&t=0&tab=design"),
                         "http://127.0.0.1:1" + PAGE)

    def test_unusual_name_is_encoded(self):
        self.assertEqual(
            opener_url("http://127.0.0.1:1/#project/%D0%BC%D0%BE%D0%BD%D1%82%D0%B0%D0%B6"),
            "http://127.0.0.1:1/api/projects/%D0%BC%D0%BE%D0%BD%D1%82%D0%B0%D0%B6/preview/"
            ".hyperframes/aimaster-desk-open.html")

    def test_no_project_in_the_address_means_no_page(self):
        for url in ("http://127.0.0.1:1/", "http://127.0.0.1:1/#settings",
                    "http://127.0.0.1:1/#project/", "http://127.0.0.1:1/#project/a%2Fb", "#project/x"):
            with self.subTest(url=url):
                self.assertIsNone(opener_url(url))


if __name__ == "__main__":
    unittest.main()
```

Добавить в класс `ServiceTests` файла `skills/aimaster/scripts/test_montage_service.py` (после `test_desk_goes_through_the_desk_interface`):

```python
    def test_open_desk_puts_the_opener_page_and_returns_its_address(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        desk = mock.Mock()
        desk.open.return_value = {"state": "open", "url": "http://127.0.0.1:7/#project/current",
                                  "port": 7, "pid": 2, "started_at": "t"}
        opened = service.open_desk(self.ws, "p", desk=desk)
        self.assertEqual(opened["opener_url"], "http://127.0.0.1:7/api/projects/current/preview/"
                                               ".hyperframes/aimaster-desk-open.html")
        self.assertTrue((self.paths.current / ".hyperframes" / "aimaster-desk-open.html").is_file())

    def test_open_desk_without_a_draft_creates_no_folders(self):
        desk = mock.Mock()
        desk.open.side_effect = MontageError("черновика ещё нет: сначала montage draft")
        with self.assertRaises(MontageError):
            service.open_desk(self.ws, "p", desk=desk)
        self.assertFalse(self.paths.current.exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_desk_opener.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage.desk_opener'`.

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_service.py' -k opener -v`
Expected: FAIL — `KeyError: 'opener_url'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/desk_opener.py`:

```python
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
```

В `skills/aimaster/studio/montage/service.py` добавить импорт после `from .desk import StudioDesk`:

```python
from .desk_opener import ensure_opener, opener_url
```

и заменить функцию `open_desk` целиком:

```python
def open_desk(workspace, project_id, *, engine=None, desk=None) -> dict:
    ctx = open_context(workspace, project_id)
    desk = desk or StudioDesk(engine or require_engine())
    if ctx.paths.index.is_file():  # без черновика стол откажет сам — папок не заводим
        ensure_opener(ctx.paths)
    opened = desk.open(ctx.paths)
    return {"project_id": project_id, **opened, "opener_url": opener_url(opened["url"])}
```

В `skills/aimaster/studio/montage/desk.py` заменить последние три строки докстринга модуля:

```python
другая реализация того же интерфейса. Остановка по простою и при выходе сервера дашборда, а также
страница-переходник, которая ставит `TELEMETRY_STORAGE_KEY` на origin Studio до
её первой загрузки, — план Б (`studio_origin` — для неё)."""
```

на

```python
другая реализация того же интерфейса. Страница-переходник, которая ставит
`TELEMETRY_STORAGE_KEY` на origin Studio до её первой загрузки, —
`desk_opener.py`; остановка по простою и при выходе сервера дашборда —
`studio/desk_keeper.py`."""
```

В `skills/aimaster/scripts/montage_replies.py` строку 75 заменить на:

```python
    fields["open"] = {"project_id", "state", *PUBLIC_KEYS, "forgotten", "opener_url"}
```

В `skills/aimaster/references/montage.md`:

1. Строку таблицы

```
| `montage open` | starts the montage desk (HyperFrames Studio) | `state`, `url`, `port`, `pid`, `started_at`; sometimes `forgotten` (Montage desk) |
```

заменить на

```
| `montage open` | starts the montage desk (HyperFrames Studio) | `state`, `url`, `opener_url`, `port`, `pid`, `started_at`; sometimes `forgotten` (Montage desk) |
```

2. Шаг 2 «Guided flow»

```
2. Wait. Words in chat → `montage edit` (one command per edit; name what
   changed). Mouse → `montage open`; open `url` in a new tab through the host
   capability, or give the link: «Монтажный стол открыт: <url>. Правки
   сохраняются сами; интерфейс стола на английском. Когда закончите —
   напишите «собери»».
```

заменить на

```
2. Wait. Words in chat → `montage edit` (one command per edit; name what
   changed). Mouse → `montage open`; open `opener_url` in a new tab through
   the host capability, or give that link (`url` only when `opener_url` is
   `null`): «Монтажный стол открыт: <opener_url>. Правки сохраняются сами;
   интерфейс стола на английском. Когда закончите — напишите «собери»».
```

3. Начало раздела «Montage desk»

```
`montage open` starts HyperFrames Studio on 127.0.0.1 for this project only
and returns `url`; a second `open` returns the same desk. Edits save to
```

заменить на

```
`montage open` starts HyperFrames Studio on 127.0.0.1 for this project only
and returns `url` and `opener_url`; a second `open` returns the same desk.
`opener_url` is a page on the desk's own address: it turns Studio's usage
analytics off in this browser and goes on to the desk — give the person
`opener_url`, not `url`. Edits save to
```

4. В «Known limitations» пункт

```
- Studio's page sends usage analytics to its developers (PostHog) unless the
  key `hyperframes-studio:telemetryDisabled` is set to `1` in the page's local
  storage before it first loads; a desk opened from chat does not set it. The
  engine's own telemetry is off.
```

заменить на

```
- Studio's page sends usage analytics to its developers (PostHog) unless the
  key `hyperframes-studio:telemetryDisabled` is `1` in the page's local
  storage before it first loads. `opener_url` sets it (and Studio's second
  opt-out key `hf-studio-telemetry-opt-out`) and then opens the desk; every
  desk start takes a new port, so the page does it on every opening. A desk
  opened at `url` directly keeps the analytics on. The engine's own telemetry
  is off.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_desk_opener.py' -v`
Expected: PASS (11 tests).

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_service.py' -v && python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_docs.py' -v`
Expected: PASS — `test_desk_goes_through_the_desk_interface` по-прежнему зелёный (`url` без `#project/…` → `opener_url: None`), `test_reply_fields_are_the_real_ones` видит `opener_url` в таблице канона.

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: все тесты зелёные на 3.14 и 3.11, compileall молчит, модули статики разобраны без ошибок, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/desk_opener.py skills/aimaster/studio/montage/service.py skills/aimaster/studio/montage/desk.py skills/aimaster/scripts/montage_replies.py skills/aimaster/references/montage.md skills/aimaster/scripts/test_montage_desk_opener.py skills/aimaster/scripts/test_montage_service.py
git commit -m "feat(montage): opener page turns Studio analytics off before its first load"
```

---

### Task 2: Состояние монтажа для экрана — дешёвая часть и схема слоёв

**Files:**
- Create: `skills/aimaster/studio/montage/status_screen.py`
- Create: `skills/aimaster/scripts/montage_built.py` (заготовка тестов экрана, не `test_*`)
- Modify: `skills/aimaster/studio/montage/status.py` (`_stale` → `stale_part`, `_model_part` → `model_part`)
- Test: `skills/aimaster/scripts/test_montage_status_screen.py`

**Interfaces:**
- Consumes: `context.ProjectContext` (`paths`, `state`, `workspace`, `media_root`, `project_id`, `revision`); `model_cache.load(cache_dir, version, html_text) -> dict | None`; `model.Model.from_dict`, `model.model_hash`; `versions.current_meta`, `versions.has_unrendered_changes`; `paths.render_output(media_root, project_id, version_id)`; `montage_state.montage_section`.
- Produces:
  - `status.stale_part(ctx) -> dict` (`{"stale_clips": [...]}` или `{"stale_error": str}`), `status.model_part(ctx, engine, current_version, runner) -> dict`
  - `status_screen.index_key(text: str) -> str` (16 hex)
  - `status_screen.shown_output(ctx, version_id: str | None) -> str | None` («<имя рабочей папки>/media/<проект>/montage/vNNN.mp4»)
  - `status_screen.cheap_status(ctx, engine: Engine | None, reason: str) -> dict` — ключи `project_id, revision, engine{state, version, reason}, exists, current_version, canvas, index_key, unrendered_changes, file{version, shown} | None`
  - `status_screen.model_status(ctx, engine: Engine | None, *, runner=None) -> dict` — ключи `project_id, index_key, model_hash, duration, layers, unrendered_changes, model_error, stale_clips, stale_error`
  - `montage_built.BuiltMontage(base)` — `.workspace`, `.seed`, `.engine`, `.runner`, `.paths`, `.probe(path)`, `.locate()`, `.draft() -> dict`, `.build(revision, *, summary=None) -> dict`, `.draft_and_build() -> dict`, `.state() -> dict`

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/montage_built.py`:

```python
"""Проект «p» с черновиком и собранной версией — заготовка тестов экрана
«Сборка» (service_screen, эндпоинты). Движок подменён (`montage_testkit`),
Node не нужен. Имя не test_* — unittest этот файл сам не запускает."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS.parent), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import (FakeHyperframes, fake_engine, fake_gsap_prefix,  # noqa: E402
                             seed_workspace, tiny_mp4, tiny_wav, video_state)
from studio.authoring_support import open_store  # noqa: E402
from studio.montage import service  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402

INFOS = {"a.mp4": MediaInfo(2.0, 108, 192, True, True),
         "b.mp4": MediaInfo(1.5, 108, 192, True, False),
         "v.wav": MediaInfo(5.0, None, None, False, True)}


class BuiltMontage:
    """Две сцены и голос; `draft()` → ревизия 1, `build(1)` → v001, ревизия 2."""

    def __init__(self, base: Path):
        files = {"a.mp4": tiny_mp4(b"a"), "b.mp4": tiny_mp4(b"b"), "v.wav": tiny_wav()}
        self.seed = seed_workspace(Path(base), files, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"]),
             ("s2", "Клубок", "Находит клубок", 2000, ids["b.mp4"])], audio={"voice": ids["v.wav"]}))
        self.workspace = self.seed.workspace
        self.engine = fake_engine(fake_gsap_prefix(base, files=("gsap", "MotionPathPlugin")))
        self.runner = FakeHyperframes(render_bytes=tiny_mp4(b"out-1"))
        self.paths = montage_paths(self.workspace / "projects" / "p")

    def probe(self, path):
        return INFOS.get(Path(path).name, MediaInfo(3.5, 108, 192, True, True))

    def locate(self):
        return self.engine, ""

    def draft(self) -> dict:
        return service.draft(self.workspace, "p", 0, engine=self.engine, runner=self.runner,
                             probe=self.probe)

    def build(self, revision: int, *, summary=None) -> dict:
        return service.render(self.workspace, "p", revision, summary=summary, engine=self.engine,
                              runner=self.runner, probe=self.probe)

    def draft_and_build(self) -> dict:
        return self.build(self.draft()["revision"])

    def state(self) -> dict:
        return open_store(self.workspace).load("p")
```

`skills/aimaster/scripts/test_montage_status_screen.py`:

```python
#!/usr/bin/env python3
"""Состояние монтажа для экрана «Сборка»: дешёвая часть без движка и без
схемы, схема слоёв — отдельно и только по запросу."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_built import BuiltMontage  # noqa: E402
from montage_testkit import FakeHyperframes, isolate_hyperframes_dir  # noqa: E402
from studio.montage import MontageError, service  # noqa: E402
from studio.montage.context import open_context  # noqa: E402
from studio.montage.edit import EditRequest  # noqa: E402
from studio.montage.index_io import read_index  # noqa: E402
from studio.montage.status_screen import cheap_status, index_key, model_status  # noqa: E402

LAYERS = ["video", "titles", "voice", "music", "fx", "atmos"]


class _TimelineBroken(FakeHyperframes):
    def json(self, engine, args, *, cwd, timeout, ok_codes=(0,)):
        if list(args) == ["timeline", "--json"]:
            raise MontageError("HyperFrames «timeline --json» завершился с кодом 1: сломано")
        return super().json(engine, args, cwd=cwd, timeout=timeout, ok_codes=ok_codes)


class StatusScreenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name).resolve()
        isolate_hyperframes_dir(self, self.temp)
        self.m = BuiltMontage(self.temp)

    def ctx(self):
        return open_context(self.m.workspace, "p")

    def test_before_the_draft_there_is_nothing_yet(self):
        status = cheap_status(self.ctx(), self.m.engine, "")
        self.assertEqual((status["exists"], status["current_version"], status["canvas"],
                          status["index_key"], status["file"], status["unrendered_changes"]),
                         (False, None, None, None, None, None))
        self.assertEqual(status["engine"], {"state": "installed", "version": "0.8.75", "reason": ""})
        self.assertEqual((status["project_id"], status["revision"]), ("p", 0))

    def test_index_key_follows_the_text_of_index_html(self):
        self.m.draft()
        text = read_index(self.m.paths.index)
        status = cheap_status(self.ctx(), self.m.engine, "")
        self.assertEqual(status["index_key"], hashlib.sha256(text.encode("utf-8")).hexdigest()[:16])
        self.assertEqual(status["index_key"], index_key(text))
        self.assertEqual(status["canvas"], {"width": 108, "height": 192})

    def test_unrendered_flag_comes_only_from_the_model_cache(self):
        self.m.draft()
        self.assertIsNone(cheap_status(self.ctx(), self.m.engine, "")["unrendered_changes"])
        before = len(self.m.runner.calls)
        self.assertIs(model_status(self.ctx(), self.m.engine, runner=self.m.runner)["unrendered_changes"], True)
        self.assertEqual(len(self.m.runner.calls), before + 1)  # один timeline --json
        self.assertIs(cheap_status(self.ctx(), self.m.engine, "")["unrendered_changes"], True)
        self.assertEqual(len(self.m.runner.calls), before + 1)  # дешёвая часть движок не зовёт

    def test_after_a_build_the_file_is_shown_from_above_the_workspace(self):
        built = self.m.draft_and_build()
        status = cheap_status(self.ctx(), self.m.engine, "")
        self.assertEqual((status["current_version"], built["version"]), ("v001", "v001"))
        self.assertEqual(status["file"], {"version": "v001", "shown": "рабочая папка/media/p/montage/v001.mp4"})
        self.assertIs(status["unrendered_changes"], False)  # сборка сама положила модель в кэш
        self.assertNotIn(str(self.temp), json.dumps(status, ensure_ascii=False))

    def test_missing_mp4_is_no_file_but_still_the_version(self):
        self.m.draft_and_build()
        (self.m.seed.media / "p" / "montage" / "v001.mp4").unlink()
        self.assertEqual(cheap_status(self.ctx(), self.m.engine, "")["file"],
                         {"version": "v001", "shown": None})

    def test_without_engine_versions_and_file_are_still_there(self):
        self.m.draft_and_build()
        status = cheap_status(self.ctx(), None, "не найден Node.js")
        self.assertEqual(status["engine"], {"state": "missing", "version": None, "reason": "не найден Node.js"})
        self.assertIsNone(status["unrendered_changes"])
        self.assertEqual(status["file"]["version"], "v001")
        model = model_status(self.ctx(), None)
        self.assertEqual((model["layers"], model["model_hash"], model["stale_clips"], model["model_error"]),
                         ([], None, [], None))

    def test_model_part_has_six_layers_and_follows_edits(self):
        self.m.draft_and_build()
        first = model_status(self.ctx(), self.m.engine, runner=self.m.runner)
        self.assertEqual([layer["layer"] for layer in first["layers"]], LAYERS)
        self.assertIs(first["unrendered_changes"], False)
        service.edit(self.m.workspace, "p", 2, EditRequest(op="trim-start", clip="v-1", seconds=0.5),
                     engine=self.m.engine, runner=self.m.runner)
        second = model_status(self.ctx(), self.m.engine, runner=self.m.runner)
        self.assertNotEqual(second["index_key"], first["index_key"])
        self.assertIs(second["unrendered_changes"], True)

    def test_model_part_before_the_draft_is_empty(self):
        model = model_status(self.ctx(), self.m.engine, runner=self.m.runner)
        self.assertEqual((model["index_key"], model["layers"], model["stale_clips"]), (None, [], []))

    def test_engine_failure_is_text_and_stale_part_stays(self):
        self.m.draft()
        model = model_status(self.ctx(), self.m.engine, runner=_TimelineBroken())
        self.assertIn("timeline --json", model["model_error"])
        self.assertEqual((model["layers"], model["stale_clips"], model["stale_error"]), ([], [], None))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_status_screen.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage.status_screen'`.

- [ ] **Step 3: Write minimal implementation**

В `skills/aimaster/studio/montage/status.py`: переименовать `def _stale(ctx: ProjectContext) -> dict:` в `def stale_part(ctx: ProjectContext) -> dict:`, `def _model_part(ctx: ProjectContext, engine: Engine, current_version, runner) -> dict:` в `def model_part(ctx: ProjectContext, engine: Engine, current_version, runner) -> dict:`, и в `montage_status` заменить `result.update(_stale(ctx))` на `result.update(stale_part(ctx))`, `result.update(_model_part(ctx, engine, result["current_version"], runner))` на `result.update(model_part(ctx, engine, result["current_version"], runner))`. Первую строку докстринга `stale_part` дополнить: `"""Устаревшие клипы (и для экрана «Сборка», status_screen.model_status).`

`skills/aimaster/studio/montage/status_screen.py`:

```python
"""Состояние монтажа для экрана «Сборка» дашборда — двумя частями.

`montage status` (status.py) для опроса раз в несколько секунд дорог: хэши
~370 файлов скиллов, `timeline --json` после каждой правки на столе (до
120 с), сверка устаревших клипов. Экрану это нужно реже:

- `cheap_status` — то, что меняют действия человека и что должно быть видно
  сразу: движок, текущая версия, файл ролика, ключ текста index.html и флаг
  несобранных правок, если модель этого текста уже лежит в кэше;
- `model_status` — схема слоёв, хэш, флаг несобранных правок и устаревшие
  клипы; экран просит её, только когда ключ index.html сменился.

Абсолютных путей нет: файл ролика — путь от папки над рабочей
(«<рабочая папка>/media/<проект>/montage/v001.mp4»). Команды установки движка
нет тоже — в ней пути к python и навыку; экран отправляет установку в чат."""

from __future__ import annotations

import hashlib

from . import model_cache
from .context import ProjectContext
from .engine import Engine
from .index_io import read_index
from .model import Model, model_hash
from .montage_state import montage_section
from .paths import render_output
from .status import model_part, stale_part
from .versions import current_meta, has_unrendered_changes


def index_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _index_text(ctx: ProjectContext) -> str | None:
    return read_index(ctx.paths.index) if ctx.paths.index.is_file() else None


def _section(ctx: ProjectContext) -> dict | None:
    return montage_section(ctx.state) if "montage" in ctx.state else None


def shown_output(ctx: ProjectContext, version_id: str | None) -> str | None:
    """MP4 версии путём от папки над рабочей; файла нет — None."""

    if not version_id:
        return None
    output = render_output(ctx.media_root, ctx.project_id, version_id)
    if not output.is_file():
        return None
    return f"{ctx.workspace.name}/{output.relative_to(ctx.workspace).as_posix()}"


def _cached_unrendered(ctx, engine, text, current_version) -> bool | None:
    """Флаг несобранных правок — только из кэша модели, движок не зовётся."""

    if engine is None or text is None:
        return None
    hit = model_cache.load(ctx.paths.cache, engine.version, text)
    try:
        model = Model.from_dict(hit) if hit is not None else None
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        model = None
    if model is None:
        return None
    return has_unrendered_changes(model_hash(model), current_meta(ctx.paths, current_version))


def cheap_status(ctx: ProjectContext, engine: Engine | None, reason: str) -> dict:
    section = _section(ctx)
    current = section["current_version"] if section else None
    text = _index_text(ctx)
    return {
        "project_id": ctx.project_id, "revision": ctx.revision,
        "engine": {"state": "installed" if engine else "missing",
                   "version": engine.version if engine else None, "reason": reason},
        "exists": text is not None, "current_version": current,
        "canvas": section["canvas"] if section else None,
        "index_key": index_key(text) if text is not None else None,
        "unrendered_changes": _cached_unrendered(ctx, engine, text, current),
        "file": {"version": current, "shown": shown_output(ctx, current)} if current else None,
    }


def model_status(ctx: ProjectContext, engine: Engine | None, *, runner=None) -> dict:
    text = _index_text(ctx)
    result = {"project_id": ctx.project_id,
              "index_key": index_key(text) if text is not None else None,
              "model_hash": None, "duration": None, "layers": [], "unrendered_changes": None,
              "model_error": None, "stale_clips": [], "stale_error": None}
    if text is None:
        return result
    result.update(stale_part(ctx))
    if engine is not None:
        section = _section(ctx)
        result.update(model_part(ctx, engine, section["current_version"] if section else None, runner))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_status_screen.py' -v`
Expected: PASS (9 tests).

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_service.py' -v`
Expected: PASS (переименование не меняет `montage status`).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/status.py skills/aimaster/studio/montage/status_screen.py skills/aimaster/scripts/montage_built.py skills/aimaster/scripts/test_montage_status_screen.py
git commit -m "feat(montage): cheap screen status and a separate layer model part"
```

---

### Task 3: Вход `service` для экрана «Сборка»

**Files:**
- Create: `skills/aimaster/studio/montage/service_screen.py`
- Test: `skills/aimaster/scripts/test_montage_service_screen.py`

**Interfaces:**
- Consumes: `context.open_context(workspace, project_id, *, guard=True)`; `desk_opener.opener_url`; `service.open_desk(..., desk=)` (задача 1); `service_versions.restore(workspace, project_id, expected_revision, version_id, *, actor)`; `status_screen.cheap_status`, `model_status`, `shown_output` (задача 2); `paths.render_output`, `paths.MontagePaths`.
- Produces:
  - `service_screen.DeskState = Callable[[MontagePaths], dict]`
  - `service_screen.desk_view(desk: dict) -> dict` — `{"state"}` + для открытого `url` (адрес переходника, иначе адрес Studio) и `telemetry_off: bool` + строки `note`/`forgotten`; ни `pid`, ни `port`
  - `service_screen.screen_status(workspace, project_id, *, locate, desk_state: DeskState) -> dict` — фото: `{"project_id", "revision", "applicable": False}`; иначе `{"applicable": True, **cheap_status, "desk": desk_view(...)}`; `desk_state` зовётся только при черновике
  - `service_screen.screen_model(workspace, project_id, *, locate, runner=None) -> dict`
  - `service_screen.open_desk_for_screen(workspace, project_id, *, desk) -> tuple[dict, MontagePaths]` — `({"project_id", **desk_view}, paths)`
  - `service_screen.restore_as_owner(workspace, project_id, expected_revision, version_id) -> dict` — `{"project_id", "revision", "current_version"}`, история пишет «Вы»
  - `service_screen.current_output(workspace, project_id) -> tuple[Path, str]` — MP4 текущей версии и его путь для показа; нет версии или файла — `MontageError`

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_service_screen.py`:

```python
#!/usr/bin/env python3
"""Вход service для экрана «Сборка»: фото без монтажа, стол через
переходник без pid и порта, «Сделать текущей» от имени человека, файл версии."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_built import BuiltMontage  # noqa: E402
from montage_testkit import isolate_hyperframes_dir  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.service_screen import (  # noqa: E402
    current_output, desk_view, open_desk_for_screen, restore_as_owner, screen_model, screen_status)

STUDIO = "http://127.0.0.1:9/#project/current"
OPENER = "http://127.0.0.1:9/api/projects/current/preview/.hyperframes/aimaster-desk-open.html"
OPEN = {"state": "open", "url": STUDIO, "port": 9, "pid": 5, "started_at": "t"}


class ServiceScreenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name).resolve()
        isolate_hyperframes_dir(self, self.temp)
        self.m = BuiltMontage(self.temp)

    def status(self, desk_state):
        return screen_status(self.m.workspace, "p", locate=self.m.locate, desk_state=desk_state)

    def test_photo_project_has_no_montage(self):
        path = self.m.workspace / "projects" / "p" / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["project"]["type"] = "photo"
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        result = self.status(lambda paths: self.fail("фото-проекту стол не нужен"))
        self.assertEqual(result, {"project_id": "p", "revision": 0, "applicable": False})

    def test_desk_is_asked_only_when_there_is_a_draft(self):
        seen = []
        state = lambda paths: seen.append(paths) or {"state": "closed"}  # noqa: E731
        before = self.status(state)
        self.assertEqual((before["applicable"], before["desk"], seen), (True, {"state": "closed"}, []))
        self.m.draft()
        self.status(state)
        self.assertEqual(seen, [self.m.paths])

    def test_open_desk_is_shown_through_the_opener_without_pid_and_port(self):
        self.m.draft()
        self.assertEqual(self.status(lambda paths: dict(OPEN))["desk"],
                         {"state": "open", "url": OPENER, "telemetry_off": True})

    def test_desk_notes_pass_as_text_and_numbers_do_not(self):
        self.assertEqual(desk_view({"state": "closed", "note": "монтажный стол не отвечает", "pid": 3}),
                         {"state": "closed", "note": "монтажный стол не отвечает"})
        self.assertEqual(desk_view({"state": "busy"}), {"state": "busy"})

    def test_studio_address_without_project_keeps_the_flag_honest(self):
        self.assertEqual(desk_view({"state": "open", "url": "http://127.0.0.1:9/"}),
                         {"state": "open", "url": "http://127.0.0.1:9/", "telemetry_off": False})

    def test_model_uses_the_engine_from_locate(self):
        self.m.draft()
        model = screen_model(self.m.workspace, "p", locate=self.m.locate, runner=self.m.runner)
        self.assertEqual(len(model["layers"]), 6)

    def test_open_desk_for_screen_returns_the_view_and_the_montage_folder(self):
        self.m.draft()
        desk = mock.Mock()
        desk.open.return_value = dict(OPEN)
        view, paths = open_desk_for_screen(self.m.workspace, "p", desk=desk)
        self.assertEqual(view, {"project_id": "p", "state": "open", "url": OPENER, "telemetry_off": True})
        self.assertEqual(paths, self.m.paths)

    def test_restore_from_the_screen_is_written_as_the_person(self):
        self.m.draft_and_build()
        self.assertEqual(restore_as_owner(self.m.workspace, "p", 2, "v001"),
                         {"project_id": "p", "revision": 3, "current_version": "v001"})
        last = self.m.state()["history"][-1]
        self.assertEqual((last["actor"], last["kind"], last["params"]["target_id"]),
                         ("you", "montage-restored", "v001"))

    def test_current_output_is_the_mp4_of_the_current_version(self):
        self.m.draft_and_build()
        target, shown = current_output(self.m.workspace, "p")
        self.assertEqual(target, self.m.seed.media / "p" / "montage" / "v001.mp4")
        self.assertTrue(target.is_file())
        self.assertEqual(shown, "рабочая папка/media/p/montage/v001.mp4")

    def test_nothing_to_reveal_before_the_first_build(self):
        self.m.draft()
        with self.assertRaisesRegex(MontageError, "ещё не собран"):
            current_output(self.m.workspace, "p")

    def test_missing_file_is_named_without_an_absolute_path(self):
        self.m.draft_and_build()
        (self.m.seed.media / "p" / "montage" / "v001.mp4").unlink()
        with self.assertRaises(MontageError) as caught:
            current_output(self.m.workspace, "p")
        self.assertIn("media/p/montage", str(caught.exception))
        self.assertNotIn(str(self.temp), str(caught.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_service_screen.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage.service_screen'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/service_screen.py`:

```python
"""Вход `service` для экрана «Сборка» дашборда. Как и остальной `service`,
каждый вызов открывает проект заново через `open_context` (проверка ссылок
в папке монтажа). Ответы — для браузера: без абсолютных путей, без pid и
порта стола; вместо адреса Studio — адрес страницы-переходника
(`desk_opener`), которая выключает аналитику Studio."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import MontageError
from .context import open_context
from .desk_opener import opener_url
from .montage_state import montage_section
from .paths import MontagePaths, render_output
from .service import open_desk
from .service_versions import restore
from .status_screen import cheap_status, model_status, shown_output

DeskState = Callable[[MontagePaths], dict]
_NOTES = ("note", "forgotten")


def desk_view(desk: dict) -> dict:
    view = {"state": desk.get("state", "closed")}
    if view["state"] == "open" and isinstance(desk.get("url"), str):
        page = opener_url(desk["url"])
        view.update(url=page or desk["url"], telemetry_off=page is not None)
    view.update({key: desk[key] for key in _NOTES if isinstance(desk.get(key), str)})
    return view


def screen_status(workspace, project_id, *, locate, desk_state: DeskState) -> dict:
    ctx = open_context(workspace, project_id)
    if (ctx.state.get("project") or {}).get("type") == "photo":
        return {"project_id": project_id, "revision": ctx.revision, "applicable": False}
    engine, reason = locate()
    result = {"applicable": True, **cheap_status(ctx, engine, reason)}
    result["desk"] = desk_view(desk_state(ctx.paths)) if result["exists"] else {"state": "closed"}
    return result


def screen_model(workspace, project_id, *, locate, runner=None) -> dict:
    ctx = open_context(workspace, project_id)
    engine, _reason = locate()
    return model_status(ctx, engine, runner=runner)


def open_desk_for_screen(workspace, project_id, *, desk) -> tuple[dict, MontagePaths]:
    opened = open_desk(workspace, project_id, desk=desk)
    paths = open_context(workspace, project_id, guard=False).paths
    return {"project_id": project_id, **desk_view(opened)}, paths


def restore_as_owner(workspace, project_id, expected_revision, version_id) -> dict:
    """«Сделать текущей» с экрана — действие человека: в истории «Вы»."""

    result = restore(workspace, project_id, expected_revision, version_id, actor="you")
    return {key: result[key] for key in ("project_id", "revision", "current_version")}


def current_output(workspace, project_id) -> tuple[Path, str]:
    """MP4 текущей версии (для «Показать в папке») и его путь для показа."""

    ctx = open_context(workspace, project_id)
    current = montage_section(ctx.state)["current_version"] if "montage" in ctx.state else None
    if not current:
        raise MontageError("ролик ещё не собран — показывать в папке нечего")
    shown = shown_output(ctx, current)
    if shown is None:
        raise MontageError(f"файла ролика {current} нет в папке media/{project_id}/montage — "
                           "соберите ролик заново")
    return render_output(ctx.media_root, project_id, current), shown
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_service_screen.py' -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/service_screen.py skills/aimaster/scripts/test_montage_service_screen.py
git commit -m "feat(montage): service entry for the assembly screen without absolute paths"
```

---

### Task 4: Реестр своих столов — под замком и с уборкой

**Files:**
- Modify: `skills/aimaster/studio/montage/desk_children.py` (весь файл)
- Test: `skills/aimaster/scripts/test_montage_desk_sweep.py`

**Interfaces:**
- Consumes: ничего нового (`subprocess.Popen`-подобные объекты с `pid`, `poll()`, `wait(timeout)`).
- Produces: `desk_children.remember(paths, process, started)`, `own(paths, record) -> str | None`, `forget(paths, pid)`, `root_key(paths) -> str` — прежние сигнатуры; новое: `desk_children.sweep(*, kill, all_live: bool = False) -> list[int]` — завершившиеся забываются, живые с исчезнувшей (переименованной) папкой montage — `kill(child)` и забываются, `all_live=True` — останавливаются все живые; ответ — pid остановленных.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_desk_sweep.py`:

```python
#!/usr/bin/env python3
"""Реестр столов, запущенных процессом дашборда: под замком (запросы идут
из разных потоков), уборка — завершившиеся забыть, осиротевшие остановить."""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage import desk_children  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402


class _Child:
    def __init__(self, pid, code=None):
        self.pid, self.code, self.waited = pid, code, False

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        self.waited = True
        return self.code


class DeskSweepTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        registry = mock.patch.dict(desk_children._children, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        self.killed = []

    def project(self, name):
        paths = montage_paths(self.base / name)
        paths.root.mkdir(parents=True)
        return paths

    def kill(self, child):
        self.killed.append(child.pid)
        child.code = -15

    def test_exited_children_are_forgotten_and_reaped_without_kill(self):
        child = _Child(11, code=0)
        desk_children.remember(self.project("a"), child, "t")
        self.assertEqual(desk_children.sweep(kill=self.kill), [])
        self.assertEqual((self.killed, desk_children._children, child.waited), ([], {}, True))

    def test_live_child_of_a_vanished_montage_folder_is_stopped(self):
        paths = self.project("b")
        desk_children.remember(paths, _Child(12), "t")
        shutil.rmtree(paths.root)
        self.assertEqual(desk_children.sweep(kill=self.kill), [12])
        self.assertEqual((self.killed, desk_children._children), ([12], {}))

    def test_renamed_project_counts_as_vanished(self):
        paths = self.project("c")
        desk_children.remember(paths, _Child(13), "t")
        (self.base / "c").rename(self.base / "c-переименован")
        self.assertEqual(desk_children.sweep(kill=self.kill), [13])

    def test_live_child_with_its_folder_stays(self):
        desk_children.remember(self.project("d"), _Child(14), "t")
        self.assertEqual(desk_children.sweep(kill=self.kill), [])
        self.assertEqual(len(desk_children._children), 1)

    def test_all_live_stops_every_own_desk(self):
        desk_children.remember(self.project("e"), _Child(15), "t")
        desk_children.remember(self.project("f"), _Child(16, code=1), "t")
        self.assertEqual(desk_children.sweep(kill=self.kill, all_live=True), [15])
        self.assertEqual(desk_children._children, {})

    def test_registry_survives_parallel_use(self):
        projects = [self.project(f"g{index}") for index in range(4)]
        errors = []

        def work(offset):
            try:
                for step in range(200):
                    paths = projects[(offset + step) % 4]
                    pid = 1000 + offset * 1000 + step
                    desk_children.remember(paths, _Child(pid), "t")
                    desk_children.own(paths, {"pid": pid, "process_started": "t"})
                    desk_children.sweep(kill=self.kill)
                    desk_children.forget(paths, pid)
            except Exception as error:  # noqa: BLE001 — любой сбой потока — провал теста
                errors.append(error)

        threads = [threading.Thread(target=work, args=(offset,)) for offset in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((errors, self.killed, desk_children._children), ([], [], {}))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_desk_sweep.py' -v`
Expected: FAIL — `AttributeError: module 'studio.montage.desk_children' has no attribute 'sweep'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/desk_children.py` — весь файл:

```python
"""Столы, запущенные этим процессом. Дашборд держит столы нескольких
проектов сразу и отвечает на запросы из разных потоков, поэтому реестр — под
замком, а свой Popen — доказательство только для своего проекта: ключ —
(папка montage проекта, pid), и время запуска процесса из записи стола должно
совпасть с запомненным при запуске. Завершившийся Popen выбрасывается, как
только это замечено; `sweep` (хранитель столов дашборда) прибирает реестр
целиком. Ждать завершения процесса — всегда вне замка."""

from __future__ import annotations

import os
import subprocess
import threading

RUNNING, EXITED = "running", "exited"
_children: dict[tuple[str, int], tuple[subprocess.Popen, str | None]] = {}
_lock = threading.Lock()


def root_key(paths) -> str:
    """Папка montage проекта в одном виде — ключ реестра и отметка в записи стола."""

    return os.path.normcase(os.path.realpath(str(paths.root)))


def _key(paths, pid: int) -> tuple[str, int]:
    return root_key(paths), pid


def remember(paths, process, started: str | None) -> None:
    with _lock:
        _children[_key(paths, process.pid)] = (process, started)


def own(paths, record: dict) -> str | None:
    """RUNNING — наш живой Popen этого проекта с тем же временем запуска, что
    в записи; EXITED — наш Popen с этим pid уже завершился (номер мог
    достаться чужому); None — доказательства нет."""

    key = _key(paths, record["pid"])
    with _lock:
        entry = _children.get(key)
    if entry is None:
        return None
    child, started = entry
    if child.poll() is not None:
        _drop(key)
        return EXITED
    return RUNNING if started == record.get("process_started") else None


def forget(paths, pid: int) -> None:
    """Убрать из реестра и прибрать процесс (без зомби в долгоживущем дашборде)."""

    _drop(_key(paths, pid))


def _drop(key: tuple[str, int]) -> None:
    with _lock:
        entry = _children.pop(key, None)
    if entry is None:
        return
    try:
        entry[0].wait(timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        pass


def sweep(*, kill, all_live: bool = False) -> list[int]:
    """Прибрать реестр: завершившиеся — забыть; живые, чья папка montage
    исчезла или переименована (или все живые при `all_live` — выход
    дашборда), — остановить `kill(child)` и забыть. Это свой Popen: пока он не
    прибран, его номер не достанется чужому процессу. Ответ — pid остановленных."""

    with _lock:
        items = list(_children.items())
    stopped = []
    for key, (child, _started) in items:
        if child.poll() is None:
            if not all_live and os.path.isdir(key[0]):
                continue
            kill(child)
            stopped.append(key[1])
        _drop(key)
    return stopped
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_desk*.py' -v`
Expected: PASS — 6 новых тестов и все прежние тесты стола.

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/desk_children.py skills/aimaster/scripts/test_montage_desk_sweep.py
git commit -m "fix(montage): desk registry under a lock, sweep of exited and orphaned desks"
```

---

### Task 5: Зарегистрированный файл — потоком, sha256 раз на отпечаток

**Files:**
- Modify: `skills/aimaster/studio/assets.py` (два метода `AssetIndex` после `resolve`)
- Create: `skills/aimaster/studio/asset_stream.py`
- Test: `skills/aimaster/scripts/test_asset_stream.py`

**Interfaces:**
- Consumes: `AssetIndex._connect()`, `AssetIndex._resolve_candidate(path)` (внутри класса), `AssetNotFound`, `AssetValidationError`.
- Produces:
  - `AssetIndex.stored(asset_id) -> dict` — `{"relative_path", "mime_type", "size_bytes", "digest"}`; нет записи — `AssetNotFound`
  - `AssetIndex.locate(relative_path: str) -> Path` — проверки `_resolve_candidate`, без чтения файла
  - `asset_stream.CHUNK_BYTES = 1048576`, `asset_stream.fingerprint(info) -> tuple[int, int, int, int]`
  - `asset_stream.VerifiedFiles(limit=256)` — `.known(asset_id, mark) -> bool`, `.remember(asset_id, mark)`
  - `asset_stream.FileBody(handle, start, length)` — `.start`, `.length`, `.chunks(size=CHUNK_BYTES) -> Iterator[bytes]` (файл короче — `OSError`), `.close()`
  - `asset_stream.OpenedAsset(handle, mime_type, size, relative_path)`
  - `asset_stream.open_asset(index, asset_id, verified) -> OpenedAsset` (не тот файл — `AssetValidationError`)

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_asset_stream.py`:

```python
#!/usr/bin/env python3
"""Отдача зарегистрированного файла потоком: размер — по записи, sha256 —
кусками и раз на отпечаток файла; целиком файл в память не читается."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import tiny_mp4  # noqa: E402
from studio import asset_stream  # noqa: E402
from studio.asset_stream import CHUNK_BYTES, FileBody, VerifiedFiles, open_asset  # noqa: E402
from studio.assets import AssetIndex, AssetNotFound, AssetValidationError  # noqa: E402
from studio.workspace import MAX_ASSET_BYTES, MONTAGE_MAX_BYTES  # noqa: E402


class AssetStreamTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        media = root / "media"
        (media / "p" / "montage").mkdir(parents=True)
        self.data = tiny_mp4(bytes(range(256)) * 12_000)  # ~3 МБ — несколько кусков по 1 МиБ
        self.file = media / "p" / "montage" / "v001.mp4"
        self.file.write_bytes(self.data)
        self.index = AssetIndex(root, (media,), MAX_ASSET_BYTES, montage_max_bytes=MONTAGE_MAX_BYTES,
                                db_path=root / ".studio" / "assets.sqlite3")
        self.asset = self.index.register("media/p/montage/v001.mp4", "result")["asset_id"]
        self.verified = VerifiedFiles()

    def open(self):
        opened = open_asset(self.index, self.asset, self.verified)
        self.addCleanup(opened.handle.close)
        return opened

    def bump_mtime(self):
        info = self.file.stat()
        os.utime(self.file, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))

    def test_index_answers_without_reading_the_file(self):
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("файл целиком")):
            row = self.index.stored(self.asset)
            located = self.index.locate(row["relative_path"])
        self.assertEqual(set(row), {"relative_path", "mime_type", "size_bytes", "digest"})
        self.assertEqual((row["relative_path"], row["size_bytes"], located),
                         ("media/p/montage/v001.mp4", len(self.data), self.file))

    def test_registered_file_opens_with_its_type_and_size(self):
        opened = self.open()
        self.assertEqual((opened.mime_type, opened.size, opened.relative_path),
                         ("video/mp4", len(self.data), "media/p/montage/v001.mp4"))

    def test_body_gives_the_range_in_chunks(self):
        body = FileBody(self.open().handle, 5, 20)
        chunks = list(body.chunks(size=7))
        self.assertEqual(([len(chunk) for chunk in chunks], body.length), ([7, 7, 6], 20))
        self.assertEqual(b"".join(chunks), self.data[5:25])

    def test_whole_file_goes_in_chunks_of_a_mebibyte(self):
        opened = self.open()
        chunks = list(FileBody(opened.handle, 0, opened.size).chunks())
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(max(map(len, chunks)), CHUNK_BYTES)
        self.assertEqual(b"".join(chunks), self.data)

    def test_file_is_hashed_once_while_it_stays_the_same(self):
        with mock.patch.object(asset_stream, "_digest", wraps=asset_stream._digest) as digest:
            self.open()
            self.open()
        self.assertEqual(digest.call_count, 1)

    def test_same_size_other_bytes_are_refused(self):
        self.open()
        changed = bytearray(self.data)
        changed[-1] ^= 0xFF
        self.file.write_bytes(bytes(changed))
        self.bump_mtime()
        with self.assertRaises(AssetValidationError):
            open_asset(self.index, self.asset, self.verified)

    def test_identical_rewrite_is_checked_again_and_opens(self):
        self.open()
        self.file.write_bytes(self.data)
        self.bump_mtime()
        with mock.patch.object(asset_stream, "_digest", wraps=asset_stream._digest) as digest:
            self.open()
        self.assertEqual(digest.call_count, 1)

    def test_shorter_file_is_refused_without_hashing(self):
        self.file.write_bytes(self.data[:-10])
        with mock.patch.object(asset_stream, "_digest") as digest:
            with self.assertRaises(AssetValidationError):
                open_asset(self.index, self.asset, self.verified)
        digest.assert_not_called()

    def test_file_is_never_read_whole(self):
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("файл целиком")):
            opened = self.open()
            self.assertEqual(b"".join(FileBody(opened.handle, 0, opened.size).chunks()), self.data)

    def test_file_that_shrinks_while_it_is_sent_breaks_the_body(self):
        opened = self.open()
        with open(self.file, "r+b") as handle:
            handle.truncate(10)
        with self.assertRaises(OSError):
            list(FileBody(opened.handle, 0, opened.size).chunks())

    def test_unknown_asset_is_not_found(self):
        with self.assertRaises(AssetNotFound):
            open_asset(self.index, "asset-нет", self.verified)

    def test_memory_of_checked_files_is_bounded(self):
        verified = VerifiedFiles(limit=2)
        for name in "abc":
            verified.remember(name, (1, 2, 3, 4))
        self.assertEqual([verified.known(name, (1, 2, 3, 4)) for name in "abc"], [False, True, True])
        self.assertFalse(verified.known("c", (1, 2, 3, 5)))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_asset_stream.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.asset_stream'`.

- [ ] **Step 3: Write minimal implementation**

В `skills/aimaster/studio/assets.py` — в класс `AssetIndex` сразу после метода `resolve`:

```python
    def stored(self, asset_id) -> dict:
        """Запись об ассете без чтения файла: `relative_path`, `mime_type`,
        `size_bytes`, `digest`. Для потоковой отдачи (`studio/asset_stream.py`):
        та сверяет файл с `digest` сама — кусками и раз на отпечаток файла."""

        if not isinstance(asset_id, str) or not asset_id:
            raise AssetNotFound(str(asset_id))
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT relative_path, mime_type, size_bytes, digest "
                "FROM assets WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise AssetNotFound(asset_id)
        return dict(row)

    def locate(self, relative_path) -> Path:
        """Путь к файлу записи с теми же проверками, что у `resolve` (внутри
        разрешённых корней, обычный файл, не в зарезервированном проекте), —
        но без чтения файла."""

        return self._resolve_candidate(relative_path)
```

`skills/aimaster/studio/asset_stream.py`:

```python
"""Отдача зарегистрированного файла потоком — без чтения целиком в память.

`AssetIndex.resolve` читает файл целиком и считает sha256 на каждом вызове; для
собранного ролика (до 2 ГиБ) и частых Range-запросов плеера это непосильно.
Здесь файл открывается один раз на запрос; размер сверяется с записью, а
sha256 считается кусками по 1 МиБ — только когда отпечаток файла (устройство,
inode, размер, время изменения) этим процессом ещё не сверен. Сверенный файл
отдаётся с того же открытого дескриптора: подменить его между проверкой и
отдачей можно только правкой того же inode, а она меняет время изменения."""

from __future__ import annotations

import hashlib
import os
import stat
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import BinaryIO, Iterator

from .assets import AssetIndex, AssetValidationError

CHUNK_BYTES = 1024 * 1024
REMEMBER = 256


def fingerprint(info: os.stat_result) -> tuple[int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


class VerifiedFiles:
    """asset_id → отпечаток файла, чей sha256 уже совпал с записью; помнит
    `limit` последних, общий для потоков сервера."""

    def __init__(self, limit: int = REMEMBER):
        self._seen: OrderedDict[str, tuple] = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()

    def known(self, asset_id: str, mark: tuple) -> bool:
        with self._lock:
            return self._seen.get(asset_id) == mark

    def remember(self, asset_id: str, mark: tuple) -> None:
        with self._lock:
            self._seen[asset_id] = mark
            self._seen.move_to_end(asset_id)
            while len(self._seen) > self._limit:
                self._seen.popitem(last=False)


class FileBody:
    """Кусок [start, start + length) открытого файла — тело ответа сервера."""

    def __init__(self, handle: BinaryIO, start: int, length: int):
        self._handle, self.start, self.length = handle, start, length

    def chunks(self, size: int = CHUNK_BYTES) -> Iterator[bytes]:
        self._handle.seek(self.start)
        left = self.length
        while left > 0:
            chunk = self._handle.read(min(size, left))
            if not chunk:
                raise OSError("asset file shrank while it was sent")
            left -= len(chunk)
            yield chunk

    def close(self) -> None:
        self._handle.close()


@dataclass(frozen=True)
class OpenedAsset:
    handle: BinaryIO
    mime_type: str
    size: int
    relative_path: str


def _digest(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
        digest.update(chunk)
    return digest.hexdigest()


def open_asset(index: AssetIndex, asset_id: str, verified: VerifiedFiles) -> OpenedAsset:
    """Открытый файл ассета, сверенный с записью. Не тот — AssetValidationError
    (сервер отвечает так же, как при отказе `resolve`), нет записи — AssetNotFound."""

    row = index.stored(asset_id)
    path = index.locate(row["relative_path"])
    try:
        handle = open(path, "rb")
    except OSError as error:
        raise AssetValidationError("asset file cannot be read") from error
    try:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != row["size_bytes"]:
            raise AssetValidationError("registered asset has changed")
        mark = fingerprint(info)
        if not verified.known(asset_id, mark):
            if _digest(handle) != row["digest"]:
                raise AssetValidationError("registered asset has changed")
            verified.remember(asset_id, mark)
        return OpenedAsset(handle, row["mime_type"], info.st_size, row["relative_path"])
    except BaseException:
        handle.close()
        raise
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_asset_stream.py' -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/assets.py skills/aimaster/studio/asset_stream.py skills/aimaster/scripts/test_asset_stream.py
git commit -m "feat(studio): open registered files as a checked stream, sha256 once per fingerprint"
```

---

### Task 6: Потоковые ответы — `/assets/<id>` в дашборде и через шлюз Mini App

**Files:**
- Create: `skills/aimaster/studio/http_write.py`
- Modify: `skills/aimaster/studio/http_app.py` (импорт, `Response`, `__init__`, `_asset`, новый `_stream_response`)
- Modify: `skills/aimaster/studio/server.py` (`_Handler._write`, импорт)
- Modify: `skills/aimaster/studio/mini_app.py` (конец `_MiniAppHandler._dispatch`, импорт)
- Test: `skills/aimaster/scripts/test_http_stream.py`

**Interfaces:**
- Consumes: `asset_stream.open_asset`, `FileBody`, `VerifiedFiles` (задача 5).
- Produces:
  - `http_app.Response(status, headers, body, stream=None)` — `stream`: объект с `length: int`, `chunks() -> Iterator[bytes]`, `close()`; при нём `body == b""`
  - `StudioApplication.verified_files: VerifiedFiles`
  - `StudioApplication._asset(asset_id, range_header=None) -> Response` — 200/206 потоком, 416 байтами
  - `http_write.write_response(handler, response) -> None` — один `Content-Length` по настоящей длине, HEAD без тела, поток закрывается всегда

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_http_stream.py`:

```python
#!/usr/bin/env python3
"""/assets/<id> потоком: весь файл, Range, одна длина (и у HEAD — запись
ответа); через шлюз Mini App — тоже; AssetIndex.resolve (чтение целиком) при
отдаче не зовётся. HEAD на /assets/ дашборд, как и раньше, не принимает (405)."""

from __future__ import annotations

import http.client
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import isolate_hyperframes_dir, seed_workspace, tiny_mp4, video_state  # noqa: E402
from studio.assets import AssetIndex  # noqa: E402
from studio.http_app import Response  # noqa: E402
from studio.http_write import write_response  # noqa: E402
from studio.mini_app import serve_mini_app  # noqa: E402
from studio.server import serve  # noqa: E402

TOKEN = "123456:" + "a" * 32


def request(port, target, headers=None, *, method="GET"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, target, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.getheaders(), response.read()
    finally:
        connection.close()


def values(headers, name):
    return [value for key, value in headers if key.lower() == name.lower()]


class _Handler:
    def __init__(self, command="GET"):
        self.command, self.sent, self.wfile = command, [], io.BytesIO()

    def send_response(self, status):
        self.sent.append(("status", status))

    def send_header(self, name, value):
        self.sent.append((name, value))

    def end_headers(self):
        self.sent.append(("end", None))


class _Stream:
    length = 6

    def __init__(self):
        self.closed = False

    def chunks(self):
        yield b"abc"
        yield b"def"

    def close(self):
        self.closed = True


class WriteResponseTests(unittest.TestCase):
    def test_bytes_body_gets_one_true_length(self):
        handler = _Handler()
        write_response(handler, Response(200, {"Content-Type": "text/plain", "Content-Length": "999"}, b"hello"))
        self.assertEqual(values(handler.sent, "Content-Length"), ["5"])
        self.assertEqual(handler.wfile.getvalue(), b"hello")

    def test_stream_goes_in_chunks_and_is_closed(self):
        handler, stream = _Handler(), _Stream()
        write_response(handler, Response(206, {}, b"", stream=stream))
        self.assertEqual((handler.wfile.getvalue(), stream.closed), (b"abcdef", True))
        self.assertEqual(values(handler.sent, "Content-Length"), ["6"])

    def test_head_sends_no_body_and_still_closes_the_stream(self):
        handler, stream = _Handler("HEAD"), _Stream()
        write_response(handler, Response(200, {}, b"", stream=stream))
        self.assertEqual((handler.wfile.getvalue(), stream.closed), (b"", True))


class StreamedAssetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        isolate_hyperframes_dir(self, base)
        self.data = tiny_mp4(bytes(range(256)) * 8_000)
        seed = seed_workspace(base, {"a.mp4": self.data}, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"])]))
        self.file, self.asset = seed.media / "a.mp4", seed.ids["a.mp4"]
        self.running = serve(seed.workspace)
        self.addCleanup(self.running.close)
        self.port = int(self.running.base_url.rsplit(":", 1)[1])

    def get(self, target, headers=None, **kwargs):
        return request(self.port, target, headers, **kwargs)

    def test_whole_file_is_sent_with_its_length(self):
        status, headers, body = self.get(f"/assets/{self.asset}")
        self.assertEqual((status, body), (200, self.data))
        self.assertEqual(values(headers, "Content-Length"), [str(len(self.data))])
        self.assertEqual(values(headers, "Accept-Ranges"), ["bytes"])
        self.assertEqual(values(headers, "Content-Type"), ["video/mp4"])

    def test_range_is_sent_as_206(self):
        status, headers, body = self.get(f"/assets/{self.asset}", {"Range": "bytes=10-19"})
        self.assertEqual((status, body), (206, self.data[10:20]))
        self.assertEqual(values(headers, "Content-Range"), [f"bytes 10-19/{len(self.data)}"])

    def test_suffix_range_gives_the_tail(self):
        status, _headers, body = self.get(f"/assets/{self.asset}", {"Range": "bytes=-5"})
        self.assertEqual((status, body), (206, self.data[-5:]))

    def test_range_past_the_end_is_416(self):
        status, headers, body = self.get(f"/assets/{self.asset}", {"Range": f"bytes={len(self.data)}-"})
        self.assertEqual((status, body), (416, b""))
        self.assertEqual(values(headers, "Content-Range"), [f"bytes */{len(self.data)}"])

    def test_asset_is_not_read_whole_by_resolve(self):
        with mock.patch.object(AssetIndex, "resolve", side_effect=AssertionError("resolve читает целиком")):
            status, _headers, body = self.get(f"/assets/{self.asset}", {"Range": "bytes=0-99"})
        self.assertEqual((status, body), (206, self.data[:100]))

    def test_changed_file_is_not_served(self):
        self.get(f"/assets/{self.asset}")
        changed = bytearray(self.data)
        changed[-1] ^= 0xFF
        self.file.write_bytes(bytes(changed))
        info = self.file.stat()
        os.utime(self.file, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
        status, _headers, body = self.get(f"/assets/{self.asset}")
        # Как и прежде у resolve: AssetValidationError — ValueError, handle отвечает 400.
        self.assertEqual(status, 400)
        self.assertNotEqual(body, bytes(changed))

    def test_mini_app_gateway_streams_with_a_ticket(self):
        mini = serve_mini_app(self.running.application, TOKEN, 501)
        self.addCleanup(mini.close)
        port = int(mini.base_url.rsplit(":", 1)[1])
        expires = int(time.time()) + 300
        ticket = mini._server.gateway._asset_ticket(self.asset, expires)
        target = f"/assets/{self.asset}?e={expires}&t={ticket}"
        status, headers, body = request(port, target)
        self.assertEqual((status, body), (200, self.data))
        self.assertEqual(values(headers, "Content-Length"), [str(len(self.data))])
        status, _headers, body = request(port, target, {"Range": "bytes=0-3"})
        self.assertEqual((status, body), (206, self.data[:4]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_http_stream.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.http_write'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/http_write.py`:

```python
"""Запись ответа `http_app.Response` в сокет — одна на оба сервера (дашборд
и шлюз Mini App). Тело — либо байты (`body`), либо поток (`stream`: файл
кусками, `asset_stream.FileBody`). Content-Length ставится ровно один раз, по
настоящей длине тела; заголовок с таким именем из самого ответа (его ставит,
например, `MiniAppGateway._rewrite_asset_urls`) не повторяется: два разных
Content-Length — недопустимая разметка (RFC 9112 §6.3), туннель Mini App её
отвергает. Поток закрывается всегда — и после HEAD, и при обрыве."""

from __future__ import annotations


def write_response(handler, response) -> None:
    stream = response.stream
    try:
        handler.send_response(response.status)
        for name, value in response.headers.items():
            if name.casefold() != "content-length":
                handler.send_header(name, value)
        length = stream.length if stream is not None else len(response.body)
        handler.send_header("Content-Length", str(length))
        handler.end_headers()
        if handler.command == "HEAD":
            return
        if stream is None:
            handler.wfile.write(response.body)
            return
        for chunk in stream.chunks():
            handler.wfile.write(chunk)
    finally:
        if stream is not None:
            stream.close()
```

В `skills/aimaster/studio/http_app.py`:

1. После `from .assets import AssetError, AssetIndex` добавить:

```python
from .asset_stream import FileBody, VerifiedFiles, open_asset
```

2. `Response` заменить на:

```python
@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes
    # Тело потоком (`asset_stream.FileBody`: `length`, `chunks()`, `close()`) —
    # у файлов `/assets/<id>`; тогда `body` пуст, пишет `http_write.write_response`.
    stream: object | None = None
```

3. В `StudioApplication.__init__` после `self.max_body_bytes = max_body_bytes` добавить:

```python
        # Файлы, чей sha256 уже сверен этим процессом (asset_stream): плеер
        # шлёт десятки Range-запросов, и каждый не должен читать весь ролик.
        self.verified_files = VerifiedFiles()
```

4. Метод `_asset` заменить целиком и добавить после него `_stream_response`:

```python
    def _asset(self, asset_id, range_header=None):
        opened = open_asset(self.assets, asset_id, self.verified_files)
        try:
            requested = self._requested_byte_range(range_header, opened.size)
            headers = {"Accept-Ranges": "bytes"}
            if requested == "unsatisfiable":
                headers["Content-Range"] = f"bytes */{opened.size}"
                opened.handle.close()
                return self._response(416, b"", opened.mime_type, headers)
            start, end = (0, opened.size - 1) if requested is None else requested
            if requested is not None:
                headers["Content-Range"] = f"bytes {start}-{end}/{opened.size}"
            body = FileBody(opened.handle, start, end - start + 1)
        except BaseException:
            opened.handle.close()
            raise
        return self._stream_response(200 if requested is None else 206, body,
                                     opened.mime_type, headers)

    @staticmethod
    def _stream_response(status, body, content_type, extra_headers) -> Response:
        headers = _security_headers(content_type)
        headers.update(extra_headers)
        return Response(status, headers, b"", stream=body)
```

В `skills/aimaster/studio/server.py` добавить импорт `from .http_write import write_response` (после `from .http_app import MAX_BODY_BYTES, StudioApplication`) и заменить `_Handler._write` на:

```python
    def _write(self, response):
        write_response(self, response)
```

В `skills/aimaster/studio/mini_app.py` добавить импорт `from .http_write import write_response` (после `from .http_app import Response`) и в `_MiniAppHandler._dispatch` заменить всё, что идёт после блока `except Exception:` (от `self.send_response(response.status)` до `self.wfile.write(response.body)` включительно, с комментарием о длине), на:

```python
        # Одна настоящая длина и поток файла кусками — http_write (там же
        # объяснено, почему Content-Length из ответа не повторяется).
        write_response(self, response)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_http_stream.py' -v && python3 -m unittest discover -s skills/aimaster/scripts -p 'test_mini_app.py' -v`
Expected: PASS (10 новых тестов; `test_live_gateway_sends_one_content_length` и прочие тесты шлюза зелёные).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/http_write.py skills/aimaster/studio/http_app.py skills/aimaster/studio/server.py skills/aimaster/studio/mini_app.py skills/aimaster/scripts/test_http_stream.py
git commit -m "feat(studio): stream /assets/<id> with Range in the dashboard and the Mini App gateway"
```

---

### Task 7: «Скачать» — `?download=1` и `Content-Disposition`

**Files:**
- Create: `skills/aimaster/studio/asset_download.py`
- Modify: `skills/aimaster/studio/http_app.py` (`_path`, ветка `/assets/` в `handle`, `_asset`, новые `_wants_download`, `_project_title`)
- Test: `skills/aimaster/scripts/test_asset_download.py`

**Interfaces:**
- Consumes: `OpenedAsset.relative_path` (задача 5); `StudioApplication._asset(asset_id, range_header)` (задача 6); `ProjectStore.load(project_id)`.
- Produces:
  - `asset_download.download_names(relative_path: str, title_of: Callable[[str], str | None]) -> tuple[str, str]` — (имя, запасное имя латиницей)
  - `asset_download.content_disposition(name: str, fallback: str) -> str`
  - `StudioApplication._asset(asset_id, range_header=None, *, download=False)`
  - маршрут: `GET /assets/<id>?download=1` — тот же ответ (200/206/416) плюс `Content-Disposition: attachment; filename="<латиница>"; filename*=UTF-8''<имя>`; любой другой query на `/assets/` и на API — 400

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_asset_download.py`:

```python
#!/usr/bin/env python3
"""«Скачать»: ролик монтажа — «<название проекта>-vNNN.mp4», прочие файлы —
своим именем; `?download=1` пускается только на /assets/<id>."""

from __future__ import annotations

import http.client
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import isolate_hyperframes_dir, seed_workspace, tiny_mp4, video_state  # noqa: E402
from studio.asset_download import content_disposition, download_names  # noqa: E402
from studio.authoring_support import open_assets  # noqa: E402
from studio.server import serve  # noqa: E402


class DownloadNameTests(unittest.TestCase):
    def test_montage_video_is_named_after_the_project_and_version(self):
        self.assertEqual(download_names("media/p/montage/v003.mp4", lambda project: "Проба монтажа"),
                         ("Проба монтажа-v003.mp4", "p-v003.mp4"))

    def test_forbidden_characters_and_line_breaks_are_dropped(self):
        name, fallback = download_names("media/p/montage/v001.mp4",
                                        lambda project: 'Кот «Барсик»: сад/вечер\r\n"?*')
        self.assertEqual((name, fallback), ("Кот «Барсик» сад вечер-v001.mp4", "p-v001.mp4"))

    def test_long_title_is_cut(self):
        name, _fallback = download_names("media/p/montage/v001.mp4", lambda project: "а" * 300)
        self.assertEqual(name, "а" * 80 + "-v001.mp4")

    def test_without_title_the_project_id_is_used(self):
        self.assertEqual(download_names("media/zz-1/montage/v002.mp4", lambda project: None),
                         ("zz-1-v002.mp4", "zz-1-v002.mp4"))

    def test_cyrillic_project_id_gets_a_latin_fallback(self):
        self.assertEqual(download_names("media/проект/montage/v001.mp4", lambda project: None),
                         ("проект-v001.mp4", "montage-v001.mp4"))

    def test_other_files_keep_their_own_name(self):
        self.assertEqual(download_names("media/clip 1.mp4", lambda project: "x"), ("clip 1.mp4", "clip-1.mp4"))
        self.assertEqual(download_names("media/клип.mp4", lambda project: "x"), ("клип.mp4", "file.mp4"))

    def test_header_carries_both_names(self):
        self.assertEqual(content_disposition("Проба-v001.mp4", "p-v001.mp4"),
                         "attachment; filename=\"p-v001.mp4\"; filename*=UTF-8''"
                         + quote("Проба-v001.mp4", safe=""))


class DownloadRouteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        isolate_hyperframes_dir(self, base)
        seed = seed_workspace(base, {"a.mp4": tiny_mp4(b"a")}, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"])]))
        folder = seed.media / "p" / "montage"
        folder.mkdir(parents=True)
        (folder / "v001.mp4").write_bytes(tiny_mp4(b"version-1"))
        self.version = open_assets(seed.workspace).register("media/p/montage/v001.mp4", "result")["asset_id"]
        self.running = serve(seed.workspace)
        self.addCleanup(self.running.close)
        self.port = int(self.running.base_url.rsplit(":", 1)[1])

    def get(self, target, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request("GET", target, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.getheader("Content-Disposition"), response.read()
        finally:
            connection.close()

    def test_download_names_the_file_after_the_project(self):
        status, disposition, body = self.get(f"/assets/{self.version}?download=1")
        self.assertEqual((status, body), (200, tiny_mp4(b"version-1")))
        self.assertEqual(disposition, "attachment; filename=\"p-v001.mp4\"; filename*=UTF-8''"
                                      + quote("Проба монтажа-v001.mp4", safe=""))

    def test_plain_get_is_not_an_attachment(self):
        status, disposition, _body = self.get(f"/assets/{self.version}")
        self.assertEqual((status, disposition), (200, None))

    def test_range_download_keeps_the_name(self):
        status, disposition, body = self.get(f"/assets/{self.version}?download=1", {"Range": "bytes=0-3"})
        self.assertEqual((status, body), (206, tiny_mp4(b"version-1")[:4]))
        self.assertTrue(disposition.startswith("attachment; "))

    def test_other_queries_are_refused(self):
        for target in (f"/assets/{self.version}?download=2", f"/assets/{self.version}?download=1&x=1",
                       f"/assets/{self.version}?download", f"/assets/{self.version}?project=p",
                       "/api/projects?download=1"):
            with self.subTest(target=target):
                self.assertEqual(self.get(target)[0], 400)

    def test_project_selector_of_the_page_still_works(self):
        self.assertEqual(self.get("/?project=p")[0], 200)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_asset_download.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.asset_download'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/asset_download.py`:

```python
"""«Скачать» (`GET /assets/<id>?download=1`): имя файла и Content-Disposition.

Ролик монтажа (`media/<проект>/montage/vNNN.mp4`) сохраняется как
«<название проекта>-vNNN.mp4», любой другой файл — под своим именем. Имя
в заголовке дважды: `filename*` (UTF-8, RFC 6266/8187) — для кириллицы,
`filename` — только латиница, цифры и «._-» — для старых программ. Знаки,
запрещённые в именах файлов Windows и macOS, и переводы строк выбрасываются:
заголовок не разорвать, файл сохранится на любой системе."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Callable
from urllib.parse import quote

_MONTAGE = re.compile(r"media/([^/]+)/montage/(v\d{3,})\.mp4")
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]+')
_NOT_LATIN = re.compile(r"[^A-Za-z0-9._-]+")
MAX_STEM = 80


def _clean(text: str) -> str:
    return " ".join(_FORBIDDEN.sub(" ", text).split())[:MAX_STEM].strip(" .")


def _latin(text: str) -> str:
    return _NOT_LATIN.sub("-", text).strip("-.")


def download_names(relative_path: str, title_of: Callable[[str], str | None]) -> tuple[str, str]:
    """(имя для сохранения, запасное имя латиницей)."""

    match = _MONTAGE.fullmatch(relative_path)
    if match is None:
        name = _clean(PurePosixPath(relative_path).name) or "file"
        path = PurePosixPath(name)
        return name, (_latin(path.stem) or "file") + path.suffix
    project_id, version = match.groups()
    title = _clean(title_of(project_id) or "") or _clean(project_id) or "montage"
    return f"{title}-{version}.mp4", f"{_latin(project_id) or 'montage'}-{version}.mp4"


def content_disposition(name: str, fallback: str) -> str:
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}"
```

В `skills/aimaster/studio/http_app.py`:

1. После `from .asset_stream import FileBody, VerifiedFiles, open_asset` добавить:

```python
from .asset_download import content_disposition, download_names
```

2. В `_path` блок `if parsed.query:` заменить целиком на:

```python
        if parsed.query:
            # Project selection belongs only to the dashboard document; the one
            # other query is «Скачать» — `/assets/<id>?download=1`. API routes
            # keep their exact-path contract.
            pairs = parse_qsl(parsed.query, keep_blank_values=True,
                              strict_parsing=True, errors="strict")
            if not (parsed.path.startswith("/assets/") and pairs == [("download", "1")]):
                if parsed.path != "/" or len(pairs) != 1 or pairs[0][0] != "project":
                    raise ValueError("unsupported query")
                project_id = pairs[0][1]
                if (not project_id or project_id in {".", ".."}
                        or any(char in project_id for char in ("/", "\\", "\0"))
                        or any(ord(char) < 32 for char in project_id)):
                    raise ValueError("invalid project selector")
```

3. В `handle` строку `return self._asset(asset_id, request_headers.get("range"))` заменить на:

```python
                    return self._asset(asset_id, request_headers.get("range"),
                                       download=self._wants_download(path))
```

4. Сигнатуру `_asset` заменить на `def _asset(self, asset_id, range_header=None, *, download=False):`, а строку `headers = {"Accept-Ranges": "bytes"}` в нём — на:

```python
            headers = {"Accept-Ranges": "bytes"}
            if download:
                headers["Content-Disposition"] = content_disposition(
                    *download_names(opened.relative_path, self._project_title))
```

5. После `_stream_response` добавить:

```python
    @staticmethod
    def _wants_download(raw_path) -> bool:
        query = urlsplit(raw_path).query
        return bool(query) and parse_qsl(query, keep_blank_values=True) == [("download", "1")]

    def _project_title(self, project_id: str) -> str | None:
        try:
            project = self.store.load(project_id).get("project") or {}
        except (ProjectNotFound, StoreError, OSError, ValueError):
            return None
        title = project.get("title")
        return title if isinstance(title, str) else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_asset_download.py' -v && python3 -m unittest discover -s skills/aimaster/scripts -p 'test_http_stream.py' -v`
Expected: PASS (12 новых тестов, потоковые — по-прежнему).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/asset_download.py skills/aimaster/studio/http_app.py skills/aimaster/scripts/test_asset_download.py
git commit -m "feat(studio): download=1 names the montage video after the project and version"
```

---

### Task 8: «Показать в папке» — Finder, Проводник, `xdg-open`

**Files:**
- Create: `skills/aimaster/studio/reveal.py`
- Test: `skills/aimaster/scripts/test_reveal.py`

**Interfaces:**
- Consumes: `platform_compat.IS_WINDOWS`, `platform_compat.find_program(name, *, environ)`; `montage.MontageError`.
- Produces:
  - `reveal.MAC_OPEN = "/usr/bin/open"`, `reveal.TIMEOUT_SECONDS = 15`
  - `reveal.current_system() -> str` — `"mac" | "windows" | "linux"`
  - `reveal.reveal_command(target: PurePath, *, system, environ, find=find_program, is_file=os.path.isfile) -> list[str] | str | None`
  - `reveal.reveal_available(*, system=None, environ=None, find=find_program, is_file=os.path.isfile) -> bool`
  - `reveal.reveal_file(target: PurePath, *, system=None, environ=None, run=subprocess.run, find=find_program, is_file=os.path.isfile) -> None` — отказ — `MontageError` по-русски

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_reveal.py`:

```python
#!/usr/bin/env python3
"""«Показать в папке»: полный путь к программе, без оболочки; Проводнику —
готовая строка с /select, и код 1 — не ошибка."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage import MontageError  # noqa: E402
from studio.reveal import MAC_OPEN, reveal_available, reveal_command, reveal_file  # noqa: E402

MAC_FILE = PurePosixPath("/Users/А Б/рабочая папка/media/p/montage/v001.mp4")
WIN_FILE = PureWindowsPath(r"C:\Users\А Б\рабочая папка\media\p\montage\v001.mp4")
LINUX_FILE = PurePosixPath("/home/а б/рабочая папка/media/p/montage/v001.mp4")


def xdg(name, environ):
    return "/usr/bin/xdg-open" if name == "xdg-open" else None


class RevealCommandTests(unittest.TestCase):
    def test_finder_selects_the_file(self):
        self.assertEqual(reveal_command(MAC_FILE, system="mac", environ={}, is_file=lambda path: path == MAC_OPEN),
                         ["/usr/bin/open", "-R", str(MAC_FILE)])

    def test_explorer_gets_one_command_line_with_select(self):
        command = reveal_command(WIN_FILE, system="windows", environ={"SystemRoot": r"C:\Windows"},
                                 is_file=lambda path: True)
        self.assertEqual(command, '"C:\\Windows\\explorer.exe" /select,'
                                  '"C:\\Users\\А Б\\рабочая папка\\media\\p\\montage\\v001.mp4"')

    def test_windir_is_used_when_system_root_is_missing(self):
        command = reveal_command(WIN_FILE, system="windows", environ={"windir": r"D:\Win"}, is_file=lambda path: True)
        self.assertTrue(command.startswith('"D:\\Win\\explorer.exe" /select,"'))

    def test_explorer_needs_an_absolute_system_root(self):
        for environ in ({}, {"SystemRoot": "Windows"}):
            with self.subTest(environ=environ):
                self.assertIsNone(reveal_command(WIN_FILE, system="windows", environ=environ,
                                                 is_file=lambda path: True))

    def test_linux_opens_the_folder_with_xdg_open_from_path(self):
        self.assertEqual(reveal_command(LINUX_FILE, system="linux", environ={"PATH": "/usr/bin"}, find=xdg),
                         ["/usr/bin/xdg-open", "/home/а б/рабочая папка/media/p/montage"])

    def test_no_program_means_no_command(self):
        self.assertIsNone(reveal_command(MAC_FILE, system="mac", environ={}, is_file=lambda path: False))
        self.assertIsNone(reveal_command(LINUX_FILE, system="linux", environ={}, find=lambda name, environ: None))

    def test_available_follows_the_command(self):
        self.assertTrue(reveal_available(system="mac", environ={}, is_file=lambda path: True))
        self.assertFalse(reveal_available(system="linux", environ={}, find=lambda name, environ: None))


class RevealFileTests(unittest.TestCase):
    def runner(self, returncode=0, error=None):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            if error is not None:
                raise error
            return subprocess.CompletedProcess(command, returncode)
        return calls, run

    def test_argv_list_without_shell_and_with_a_timeout(self):
        calls, run = self.runner()
        reveal_file(MAC_FILE, system="mac", environ={}, run=run, is_file=lambda path: True)
        command, kwargs = calls[0]
        self.assertEqual(command, ["/usr/bin/open", "-R", str(MAC_FILE)])
        self.assertNotIn("shell", kwargs)
        self.assertEqual((kwargs["timeout"], kwargs["stdin"], kwargs["check"]), (15, subprocess.DEVNULL, False))

    def test_explorer_code_one_is_success(self):
        calls, run = self.runner(returncode=1)
        reveal_file(WIN_FILE, system="windows", environ={"SystemRoot": r"C:\Windows"}, run=run,
                    is_file=lambda path: True)
        self.assertIsInstance(calls[0][0], str)

    def test_finder_failure_is_a_refusal(self):
        _calls, run = self.runner(returncode=1)
        with self.assertRaisesRegex(MontageError, "не удалось открыть папку"):
            reveal_file(MAC_FILE, system="mac", environ={}, run=run, is_file=lambda path: True)

    def test_timeout_is_a_refusal(self):
        _calls, run = self.runner(error=subprocess.TimeoutExpired(cmd="open", timeout=15))
        with self.assertRaisesRegex(MontageError, "не удалось открыть папку"):
            reveal_file(MAC_FILE, system="mac", environ={}, run=run, is_file=lambda path: True)

    def test_missing_program_is_named(self):
        _calls, run = self.runner()
        with self.assertRaisesRegex(MontageError, "xdg-open"):
            reveal_file(LINUX_FILE, system="linux", environ={}, run=run, find=lambda name, environ: None)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_reveal.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.reveal'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/reveal.py`:

```python
"""«Показать в папке»: файловый менеджер компьютера с выделенным файлом.

macOS — Finder: `/usr/bin/open -R <файл>`. Windows — Проводник:
`%SystemRoot%\\explorer.exe /select,"<файл>"` одной командной строкой для
CreateProcess, без cmd.exe: Проводник разбирает `/select,` сам и не понимает
кавычки вокруг всего аргумента, которые ставит list2cmdline; кавычки в имени
файла на Windows не бывает. Linux — `xdg-open <папка>`: выделять файл он не
умеет. Программа — всегда по полному пути, оболочки нет. Проводник отвечает
кодом 1 и при успехе — поэтому код не проверяется только у него."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path, PurePath, PureWindowsPath
from typing import Mapping

from .montage import MontageError
from .platform_compat import IS_WINDOWS, find_program

MAC_OPEN = "/usr/bin/open"
TIMEOUT_SECONDS = 15
FAILED = "не удалось открыть папку с роликом"
NO_PROGRAM = {
    "mac": "на этом компьютере нет программы open — откройте папку с роликом сами",
    "windows": "не найден Проводник (explorer.exe) — откройте папку с роликом сами",
    "linux": "на этом компьютере нет программы xdg-open — откройте папку с роликом сами",
}


def current_system() -> str:
    if IS_WINDOWS:
        return "windows"
    return "mac" if sys.platform == "darwin" else "linux"


def reveal_command(target: PurePath, *, system: str, environ: Mapping[str, str],
                   find=find_program, is_file=os.path.isfile) -> list[str] | str | None:
    """Чем показать `target` на этой ОС; нечем — None."""

    if system == "mac":
        return [MAC_OPEN, "-R", str(target)] if is_file(MAC_OPEN) else None
    if system == "windows":
        root = environ.get("SystemRoot") or environ.get("windir") or ""
        if not PureWindowsPath(root).is_absolute():
            return None
        explorer = str(PureWindowsPath(root) / "explorer.exe")
        return f'"{explorer}" /select,"{target}"' if is_file(explorer) else None
    program = find("xdg-open", environ=environ)
    return [program, str(target.parent)] if program else None


def reveal_available(*, system=None, environ=None, find=find_program, is_file=os.path.isfile) -> bool:
    system = system or current_system()
    environ = os.environ if environ is None else environ
    return reveal_command(Path("ролик.mp4"), system=system, environ=environ, find=find,
                          is_file=is_file) is not None


def reveal_file(target: PurePath, *, system=None, environ=None, run=subprocess.run,
                find=find_program, is_file=os.path.isfile) -> None:
    system = system or current_system()
    environ = os.environ if environ is None else environ
    command = reveal_command(target, system=system, environ=environ, find=find, is_file=is_file)
    if command is None:
        raise MontageError(NO_PROGRAM[system])
    try:
        result = run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, timeout=TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise MontageError(FAILED) from error
    if system != "windows" and result.returncode != 0:
        raise MontageError(FAILED)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_reveal.py' -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/reveal.py skills/aimaster/scripts/test_reveal.py
git commit -m "feat(studio): reveal the montage video in Finder, Explorer or the Linux file manager"
```

---

### Task 9: Хранитель столов дашборда — замки проектов, простой, выход

**Files:**
- Create: `skills/aimaster/studio/desk_keeper.py`
- Test: `skills/aimaster/scripts/test_desk_keeper.py`

**Interfaces:**
- Consumes: `desk_children.sweep(*, kill, all_live=False)` (задача 4); `montage.proc_tree.kill_tree(proc)`; `paths.MontagePaths.index`.
- Produces:
  - `desk_keeper.IDLE_SECONDS = 3600`, `SWEEP_SECONDS = 60.0`, `STOP_WAIT = 10.0`
  - `desk_keeper.index_stamp(paths) -> tuple[int, int] | None`
  - `desk_keeper.DeskKeeper(*, close_desk, kill=kill_tree, clock=time.monotonic, idle=IDLE_SECONDS, sweep_every=SWEEP_SECONDS, stamp=index_stamp)`:
    `.lock(project_id) -> threading.Lock`, `.opened(project_id, paths)`, `.closed(project_id)`, `.touch(project_id)`, `.watched() -> list[str]`, `.sweep() -> list[str]` (остановленные по простою), `.start()`, `.running() -> bool`, `.stop()`; `close_desk(paths) -> dict` — в сервере `StudioDesk(None).close`

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_desk_keeper.py`:

```python
#!/usr/bin/env python3
"""Хранитель столов дашборда: час без опроса экрана и без правок — стол
останавливается; занятый стол ждёт следующей уборки; выход сервера
останавливает все свои столы."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.desk_keeper import DeskKeeper  # noqa: E402
from studio.montage import MontageError, desk_children  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class DeskKeeperTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.paths = self.project("p")
        registry = mock.patch.dict(desk_children._children, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        self.clock, self.closed = FakeClock(), []
        self.keeper = DeskKeeper(close_desk=self.closed.append, kill=self.no_kill, clock=self.clock,
                                 idle=3600, sweep_every=0.01)

    def project(self, name):
        paths = montage_paths(self.base / name)
        paths.current.mkdir(parents=True)
        paths.index.write_text("<html></html>", encoding="utf-8")
        return paths

    def no_kill(self, child):
        self.fail("живой свой процесс с папкой на месте так не останавливают")

    def test_desk_without_signs_of_life_stops_after_an_hour(self):
        self.keeper.opened("p", self.paths)
        self.clock.now += 3599
        self.assertEqual(self.keeper.sweep(), [])
        self.clock.now += 1
        self.assertEqual(self.keeper.sweep(), ["p"])
        self.assertEqual((self.closed, self.keeper.watched()), ([self.paths], []))

    def test_screen_poll_keeps_the_desk(self):
        self.keeper.opened("p", self.paths)
        self.clock.now += 3000
        self.keeper.touch("p")
        self.clock.now += 3000
        self.assertEqual(self.keeper.sweep(), [])
        self.clock.now += 600
        self.assertEqual(self.keeper.sweep(), ["p"])

    def test_edit_on_the_desk_keeps_it(self):
        self.keeper.opened("p", self.paths)
        self.clock.now += 3000
        self.paths.index.write_text("<html><body>правка</body></html>", encoding="utf-8")
        info = self.paths.index.stat()
        os.utime(self.paths.index, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
        self.assertEqual(self.keeper.sweep(), [])
        self.clock.now += 3599
        self.assertEqual(self.keeper.sweep(), [])
        self.clock.now += 1
        self.assertEqual(self.keeper.sweep(), ["p"])

    def test_touch_of_a_desk_nobody_opened_changes_nothing(self):
        self.keeper.touch("чужой")
        self.assertEqual(self.keeper.watched(), [])

    def test_busy_desk_waits_for_the_next_sweep(self):
        self.keeper.opened("p", self.paths)
        self.clock.now += 3600
        lock = self.keeper.lock("p")
        lock.acquire()
        try:
            self.assertEqual(self.keeper.sweep(), [])
        finally:
            lock.release()
        self.assertEqual(self.closed, [])
        self.assertEqual(self.keeper.sweep(), ["p"])

    def test_refused_close_does_not_stop_the_sweep(self):
        def refuse(paths):
            raise MontageError("не удалось остановить монтажный стол")
        keeper = DeskKeeper(close_desk=refuse, kill=self.no_kill, clock=self.clock, idle=10)
        keeper.opened("p", self.paths)
        keeper.opened("q", self.project("q"))
        self.clock.now += 10
        self.assertEqual(sorted(keeper.sweep()), ["p", "q"])
        self.assertEqual(keeper.watched(), [])

    def test_sweep_tidies_the_registry_of_own_processes(self):
        with mock.patch.object(desk_children, "sweep", return_value=[]) as sweep:
            self.keeper.sweep()
        sweep.assert_called_once_with(kill=self.no_kill)

    def test_stop_closes_every_dashboard_desk_and_ends_the_thread(self):
        self.keeper.start()
        self.assertTrue(self.keeper.running())
        self.keeper.opened("p", self.paths)
        with mock.patch.object(desk_children, "sweep", return_value=[]) as sweep:
            self.keeper.stop()
        self.assertEqual((self.closed, self.keeper.running()), ([self.paths], False))
        self.assertEqual(sweep.call_args_list[-1], mock.call(kill=self.no_kill, all_live=True))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_desk_keeper.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.desk_keeper'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/desk_keeper.py`:

```python
"""Монтажные столы, открытые дашбордом: одно действие со столом проекта за
раз, остановка по простою и при выходе сервера, уборка реестра своих
процессов (`desk_children.sweep`).

Простой — 60 минут без обоих признаков жизни: экран «Сборка» этого проекта не
спрашивал состояние монтажа (спрашивает раз в 5 с, пока вкладка видна —
`touch`) и current/index.html не менялся (Studio пишет правку мыши на диск за
секунду). Короче нельзя: человек работает во вкладке Studio, вкладка
дашборда при этом скрыта и молчит, а правок может не быть, пока он смотрит и
слушает. Дольше незачем: Studio с браузером превью занимает сотни мегабайт,
а поднять стол снова — секунда-другая, правки уже на диске.

Столы, открытые агентом (`montage open`), здесь не учитываются — их
останавливает `montage close`. При выходе сервера останавливаются все столы,
запущенные этим процессом."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from .montage import MontageError, desk_children
from .montage.paths import MontagePaths
from .montage.proc_tree import kill_tree

IDLE_SECONDS = 60 * 60
SWEEP_SECONDS = 60.0
STOP_WAIT = 10.0


def index_stamp(paths: MontagePaths) -> tuple[int, int] | None:
    try:
        info = os.stat(paths.index)
    except OSError:
        return None
    return info.st_mtime_ns, info.st_size


@dataclass
class _Watched:
    paths: MontagePaths
    seen_at: float
    stamp: tuple | None


def _take(lock: threading.Lock, wait: float) -> bool:
    return lock.acquire(timeout=wait) if wait > 0 else lock.acquire(blocking=False)


class DeskKeeper:
    def __init__(self, *, close_desk, kill=kill_tree, clock=time.monotonic, idle=IDLE_SECONDS,
                 sweep_every=SWEEP_SECONDS, stamp=index_stamp):
        self._close_desk, self._kill, self._clock = close_desk, kill, clock
        self._idle, self._sweep_every, self._stamp = idle, sweep_every, stamp
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._watched: dict[str, _Watched] = {}
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def lock(self, project_id: str) -> threading.Lock:
        """Одно действие со столом проекта за раз: открыть, закрыть, спросить, остановить."""

        with self._guard:
            return self._locks.setdefault(project_id, threading.Lock())

    def opened(self, project_id: str, paths: MontagePaths) -> None:
        with self._guard:
            self._watched[project_id] = _Watched(paths, self._clock(), self._stamp(paths))

    def closed(self, project_id: str) -> None:
        with self._guard:
            self._watched.pop(project_id, None)

    def touch(self, project_id: str) -> None:
        with self._guard:
            watched = self._watched.get(project_id)
            if watched is not None:
                watched.seen_at = self._clock()

    def watched(self) -> list[str]:
        with self._guard:
            return sorted(self._watched)

    def sweep(self) -> list[str]:
        """Уборка реестра и остановка простаивающих столов; ответ — чьи остановлены."""

        desk_children.sweep(kill=self._kill)
        now, idle = self._clock(), []
        with self._guard:
            items = list(self._watched.items())
        for project_id, watched in items:
            stamp = self._stamp(watched.paths)
            with self._guard:
                if stamp != watched.stamp:
                    watched.stamp, watched.seen_at = stamp, now
                    continue
                expired = now - watched.seen_at >= self._idle
            if expired:
                idle.append(project_id)
        return [project_id for project_id in idle if self._stop_desk(project_id, wait=0)]

    def _stop_desk(self, project_id: str, *, wait: float) -> bool:
        lock = self.lock(project_id)
        if not _take(lock, wait):
            return False  # стол сейчас открывают или закрывают — до следующей уборки
        try:
            with self._guard:
                watched = self._watched.pop(project_id, None)
            if watched is None:
                return False
            try:
                self._close_desk(watched.paths)
            except MontageError:
                pass  # не остановился по-хорошему — выход сервера добьёт свой процесс
            return True
        finally:
            lock.release()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="aimaster-desk-keeper", daemon=True)
        self._thread.start()

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stopping.wait(self._sweep_every):
            try:
                self.sweep()
            except Exception:  # noqa: BLE001 — уборка не должна уронить сервер
                pass

    def stop(self) -> None:
        """Выход сервера: остановить уборку, закрыть свои столы, добить свои процессы."""

        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        for project_id in self.watched():
            self._stop_desk(project_id, wait=STOP_WAIT)
        desk_children.sweep(kill=self._kill, all_live=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_desk_keeper.py' -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/desk_keeper.py skills/aimaster/scripts/test_desk_keeper.py
git commit -m "feat(studio): desk keeper stops dashboard desks after an idle hour and on exit"
```

---

### Task 10: Экран «Сборка» на сервере — `EngineLookup` и `MontageScreen`

**Files:**
- Create: `skills/aimaster/studio/montage_screen.py`
- Test: `skills/aimaster/scripts/test_montage_screen.py`

**Interfaces:**
- Consumes: `service_screen.screen_status`, `screen_model`, `open_desk_for_screen`, `restore_as_owner`, `current_output` (задача 3); `service.close_desk(workspace, project_id, *, desk)`; `StudioDesk(engine)`; `engine.locate() -> (Engine | None, str)`; `DeskKeeper` (задача 9); `reveal.reveal_file`, `reveal.reveal_available` (задача 8).
- Produces:
  - `montage_screen.EngineLookup(locate=None, *, clock=time.monotonic, fresh=60.0, missing=15.0)` — вызов → `(Engine | None, str)`
  - `montage_screen.MontageScreen(workspace, *, keeper, engines, desk_factory=StudioDesk, reveal=reveal_file, reveal_ready=None, runner=None)`:
    `.status(project_id) -> dict` (задача 3 + `"reveal": bool`), `.model(project_id) -> dict`, `.open_desk(project_id) -> dict`, `.close_desk(project_id) -> dict`, `.restore(project_id, version_id, expected_revision) -> dict`, `.reveal(project_id) -> {"project_id", "shown"}`; отказы — `MontageError`

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_screen.py`:

```python
#!/usr/bin/env python3
"""MontageScreen: движок ищется не чаще раза в минуту, опрос не ждёт занятый
стол, схема читается одним потоком, стол дашборда — под присмотром хранителя."""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_built import BuiltMontage  # noqa: E402
from montage_testkit import FakeHyperframes, isolate_hyperframes_dir, tiny_mp4  # noqa: E402
from studio.desk_keeper import DeskKeeper  # noqa: E402
from studio.montage import MontageError, desk_children  # noqa: E402
from studio.montage_screen import EngineLookup, MontageScreen  # noqa: E402

STUDIO = "http://127.0.0.1:9/#project/current"
OPENER = "http://127.0.0.1:9/api/projects/current/preview/.hyperframes/aimaster-desk-open.html"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeDesk:
    def __init__(self, log, answer=None):
        self.log, self.answer = log, answer or {"state": "closed"}

    def open(self, paths):
        self.log.append("open")
        return {"state": "open", "url": STUDIO, "port": 9, "pid": 5, "started_at": "t"}

    def close(self, paths):
        self.log.append("close")
        return {"state": "closed"}

    def status(self, paths):
        self.log.append("status")
        return dict(self.answer)


class SlowTimeline(FakeHyperframes):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.timelines = 0

    def json(self, engine, args, *, cwd, timeout, ok_codes=(0,)):
        if list(args) == ["timeline", "--json"]:
            self.timelines += 1
            time.sleep(0.3)
        return super().json(engine, args, cwd=cwd, timeout=timeout, ok_codes=ok_codes)


class EngineLookupTests(unittest.TestCase):
    def test_installed_engine_is_looked_up_once_a_minute(self):
        clock, calls = FakeClock(), []
        lookup = EngineLookup(lambda: calls.append(1) or ("движок", ""), clock=clock)
        self.assertEqual(lookup(), ("движок", ""))
        clock.now += 59
        lookup()
        self.assertEqual(len(calls), 1)
        clock.now += 2
        lookup()
        self.assertEqual(len(calls), 2)

    def test_missing_engine_is_rechecked_every_fifteen_seconds(self):
        clock, calls = FakeClock(), []
        lookup = EngineLookup(lambda: calls.append(1) or (None, "не найден Node.js"), clock=clock)
        lookup()
        clock.now += 14
        lookup()
        self.assertEqual(len(calls), 1)
        clock.now += 2
        self.assertEqual(lookup(), (None, "не найден Node.js"))
        self.assertEqual(len(calls), 2)


class MontageScreenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name).resolve()
        isolate_hyperframes_dir(self, self.temp)
        registry = mock.patch.dict(desk_children._children, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        self.m = BuiltMontage(self.temp)
        self.m.draft_and_build()  # v001, ревизия 2
        self.log, self.revealed = [], []
        self.keeper = DeskKeeper(close_desk=lambda paths: None)

    def screen(self, **overrides):
        options = {"keeper": self.keeper, "engines": self.m.locate,
                   "desk_factory": lambda engine: FakeDesk(self.log),
                   "reveal": self.revealed.append, "reveal_ready": True, "runner": self.m.runner}
        options.update(overrides)
        return MontageScreen(self.m.workspace, **options)

    def test_status_asks_the_desk_and_says_whether_folders_can_be_shown(self):
        status = self.screen().status("p")
        self.assertEqual((status["desk"], status["reveal"], self.log), ({"state": "closed"}, True, ["status"]))

    def test_busy_desk_does_not_hold_the_status(self):
        lock = self.keeper.lock("p")
        lock.acquire()
        try:
            started = time.monotonic()
            status = self.screen().status("p")
        finally:
            lock.release()
        self.assertEqual((status["desk"], self.log), ({"state": "busy"}, []))
        self.assertLess(time.monotonic() - started, 2)

    def test_status_polls_keep_a_dashboard_desk_alive(self):
        clock, closed = FakeClock(), []
        keeper = DeskKeeper(close_desk=closed.append, clock=clock, idle=100)
        screen = self.screen(keeper=keeper)
        screen.open_desk("p")
        clock.now += 90
        screen.status("p")
        clock.now += 90
        self.assertEqual(keeper.sweep(), [])
        clock.now += 20
        self.assertEqual((keeper.sweep(), closed), (["p"], [self.m.paths]))

    def test_open_desk_without_engine_is_refused_in_words(self):
        screen = self.screen(engines=lambda: (None, "не найден Node.js"))
        with self.assertRaisesRegex(MontageError, "не установлен: не найден Node.js"):
            screen.open_desk("p")
        self.assertEqual((self.log, self.keeper.watched()), ([], []))

    def test_open_and_close_are_watched_by_the_keeper(self):
        screen = self.screen()
        self.assertEqual(screen.open_desk("p")["url"], OPENER)
        self.assertEqual(self.keeper.watched(), ["p"])
        self.assertEqual(screen.close_desk("p"), {"project_id": "p", "state": "closed"})
        self.assertEqual((self.keeper.watched(), self.log), ([], ["open", "close"]))

    def test_one_model_read_at_a_time(self):
        runner = SlowTimeline(render_bytes=tiny_mp4(b"out-1"))
        shutil.rmtree(self.m.paths.cache, ignore_errors=True)  # кэша нет — схему читает движок
        screen = self.screen(runner=runner)
        results = []
        threads = [threading.Thread(target=lambda: results.append(screen.model("p"))) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((runner.timelines, len(results)), (1, 2))
        self.assertEqual(results[0]["model_hash"], results[1]["model_hash"])

    def test_restore_and_reveal(self):
        screen = self.screen()
        self.assertEqual(screen.restore("p", "v001", 2)["current_version"], "v001")
        self.assertEqual(screen.reveal("p"), {"project_id": "p", "shown": "рабочая папка/media/p/montage/v001.mp4"})
        self.assertEqual(self.revealed, [self.m.seed.media / "p" / "montage" / "v001.mp4"])

    def test_reveal_needs_a_way_to_open_folders(self):
        with self.assertRaisesRegex(MontageError, "нечем открыть папку"):
            self.screen(reveal_ready=False).reveal("p")
        self.assertEqual(self.revealed, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_screen.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage_screen'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage_screen.py`:

```python
"""Экран «Сборка» со стороны сервера дашборда: ответы эндпоинтов
`/api/projects/<id>/montage…` (разбор путей и коды — `montage_routes.py`).

Всё идёт через `studio.montage.service_screen` и `service`: там проект
открывается заново и папка монтажа проверяется на ссылки. Действия со столом
проекта — по одному (`DeskKeeper.lock`); опрос состояния стол не ждёт —
занят, значит «busy». Схема слоёв одного проекта читается одним потоком за
раз: движок после правки думает до 120 с, второй запрос ждёт и берёт кэш.
Ответы — без абсолютных путей и без команды установки движка."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from .desk_keeper import DeskKeeper
from .montage import MontageError, service, service_screen
from .montage.desk import StudioDesk
from .montage.engine import locate as locate_engine
from .reveal import reveal_available, reveal_file

DESK_STATUS_WAIT = 0.2
NO_REVEAL = "на этом компьютере нечем открыть папку — путь к файлу есть на экране"


class EngineLookup:
    """`engine.locate()` не чаще раза в минуту, а пока движка нет — раз в
    15 с: он запускает `node --version`, а экран спрашивает состояние раз в
    5 с. Поставленный движок экран увидит не позже чем через 15 с."""

    def __init__(self, locate=None, *, clock=time.monotonic, fresh=60.0, missing=15.0):
        self._locate, self._clock = locate or locate_engine, clock
        self._fresh, self._missing = fresh, missing
        self._lock = threading.Lock()
        self._value, self._until = (None, ""), float("-inf")

    def __call__(self):
        with self._lock:
            now = self._clock()
            if now >= self._until:
                self._value = self._locate()
                self._until = now + (self._fresh if self._value[0] is not None else self._missing)
            return self._value


class MontageScreen:
    def __init__(self, workspace, *, keeper: DeskKeeper, engines, desk_factory=StudioDesk,
                 reveal=reveal_file, reveal_ready: bool | None = None, runner=None):
        self.workspace = Path(workspace)
        self.keeper, self.engines, self.desk_factory = keeper, engines, desk_factory
        self.reveal_file, self.runner = reveal, runner
        self.reveal_ready = reveal_available() if reveal_ready is None else reveal_ready
        self._guard = threading.Lock()
        self._model_locks: dict[str, threading.Lock] = {}

    def status(self, project_id: str) -> dict:
        self.keeper.touch(project_id)
        result = service_screen.screen_status(
            self.workspace, project_id, locate=self.engines,
            desk_state=lambda paths: self._desk_state(project_id, paths))
        if result.get("applicable"):
            result["reveal"] = self.reveal_ready
        return result

    def _desk_state(self, project_id: str, paths) -> dict:
        lock = self.keeper.lock(project_id)
        if not lock.acquire(timeout=DESK_STATUS_WAIT):
            return {"state": "busy"}
        try:
            return self.desk_factory(None).status(paths)
        finally:
            lock.release()

    def model(self, project_id: str) -> dict:
        with self._guard:
            lock = self._model_locks.setdefault(project_id, threading.Lock())
        with lock:
            return service_screen.screen_model(self.workspace, project_id, locate=self.engines,
                                               runner=self.runner)

    def open_desk(self, project_id: str) -> dict:
        with self.keeper.lock(project_id):
            engine, reason = self.engines()
            if engine is None:
                raise MontageError(f"монтажный стол не установлен: {reason}")
            view, paths = service_screen.open_desk_for_screen(
                self.workspace, project_id, desk=self.desk_factory(engine))
            self.keeper.opened(project_id, paths)
            return view

    def close_desk(self, project_id: str) -> dict:
        with self.keeper.lock(project_id):
            closed = service.close_desk(self.workspace, project_id, desk=self.desk_factory(None))
            self.keeper.closed(project_id)
            return closed

    def restore(self, project_id: str, version_id: str, expected_revision: int) -> dict:
        return service_screen.restore_as_owner(self.workspace, project_id, expected_revision,
                                               version_id)

    def reveal(self, project_id: str) -> dict:
        if not self.reveal_ready:
            raise MontageError(NO_REVEAL)
        target, shown = service_screen.current_output(self.workspace, project_id)
        self.reveal_file(target)
        return {"project_id": project_id, "shown": shown}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_screen.py' -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage_screen.py skills/aimaster/scripts/test_montage_screen.py
git commit -m "feat(studio): assembly screen answers — cached engine lookup, one desk action per project"
```

---

### Task 11: Маршруты `/api/projects/<id>/montage…` и подключение к серверу

**Files:**
- Create: `skills/aimaster/studio/montage_routes.py`
- Modify: `skills/aimaster/studio/http_app.py` (импорт, `__init__(…, montage=None)`, ветка в `handle`)
- Modify: `skills/aimaster/studio/server.py` (импорты, `RunningServer`, `serve()`)
- Modify: `skills/aimaster/scripts/creator_studio.py` (`import signal`, `_stop_on_sigterm`, первая строка `command_serve`)
- Test: `skills/aimaster/scripts/test_montage_http.py`

**Interfaces:**
- Consumes: `MontageScreen` (задача 10), `DeskKeeper` (задача 9), `StudioDesk`; `StudioApplication._parse_json(headers, body, expected_keys)`, `._json_response(status, value)`, `.error_response(status, code, **fields)`, `_authorize_write` (вызывается в `handle` для любого POST); `ledger.InvalidAction`, `authoring_support.AuthoringError`, `montage.MontageError`, `paths.VERSION_ID`.
- Produces:
  - `montage_routes.match(path: str) -> tuple[str, str | None] | None`
  - `montage_routes.route(app, screen, method, project_id, part, headers, body) -> Response`
  - `StudioApplication(..., montage=None)`, атрибут `.montage`
  - `RunningServer._desk_keeper`; `serve()` запускает хранитель, `close()` его останавливает
  - `creator_studio.py serve`: SIGTERM закрывает дашборд так же, как Ctrl+C (код выхода 0, `RunningServer.close()` — и столы дашборда)
  - HTTP: `GET …/montage` → 200 состояние; `GET …/montage/model` → 200 схема; `POST …/montage/desk` `{}` → 200 `{"project_id","state":"open","url","telemetry_off"[,"note"|"forgotten"]}`; `POST …/montage/desk/close` `{}` → 200 `{"project_id","state":"closed"[,…]}`; `POST …/montage/restore` `{"version","expected_revision"}` → 200 `{"project_id","revision","current_version"}`; `POST …/montage/reveal` `{}` → 200 `{"project_id","shown"}`; отказ монтажа → 422 `{"error":{"code":"montage_refused","message":"…"}}`; устаревшая ревизия → 409 `revision_conflict`; тело не по схеме → 400; без Origin/CSRF → 403; нет экрана или неизвестная часть → 404

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_http.py`:

```python
#!/usr/bin/env python3
"""Эндпоинты экрана «Сборка»: запись только с Origin и CSRF дашборда, отказы
монтажа — текстом, «Сделать текущей» — от имени человека, выход сервера
останавливает столы дашборда."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_built import BuiltMontage  # noqa: E402
from montage_testkit import isolate_hyperframes_dir  # noqa: E402
from studio.desk_keeper import DeskKeeper  # noqa: E402
from studio.montage import desk_children  # noqa: E402
from studio.montage.engine import PREFIX_ENV  # noqa: E402
from studio.montage_screen import MontageScreen  # noqa: E402
from studio.server import serve  # noqa: E402

STUDIO = "http://127.0.0.1:9/#project/current"
OPENER = "http://127.0.0.1:9/api/projects/current/preview/.hyperframes/aimaster-desk-open.html"
RESTORE = "/api/projects/p/montage/restore"


class FakeDesk:
    def __init__(self, log):
        self.log = log

    def open(self, paths):
        self.log.append("open")
        return {"state": "open", "url": STUDIO, "port": 9, "pid": 5, "started_at": "t"}

    def close(self, paths):
        self.log.append("close")
        return {"state": "closed"}

    def status(self, paths):
        return {"state": "closed"}


class MontageHttpTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name).resolve()
        isolate_hyperframes_dir(self, self.temp)
        registry = mock.patch.dict(desk_children._children, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        self.m = BuiltMontage(self.temp)
        self.m.draft_and_build()  # v001, ревизия 2
        self.running = serve(self.m.workspace)
        self.addCleanup(self.running.close)
        self.app = self.running.application
        self.desk_log, self.revealed = [], []
        self.keeper = DeskKeeper(close_desk=lambda paths: None)
        self.app.montage = MontageScreen(
            self.m.workspace, keeper=self.keeper, engines=self.m.locate,
            desk_factory=lambda engine: FakeDesk(self.desk_log), reveal=self.revealed.append,
            reveal_ready=True, runner=self.m.runner)

    def call(self, method, path, body=None, *, origin=True, token=True):
        headers = [("Host", self.app.authority)]
        raw = b""
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            headers.append(("Content-Type", "application/json"))
        if method == "POST" and origin is not False:
            headers.append(("Origin", self.app.origin if origin is True else origin))
        if method == "POST" and token is not False:
            headers.append(("X-CSRF-Token", self.app.csrf_token if token is True else token))
        response = self.app.handle(method, path, headers, raw)
        return response.status, json.loads(response.body.decode("utf-8"))

    def edit_state(self, change):
        path = self.m.workspace / "projects" / "p" / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        change(state)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def test_status_has_no_absolute_paths_and_no_install_command(self):
        status, body = self.call("GET", "/api/projects/p/montage")
        self.assertEqual(status, 200)
        self.assertNotIn(str(self.temp), json.dumps(body, ensure_ascii=False))
        self.assertEqual(set(body["engine"]), {"state", "version", "reason"})
        self.assertEqual(body["file"], {"version": "v001", "shown": "рабочая папка/media/p/montage/v001.mp4"})
        self.assertEqual((body["desk"], body["reveal"], body["current_version"]), ({"state": "closed"}, True, "v001"))

    def test_model_part(self):
        status, body = self.call("GET", "/api/projects/p/montage/model")
        self.assertEqual((status, len(body["layers"]), body["unrendered_changes"]), (200, 6, False))

    def test_writes_need_the_dashboard_origin_and_csrf(self):
        for origin, token in ((False, True), ("http://evil.test", True), (True, False), (True, "wrong-token")):
            with self.subTest(origin=origin, token=token):
                status, body = self.call("POST", RESTORE, {"version": "v001", "expected_revision": 2},
                                         origin=origin, token=token)
                self.assertEqual((status, body["error"]["code"]), (403, "forbidden"))
        for part in ("desk", "desk/close", "reveal"):
            with self.subTest(part=part):
                self.assertEqual(self.call("POST", f"/api/projects/p/montage/{part}", {}, token=False)[0], 403)
        self.assertEqual((self.m.state()["revision"], self.desk_log, self.revealed), (2, [], []))

    def test_restore_is_written_as_the_person(self):
        status, body = self.call("POST", RESTORE, {"version": "v001", "expected_revision": 2})
        self.assertEqual((status, body), (200, {"project_id": "p", "revision": 3, "current_version": "v001"}))
        last = self.m.state()["history"][-1]
        self.assertEqual((last["actor"], last["kind"]), ("you", "montage-restored"))

    def test_stale_revision_is_a_conflict(self):
        status, body = self.call("POST", RESTORE, {"version": "v001", "expected_revision": 1})
        self.assertEqual((status, body["error"]["code"], body["error"]["current_revision"]),
                         (409, "revision_conflict", 2))

    def test_montage_refusal_comes_back_as_text(self):
        status, body = self.call("POST", RESTORE, {"version": "v009", "expected_revision": 2})
        self.assertEqual((status, body["error"]["code"]), (422, "montage_refused"))
        self.assertIn("нет версии v009", body["error"]["message"])

    def test_approved_assembly_refuses_in_words(self):
        self.edit_state(lambda state: state["milestones"].__setitem__("assembly", "approved"))
        status, body = self.call("POST", RESTORE, {"version": "v001", "expected_revision": 2})
        self.assertEqual((status, body["error"]["code"]), (422, "montage_refused"))
        self.assertIn("уже одобрен", body["error"]["message"])

    def test_malformed_restore_is_a_bad_request(self):
        for payload in ({"version": "1", "expected_revision": 2}, {"version": "v001", "expected_revision": True},
                        {"version": "v001"}, {"version": "v001", "expected_revision": 2, "x": 1}):
            with self.subTest(payload=payload):
                self.assertEqual(self.call("POST", RESTORE, payload)[0], 400)

    def test_desk_opens_through_the_opener_page_and_closes(self):
        status, body = self.call("POST", "/api/projects/p/montage/desk", {})
        self.assertEqual((status, body), (200, {"project_id": "p", "state": "open", "url": OPENER,
                                                "telemetry_off": True}))
        self.assertEqual(self.keeper.watched(), ["p"])
        status, body = self.call("POST", "/api/projects/p/montage/desk/close", {})
        self.assertEqual((status, body["state"]), (200, "closed"))
        self.assertEqual((self.keeper.watched(), self.desk_log), ([], ["open", "close"]))

    def test_reveal_shows_the_current_file(self):
        status, body = self.call("POST", "/api/projects/p/montage/reveal", {})
        self.assertEqual((status, body), (200, {"project_id": "p", "shown": "рабочая папка/media/p/montage/v001.mp4"}))
        self.assertEqual(self.revealed, [self.m.seed.media / "p" / "montage" / "v001.mp4"])

    def test_photo_project_has_no_montage_screen(self):
        self.edit_state(lambda state: state["project"].__setitem__("type", "photo"))
        status, body = self.call("GET", "/api/projects/p/montage")
        self.assertEqual((status, body["applicable"]), (200, False))

    def test_unknown_part_and_missing_screen_are_404(self):
        self.assertEqual(self.call("GET", "/api/projects/p/montage/other")[0], 404)
        self.app.montage = None
        self.assertEqual(self.call("GET", "/api/projects/p/montage")[0], 404)

    def test_server_close_stops_the_desks_of_the_dashboard(self):
        real_stop = DeskKeeper.stop
        with mock.patch.object(DeskKeeper, "stop", autospec=True, side_effect=real_stop) as stop:
            self.running.close()
        stop.assert_called_once()


@unittest.skipIf(os.name == "nt", "на Windows SIGTERM не перехватить: TerminateProcess")
class ServeStopsOnTermTests(unittest.TestCase):
    """Дашборд, остановленный SIGTERM (агент, launchd, `kill`), закрывается так
    же, как по Ctrl+C: `RunningServer.close()` — и столы, открытые им, тоже."""

    def test_sigterm_closes_the_dashboard_like_ctrl_c(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "рабочая папка"
            (workspace / "projects").mkdir(parents=True)
            env = {**os.environ, PREFIX_ENV: str(Path(temp) / "нет-движка")}
            proc = subprocess.Popen([sys.executable, str(_SCRIPTS / "creator_studio.py"), "serve",
                                     str(workspace)], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, env=env)
            try:
                self.assertIn(b"base_url", proc.stdout.readline())
                proc.send_signal(signal.SIGTERM)
                self.assertEqual(proc.wait(timeout=30), 0)  # без обработчика было бы -15
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_http.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage_routes'` (через `studio.server` → `studio.http_app`) либо `404` на всех маршрутах.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage_routes.py`:

```python
"""Маршруты экрана «Сборка»: `/api/projects/<id>/montage…`.

    GET  …/montage             дешёвое состояние (экран спрашивает раз в 5 с)
    GET  …/montage/model       схема слоёв (когда сменился index_key)
    POST …/montage/desk        {} → открыть стол; адрес страницы-переходника
    POST …/montage/desk/close  {} → закрыть стол
    POST …/montage/restore     {"version": "v001", "expected_revision": N}
    POST …/montage/reveal      {} → «Показать в папке» (файл текущей версии)

Любой POST доходит сюда только после `_authorize_write` (Origin и CSRF) — его
зовёт `StudioApplication.handle` до разбора маршрута. Отказ монтажа и запрет
по стадии — 422 `montage_refused` с русским текстом в `message`: запрет
по стадии (`AuthoringError`) — наследник ValueError, и `handle` превратил
бы его в немой 400. Устаревшая ревизия — 409 `revision_conflict`, как у
`/api/actions`."""

from __future__ import annotations

import re

from .authoring_support import AuthoringError
from .ledger import InvalidAction
from .montage import MontageError
from .montage.paths import VERSION_ID

ROUTE = re.compile(r"/api/projects/([^/]+)/montage(?:/(model|desk|desk/close|restore|reveal))?")
_GET = {None: "status", "model": "model"}
_POST = {"desk": "open_desk", "desk/close": "close_desk", "reveal": "reveal"}
_RESTORE_KEYS = {"version", "expected_revision"}


def match(path: str) -> tuple[str, str | None] | None:
    found = ROUTE.fullmatch(path)
    return (found.group(1), found.group(2)) if found else None


def _restore_args(request: dict) -> tuple[str, int]:
    version, revision = request["version"], request["expected_revision"]
    if not isinstance(version, str) or not VERSION_ID.fullmatch(version):
        raise InvalidAction("version must look like v001")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise InvalidAction("expected_revision must be a non-negative integer")
    return version, revision


def route(app, screen, method, project_id, part, headers, body):
    if screen is None:
        return app.error_response(404, "not_found")
    try:
        if method == "GET" and part in _GET:
            return app._json_response(200, getattr(screen, _GET[part])(project_id))
        if method == "POST" and part == "restore":
            version, revision = _restore_args(app._parse_json(headers, body, _RESTORE_KEYS))
            return app._json_response(200, screen.restore(project_id, version, revision))
        if method == "POST" and part in _POST:
            app._parse_json(headers, body, set())
            return app._json_response(200, getattr(screen, _POST[part])(project_id))
    except (MontageError, AuthoringError) as error:
        return app.error_response(422, "montage_refused", message=str(error))
    return app.error_response(404, "not_found")
```

В `skills/aimaster/studio/http_app.py`:

1. После `from .asset_download import content_disposition, download_names` добавить:

```python
from .montage_routes import match as match_montage
from .montage_routes import route as route_montage
```

2. В сигнатуре `StudioApplication.__init__` после `max_body_bytes: int = MAX_BODY_BYTES,` добавить параметр `montage=None,`, а после `self.verified_files = VerifiedFiles()` — строку:

```python
        # Экран «Сборка» (studio/montage_screen.py); None — маршрутов монтажа нет (404).
        self.montage = montage
```

3. В `handle` сразу после строки `return self._events(request_headers)` (ветка `/api/events`) добавить:

```python
            montage_route = match_montage(request_path)
            if montage_route is not None and method in {"GET", "POST"}:
                return route_montage(self, self.montage, method, *montage_route,
                                     request_headers, body)
```

В `skills/aimaster/studio/server.py`:

1. Импорты — после `from .decisions import DecisionWorker`:

```python
from .desk_keeper import DeskKeeper
```

и после `from .loopback_http import LoopbackThreadingHTTPServer`:

```python
from .montage.desk import StudioDesk
from .montage_screen import EngineLookup, MontageScreen
```

2. В `RunningServer` после поля `_decision_worker: DecisionWorker` добавить поле `_desk_keeper: DeskKeeper`, а в `close()` после `self._thread.join(timeout=5)`:

```python
        # План Б: после HTTP новых открытий стола не будет; столы, которые
        # открыл этот дашборд, останавливаются вместе с ним.
        self._desk_keeper.stop()
```

3. В `serve()` перед `httpd = _LoopbackHTTPServer((host, port), _Handler)`:

```python
    # План Б, экран «Сборка»: столы, открытые дашбордом, — под присмотром
    # хранителя (простой, выход сервера). Сам дашборд ролик не собирает.
    desk_keeper = DeskKeeper(close_desk=lambda paths: StudioDesk(None).close(paths))
    montage = MontageScreen(workspace, keeper=desk_keeper, engines=EngineLookup())
```

в вызов `StudioApplication(...)` добавить аргумент `montage=montage,` (после `event_source=events,`), после `decision_worker.start()` — строку `desk_keeper.start()`, а последнюю строку заменить на:

```python
    return RunningServer(base_url, application, httpd, thread, decision_worker, desk_keeper)
```

В `skills/aimaster/scripts/creator_studio.py` к импортам стандартной библиотеки добавить `import signal` (после `import json`), а перед `def command_serve(args):` — функцию, и вызвать её первой строкой `command_serve`:

```python
def _stop_on_sigterm() -> None:
    """SIGTERM (агент, launchd, `kill`) — как Ctrl+C: `finally` в command_serve
    закроет сервер, а с ним и монтажные столы, открытые дашбордом
    (studio/desk_keeper.py). Без этого процесс умер бы, не закрыв их."""

    def stop(signum, frame):
        raise KeyboardInterrupt

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop)


def command_serve(args):
    _stop_on_sigterm()
    running = serve(args.workspace, port=args.port)
```

(остаток `command_serve` — печать `base_url`, ожидание, `except KeyboardInterrupt`, `finally: running.close()` — без изменений.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_http.py' -v`
Expected: PASS (14 tests; на Windows `ServeStopsOnTermTests` — skipped).

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_http_stream.py' -v && python3 -m unittest discover -s skills/aimaster/scripts -p 'test_asset_download.py' -v`
Expected: PASS (сервер с хранителем открывается и закрывается).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage_routes.py skills/aimaster/studio/http_app.py skills/aimaster/studio/server.py skills/aimaster/scripts/creator_studio.py skills/aimaster/scripts/test_montage_http.py
git commit -m "feat(studio): /api/projects/<id>/montage endpoints behind Origin and CSRF, keeper in serve()"
```

---

### Task 12: Шлюз Mini App не пускает к столу и к папке

**Files:**
- Modify: `skills/aimaster/studio/mini_app.py` (импорты, `_LOCAL_ONLY`, `MiniAppGateway._local_only`, начало `handle`)
- Test: `skills/aimaster/scripts/test_mini_app.py` (новый класс)

**Interfaces:**
- Consumes: `MiniAppGateway._forbidden()`, `MiniAppGateway.handle(method, path, headers, body)`.
- Produces: `MiniAppGateway._local_only(path: str) -> bool` — `True` для `/api/projects/<id>/montage/desk`, `…/desk/close`, `…/reveal` (с `/` на конце и в любом процентном написании); такие запросы — 403 до проверки входа и без обращения к дашборду. Состояние, схема и `…/montage/restore` через шлюз проходят (после проверки входа).

- [ ] **Step 1: Write the failing test**

Добавить в `skills/aimaster/scripts/test_mini_app.py` перед `class MiniAppFramingTests`:

```python
class MiniAppMontageTests(unittest.TestCase):
    """План Б: монтажный стол и «Показать в папке» — только на компьютере
    владельца; через шлюз (телефон, туннель) — 403, дашборд не зовётся."""

    def setUp(self):
        self.token = "123456:" + "a" * 32
        self.inner = _StubInner()
        self.gateway = MiniAppGateway(self.inner, self.token, 501)
        self.auth = ("Authorization", "tma " + init_data(self.token, 501, int(time.time())))

    def post(self, target):
        return self.gateway.handle("POST", target, [("Host", "public"), self.auth,
                                                    ("Content-Type", "application/json")], b"{}")

    def test_desk_and_reveal_are_refused_in_any_spelling(self):
        for target in ("/api/projects/p/montage/desk", "/api/projects/p/montage/desk/close",
                       "/api/projects/p/montage/reveal", "/api/projects/p/montage/desk/",
                       "/api/projects/p/montage%2Fdesk", "/api/projects/p/montage%2freveal",
                       "/api/projects/p%20x/montage/desk%2Fclose"):
            with self.subTest(target=target):
                self.assertEqual(self.post(target).status, 403)
        self.assertEqual(self.inner.calls, [])

    def test_state_model_and_restore_pass_after_login(self):
        get = self.gateway.handle("GET", "/api/projects/p/montage", [("Host", "public"), self.auth], b"")
        model = self.gateway.handle("GET", "/api/projects/p/montage/model", [("Host", "public"), self.auth], b"")
        restore = self.post("/api/projects/p/montage/restore")
        self.assertEqual((get.status, model.status, restore.status), (200, 200, 200))
        self.assertEqual([call[1] for call in self.inner.calls],
                         ["/api/projects/p/montage", "/api/projects/p/montage/model",
                          "/api/projects/p/montage/restore"])

    def test_restore_without_login_is_still_refused(self):
        denied = self.gateway.handle("POST", "/api/projects/p/montage/restore",
                                     [("Host", "public"), ("Content-Type", "application/json")], b"{}")
        self.assertEqual((denied.status, self.inner.calls), (403, []))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_mini_app.py' -k MiniAppMontage -v`
Expected: FAIL — `test_desk_and_reveal_are_refused_in_any_spelling`: `200 != 403`.

- [ ] **Step 3: Write minimal implementation**

В `skills/aimaster/studio/mini_app.py`:

1. Строку `from urllib.parse import parse_qsl, urlsplit` заменить на:

```python
import re
from urllib.parse import parse_qsl, unquote, urlsplit
```

(`import re` — в блок стандартных импортов по алфавиту, после `import json`.)

2. После импортов, перед `def validate_init_data`:

```python
# План Б (экран «Сборка»): монтажный стол и «Показать в папке» — только на
# компьютере владельца. Через шлюз (телефон, туннель) их нет: Studio наружу не
# выставляется, а папка открылась бы на компьютере, а не у человека в руках.
_LOCAL_ONLY = re.compile(r"/api/projects/[^/]+/montage/(?:desk|desk/close|reveal)/?")
```

3. В `MiniAppGateway` перед `def handle`:

```python
    @staticmethod
    def _local_only(path: str) -> bool:
        """Путь стола или папки — в том виде, в каком его увидит дашборд
        (`http_app._path` раскодирует процентные последовательности)."""

        try:
            decoded = unquote(path, errors="strict")
        except (UnicodeDecodeError, ValueError):
            return True
        return _LOCAL_ONLY.fullmatch(decoded) is not None
```

4. В `handle` сразу после `parsed = urlsplit(path)`:

```python
        if self._local_only(parsed.path):
            return self._forbidden()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_mini_app.py' -v`
Expected: PASS (3 новых теста и все прежние).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/mini_app.py skills/aimaster/scripts/test_mini_app.py
git commit -m "fix(mini-app): gateway refuses the montage desk and reveal-in-folder"
```

---

### Task 13: Промпты «Собрать ролик → чат», «Установить → чат», «Обновить клипы → чат»

**Files:**
- Modify: `skills/aimaster/studio/static/ui/v2/screen-prompts.js` (шапка файла, `assembleFinal` и новое после неё)
- Modify: `skills/aimaster/studio/static/ui/v2/viewer.js:14` и `:283-287` (надпись и аргументы кнопки сборки)
- Modify: `skills/aimaster/studio/static/ui/v2/screen-assembly.js:13` и `:75-79` (надпись карточки — до переделки экрана в задаче 18)
- Test: `skills/aimaster/studio/static/ui/v2/screen-prompts.test.mjs` (новый)

**Interfaces:**
- Consumes: `chat-prompts.projectRef(project, revision)`.
- Produces:
  - `ASSEMBLE_LABEL = "Собрать ролик → чат"`, `assembleLabel(project) -> string` («Собрать → чат» у фото)
  - `assembleFinal(project, revision) -> {title, prompt}` — видео/смешанный: монтаж по канону (`montage status` → `montage draft`, если черновика нет → `montage diff` и пересказ → сразу `montage render --by owner`, бесплатно, без подтверждения); фото: `assembly set`
  - `installMontage(project, revision) -> {title, prompt}`
  - `updateMontageClips(project, revision) -> {title, prompt}`

- [ ] **Step 1: Write the failing test**

`skills/aimaster/studio/static/ui/v2/screen-prompts.test.mjs`:

```js
// node --test skills/aimaster/studio/static/ui/v2/screen-prompts.test.mjs
//
// Промпты экрана «Сборка» по канону монтажа (references/montage.md): сборка
// бесплатная и локальная — агент собирает сразу, без плана и подтверждения;
// установка — командой из montage status, путей в тексте нет.

import test from "node:test";
import assert from "node:assert/strict";

import {
  ASSEMBLE_LABEL, assembleFinal, assembleLabel, installMontage, updateMontageClips,
} from "./screen-prompts.js";
import { projectWith } from "./snapshot.fixture.mjs";

const VIDEO = projectWith({ type: "video" });
const PHOTO = projectWith({ type: "photo" });
const PATHS = /\/Users\/|[A-Za-z]:\\|\/home\//;

test("«Собрать ролик → чат» — одна надпись; у фото — «Собрать → чат»", () => {
  assert.equal(ASSEMBLE_LABEL, "Собрать ролик → чат");
  assert.equal(assembleLabel(VIDEO), "Собрать ролик → чат");
  assert.equal(assembleLabel(projectWith({ type: "mixed" })), "Собрать ролик → чат");
  assert.equal(assembleLabel(PHOTO), "Собрать → чат");
});

test("сборка видео: diff и пересказ, затем сразу render --by owner, без подтверждения", () => {
  const { title, prompt } = assembleFinal(VIDEO, 62);
  assert.equal(title, "Собрать ролик");
  assert.match(prompt, /project_id «dashboard-dialogue»/);
  assert.match(prompt, /snapshot revision 62/);
  assert.match(prompt, /references\/montage\.md/);
  assert.match(prompt, /montage diff/);
  assert.match(prompt, /montage render --by owner/);
  assert.match(prompt, /бесплатная, подтверждения не нужно/);
  assert.match(prompt, /копию не собирай/);
  assert.doesNotMatch(prompt, /платное действие|дождись моего подтверждения/);
});

test("нет черновика — тот же промпт велит сделать его montage draft", () => {
  assert.match(assembleFinal(VIDEO, 1).prompt, /нет черновика — сделай его \(montage draft\)/);
});

test("фото-проект собирается принятой картинкой, без монтажа", () => {
  const { title, prompt } = assembleFinal(PHOTO, 3);
  assert.equal(title, "Собрать итог");
  assert.match(prompt, /assembly set/);
  assert.doesNotMatch(prompt, /montage/);
});

test("«Установить → чат» — команда из montage status, без путей", () => {
  const { title, prompt } = installMontage(VIDEO, 62);
  assert.equal(title, "Установить монтажный стол");
  assert.match(prompt, /engine\.install_argv/);
  assert.match(prompt, /бесплатный/);
  assert.doesNotMatch(prompt, PATHS);
});

test("«Обновить клипы → чат» — refresh сразу, rebuild только по слову", () => {
  const { title, prompt } = updateMontageClips(VIDEO, 62);
  assert.equal(title, "Обновить клипы в монтаже");
  assert.match(prompt, /stale_clips/);
  assert.match(prompt, /montage draft --refresh/);
  assert.match(prompt, /дождись моего ответа/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test skills/aimaster/studio/static/ui/v2/screen-prompts.test.mjs`
Expected: FAIL — `SyntaxError: The requested module './screen-prompts.js' does not provide an export named 'ASSEMBLE_LABEL'`.

- [ ] **Step 3: Write minimal implementation**

В `skills/aimaster/studio/static/ui/v2/screen-prompts.js` шапку (строки 1–4) дополнить двумя строками после «Чистые функции: возвращают `{title, prompt}` и ничего не открывают.»:

```js
// Сборка видео — монтаж (references/montage.md): бесплатно и локально,
// агент собирает сразу, без плана и подтверждения.
```

и функцию `assembleFinal` (строки 47–55) заменить на:

```js
/** Надпись кнопки сборки: у видео — монтаж ролика, у фото — итог-картинка. */
export const ASSEMBLE_LABEL = "Собрать ролик → чат";

export function assembleLabel(project) {
  return project?.type === "photo" ? "Собрать → чат" : ASSEMBLE_LABEL;
}

/** «Собрать ролик → чат»: новая версия монтажа или итог фото-проекта. */
export function assembleFinal(project, revision) {
  const ref = projectRef(project, revision);
  if (project?.type === "photo") {
    return {
      title: "Собрать итог",
      prompt: `Открой ${ref}. Это фото-проект: его сборка — принятая картинка. Проверь, что она `
        + `выбрана и принята, и запиши сборку штатной командой Creator Studio (assembly set). `
        + `Это бесплатно, подтверждения не нужно. Недостающее ничем не подменяй — честно скажи, `
        + `чего не хватает.`,
    };
  }
  return {
    title: "Собрать ролик",
    prompt: `Открой ${ref}. Собери новую версию ролика по references/montage.md. Начни с montage `
      + `status: нет движка — предложи установку и дождись ответа; нет черновика — сделай его `
      + `(montage draft); черновик есть — прочитай montage diff и перескажи изменения простыми `
      + `словами, без номеров клипов. Изменений нет — так и скажи и копию не собирай. Затем сразу `
      + `montage render --by owner: сборка локальная и бесплатная, подтверждения не нужно. В конце `
      + `назови новую версию, её длину и что в ней изменилось. Недостающие клипы ничем не `
      + `подменяй — скажи, чего не хватает.`,
  };
}

/** «Установить → чат»: монтажного движка нет. Команду агент берёт из montage status —
 * на экране путей нет. */
export function installMontage(project, revision) {
  return {
    title: "Установить монтажный стол",
    prompt: `Открой ${projectRef(project, revision)}. Установи монтажный движок HyperFrames — он `
      + `бесплатный, около 330 МБ, ставится один раз. Команду возьми из ответа montage status: `
      + `engine.install_argv (или строку engine.install) — и выполни её. Потом снова montage `
      + `status; движок готов — продолжай сборку по references/montage.md. Не вышло — покажи `
      + `строки установщика про монтаж.`,
  };
}

/** «Обновить клипы → чат»: после черновика в проекте выбрали другие клипы или звук. */
export function updateMontageClips(project, revision) {
  return {
    title: "Обновить клипы в монтаже",
    prompt: `Открой ${projectRef(project, revision)}. После чернового монтажа в проекте выбрали `
      + `другие клипы или звук. Прочитай montage status → stale_clips. Где reason пустой — обнови `
      + `монтаж: montage draft --refresh. Где «нужен --rebuild» — объясни, что пропадут титры и `
      + `правки со стола, и дождись моего ответа. Где «нет принятого» — скажи, что выбрать. `
      + `Потом собери новую версию по references/montage.md.`,
  };
}
```

В `skills/aimaster/studio/static/ui/v2/viewer.js` строку 14 `import { assembleFinal } from "./screen-prompts.js";` заменить на:

```js
import { assembleFinal, assembleLabel } from "./screen-prompts.js";
```

и блок (строки 283–287)

```js
    secondary: final
      ? {
        label: strip.total ? "Пересобрать → чат" : "Собрать → чат",
        request: assembleFinal(project, snapshot.revision, { ready: strip.total > 0 }),
      }
```

на

```js
    secondary: final
      ? { label: assembleLabel(project), request: assembleFinal(project, snapshot.revision) }
```

В `skills/aimaster/studio/static/ui/v2/screen-assembly.js` строку 13 `import { assembleFinal } from "./screen-prompts.js";` заменить на `import { assembleFinal, assembleLabel } from "./screen-prompts.js";`, а блок строк 75–79

```js
  card.append(chatButton(
    state.ready ? "Собрать заново → чат" : "Собрать → чат",
    assembleFinal(project, revision, { ready: state.ready }),
    "v2-chat-button v2-card-button",
  ));
```

на

```js
  card.append(chatButton(assembleLabel(project), assembleFinal(project, revision),
    "v2-chat-button v2-card-button"));
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test skills/aimaster/studio/static/ui/v2/screen-prompts.test.mjs`
Expected: PASS (6 tests).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст; `grep -rn "Пересобрать → чат" skills/aimaster/studio/static/ui/v2/*.js` и `grep -n "платное действие" skills/aimaster/studio/static/ui/v2/screen-prompts.js` — пусто («платное действие» в `chat-prompts.js` — про генерации, так и должно быть; комментарии `screen-assembly.js` со старой надписью уходят в задаче 18).

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/static/ui/v2/screen-prompts.js skills/aimaster/studio/static/ui/v2/viewer.js skills/aimaster/studio/static/ui/v2/screen-assembly.js skills/aimaster/studio/static/ui/v2/screen-prompts.test.mjs
git commit -m "feat(dashboard): «Собрать ролик → чат» builds at once by the montage canon; install and refresh prompts"
```

---

### Task 14: Модель экрана монтажа — версии, флаги, плашки

**Files:**
- Create: `skills/aimaster/studio/static/ui/v2/montage-model.js`
- Modify: `skills/aimaster/studio/static/ui/v2/responsive.js` (`inTelegram`)
- Test: `skills/aimaster/studio/static/ui/v2/montage-model.test.mjs` (новый), `skills/aimaster/studio/static/ui/v2/responsive.test.mjs` (+1 тест)

**Interfaces:**
- Consumes: снимок `project.montage` (`current_version`, `versions[{id, asset_url, created_at, by, based_on, summary}]`, `canvas`), `project.assembly.asset_url`, `project.scenes[].end_ms`; ответ состояния (задачи 2–3, 10) и схемы (задача 2).
- Produces (все чистые):
  - `montageApplies(project) -> boolean`; `montageScreen(project) -> boolean` (монтажная раскладка: видео/смешанный и есть монтаж либо ещё нет итога)
  - `versionLabel(id) -> string` («v003» → «v3»), `whenText(iso) -> string` («28.09, 14:05»)
  - `versionRows(project) -> {id, label, who, when, summary, current, assetUrl}[]` — новые первыми
  - `downloadHref(url) -> string | null`
  - `screenFlags({status, finished, phone, telegram}) -> {engine: "installed"|"missing"|"unknown", desk: "hidden"|"closed"|"open"|"busy", deskUrl, deskHint, reveal, restore, build}`
  - `notices({status, model, feedError}) -> {key, tone: "warn"|"error"|"info", text, action?: "build"|"refresh"}[]`
  - `orientation(canvas) -> "portrait"|"landscape"|"square"`, `durationText({status, model, project}) -> string`
  - `responsive.inTelegram() -> boolean`

- [ ] **Step 1: Write the failing test**

`skills/aimaster/studio/static/ui/v2/montage-model.test.mjs`:

```js
// node --test skills/aimaster/studio/static/ui/v2/montage-model.test.mjs
//
// Экран «Сборка» монтажа — что человек увидит по снимку проекта и ответам
// `GET …/montage` и `GET …/montage/model`. Только чистые функции.

import test from "node:test";
import assert from "node:assert/strict";

import {
  downloadHref, durationText, montageApplies, montageScreen, notices, orientation, screenFlags,
  versionLabel, versionRows, whenText,
} from "./montage-model.js";
import { PROJECT, projectWith } from "./snapshot.fixture.mjs";

const AT = new Date(2026, 8, 28, 14, 5).toISOString();
const MONTAGE = {
  current_version: "v002",
  canvas: { width: 1080, height: 1920 },
  versions: [
    { id: "v001", asset_id: "asset-1", asset_url: "/assets/asset-1", created_at: AT, by: "agent",
      based_on: null, summary: "черновой монтаж: 3 клипа, 0:15" },
    { id: "v002", asset_id: "asset-2", asset_url: "/assets/asset-2", created_at: AT, by: "owner",
      based_on: "v001", summary: "" },
  ],
};
const STATUS = Object.freeze({
  project_id: "p", revision: 7, applicable: true,
  engine: { state: "installed", version: "0.8.75", reason: "" },
  exists: true, current_version: "v002", canvas: { width: 1080, height: 1920 },
  index_key: "k1", unrendered_changes: false,
  file: { version: "v002", shown: "рабочая папка/media/p/montage/v002.mp4" },
  desk: { state: "closed" }, reveal: true,
});
const status = (patch = {}) => ({ ...structuredClone(STATUS), ...patch });

test("монтаж — у видео и смешанных проектов; фото собирается картинкой", () => {
  assert.equal(montageApplies(projectWith({ type: "video" })), true);
  assert.equal(montageApplies(projectWith({ type: "mixed" })), true);
  assert.equal(montageApplies(projectWith({ type: "photo" })), false);
});

test("монтажная раскладка: есть монтаж или итога ещё нет; старый итог без монтажа — как раньше", () => {
  assert.equal(montageScreen(projectWith({ type: "video", montage: MONTAGE })), true);
  assert.equal(montageScreen(projectWith({ type: "video" })), true);
  assert.equal(montageScreen(projectWith({ type: "video", assembly: { asset_url: "/assets/old" } })), false);
  assert.equal(montageScreen(projectWith({ type: "photo" })), false);
});

test("версии новыми сверху: кто, когда, что изменилось, какая текущая", () => {
  const rows = versionRows(projectWith({ montage: MONTAGE }));
  assert.deepEqual(rows.map((row) => [row.label, row.who, row.current]), [["v2", "Вы", true], ["v1", "Агент", false]]);
  assert.equal(rows[0].summary, "без описания");
  assert.equal(rows[1].summary, "черновой монтаж: 3 клипа, 0:15");
  assert.equal(rows[1].when, "28.09, 14:05");
  assert.equal(rows[1].assetUrl, "/assets/asset-1");
  assert.deepEqual(versionRows(PROJECT), []);
});

test("номер версии читается коротко, дата — по-русски", () => {
  assert.equal(versionLabel("v010"), "v10");
  assert.equal(versionLabel("v1000"), "v1000");
  assert.equal(whenText("не дата"), "");
});

test("«Скачать» — тот же файл с download=1, и с билетом Mini App тоже", () => {
  assert.equal(downloadHref("/assets/asset-2"), "/assets/asset-2?download=1");
  assert.equal(downloadHref("/assets/asset-2?e=1&t=x"), "/assets/asset-2?e=1&t=x&download=1");
  assert.equal(downloadHref("https://example.test/x"), null);
  assert.equal(downloadHref(undefined), null);
});

test("стол на компьютере: закрыт, открыт со ссылкой, запускается", () => {
  assert.equal(screenFlags({ status: status() }).desk, "closed");
  const open = screenFlags({ status: status({ desk: { state: "open", url: "http://127.0.0.1:9/x", telemetry_off: true } }) });
  assert.deepEqual([open.desk, open.deskUrl], ["open", "http://127.0.0.1:9/x"]);
  assert.equal(screenFlags({ status: status({ desk: { state: "busy" } }) }).desk, "busy");
});

test("на телефоне и в Telegram нет стола и «Показать в папке» — есть подсказка", () => {
  for (const place of [{ phone: true }, { telegram: true }]) {
    const flags = screenFlags({ status: status(), ...place });
    assert.deepEqual([flags.desk, flags.reveal, flags.deskHint, flags.build], ["hidden", false, true, true]);
  }
});

test("нет движка или черновика — стола нет, сборка в чат остаётся", () => {
  const missing = screenFlags({ status: status({ engine: { state: "missing", version: null, reason: "не найден Node.js" } }) });
  assert.deepEqual([missing.engine, missing.desk, missing.build], ["missing", "hidden", true]);
  assert.equal(screenFlags({ status: status({ exists: false }) }).desk, "hidden");
  assert.deepEqual([screenFlags({ status: null }).engine, screenFlags({ status: null }).desk], ["unknown", "hidden"]);
});

test("после принятия ролика — ни стола, ни «Сделать текущей», ни сборки", () => {
  const flags = screenFlags({ status: status(), finished: true });
  assert.deepEqual([flags.desk, flags.restore, flags.build, flags.deskHint], ["hidden", false, false, false]);
});

test("«Показать в папке» — только когда файл на месте и серверу есть чем открыть папку", () => {
  assert.equal(screenFlags({ status: status() }).reveal, true);
  assert.equal(screenFlags({ status: status({ reveal: false }) }).reveal, false);
  assert.equal(screenFlags({ status: status({ file: { version: "v002", shown: null } }) }).reveal, false);
});

test("плашка несобранных правок — по свежей схеме, иначе по дешёвому состоянию", () => {
  const byStatus = notices({ status: status({ unrendered_changes: true }) });
  assert.deepEqual(byStatus.map((item) => [item.key, item.action]), [["unrendered", "build"]]);
  assert.match(byStatus[0].text, /^Есть несобранные правки/);
  const byModel = notices({ status: status({ unrendered_changes: null }), model: { index_key: "k1", unrendered_changes: true } });
  assert.deepEqual(byModel.map((item) => item.key), ["unrendered"]);
  const oldModel = notices({ status: status({ index_key: "k2" }), model: { index_key: "k1", unrendered_changes: true } });
  assert.deepEqual(oldModel, []);
});

test("без собранной версии плашки нет: собирать ещё нечего сравнивать", () => {
  assert.deepEqual(notices({ status: status({ current_version: null, file: null, unrendered_changes: true }) }), []);
});

test("ошибки монтажа, пропавший файл и устаревшие клипы — текстом", () => {
  const list = notices({
    status: status({ file: { version: "v002", shown: null } }),
    model: { index_key: "k1", unrendered_changes: false, model_error: "HyperFrames «timeline --json» завершился с кодом 1",
             stale_error: null, stale_clips: [{ clip: "v-1" }, { clip: "v-2" }] },
  });
  assert.deepEqual(list.map((item) => [item.key, item.tone]), [["file", "error"], ["model_error", "error"], ["stale", "warn"]]);
  assert.match(list[0].text, /v2 нет на месте/);
  assert.match(list[2].text, /устарело: 2/);
  assert.equal(list[2].action, "refresh");
});

test("записки стола и ошибка опроса видны; фото — только ошибка опроса", () => {
  const list = notices({ status: status({ desk: { state: "closed", note: "монтажный стол не отвечает" } }), feedError: "Нет связи с дашбордом." });
  assert.deepEqual(list.map((item) => item.key), ["feed", "desk-note"]);
  assert.deepEqual(notices({ status: { applicable: false }, feedError: "x" }).map((item) => item.key), ["feed"]);
  const noOpener = notices({ status: status({ desk: { state: "open", url: "http://127.0.0.1:9/", telemetry_off: false } }) });
  assert.deepEqual(noOpener.map((item) => item.key), ["telemetry"]);
});

test("сторона кадра — для превью вертикального ролика", () => {
  assert.equal(orientation({ width: 1080, height: 1920 }), "portrait");
  assert.equal(orientation({ width: 1920, height: 1080 }), "landscape");
  assert.equal(orientation({ width: 1080, height: 1080 }), "square");
  assert.equal(orientation(null), "landscape");
});

test("длина — из схемы без несобранных правок, иначе по концу последней сцены", () => {
  const model = { index_key: "k1", unrendered_changes: false, duration: 14.6 };
  assert.equal(durationText({ status: status(), model, project: PROJECT }), "00:15");
  assert.equal(durationText({ status: status(), model: { ...model, unrendered_changes: true }, project: PROJECT }), "00:35");
  assert.equal(durationText({ status: null, model: null, project: projectWith({ scenes: [] }) }), "");
});
```

В `skills/aimaster/studio/static/ui/v2/responsive.test.mjs` добавить импорт `inTelegram` к импорту из `./responsive.js` и тест:

```js
test("Telegram — только когда есть initData; обычный браузер со скриптом Telegram — нет", () => {
  const saved = globalThis.Telegram;
  try {
    globalThis.Telegram = { WebApp: { initData: "query_id=AA" } };
    assert.equal(inTelegram(), true);
    globalThis.Telegram = { WebApp: { initData: "" } };
    assert.equal(inTelegram(), false);
    delete globalThis.Telegram;
    assert.equal(inTelegram(), false);
  } finally {
    if (saved === undefined) delete globalThis.Telegram;
    else globalThis.Telegram = saved;
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test skills/aimaster/studio/static/ui/v2/montage-model.test.mjs skills/aimaster/studio/static/ui/v2/responsive.test.mjs`
Expected: FAIL — `Cannot find module …/montage-model.js`; `inTelegram` не экспортирован.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/static/ui/v2/montage-model.js`:

```js
// Экран «Сборка» монтажа — чистые правила без DOM (их проверяет
// montage-model.test.mjs): строки версий, что показать и что спрятать,
// плашки, сторона кадра, длина. Данные — снимок проекта (`project.montage`:
// версии с `asset_url`, текущая, `canvas`) и ответы
// `GET /api/projects/<id>/montage` (движок, стол, файл, `index_key`) и
// `…/montage/model` (схема, несобранные правки, ошибки движка).

const WHO = Object.freeze({ owner: "Вы", agent: "Агент", autopilot: "Автопилот" });

/** Монтаж — у видео и смешанных проектов; фото собирается картинкой. */
export function montageApplies(project) {
  return project?.type === "video" || project?.type === "mixed";
}

/** Монтажная раскладка экрана: монтаж уже есть — или итога ещё нет. Старый
 * итог, собранный до монтажа (`assembly set`), показывается как раньше. */
export function montageScreen(project) {
  if (!montageApplies(project)) return false;
  return Boolean(project?.montage) || typeof project?.assembly?.asset_url !== "string";
}

/** «v003» → «v3». */
export function versionLabel(id) {
  const match = /^v0*(\d+)$/.exec(typeof id === "string" ? id : "");
  return match ? `v${match[1]}` : String(id || "");
}

/** «28.09, 14:05» по времени компьютера; не дата — пустая строка. */
export function whenText(iso) {
  const date = new Date(typeof iso === "string" ? iso : Number.NaN);
  if (Number.isNaN(date.getTime())) return "";
  const two = (value) => String(value).padStart(2, "0");
  return `${two(date.getDate())}.${two(date.getMonth() + 1)}, ${two(date.getHours())}:${two(date.getMinutes())}`;
}

/** Версии новыми сверху: номер, кто собрал, когда, что изменилось, текущая ли. */
export function versionRows(project) {
  const montage = project?.montage;
  const list = Array.isArray(montage?.versions) ? montage.versions : [];
  return list.map((item) => ({
    id: item.id,
    label: versionLabel(item.id),
    who: WHO[item.by] || WHO.agent,
    when: whenText(item.created_at),
    summary: typeof item.summary === "string" && item.summary.trim() ? item.summary.trim() : "без описания",
    current: item.id === montage.current_version,
    assetUrl: typeof item.asset_url === "string" && item.asset_url.startsWith("/assets/") ? item.asset_url : null,
  })).reverse();
}

/** «Скачать»: тот же файл с `download=1` (в Mini App у адреса уже есть билет `?e=…&t=…`). */
export function downloadHref(url) {
  if (typeof url !== "string" || !url.startsWith("/assets/")) return null;
  return `${url}${url.includes("?") ? "&" : "?"}download=1`;
}

function engineState(status) {
  const state = status?.engine?.state;
  return state === "installed" || state === "missing" ? state : "unknown";
}

/**
 * Что можно делать на экране. Стол и «Показать в папке» — только на компьютере
 * (не телефон, не Telegram); после принятия ролика монтаж не меняется.
 */
export function screenFlags({ status = null, finished = false, phone = false, telegram = false } = {}) {
  const engine = engineState(status);
  const local = !phone && !telegram;
  const deskPossible = !finished && status?.exists === true && engine === "installed";
  const state = status?.desk?.state;
  const desk = local && deskPossible ? (state === "open" || state === "busy" ? state : "closed") : "hidden";
  return {
    engine,
    desk,
    deskUrl: desk === "open" && typeof status?.desk?.url === "string" ? status.desk.url : null,
    deskHint: !local && deskPossible,
    reveal: local && status?.reveal === true && typeof status?.file?.shown === "string",
    restore: !finished,
    build: !finished,
  };
}

/** Плашки над экраном — тексты сервера (по-русски, без путей) и свои. */
export function notices({ status = null, model = null, feedError = null } = {}) {
  const list = [];
  if (feedError) list.push({ key: "feed", tone: "error", text: feedError });
  if (!status || status.applicable === false) return list;
  const fresh = Boolean(model && model.index_key && model.index_key === status.index_key);
  const unrendered = fresh ? model.unrendered_changes : status.unrendered_changes;
  if (status.current_version && unrendered === true) {
    list.push({ key: "unrendered", tone: "warn", action: "build",
      text: "Есть несобранные правки: монтаж менялся после последней сборки." });
  }
  if (status.current_version && status.file && !status.file.shown) {
    list.push({ key: "file", tone: "error", action: "build",
      text: `Файла ролика ${versionLabel(status.current_version)} нет на месте — соберите ролик заново.` });
  }
  for (const key of ["model_error", "stale_error"]) {
    if (fresh && typeof model[key] === "string" && model[key]) list.push({ key, tone: "error", text: model[key] });
  }
  const stale = fresh && Array.isArray(model.stale_clips) ? model.stale_clips.length : 0;
  if (stale) {
    list.push({ key: "stale", tone: "warn", action: "refresh",
      text: `После черновика в проекте выбрали другие клипы или звук — в монтаже устарело: ${stale}.` });
  }
  for (const key of ["note", "forgotten"]) {
    const text = status.desk?.[key];
    if (typeof text === "string" && text) list.push({ key: `desk-${key}`, tone: "info", text });
  }
  if (status.desk?.state === "open" && status.desk.telemetry_off === false) {
    list.push({ key: "telemetry", tone: "info",
      text: "Монтажный стол открыт без отключения аналитики Studio: его адрес не распознан." });
  }
  return list;
}

/** Сторона кадра превью: вертикальный ролик не сжимается в полосу 16:9. */
export function orientation(canvas) {
  const width = Number(canvas?.width);
  const height = Number(canvas?.height);
  if (!(width > 0 && height > 0)) return "landscape";
  if (height > width) return "portrait";
  return width > height ? "landscape" : "square";
}

function mmss(seconds) {
  const total = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

/** Длина текущей версии: из схемы, когда несобранных правок нет; иначе — по сценам. */
export function durationText({ status = null, model = null, project = null } = {}) {
  const settled = Boolean(model && status && model.index_key === status.index_key && model.unrendered_changes === false);
  if (settled && Number(model.duration) > 0) return mmss(Number(model.duration));
  const ends = (project?.scenes || []).map((scene) => scene?.end_ms).filter(Number.isFinite);
  return ends.length ? mmss(Math.max(...ends) / 1000) : "";
}
```

В `skills/aimaster/studio/static/ui/v2/responsive.js` добавить в конец:

```js
/** Дашборд открыт внутри Telegram (Mini App): `initData` у Telegram.WebApp
 * есть только там — в обычном браузере скрипт Telegram загружен, но пуст. */
export function inTelegram() {
  const data = globalThis.Telegram?.WebApp?.initData;
  return typeof data === "string" && data.length > 0;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test skills/aimaster/studio/static/ui/v2/montage-model.test.mjs skills/aimaster/studio/static/ui/v2/responsive.test.mjs`
Expected: PASS (16 + все тесты `responsive`).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/static/ui/v2/montage-model.js skills/aimaster/studio/static/ui/v2/montage-model.test.mjs skills/aimaster/studio/static/ui/v2/responsive.js skills/aimaster/studio/static/ui/v2/responsive.test.mjs
git commit -m "feat(dashboard): montage screen model — versions, flags, notices"
```

---

### Task 15: Модель схемы слоёв

**Files:**
- Create: `skills/aimaster/studio/static/ui/v2/montage-layers-model.js`
- Test: `skills/aimaster/studio/static/ui/v2/montage-layers-model.test.mjs`

**Interfaces:**
- Consumes: ответ `GET …/montage/model` → `duration`, `layers[{layer, label, clips[{id, kind, start, duration, media_start, volume, scene_id, asset_id, text}]}]` (порядок дорожек — `video, titles, voice, music, fx, atmos`); `project.scenes[{scene_id, order, title}]`.
- Produces:
  - `fmtTime(seconds) -> string` («0:03.3», как строки `montage diff`), `fmtLen(seconds) -> string` («2,5 с»), `volumeText(volume) -> string` («30 %»; нет значения — «100 %»)
  - `sceneNames(project) -> {[scene_id]: {number, text}}`
  - `clipDetail(clip, layer, label, names) -> string`
  - `layerRows(model, project) -> {layer, label, blocks: {id, at, len, text, detail}[]}[]` — `at`, `len` — проценты ширины дорожки, `len ≥ 1.2`

- [ ] **Step 1: Write the failing test**

`skills/aimaster/studio/static/ui/v2/montage-layers-model.test.mjs`:

```js
// node --test skills/aimaster/studio/static/ui/v2/montage-layers-model.test.mjs
//
// Схема монтажа: шесть дорожек, блоки по времени, подпись по нажатию —
// чей клип, где он в ролике и какой кусок исходника взят.

import test from "node:test";
import assert from "node:assert/strict";

import {
  clipDetail, fmtLen, fmtTime, layerRows, sceneNames, volumeText,
} from "./montage-layers-model.js";
import { projectWith } from "./snapshot.fixture.mjs";

const PROJECT = projectWith({
  scenes: [
    { scene_id: "s2", order: 2, title: "Клубок" },
    { scene_id: "s1", order: 1, title: "Сад" },
  ],
});
const clip = (patch) => ({ id: "x", kind: "video", start: 0, duration: 1, media_start: 0, volume: null,
  scene_id: null, asset_id: null, text: null, ...patch });
const MODEL = {
  duration: 10,
  layers: [
    { layer: "video", label: "Видео", clips: [clip({ id: "v-1", start: 0, duration: 2.5, media_start: 0.5, volume: 0.3, scene_id: "s1" }),
                                              clip({ id: "v-2", start: 2.5, duration: 5, scene_id: "s2" })] },
    { layer: "titles", label: "Титры", clips: [clip({ id: "t-1", kind: "div", start: 0.2, duration: 1.6, text: "Барсик" })] },
    { layer: "voice", label: "Голос", clips: [clip({ id: "a-voice", kind: "audio", start: 0, duration: 5 })] },
    { layer: "music", label: "Музыка", clips: [] },
    { layer: "fx", label: "Шумы", clips: [clip({ id: "a-fx", kind: "audio", start: 9.99, duration: 0.01, volume: 0.8 })] },
    { layer: "atmos", label: "Атмосфера", clips: [clip({ id: "a-atmos", kind: "audio", start: 12, duration: 2 })] },
  ],
};

test("время и длина — как в строках montage diff", () => {
  assert.equal(fmtTime(3.25), "0:03.3");
  assert.equal(fmtTime(65), "1:05.0");
  assert.equal(fmtTime(0), "0:00.0");
  assert.equal(fmtLen(2.5), "2,5 с");
  assert.equal(volumeText(0.3), "30 %");
  assert.equal(volumeText(null), "100 %");
});

test("сцены называются по порядку, а не по месту в списке", () => {
  assert.deepEqual(sceneNames(PROJECT), {
    s1: { number: 1, text: "сцена 1 «Сад»" },
    s2: { number: 2, text: "сцена 2 «Клубок»" },
  });
});

test("шесть дорожек в постоянном порядке, блоки — доли длины ролика", () => {
  const rows = layerRows(MODEL, PROJECT);
  assert.deepEqual(rows.map((row) => row.label), ["Видео", "Титры", "Голос", "Музыка", "Шумы", "Атмосфера"]);
  assert.deepEqual(rows[0].blocks.map((block) => [block.id, block.at, block.len, block.text]),
    [["v-1", 0, 25, "1"], ["v-2", 25, 50, "2"]]);
  assert.deepEqual(rows[1].blocks.map((block) => block.text), ["Барсик"]);
  assert.deepEqual(rows[3].blocks, []);
});

test("короткий клип всё равно можно нажать, а вылезший за конец — виден у края", () => {
  const rows = layerRows(MODEL, PROJECT);
  assert.deepEqual([rows[4].blocks[0].at, rows[4].blocks[0].len], [98.8, 1.2]);
  assert.deepEqual([rows[5].blocks[0].at, rows[5].blocks[0].len], [98.8, 1.2]);
});

test("подпись по нажатию: клип сцены, кусок исходника, громкость", () => {
  const names = sceneNames(PROJECT);
  assert.equal(clipDetail(MODEL.layers[0].clips[0], "video", "Видео", names),
    "Клип: сцена 1 «Сад» · 0:00.0–0:02.5 ролика · из исходника с 0:00.5, 2,5 с · громкость 30 %");
  assert.equal(clipDetail(MODEL.layers[0].clips[1], "video", "Видео", names),
    "Клип: сцена 2 «Клубок» · 0:02.5–0:07.5 ролика · из исходника с 0:00.0, 5,0 с");
  assert.equal(clipDetail(MODEL.layers[1].clips[0], "titles", "Титры", names), "Титр «Барсик» · 0:00.2–0:01.8 ролика");
  assert.equal(clipDetail(MODEL.layers[2].clips[0], "voice", "Голос", names),
    "Голос · 0:00.0–0:05.0 ролика · из исходника с 0:00.0, 5,0 с · громкость 100 %");
});

test("без схемы дорожек нет; без длины ролика — она по концу последнего клипа", () => {
  assert.deepEqual(layerRows(null, PROJECT), []);
  const rows = layerRows({ duration: 0, layers: [{ layer: "video", label: "Видео", clips: [clip({ id: "v-1", start: 0, duration: 4 })] }] }, PROJECT);
  assert.deepEqual([rows[0].blocks[0].at, rows[0].blocks[0].len], [0, 100]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test skills/aimaster/studio/static/ui/v2/montage-layers-model.test.mjs`
Expected: FAIL — `Cannot find module …/montage-layers-model.js`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/static/ui/v2/montage-layers-model.js`:

```js
// Схема монтажа — чистые правила без DOM (montage-layers-model.test.mjs):
// шесть дорожек в постоянном порядке и блоки клипов по времени. Данные —
// `GET /api/projects/<id>/montage/model` → `layers` (время — секунды
// готового ролика, как в `montage status`). Подписи — как в строках
// `montage diff`: «0:03.3», «2,5 с».

const MIN_LEN = 1.2; // % ширины дорожки: короткий клип всё равно можно нажать

const round2 = (value) => Math.round(value * 100) / 100;

/** 3.25 → «0:03.3». */
export function fmtTime(seconds) {
  const tenths = Math.round(Math.max(0, Number(seconds) || 0) * 10);
  const minutes = Math.floor(tenths / 600);
  const rest = (tenths - minutes * 600) / 10;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}

/** 2.5 → «2,5 с». */
export function fmtLen(seconds) {
  const tenths = Math.round(Math.max(0, Number(seconds) || 0) * 10);
  return `${(tenths / 10).toFixed(1).replace(".", ",")} с`;
}

/** Громкость в процентах; нет значения — как записано, 100 %. */
export function volumeText(volume) {
  return `${Math.round((Number.isFinite(volume) ? volume : 1) * 100)} %`;
}

/** {scene_id: {number, text: "сцена 2 «Скептик»"}} — по порядку сцен. */
export function sceneNames(project) {
  const scenes = (project?.scenes || []).filter((scene) => scene?.scene_id)
    .sort((left, right) => (left.order || 0) - (right.order || 0));
  return Object.fromEntries(scenes.map((scene, index) => [scene.scene_id,
    { number: index + 1, text: `сцена ${index + 1} «${scene.title || scene.scene_id}»` }]));
}

/** Что показать по нажатию: чей клип, где он в ролике, какой кусок исходника. */
export function clipDetail(clip, layer, label, names = {}) {
  const span = `${fmtTime(clip.start)}–${fmtTime(clip.start + clip.duration)} ролика`;
  if (layer === "titles") return `Титр «${clip.text || clip.id}» · ${span}`;
  const who = layer === "video" && names[clip.scene_id] ? `Клип: ${names[clip.scene_id].text}` : label;
  const parts = [who, span, `из исходника с ${fmtTime(clip.media_start)}, ${fmtLen(clip.duration)}`];
  if (layer !== "video" || Number.isFinite(clip.volume)) parts.push(`громкость ${volumeText(clip.volume)}`);
  return parts.join(" · ");
}

function blockText(layer, clip, names) {
  if (layer === "titles") return clip.text || "титр";
  if (layer === "video" && names[clip.scene_id]) return String(names[clip.scene_id].number);
  return "";
}

/** Дорожки и блоки: `at`/`len` — проценты ширины дорожки. */
export function layerRows(model, project) {
  const layers = Array.isArray(model?.layers) ? model.layers : [];
  const ends = layers.flatMap((layer) => (layer.clips || []).map((clip) => clip.start + clip.duration));
  const duration = Number(model?.duration) > 0 ? Number(model.duration) : Math.max(0, ...ends);
  const names = sceneNames(project);
  return layers.map((layer) => ({
    layer: layer.layer,
    label: layer.label,
    blocks: (layer.clips || []).map((clip) => {
      const at = duration > 0 ? Math.min(Math.max((clip.start / duration) * 100, 0), 100 - MIN_LEN) : 0;
      const len = duration > 0 ? Math.max(MIN_LEN, Math.min(100 - at, (clip.duration / duration) * 100)) : MIN_LEN;
      return { id: clip.id, at: round2(at), len: round2(len), text: blockText(layer.layer, clip, names),
        detail: clipDetail(clip, layer.layer, layer.label, names) };
    }),
  }));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test skills/aimaster/studio/static/ui/v2/montage-layers-model.test.mjs`
Expected: PASS (6 tests).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/static/ui/v2/montage-layers-model.js skills/aimaster/studio/static/ui/v2/montage-layers-model.test.mjs
git commit -m "feat(dashboard): layer scheme model — six tracks, blocks by time, clip details"
```

---

### Task 16: Запросы к эндпоинтам и опрос, пока открыт экран

**Files:**
- Modify: `skills/aimaster/studio/static/ui/actions.js` (`postJson` — экспорт; `parseErrorBody` — `message`)
- Create: `skills/aimaster/studio/static/ui/v2/montage-api.js`
- Create: `skills/aimaster/studio/static/ui/v2/montage-feed.js`
- Test: `skills/aimaster/studio/static/ui/v2/montage-feed.test.mjs`

**Interfaces:**
- Consumes: HTTP задачи 11; `actions.fetchCsrfToken` (внутри `postJson`).
- Produces:
  - `actions.postJson(path, body, expectedStatus) -> Promise<{ok: true, body} | {ok: false, code, message?, currentRevision?}>` (теперь экспортирован)
  - `montage-api.montageUrl(projectId, part = "") -> string`; `getMontage(projectId, part = "", fetchImpl = globalThis.fetch) -> Promise<{ok, body} | {ok: false, code, message?}>`; `postMontage(projectId, part, body = {})`; `refusalText(result) -> string`
  - `montage-feed.POLL_MS = 5000`; `createMontageFeed({load, notify}) -> {show(id), hide(), tick(): Promise<void>, current(id) -> {status, model, error} | null, active() -> string | null}`
  - обёртка страницы: `showMontage(projectId)`, `hideMontage()`, `montageState(projectId)`, `refreshMontage()`; событие `studio:montage-updated` `{projectId}`

- [ ] **Step 1: Write the failing test**

`skills/aimaster/studio/static/ui/v2/montage-feed.test.mjs`:

```js
// node --test skills/aimaster/studio/static/ui/v2/montage-feed.test.mjs
//
// Опрос монтажа: дешёвое состояние каждый раз, схема — только когда сменился
// index_key; ответ для прежнего проекта выбрасывается; отказ сервера — текстом.

import test from "node:test";
import assert from "node:assert/strict";

import { getMontage, montageUrl, postMontage, refusalText } from "./montage-api.js";
import { POLL_MS, createMontageFeed } from "./montage-feed.js";

const ok = (body) => ({ ok: true, body });
const STATUS = (key, patch = {}) => ({ applicable: true, exists: true, engine: { state: "installed" }, index_key: key, ...patch });

function server(answers) {
  const calls = [];
  const load = async (id, part) => {
    calls.push(part ? `${id}:${part}` : id);
    const queue = answers[part || "status"];
    return queue.length > 1 ? queue.shift() : queue[0];
  };
  return { calls, load };
}

function feedFor(answers) {
  const { calls, load } = server(answers);
  const seen = [];
  return { calls, seen, feed: createMontageFeed({ load, notify: (id) => seen.push(id) }) };
}

test("опрос раз в 5 секунд", () => {
  assert.equal(POLL_MS, 5000);
});

test("первый опрос: состояние и схема, одно оповещение", async () => {
  const { calls, seen, feed } = feedFor({ status: [ok(STATUS("k1"))], model: [ok({ index_key: "k1", layers: [] })] });
  feed.show("p");
  await feed.tick();
  assert.deepEqual(calls, ["p", "p:model"]);
  assert.deepEqual(seen, ["p"]);
  assert.equal(feed.current("p").model.index_key, "k1");
});

test("то же состояние — схему не спрашиваем и не перерисовываем", async () => {
  const { calls, seen, feed } = feedFor({ status: [ok(STATUS("k1"))], model: [ok({ index_key: "k1" })] });
  feed.show("p");
  await feed.tick();
  await feed.tick();
  assert.deepEqual(calls, ["p", "p:model", "p"]);
  assert.deepEqual(seen, ["p"]);
});

test("сменился index_key — схема заново", async () => {
  const { calls, seen, feed } = feedFor({
    status: [ok(STATUS("k1")), ok(STATUS("k2"))],
    model: [ok({ index_key: "k1" }), ok({ index_key: "k2" })],
  });
  feed.show("p");
  await feed.tick();
  await feed.tick();
  assert.deepEqual(calls, ["p", "p:model", "p", "p:model"]);
  assert.deepEqual(seen, ["p", "p"]);
});

test("нет движка, черновика или это фото — схему не спрашиваем", async () => {
  for (const status of [STATUS("k1", { engine: { state: "missing" } }), STATUS(null, { exists: false }),
    { applicable: false }]) {
    const { calls, feed } = feedFor({ status: [ok(status)], model: [ok({})] });
    feed.show("p");
    await feed.tick();
    assert.deepEqual(calls, ["p"]);
  }
});

test("скрытый экран не опрашивается", async () => {
  const { calls, feed } = feedFor({ status: [ok(STATUS("k1"))], model: [ok({ index_key: "k1" })] });
  feed.show("p");
  feed.hide();
  await feed.tick();
  assert.deepEqual(calls, []);
  assert.equal(feed.current("p"), null);
});

test("ответ для прежнего проекта выбрасывается", async () => {
  let release;
  const load = (id) => (id === "a"
    ? new Promise((resolve) => { release = () => resolve(ok(STATUS("k1"))); })
    : Promise.resolve(ok(STATUS("k9", { engine: { state: "missing" } }))));
  const seen = [];
  const feed = createMontageFeed({ load, notify: (id) => seen.push(id) });
  feed.show("a");
  const first = feed.tick();
  feed.show("b");
  await feed.tick();
  release();
  await first;
  assert.equal(feed.current("a"), null);
  assert.equal(feed.current("b").status.index_key, "k9");
  assert.deepEqual(seen, ["b"]);
});

test("отказ сервера сохраняется с текстом", async () => {
  const refusal = { ok: false, code: "montage_refused", message: "в папке монтажа есть ссылки на другие места" };
  const { seen, feed } = feedFor({ status: [refusal], model: [ok({})] });
  feed.show("p");
  await feed.tick();
  assert.deepEqual(feed.current("p").error, refusal);
  assert.equal(refusalText(feed.current("p").error), refusal.message);
  assert.deepEqual(seen, ["p"]);
});

test("getMontage: адрес, ответ, отказ с текстом, нет сети", async () => {
  assert.equal(montageUrl("проект 1", "model"), "/api/projects/%D0%BF%D1%80%D0%BE%D0%B5%D0%BA%D1%82%201/montage/model");
  const seen = [];
  const answer = (status, body) => async (url) => {
    seen.push(url);
    return { ok: status < 400, status, json: async () => body };
  };
  assert.deepEqual(await getMontage("p", "", answer(200, { exists: true })), { ok: true, body: { exists: true } });
  assert.deepEqual(await getMontage("p", "model", answer(422, { error: { code: "montage_refused", message: "нет версии v009" } })),
    { ok: false, code: "montage_refused", message: "нет версии v009" });
  assert.deepEqual(await getMontage("p", "", async () => { throw new Error("offline"); }), { ok: false, code: "network_error" });
  assert.deepEqual(seen, ["/api/projects/p/montage", "/api/projects/p/montage/model"]);
});

test("postMontage: CSRF дашборда и текст отказа", async () => {
  const calls = [];
  globalThis.fetch = async (path, init = {}) => {
    calls.push([init.method || "GET", String(path), init.headers?.["X-CSRF-Token"] || null]);
    const json = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
    if (path === "/api/session") return json({ csrf_token: "t" });
    return json({ error: { code: "montage_refused", message: "ролик ещё не собран — показывать в папке нечего" } }, 422);
  };
  const result = await postMontage("p", "reveal");
  assert.deepEqual(result, { ok: false, code: "montage_refused", message: "ролик ещё не собран — показывать в папке нечего" });
  assert.deepEqual(calls.at(-1), ["POST", "/api/projects/p/montage/reveal", "t"]);
});

test("refusalText: текст сервера, иначе по коду", () => {
  assert.equal(refusalText({ ok: false, code: "revision_conflict" }), "Проект только что изменился — попробуйте ещё раз.");
  assert.equal(refusalText({ ok: false, code: "forbidden" }), "Дашборд не принял запрос — обновите страницу.");
  assert.equal(refusalText({ ok: false, code: "что-то" }), "Не получилось. Попробуйте ещё раз.");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test skills/aimaster/studio/static/ui/v2/montage-feed.test.mjs`
Expected: FAIL — `Cannot find module …/montage-api.js`.

- [ ] **Step 3: Write minimal implementation**

В `skills/aimaster/studio/static/ui/actions.js`:

1. В `parseErrorBody` после блока `if (body && body.error && typeof body.error.current_revision === "number") { … }` добавить:

```js
  // Отказ монтажа (422 montage_refused) несёт русский текст для человека —
  // экран «Сборка» показывает его как есть (studio/montage_routes.py).
  if (body && body.error && typeof body.error.message === "string") {
    result.message = body.error.message;
  }
```

2. Объявление `async function postJson(path, body, expectedStatus) {` заменить на:

```js
export async function postJson(path, body, expectedStatus) {
```

и в его докстринг дописать строку: `Экспортирован для экрана «Сборка» (ui/v2/montage-api.js): его POST-маршруты — не /api/actions.`

`skills/aimaster/studio/static/ui/v2/montage-api.js`:

```js
// Запросы экрана «Сборка» к `/api/projects/<id>/montage…`
// (studio/montage_routes.py). Без DOM. Ответ — всегда `{ok: true, body}` или
// `{ok: false, code, message?}`: `message` — русский текст отказа монтажа
// (422 montage_refused), экран показывает его как есть. POST — через общий
// `postJson` (CSRF дашборда из `/api/session`).

import { postJson } from "../actions.js";

const CODE_TEXT = Object.freeze({
  forbidden: "Дашборд не принял запрос — обновите страницу.",
  revision_conflict: "Проект только что изменился — попробуйте ещё раз.",
  network_error: "Нет связи с дашбордом.",
  session_error: "Нет связи с дашбордом — обновите страницу.",
  not_found: "Экран монтажа не нашёл проект — обновите страницу.",
});

export function montageUrl(projectId, part = "") {
  const base = `/api/projects/${encodeURIComponent(projectId)}/montage`;
  return part ? `${base}/${part}` : base;
}

export async function getMontage(projectId, part = "", fetchImpl = globalThis.fetch) {
  let response;
  try {
    response = await fetchImpl(montageUrl(projectId, part), { headers: { Accept: "application/json" } });
  } catch {
    return { ok: false, code: "network_error" };
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (response.ok && body && typeof body === "object") return { ok: true, body };
  const error = body?.error || {};
  const result = { ok: false, code: typeof error.code === "string" ? error.code : `http_${response.status}` };
  if (typeof error.message === "string") result.message = error.message;
  return result;
}

export function postMontage(projectId, part, body = {}) {
  return postJson(montageUrl(projectId, part), body, 200);
}

/** Текст отказа для человека: русский текст сервера, иначе — по коду. */
export function refusalText(result) {
  if (typeof result?.message === "string" && result.message) return result.message;
  return CODE_TEXT[result?.code] || "Не получилось. Попробуйте ещё раз.";
}
```

`skills/aimaster/studio/static/ui/v2/montage-feed.js`:

```js
// Опрос монтажа, пока открыт экран «Сборка»: дешёвое состояние раз в 5 с
// (только когда вкладка видна), схема слоёв — когда сменился index_key.
// Каждый опрос — ещё и знак серверу «экран смотрят»: стол, открытый
// дашбордом, не остановится по простою (studio/desk_keeper.py).
// Ядро `createMontageFeed` — без DOM и таймеров, его проверяют тесты;
// обёртка ниже вешает таймер и шлёт `studio:montage-updated`.

import { getMontage } from "./montage-api.js";

export const POLL_MS = 5000;

export function createMontageFeed({ load, notify }) {
  let projectId = null;
  let entry = null;
  let inFlight = null;

  function needsModel(body, known) {
    return Boolean(body) && body.applicable !== false && body.exists === true
      && body.engine?.state === "installed" && known?.index_key !== body.index_key;
  }

  async function tick() {
    if (!projectId || inFlight === projectId) return;
    const id = projectId;
    inFlight = id;
    try {
      const status = await load(id, "");
      if (projectId !== id) return;
      const next = { status: status.ok ? status.body : entry?.status || null,
        model: entry?.model || null, error: status.ok ? null : status };
      if (status.ok && needsModel(status.body, next.model)) {
        const model = await load(id, "model");
        if (projectId !== id) return;
        if (model.ok) next.model = model.body;
        else next.error = model;
      }
      const changed = JSON.stringify(next) !== JSON.stringify(entry);
      entry = next;
      if (changed) notify(id);
    } finally {
      if (inFlight === id) inFlight = null;
    }
  }

  return {
    show(id) {
      if (id !== projectId) {
        projectId = id;
        entry = null;
      }
    },
    hide() {
      projectId = null;
      entry = null;
    },
    tick,
    current(id) {
      return id && id === projectId ? entry : null;
    },
    active() {
      return projectId;
    },
  };
}

// --- Обёртка страницы -------------------------------------------------

const feed = createMontageFeed({
  load: (id, part) => getMontage(id, part),
  notify: (id) => document.dispatchEvent(new CustomEvent("studio:montage-updated", {
    bubbles: true, detail: { projectId: id },
  })),
});
let timer = null;

function visible() {
  return typeof document === "undefined" || document.visibilityState === "visible";
}

/** Экран «Сборка» проекта на экране: начать (или продолжить) опрос. */
export function showMontage(projectId) {
  const fresh = feed.active() !== projectId;
  feed.show(projectId);
  if (!timer) timer = setInterval(() => { if (visible()) feed.tick(); }, POLL_MS);
  if (fresh) feed.tick();
}

/** Другой экран или фото-проект — опрос не нужен. */
export function hideMontage() {
  feed.hide();
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
}

/** Что известно о монтаже проекта: `{status, model, error}` или `null`. */
export function montageState(projectId) {
  return feed.current(projectId);
}

/** Спросить сейчас: после «Сделать текущей», открытия стола, возврата на вкладку. */
export function refreshMontage() {
  return feed.tick();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test skills/aimaster/studio/static/ui/v2/montage-feed.test.mjs skills/aimaster/studio/static/ui/v2/actions-wait.test.mjs`
Expected: PASS (11 новых тестов; решения `actions-wait` — по-прежнему).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/static/ui/actions.js skills/aimaster/studio/static/ui/v2/montage-api.js skills/aimaster/studio/static/ui/v2/montage-feed.js skills/aimaster/studio/static/ui/v2/montage-feed.test.mjs
git commit -m "feat(dashboard): montage API client and a poll that runs only while the screen is open"
```

---

### Task 17: Блоки экрана — плашки, файл, главные кнопки и стол, версии, схема; стили

**Files:**
- Create: `skills/aimaster/studio/static/ui/v2/montage-notices.js`
- Create: `skills/aimaster/studio/static/ui/v2/montage-file.js`
- Create: `skills/aimaster/studio/static/ui/v2/montage-desk.js`
- Create: `skills/aimaster/studio/static/ui/v2/montage-versions.js`
- Create: `skills/aimaster/studio/static/ui/v2/montage-layers.js`
- Create: `skills/aimaster/studio/static/styles/v2/montage.css`
- Test: `skills/aimaster/studio/static/ui/v2/montage-dom.test.mjs` (новый: модули грузятся в node, стили — на токенах, схема — без атрибута `style`)

**Interfaces:**
- Consumes: `montage-model` (задача 14), `montage-layers-model` (задача 15), `montage-api.postMontage/refusalText`, `montage-feed.refreshMontage` (задача 16), `screen-prompts.assembleFinal/assembleLabel/installMontage/updateMontageClips` (задача 13); `dom.el`, `dom.chatButton`, `board-bits.badge`, `toast.showToast`, `../card-forms.js` (`buildStatusLine`, `markControlHooks`, `noteCardFocusPending`).
- Produces (DOM, рисуют узел и ничего не держат, кроме отмеченного):
  - `renderNotices(list, {project, revision, actions}) -> HTMLElement`
  - `renderFileCard({project, status, flags}) -> HTMLElement`
  - `renderMainActions({project, revision, status, flags}) -> HTMLElement`
  - `renderVersions({project, revision, flags, onChanged(projectId)}) -> HTMLElement` (помнит запросы «Сделать текущей» в полёте)
  - `renderLayers({project, model, engine, exists}) -> HTMLElement` (помнит выбранный блок)
  - классы `am-*` в `styles/v2/montage.css`

- [ ] **Step 1: Write the failing test**

`skills/aimaster/studio/static/ui/v2/montage-dom.test.mjs`:

```js
// node --test skills/aimaster/studio/static/ui/v2/montage-dom.test.mjs
//
// DOM-модули экрана монтажа: грузятся без браузера (ничего не трогают при
// импорте), стили — только на токенах, блоки схемы — CSS-переменные через
// CSSOM, а не атрибут style (CSP страницы его запрещает). Вид проверяет
// задача 20 в браузере.

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const MODULES = Object.freeze({
  "./montage-notices.js": ["renderNotices"],
  "./montage-file.js": ["renderFileCard"],
  "./montage-desk.js": ["renderMainActions"],
  "./montage-versions.js": ["renderVersions"],
  "./montage-layers.js": ["renderLayers"],
});

test("модули экрана монтажа загружаются в node и отдают свои функции", async () => {
  for (const [path, names] of Object.entries(MODULES)) {
    const module = await import(path);
    for (const name of names) assert.equal(typeof module[name], "function", `${path}: ${name}`);
  }
});

test("стили монтажа не заводят цветов мимо токенов", () => {
  const css = fs.readFileSync(new URL("../../styles/v2/montage.css", import.meta.url), "utf8");
  const literals = (css.match(/#[0-9a-fA-F]{3,8}\b/g) || []).filter((color) => color.toLowerCase() !== "#fff");
  assert.deepEqual(literals, []);
  assert.match(css, /@media \(max-width: 759px\)/);
});

test("блоки схемы ставятся переменными через CSSOM, атрибута style нет нигде", () => {
  const layers = fs.readFileSync(new URL("./montage-layers.js", import.meta.url), "utf8");
  assert.match(layers, /style\.setProperty\("--am-at"/);
  for (const path of Object.keys(MODULES)) {
    const source = fs.readFileSync(new URL(path, import.meta.url), "utf8");
    assert.doesNotMatch(source, /setAttribute\("style"|\.style\.cssText|innerHTML/, path);
  }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test skills/aimaster/studio/static/ui/v2/montage-dom.test.mjs`
Expected: FAIL — `Cannot find module …/montage-notices.js`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/static/ui/v2/montage-notices.js`:

```js
// Плашки экрана «Сборка»: несобранные правки, ошибки монтажа (текст сервера —
// по-русски, без путей), записки монтажного стола. Список —
// montage-model.notices; у плашки со сборкой или обновлением — кнопка в чат.

import { chatButton, el } from "./dom.js";
import { assembleFinal, assembleLabel, updateMontageClips } from "./screen-prompts.js";

export function renderNotices(list, { project, revision, actions = true }) {
  const box = el("div", "am-notices");
  box.dataset.hook = "am-notices";
  box.setAttribute("role", "status");
  for (const notice of list) {
    const row = el("div", "am-notice");
    row.dataset.tone = notice.tone;
    row.dataset.key = notice.key;
    row.append(el("p", "am-notice-text", notice.text));
    if (actions && notice.action === "build") {
      row.append(chatButton(assembleLabel(project), assembleFinal(project, revision)));
    }
    if (actions && notice.action === "refresh") {
      row.append(chatButton("Обновить клипы → чат", updateMontageClips(project, revision)));
    }
    box.append(row);
  }
  return box;
}
```

`skills/aimaster/studio/static/ui/v2/montage-file.js`:

```js
// Файл текущей версии: «Скачать» (тот же /assets/<id> с download=1 — имя
// файла даёт сервер), «Показать в папке» (только на компьютере: сервер
// открывает Finder, Проводник или файловый менеджер Linux), путь к файлу
// текстом и «Скопировать путь». Путь — от папки над рабочей: абсолютных
// путей сервер не отдаёт. Версию и адрес файла даёт снимок проекта, путь —
// живое состояние, если оно про ту же версию.

import { buildStatusLine, markControlHooks } from "../card-forms.js";
import { el } from "./dom.js";
import { postMontage, refusalText } from "./montage-api.js";
import { downloadHref, versionRows } from "./montage-model.js";
import { showToast } from "./toast.js";

function downloadLink(href) {
  const link = el("a", "v2-chat-button", "Скачать");
  link.href = href;
  link.setAttribute("download", "");
  link.dataset.hook = "am-download";
  return link;
}

function revealButton(project) {
  const wrap = el("span", "am-inline");
  const button = el("button", "v2-chat-button", "Показать в папке");
  button.type = "button";
  markControlHooks(button, `montage:${project.id}`, "reveal");
  const status = buildStatusLine();
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "";
    const result = await postMontage(project.id, "reveal");
    button.disabled = false;
    if (!result.ok) status.textContent = refusalText(result);
  });
  wrap.append(button, status);
  return wrap;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function pathLine(shown) {
  const line = el("div", "am-file-path");
  const text = el("code", "am-file-path-text", shown);
  text.dataset.hook = "am-file-path";
  const copy = el("button", "am-link-button", "Скопировать путь");
  copy.type = "button";
  copy.addEventListener("click", async () => {
    showToast((await copyText(shown)) ? "Путь скопирован"
      : "Не получилось скопировать — выделите путь и скопируйте сами");
  });
  line.append(text, copy);
  return line;
}

export function renderFileCard({ project, status, flags }) {
  const current = versionRows(project).find((row) => row.current) || null;
  const card = el("section", "v2-card am-file");
  card.dataset.hook = "am-file";
  card.append(el("h2", "v2-card-title", current ? `Ролик ${current.label}` : "Ролик"));
  if (!current) {
    card.append(el("p", "v2-section-hint", "Ролик ещё не собран — первую версию соберёт агент."));
    return card;
  }
  const shown = status?.current_version === current.id ? status?.file?.shown || null : null;
  const actions = el("div", "am-file-actions");
  const href = downloadHref(current.assetUrl);
  if (href) actions.append(downloadLink(href));
  if (flags.reveal && shown) actions.append(revealButton(project));
  card.append(actions);
  if (shown) card.append(pathLine(shown));
  return card;
}
```

`skills/aimaster/studio/static/ui/v2/montage-desk.js`:

```js
// Главные кнопки экрана «Сборка»: «Открыть монтажный стол» и «Собрать
// ролик → чат»; нет движка — «Монтажный стол не установлен» и «Установить →
// чат». Стол — HyperFrames Studio в новой вкладке, через страницу-переходник
// на её же адресе (выключает аналитику Studio, studio/montage/desk_opener.py).
// Вкладка открывается сразу по нажатию, пустой: откройся она после ответа
// сервера, браузер счёл бы её всплывающим окном. Заблокирована — после ответа
// появится ссылка «Перейти к монтажному столу». На телефоне и в Telegram
// стола нет (flags.desk === "hidden") — вместо него подсказка.

import { buildStatusLine, markControlHooks } from "../card-forms.js";
import { chatButton, el } from "./dom.js";
import { postMontage, refusalText } from "./montage-api.js";
import { refreshMontage } from "./montage-feed.js";
import { assembleFinal, assembleLabel, installMontage } from "./screen-prompts.js";

const PHONE_HINT = "Монтажный стол открывается на компьютере. Здесь можно смотреть версии "
  + "и просить правки словами в чате.";

function blankTab() {
  try {
    const tab = window.open("", "_blank");
    if (!tab) return null;
    tab.opener = null;
    tab.document.title = "Монтажный стол";
    tab.document.body.textContent = "Открываю монтажный стол…";
    return tab;
  } catch {
    return null;
  }
}

function openDesk(project) {
  const wrap = el("div", "am-desk");
  const button = el("button", "v2-primary v2-primary-back", "Открыть монтажный стол");
  button.type = "button";
  markControlHooks(button, `montage:${project.id}`, "desk-open");
  const status = buildStatusLine();
  button.addEventListener("click", async () => {
    const tab = blankTab();
    button.disabled = true;
    status.textContent = "Запускаю монтажный стол…";
    const result = await postMontage(project.id, "desk");
    button.disabled = false;
    if (result.ok && typeof result.body?.url === "string") {
      status.textContent = tab ? "" : "Стол открыт — нажмите «Перейти к монтажному столу».";
      if (tab) tab.location.replace(result.body.url);
      refreshMontage();
      return;
    }
    tab?.close();
    status.textContent = refusalText(result);
  });
  wrap.append(button, status);
  return wrap;
}

function deskIsOpen(project, url) {
  const wrap = el("div", "am-desk");
  if (url) {
    const link = el("a", "v2-primary v2-primary-back", "Перейти к монтажному столу ↗");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.dataset.hook = "am-desk-go";
    wrap.append(link);
  }
  const close = el("button", "am-link-button", "Закрыть стол");
  close.type = "button";
  markControlHooks(close, `montage:${project.id}`, "desk-close");
  const status = buildStatusLine();
  close.addEventListener("click", async () => {
    close.disabled = true;
    const result = await postMontage(project.id, "desk/close");
    close.disabled = false;
    status.textContent = result.ok ? "" : refusalText(result);
    refreshMontage();
  });
  wrap.append(close, status);
  return wrap;
}

function engineMissing(project, revision, reason) {
  const box = el("div", "am-engine");
  box.dataset.hook = "am-engine-missing";
  box.append(el("p", "am-engine-title", "Монтажный стол не установлен"));
  if (reason) box.append(el("p", "am-engine-reason", reason));
  box.append(chatButton("Установить → чат", installMontage(project, revision)));
  return box;
}

export function renderMainActions({ project, revision, status, flags }) {
  const box = el("div", "am-main-actions");
  box.dataset.hook = "am-main-actions";
  if (flags.engine === "missing") box.append(engineMissing(project, revision, status?.engine?.reason));
  if (flags.desk === "closed") box.append(openDesk(project));
  if (flags.desk === "busy") box.append(el("p", "am-note", "Монтажный стол запускается…"));
  if (flags.desk === "open") box.append(deskIsOpen(project, flags.deskUrl));
  if (flags.deskHint) box.append(el("p", "am-note", PHONE_HINT));
  if (flags.build) {
    box.append(chatButton(assembleLabel(project), assembleFinal(project, revision), "v2-primary v2-primary-back"));
  }
  return box;
}
```

`skills/aimaster/studio/static/ui/v2/montage-versions.js`:

```js
// Листалка версий монтажа, новые слева: номер, кто собрал, когда, что
// изменилось. «Сделать текущей» — прямое действие дашборда (POST
// …/montage/restore): локально, бесплатно, обратимо — версии не удаляются.
// «Принять» — главная кнопка подвала «Принять ролик» (решение `approve`
// стадии «Сборка»): она принимает текущую версию.

import { buildStatusLine, markControlHooks, noteCardFocusPending } from "../card-forms.js";
import { badge } from "./board-bits.js";
import { el } from "./dom.js";
import { postMontage, refusalText } from "./montage-api.js";
import { versionRows } from "./montage-model.js";
import { showToast } from "./toast.js";

const pending = new Set(); // «проект:версия» в полёте — перерисовка не вернёт кнопку раньше ответа

function restoreButton(project, revision, row, onChanged) {
  const key = `${project.id}:${row.id}`;
  const targetId = `montage:${key}`;
  const wrap = el("div", "am-version-actions");
  const button = el("button", "v2-chat-button", pending.has(key) ? "Отправляется…" : "Сделать текущей");
  button.type = "button";
  button.disabled = pending.has(key);
  markControlHooks(button, targetId, "restore");
  const status = buildStatusLine();
  button.addEventListener("click", async () => {
    noteCardFocusPending(targetId, "restore");
    pending.add(key);
    button.disabled = true;
    button.textContent = "Отправляется…";
    const result = await postMontage(project.id, "restore", { version: row.id, expected_revision: revision });
    pending.delete(key);
    button.disabled = false;
    button.textContent = "Сделать текущей";
    if (result.ok) {
      showToast(`Текущая версия — ${row.label}`);
      onChanged(project.id);
      return;
    }
    status.textContent = refusalText(result);
    if (result.code === "revision_conflict") onChanged(project.id);
  });
  wrap.append(button, status);
  return wrap;
}

function versionItem(project, revision, row, flags, onChanged) {
  const item = el("li", "am-version");
  item.dataset.hook = "am-version";
  item.dataset.current = String(row.current);
  const top = el("div", "am-version-top");
  top.append(el("span", "am-version-label", row.label));
  if (row.current) top.append(badge("текущая", "ok"));
  item.append(top, el("p", "am-version-meta", [row.who, row.when].filter(Boolean).join(" · ")),
    el("p", "am-version-summary", row.summary));
  if (!row.current && flags.restore) item.append(restoreButton(project, revision, row, onChanged));
  return item;
}

export function renderVersions({ project, revision, flags, onChanged }) {
  const rows = versionRows(project);
  const box = el("section", "v2-card am-versions");
  box.dataset.hook = "am-versions";
  const head = el("div", "v2-card-head");
  head.append(el("h2", "v2-card-title", "Версии"), el("span", "v2-card-meta", String(rows.length)));
  box.append(head);
  if (!rows.length) {
    box.append(el("p", "v2-section-hint", "Версий пока нет: первую соберёт агент."));
    return box;
  }
  const list = el("ol", "am-version-list");
  for (const row of rows) list.append(versionItem(project, revision, row, flags, onChanged));
  box.append(list);
  if (flags.restore) box.append(el("p", "am-versions-hint", "«Принять ролик» внизу принимает текущую версию."));
  return box;
}
```

`skills/aimaster/studio/static/ui/v2/montage-layers.js`:

```js
// Схема монтажа — только просмотр: шесть дорожек, блоки клипов по времени.
// Положение и ширина блока — CSS-переменные `--am-at`/`--am-len` через CSSOM
// (`style.setProperty`): CSP страницы (`style-src 'self'`) запрещает атрибут
// style, но не CSSOM — проверено в Chromium 2026-09-28. Нажатие на блок
// показывает под схемой, чей это клип, где он в ролике и какой кусок
// исходника взят; выбор переживает перерисовку экрана.

import { el } from "./dom.js";
import { fmtTime, layerRows } from "./montage-layers-model.js";

const HINT = "Нажмите на блок — покажу, что это за клип и какой кусок исходника взят.";
let chosen = "";

function block(projectId, item, detail, grid) {
  const key = `${projectId}:${item.id}`;
  const button = el("button", "am-block", item.text);
  button.type = "button";
  button.dataset.hook = "am-block";
  button.style.setProperty("--am-at", String(item.at));
  button.style.setProperty("--am-len", String(item.len));
  button.setAttribute("aria-label", item.detail);
  button.setAttribute("aria-pressed", String(chosen === key));
  button.addEventListener("click", () => {
    chosen = key;
    detail.textContent = item.detail;
    for (const other of grid.querySelectorAll('.am-block[aria-pressed="true"]')) {
      other.setAttribute("aria-pressed", "false");
    }
    button.setAttribute("aria-pressed", "true");
  });
  return button;
}

function track(projectId, row, detail, grid) {
  const line = el("div", "am-track");
  line.dataset.layer = row.layer;
  const lane = el("div", "am-lane");
  if (!row.blocks.length) lane.append(el("span", "am-lane-empty", "пусто"));
  for (const item of row.blocks) lane.append(block(projectId, item, detail, grid));
  line.append(el("span", "am-track-label", row.label), lane);
  return line;
}

function hintText(engine, exists, model) {
  if (exists === false) return "Схема появится после чернового монтажа.";
  if (engine === "missing") return "Схема появится, когда будет установлен монтажный стол.";
  return model ? "Схему прочитать не удалось." : "Читаем монтаж…";
}

export function renderLayers({ project, model, engine, exists }) {
  const box = el("section", "v2-card am-layers");
  box.dataset.hook = "am-layers";
  box.append(el("h2", "v2-card-title", "Схема монтажа"));
  const rows = exists !== false && engine === "installed" && model ? layerRows(model, project) : [];
  if (!rows.length) {
    box.append(el("p", "v2-section-hint", hintText(engine, exists, model)));
    return box;
  }
  const grid = el("div", "am-tracks");
  const detail = el("p", "am-layer-detail");
  detail.setAttribute("aria-live", "polite");
  const picked = rows.flatMap((row) => row.blocks).find((item) => `${project.id}:${item.id}` === chosen);
  detail.textContent = picked ? picked.detail : HINT;
  for (const row of rows) grid.append(track(project.id, row, detail, grid));
  const ruler = el("div", "am-ruler");
  ruler.append(el("span", "", fmtTime(0)), el("span", "", fmtTime(model.duration)));
  box.append(grid, ruler, detail);
  return box;
}
```

`skills/aimaster/studio/static/styles/v2/montage.css`:

```css
/*
 * Экран «Сборка» с монтажом (спецификация монтажа 2026-09-25, «Дашборд:
 * экран «Сборка»»): плашки, превью по стороне кадра, файл, главные кнопки,
 * версии, схема слоёв. Визуальный язык — хэндофф 2026-09-23: карточки 16,
 * пилюли, токены tokens-v2.css; цветов мимо токенов нет (кроме #fff на
 * тёмном блоке). Положение блоков схемы — переменные --am-at/--am-len, их
 * ставит montage-layers.js через CSSOM (атрибут style CSP запрещает).
 * Телефон — @media (max-width: 759px), цели нажатия ≥ 44px.
 */

a.v2-primary, a.v2-chat-button { text-decoration: none; }

.am-notices { display: grid; gap: 8px; margin-bottom: 16px; }
.am-notice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 10px 14px;
  border-radius: var(--v2-r-group);
  font-size: var(--v2-fs-13);
}
.am-notice[data-tone="warn"] { background: var(--v2-warn-bg); color: var(--v2-warn-ink); border: 1px solid var(--v2-warn-line); }
.am-notice[data-tone="error"] { background: var(--v2-surface); color: var(--v2-danger); border: 1px solid var(--v2-danger); }
.am-notice[data-tone="info"] { background: var(--v2-soft); color: var(--v2-ink-2); }
.am-notice-text { flex: 1 1 240px; margin: 0; }

.am-top { display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start; margin-bottom: 20px; }
.am-side { flex: 1 1 300px; min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.am-top > .v2-final-preview[data-orientation="portrait"] { flex: 0 1 300px; max-width: 340px; aspect-ratio: 9 / 16; }
.am-top > .v2-final-preview[data-orientation="square"] { flex: 0 1 420px; max-width: 480px; aspect-ratio: 1 / 1; }

.am-file-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 10px; }
.am-inline { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.am-file-path { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; margin-top: 12px; }
.am-file-path-text {
  flex: 1 1 200px;
  min-width: 0;
  padding: 6px 8px;
  border-radius: var(--v2-r-sm);
  background: var(--v2-soft);
  color: var(--v2-ink-2);
  font-size: var(--v2-fs-12);
  overflow-wrap: anywhere;
}
.am-link-button {
  min-height: 36px;
  padding: 0;
  border: 0;
  background: none;
  color: var(--v2-ink);
  font: inherit;
  font-size: var(--v2-fs-13);
  font-weight: 600;
  text-decoration: underline;
  cursor: pointer;
}

.am-main-actions { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; }
.am-desk { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; }
.am-note { margin: 0; font-size: var(--v2-fs-13); color: var(--v2-muted); }
.am-engine {
  align-self: stretch;
  padding: 14px 16px;
  border: 1px solid var(--v2-warn-line);
  border-radius: var(--v2-r-group);
  background: var(--v2-warn-bg);
  color: var(--v2-warn-ink);
}
.am-engine-title { margin: 0; font-weight: 600; }
.am-engine-reason { margin: 4px 0 10px; font-size: var(--v2-fs-13); }

.am-versions, .am-layers { margin-bottom: 20px; }
.am-version-list {
  display: flex;
  gap: 12px;
  margin: 0;
  padding: 0 0 4px;
  list-style: none;
  overflow-x: auto;
  scroll-snap-type: x proximity;
}
.am-version {
  flex: 0 0 240px;
  scroll-snap-align: start;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid var(--v2-line);
  border-radius: var(--v2-r-group);
  background: var(--v2-surface);
}
.am-version[data-current="true"] { border-color: var(--v2-ok); box-shadow: inset 0 0 0 1px var(--v2-ok); }
.am-version-top { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.am-version-label { font-size: var(--v2-fs-15); font-weight: 700; font-variant-numeric: tabular-nums; }
.am-version-meta { margin: 0; font-size: var(--v2-fs-12); color: var(--v2-muted); }
.am-version-summary {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  color: var(--v2-ink-2);
  font-size: var(--v2-fs-13);
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.am-version-actions { margin-top: auto; }
.am-versions-hint { margin: 10px 0 0; font-size: var(--v2-fs-12); color: var(--v2-muted); }

.am-tracks { display: grid; gap: 6px; margin-top: 12px; }
.am-track { display: grid; grid-template-columns: 96px minmax(0, 1fr); align-items: center; gap: 10px; }
.am-track-label { font-size: var(--v2-fs-12); color: var(--v2-muted); }
.am-lane { position: relative; height: 30px; border-radius: var(--v2-r-sm); background: var(--v2-soft); }
.am-lane-empty { position: absolute; inset: 0; display: grid; place-items: center; font-size: var(--v2-fs-11); color: var(--v2-none); }
.am-block {
  position: absolute;
  top: 3px;
  bottom: 3px;
  left: calc(var(--am-at, 0) * 1%);
  width: calc(var(--am-len, 1) * 1%);
  min-width: 6px;
  padding: 0 6px;
  border: 0;
  border-radius: 6px;
  background: var(--v2-ink-2);
  color: #fff;
  font: inherit;
  font-size: var(--v2-fs-11);
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}
.am-track[data-layer="video"] .am-block { background: var(--v2-ink); }
.am-track[data-layer="titles"] .am-block { background: var(--v2-warn); color: var(--v2-ink); }
.am-track[data-layer="voice"] .am-block { background: var(--v2-ok); }
.am-track[data-layer="music"] .am-block { background: var(--v2-ok-ink); }
.am-track[data-layer="fx"] .am-block { background: var(--v2-muted); }
.am-track[data-layer="atmos"] .am-block { background: var(--v2-dashed); color: var(--v2-ink); }
.am-block[aria-pressed="true"], .am-block:focus-visible { outline: 2px solid var(--v2-ink); outline-offset: 1px; }
.am-ruler {
  display: flex;
  justify-content: space-between;
  margin: 6px 0 0 106px;
  color: var(--v2-muted);
  font-size: var(--v2-fs-11);
  font-variant-numeric: tabular-nums;
}
.am-layer-detail { min-height: 1.5em; margin: 12px 0 0; color: var(--v2-ink-2); font-size: var(--v2-fs-13); }

@media (max-width: 759px) {
  .am-top { flex-direction: column; flex-wrap: nowrap; gap: 12px; align-items: stretch; margin-bottom: 12px; }
  /* В колонке основа flex — это высота: правило стороны кадра выше задало бы её 300px. */
  .am-top > .v2-final-preview,
  .am-top > .v2-final-preview[data-orientation] { flex: none; width: 100%; max-width: none; }
  .am-top > .v2-final-preview[data-orientation="portrait"] { width: min(100%, calc(62vh * 9 / 16)); margin-inline: auto; }
  .am-side { gap: 12px; }
  .am-file-actions > .v2-chat-button, .am-main-actions .v2-primary { width: 100%; min-height: 44px; }
  .am-link-button { min-height: 44px; }
  .am-version { flex-basis: 78%; }
  .am-track { grid-template-columns: 1fr; gap: 4px; }
  .am-lane { height: 44px; }
  .am-block { top: 4px; bottom: 4px; min-width: 12px; }
  .am-ruler { margin-left: 0; }
  .am-versions, .am-layers { margin-bottom: 12px; }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test skills/aimaster/studio/static/ui/v2/montage-dom.test.mjs && node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs`
Expected: PASS (3 tests), все модули статики разобраны.

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/static/ui/v2/montage-notices.js skills/aimaster/studio/static/ui/v2/montage-file.js skills/aimaster/studio/static/ui/v2/montage-desk.js skills/aimaster/studio/static/ui/v2/montage-versions.js skills/aimaster/studio/static/ui/v2/montage-layers.js skills/aimaster/studio/static/styles/v2/montage.css skills/aimaster/studio/static/ui/v2/montage-dom.test.mjs
git commit -m "feat(dashboard): montage blocks — notices, file, desk, versions, layer scheme"
```

---

### Task 18: Экран «Сборка» целиком; опрос и перерисовка в оболочке

**Files:**
- Create: `skills/aimaster/studio/static/ui/v2/assembly-parts.js` (перенос `assemblyLines`, превью, карточки, истории из `screen-assembly.js`)
- Modify: `skills/aimaster/studio/static/ui/v2/screen-assembly.js` (весь файл)
- Modify: `skills/aimaster/studio/static/ui/v2/shell.js` (импорт, остановка опроса на других экранах)
- Modify: `skills/aimaster/studio/static/ui/v2/boot.js` (стили `montage.css`, перерисовка по `studio:montage-updated`, опрос при возврате на вкладку)
- Modify: `skills/aimaster/studio/static/ui/v2/README.md` (модули, событие, долг)
- Test: `skills/aimaster/studio/static/ui/v2/montage-dom.test.mjs` (+1 тест)

**Interfaces:**
- Consumes: всё из задач 13–17; `footer.footerMode/renderFooter`; `responsive.isPhone/inTelegram`; `../card-forms.requestProjectRefresh`.
- Produces:
  - `assembly-parts.sceneDuration(project)`, `assemblyLines(project, {ready, finished})`, `doneBanner()`, `finalPreview(project, {ready, statusText, durationText, orientation})`, `summaryCard(project, revision, {ready, finished})`, `historyBlock(project)`
  - `screen-assembly.renderAssemblyScreen(root, {state, screen})` — фото и старый итог без монтажа: прежний вид; монтаж: плашки → превью + (файл, главные кнопки) → версии → схема → история → подвал; `surface.dataset.montage`
  - `boot.js` слушает `studio:montage-updated` и перерисовывает оболочку; `shell.js` зовёт `hideMontage()` на любом экране, кроме «Сборки»

- [ ] **Step 1: Write the failing test**

Добавить в `skills/aimaster/studio/static/ui/v2/montage-dom.test.mjs` (к импортам — `import { PROJECT } from "./snapshot.fixture.mjs";`):

```js
test("экран «Сборка» и его части загружаются; строки «Финальный ролик» — прежние", async () => {
  const screen = await import("./screen-assembly.js");
  assert.equal(typeof screen.renderAssemblyScreen, "function");
  const parts = await import("./assembly-parts.js");
  for (const name of ["sceneDuration", "doneBanner", "finalPreview", "summaryCard", "historyBlock"]) {
    assert.equal(typeof parts[name], "function", name);
  }
  const lines = parts.assemblyLines(PROJECT, { ready: false, finished: false });
  assert.deepEqual(lines.map((line) => [line.key, line.value]),
    [["Сцены", "6 · 00:35"], ["Режим", "кадр за кадром"], ["Звук", "без звука"], ["Статус", "ещё не собран"]]);
  assert.equal(parts.sceneDuration(PROJECT), "00:35");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test skills/aimaster/studio/static/ui/v2/montage-dom.test.mjs`
Expected: FAIL — `Cannot find module …/assembly-parts.js`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/static/ui/v2/assembly-parts.js`:

```js
// Части экрана «Сборка», общие для фото и монтажа (хэндофф 2026-09-23):
// плашка «Ролик принят», превью ролика, карточка «Финальный ролик»,
// «История решений». Вынесены из screen-assembly.js без изменения вида;
// превью знает сторону кадра (`data-orientation`) — вертикальный ролик
// монтажа не сжимается в полосу 16:9.

import { formatHistoryEntries } from "../history-panel.js";
import { AUDIO_LAYERS } from "./audio-model.js";
import { playMark } from "./board-bits.js";
import { chatButton, clock, el, openViewer } from "./dom.js";
import { renderPreview } from "./preview.js";
import { assembleFinal, assembleLabel } from "./screen-prompts.js";
import { selectedResultVersion } from "./variants.js";

const MODE_WORDS = Object.freeze({ per_scene: "кадр за кадром", one_shot: "одним заходом" });

/** Длительность ролика по концу последней сцены, «00:30»; нет — «». */
export function sceneDuration(project) {
  const ends = (project?.scenes || []).map((scene) => scene?.end_ms).filter(Number.isFinite);
  return ends.length ? clock(Math.max(...ends)) : "";
}

/** Строки «ключ — значение» карточки «Финальный ролик». */
export function assemblyLines(project, { ready, finished }) {
  const scenes = (project?.scenes || []).length;
  const time = sceneDuration(project);
  const layers = AUDIO_LAYERS
    .filter((meta) => selectedResultVersion(project, { layer: meta.layer }))
    .map((meta) => meta.name.toLowerCase());
  return [
    { key: "Сцены", value: time ? `${scenes} · ${time}` : String(scenes) },
    { key: "Режим", value: MODE_WORDS[project?.gen_mode] || "кадр за кадром" },
    { key: "Звук", value: layers.length ? layers.join(", ") : "без звука" },
    { key: "Статус", value: finished ? "принят" : ready ? "ждёт вашего решения" : "ещё не собран" },
  ];
}

/** «Ролик принят. Проект завершён.» */
export function doneBanner() {
  const done = el("div", "v2-done");
  done.dataset.hook = "v2-done";
  const mark = el("span", "v2-done-mark", "✓");
  mark.setAttribute("aria-hidden", "true");
  done.append(mark, el("span", "", "Ролик принят. Проект завершён."));
  return done;
}

/** Превью ролика: первый кадр, «▶», статус и длительность; нажатие — просмотрщик. */
export function finalPreview(project, { ready, statusText, durationText = "", orientation = "landscape" }) {
  const assembly = project?.assembly && typeof project.assembly === "object" ? project.assembly : null;
  const button = el("button", "v2-final-preview");
  button.type = "button";
  button.dataset.hook = "v2-final-slot";
  button.dataset.ready = String(ready);
  button.dataset.orientation = orientation;
  button.setAttribute("aria-label", ready ? "Открыть финальный ролик" : "Финального ролика пока нет");
  button.disabled = !ready;
  button.append(renderPreview(ready ? assembly : null,
    { kind: ready ? "video" : "none", label: "Финальный ролик", emptyText: "ролик ещё не собран" }));
  if (ready) button.append(playMark("v2-play v2-play-big"));
  button.append(el("span", "v2-final-status", statusText));
  if (durationText) button.append(el("span", "v2-final-duration", durationText));
  button.addEventListener("click", () => openViewer(
    { kind: "assembly", id: "final" }, { tab: "video", trigger: button },
  ));
  return button;
}

/** Карточка «Финальный ролик»: что в нём и кнопка сборки в чат. */
export function summaryCard(project, revision, state) {
  const card = el("section", "v2-card v2-final");
  card.dataset.hook = "v2-final";
  card.append(el("h2", "v2-card-title", "Финальный ролик"));
  const list = el("dl", "v2-kv");
  for (const line of assemblyLines(project, state)) {
    const row = el("div", "v2-kv-row");
    row.append(el("dt", "", line.key), el("dd", "", line.value));
    list.append(row);
  }
  card.append(list);
  const summary = typeof project?.assembly?.summary === "string" ? project.assembly.summary.trim() : "";
  if (summary) card.append(el("p", "v2-final-summary", summary));
  card.append(chatButton(assembleLabel(project), assembleFinal(project, revision),
    "v2-chat-button v2-card-button"));
  return card;
}

/** «История решений»: тот же разбор записей, что у панели истории v1. */
export function historyBlock(project) {
  const entries = formatHistoryEntries(project?.history);
  const box = el("details", "v2-card v2-history");
  box.dataset.hook = "v2-history";
  const summary = el("summary", "v2-history-summary");
  summary.append(
    el("span", "v2-history-title", `История решений · ${entries.length}`),
    el("span", "v2-history-toggle v2-when-closed", "показать"),
    el("span", "v2-history-toggle v2-when-open", "скрыть"),
  );
  box.append(summary);
  if (!entries.length) {
    box.append(el("p", "v2-section-hint", "Решений пока нет."));
    return box;
  }
  const list = el("ol", "v2-history-list");
  for (const entry of entries) {
    const row = el("li", "v2-history-row");
    row.dataset.actor = entry.actor;
    row.append(el("span", "v2-history-actor", entry.actorLabel), el("span", "v2-history-text", entry.text));
    list.append(row);
  }
  box.append(list);
  return box;
}
```

`skills/aimaster/studio/static/ui/v2/screen-assembly.js` — весь файл:

```js
// Экран «Сборка» (спецификация §3.5; спецификация монтажа 2026-09-25,
// «Дашборд: экран «Сборка»»; хэндофф 2026-09-23 — вид). Фото-проект и
// старый итог без монтажа — как раньше: превью, карточка «Финальный ролик»,
// история решений. Видео и смешанный с монтажом — плашки, превью текущей
// версии, файл («Скачать», «Показать в папке», путь), главные кнопки
// («Открыть монтажный стол», «Собрать ролик → чат»), версии, схема слоёв,
// история. Живое состояние монтажа опрашивает montage-feed.js, пока этот
// экран открыт. Заголовок экрана рисует оболочка, подвал — renderFooter.

import { requestProjectRefresh } from "../card-forms.js";
import { doneBanner, finalPreview, historyBlock, sceneDuration, summaryCard } from "./assembly-parts.js";
import { el } from "./dom.js";
import { footerMode, renderFooter } from "./footer.js";
import { refusalText } from "./montage-api.js";
import { renderMainActions } from "./montage-desk.js";
import { hideMontage, montageState, refreshMontage, showMontage } from "./montage-feed.js";
import { renderFileCard } from "./montage-file.js";
import { renderLayers } from "./montage-layers.js";
import {
  durationText, montageScreen, notices, orientation, screenFlags, versionLabel,
} from "./montage-model.js";
import { renderNotices } from "./montage-notices.js";
import { renderVersions } from "./montage-versions.js";
import { inTelegram, isPhone } from "./responsive.js";

function isReady(project) {
  const url = project?.assembly?.asset_url;
  return typeof url === "string" && url.startsWith("/assets/");
}

function onChanged(projectId) {
  requestProjectRefresh(projectId);
  refreshMontage();
}

function plainLayout(surface, snapshot, project, finished) {
  hideMontage();
  const ready = isReady(project);
  const layout = el("div", "v2-final-layout");
  const side = el("div", "v2-final-side");
  side.append(summaryCard(project, snapshot.revision, { ready, finished }), historyBlock(project));
  const statusText = finished ? "принят" : ready ? "ждёт вашего решения" : "ещё не собран";
  layout.append(finalPreview(project, { ready, statusText, durationText: sceneDuration(project) }), side);
  surface.append(layout);
}

function montageLayout(surface, snapshot, project, finished) {
  showMontage(project.id);
  const live = montageState(project.id) || {};
  const status = live.status && live.status.applicable !== false ? live.status : null;
  const model = live.model || null;
  const revision = snapshot.revision;
  const flags = screenFlags({ status, finished, phone: isPhone(), telegram: inTelegram() });
  const list = notices({ status, model, feedError: live.error ? refusalText(live.error) : null });
  if (list.length) surface.append(renderNotices(list, { project, revision, actions: flags.build }));
  const ready = isReady(project);
  const current = project?.montage?.current_version;
  const statusText = finished ? "принят" : ready && current ? `текущая ${versionLabel(current)}` : "ещё не собран";
  const top = el("div", "am-top");
  const side = el("div", "am-side");
  side.append(renderFileCard({ project, status, flags }), renderMainActions({ project, revision, status, flags }));
  top.append(finalPreview(project, {
    ready, statusText,
    durationText: durationText({ status, model, project }),
    orientation: orientation(status?.canvas || project?.montage?.canvas),
  }), side);
  surface.append(top,
    renderVersions({ project, revision, flags, onChanged }),
    renderLayers({ project, model, engine: flags.engine, exists: status ? status.exists : null }),
    historyBlock(project));
}

/**
 * @param {HTMLElement} root куда рисовать (очищается)
 * @param {{state: object, screen?: string}} context `state.snapshot` — весь snapshot
 */
export function renderAssemblyScreen(root, { state, screen = "assembly" } = {}) {
  root.textContent = "";
  const snapshot = state?.snapshot;
  const project = snapshot?.active_project;
  const surface = el("div", "v2-screen v2-screen-assembly");
  surface.dataset.hook = "v2-screen-assembly";
  if (!project) {
    surface.setAttribute("aria-busy", "true");
    surface.append(el("p", "", "Загружаем сборку…"));
    root.append(surface);
    return;
  }
  const finished = footerMode(snapshot, { screen, stage: "assembly" }) === "done";
  if (finished) surface.append(doneBanner());
  const montage = montageScreen(project);
  surface.dataset.montage = String(montage);
  if (montage) montageLayout(surface, snapshot, project, finished);
  else plainLayout(surface, snapshot, project, finished);
  surface.append(renderFooter(snapshot, { screen }));
  root.append(surface);
}
```

В `skills/aimaster/studio/static/ui/v2/shell.js` добавить импорт после `import { el, restoreCardFocus, cardFocusNote } from "./dom.js";`:

```js
import { hideMontage } from "./montage-feed.js";
```

и в `renderShellV2` сразу после строки `const screen = project ? currentScreen(project) : null;`:

```js
  // Опрос монтажа нужен только экрану «Сборка» (montage-feed.js).
  if (screen !== "assembly") hideMontage();
```

В `skills/aimaster/studio/static/ui/v2/boot.js`:

1. После `import { attachViewerV2, repaintViewer } from "./viewer.js";` добавить `import { refreshMontage } from "./montage-feed.js";`.
2. После `ensureStylesheet("/static/styles/v2/viewer.css");` добавить `ensureStylesheet("/static/styles/v2/montage.css");`.
3. После строки `window.addEventListener("focus", controller.refreshOnReturn);` добавить:

```js
  // Экран «Сборка»: опрос монтажа принёс новое — перерисовать; вернулись на
  // вкладку — спросить сразу, не ждать 5 секунд (montage-feed.js).
  document.addEventListener("studio:montage-updated", () => renderShellV2(shellRoot, store.getState()));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refreshMontage();
  });
```

В `skills/aimaster/studio/static/ui/v2/README.md`:

1. Пункт про `screen-prompts.js` в списке «Чистые» заменить на:

```
- `screen-prompts.js` — тексты для чата, нужные только экранам:
  `changeGenMode`, `editScenario`, `reopenScenario`, `assembleFinal`
  (монтаж: `montage diff` → пересказ → сразу `montage render --by owner`,
  бесплатно; у фото — `assembly set`), `ASSEMBLE_LABEL`/`assembleLabel`,
  `installMontage` («Установить → чат»), `updateMontageClips`.
- `montage-model.js` — экран монтажа: `montageApplies`, `montageScreen`,
  `versionLabel`, `whenText`, `versionRows(project)`, `downloadHref(url)`,
  `screenFlags({status, finished, phone, telegram})`,
  `notices({status, model, feedError})`, `orientation(canvas)`,
  `durationText({status, model, project})`.
- `montage-layers-model.js` — схема слоёв: `fmtTime`, `fmtLen`, `volumeText`,
  `sceneNames`, `clipDetail`, `layerRows(model, project)`.
- `montage-api.js` — `montageUrl`, `getMontage(projectId, part)`,
  `postMontage(projectId, part, body)`, `refusalText(result)`.
- `montage-feed.js` — ядро опроса `createMontageFeed({load, notify})`
  и обёртка страницы `showMontage`, `hideMontage`, `montageState`,
  `refreshMontage`, `POLL_MS`.
```

2. В список «С DOM» после пункта `screen-frames.js` добавить:

```
- `assembly-parts.js` — `sceneDuration`, `assemblyLines`, `doneBanner`,
  `finalPreview` (сторона кадра — `data-orientation`), `summaryCard`,
  `historyBlock`: части «Сборки» для фото и монтажа.
- `montage-notices.js` · `montage-file.js` · `montage-desk.js` ·
  `montage-versions.js` · `montage-layers.js` — плашки; файл («Скачать»,
  «Показать в папке», путь); главные кнопки и монтажный стол; версии с
  «Сделать текущей»; схема слоёв. Стили — `styles/v2/montage.css`
  (подключает `boot.js`).
```

3. В «События» добавить:

```
- `studio:montage-updated` · `{projectId}` — опрос монтажа принёс новое;
  слушает `boot.js` и перерисовывает оболочку.
```

4. В «Что осталось известным долгом» предложение «Скачивания пока нет — оно отдельной работой.» заменить на «Скачивание — «Скачать» на экране «Сборка» у проектов с монтажом.»

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test skills/aimaster/studio/static/ui/v2/*.test.mjs && node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs`
Expected: PASS — все тесты v2, модули разобраны.

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/static/ui/v2/assembly-parts.js skills/aimaster/studio/static/ui/v2/screen-assembly.js skills/aimaster/studio/static/ui/v2/shell.js skills/aimaster/studio/static/ui/v2/boot.js skills/aimaster/studio/static/ui/v2/README.md skills/aimaster/studio/static/ui/v2/montage-dom.test.mjs
git commit -m "feat(dashboard): assembly screen with montage — player, file, desk, versions, layers"
```

---

### Task 19: Канон и README — экран «Сборка», простой стола, промпт без «платно»

**Files:**
- Modify: `skills/aimaster/references/montage.md` («When to start», шаг 1 «Guided flow», новый раздел «Dashboard screen» перед «Retelling a diff», абзац о `montage close` в «Montage desk», два пункта «Known limitations»)
- Modify: `README.md` (абзац о монтажном столе после абзаца установки в «Вариант 2»)
- Test: `skills/aimaster/scripts/test_montage_docs.py` (новый класс)

**Interfaces:**
- Consumes: поведение задач 1–18 (подписи кнопок, `opener_url`, 60 минут простоя, `--by owner`).
- Produces: канон, по которому агент отвечает на промпты экрана; честная запись для человека об аналитике Studio.

- [ ] **Step 1: Write the failing test**

Добавить в `skills/aimaster/scripts/test_montage_docs.py` после класса `CanonMatchesCliTests`:

```python
class DashboardCanonTests(DocsTestCase):
    """План Б: канон знает экран «Сборка» и больше не оправдывается за
    старый промпт дашборда («платно, дождись подтверждения»)."""

    canon = _read("references/montage.md")

    def test_old_notes_are_gone(self):
        self.assertNotIn("still calls the build paid", self.canon)
        self.assertNotIn("nothing stops the desk on its", self.canon)
        self.assertNotIn("a desk opened from chat does not set it", self.canon)

    def test_dashboard_screen_is_described(self):
        for text in ("## Dashboard screen", "«Собрать ролик → чат»", "«Сделать текущей»",
                     "«Установить → чат»", "«Обновить клипы → чат»", "«Скачать»",
                     "«Показать в папке»", "«Принять ролик»", "opener_url", "60 minutes",
                     "`montage render --by owner`"):
            self.assertMentions(text, self.canon)

    def test_readme_is_honest_about_studio_analytics(self):
        readme = (_SKILL_ROOT.parent.parent / "README.md").read_text(encoding="utf-8")
        self.assertMentions("Монтажный стол", readme)
        self.assertMentions("анонимной статистики Studio", readme)
```

(`_SKILL_ROOT` уже определён в файле: `skills/aimaster`; README репозитория — двумя уровнями выше.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_docs.py' -k DashboardCanon -v`
Expected: FAIL — `still calls the build paid` найден в каноне; «## Dashboard screen» нет.

- [ ] **Step 3: Write minimal implementation**

В `skills/aimaster/references/montage.md`:

1. В «When to start» фрагмент

```
and needs no confirmation. «Собрать ролик» — in chat or from the dashboard — is
`montage diff` → retell → `montage render` straight away, with no plan and no
confirmation step. The dashboard's current prompt («Собрать → чат» /
«Собрать заново → чат») still calls the build paid and asks to wait for a
confirmation: that text predates the montage; do not wait.
```

заменить на

```
and needs no confirmation. «Собрать ролик» — in chat or from the dashboard's
«Собрать ролик → чат» — is `montage diff` → retell → `montage render --by
owner` straight away, with no plan and no confirmation step.
```

2. Шаг 1 «Guided flow»

```
1. `montage status` (engine), `montage draft`, `montage render`. Say: «Черновой
   монтаж готов — версия v1, 0:15. Он на экране «Сборка». Поправить можно
   словами здесь или мышью на монтажном столе». The dashboard's «Сборка»
   shows the current version as the final video; `paths.output` is the file.
```

заменить на

```
1. `montage status` (engine), `montage draft`, `montage render`. Say: «Черновой
   монтаж готов — версия v1, 0:15. Он на экране «Сборка». Поправить можно
   словами здесь или мышью на монтажном столе». The dashboard's «Сборка»
   shows the current version, its file and all versions (Dashboard screen);
   `paths.output` is the file.
```

3. Перед строкой `## Retelling a diff` вставить раздел:

```
## Dashboard screen

The «Сборка» step of the dashboard shows the montage of a video or mixed
project to the person; you read the same facts with `montage status`.

- The preview plays the current version. «Скачать» saves its MP4 as
  «<project title>-vNNN.mp4»; «Показать в папке» opens Finder, Explorer or the
  Linux file manager at it; the path is shown from above the workspace folder,
  with «Скопировать путь».
- The versions list shows who built each version (`by`), when and its
  `summary`. «Сделать текущей» runs `montage restore` for the person — the
  history says «Вы». «Принять ролик» at the bottom approves the current
  version (`stage approve`, as before).
- The layer scheme is read-only: the six tracks with clips by time; a tap
  shows the clip and the piece of its source. «Есть несобранные правки» means
  `unrendered_changes`.
- «Открыть монтажный стол» opens Studio in a new tab through `opener_url`;
  «Закрыть стол» stops it. On a phone and inside Telegram there is no desk
  and no «Показать в папке».
- Chat buttons send ready prompts: «Собрать ролик → чат» (Guided flow, step
  3), «Установить → чат» (Engine check — the person has already said «да»)
  and «Обновить клипы → чат» (Keeping the draft current).
```

4. В «Montage desk» фрагмент

```
`montage close` stops Studio and its browser; nothing stops the desk on its
own yet. `montage status` → `desk.state` shows `open` or `closed`. Extra
```

заменить на

```
`montage close` stops Studio and its browser. A desk opened from the
dashboard stops by itself after 60 minutes with neither the «Сборка» screen
open nor an edit, and when the dashboard stops; a desk opened with
`montage open` stops only with `montage close`. `montage status` →
`desk.state` shows `open` or `closed`. Extra
```

5. В «Known limitations» два пункта

```
- The desk is not stopped by idleness or when the dashboard stops: close it
  with `montage close`.
- The studio reads a version's MP4 whole to check it: large videos register
  slowly.
```

заменить на

```
- A desk opened with `montage open` is not stopped by idleness or by the
  dashboard: close it with `montage close`.
- The studio reads a version's MP4 whole to check it when the version is
  built: large videos register slowly. The dashboard plays and downloads them
  in pieces and checks a file once until it changes.
```

В `README.md` (корень репозитория), в «Вариант 2. Установить вручную в терминале», после абзаца, который кончается словами «…установщик остановится и скажет об этом.», вставить отдельный абзац:

```
Монтажный стол (экран «Сборка» → «Открыть монтажный стол») — HyperFrames
Studio в соседней вкладке. Дашборд открывает его через свою страницу, которая
в этом браузере выключает отправку анонимной статистики Studio её
разработчикам; стол, открытый по прямой ссылке `url` из ответа
`montage open`, статистику шлёт.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_docs.py' -v`
Expected: PASS (3 новых теста и все прежние проверки канона).

- [ ] **Step 5: Full checks**

Run:
```bash
python3.14 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3.11 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'
python3 -m compileall -q skills/aimaster
node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs
node --test skills/aimaster/studio/static/ui/v2/*.test.mjs
git diff --check
```
Expected: всё зелёное, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/references/montage.md README.md skills/aimaster/scripts/test_montage_docs.py
git commit -m "docs(montage): dashboard assembly screen, desk idle stop, honest note on Studio analytics"
```

---

### Task 20: Проверка в браузере — 1400 и 390 px (проводит контроллер)

Ничего не коммитится: это проверка живого результата задач 1–19 на синтетическом проекте. Копия проекта владельца — его собственная приёмка (спецификация, «Проверка»), исполнители плана его проекты не трогают.

**Files:** рабочая папка `$SCRATCH/e2e-screen/` (своя, с README-пометкой; удаляется в конце).

**Interfaces:**
- Consumes: всё из задач 1–19; движок — копия `…/scratchpad/plan-verify/engine` (оригинал только читается).
- Produces: отчёт контроллера (в его журнал, не в репозиторий): по каждому пункту — «видно / не видно» и доказательство (скриншот, вывод команды, ответ `javascript_tool`).

- [ ] **Step 1: Копия движка и проект с v001**

```bash
SCRATCH=/private/tmp/claude-501/-Users-AlexFisenkov-Documents---------------------------/f8deea07-f40a-45a7-a5bc-dfb56a12505e/scratchpad
E2E="$SCRATCH/e2e-screen"
mkdir -p "$E2E" && printf 'проба экрана «Сборка» (план Б, задача 20); удалить после\n' > "$E2E/README"
cp -R "$SCRATCH/plan-verify/engine" "$E2E/engine"
python3 - "$E2E/engine" <<'PY'
import json, sys
from pathlib import Path
prefix = Path(sys.argv[1])
path = prefix / "aimaster-engine.json"
record = json.loads(path.read_text(encoding="utf-8"))
record["browser"] = str(prefix / "home" / record["browser"].split("/engine/home/", 1)[1])
path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(Path(record["browser"]).is_file())
PY
cd /Users/AlexFisenkov/Documents/aimaster-montage
export AIMASTER_HYPERFRAMES_DIR="$E2E/engine"
python3 - "$E2E/ws" <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, "skills/aimaster/scripts")
from smoke_kit import cli
from smoke_montage import MONTAGE_PROJECT, project_ready_for_assembly
workspace = Path(sys.argv[1])
workspace.mkdir(parents=True, exist_ok=True)
env = dict(os.environ)
cli(env, "workspace", "init", workspace)
revision = project_ready_for_assembly(env, workspace)
drafted = cli(env, "montage", "draft", workspace, MONTAGE_PROJECT, "--expected-revision", revision)
built = cli(env, "montage", "render", workspace, MONTAGE_PROJECT, "--expected-revision", drafted["revision"])
print(built["version"], built["revision"])
PY
```

Expected: `True`, затем `v001 <ревизия>`.

- [ ] **Step 2: Дашборд из ветки**

Run (в фоне, `AIMASTER_HYPERFRAMES_DIR` из шага 1): `python3 skills/aimaster/scripts/creator_studio.py serve "$E2E/ws" > "$E2E/serve.log" 2>&1` — pid записать в `$E2E/serve.pid`.
Expected: в `$E2E/serve.log` строка `{"base_url": "http://127.0.0.1:<порт>"}`.

- [ ] **Step 3: Ширина 1400 px (Browser pane: `resize_window` 1400×900, `navigate` на `<base_url>/?project=smoke-montage`, шаг «Сборка» в степпере)**

Что нажать и что должно быть видно:

1. Превью вертикальное 9:16 (кадр 180×320) с «▶», пилюли «текущая v1» и «00:03»; плашек нет.
2. Карточка «Ролик v1»: «Скачать», «Показать в папке»; путь `ws/media/smoke-montage/montage/v001.mp4` — ни `/private/`, ни `/Users/` на странице (`get_page_text`); «Скопировать путь» → тост «Путь скопирован» (или «Не получилось скопировать…», если панели браузера недоступен буфер — отметить, какой).
3. «Скачать»: `curl -sI "<base_url>/assets/<id версии>?download=1"` (id — из `read_network_requests` или `GET /api/projects/smoke-montage/snapshot`) → `200`, `Content-Disposition: attachment; filename="smoke-montage-v001.mp4"; filename*=UTF-8''…` (раскодированное имя — «Проба «монтаж»-v001.mp4»); `curl -s -H 'Range: bytes=0-99' -o /dev/null -w '%{http_code} %{size_download}' "<тот же адрес>"` → `206 100`.
4. «Показать в папке» → в Finder выделен `v001.mp4` (скриншот экрана); под кнопкой отказа нет.
5. «Версии»: одна карточка — «v1», бейдж «текущая», «Автопилот · <дата, время>», строка «черновой монтаж: 2 клипа, 3,0 с» (или то, что вернул `render` в `changes`); подсказка «„Принять ролик“ внизу принимает текущую версию».
6. «Схема монтажа»: шесть дорожек; на «Видео» два блока с шириной примерно 2:1; нажатие на первый → подпись «Клип: сцена 1 «…» · 0:00.0–0:02.0 ролика · из исходника с 0:00.0, 2,0 с…»; `read_console_messages` с `onlyErrors` — нарушений CSP нет.
7. «Открыть монтажный стол» → открылась новая вкладка со Studio (проект `current`); в ней `javascript_tool`: `localStorage.getItem('hyperframes-studio:telemetryDisabled')` → `"1"`; через 10 с (вкладка Code, Play) `performance.getEntriesByType('resource').map(e => e.name).filter(n => !n.startsWith('http://127.0.0.1') && !n.startsWith('blob:'))` → `[]`. На дашборде вместо кнопки — «Перейти к монтажному столу ↗» и «Закрыть стол».
8. В Studio сдвинуть или обрезать клип мышью → на дашборде не позже чем через 10 с плашка «Есть несобранные правки: …» с кнопкой «Собрать ролик → чат»; схема слоёв изменилась.
9. «Собрать ролик → чат» → окно запроса: в тексте `montage diff`, `montage render --by owner`, «бесплатная, подтверждения не нужно»; слов «платное действие» нет.
10. Как агент: `python3 skills/aimaster/scripts/creator_studio.py montage diff "$E2E/ws" smoke-montage` → строка правки; `… montage status "$E2E/ws" smoke-montage` → `revision`; `… montage render "$E2E/ws" smoke-montage --expected-revision <N> --by owner` → `v002`. На экране не позже чем через 10 с: v2 «Вы», «текущая»; плашка ушла; пилюля «текущая v2».
11. На карточке v1 «Сделать текущей» → тост «Текущая версия — v1», у v1 бейдж «текущая»; в «Истории решений» последняя запись от «Вы»; вкладка Studio показывает монтаж v1.
12. «Закрыть стол» → снова «Открыть монтажный стол»; `curl -s --noproxy '*' "http://127.0.0.1:<порт стола>/__hyperframes_config"` → соединение отклонено.
13. Без движка: остановить дашборд, запустить снова с `AIMASTER_HYPERFRAMES_DIR="$E2E/нет-движка"` → «Монтажный стол не установлен», причина по-русски, «Установить → чат» (в тексте запроса `engine.install_argv`, путей нет); кнопки стола нет; «Скачать», версии и «Сделать текущей» работают; схема — «Схема появится, когда будет установлен монтажный стол.» Вернуть `AIMASTER_HYPERFRAMES_DIR="$E2E/engine"` и перезапустить дашборд.

- [ ] **Step 4: Ширина 390 px (`resize_window` preset `mobile`, перезагрузить страницу)**

1. Одна колонка; превью по центру, не выше ~62 % высоты окна; `document.documentElement.scrollWidth <= 390` (нет прокрутки страницы вбок).
2. Нет «Открыть монтажный стол» и «Показать в папке»; есть подсказка «Монтажный стол открывается на компьютере…».
3. «Скачать» и «Собрать ролик → чат» — на всю ширину, высота ≥ 44 px (`getBoundingClientRect().height`).
4. Версии листаются вбок, карточка ≈ 78 % ширины.
5. Схема: подпись дорожки над полосой, полоса 44 px, нажатие на блок показывает подпись.
6. Подвал «Принять ролик» — на всю ширину, прилипает к низу.

- [ ] **Step 5: Выход дашборда и уборка**

1. Снова открыть стол с экрана (1400 px), затем остановить дашборд: `kill -TERM "$(cat "$E2E/serve.pid")"` (фоновый процесс SIGINT не получает, SIGTERM задача 11 превращает в Ctrl+C) → процесс завершился с кодом 0, порт стола отклоняет соединение (стол остановлен хранителем).
2. Ни одного своего процесса: `pgrep -fl "$E2E"` — пусто (иначе остановить по pid и отметить в отчёте как находку).
3. `resize_window` preset `desktop`; `rm -rf "$E2E"` (только своя папка с пометкой README).

- [ ] **Step 6: Отчёт**

По каждому пункту шагов 3–5 — «видно / не видно» и доказательство. Любое «не видно» — находка к исправлению до передачи владельцу; «проверено» пишется только о том, что действительно видно.

---

## Решения плана (в спецификации их нет или они уточнены)

1. **Страница-переходник — файл в папке монтажа, её отдаёт сама Studio** (`current/.hyperframes/aimaster-desk-open.html` → `GET /api/projects/current/preview/…` на origin стола). Проверено живьём (факты выше). Путь через `VITE_STUDIO_*` отклонён: он держится на отсутствии экранирования `</script>` в движке. Запись в README остаётся — о прямом `url`.
2. **`montage open` из чата тоже отдаёт `opener_url`**, канон велит давать человеку его: стол, открытый агентом, тоже без аналитики. Прежний `url` в ответе остаётся.
3. **Живое состояние экрана — не в снимке проекта, а в двух эндпоинтах**: снимок опрашивается раз в 8 с на всех экранах, а схема слоёв требует запуска Node (до 120 с после правки). Снимок по-прежнему несёт версии, текущую и `canvas` (план А); движок, стол, флаг несобранных правок и файл — `GET …/montage` (раз в 5 с, пока открыт экран); схема и устаревшие клипы — `GET …/montage/model` (только при смене `index_key`). Скиллы HyperFrames (хэши ~370 файлов) экрану не нужны и не считаются. Движок ищется раз в минуту (без движка — раз в 15 с).
4. **Простой стола — 60 минут** без опроса экрана «Сборка» этого проекта и без изменения `current/index.html`; при выходе дашборда останавливаются все столы, запущенные им; столы, открытые агентом из чата, дашборд не трогает (канон: `montage close`). Короче нельзя — вкладка дашборда скрыта, пока человек работает в Studio; дольше незачем — стол поднимается за секунду-две.
5. **Путь к файлу — от папки над рабочей** («<рабочая папка>/media/<проект>/montage/v001.mp4»), «Скопировать путь» копирует его же: абсолютные пути на экран не попадают и сервером браузеру не отдаются.
6. **«Принять» — главная кнопка подвала «Принять ролик»** (прежнее решение `approve` стадии «Сборка», принимает текущую версию); в листалке — подсказка, второй кнопки нет: два пути к одному решению дали бы двойную отправку.
7. **Потоковая отдача — для всех `/assets/<id>`**, а не только роликов монтажа: целостность та же (sha256 совпал с записью), но файл не читается целиком, а sha256 считается раз на отпечаток файла.
8. **«Показать в папке» и стол — только на компьютерной ширине и не в Telegram**; на 390 px — подсказка; шлюз Mini App их запрещает в любом написании пути. Телефонный стол через туннель — план В.
9. **Отказы монтажа — 422 `montage_refused` с русским текстом**, включая запрет по стадии (`AuthoringError`), который иначе стал бы немым 400.
10. **Старый итог видео-проекта без монтажа** показывается прежней раскладкой (спецификация: «Старые проекты без montage/ работают как раньше»); монтажная раскладка — когда монтаж есть или итога ещё нет.
11. **Превью учитывает сторону кадра**: вертикальный ролик — 9:16, а не полоса в рамке 16:9 из хэндоффа.
12. **Один промпт «Собрать ролик → чат»** на оба случая (черновика нет / есть): агент решает по `montage status`; `--by owner` — это «собери» человека.
13. **`creator_studio.py serve` закрывается по SIGTERM так же, как по Ctrl+C** (задача 11): агент, launchd и `kill` шлют SIGTERM, а без обработчика процесс умер бы, не остановив столы (найдено прогоном: фоновый процесс SIGINT не получает вовсе). Транспорт Telegram (`creator_studio_telegram.py`) живёт своим циклом — его выход проверяет план В.

## Вопросы владельцу

1. **Сколько ждать, прежде чем остановить монтажный стол.** Предлагаю: стол, открытый с дашборда, останавливается через 60 минут, если экран «Сборка» этого проекта закрыт и на столе ничего не правили, и вместе с дашбордом. Подходит — или держать стол открытым, пока работает дашборд?
2. **Что копирует «Скопировать путь».** Сейчас — тот же путь, что на экране: от папки над рабочей, без `/Users/…`. Если нужен полный путь (например, для «Переход к папке» в Finder), скажите: на экран он всё равно не попадёт, только в буфер.

## Самопроверка

**1. Покрытие спецификации и задания.**

| Требование | Задача |
|---|---|
| Плеер текущей версии (`renderPreview`), длительность | 14 (`durationText`, `orientation`), 18 |
| «Скачать» — `GET /assets/<id>?download=1`, `Content-Disposition: attachment; filename*=UTF-8''…`, потоком, Range работает | 5, 6, 7, 17 |
| «Показать в папке» — `POST …/montage/reveal`, Origin + CSRF; Finder `open -R`, Проводник `explorer /select,`, Linux `xdg-open` на папку; полный путь к программе, без оболочки | 8, 10, 11, 17 |
| Путь к файлу текстом и копированием; без абсолютных путей | 2, 3, 17 |
| Листалка версий: кто, когда, что изменилось; «Сделать текущей» (`POST …/montage/restore`, Origin + CSRF, `actor="you"`); «Принять» — прежнее решение | 3, 10, 11, 14, 17 (решение 6) |
| Схема слоёв только для просмотра: шесть дорожек, блоки по времени, нажатие — клип и кусок исходника | 2, 15, 17 |
| Плашка «Есть несобранные правки» | 2, 14, 17 |
| «Открыть монтажный стол» (`POST …/montage/desk`, ответ — URL, новая вкладка) и «Собрать ролик → чат» | 1, 3, 10, 11, 13, 17 |
| Переходник на origin Studio ставит `hyperframes-studio:telemetryDisabled=1`; честная запись в README | 1, 19; факты пробы |
| Нет движка — «Монтажный стол не установлен» и «Установить → чат»; остальной экран работает | 13, 14, 17, 18 |
| Ошибки состояния — текстом (`MontageError`, `model_error`, `stale_error`, записки стола) | 2, 3, 11, 14, 16, 17 |
| Дешёвое состояние отдельно от схемы; схема — при смене `index_key` | 2, 10, 16 |
| Действия со столом — по одному на проект; уборка реестра (исчезнувшая папка, завершившиеся Popen); простой и выход | 4, 9, 10, 11 |
| Шлюз Mini App не пускает к столу и к папке | 12 |
| Телефонная ширина 390 px по хэндоффу; стола на телефоне нет | 14, 17, 18, 20 |
| `assembleFinal` по канону: сразу, бесплатно, пересказ `montage diff`, новая версия; «Пересобрать → чат» — единая надпись | 13, 19 |
| Тесты: Python — Origin/CSRF, шлюз, заголовки потока и скачивания, argv по ОС, `actor` возврата; `node --test` — модели экрана; проверка контроллером в браузере | 1–12; 13–18; 20 |
| Канон и README | 1, 19 |

Вне плана Б (план В): «Прислать в Telegram», стол на телефоне через туннель, скачивание через шлюз Mini App.

**2. Заглушки.** Поиск по плану «TBD», «TODO», «implement later», «подобно задаче», «добавить обработку ошибок», «написать тесты» пуст; у каждой правки существующего файла указан точный якорь (строки или цитата старого текста), у новых файлов — текст целиком.

**3. Согласованность имён.** Сигнатуры из блоков Interfaces совпадают с кодом задач: `opener_url(studio_url)`, `ensure_opener(paths)`, `service.open_desk(...)["opener_url"]`; `stale_part(ctx)`, `model_part(ctx, engine, current_version, runner)`, `cheap_status(ctx, engine, reason)`, `model_status(ctx, engine, *, runner)`, `index_key(text)`, `shown_output(ctx, version_id)`; `desk_view(desk)`, `screen_status(ws, pid, *, locate, desk_state)`, `screen_model(ws, pid, *, locate, runner)`, `open_desk_for_screen(ws, pid, *, desk) -> (view, paths)`, `restore_as_owner(ws, pid, expected_revision, version_id)`, `current_output(ws, pid) -> (Path, str)`; `desk_children.sweep(*, kill, all_live=False)`; `AssetIndex.stored(asset_id)`, `AssetIndex.locate(relative_path)`, `open_asset(index, asset_id, verified) -> OpenedAsset(handle, mime_type, size, relative_path)`, `FileBody(handle, start, length)`; `Response(status, headers, body, stream=None)`, `write_response(handler, response)`; `download_names(relative_path, title_of) -> (name, fallback)`, `content_disposition(name, fallback)`; `reveal_command(target, *, system, environ, find, is_file)`, `reveal_file(target, *, system, environ, run, find, is_file)`, `reveal_available(...)`; `DeskKeeper(*, close_desk, kill, clock, idle, sweep_every, stamp)` с `lock/opened/closed/touch/watched/sweep/start/running/stop`; `EngineLookup(locate, *, clock, fresh, missing)`, `MontageScreen(workspace, *, keeper, engines, desk_factory, reveal, reveal_ready, runner)` с `status/model/open_desk/close_desk/restore(project_id, version_id, expected_revision)/reveal`; `montage_routes.match(path)`, `route(app, screen, method, project_id, part, headers, body)`; JS — `ASSEMBLE_LABEL`, `assembleLabel`, `assembleFinal(project, revision)`, `installMontage`, `updateMontageClips`, `montageApplies`, `montageScreen`, `versionLabel`, `whenText`, `versionRows`, `downloadHref`, `screenFlags({status, finished, phone, telegram})`, `notices({status, model, feedError})`, `orientation`, `durationText({status, model, project})`, `fmtTime`, `fmtLen`, `volumeText`, `sceneNames`, `clipDetail(clip, layer, label, names)`, `layerRows(model, project)`, `montageUrl`, `getMontage(projectId, part, fetchImpl)`, `postMontage(projectId, part, body)`, `refusalText`, `createMontageFeed({load, notify})`, `showMontage/hideMontage/montageState/refreshMontage`, `renderNotices/renderFileCard/renderMainActions/renderVersions/renderLayers`, `finalPreview(project, {ready, statusText, durationText, orientation})`. Ответ `desk` на экране везде один: `{state, url?, telemetry_off?, note?, forgotten?}`.

**4. Что проверено при подготовке плана (2026-09-28) и что нет.**

- Переходник — на настоящей Studio 0.8.75 (копия движка plan-verify, свой HOME, Chromium панели браузера) с контрольным прогоном без ключей; CSSOM-переменные — на странице с CSP дашборда.
- Весь код плана перенесён в чистую копию ветки (`git archive` коммита `d5348d2`) шаг за шагом, как написано в задачах, и прогнан: каждый «failing test» падал до реализации и проходил после; итог — `python3.14` и `python3.11`: 1070 тестов OK (12 skipped; было 947), `node --test` v2 — 177, `check_static_modules.mjs` — 119 модулей, `compileall` и `git diff --check` чисто. Числа тестов в шагах 4 взяты из этого прогона.
- Живой экран — там же: `creator_studio.py serve` на синтетическом проекте (две версии собраны подменённым движком, настоящего движка нет) в панели браузера на 1400 и 375 px: монтажная раскладка, вертикальное превью, «Ролик v1», «Скачать» (`Content-Disposition` с именем проекта), путь без `/Users/`, «Монтажный стол не установлен» + «Установить → чат», листалка версий, «Сделать текущей» (история — «Вы»), `POST …/reveal` без CSRF → 403, нет ошибок в консоли, нет прокрутки вбок на телефоне.
- Прогоном найдено и исправлено в плане: HEAD на `/assets/` дашборд не принимает (тест убран); изменённый файл даёт 400, как и раньше у `resolve`; вертикальное превью на телефоне сжималось до 300 px; порядок вычисления в одном тесте хранителя; не-ASCII CSRF в тесте; SIGTERM не закрывал дашборд (решение 13).
- Не проверено до исполнения: стол из дашборда на настоящем движке и правка мышью (задача 20); переходник на Windows и Linux (маршрут Studio тот же, живьём не пробовался); Проводник Windows с `/select,` — только разбор командной строки в тестах; «Показать в папке» живьём (Finder открывался бы на экране владельца — это пункт задачи 20).

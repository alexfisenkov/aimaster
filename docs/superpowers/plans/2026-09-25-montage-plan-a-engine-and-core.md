# Монтаж на HyperFrames, план А (движок, установка, ядро монтажа) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Этапы 1 и 2 спецификации: поставить закреплённый HyperFrames 0.8.75 с браузером и скиллами одной командой установщика, проверить его на CI трёх ОС и дать агенту монтаж проекта через `creator_studio.py montage …` — черновик, смысловой diff, правки, сборка MP4 версиями, возврат к версии, монтажный стол.

**Architecture:** Новый пакет `skills/aimaster/studio/montage/` — по файлу на ответственность (60–150 строк). Движок живёт в `<user_data_dir>/tools/hyperframes` со своим HOME (`home/`), запускается без оболочки как `node <…>/hyperframes/bin/hyperframes.mjs`. Источник правды о монтаже — `montage/current/index.html` композиции; в `state.json` только компактный раздел `montage` (версии, текущая, размер кадра), который пишется той же транзакцией, что `assembly`. Всё, что запускает движок, принимает подменяемый `runner`; тесты работают без Node через `FakeHyperframes`, реальный движок проверяют CI и сквозной тест.

**Tech Stack:** Python 3.11+ (только стандартная библиотека), unittest, HyperFrames 0.8.75 (npm, Node.js ≥ 22), FFmpeg/ffprobe, GitHub Actions (ubuntu/macos/windows).

**Spec:** `docs/superpowers/specs/2026-09-25-montage-hyperframes-design.md`

## Global Constraints

- Версия движка закреплена: `hyperframes@0.8.75`; меняется только выпуском навыка после зелёного CI (`studio/montage/engine.json`).
- Node.js ≥ 22 (`engines.node` пакета `hyperframes`); FFmpeg и ffprobe обязательны для черновика и сборки.
- Движок ставится `npm install --prefix <user_data_dir>/tools/hyperframes hyperframes@0.8.75`, не глобально, без автообновления.
- Любой запуск движка — без оболочки, по полному пути к `node` и к `node_modules/hyperframes/bin/hyperframes.mjs`; npm — как `node <npm-cli.js>`. Никаких `npx`, `npx.cmd`, `npm.cmd`, `shell=True`.
- Переменные каждого запуска: `HYPERFRAMES_NO_UPDATE_CHECK=1`, `HYPERFRAMES_NO_AUTO_INSTALL=1`, `HYPERFRAMES_NO_TELEMETRY=1`, `HYPERFRAMES_SKIP_SKILLS=1`; `HOME` (на Windows ещё `USERPROFILE`) = `<prefix>/home`; `HYPERFRAMES_BROWSER_PATH` = браузер из записи установщика; кэш кадров — `<prefix>/cache/frames` (`--frames-cache-dir` у `render`).
- Черновик: без GSAP, без внешних URL, без внешних шрифтов (`font-family: sans-serif`), корень с `data-no-timeline`.
- Медиа композиции — только внутри `montage/current/`; в `assets/` — жёсткая ссылка на файл из `<workspace>/media/`, иначе копия. Симлинки не используются.
- Версии не удаляются и не перезаписываются; «сделать текущей» копирует снимок в `current/`.
- MP4 версии: `<workspace>/media/<project-id>/montage/vNNN.mp4`, регистрация в `AssetIndex` с ролью `result`.
- Раздел `montage` в `state.json` меняется только через `authoring_support.mutate` с `expected_revision` и пишет запись в историю проекта.
- Меняющие команды CLI (`draft`, `edit`, `render`, `restore`) требуют `--expected-revision`; все печатают один JSON-объект; отказ — код 3 без traceback.
- Фото-проекты монтажом не затрагиваются.
- Пути — только `pathlib`; Windows-ветки проверяются подменой `os.name`/`IS_WINDOWS`.
- Модули — около 60–150 строк, одна ответственность (самые длинные в плане — 151–162 строки: `html_doc.py`, `install_montage_fetch.py`, `draft_plan.py`); `scripts/install.py` (720 строк) только вызывает `scripts/install_montage.py`.
- Реальные генерации и платные сервисы не используются; реальные проекты владельца не трогаются; тестовые медиа генерирует ffmpeg или собираются минимальные MP4/WAV в коде.
- Каждая задача заканчивается зелёными: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'`, `python3 -m compileall -q skills/aimaster`, `git diff --check`, а если трогали статику — `node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs` и `node --test skills/aimaster/studio/static/ui/v2/*.test.mjs`.

---

## Факты пробы, на которые опирается план (проверено 2026-09-25 командами)

| Факт | Как проверено | Что из него следует в плане |
|---|---|---|
| Тег `v0.8.75` есть: коммит `a95cb96a5dd3c1f7b31266a4b470590c86ad231f`, дерево `skills/` — `553a635bb8604fa571cf155d7df09171ecf4d6b9` | `git ls-remote --tags`, неполный клон без блобов | `engine.json` закрепляет коммит и дерево |
| В `skills/` тега 21 скилл; «ядро» HyperFrames (`FALLBACK_CORE_SKILLS` в CLI) — 10: `hyperframes`, `hyperframes-animation`, `-audio`, `-cli`, `-core`, `-creative`, `-keyframes`, `-registry`, `-studio`, `media-use`. Остальные 11 — сценарные (`figma`, `slideshow`, `general-video`, `music-to-video`, …) | `git ls-tree`, код `dist/cli.js` | ставим только ядро; `figma` и другие сценарные — нет (конфликт имён) |
| `skills-manifest.json` тега хранит хэш каждого скилла; алгоритм (`hashSkillBundle`) воспроизведён на Python и совпал на всех 21 скилле | архив тега, скрипт сверки | `bundle_hash` в установщике, проверка каждого скилла |
| Ядро — 370 файлов, 4,7 МБ; дерево отдаёт одним запросом `GET /repos/heygen-com/hyperframes/git/trees/553a635…?recursive=1` (1127 записей, не обрезано); архив всего тега — 125,6 МБ | `curl` | качаем файлы по одному с raw.githubusercontent.com по закреплённому коммиту, сверяем git-хэш блоба |
| npm-пакет несёт только 3 скилла (`hyperframes`, `hyperframes-cli` совпали с тегом; `media-use` — другой, 173 файла). `init` ставит скиллы через `npx skills add` с ветки `main` и нужен `git` | `dist/skills`, `dist/cli.js` | скиллы не берём из пакета и не через `init` |
| В репозитории LFS есть, но под `skills/` его нет | `.gitattributes` тега | прямое скачивание файлов безопасно |
| `hyperframes browser ensure` качает `chrome-headless-shell` в `$HOME/.cache/hyperframes/chrome`; `browser path` без него **молча отдаёт системный Chrome** | запуск с пустым HOME | установщик пишет путь скачанного браузера в запись, движок всегда передаёт `HYPERFRAMES_BROWSER_PATH` |
| `timeline --json` с папкой позиционным аргументом не работает («Unknown command»): список — только из cwd проекта; правки принимают `--dir` | запуски CLI | список: `cwd=current`, правки: `--dir .` |
| Отказ правки: код 2, JSON `{ok:false, reason, fix}` в stderr. `lint --json`: код 1 при ошибках, JSON в stdout. `render` без `--json` для одиночного ролика | запуски CLI | `run_engine_json(ok_codes=…)`, лог рендера разбираем как текст |
| `timeline set <ref> volume=<n>` (также `rate=`, `track=`); `trim` — `--start/--end/--duration`, начало не сдвигает `data-media-start`; `move` за конец ролика отказывает; `split` сам ставит `data-media-start` новой части; `undo <квитанция>` работает | запуски CLI на копии композиции | выравнивание под Studio в `edit_ops.py` |
| Строки `timeline --json` не содержат `data-media-start` | вывод CLI | модель читает атрибуты из `index.html` сама |
| Studio при правке мышью меняет `data-track-index` (музыка 1→0, голос 2→1) | диффы `v-link.index.*.html` | слой клипа — наш атрибут `data-am-layer`, дорожка в модель не входит |
| `data-fade-in/out` — это **громкость** на краях клипа, не картинка (документация `html-schema.md`) | чтение схемы | визуальный переход — CSS-анимация, `data-fade-*` — только звук |
| Композиция без GSAP: корень с `data-no-timeline`, переход — CSS `@keyframes` (рантайм перематывает: яркость кадров 1.6/1.75/2.2 с — 17 → 49 → 93 из 93), титр `font-family: sans-serif` с кириллицей. `lint` — 0 ошибок; `render` проходит с отрезанной сетью Node (`NODE_USE_ENV_PROXY=1`, прокси на закрытый порт — проверено, что fetch падает) и пустым кэшем шрифтов, кириллица титра видна | проба `plan-probe/d`, кадр 0,5 с | GSAP в `assets/` **не нужен** ни рантайму, ни черновику; рендер без сети работает, CI подтверждает это на Linux |
| **Но при доступной сети** HyperFrames сам ходит в Google Fonts: `normalizeSystemFontPrimaryFamilies` подменяет первичное `sans-serif` на `Inter` ради детерминизма, встроенный Inter — только латиница, недостающие диапазоны (кириллица) он качает с fonts.googleapis.com на каждом рендере («Fetched 11 font face(s) for "Inter" from Google Fonts»). Без сети молча берёт системный шрифт для кириллицы | прогон кода плана на настоящем движке с чистым кэшем шрифтов; `dist/cli.js` | известное ограничение (спецификация это разрешает): лог-строка шрифтов — предупреждение, не ошибка; CDN-скрипты — ошибка. Полная автономность — только своим шрифтом в `assets/` (вопрос владельцу) |
| Python с python.org на macOS без «Install Certificates.command» не проверяет сертификат GitHub (`CERTIFICATE_VERIFY_FAILED`, в хранилище 0 корневых) | прогон установщика скиллов на этой машине | `ssl_context()` дополняет пустое хранилище системным `/etc/ssl/cert.pem` |
| Без `data-no-timeline` `lint` предупреждает `missing_data_no_timeline`, рендер ждёт таймлайн 45 с | проба | атрибут обязателен в черновике |
| Arial/Helvetica HyperFrames подменяет на Inter и тянет с Google Fonts; семейства из `GENERIC_FAMILIES` (`sans-serif` и др.) — нет | `dist/cli.js`, лог рендера пробы | черновик — только `sans-serif` |
| `lint` не ловит внешнюю таблицу стилей `https://fonts.googleapis.com/…` | проба `plan-probe/e` | своя проверка внешних ссылок в `media_sync.py` |
| Качество `render`: `draft` — CRF 28, `standard` — CRF 18, `looks` (по умолчанию) — CRF 16, `high` — CRF 15 | `dist/cli.js` | версии собираются в `standard`, CI — в `draft` |
| `preview --foreground --json --no-open --port N` первой строкой печатает `{"ok":true,"result":{"port","pid","studioUrl","ready":true,…}}` | `logs/preview.log` пробы | `desk.py` ждёт эту строку |
| Движок: 124 МБ `node_modules`, браузер 196 МБ на диске | `du` | сообщение «Качаю компонент для сборки видео (~100 МБ)» |
| npm у Homebrew: `/opt/homebrew/bin/node` → `Cellar/node/<v>/bin/node`, а `npm-cli.js` — в `/opt/homebrew/lib/node_modules/npm/bin/`; на Windows — рядом с `node.exe` в `node_modules\npm\bin\` | `realpath` на этой машине | `npm_cli_js()` проверяет три раскладки |
| Текущий CI FFmpeg не ставит вовсе; Node — `actions/setup-node@v4` с `22` | `.github/workflows/ci.yml` | новая задача CI ставит FFmpeg: apt / brew / choco |
| `AssetIndex` не знает размер кадра MP4 (`_mp4` отдаёт `None, None`) | `studio/assets.py:492-518` | `canvas.py` берёт размер у ffprobe |
| `MAX_ASSET_BYTES` = 128 МБ | `studio/workspace.py` | сборка больше — понятный отказ |

## Раскладка файлов

Новые (все пути от корня репозитория):

| Файл | Ответственность |
|---|---|
| `skills/aimaster/studio/montage/__init__.py` | `MontageError`, имена слоёв и дорожек |
| `skills/aimaster/studio/montage/engine.json` | закреплённая версия движка, тайм-ауты, скиллы |
| `skills/aimaster/studio/montage/engine.py` | где стоит движок, готов ли (Node, пакет, браузер) |
| `skills/aimaster/studio/montage/engine_cli.py` | запуск CLI без оболочки, окружение, JSON, отдельный процесс |
| `skills/aimaster/studio/montage/probe.py` | ffprobe → `MediaInfo` |
| `skills/aimaster/studio/montage/canvas.py` | размер кадра |
| `skills/aimaster/studio/montage/paths.py` | раскладка `montage/`, путь MP4 версии |
| `skills/aimaster/studio/montage/html_doc.py` | чтение атрибутов и точечная правка `index.html` |
| `skills/aimaster/studio/montage/media_sync.py` | ссылка/копия медиа, проверка ссылок композиции |
| `skills/aimaster/studio/montage/draft_plan.py` | проект → план черновика (чистая функция) |
| `skills/aimaster/studio/montage/draft_html.py` | план → HTML композиции |
| `skills/aimaster/studio/montage/draft.py` | создать / обновить устаревшее / пересобрать `current/` |
| `skills/aimaster/studio/montage/model.py` | модель монтажа из `timeline --json` + атрибутов, хэш, вид слоёв |
| `skills/aimaster/studio/montage/model_diff.py` | смысловой diff по-русски |
| `skills/aimaster/studio/montage/versions.py` | снимки версий, список, возврат файлов |
| `skills/aimaster/studio/montage/montage_state.py` | раздел `state["montage"]` + `assembly` + история одной транзакцией |
| `skills/aimaster/studio/montage/edit.py` | правка: снимок для отката, проверка хэша, `undo` |
| `skills/aimaster/studio/montage/edit_ops.py` | сами операции поверх CLI, выровненные под Studio |
| `skills/aimaster/studio/montage/context.py` | всё о проекте, что нужно монтажу |
| `skills/aimaster/studio/montage/verify.py` | проверки lint, ffprobe, сетевых следов в логе |
| `skills/aimaster/studio/montage/render.py` | сборка версии целиком |
| `skills/aimaster/studio/montage/proc.py` | жив ли процесс, остановка с детьми |
| `skills/aimaster/studio/montage/desk.py` | интерфейс `Desk` и `StudioDesk` |
| `skills/aimaster/studio/montage/status.py` | состояние монтажа одним словарём |
| `skills/aimaster/studio/montage/service.py` | вход для CLI и дашборда |
| `skills/aimaster/scripts/install_montage_node.py` | Node.js 22+: найти, поставить, найти `npm-cli.js` |
| `skills/aimaster/scripts/install_montage_engine.py` | HyperFrames через npm, браузер для сборки |
| `skills/aimaster/scripts/install_montage_fetch.py` | скачивание и сверка скиллов HyperFrames |
| `skills/aimaster/scripts/install_montage_skills.py` | подключение скиллов в каталоги агентов, отчёт |
| `skills/aimaster/scripts/install_montage.py` | раздел `montage` отчёта, отдельный запуск для CI |
| `skills/aimaster/scripts/creator_studio_montage.py` | подкоманды `montage …` |
| `skills/aimaster/scripts/montage_ci_check.py` | проверка движка на CI (рендер 3 с) |
| `skills/aimaster/scripts/montage_testkit.py` | заготовки тестов (не `test_*`) |
| `skills/aimaster/scripts/test_montage_*.py`, `test_install_montage*.py` | тесты |
| `skills/aimaster/references/montage.md` | канон монтажа для агента |

Меняются: `studio/platform_compat.py` (`find_program`), `studio/store.py` (`project_dir`), `studio/domain.py` (виды истории), `studio/projection.py` (раздел `montage`), `studio/authoring_qa.py` (`apply_assembly`), `studio/static/ui/history-panel.js` (подписи истории), `scripts/install.py`, `scripts/test_install.py`, `scripts/creator_studio.py`, `scripts/smoke_clean_machine.py`, `.github/workflows/ci.yml`, `references/phases/06-assembly.md`, `references/autopilot.md`, `references/creator-studio.md`, `SKILL.md`, `INSTALL_WITH_AGENT.md`, `README.md`.

## Порядок задач

Этап 1 — движок и установка: задачи 1–6. Этап 2 — монтаж для агента: задачи 7–20. Каждая задача оставляет ветку зелёной и коммитится отдельно.

---

### Task 1: Закреплённая версия и поиск движка

**Files:**
- Create: `skills/aimaster/studio/montage/__init__.py`
- Create: `skills/aimaster/studio/montage/engine.json`
- Create: `skills/aimaster/studio/montage/engine.py`
- Modify: `skills/aimaster/studio/platform_compat.py` (новая функция `find_program` после `ensure_utf8_stdio`)
- Test: `skills/aimaster/scripts/test_montage_engine.py`

**Interfaces:**
- Consumes: `studio.platform_compat.user_data_dir(*, home=None, environ=None) -> Path`, `IS_WINDOWS`.
- Produces:
  - `studio.montage.MontageError(RuntimeError)`; `LAYERS: tuple[str, ...] = ("video", "titles", "voice", "music", "fx", "atmos")`; `LAYER_LABELS: dict[str, str]`; `TRACK_OF_LAYER: dict[str, int]`; `AUDIO_LAYER_NAMES = ("voice", "music", "fx", "atmos")`.
  - `platform_compat.find_program(name: str, *, environ=None) -> str | None`.
  - `engine.PREFIX_ENV = "AIMASTER_HYPERFRAMES_DIR"`, `engine.RECORD_NAME = "aimaster-engine.json"`.
  - `engine.load_pin() -> dict`; `engine.tools_prefix(*, home=None, environ=None) -> Path`; `engine.entry_script(prefix: Path) -> Path`; `engine.installed_version(prefix: Path) -> str | None`; `engine.find_node(*, environ=None) -> str | None`; `engine.node_major(node: str, *, run=subprocess.run) -> int | None`; `engine.read_record(prefix: Path) -> dict`; `engine.write_record(prefix: Path, record: dict) -> None`.
  - `@dataclass(frozen=True) engine.Engine(node: str, script: Path, prefix: Path, version: str, browser: str | None)`.
  - `engine.locate(*, home=None, environ=None, run=subprocess.run) -> tuple[Engine | None, str]` (причина по-русски, пустая при успехе); `engine.engine_status(...) -> {"state": "installed"|"missing", "version", "wanted", "reason", "prefix"}`; `engine.require_engine(**kwargs) -> Engine` (иначе `MontageError`).

- [ ] **Step 1: Write the failing test**

Создать `skills/aimaster/scripts/test_montage_engine.py`:

```python
#!/usr/bin/env python3
"""Движок HyperFrames: закреплённая версия, где стоит, готов ли (Node 22+, пакет, браузер)."""

from __future__ import annotations

import json
import os
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

from studio import platform_compat  # noqa: E402
from studio.montage import MontageError, engine  # noqa: E402


def node_says(version: str):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, (version + "\n").encode(), b"")
    return run


class _Prefix(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.prefix = self.base / "tools" / "hyperframes"
        self.env = {engine.PREFIX_ENV: str(self.prefix), "PATH": ""}

    def install_package(self, version="0.8.75"):
        package = self.prefix / "node_modules" / "hyperframes"
        (package / "bin").mkdir(parents=True)
        (package / "bin" / "hyperframes.mjs").write_text("// заглушка\n", encoding="utf-8")
        (package / "package.json").write_text(
            json.dumps({"name": "hyperframes", "version": version}), encoding="utf-8")

    def install_browser(self):
        browser = self.prefix / "home" / ".cache" / "hyperframes" / "chrome" / "chrome-headless-shell"
        browser.parent.mkdir(parents=True)
        browser.write_text("", encoding="utf-8")
        engine.write_record(self.prefix, {"browser": str(browser), "version": "0.8.75"})
        return browser

    def locate(self, version="v22.3.0"):
        with mock.patch.object(engine, "find_node", return_value="/usr/local/bin/node"):
            return engine.locate(environ=self.env, run=node_says(version))


class PinTests(unittest.TestCase):
    def test_pin_is_hyperframes_0875_with_ten_core_skills(self):
        pin = engine.load_pin()
        self.assertEqual((pin["package"], pin["version"], pin["node_min_major"]),
                         ("hyperframes", "0.8.75", 22))
        skills = pin["skills"]
        self.assertEqual(skills["tag"], "v0.8.75")
        self.assertEqual(skills["commit"], "a95cb96a5dd3c1f7b31266a4b470590c86ad231f")
        self.assertEqual(len(skills["bundles"]), 10)
        self.assertNotIn("figma", skills["bundles"])
        self.assertEqual(skills["bundles"]["hyperframes"], {"hash": "e4788caea448bc93", "files": 26})


class PrefixTests(unittest.TestCase):
    def test_default_prefix_is_user_data_tools(self):
        with tempfile.TemporaryDirectory() as home:
            expected = platform_compat.user_data_dir(home=Path(home), environ={}) / "tools" / "hyperframes"
            self.assertEqual(engine.tools_prefix(home=Path(home), environ={}), expected)

    def test_override_must_be_absolute(self):
        self.assertNotEqual(engine.tools_prefix(environ={engine.PREFIX_ENV: "relative/dir"}),
                            Path("relative/dir"))
        absolute = Path(tempfile.gettempdir()).resolve() / "hf"
        self.assertEqual(engine.tools_prefix(environ={engine.PREFIX_ENV: str(absolute)}), absolute)


class LocateTests(_Prefix):
    def test_no_node(self):
        with mock.patch.object(engine, "find_node", return_value=None):
            found, reason = engine.locate(environ=self.env)
        self.assertIsNone(found)
        self.assertIn("Node.js", reason)

    def test_old_node_is_refused(self):
        found, reason = self.locate("v20.11.1")
        self.assertIsNone(found)
        self.assertIn("22", reason)

    def test_missing_package(self):
        found, reason = self.locate()
        self.assertIsNone(found)
        self.assertIn("не установлен", reason)

    def test_other_version_is_refused(self):
        self.install_package("0.8.74")
        found, reason = self.locate()
        self.assertIsNone(found)
        self.assertIn("0.8.74", reason)

    def test_browser_record_is_required(self):
        self.install_package()
        found, reason = self.locate()
        self.assertIsNone(found)
        self.assertIn("браузер", reason)

    def test_ready_engine(self):
        self.install_package()
        browser = self.install_browser()
        found, reason = self.locate("v24.1.0")
        self.assertEqual(reason, "")
        self.assertEqual(found.version, "0.8.75")
        self.assertEqual(found.browser, str(browser))
        self.assertEqual(found.script,
                         self.prefix / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs")

    def test_status_and_require(self):
        status = engine.engine_status(environ=self.env)
        self.assertEqual((status["state"], status["wanted"]), ("missing", "0.8.75"))
        with mock.patch.object(engine, "find_node", return_value=None):
            with self.assertRaises(MontageError) as caught:
                engine.require_engine(environ=self.env)
        self.assertIn("install.py --install-deps", str(caught.exception))


class FindNodeTests(unittest.TestCase):
    def test_node_major_parses_version(self):
        self.assertEqual(engine.node_major("node", run=node_says("v22.3.0")), 22)
        self.assertIsNone(engine.node_major("node", run=node_says("garbage")))

    def test_windows_takes_exe_not_cmd_and_ignores_relative_path(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            (base / "npmdir").mkdir()
            (base / "npmdir" / "node.cmd").write_text("", encoding="utf-8")
            program_files = base / "Program Files"
            (program_files / "nodejs").mkdir(parents=True)
            exe = program_files / "nodejs" / "node.exe"
            exe.write_text("", encoding="utf-8")
            env = {"PATH": os.pathsep.join(["relative", str(base / "npmdir")]),
                   "ProgramFiles": str(program_files)}
            with mock.patch.object(platform_compat, "IS_WINDOWS", True), \
                    mock.patch.object(engine, "IS_WINDOWS", True):
                self.assertEqual(engine.find_node(environ=env), str(exe))

    def test_posix_needs_executable_bit(self):
        if os.name == "nt":
            self.skipTest("бит исполнения есть только на POSIX")
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp).resolve()
            node = folder / "node"
            node.write_text("#!/bin/sh\n", encoding="utf-8")
            self.assertIsNone(platform_compat.find_program("node", environ={"PATH": str(folder)}))
            node.chmod(0o755)
            self.assertEqual(platform_compat.find_program("node", environ={"PATH": str(folder)}),
                             str(node))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_engine.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/__init__.py`:

```python
"""Монтаж на HyperFrames (docs/superpowers/specs/2026-09-25-montage-hyperframes-design.md).

Пакет разбит по ответственностям: engine* — движок, draft* — черновик,
model* — модель и смысловой diff, versions — версии, edit* — правки,
render/verify — сборка, desk — монтажный стол, service — вход для CLI и дашборда.
"""

from __future__ import annotations


class MontageError(RuntimeError):
    """Отказ монтажа; текст по-русски и показывается человеку как есть."""


LAYERS = ("video", "titles", "voice", "music", "fx", "atmos")
LAYER_LABELS = {"video": "Видео", "titles": "Титры", "voice": "Голос",
                "music": "Музыка", "fx": "Шумы", "atmos": "Атмосфера"}
TRACK_OF_LAYER = {layer: index for index, layer in enumerate(LAYERS)}
AUDIO_LAYER_NAMES = ("voice", "music", "fx", "atmos")
```

`skills/aimaster/studio/montage/engine.json`:

```json
{
  "package": "hyperframes",
  "version": "0.8.75",
  "node_min_major": 22,
  "render_quality": "standard",
  "timeouts": {
    "cli": 120,
    "render": 1800,
    "preview_start": 30,
    "npm_install": 900,
    "browser": 900
  },
  "skills": {
    "repo": "heygen-com/hyperframes",
    "tag": "v0.8.75",
    "commit": "a95cb96a5dd3c1f7b31266a4b470590c86ad231f",
    "tree": "553a635bb8604fa571cf155d7df09171ecf4d6b9",
    "bundles": {
      "hyperframes": {"hash": "e4788caea448bc93", "files": 26},
      "hyperframes-animation": {"hash": "9add954e7eff1aa6", "files": 122},
      "hyperframes-audio": {"hash": "7e9a13aba7143c08", "files": 7},
      "hyperframes-cli": {"hash": "d994bb25706982ee", "files": 11},
      "hyperframes-core": {"hash": "b4d9c7b3d0e5ae75", "files": 11},
      "hyperframes-creative": {"hash": "0803c90800fda4ce", "files": 79},
      "hyperframes-keyframes": {"hash": "16a7da9819e7e4ab", "files": 3},
      "hyperframes-registry": {"hash": "4a1a7daf23a9e569", "files": 12},
      "hyperframes-studio": {"hash": "b063eaa9eb1e4b9b", "files": 1},
      "media-use": {"hash": "b35de041b87e763d", "files": 98}
    }
  }
}
```

В `skills/aimaster/studio/platform_compat.py` добавить в конец файла:

```python
def find_program(name: str, *, environ=None) -> str | None:
    """Полный путь к программе из абсолютных элементов PATH или None.

    Пустой или относительный элемент PATH означал бы текущую папку, где может
    лежать чужой файл. На Windows берём только настоящие .exe/.com: .cmd и
    .bat запускаются через cmd.exe, а оболочку монтаж не использует.
    """

    environ = os.environ if environ is None else environ
    folders = []
    for entry in environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if entry and os.path.isabs(entry) and entry not in folders:
            folders.append(entry)
    suffixes = ("",) if not IS_WINDOWS or os.path.splitext(name)[1] else (".exe", ".com")
    for folder in folders:
        for suffix in suffixes:
            candidate = os.path.join(folder, name + suffix)
            if os.path.isfile(candidate) and (IS_WINDOWS or os.access(candidate, os.X_OK)):
                return candidate
    return None
```

`skills/aimaster/studio/montage/engine.py`:

```python
"""Где стоит движок HyperFrames и готов ли он к работе.

Движок ставит scripts/install_montage.py в <user_data_dir>/tools/hyperframes:
`npm install --prefix`, свой HOME (home/) для кэшей и браузера и запись
aimaster-engine.json с путём к скачанному браузеру. Переменная
AIMASTER_HYPERFRAMES_DIR подменяет папку — для CI и смоука.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..platform_compat import IS_WINDOWS, find_program, user_data_dir
from . import MontageError

PIN_FILE = Path(__file__).with_name("engine.json")
RECORD_NAME = "aimaster-engine.json"
PREFIX_ENV = "AIMASTER_HYPERFRAMES_DIR"
_VERSION = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def load_pin() -> dict:
    return json.loads(PIN_FILE.read_text(encoding="utf-8"))


def tools_prefix(*, home=None, environ=None) -> Path:
    environ = os.environ if environ is None else environ
    override = environ.get(PREFIX_ENV)
    if override and Path(override).is_absolute():
        return Path(override)
    return user_data_dir(home=home, environ=environ) / "tools" / "hyperframes"


def entry_script(prefix: Path) -> Path:
    return Path(prefix) / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"


def installed_version(prefix: Path) -> str | None:
    manifest = Path(prefix) / "node_modules" / "hyperframes" / "package.json"
    try:
        version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return None
    return version if isinstance(version, str) else None


def find_node(*, environ=None) -> str | None:
    environ = os.environ if environ is None else environ
    found = find_program("node", environ=environ)
    if found or not IS_WINDOWS:
        return found
    # winget ставит Node в Program Files; PATH этого процесса про него ещё не знает
    for base in (environ.get("ProgramFiles"), environ.get("ProgramW6432")):
        candidate = Path(base) / "nodejs" / "node.exe" if base else None
        if candidate is not None and candidate.is_file():
            return str(candidate)
    return None


def node_major(node: str, *, run=subprocess.run) -> int | None:
    try:
        proc = run([node, "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION.search((proc.stdout or b"").decode("utf-8", errors="replace"))
    return int(match.group(1)) if proc.returncode == 0 and match else None


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


@dataclass(frozen=True)
class Engine:
    node: str
    script: Path
    prefix: Path
    version: str
    browser: str | None


def locate(*, home=None, environ=None, run=subprocess.run) -> tuple[Engine | None, str]:
    """(движок, "") если всё на месте, иначе (None, причина по-русски)."""

    pin = load_pin()
    prefix = tools_prefix(home=home, environ=environ)
    node = find_node(environ=environ)
    if node is None:
        return None, "не найден Node.js"
    major = node_major(node, run=run)
    if major is None or major < pin["node_min_major"]:
        return None, (f"нужен Node.js {pin['node_min_major']} или новее "
                      f"(найден {major if major is not None else 'неизвестной версии'})")
    script = entry_script(prefix)
    version = installed_version(prefix)
    if not script.is_file() or version is None:
        return None, f"HyperFrames не установлен в {prefix}"
    if version != pin["version"]:
        return None, f"стоит HyperFrames {version}, нужен {pin['version']}"
    browser = read_record(prefix).get("browser")
    if not browser or not Path(browser).is_file():
        return None, "не скачан браузер для сборки видео"
    return Engine(node=node, script=script, prefix=prefix, version=version, browser=browser), ""


def engine_status(*, home=None, environ=None, run=subprocess.run) -> dict:
    found, reason = locate(home=home, environ=environ, run=run)
    return {"state": "installed" if found else "missing",
            "version": found.version if found else None,
            "wanted": load_pin()["version"], "reason": reason,
            "prefix": str(tools_prefix(home=home, environ=environ))}


def require_engine(**kwargs) -> Engine:
    found, reason = locate(**kwargs)
    if found is None:
        raise MontageError(
            f"Монтажный движок не готов: {reason}. Поставьте его: "
            "python3 skills/aimaster/scripts/install.py --install-deps")
    return found
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_engine.py' -v`
Expected: PASS (13 tests; `test_posix_needs_executable_bit` на Windows — skipped).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: все тесты зелёные, compileall молчит, `git diff --check` пуст.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/__init__.py skills/aimaster/studio/montage/engine.json skills/aimaster/studio/montage/engine.py skills/aimaster/studio/platform_compat.py skills/aimaster/scripts/test_montage_engine.py
git commit -m "feat(montage): pinned HyperFrames 0.8.75 and engine locator"
```

---

### Task 2: Запуск CLI движка без оболочки

**Files:**
- Create: `skills/aimaster/studio/montage/engine_cli.py`
- Test: `skills/aimaster/scripts/test_montage_engine_cli.py`

**Interfaces:**
- Consumes: `engine.Engine`, `studio.montage.MontageError`, `platform_compat.IS_WINDOWS`.
- Produces:
  - `engine_cli.QUIET_FLAGS: dict[str, str]`; `CREATE_NEW_PROCESS_GROUP = 0x200`; `CREATE_NO_WINDOW = 0x08000000`.
  - `@dataclass(frozen=True) engine_cli.EngineResult(code: int, stdout: str, stderr: str, timed_out: bool = False)`.
  - `engine_cli.engine_home(engine) -> Path` (= `prefix/home`); `engine_cli.frames_cache(engine) -> Path` (= `prefix/cache/frames`).
  - `engine_cli.engine_env(engine, base: Mapping[str, str] | None = None) -> dict[str, str]`.
  - `engine_cli.argv_for(engine, args) -> list[str]`.
  - `engine_cli.run_engine(engine, args, *, cwd: Path, timeout: float, runner=subprocess.run) -> EngineResult`.
  - `engine_cli.run_engine_json(engine, args, *, cwd: Path, timeout: float, ok_codes=(0,), runner=subprocess.run) -> dict` (отказ → `MontageError`).
  - `engine_cli.popen_engine(engine, args, *, cwd: Path, log_path: Path, popen=subprocess.Popen)` — процесс, переживающий вызвавший CLI.
  - `class engine_cli.EngineRunner` с методами `json(engine, args, *, cwd, timeout, ok_codes=(0,)) -> dict` и `run(engine, args, *, cwd, timeout) -> EngineResult` — именно этот объект все следующие задачи принимают параметром `runner` (тесты подставляют `FakeHyperframes` с теми же методами).

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_engine_cli.py`:

```python
#!/usr/bin/env python3
"""Запуск HyperFrames: node + JS-вход, без оболочки, свои переменные и HOME."""

from __future__ import annotations

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

from studio.montage import MontageError, engine, engine_cli  # noqa: E402


class FakeRun:
    def __init__(self, code=0, stdout=b"", stderr=b"", timeout=False):
        self.code, self.stdout, self.stderr, self.timeout = code, stdout, stderr, timeout
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.timeout:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        return subprocess.CompletedProcess(argv, self.code, self.stdout, self.stderr)


def make_engine(base: Path, browser=True) -> engine.Engine:
    return engine.Engine(node="/opt/node/bin/node",
                         script=base / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs",
                         prefix=base, version="0.8.75",
                         browser=str(base / "chrome") if browser else None)


class EnvTests(unittest.TestCase):
    def test_env_has_quiet_flags_private_home_and_browser(self):
        base = Path("/tmp/hf")
        env = engine_cli.engine_env(make_engine(base), {"PATH": "/usr/bin", "HOME": "/Users/me"})
        for key in ("HYPERFRAMES_NO_UPDATE_CHECK", "HYPERFRAMES_NO_AUTO_INSTALL",
                    "HYPERFRAMES_NO_TELEMETRY", "HYPERFRAMES_SKIP_SKILLS"):
            self.assertEqual(env[key], "1")
        self.assertEqual(env["HOME"], str(base / "home"))
        self.assertEqual(env["HYPERFRAMES_BROWSER_PATH"], str(base / "chrome"))
        self.assertEqual(env["HYPERFRAMES_EXTRACT_CACHE_DIR"], str(base / "cache" / "frames"))
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertNotIn("USERPROFILE", env)

    def test_windows_also_moves_userprofile(self):
        with mock.patch.object(engine_cli, "IS_WINDOWS", True):
            env = engine_cli.engine_env(make_engine(Path("/tmp/hf"), browser=False), {})
        self.assertEqual(env["USERPROFILE"], env["HOME"])
        self.assertNotIn("HYPERFRAMES_BROWSER_PATH", env)


class RunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.engine = make_engine(self.base)

    def test_argv_is_node_plus_script_without_shell(self):
        run = FakeRun(stdout=b'{"ok": true}')
        payload = engine_cli.run_engine_json(self.engine, ["timeline", "--json"],
                                             cwd=self.base, timeout=5, runner=run)
        argv, kwargs = run.calls[0]
        self.assertEqual(argv, [self.engine.node, str(self.engine.script), "timeline", "--json"])
        self.assertNotIn("shell", kwargs)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["cwd"], str(self.base))
        self.assertEqual(payload, {"ok": True})
        self.assertTrue((self.base / "home").is_dir())

    def test_refusal_json_on_stderr_becomes_message(self):
        run = FakeRun(code=2, stderr=b'{"ok": false, "reason": "#s1 would overlap #s2 at 1-6",'
                                     b' "fix": "pass --overwrite or move the named neighbour"}')
        with self.assertRaises(MontageError) as caught:
            engine_cli.run_engine_json(self.engine, ["timeline", "trim"], cwd=self.base,
                                       timeout=5, runner=run)
        self.assertIn("would overlap", str(caught.exception))
        self.assertIn("--overwrite", str(caught.exception))

    def test_timeout_is_a_clear_message(self):
        with self.assertRaises(MontageError) as caught:
            engine_cli.run_engine_json(self.engine, ["lint", "."], cwd=self.base, timeout=5,
                                       runner=FakeRun(timeout=True))
        self.assertIn("не ответил", str(caught.exception))

    def test_lint_exit_one_is_allowed_when_asked(self):
        run = FakeRun(code=1, stdout=b'{"ok": false, "findings": []}')
        payload = engine_cli.run_engine_json(self.engine, ["lint", ".", "--json"], cwd=self.base,
                                             timeout=5, ok_codes=(0, 1), runner=run)
        self.assertIs(payload["ok"], False)

    def test_non_json_output_is_refused(self):
        with self.assertRaises(MontageError):
            engine_cli.run_engine_json(self.engine, ["timeline", "--json"], cwd=self.base,
                                       timeout=5, runner=FakeRun(stdout=b"hello"))

    def test_runner_object_delegates_to_module_functions(self):
        with mock.patch.object(engine_cli, "run_engine_json", return_value={"x": 1}) as fake:
            self.assertEqual(engine_cli.EngineRunner().json(self.engine, ["a"], cwd=self.base,
                                                            timeout=1), {"x": 1})
        fake.assert_called_once()


class PopenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.engine = make_engine(self.base)
        self.calls = []

    def popen(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return mock.Mock(pid=4242)

    def test_posix_detaches_with_new_session(self):
        log = self.base / "logs" / "desk.log"
        with mock.patch.object(engine_cli, "IS_WINDOWS", False):
            engine_cli.popen_engine(self.engine, ["preview", "."], cwd=self.base, log_path=log,
                                    popen=self.popen)
        argv, kwargs = self.calls[0]
        self.assertEqual(argv[:2], [self.engine.node, str(self.engine.script)])
        self.assertIs(kwargs["start_new_session"], True)
        self.assertNotIn("creationflags", kwargs)
        self.assertTrue(log.exists())

    def test_windows_hides_console_and_starts_a_new_group(self):
        with mock.patch.object(engine_cli, "IS_WINDOWS", True):
            engine_cli.popen_engine(self.engine, ["preview", "."], cwd=self.base,
                                    log_path=self.base / "desk.log", popen=self.popen)
        _, kwargs = self.calls[0]
        self.assertTrue(kwargs["creationflags"] & engine_cli.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(kwargs["creationflags"] & engine_cli.CREATE_NO_WINDOW)
        self.assertNotIn("start_new_session", kwargs)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_engine_cli.py' -v`
Expected: FAIL — `ImportError: cannot import name 'engine_cli'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/engine_cli.py`:

```python
"""Запуск CLI HyperFrames: без оболочки, `node <…>/bin/hyperframes.mjs <команда>`.

Окружение каждого запуска: тихие флаги HyperFrames, свой HOME движка (кэши,
браузер, настройки не попадают в домашнюю папку человека), путь к скачанному
браузеру и кэш кадров. Отказ CLI (код 2, JSON в stderr) превращается в
понятный `MontageError`.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ..platform_compat import IS_WINDOWS
from . import MontageError
from .engine import Engine

QUIET_FLAGS = {
    "HYPERFRAMES_NO_UPDATE_CHECK": "1",
    "HYPERFRAMES_NO_AUTO_INSTALL": "1",
    "HYPERFRAMES_NO_TELEMETRY": "1",
    "HYPERFRAMES_SKIP_SKILLS": "1",
    "NO_COLOR": "1",
    "FORCE_COLOR": "0",
}
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class EngineResult:
    code: int
    stdout: str
    stderr: str
    timed_out: bool = False


def engine_home(engine: Engine) -> Path:
    return Path(engine.prefix) / "home"


def frames_cache(engine: Engine) -> Path:
    return Path(engine.prefix) / "cache" / "frames"


def engine_env(engine: Engine, base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update(QUIET_FLAGS)
    env["HOME"] = str(engine_home(engine))
    if IS_WINDOWS:
        env["USERPROFILE"] = env["HOME"]
    env["HYPERFRAMES_EXTRACT_CACHE_DIR"] = str(frames_cache(engine))
    if engine.browser:
        env["HYPERFRAMES_BROWSER_PATH"] = engine.browser
    return env


def argv_for(engine: Engine, args: Sequence[str]) -> list[str]:
    return [engine.node, str(engine.script), *map(str, args)]


def _decode(raw) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


def run_engine(engine: Engine, args: Sequence[str], *, cwd: Path, timeout: float,
               runner=subprocess.run) -> EngineResult:
    engine_home(engine).mkdir(parents=True, exist_ok=True)
    try:
        proc = runner(argv_for(engine, args), cwd=str(cwd), env=engine_env(engine),
                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return EngineResult(124, "", f"не завершился за {timeout:g} с", True)
    except OSError as error:
        return EngineResult(127, "", str(error))
    return EngineResult(proc.returncode, _decode(proc.stdout), _decode(proc.stderr))


def _json_payload(text: str):
    text = (text or "").strip()
    start = text.find("{")
    if start < 0:
        return None
    try:
        return json.loads(text[start:])
    except ValueError:
        return None


def run_engine_json(engine: Engine, args: Sequence[str], *, cwd: Path, timeout: float,
                    ok_codes=(0,), runner=subprocess.run) -> dict:
    result = run_engine(engine, args, cwd=cwd, timeout=timeout, runner=runner)
    command = " ".join(map(str, list(args)[:2]))
    if result.timed_out:
        raise MontageError(f"HyperFrames «{command}» не ответил за {timeout:g} с")
    if result.code not in ok_codes:
        refusal = _json_payload(result.stderr) or _json_payload(result.stdout)
        if isinstance(refusal, dict) and refusal.get("reason"):
            fix = f" ({refusal['fix']})" if refusal.get("fix") else ""
            raise MontageError(f"HyperFrames отказал: {refusal['reason']}{fix}")
        tail = (result.stderr or result.stdout).strip()[-600:]
        raise MontageError(f"HyperFrames «{command}» завершился с кодом {result.code}: {tail}")
    payload = _json_payload(result.stdout)
    if not isinstance(payload, dict):
        raise MontageError(f"HyperFrames «{command}» вернул не JSON")
    return payload


def popen_engine(engine: Engine, args: Sequence[str], *, cwd: Path, log_path: Path,
                 popen=subprocess.Popen):
    """Отдельный процесс (монтажный стол): переживает вызвавший его CLI.

    POSIX — своя сессия (группа для остановки с детьми); Windows — своя группа
    процессов и скрытая консоль, чтобы Chrome и ffmpeg не открывали окна."""

    engine_home(engine).mkdir(parents=True, exist_ok=True)
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    extra = ({"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW} if IS_WINDOWS
             else {"start_new_session": True})
    with open(log_path, "wb") as log:
        return popen(argv_for(engine, args), cwd=str(cwd), env=engine_env(engine),
                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, **extra)


class EngineRunner:
    """Настоящий запуск. Тесты подставляют объект с теми же двумя методами."""

    def json(self, engine: Engine, args, *, cwd: Path, timeout: float, ok_codes=(0,)) -> dict:
        return run_engine_json(engine, args, cwd=cwd, timeout=timeout, ok_codes=ok_codes)

    def run(self, engine: Engine, args, *, cwd: Path, timeout: float) -> EngineResult:
        return run_engine(engine, args, cwd=cwd, timeout=timeout)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_engine_cli.py' -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/engine_cli.py skills/aimaster/scripts/test_montage_engine_cli.py
git commit -m "feat(montage): shell-free HyperFrames runner with private HOME"
```

---

### Task 3: ffprobe, размер кадра и заготовки тестов

**Files:**
- Create: `skills/aimaster/studio/montage/probe.py`
- Create: `skills/aimaster/studio/montage/canvas.py`
- Create: `skills/aimaster/scripts/montage_testkit.py`
- Test: `skills/aimaster/scripts/test_montage_probe.py`

**Interfaces:**
- Consumes: `platform_compat.find_program`, `MontageError`.
- Produces:
  - `@dataclass(frozen=True) probe.MediaInfo(duration: float, width: int | None, height: int | None, has_video: bool, has_audio: bool)`.
  - `probe.find_ffprobe() -> str | None`; `probe.parse_probe(payload: dict) -> MediaInfo`; `probe.probe_media(path: Path, *, ffprobe: str | None = None, runner=subprocess.run) -> MediaInfo`.
  - `@dataclass(frozen=True) canvas.Canvas(width: int, height: int)` с `to_dict() -> {"width", "height"}`; `canvas.DEFAULT_WIDTH = 1080`, `DEFAULT_HEIGHT = 1920`; `canvas.canvas_for(first_video: MediaInfo | None) -> Canvas`.
  - `montage_testkit.ffmpeg_or_skip() -> str`; `montage_testkit.make_clip(path, seconds=2.0, *, size=(108, 192), color="red", freq=440, audio=True) -> Path`; `montage_testkit.make_tone(path, seconds=3.0, *, freq=220) -> Path`.

- [ ] **Step 1: Write the failing test**

Сначала заготовки `skills/aimaster/scripts/montage_testkit.py` (не тест, их используют тесты):

```python
"""Заготовки тестов монтажа: клипы из ffmpeg, состояния проектов, подмена CLI
HyperFrames. Имя не test_* — unittest сам этот файл не запускает."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.platform_compat import find_program  # noqa: E402


def ffmpeg_or_skip() -> str:
    ffmpeg = find_program("ffmpeg")
    if ffmpeg is None or find_program("ffprobe") is None:
        raise unittest.SkipTest("нужны ffmpeg и ffprobe")
    return ffmpeg


def _ffmpeg(args) -> None:
    subprocess.run([ffmpeg_or_skip(), "-v", "error", "-y", *map(str, args)], check=True,
                   stdin=subprocess.DEVNULL, timeout=120)


def make_clip(path: Path, seconds: float = 2.0, *, size=(108, 192), color="red", freq=440,
              audio=True) -> Path:
    """Клип H.264 с ключевым кадром раз в секунду (иначе HyperFrames ругается
    на редкие ключевые кадры) и тоном, если нужен звук."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    args = ["-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:r=30:d={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "30"]
    args += ["-c:a", "aac", "-shortest"] if audio else ["-an"]
    _ffmpeg(args + ["-movflags", "+faststart", path])
    return path


def make_tone(path: Path, seconds: float = 3.0, *, freq=220) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg(["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
             "-c:a", "pcm_s16le", path])
    return path
```

Затем тест `skills/aimaster/scripts/test_montage_probe.py`:

```python
#!/usr/bin/env python3
"""ffprobe → MediaInfo и размер кадра монтажа."""

from __future__ import annotations

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

import montage_testkit  # noqa: E402
from studio.montage import MontageError, probe  # noqa: E402
from studio.montage.canvas import Canvas, canvas_for  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_video_with_sound(self):
        info = probe.parse_probe({"streams": [
            {"codec_type": "video", "width": 1080, "height": 1920}, {"codec_type": "audio"}],
            "format": {"duration": "15.000000"}})
        self.assertEqual(info, MediaInfo(15.0, 1080, 1920, True, True))

    def test_mp3_cover_is_not_a_picture(self):
        info = probe.parse_probe({"streams": [
            {"codec_type": "video", "width": 500, "height": 500, "disposition": {"attached_pic": 1}},
            {"codec_type": "audio"}], "format": {"duration": "3.5"}})
        self.assertEqual(info, MediaInfo(3.5, None, None, False, True))

    def test_bad_duration_is_zero(self):
        self.assertEqual(probe.parse_probe({"format": {"duration": "N/A"}}).duration, 0.0)


class ProbeTests(unittest.TestCase):
    def test_missing_ffprobe(self):
        with mock.patch.object(probe, "find_ffprobe", return_value=None):
            with self.assertRaises(MontageError) as caught:
                probe.probe_media(Path("x.mp4"))
        self.assertIn("ffprobe", str(caught.exception))

    def test_failure_names_the_file(self):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, b"", b"Invalid data found")
        with self.assertRaises(MontageError) as caught:
            probe.probe_media(Path("клип 1.mp4"), ffprobe="/usr/bin/ffprobe", runner=runner)
        self.assertIn("клип 1.mp4", str(caught.exception))
        self.assertIn("Invalid data", str(caught.exception))

    def test_real_clip_with_cyrillic_path(self):
        montage_testkit.ffmpeg_or_skip()
        with tempfile.TemporaryDirectory() as temp:
            clip = montage_testkit.make_clip(Path(temp) / "папка с пробелом" / "клип 1.mp4", 1.0)
            info = probe.probe_media(clip)
        self.assertAlmostEqual(info.duration, 1.0, delta=0.1)
        self.assertEqual((info.width, info.height, info.has_video, info.has_audio),
                         (108, 192, True, True))


class CanvasTests(unittest.TestCase):
    def test_default_when_unknown(self):
        self.assertEqual(canvas_for(None), Canvas(1080, 1920))
        self.assertEqual(canvas_for(MediaInfo(3.0, None, None, False, True)), Canvas(1080, 1920))

    def test_takes_first_video_and_rounds_up_to_even(self):
        self.assertEqual(canvas_for(MediaInfo(3.0, 1280, 720, True, False)), Canvas(1280, 720))
        self.assertEqual(canvas_for(MediaInfo(3.0, 1081, 1919, True, False)), Canvas(1082, 1920))
        self.assertEqual(Canvas(540, 960).to_dict(), {"width": 540, "height": 960})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_probe.py' -v`
Expected: FAIL — `ImportError: cannot import name 'probe'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/probe.py`:

```python
"""ffprobe: длительность, размер кадра, есть ли картинка и звук."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..platform_compat import find_program
from . import MontageError

PROBE_TIMEOUT = 60


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int | None
    height: int | None
    has_video: bool
    has_audio: bool


def find_ffprobe() -> str | None:
    return find_program("ffprobe")


def parse_probe(payload: dict) -> MediaInfo:
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    width = int(video["width"]) if video and video.get("width") else None
    height = int(video["height"]) if video and video.get("height") else None
    return MediaInfo(duration=round(duration, 3), width=width, height=height,
                     has_video=video is not None,
                     has_audio=any(s.get("codec_type") == "audio" for s in streams))


def probe_media(path: Path, *, ffprobe: str | None = None, runner=subprocess.run) -> MediaInfo:
    ffprobe = ffprobe or find_ffprobe()
    if ffprobe is None:
        raise MontageError("Не найден ffprobe (ставится вместе с ffmpeg): "
                           "python3 skills/aimaster/scripts/install.py --install-deps")
    argv = [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
            str(path)]
    try:
        proc = runner(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                      stderr=subprocess.PIPE, timeout=PROBE_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        raise MontageError(f"ffprobe не запустился: {error}") from error
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", errors="replace").strip()[-300:]
        raise MontageError(f"ffprobe не прочитал {Path(path).name}: {tail}")
    try:
        payload = json.loads((proc.stdout or b"").decode("utf-8", errors="replace"))
    except ValueError as error:
        raise MontageError(f"ffprobe вернул не JSON для {Path(path).name}") from error
    return parse_probe(payload)
```

`skills/aimaster/studio/montage/canvas.py`:

```python
"""Размер кадра монтажа: по первому видеоклипу, иначе 1080×1920.

`AssetIndex` размер кадра MP4 не знает (`assets._mp4` отдаёт None), поэтому
его приносит ffprobe (`probe.MediaInfo`)."""

from __future__ import annotations

from dataclasses import dataclass

from .probe import MediaInfo

DEFAULT_WIDTH, DEFAULT_HEIGHT = 1080, 1920


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int

    def to_dict(self) -> dict:
        return {"width": self.width, "height": self.height}


def _even(value: int) -> int:
    return value if value % 2 == 0 else value + 1


def canvas_for(first_video: MediaInfo | None) -> Canvas:
    """H.264 требует чётных сторон: нечётный размер исходника округляем вверх."""

    if first_video is None or not first_video.width or not first_video.height:
        return Canvas(DEFAULT_WIDTH, DEFAULT_HEIGHT)
    return Canvas(_even(first_video.width), _even(first_video.height))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_probe.py' -v`
Expected: PASS (8 tests; `test_real_clip_with_cyrillic_path` — skipped, если нет ffmpeg).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/probe.py skills/aimaster/studio/montage/canvas.py skills/aimaster/scripts/montage_testkit.py skills/aimaster/scripts/test_montage_probe.py
git commit -m "feat(montage): ffprobe media info and canvas size"
```

---
### Task 4: Установщик монтажа — Node.js, HyperFrames, браузер; раздел `montage` в отчёте

**Files:**
- Create: `skills/aimaster/scripts/install_montage_node.py` (Node.js 22+ и npm-cli.js)
- Create: `skills/aimaster/scripts/install_montage_engine.py` (HyperFrames и браузер)
- Create: `skills/aimaster/scripts/install_montage.py` (раздел `montage` отчёта, отдельный запуск)
- Modify: `skills/aimaster/scripts/install.py` (докстринг п. 3, `DEPS` без `node`, `_run` с `env`, помощь `--install-deps`, новая `_montage_report`, `main`, `render_text`)
- Modify: `skills/aimaster/scripts/test_install.py` (`_TempInstall.setUp`, два теста `DepsTests`, новый тест раздела `montage`)
- Modify: `INSTALL_WITH_AGENT.md` (раздел «Разрешённые границы»), `README.md` («Вариант 2»)
- Test: `skills/aimaster/scripts/test_install_montage.py`

**Interfaces:**
- Consumes: `install._install_argv(kind, group, command) -> (argv | None, why)`, `install._run_installer(kind, argv, command) -> (ok, status, why)`, `install._run(argv, cwd=None, timeout=None, env=None) -> (code, out, err)`, `install.TIMEOUT_CODE`, `install._inside(path, folder) -> bool`, `install.platform_kind()`, `install.ensure_utf8_output()`; `engine.load_pin/find_node/node_major/tools_prefix/installed_version/entry_script/read_record/write_record/Engine`; `engine_cli.run_engine(engine, args, *, cwd, timeout, runner=subprocess.run) -> EngineResult`.
- Produces:
  - `install_montage_node.NODE_INSTALL: dict[str, str]`, `install_montage_node.READY = ("found", "installed")`, `install_montage_node.item(status, message="", **extra) -> dict`.
  - `install_montage_node.node_check(kind: str, install_missing: bool) -> dict` — `{"status": found|installed|missing|failed|timeout, "message", "path"?, "version"?, "install_cmd"?}`.
  - `install_montage_node.npm_cli_js(node: str) -> Path | None`.
  - `install_montage_engine.engine_install(node: str, prefix: Path, pin: dict, *, update: bool, run=None) -> dict`; `install_montage_engine.check_package(prefix, pin) -> dict`.
  - `install_montage_engine.browser_install(node: str, prefix: Path, pin: dict, *, runner=None) -> dict`; `install_montage_engine.check_browser(prefix, pin) -> dict`.
  - `install_montage.montage_report(kind: str, *, install_missing: bool, update: bool, install_node: bool, home: Path | None = None) -> dict` — `{"prefix", "node", "hyperframes", "browser", "ok"}` (задача 5 добавит `skills`).
  - `install_montage.render_montage_lines(report: dict) -> list[str]`; `install_montage.main(argv=None) -> int` (флаги `--json`, `--update`, `--install-node`, `--check`).
  - `install._montage_report(kind, install_deps, update, home) -> dict`; ключ `report["montage"]` в `install.py --json`.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_install_montage.py`:

```python
#!/usr/bin/env python3
"""Установка монтажа: Node 22+, HyperFrames через node + npm-cli.js, браузер в HOME движка."""

from __future__ import annotations

import json
import os
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

import install  # noqa: E402
import install_montage  # noqa: E402
import install_montage_engine  # noqa: E402
import install_montage_node  # noqa: E402
from studio.montage import engine  # noqa: E402

PIN = engine.load_pin()


def temp_base(test) -> Path:
    temp = tempfile.TemporaryDirectory()
    test.addCleanup(temp.cleanup)
    return Path(temp.name).resolve()


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


class NodeCheckTests(unittest.TestCase):
    def patch_node(self, paths, major):
        sequence = iter(paths)
        return (mock.patch.object(engine, "find_node", side_effect=lambda **kw: next(sequence)),
                mock.patch.object(engine, "node_major", return_value=major))

    def test_found_when_new_enough(self):
        find, major = self.patch_node(["/usr/local/bin/node"], 22)
        with find, major:
            item = install_montage_node.node_check("macos", install_missing=False)
        self.assertEqual((item["status"], item["version"]), ("found", 22))

    def test_old_node_is_missing_with_command(self):
        find, major = self.patch_node(["/usr/local/bin/node"], 20)
        with find, major, mock.patch.object(install, "_run") as run:
            item = install_montage_node.node_check("macos", install_missing=False)
        run.assert_not_called()
        self.assertEqual((item["status"], item["install_cmd"]), ("missing", "brew install node"))
        self.assertIn("20", item["message"])

    def test_windows_installs_lts_with_winget_flags(self):
        find, major = self.patch_node([None, "C:/Program Files/nodejs/node.exe"], 24)
        with find, major, mock.patch.object(install, "_find_program", return_value="C:/winget.exe"), \
                mock.patch.object(install, "_run", return_value=(0, "", "")) as run:
            item = install_montage_node.node_check("windows", install_missing=True)
        self.assertEqual(item["status"], "installed")
        argv = run.call_args.args[0]
        self.assertEqual(argv[:5], ["C:/winget.exe", "install", "-e", "--id", "OpenJS.NodeJS.LTS"])
        self.assertIn("--disable-interactivity", argv)

    def test_linux_prints_instruction_and_never_runs(self):
        find, major = self.patch_node([None], None)
        with find, major, mock.patch.object(install, "_run") as run:
            item = install_montage_node.node_check("linux", install_missing=True)
        run.assert_not_called()
        self.assertEqual(item["status"], "missing")
        self.assertIn("nodejs.org", item["message"])


class NpmCliTests(unittest.TestCase):
    def test_windows_layout(self):
        base = temp_base(self)
        node = touch(base / "nodejs" / "node.exe")
        npm = touch(base / "nodejs" / "node_modules" / "npm" / "bin" / "npm-cli.js")
        self.assertEqual(install_montage_node.npm_cli_js(str(node)), npm)

    def test_tarball_nvm_and_setup_node_layout(self):
        base = temp_base(self)
        node = touch(base / "node-v22" / "bin" / "node")
        npm = touch(base / "node-v22" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js")
        self.assertEqual(install_montage_node.npm_cli_js(str(node)), npm)

    def test_homebrew_layout(self):
        base = temp_base(self)
        cellar = touch(base / "Cellar" / "node" / "26.7.0" / "bin" / "node")
        npm = touch(base / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js")
        (base / "bin").mkdir()
        try:
            os.symlink(cellar, base / "bin" / "node")
        except (OSError, NotImplementedError):
            self.skipTest("символические ссылки недоступны")
        self.assertEqual(install_montage_node.npm_cli_js(str(base / "bin" / "node")), npm)

    def test_missing_npm(self):
        base = temp_base(self)
        self.assertIsNone(install_montage_node.npm_cli_js(str(touch(base / "bin" / "node"))))


class EngineInstallTests(unittest.TestCase):
    def setUp(self):
        self.base = temp_base(self)
        self.prefix = self.base / "tools" / "hyperframes"
        self.node = touch(self.base / "node" / "bin" / "node")
        self.npm = touch(self.base / "node" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js")
        self.calls = []

    def fake_npm(self, version="0.8.75", code=0):
        def run(argv, cwd=None, timeout=None, env=None):
            self.calls.append({"argv": argv, "cwd": cwd, "timeout": timeout, "env": env})
            if code != 0:
                return code, "", "npm ERR! network"
            package = self.prefix / "node_modules" / "hyperframes"
            touch(package / "bin" / "hyperframes.mjs")
            (package / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
            return 0, "added 69 packages", ""
        return run

    def test_runs_npm_cli_js_with_node_and_pinned_package(self):
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=False,
                                              run=self.fake_npm())
        self.assertEqual(item["status"], "installed")
        call = self.calls[0]
        argv = call["argv"]
        self.assertEqual(argv[:3], [str(self.node), str(self.npm), "install"])
        self.assertEqual(argv[argv.index("--prefix") + 1], str(self.prefix))
        self.assertIn("hyperframes@0.8.75", argv)
        self.assertFalse(any("npx" in str(part) for part in argv))
        self.assertEqual(call["timeout"], PIN["timeouts"]["npm_install"])
        self.assertTrue(call["env"]["PATH"].startswith(str(self.node.parent)))

    def test_pinned_version_is_found_without_npm(self):
        self.fake_npm()([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=False,
                                              run=self.fake_npm())
        self.assertEqual(item["status"], "found")
        self.assertEqual(self.calls, [])

    def test_other_version_waits_for_update(self):
        self.fake_npm("0.8.74")([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=False,
                                              run=self.fake_npm())
        self.assertEqual(item["status"], "found")
        self.assertIn("--update", item["message"])
        self.assertEqual(self.calls, [])
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=True,
                                              run=self.fake_npm())
        self.assertEqual(item["status"], "installed")

    def test_npm_failure_and_timeout(self):
        failed = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=False,
                                                run=self.fake_npm(code=1))
        self.assertEqual(failed["status"], "failed")
        self.assertIn("npm ERR", failed["message"])
        slow = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=False,
                                              run=lambda *a, **k: (install.TIMEOUT_CODE, "", ""))
        self.assertEqual(slow["status"], "timeout")


class BrowserInstallTests(unittest.TestCase):
    def setUp(self):
        self.base = temp_base(self)
        self.prefix = self.base / "tools" / "hyperframes"
        self.browser = self.prefix / "home" / ".cache" / "hyperframes" / "chrome" / "chrome-headless-shell"
        self.calls = []

    def runner(self, path_line):
        def run(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[2:4] == ["browser", "path"]:
                return subprocess.CompletedProcess(argv, 0, (path_line + "\n").encode(), b"")
            touch(self.browser)
            return subprocess.CompletedProcess(argv, 0, b"Ready to render.", b"")
        return run

    def test_downloads_into_engine_home_and_records_the_path(self):
        item = install_montage_engine.browser_install("/usr/bin/node", self.prefix, PIN,
                                               runner=self.runner(str(self.browser)))
        self.assertEqual(item["status"], "installed")
        self.assertEqual(engine.read_record(self.prefix)["browser"], str(self.browser))
        argv, kwargs = self.calls[0]
        self.assertEqual(argv[2:4], ["browser", "ensure"])
        self.assertEqual(kwargs["env"]["HOME"], str(self.prefix / "home"))

    def test_system_chrome_is_not_accepted(self):
        outside = touch(self.base / "Google Chrome")
        item = install_montage_engine.browser_install("/usr/bin/node", self.prefix, PIN,
                                               runner=self.runner(str(outside)))
        self.assertEqual(item["status"], "failed")
        self.assertNotIn("browser", engine.read_record(self.prefix))

    def test_recorded_browser_is_found_without_download(self):
        touch(self.browser)
        engine.write_record(self.prefix, {"browser": str(self.browser), "version": PIN["version"]})
        item = install_montage_engine.browser_install("/usr/bin/node", self.prefix, PIN,
                                               runner=self.runner("x"))
        self.assertEqual(item["status"], "found")
        self.assertEqual(self.calls, [])


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.base = temp_base(self)
        patcher = mock.patch.dict(os.environ, {engine.PREFIX_ENV: str(self.base / "hf")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_check_only_installs_nothing(self):
        with mock.patch.object(engine, "find_node", return_value="/usr/bin/node"), \
                mock.patch.object(engine, "node_major", return_value=22), \
                mock.patch.object(install, "_run", side_effect=AssertionError("ничего не ставим")), \
                mock.patch.object(install_montage_engine, "run_engine",
                                  side_effect=AssertionError("ничего не качаем")):
            report = install_montage.montage_report("macos", install_missing=False, update=False,
                                                    install_node=False, home=self.base)
        self.assertEqual([report[key]["status"] for key in ("node", "hyperframes", "browser")],
                         ["found", "missing", "missing"])
        self.assertIs(report["ok"], False)
        self.assertEqual(report["prefix"], str(self.base / "hf"))

    def test_no_node_skips_the_engine(self):
        with mock.patch.object(engine, "find_node", return_value=None):
            report = install_montage.montage_report("linux", install_missing=True, update=False,
                                                    install_node=True, home=self.base)
        self.assertEqual(report["hyperframes"]["status"], "missing")
        self.assertIn("Node.js", report["hyperframes"]["message"])

    def test_text_lines(self):
        lines = install_montage.render_montage_lines(
            {"ok": False, "node": {"status": "missing", "message": "Node.js не найден"}})
        self.assertEqual(lines[0], "Монтаж (HyperFrames): не готов")
        self.assertIn("  Node.js 22+ — нет", lines)
        self.assertIn("      Node.js не найден", lines)


if __name__ == "__main__":
    unittest.main()
```

В `skills/aimaster/scripts/test_install.py`:

1) в `_TempInstall.setUp` сразу после строки `self.addCleanup(patcher.stop)` (патч `check_deps`) вставить:

```python
        # раздел монтажа проверяется в test_install_montage.py; здесь — заглушка
        montage = mock.patch.object(install, "_montage_report",
                                    return_value={"ok": True, "node": {"status": "found", "message": ""}})
        self.montage = montage.start()
        self.addCleanup(montage.stop)
```

2) в классе `InstallTests` добавить тест:

```python
    def test_montage_section_is_reported_and_rendered(self):
        code, report = self.run_install("--install-deps")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["montage"]["ok"], True)
        kind, install_deps, update, home = self.montage.call_args.args
        self.assertEqual((kind, install_deps, update, home), (report["platform"], True, False, self.home))
        text = install.render_text({**report, "montage": {
            "ok": False, "node": {"status": "missing", "message": "Node.js не найден"}}})
        self.assertIn("Монтаж (HyperFrames): не готов", text)
        self.assertIn("Node.js не найден", text)
```

3) в `DepsTests` заменить два теста целиком:

```python
    def test_missing_deps_are_listed_not_installed(self):
        with mock.patch.object(install, "_which", return_value=None), \
                mock.patch.object(install, "_run") as run:
            report = install.check_deps("windows", install=False)
        run.assert_not_called()
        names = [d["name"] for d in report]
        # Node.js теперь зависимость монтажа: его проверяет install_montage.py
        self.assertEqual(names, ["ffmpeg", "ffprobe", "cloudflared", "git"])
        self.assertTrue(all(not d["found"] and d["installed"] is None for d in report))
        self.assertEqual(report[0]["install_cmd"], "winget install -e --id Gyan.FFmpeg")

    def test_install_deps_runs_winget_once_per_package(self):
        with mock.patch.object(install, "_which", return_value=None), \
                mock.patch.object(install, "_find_program", return_value="C:/winget.exe"), \
                mock.patch.object(install, "_run", return_value=(0, "", "")) as run:
            report = install.check_deps("windows", install=True)
        ids = [call.args[0][4] for call in run.call_args_list]
        self.assertEqual(ids, ["Gyan.FFmpeg", "Cloudflare.cloudflared", "Git.Git"])
        for call in run.call_args_list:
            argv = call.args[0]
            self.assertEqual(argv[0], "C:/winget.exe")
            self.assertIn("--disable-interactivity", argv)
            self.assertEqual(call.kwargs["timeout"], install.INSTALL_TIMEOUT)
        self.assertNotIn("node", [d["name"] for d in report])
        self.assertIn("новый терминал", report[0]["message"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_install*.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'install_montage'`; в `test_install.py` — `AttributeError: ... does not have the attribute '_montage_report'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/scripts/install_montage_node.py`:

```python
#!/usr/bin/env python3
"""Node.js 22+ для монтажа: найти, при --install-deps поставить (winget/brew) и
найти npm-cli.js рядом с этим Node — npm потом запускается как `node <npm-cli.js>`,
без npm.cmd и оболочки. Часть установщика монтажа (install_montage.py)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS), str(_SCRIPTS.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install  # noqa: E402
from studio.montage import engine  # noqa: E402

NODE_INSTALL = {"windows": "winget install -e --id OpenJS.NodeJS.LTS",
                "macos": "brew install node", "linux": "sudo apt install nodejs"}
LINUX_NODE_HINT = ("в apt часто Node.js старее 22 — тогда поставьте 22+ по инструкции "
                   "https://nodejs.org/en/download")
READY = ("found", "installed")


def item(status: str, message: str = "", **extra) -> dict:
    return {"status": status, "message": message, **extra}


def node_check(kind: str, install_missing: bool) -> dict:
    wanted = engine.load_pin()["node_min_major"]
    node = engine.find_node()
    major = engine.node_major(node) if node else None
    if node and major and major >= wanted:
        return item("found", path=node, version=major)
    command = NODE_INSTALL[kind]
    why = "не найден" if not node else f"версии {major}, нужна {wanted}+"
    if not install_missing:
        return item("missing", f"Node.js {why}; поставить: {command}", path=node,
                     version=major, install_cmd=command)
    argv, reason = install._install_argv(kind, "node", command)
    if argv is None:
        hint = f"{reason}. {LINUX_NODE_HINT}" if kind == "linux" else reason
        return item("missing", hint, path=node, version=major, install_cmd=command)
    ok, status, reason = install._run_installer(kind, argv, command)
    if not ok:
        return item(status, reason, install_cmd=command)
    node = engine.find_node()
    major = engine.node_major(node) if node else None
    if node and major and major >= wanted:
        return item("installed", path=node, version=major)
    return item("failed", f"установщик отработал, но Node.js {wanted}+ не виден: откройте новый "
                 f"терминал и повторите или поставьте вручную: {command}", install_cmd=command)


def npm_cli_js(node: str) -> Path | None:
    """npm-cli.js рядом с этим Node: Windows, tar.gz/nvm/setup-node, Homebrew."""

    here = Path(node).parent
    real = Path(os.path.realpath(node)).parent
    tail = Path("node_modules") / "npm" / "bin" / "npm-cli.js"
    candidates = [here / tail, real.parent / "lib" / tail, here.parent / "lib" / tail]
    for npm in (here / "npm", real / "npm"):
        resolved = Path(os.path.realpath(npm))
        if resolved.suffix == ".js":
            candidates.append(resolved)
    return next((path for path in candidates if path.is_file()), None)
```

`skills/aimaster/scripts/install_montage_engine.py`:

```python
#!/usr/bin/env python3
"""HyperFrames закреплённой версии и браузер для сборки видео — часть установщика
монтажа (install_montage.py). npm запускается как `node <npm-cli.js> install
--prefix <папка движка>`, браузер качает сам HyperFrames (`browser ensure`) в HOME
движка; путь к нему пишется в aimaster-engine.json — иначе `browser path` молча
отдал бы системный Chrome."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS), str(_SCRIPTS.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install  # noqa: E402
from install_montage_node import item, npm_cli_js  # noqa: E402
from studio.montage import engine  # noqa: E402
from studio.montage.engine_cli import run_engine  # noqa: E402


def engine_install(node: str, prefix: Path, pin: dict, *, update: bool, run=None) -> dict:
    run = run or install._run
    have = engine.installed_version(prefix)
    if have == pin["version"]:
        return item("found", version=have, path=str(prefix))
    if have and not update:
        return item("found", f"стоит {have}, нужна {pin['version']}: запустите install.py --update",
                     version=have, path=str(prefix))
    npm = npm_cli_js(node)
    if npm is None:
        return item("failed", "рядом с Node.js нет npm — переустановите Node.js")
    Path(prefix).mkdir(parents=True, exist_ok=True)
    argv = [node, str(npm), "install", "--prefix", str(prefix),
            f"{pin['package']}@{pin['version']}", "--no-audit", "--no-fund", "--omit=dev",
            "--save-exact"]
    env = dict(os.environ)
    env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
    timeout = pin["timeouts"]["npm_install"]
    code, out, err = run(argv, cwd=str(prefix), timeout=timeout, env=env)
    if code == install.TIMEOUT_CODE:
        return item("timeout", f"npm не уложился в {timeout // 60} мин; повторите позже")
    have = engine.installed_version(prefix)
    if code != 0 or have != pin["version"]:
        return item("failed", (err or out).strip()[-400:] or f"npm завершился с кодом {code}")
    return item("installed", version=have, path=str(prefix))


def browser_install(node: str, prefix: Path, pin: dict, *, runner=None) -> dict:
    record = engine.read_record(prefix)
    if record.get("version") == pin["version"] and record.get("browser") \
            and Path(record["browser"]).is_file():
        return item("found", path=record["browser"])
    eng = engine.Engine(node=node, script=engine.entry_script(prefix), prefix=Path(prefix),
                        version=pin["version"], browser=None)
    kwargs = {} if runner is None else {"runner": runner}
    print("Качаю компонент для сборки видео (~100 МБ)…", file=sys.stderr, flush=True)
    ensured = run_engine(eng, ["browser", "ensure"], cwd=prefix,
                         timeout=pin["timeouts"]["browser"], **kwargs)
    if ensured.timed_out:
        return item("timeout", "браузер для сборки не скачался за отведённое время; повторите позже")
    located = run_engine(eng, ["browser", "path"], cwd=prefix, timeout=pin["timeouts"]["cli"],
                         **kwargs)
    lines = located.stdout.strip().splitlines()
    path = lines[-1].strip() if lines else ""
    inside = bool(path) and install._inside(path, str(Path(prefix) / "home"))
    if ensured.code != 0 or located.code != 0 or not inside or not Path(path).is_file():
        detail = (ensured.stderr or ensured.stdout).strip()[-400:]
        return item("failed", detail or "после загрузки браузер для сборки не найден в папке движка")
    record.update(browser=path, version=pin["version"], node=node,
                  updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    engine.write_record(prefix, record)
    return item("installed", "скачан браузер для сборки видео (~100 МБ)", path=path)


def check_package(prefix: Path, pin: dict) -> dict:
    have = engine.installed_version(prefix)
    if have is None:
        return item("missing", "поставить: install.py --install-deps", path=str(prefix))
    if have != pin["version"]:
        return item("found", f"стоит {have}, нужна {pin['version']}: запустите install.py --update",
                     version=have, path=str(prefix))
    return item("found", version=have, path=str(prefix))


def check_browser(prefix: Path, pin: dict) -> dict:
    record = engine.read_record(prefix)
    if record.get("version") == pin["version"] and record.get("browser") \
            and Path(record["browser"]).is_file():
        return item("found", path=record["browser"])
    return item("missing", "скачается при install.py --install-deps")
```

`skills/aimaster/scripts/install_montage.py`:

```python
#!/usr/bin/env python3
"""Монтаж для install.py: собирает раздел `montage` отчёта из трёх частей —
Node.js 22+ (install_montage_node.py), HyperFrames и браузер для сборки
(install_montage_engine.py), скиллы HyperFrames (install_montage_skills.py).

Всё без оболочки: npm запускается как `node <npm-cli.js>`, HyperFrames — как
`node <prefix>/node_modules/hyperframes/bin/hyperframes.mjs`. Движок живёт в
<user_data_dir>/tools/hyperframes со своим HOME (home/): кэши и скачанный
браузер не попадают в домашнюю папку человека.

Отдельный запуск (CI):  python3 install_montage.py --json [--update] [--install-node]
install.py импортирует этот файл только после проверки версии Python.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS), str(_SCRIPTS.parent)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install  # noqa: E402
from studio.montage import engine  # noqa: E402
from install_montage_engine import browser_install, check_browser, check_package, engine_install  # noqa: E402
from install_montage_node import READY, item, node_check  # noqa: E402

LABELS = (("node", "Node.js 22+"), ("hyperframes", "HyperFrames"),
          ("browser", "браузер для сборки"), ("skills", "скиллы HyperFrames"))
WORDS = {"installed": "поставлено", "found": "есть", "missing": "нет", "failed": "ОШИБКА",
         "timeout": "не успело", "conflict": "конфликт имён"}


def montage_report(kind: str, *, install_missing: bool, update: bool, install_node: bool,
                   home: Path | None = None) -> dict:
    pin = engine.load_pin()
    prefix = engine.tools_prefix(home=home)
    act = install_missing or update
    report = {"prefix": str(prefix), "node": node_check(kind, install_node)}
    node = report["node"].get("path") if report["node"]["status"] in READY else None
    if node is None:
        report["hyperframes"] = item("missing", f"сначала нужен Node.js {pin['node_min_major']}+")
    elif act:
        report["hyperframes"] = engine_install(node, prefix, pin, update=update)
    else:
        report["hyperframes"] = check_package(prefix, pin)
    if report["hyperframes"]["status"] not in READY or engine.installed_version(prefix) != pin["version"]:
        report["browser"] = item("missing", f"сначала нужен HyperFrames {pin['version']}")
    elif act:
        report["browser"] = browser_install(node, prefix, pin)
    else:
        report["browser"] = check_browser(prefix, pin)
    report["ok"] = all(report[key]["status"] in READY for key in ("node", "hyperframes", "browser"))
    return report


def render_montage_lines(report: dict) -> list[str]:
    lines = ["Монтаж (HyperFrames): " + ("готов" if report.get("ok") else "не готов")]
    for key, label in LABELS:
        item = report.get(key)
        if not item:
            continue
        lines.append(f"  {label} — {WORDS.get(item['status'], item['status'])}")
        if item.get("message"):
            lines.append("      " + item["message"])
    return lines


def main(argv=None) -> int:
    install.ensure_utf8_output()
    parser = argparse.ArgumentParser(description="Поставить монтажный движок HyperFrames.")
    parser.add_argument("--json", action="store_true", help="вывод JSON")
    parser.add_argument("--update", action="store_true", help="обновить движок до engine.json")
    parser.add_argument("--install-node", action="store_true",
                        help="поставить Node.js через winget/brew, если его нет или он старый")
    parser.add_argument("--check", action="store_true", help="только проверить, ничего не ставить")
    parser.add_argument("--home", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    home = Path(args.home).expanduser() if args.home else None
    report = montage_report(install.platform_kind(), install_missing=not args.check,
                            update=args.update and not args.check,
                            install_node=args.install_node and not args.check, home=home)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else "\n".join(render_montage_lines(report)))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

```

Правки `skills/aimaster/scripts/install.py` (синтаксис старых Python 3 не нарушать — без f-строк):

- докстринг, пункт 3 — заменить

```
  3. проверяет необязательные программы (ffmpeg, cloudflared, git, node) и
     ставит их только с флагом --install-deps;
```
на
```
  3. проверяет необязательные программы (ffmpeg, cloudflared, git) и монтаж
     (Node.js 22+, движок HyperFrames, браузер для сборки, скиллы HyperFrames —
     scripts/install_montage.py) и ставит их только с флагом --install-deps;
```

- из `DEPS` удалить запись целиком:

```python
    ("node", "только разработчикам: тесты интерфейса", None, {
        "windows": "winget install -e --id OpenJS.NodeJS.LTS",
        "macos": "brew install node", "linux": "sudo apt install nodejs"}),
```

- `_run` принимает окружение:

```python
def _run(argv, cwd=None, timeout=None, env=None):
    """Запуск без оболочки; вывод как байты, декодируем сами (UTF-8 с заменой).

    Код TIMEOUT_CODE — программа не уложилась в timeout и остановлена."""
    try:
        proc = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, timeout=timeout, env=env)
```

- перед `def build_parser():` добавить:

```python
def _montage_report(kind, install_deps, update, home):
    """Раздел montage отчёта. Модуль импортируется здесь, а не в начале файла:
    install_montage.py написан для Python 3.11+, а проверка версии — в main."""
    import install_montage
    return install_montage.montage_report(kind, install_missing=install_deps, update=update,
                                          install_node=install_deps, home=home)
```

- помощь флага:

```python
    parser.add_argument("--install-deps", action="store_true",
                        help="поставить недостающие ffmpeg, cloudflared, git (winget/brew), "
                             "Node.js 22+ и монтажный движок HyperFrames")
```

- в `main` сразу после `report["deps"] = check_deps(kind, args.install_deps)`:

```python
    report["montage"] = _montage_report(kind, args.install_deps, args.update, home)
```

- в `main` после блока `if any(t["method"] == "copy" ...)` (перед `print`):

```python
    if not report["montage"]["ok"]:
        report["next_steps"].append("Монтаж не готов — повторите: install.py --install-deps "
                                    "(подробности в разделе «Монтаж» выше)")
```

- в `render_text` между циклом по `report["deps"]` и строкой `if report["self_check"] is not None:`:

```python
    if report.get("montage") is not None:
        import install_montage
        lines.extend(install_montage.render_montage_lines(report["montage"]))
```

`INSTALL_WITH_AGENT.md`, раздел «Разрешённые границы» — первый абзац заменить на:

```markdown
Разрешено проверить и при отсутствии поставить Git и Python 3.11+ через
официальный менеджер пакетов ОС (winget, Homebrew, apt), а также запустить
`install.py --install-deps`: он ставит бесплатные ffmpeg, cloudflared и Git,
Node.js 22+ (winget `OpenJS.NodeJS.LTS`, Homebrew `node`; на Linux только
печатает команду) и монтажный движок HyperFrames закреплённой версии: npm-пакет
в папку данных пользователя (не глобально), браузер для сборки видео (~100 МБ)
и скиллы HyperFrames той же версии. На Windows установщик передаёт winget флаги
`--accept-package-agreements --accept-source-agreements`, то есть соглашается с
условиями этих пакетов; если пользователь против, запустите без
`--install-deps` — установщик только напечатает команды. pip и сторонние
Python-пакеты не нужны.
```

`README.md`, «Вариант 2» — строки

```
Нужны Python 3.11+ и Git (без Git можно скачать архив). Node, npm и `pip` не
нужны. Всё остальное делает установщик `install.py`: подключает навык к
```
заменить на
```
Нужны Python 3.11+ и Git (без Git можно скачать архив); `pip` не нужен. Для
монтажа нужен Node.js 22+ — его вместе с движком HyperFrames ставит
`install.py --install-deps`. Всё остальное делает установщик `install.py`: подключает навык к
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_install*.py' -v`
Expected: PASS (новые 18 тестов в `test_install_montage.py`; все тесты `test_install.py`, включая новый `test_montage_section_is_reported_and_rendered`).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/scripts/install_montage_node.py skills/aimaster/scripts/install_montage_engine.py skills/aimaster/scripts/install_montage.py skills/aimaster/scripts/install.py skills/aimaster/scripts/test_install.py skills/aimaster/scripts/test_install_montage.py INSTALL_WITH_AGENT.md README.md
git commit -m "feat(install): Node 22+, pinned HyperFrames and render browser via --install-deps"
```

---

### Task 5: Скиллы HyperFrames той же версии

**Files:**
- Create: `skills/aimaster/scripts/install_montage_fetch.py` (скачивание и сверка)
- Create: `skills/aimaster/scripts/install_montage_skills.py` (подключение и отчёт)
- Modify: `skills/aimaster/scripts/install_montage.py` (`montage_report` получает `agents`, `skills`; раздел `skills`)
- Modify: `skills/aimaster/scripts/install.py` (`_montage_report` передаёт `agents`)
- Modify: `skills/aimaster/scripts/test_install.py` (ожидаемые аргументы заглушки)
- Modify: `skills/aimaster/scripts/test_install_montage.py` (`ReportTests.setUp` глушит скачивание скиллов)
- Test: `skills/aimaster/scripts/test_install_montage_skills.py`

**Interfaces:**
- Consumes: `install.AGENT_DIRS`, `install.MARKER`, `install.connect(source, target, version) -> (method, notes)`, `install.replace_installed(source, target, version) -> (method, notes, leftover)`, `install._is_link_like`, `install._norm`, `install._inside`, `install._short_error`; `engine.load_pin()["skills"]`.
- Produces (скачивание — `install_montage_fetch`):
  - `install_montage_fetch.git_blob_sha(data: bytes) -> str`; `bundle_hash(skill_dir: Path) -> tuple[str, int]`.
  - `ssl_context() -> ssl.SSLContext` — если хранилище корневых сертификатов Python пусто (Python с python.org на macOS без «Install Certificates.command» — проверено на этой машине: `CERTIFICATE_VERIFY_FAILED`), подгружает системный набор `/etc/ssl/cert.pem` (macOS), `/etc/ssl/certs/ca-certificates.crt` (Debian/Ubuntu) или `/etc/pki/tls/certs/ca-bundle.crt` (RHEL).
  - `fetch_tree(pin: dict, *, opener=urllib.request.urlopen) -> list[dict]`; `class RawFetcher(pin, *, factory=http.client.HTTPSConnection, context=None)` с `get(rel_path) -> bytes`, `close()`.
  - `verify_skills(root: Path, pin: dict) -> list[str]`; `download_skills(pin, dest: Path, *, tree=None, fetcher=None) -> None`.
- Produces (подключение и отчёт — `install_montage_skills`):
  - `inspect_skill(target: Path, source: Path, ours_root: Path) -> "missing"|"ours_current"|"ours_old"|"foreign"`.
  - `link_skills(source_root, ours_root, home, version, *, names, agents=("claude", "codex"), create=True) -> list[dict]` — элементы `{"agent", "name", "path", "status", "method", "message"}`.
  - `skills_report(prefix: Path, home: Path, *, act: bool, agents=("claude", "codex"), pin=None, tree=None, fetcher=None) -> {"status", "version", "names", "items", "message"}`; статусы `installed|found|missing|failed|timeout|conflict`.
  - `install_montage.montage_report(kind, *, install_missing, update, install_node, home=None, agents=("claude", "codex"), skills=True) -> dict` — теперь с ключом `skills` (на `ok` не влияет: `ok` — готовность движка).
  - `install._montage_report(kind, install_deps, update, home, agents)`.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_install_montage_skills.py` (эталонные хэши посчитаны тем же алгоритмом, что совпал с `skills-manifest.json` HyperFrames 0.8.75 на всех 21 скилле):

```python
#!/usr/bin/env python3
"""Скиллы HyperFrames: сверка с выпуском, подключение как у навыка, чужое не трогаем."""

from __future__ import annotations

import io
import json
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

import install_montage_fetch as fetch  # noqa: E402
import install_montage_skills as skills  # noqa: E402

FILES = {
    "demo/SKILL.md": b"---\nname: demo\n---\r\nhello\r\n",
    "demo/scripts/run.py": b"print(1)\r\n",
    "demo/a.json": b'{"a":1}',
    "other/SKILL.md": b"---\nname: other\n---\n",
}
PIN = {"repo": "heygen-com/hyperframes", "tag": "v9.9.9", "commit": "c" * 40, "tree": "t" * 40,
       "bundles": {"demo": {"hash": "82e2a555abf32641", "files": 3},
                   "other": {"hash": "05d1df8575671f97", "files": 1}}}


def tree_for(files):
    return [{"path": path, "type": "blob", "sha": fetch.git_blob_sha(data),
             "mode": "100755" if path.endswith(".py") else "100644"} for path, data in files.items()]


class FakeFetcher:
    def __init__(self, files):
        self.files = dict(files)
        self.gets = []

    def get(self, rel_path):
        self.gets.append(rel_path)
        return self.files[rel_path]

    def close(self):
        pass


class _Temp(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()

    def write(self, root: Path, files=FILES):
        for rel, data in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)
        return root


class HashTests(_Temp):
    def test_git_blob_sha_matches_git(self):
        self.assertEqual(fetch.git_blob_sha(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_bundle_hash_matches_reference_vectors(self):
        root = self.write(self.base / "skills")
        self.assertEqual(fetch.bundle_hash(root / "demo"), ("82e2a555abf32641", 3))
        self.assertEqual(fetch.bundle_hash(root / "other"), ("05d1df8575671f97", 1))

    def test_crlf_is_normalized_only_in_text_files(self):
        lf = dict(FILES, **{"demo/SKILL.md": b"---\nname: demo\n---\nhello\n"})
        root = self.write(self.base / "lf", lf)
        self.assertEqual(fetch.bundle_hash(root / "demo")[0], "82e2a555abf32641")
        py_lf = dict(FILES, **{"demo/scripts/run.py": b"print(1)\n"})
        root = self.write(self.base / "py", py_lf)
        self.assertNotEqual(fetch.bundle_hash(root / "demo")[0], "82e2a555abf32641")


class TreeTests(unittest.TestCase):
    def opener(self, payload):
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        return lambda request, timeout=None, context=None: Response(json.dumps(payload).encode())

    def test_keeps_only_pinned_skills_blobs(self):
        payload = {"truncated": False, "tree": tree_for(FILES) + [
            {"path": "figma/SKILL.md", "type": "blob", "sha": "x"},
            {"path": "demo", "type": "tree", "sha": "y"}]}
        paths = [item["path"] for item in fetch.fetch_tree(PIN, opener=self.opener(payload))]
        self.assertEqual(sorted(paths), sorted(FILES))

    def test_truncated_tree_is_refused(self):
        with self.assertRaises(OSError):
            fetch.fetch_tree(PIN, opener=self.opener({"truncated": True, "tree": []}))


class SslTests(unittest.TestCase):
    def test_empty_python_store_falls_back_to_the_system_bundle(self):
        loaded = []
        fake = mock.Mock(cert_store_stats=mock.Mock(return_value={"x509_ca": 0}),
                         load_verify_locations=lambda cafile: loaded.append(cafile))
        with mock.patch.object(fetch.ssl, "create_default_context", return_value=fake), \
                mock.patch.object(fetch.os.path, "isfile", side_effect=lambda path: path == "/etc/ssl/cert.pem"):
            self.assertIs(fetch.ssl_context(), fake)
        self.assertEqual(loaded, ["/etc/ssl/cert.pem"])

    def test_filled_store_is_left_alone(self):
        fake = mock.Mock(cert_store_stats=mock.Mock(return_value={"x509_ca": 150}))
        with mock.patch.object(fetch.ssl, "create_default_context", return_value=fake):
            fetch.ssl_context()
        fake.load_verify_locations.assert_not_called()


class DownloadTests(_Temp):
    def test_download_verifies_and_places_the_bundle(self):
        dest = self.base / "skills" / "v9.9.9"
        fetch.download_skills(PIN, dest, tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertEqual(fetch.verify_skills(dest, PIN), [])
        if os.name != "nt":
            self.assertTrue(os.access(dest / "demo" / "scripts" / "run.py", os.X_OK))

    def test_tampered_file_leaves_nothing(self):
        dest = self.base / "skills" / "v9.9.9"
        bad = dict(FILES, **{"demo/a.json": b'{"a":2}'})
        with self.assertRaises(OSError) as caught:
            fetch.download_skills(PIN, dest, tree=tree_for(FILES), fetcher=FakeFetcher(bad))
        self.assertIn("git sha", str(caught.exception))
        self.assertFalse(dest.exists())
        self.assertEqual(list((self.base / "skills").iterdir()), [])

    def test_wrong_bundle_hash_is_refused(self):
        pin = dict(PIN, bundles={**PIN["bundles"], "demo": {"hash": "0" * 16, "files": 3}})
        with self.assertRaises(OSError) as caught:
            fetch.download_skills(pin, self.base / "d", tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertIn("demo", str(caught.exception))


class LinkTests(_Temp):
    def setUp(self):
        super().setUp()
        self.home = self.base / "дом"
        self.ours = self.base / "tools" / "skills"
        self.source = self.write(self.ours / "v9.9.9")

    def link(self, create=True):
        return skills.link_skills(self.source, self.ours, self.home, "v9.9.9",
                                  names=["demo", "other"], create=create)

    def test_fresh_install_then_repeat_is_found(self):
        first = self.link()
        self.assertEqual({i["status"] for i in first}, {"installed"})
        self.assertEqual(len(first), 4)
        self.assertTrue((self.home / ".claude" / "skills" / "demo" / "SKILL.md").is_file())
        self.assertTrue((self.home / ".agents" / "skills" / "other" / "SKILL.md").is_file())
        self.assertEqual({i["status"] for i in self.link()}, {"found"})

    def test_foreign_folder_is_a_conflict_and_untouched(self):
        foreign = self.home / ".claude" / "skills" / "other"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("чужое", encoding="utf-8")
        items = {(i["agent"], i["name"]): i for i in self.link()}
        self.assertEqual(items[("claude", "other")]["status"], "conflict")
        self.assertEqual((foreign / "SKILL.md").read_text(encoding="utf-8"), "чужое")
        self.assertEqual(items[("claude", "demo")]["status"], "installed")

    def test_old_version_of_ours_is_replaced(self):
        old = self.write(self.ours / "v9.9.8")
        skills.link_skills(old, self.ours, self.home, "v9.9.8", names=["demo"], agents=("claude",))
        target = self.home / ".claude" / "skills" / "demo"
        self.assertEqual(skills.inspect_skill(target, self.source / "demo", self.ours), "ours_old")
        items = skills.link_skills(self.source, self.ours, self.home, "v9.9.9", names=["demo"],
                                   agents=("claude",))
        self.assertEqual(items[0]["status"], "installed")
        self.assertEqual(skills.inspect_skill(target, self.source / "demo", self.ours), "ours_current")

    def test_dry_run_reports_missing(self):
        self.assertEqual({i["status"] for i in self.link(create=False)}, {"missing"})
        self.assertFalse((self.home / ".claude").exists())


class ReportTests(_Temp):
    def test_check_only_never_downloads(self):
        fetcher = FakeFetcher({})
        report = skills.skills_report(self.base / "tools", self.base / "дом", act=False, pin=PIN,
                                      tree=[], fetcher=fetcher)
        self.assertEqual(report["status"], "missing")
        self.assertEqual(fetcher.gets, [])

    def test_act_downloads_links_and_aggregates(self):
        report = skills.skills_report(self.base / "tools", self.base / "дом", act=True, pin=PIN,
                                      tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertEqual((report["status"], report["version"]), ("installed", "v9.9.9"))
        again = skills.skills_report(self.base / "tools", self.base / "дом", act=True, pin=PIN,
                                     tree=[], fetcher=FakeFetcher({}))
        self.assertEqual(again["status"], "found")

    def test_conflict_is_named_in_the_message(self):
        foreign = self.base / "дом" / ".claude" / "skills" / "other"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("чужое", encoding="utf-8")
        report = skills.skills_report(self.base / "tools", self.base / "дом", act=True, pin=PIN,
                                      tree=tree_for(FILES), fetcher=FakeFetcher(FILES))
        self.assertEqual(report["status"], "conflict")
        self.assertIn(str(foreign), report["message"])

    def test_rate_limit_message(self):
        error = skills.urllib.error.HTTPError("https://api.github.com", 403, "rate limit", {}, None)
        with mock.patch.object(skills, "download_skills", side_effect=error):
            report = skills.skills_report(self.base / "tools", self.base / "дом", act=True, pin=PIN)
        self.assertEqual(report["status"], "failed")
        self.assertIn("через час", report["message"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_install_montage_skills.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'install_montage_fetch'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/scripts/install_montage_fetch.py`:

```python
#!/usr/bin/env python3
"""Скачивание и сверка скиллов HyperFrames закреплённой версии (engine.json → skills).

Список файлов — один запрос к API деревьев GitHub по закреплённому дереву
`skills/`, содержимое — raw.githubusercontent.com по закреплённому коммиту через
одно HTTPS-соединение. Каждый файл сверяется с git-хэшем блоба, каждый скилл —
с хэшем набора из skills-manifest.json этой версии (алгоритм `hashSkillBundle`
HyperFrames, воспроизведён и сверен на всех 21 скилле v0.8.75). Подключение в
каталоги агентов — install_montage_skills.py.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import shutil
import ssl
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

import install

API_TREE = "https://api.github.com/repos/{repo}/git/trees/{tree}?recursive=1"
RAW_HOST = "raw.githubusercontent.com"
TEXT_EXT = frozenset({".md", ".txt", ".mjs", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
                      ".json", ".svg", ".csv", ".yml", ".yaml"})
HTTP_TIMEOUT = 60
HEADERS = {"User-Agent": "aimaster-install", "Accept": "application/vnd.github+json"}
CA_BUNDLES = ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
              "/etc/pki/tls/certs/ca-bundle.crt")


def ssl_context() -> ssl.SSLContext:
    """Python с python.org на macOS приходит без корневых сертификатов, пока не
    запущен «Install Certificates.command»: тогда проверка GitHub падает с
    CERTIFICATE_VERIFY_FAILED. Пустое хранилище дополняем системным набором."""

    context = ssl.create_default_context()
    if context.cert_store_stats().get("x509_ca", 0) == 0:
        bundle = next((path for path in CA_BUNDLES if os.path.isfile(path)), None)
        if bundle:
            context.load_verify_locations(cafile=bundle)
    return context


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def bundle_hash(skill_dir: Path) -> tuple[str, int]:
    """(хэш, число файлов) как у `hyperframes skills check`: CRLF → LF только в текстовых."""

    skill_dir = Path(skill_dir)
    files = sorted((p for p in skill_dir.rglob("*")
                    if p.is_file() and p.name not in (".DS_Store", install.MARKER)),
                   key=lambda p: p.relative_to(skill_dir).as_posix())
    digest = hashlib.sha256()
    for path in files:
        rel = path.relative_to(skill_dir).as_posix()
        data = path.read_bytes()
        if rel[rel.rfind("."):] in TEXT_EXT:
            data = data.decode("utf-8").replace("\r\n", "\n").encode("utf-8")
        digest.update(rel.encode("utf-8") + b"\0" + data + b"\0")
    return digest.hexdigest()[:16], len(files)


def fetch_tree(pin: dict, *, opener=urllib.request.urlopen) -> list[dict]:
    request = urllib.request.Request(API_TREE.format(repo=pin["repo"], tree=pin["tree"]),
                                     headers=HEADERS)
    with opener(request, timeout=HTTP_TIMEOUT, context=ssl_context()) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("truncated"):
        raise OSError("GitHub отдал неполный список файлов скиллов")
    names = set(pin["bundles"])
    return [item for item in payload.get("tree", []) if item.get("type") == "blob"
            and str(item.get("path", "")).split("/", 1)[0] in names]


class RawFetcher:
    """Одно HTTPS-соединение на все файлы: сотни мелких запросов без нового TLS."""

    def __init__(self, pin: dict, *, factory=http.client.HTTPSConnection, context=None):
        self.base = f"/{pin['repo']}/{pin['commit']}/skills/"
        self.factory = factory
        self.context = context or ssl_context()
        self.connection = None

    def get(self, rel_path: str) -> bytes:
        for attempt in (1, 2):
            if self.connection is None:
                self.connection = self.factory(RAW_HOST, timeout=HTTP_TIMEOUT, context=self.context)
            try:
                self.connection.request("GET", self.base + urllib.parse.quote(rel_path),
                                        headers={"User-Agent": HEADERS["User-Agent"]})
                response = self.connection.getresponse()
                body = response.read()
            except (OSError, http.client.HTTPException):
                self.close()
                if attempt == 2:
                    raise
                continue
            if response.status != 200:
                raise OSError(f"{RAW_HOST}: {rel_path} → HTTP {response.status}")
            return body
        raise OSError(f"{RAW_HOST}: {rel_path} не скачался")

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None


def verify_skills(root: Path, pin: dict) -> list[str]:
    """Имена скиллов, которых нет в root или чей хэш не совпал с выпуском."""

    broken = []
    for name, expected in sorted(pin["bundles"].items()):
        folder = Path(root) / name
        if not (folder / "SKILL.md").is_file() \
                or bundle_hash(folder) != (expected["hash"], expected["files"]):
            broken.append(name)
    return broken


def download_skills(pin: dict, dest: Path, *, tree=None, fetcher=None) -> None:
    """Качает во временную папку рядом с dest, сверяет, затем ставит на место."""

    tree = fetch_tree(pin) if tree is None else tree
    own = fetcher is None
    fetcher = RawFetcher(pin) if own else fetcher
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=".download-", dir=str(dest.parent)))
    try:
        for item in tree:
            data = fetcher.get(item["path"])
            if git_blob_sha(data) != item["sha"]:
                raise OSError(f"файл {item['path']} не совпал с выпуском {pin['tag']} (git sha)")
            target = work / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if item.get("mode") == "100755" and os.name != "nt":
                target.chmod(0o755)
        broken = verify_skills(work, pin)
        if broken:
            raise OSError(f"скиллы не совпали с выпуском {pin['tag']}: {', '.join(broken)}")
        if dest.exists():
            shutil.rmtree(dest)  # своя прежняя загрузка того же тега, не прошедшая сверку
        os.rename(work, dest)
    finally:
        if own:
            fetcher.close()
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
```

`skills/aimaster/scripts/install_montage_skills.py`:

```python
#!/usr/bin/env python3
"""Скиллы HyperFrames той же версии, что и движок: подключение и отчёт.

Скачанное (install_montage_fetch.py) лежит в <prefix>/skills/<тег>/<имя> и
подключается в ~/.claude/skills и ~/.agents/skills так же, как навык aimaster
(install.connect: ссылка, junction или копия с пометкой). Чужая папка с тем же
именем не трогается — статус conflict. Ставится только ядро (10 скиллов):
сценарные скиллы HyperFrames (figma, slideshow, …) не нужны — монтажом руководит
aimaster.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.error
from pathlib import Path

import install
from install_montage_fetch import download_skills, verify_skills
from studio.montage import engine


def inspect_skill(target: Path, source: Path, ours_root: Path) -> str:
    """missing | ours_current | ours_old | foreign."""

    if install._is_link_like(target):
        if install._norm(target) == install._norm(source):
            return "ours_current"
        return "ours_old" if install._inside(os.path.realpath(str(target)), str(ours_root)) \
            else "foreign"
    if not Path(target).exists():
        return "missing"
    try:
        marker = json.loads((Path(target) / install.MARKER).read_text(encoding="utf-8"))
        origin = str(marker.get("source", ""))
    except (OSError, ValueError, AttributeError):
        return "foreign"
    if not origin or not install._inside(origin, str(ours_root)):
        return "foreign"
    return "ours_current" if install._norm(origin) == install._norm(source) else "ours_old"


def link_skills(source_root, ours_root, home, version, *, names, agents=("claude", "codex"),
                create=True) -> list[dict]:
    items = []
    for agent, _label, parts in install.AGENT_DIRS:
        if agent not in agents:
            continue
        for name in names:
            source = Path(source_root) / name
            target = Path(home).joinpath(*parts) / name
            state = inspect_skill(target, source, Path(ours_root))
            item = {"agent": agent, "name": name, "path": str(target), "status": "found",
                    "method": None, "message": ""}
            if state == "foreign":
                item.update(status="conflict", message="здесь чужая папка с тем же именем; не тронута")
            elif state != "ours_current" and not create:
                item.update(status="missing", message="поставить: install.py --install-deps")
            elif state != "ours_current":
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if state == "ours_old":
                        method, _notes, _left = install.replace_installed(source, target, version)
                    else:
                        method, _notes = install.connect(source, target, version)
                    item.update(status="installed", method=method)
                except (OSError, shutil.Error) as error:
                    item.update(status="failed", message=install._short_error(error))
            items.append(item)
    return items


def _overall(statuses) -> str:
    for status in ("failed", "timeout", "conflict", "missing", "installed"):
        if status in statuses:
            return status
    return "found"


def _download_problem(error) -> tuple[str, str]:
    reason = getattr(error, "reason", None)
    if isinstance(error, TimeoutError) or isinstance(reason, TimeoutError):
        return "timeout", "скиллы HyperFrames не скачались за отведённое время; повторите позже"
    if isinstance(error, urllib.error.HTTPError) and error.code in (403, 429):
        return "failed", "GitHub временно ограничил число запросов — повторите через час"
    if "CERTIFICATE_VERIFY_FAILED" in str(error):
        return "failed", ("не удалось проверить сертификат GitHub: у этого Python нет корневых "
                          "сертификатов (на macOS запустите «Install Certificates.command» из папки Python)")
    return "failed", "скиллы HyperFrames не скачались: " + install._short_error(error)


def skills_report(prefix: Path, home: Path, *, act: bool, agents=("claude", "codex"),
                  pin=None, tree=None, fetcher=None) -> dict:
    pin = pin or engine.load_pin()["skills"]
    ours_root = Path(prefix) / "skills"
    source_root = ours_root / pin["tag"]
    names = sorted(pin["bundles"])
    base = {"version": pin["tag"], "names": names, "items": [], "message": ""}
    if verify_skills(source_root, pin):
        if not act:
            return {**base, "status": "missing",
                    "message": "скиллы HyperFrames не скачаны; поставить: install.py --install-deps"}
        try:
            download_skills(pin, source_root, tree=tree, fetcher=fetcher)
        except (OSError, ValueError) as error:
            status, message = _download_problem(error)
            return {**base, "status": status, "message": message}
    items = link_skills(source_root, ours_root, home, pin["tag"], names=names, agents=agents,
                        create=act)
    status = _overall({item["status"] for item in items})
    conflicts = [item["path"] for item in items if item["status"] == "conflict"]
    if conflicts:
        message = "чужие папки с теми же именами не тронуты: " + ", ".join(conflicts)
    elif status == "missing":
        message = "скиллы HyperFrames не подключены; поставить: install.py --install-deps"
    else:
        message = ""
    return {**base, "status": status, "items": items, "message": message}

```

В `skills/aimaster/scripts/install_montage.py`:

- после строки `from install_montage_node import READY, item, node_check  # noqa: E402` добавить `import install_montage_skills  # noqa: E402`;
- `montage_report` заменить целиком:

```python
def montage_report(kind: str, *, install_missing: bool, update: bool, install_node: bool,
                   home: Path | None = None, agents=("claude", "codex"), skills=True) -> dict:
    pin = engine.load_pin()
    prefix = engine.tools_prefix(home=home)
    act = install_missing or update
    report = {"prefix": str(prefix), "node": node_check(kind, install_node)}
    node = report["node"].get("path") if report["node"]["status"] in READY else None
    if node is None:
        report["hyperframes"] = item("missing", f"сначала нужен Node.js {pin['node_min_major']}+")
    elif act:
        report["hyperframes"] = engine_install(node, prefix, pin, update=update)
    else:
        report["hyperframes"] = check_package(prefix, pin)
    if report["hyperframes"]["status"] not in READY or engine.installed_version(prefix) != pin["version"]:
        report["browser"] = item("missing", f"сначала нужен HyperFrames {pin['version']}")
    elif act:
        report["browser"] = browser_install(node, prefix, pin)
    else:
        report["browser"] = check_browser(prefix, pin)
    if skills:
        report["skills"] = install_montage_skills.skills_report(
            prefix, Path(home) if home else Path.home(), act=act, agents=agents)
    # ok — готовность движка; конфликт имён скиллов виден в report["skills"], но сборку не блокирует
    report["ok"] = all(report[key]["status"] in READY for key in ("node", "hyperframes", "browser"))
    return report
```

В `skills/aimaster/scripts/install.py` — `_montage_report` заменить:

```python
def _montage_report(kind, install_deps, update, home, agents):
    """Раздел montage отчёта. Модуль импортируется здесь, а не в начале файла:
    install_montage.py написан для Python 3.11+, а проверка версии — в main."""
    import install_montage
    return install_montage.montage_report(kind, install_missing=install_deps, update=update,
                                          install_node=install_deps, home=home, agents=agents)
```

и вызов в `main`:

```python
    agents = ("claude", "codex") if args.agent == "all" else (args.agent,)
    report["montage"] = _montage_report(kind, args.install_deps, args.update, home, agents)
```

В `skills/aimaster/scripts/test_install.py`, тест `test_montage_section_is_reported_and_rendered` — строки распаковки аргументов заменить на:

```python
        kind, install_deps, update, home, agents = self.montage.call_args.args
        self.assertEqual((kind, install_deps, update, home, agents),
                         (report["platform"], True, False, self.home, ("claude", "codex")))
```

В `skills/aimaster/scripts/test_install_montage.py`, `ReportTests.setUp` — в конец добавить:

```python
        skills_patch = mock.patch.object(install_montage.install_montage_skills, "skills_report",
                                         return_value={"status": "found", "items": [], "message": ""})
        self.skills = skills_patch.start()
        self.addCleanup(skills_patch.stop)
```

и в `ReportTests` — тест:

```python
    def test_skills_follow_the_act_flag_and_agents(self):
        with mock.patch.object(engine, "find_node", return_value=None):
            report = install_montage.montage_report("linux", install_missing=True, update=False,
                                                    install_node=False, home=self.base,
                                                    agents=("claude",))
        self.assertEqual(report["skills"]["status"], "found")
        _prefix, home = self.skills.call_args.args
        self.assertEqual(home, self.base)
        self.assertEqual(self.skills.call_args.kwargs, {"act": True, "agents": ("claude",)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_install*.py' -v`
Expected: PASS (новые 18 тестов в `test_install_montage_skills.py`; `test_install_montage.py` — 19; `test_install.py` — все).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/scripts/install_montage_fetch.py skills/aimaster/scripts/install_montage_skills.py skills/aimaster/scripts/install_montage.py skills/aimaster/scripts/install.py skills/aimaster/scripts/test_install.py skills/aimaster/scripts/test_install_montage.py skills/aimaster/scripts/test_install_montage_skills.py
git commit -m "feat(install): HyperFrames core skills pinned to v0.8.75, conflicts left untouched"
```

---

### Task 6: CI — настоящий движок на трёх ОС, рендер 3 с, рендер без сети на Linux

**Files:**
- Create: `skills/aimaster/scripts/montage_ci_check.py`
- Modify: `.github/workflows/ci.yml` (новая задача `montage-engine`)
- Test: `skills/aimaster/scripts/test_montage_ci_check.py`

**Interfaces:**
- Consumes: `engine.require_engine()`, `engine_cli.run_engine`, `engine_cli.run_engine_json`, `engine_cli.frames_cache`, `probe.probe_media`, `montage_testkit.make_clip/make_tone`, `platform_compat.ensure_utf8_stdio`.
- Produces: `montage_ci_check.COMPOSITION: str`, `montage_ci_check.external_urls(html_text) -> list[str]`, `montage_ci_check.check(offline: bool) -> dict`, `montage_ci_check.main(argv=None) -> int` (JSON: `ok`, `offline`, `engine`, `lint_errors`, `render_seconds`, `probe`, `external_urls`, `network_markers` — неожиданная сеть, ошибка; `known_network` — подкачка Inter с Google Fonts, известное ограничение; `problems`). Задача 19 переведёт проверку на настоящий черновик.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_ci_check.py`:

```python
#!/usr/bin/env python3
"""Проверка движка для CI: без движка — понятный JSON, композиция без внешних ссылок."""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import montage_ci_check  # noqa: E402
from studio.montage import MontageError  # noqa: E402


class CiCheckTests(unittest.TestCase):
    def test_missing_engine_is_json_not_traceback(self):
        buffer = io.StringIO()
        with mock.patch.object(montage_ci_check, "require_engine",
                               side_effect=MontageError("Монтажный движок не готов: не найден Node.js")), \
                redirect_stdout(buffer):
            code = montage_ci_check.main(["--json"])
        report = json.loads(buffer.getvalue())
        self.assertEqual(code, 1)
        self.assertIs(report["ok"], False)
        self.assertIn("не готов", report["problems"][0])

    def test_external_urls_are_found(self):
        html = ('<link href="https://fonts.googleapis.com/css2?family=Inter">'
                '<video src="assets/a.mp4"></video>'
                '<div style="background:url(//cdn.example/y.png)"></div>'
                '<img src="data:image/png;base64,AA">')
        self.assertEqual(montage_ci_check.external_urls(html),
                         ["https://fonts.googleapis.com/css2?family=Inter", "//cdn.example/y.png"])

    def test_fixture_has_no_external_urls_and_no_gsap(self):
        self.assertEqual(montage_ci_check.external_urls(montage_ci_check.COMPOSITION), [])
        self.assertNotIn("gsap", montage_ci_check.COMPOSITION.lower())
        self.assertIn("data-no-timeline", montage_ci_check.COMPOSITION)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_ci_check.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'montage_ci_check'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/scripts/montage_ci_check.py`:

```python
#!/usr/bin/env python3
"""Проверка монтажного движка на CI: ролик 3 с из клипов ffmpeg.

    python skills/aimaster/scripts/montage_ci_check.py --json [--offline]

Берёт движок, поставленный install_montage.py; в папке с кириллицей и
пробелами собирает композицию из двух клипов, титра и голоса, прогоняет lint,
рендер и ffprobe, ищет в композиции внешние ссылки, а в логе рендера — следы
сетевых запросов (шрифты Google, CDN). --offline только помечает запуск: сеть
отрезают снаружи (см. .github/workflows/ci.yml).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import asdict
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS.parent), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import montage_testkit  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.engine import require_engine  # noqa: E402
from studio.montage.engine_cli import frames_cache, run_engine, run_engine_json  # noqa: E402
from studio.montage.probe import probe_media  # noqa: E402
from studio.platform_compat import ensure_utf8_stdio  # noqa: E402

SIZE = (540, 960)
DURATION = 3.0
# CDN-скрипт в логе — ошибка; подкачка Inter с Google Fonts — известное ограничение
# HyperFrames (подменяет sans-serif на Inter), фиксируется отдельно, но не валит проверку.
SCRIPT_MARKERS = ("Inlined CDN script", "Failed to download CDN script")
FONT_MARKERS = ("from Google Fonts",)
_EXTERNAL = re.compile(r"""(?:src|href)\s*=\s*["']((?:[a-z][a-z0-9+.-]*:|//)[^"']*)"""
                       r"""|url\(\s*["']?((?:[a-z][a-z0-9+.-]*:|//)[^"')]*)""", re.I)

COMPOSITION = """<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=540, height=960" />
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 540px; height: 960px; overflow: hidden; background: #000; }
      #root { position: relative; width: 540px; height: 960px; overflow: hidden; background: #000; }
      .am-video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; z-index: 1; }
      .am-fade-in { animation: am-fade-in 0.4s linear both; }
      @keyframes am-fade-in { from { opacity: 0; } to { opacity: 1; } }
      .am-title { position: absolute; left: 30px; right: 30px; bottom: 115px; z-index: 5;
        display: flex; justify-content: center; font-family: sans-serif; }
      .am-title span { background: rgba(0, 0, 0, 0.6); color: #fff; font-size: 32px;
        font-weight: 700; padding: 8px 16px; border-radius: 8px; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="3" data-width="540" data-height="960" data-no-timeline>
      <video id="v-1" class="am-video" src="assets/clip-1.mp4" data-start="0" data-duration="1.5" data-media-start="0" data-track-index="0" data-has-audio="true" data-volume="0.3" playsinline></video>
      <video id="v-2" class="am-video am-fade-in" src="assets/clip-2.mp4" data-start="1.5" data-duration="1.5" data-media-start="0" data-track-index="0" data-has-audio="true" data-volume="0.3" playsinline></video>
      <div id="t-1" class="clip am-title" data-start="0.2" data-duration="2.6" data-track-index="1"><span>Проверка монтажа</span></div>
      <audio id="a-voice" src="assets/voice.wav" data-start="0" data-duration="3" data-media-start="0" data-track-index="2" data-volume="1"></audio>
    </div>
  </body>
</html>
"""


def external_urls(html_text: str) -> list[str]:
    found = [first or second for first, second in _EXTERNAL.findall(html_text)]
    return [url for url in found if not url.lower().startswith("data:")]


def _build(comp: Path) -> None:
    assets = comp / "assets"
    montage_testkit.make_clip(assets / "clip-1.mp4", 1.5, size=SIZE, color="red", freq=440)
    montage_testkit.make_clip(assets / "clip-2.mp4", 1.5, size=SIZE, color="blue", freq=660)
    montage_testkit.make_tone(assets / "voice.wav", DURATION, freq=220)
    (comp / "hyperframes.json").write_text('{\n  "media": {"autoProxy": true}\n}\n', encoding="utf-8")
    (comp / "index.html").write_text(COMPOSITION, encoding="utf-8")


def check(offline: bool) -> dict:
    report = {"ok": False, "offline": offline, "problems": []}
    engine = require_engine()
    report["engine"] = engine.version
    with tempfile.TemporaryDirectory(prefix="aimaster-montage-") as temp:
        comp = Path(temp) / "проверка монтажа" / "ролик 1"
        _build(comp)
        report["external_urls"] = external_urls((comp / "index.html").read_text(encoding="utf-8"))
        lint = run_engine_json(engine, ["lint", ".", "--json"], cwd=comp, timeout=120, ok_codes=(0, 1))
        report["lint_errors"] = [f"{f.get('code')}: {f.get('message')}"
                                 for f in lint.get("findings", []) if f.get("severity") == "error"]
        output = comp.parent / "итог ролика.mp4"
        started = time.monotonic()
        result = run_engine(engine, ["render", ".", "--output", str(output), "--quality", "draft",
                                     "--frames-cache-dir", str(frames_cache(engine)), "--quiet"],
                            cwd=comp, timeout=900)
        report["render_seconds"] = round(time.monotonic() - started, 1)
        log = result.stdout + "\n" + result.stderr
        report["network_markers"] = [line.strip()[:300] for line in log.splitlines()
                                     if any(marker in line for marker in SCRIPT_MARKERS)]
        report["known_network"] = [line.strip()[:300] for line in log.splitlines()
                                   if any(marker in line for marker in FONT_MARKERS)]
        if result.code != 0 or not output.is_file():
            report["problems"].append(f"рендер завершился с кодом {result.code}: {log.strip()[-600:]}")
        else:
            info = probe_media(output)
            report["probe"] = asdict(info)
            if abs(info.duration - DURATION) > 0.1:
                report["problems"].append(f"длительность {info.duration} с вместо {DURATION} с")
            if (info.width, info.height) != SIZE:
                report["problems"].append(f"кадр {info.width}×{info.height} вместо {SIZE[0]}×{SIZE[1]}")
            if not info.has_audio:
                report["problems"].append("в ролике нет звука")
    report["problems"] += [f"внешняя ссылка: {url}" for url in report["external_urls"]]
    report["problems"] += [f"lint: {error}" for error in report["lint_errors"]]
    report["problems"] += [f"сеть: {line}" for line in report["network_markers"]]
    report["ok"] = not report["problems"]
    return report


def main(argv=None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Проверка монтажного движка на CI.")
    parser.add_argument("--json", action="store_true", help="вывод JSON")
    parser.add_argument("--offline", action="store_true", help="пометить запуск без сети")
    args = parser.parse_args(argv)
    try:
        report = check(args.offline)
    except (MontageError, OSError, subprocess.SubprocessError, unittest.SkipTest) as error:
        report = {"ok": False, "offline": args.offline, "problems": [str(error)]}
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else "\n".join(["ОК" if report["ok"] else "НЕ ПРОЙДЕНО", *report["problems"]]))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

В `.github/workflows/ci.yml` в конец секции `jobs:` добавить задачу (текущий CI FFmpeg не ставит — ставим здесь):

```yaml
  montage-engine:
    name: montage · ${{ matrix.os }}
    runs-on: ${{ matrix.os }}
    timeout-minutes: 45
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    env:
      PYTHONUTF8: "1"
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - uses: actions/setup-node@v4
        with:
          node-version: "22"

      - name: FFmpeg (Linux)
        if: runner.os == 'Linux'
        run: sudo apt-get update && sudo apt-get install -y ffmpeg

      - name: FFmpeg (macOS)
        if: runner.os == 'macOS'
        run: brew install ffmpeg

      - name: FFmpeg (Windows)
        if: runner.os == 'Windows'
        run: choco install ffmpeg -y --no-progress

      - name: Install pinned HyperFrames, render browser and skills
        shell: bash
        run: |
          python skills/aimaster/scripts/install_montage.py --json > montage-install.json || true
          cat montage-install.json
          python -c "import json,sys; r=json.load(open('montage-install.json',encoding='utf-8')); sys.exit(0 if r['ok'] and r['skills']['status'] in ('found','installed') else 1)"

      - name: Render a 3-second clip, ffprobe, no external URLs, no network traces
        run: python skills/aimaster/scripts/montage_ci_check.py --json

      - name: Render without network (Linux, empty network namespace)
        if: runner.os == 'Linux'
        run: |
          sudo unshare --net -- bash -c "ip link set lo up && exec setpriv --reuid=$(id -u) --regid=$(id -g) --init-groups env PATH=\"$PATH\" HOME=\"$HOME\" PYTHONUTF8=1 python skills/aimaster/scripts/montage_ci_check.py --json --offline"
```

Если шаг «без сети» на CI упадёт (в отчёте `problems` — строки `сеть: …` или ошибка рендера), шаг не отключать молча: добавить ему `continue-on-error: true`, а в `skills/aimaster/references/montage.md` (задача 20), раздел «Known limitations», записать строки отчёта как известное ограничение. Проба 2026-09-25 на macOS показала, что без сети рендер проходит (кириллица — системным шрифтом), поэтому по умолчанию шаг строгий.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_ci_check.py' -v`
Expected: PASS (3 tests).

Затем проверить на этой машине по-настоящему (движок ставится в папку данных пользователя, ~225 МБ):
Run: `python3 skills/aimaster/scripts/install_montage.py --json && python3 skills/aimaster/scripts/montage_ci_check.py --json`
Expected: оба `"ok": true`; у `montage_ci_check` — `"external_urls": []`, `"network_markers": []`, `probe.duration` ≈ 3.0, `540×960`, `has_audio: true`; в `known_network` при доступной сети — строка «Fetched … "Inter" from Google Fonts» (это известное ограничение, см. факты).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit and watch CI**

```bash
git add skills/aimaster/scripts/montage_ci_check.py skills/aimaster/scripts/test_montage_ci_check.py .github/workflows/ci.yml
git commit -m "ci(montage): real HyperFrames install and 3-second render on three OSes, offline on Linux"
git push
gh run watch --exit-status
```
Expected: задачи `montage · ubuntu-latest|macos-latest|windows-latest` зелёные; в логе Linux шаг «Render without network» — `"ok": true, "offline": true, "known_network": []` (без сети HyperFrames шрифт не качает, а берёт системный).

---
### Task 7: Раскладка `montage/` и точечная правка `index.html`

**Files:**
- Create: `skills/aimaster/studio/montage/paths.py`
- Create: `skills/aimaster/studio/montage/html_doc.py`
- Test: `skills/aimaster/scripts/test_montage_html_doc.py`

**Interfaces:**
- Consumes: `MontageError`.
- Produces:
  - `paths.VERSION_ID` (regex `v\d{3,}`), `paths.version_name(number: int) -> str`, `paths.version_number(version_id: str) -> int` (иначе `ValueError`).
  - `@dataclass(frozen=True) paths.MontagePaths(root: Path)` со свойствами `current`, `index`, `assets`, `versions`, `undo` (`.undo`), `cache` (`.cache`), `logs` (`.logs`), `desk_file` (`.desk.json`) и методом `version_dir(version_id) -> Path`.
  - `paths.montage_paths(project_dir: Path) -> MontagePaths`; `paths.render_output(media_root: Path, project_id: str, version_id: str) -> Path`.
  - `html_doc.ROOT_ID = "root"`; `html_doc.fmt_number(value: float) -> str`; `html_doc.element_attrs(text) -> dict[str, dict[str, str]]` (плюс ключи `_tag`, `_text`); `html_doc.set_attr(text, element_id, name, value: str | None) -> str`; `html_doc.set_text(text, element_id, value) -> str`; `html_doc.element_span(text, element_id) -> tuple[int, int]`; `html_doc.insert_before_root_end(text, fragment, root_id="root") -> str`; `html_doc.root_duration(text) -> float`.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_html_doc.py`:

```python
#!/usr/bin/env python3
"""Раскладка montage/ и точечная правка index.html: остальное — байт в байт."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage import MontageError  # noqa: E402
from studio.montage.html_doc import (  # noqa: E402
    element_attrs, element_span, fmt_number, insert_before_root_end, root_duration, set_attr,
    set_text)
from studio.montage.paths import (  # noqa: E402
    montage_paths, render_output, version_name, version_number)

# Так выглядит композиция после открытия в Studio: data-hf-id, <!DOCTYPE>, <meta …>.
SAMPLE = """<!DOCTYPE html>
<html lang="ru">
  <head>
    <meta charset="UTF-8">
  </head>
  <body>
    <div data-hf-id="hf-qv3y" id="root" data-composition-id="main" data-start="0" data-duration="15" data-width="1080" data-height="1920" data-no-timeline>
      <video data-hf-id="hf-hjwo" id="v-1" class="am-video" src="assets/a.mp4" data-start="0" data-duration="5" data-media-start="0" data-am-layer="video" data-am-scene="s1" playsinline></video>
      <div data-hf-id="hf-d5xw" id="t-1" class="clip am-title" data-start="1" data-duration="2" data-am-layer="titles"><span data-hf-id="hf-p0ft">Барсик &amp; клубок</span></div>
      <audio id="a-voice" src="assets/v.wav" data-start="2" data-duration="6" data-volume="1" data-am-layer="voice"></audio>
    </div>
  </body>
</html>
"""


class ReadTests(unittest.TestCase):
    def test_attributes_text_and_boolean_attrs(self):
        attrs = element_attrs(SAMPLE)
        self.assertEqual((attrs["v-1"]["_tag"], attrs["v-1"]["data-am-scene"]), ("video", "s1"))
        self.assertEqual(attrs["t-1"]["_text"], "Барсик & клубок")
        self.assertEqual(attrs["root"]["data-no-timeline"], "")
        self.assertEqual(root_duration(SAMPLE), 15.0)

    def test_numbers_are_short(self):
        self.assertEqual([fmt_number(v) for v in (1.5, 2, 0.30000001, -0.0, 12.3456)],
                         ["1.5", "2", "0.3", "0", "12.346"])


class PatchTests(unittest.TestCase):
    def test_replace_changes_only_that_value(self):
        changed = set_attr(SAMPLE, "v-1", "data-start", "1")
        self.assertEqual(changed, SAMPLE.replace(
            'src="assets/a.mp4" data-start="0"', 'src="assets/a.mp4" data-start="1"'))

    def test_add_and_remove(self):
        added = set_attr(SAMPLE, "a-voice", "data-fade-out", "0.5")
        self.assertIn('data-am-layer="voice" data-fade-out="0.5"></audio>', added)
        removed = set_attr(SAMPLE, "v-1", "data-media-start", None)
        self.assertIn('data-duration="5" data-am-layer="video"', removed)
        self.assertEqual(set_attr(SAMPLE, "v-1", "data-nothing", None), SAMPLE)

    def test_values_are_escaped(self):
        changed = set_attr(SAMPLE, "t-1", "title", 'a "b" & c')
        self.assertIn('title="a &quot;b&quot; &amp; c"', changed)
        self.assertEqual(element_attrs(changed)["t-1"]["title"], 'a "b" & c')

    def test_title_text(self):
        changed = set_text(SAMPLE, "t-1", "Кот <и> мяч")
        self.assertIn('<span data-hf-id="hf-p0ft">Кот &lt;и&gt; мяч</span>', changed)
        with self.assertRaises(MontageError):
            set_text(SAMPLE, "v-1", "не титр")

    def test_span_and_insert(self):
        begin, end = element_span(SAMPLE, "t-1")
        self.assertTrue(SAMPLE[begin:end].startswith('<div data-hf-id="hf-d5xw" id="t-1"'))
        self.assertTrue(SAMPLE[begin:end].endswith("</span></div>"))
        inserted = insert_before_root_end(SAMPLE, '<div id="t-9"></div>')
        self.assertIn('      <div id="t-9"></div>\n    </div>\n  </body>', inserted)

    def test_missing_element(self):
        with self.assertRaises(MontageError):
            set_attr(SAMPLE, "nope", "data-start", "1")


class PathsTests(unittest.TestCase):
    def test_layout(self):
        paths = montage_paths(Path("/w/projects/p"))
        self.assertEqual(paths.index, Path("/w/projects/p/montage/current/index.html"))
        self.assertEqual(paths.assets, Path("/w/projects/p/montage/current/assets"))
        self.assertEqual(paths.version_dir("v003"), Path("/w/projects/p/montage/versions/v003"))
        self.assertEqual(paths.desk_file, Path("/w/projects/p/montage/.desk.json"))
        self.assertEqual(render_output(Path("/w/media"), "p", "v003"),
                         Path("/w/media/p/montage/v003.mp4"))

    def test_version_names(self):
        self.assertEqual((version_name(12), version_number("v012")), ("v012", 12))
        for bad in ("v1", "003", "v01a"):
            with self.assertRaises(ValueError):
                version_number(bad)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_html_doc.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage.html_doc'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/paths.py`:

```python
"""Раскладка монтажа в папке проекта и путь к MP4 версии в media/.

<проект>/montage/current — рабочий монтаж (его правят Studio и агент),
versions/vNNN — неизменяемые снимки, скрытые .undo/.cache/.logs/.desk.json —
служебное. MP4 версии лежит в <workspace>/media/<проект>/montage/vNNN.mp4:
только внутри media/ его принимает AssetIndex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

VERSION_ID = re.compile(r"v(\d{3,})")


def version_name(number: int) -> str:
    return f"v{number:03d}"


def version_number(version_id: str) -> int:
    match = VERSION_ID.fullmatch(version_id or "")
    if not match:
        raise ValueError(f"не версия монтажа: {version_id!r}")
    return int(match.group(1))


@dataclass(frozen=True)
class MontagePaths:
    root: Path

    @property
    def current(self) -> Path:
        return self.root / "current"

    @property
    def index(self) -> Path:
        return self.current / "index.html"

    @property
    def assets(self) -> Path:
        return self.current / "assets"

    @property
    def versions(self) -> Path:
        return self.root / "versions"

    @property
    def undo(self) -> Path:
        return self.root / ".undo"

    @property
    def cache(self) -> Path:
        return self.root / ".cache"

    @property
    def logs(self) -> Path:
        return self.root / ".logs"

    @property
    def desk_file(self) -> Path:
        return self.root / ".desk.json"

    def version_dir(self, version_id: str) -> Path:
        version_number(version_id)
        return self.versions / version_id


def montage_paths(project_dir: Path) -> MontagePaths:
    return MontagePaths(Path(project_dir) / "montage")


def render_output(media_root: Path, project_id: str, version_id: str) -> Path:
    version_number(version_id)
    return Path(media_root) / project_id / "montage" / f"{version_id}.mp4"
```

`skills/aimaster/studio/montage/html_doc.py`:

```python
"""Чтение и точечная правка index.html композиции.

Атрибуты — по id элемента, текст титра — в его <span>, вставка — перед
закрывающим тегом корня. Правка меняет только нужный открывающий тег или
текст: остальная разметка (в том числе то, что переписала Studio: data-hf-id,
<!DOCTYPE html>, <meta …>) остаётся байт в байт.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from . import MontageError

ROOT_ID = "root"
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                   "source", "track", "wbr"})
_START_TAG = re.compile(
    r"<([a-zA-Z][\w:-]*)((?:\s+[^\s=/>]+(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'>]+))?)*)\s*(/?)>")
_ATTR = re.compile(r"([^\s=/>]+)(?:\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'>]+))?")
_SPAN_OPEN = re.compile(r"<span\b[^>]*>", re.I)


def fmt_number(value: float) -> str:
    """Секунды и громкость в атрибутах: до миллисекунд, без лишних нулей."""

    text = f"{float(value):.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _attrs(raw: str):
    for match in _ATTR.finditer(raw or ""):
        value = match.group(2)
        if value is not None and value[:1] in "\"'":
            value = value[1:-1]
        yield match.group(1).lower(), (html.unescape(value) if value is not None else None), match.span()


def _find_start(text: str, element_id: str) -> re.Match:
    for match in _START_TAG.finditer(text):
        if any(name == "id" and value == element_id for name, value, _ in _attrs(match.group(2))):
            return match
    raise MontageError(f"в монтаже нет элемента {element_id}")


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements: dict[str, dict] = {}
        self.stack: list[tuple[str, str | None]] = []

    def _register(self, tag, attrs):
        data = {name.lower(): (value if value is not None else "") for name, value in attrs}
        element_id = data.get("id")
        if element_id and element_id not in self.elements:
            self.elements[element_id] = {**data, "_tag": tag, "_text": ""}
        return element_id

    def handle_starttag(self, tag, attrs):
        element_id = self._register(tag, attrs)
        if tag not in _VOID:
            self.stack.append((tag, element_id))

    def handle_startendtag(self, tag, attrs):
        self._register(tag, attrs)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        for _tag, element_id in reversed(self.stack):
            if element_id:
                self.elements[element_id]["_text"] += data
                return


def element_attrs(text: str) -> dict[str, dict[str, str]]:
    """{id: {атрибут: значение, "_tag": тег, "_text": текст внутри}}."""

    collector = _Collector()
    collector.feed(text)
    collector.close()
    for data in collector.elements.values():
        data["_text"] = " ".join(data["_text"].split())
    return collector.elements


def set_attr(text: str, element_id: str, name: str, value: str | None) -> str:
    """Ставит, меняет или (value=None) убирает атрибут открывающего тега элемента."""

    match = _find_start(text, element_id)
    raw, start = match.group(2) or "", match.start(2)
    for attr_name, _old, (begin, end) in _attrs(raw):
        if attr_name == name.lower():
            if value is None:
                new_raw = raw[:begin].rstrip() + raw[end:]
            else:
                new_raw = raw[:begin] + f'{name}="{html.escape(value, quote=True)}"' + raw[end:]
            return text[:start] + new_raw + text[start + len(raw):]
    if value is None:
        return text
    insert = start + len(raw)
    return text[:insert] + f' {name}="{html.escape(value, quote=True)}"' + text[insert:]


def element_span(text: str, element_id: str) -> tuple[int, int]:
    """(начало, конец) элемента целиком: от «<» открывающего до «>» закрывающего тега."""

    match = _find_start(text, element_id)
    tag = match.group(1).lower()
    if match.group(3) or tag in _VOID:
        return match.start(), match.end()
    pattern = re.compile(rf"<(/?){re.escape(tag)}\b[^>]*?(/?)>", re.I)
    depth = 1
    for token in pattern.finditer(text, match.end()):
        if token.group(2):
            continue
        depth += -1 if token.group(1) else 1
        if depth == 0:
            return match.start(), token.end()
    raise MontageError(f"у элемента {element_id} нет закрывающего тега")


def set_text(text: str, element_id: str, value: str) -> str:
    """Меняет текст титра — содержимое первого <span> внутри элемента."""

    begin, end = element_span(text, element_id)
    opening = _SPAN_OPEN.search(text, begin, end)
    closing = text.find("</span>", opening.end(), end) if opening else -1
    if closing < 0:
        raise MontageError(f"{element_id} — не титр: в нём нет текста в <span>")
    return text[:opening.end()] + html.escape(value, quote=False) + text[closing:]


def insert_before_root_end(text: str, fragment: str, root_id: str = ROOT_ID) -> str:
    _begin, end = element_span(text, root_id)
    close = text.rfind("<", 0, end)
    line_start = text.rfind("\n", 0, close) + 1
    indent = text[line_start:close]
    if indent.strip():
        return text[:close] + fragment + text[close:]
    return text[:line_start] + indent + "  " + fragment + "\n" + text[line_start:]


def root_duration(text: str) -> float:
    return float(element_attrs(text).get(ROOT_ID, {}).get("data-duration") or 0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_html_doc.py' -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/paths.py skills/aimaster/studio/montage/html_doc.py skills/aimaster/scripts/test_montage_html_doc.py
git commit -m "feat(montage): montage folder layout and byte-preserving index.html patches"
```

---

### Task 8: Медиа композиции — ссылка или копия, проверка ссылок

**Files:**
- Create: `skills/aimaster/studio/montage/media_sync.py`
- Test: `skills/aimaster/scripts/test_montage_media_sync.py`

**Interfaces:**
- Consumes: `MontageError`.
- Produces: `media_sync.ASSETS_DIR = "assets"`; `asset_filename(asset_id, source: Path) -> str` (= `<asset_id><суффикс в нижнем регистре>`); `link_or_copy(source: Path, target: Path) -> "link"|"copy"|"exists"`; `sync_media(items: Iterable[tuple[str, Path]], assets_dir: Path) -> dict[str, {"src": "assets/<файл>", "method"}]`; `references(html_text) -> list[str]`; `external_references(html_text) -> list[str]`; `missing_sources(html_text, current_dir: Path) -> list[str]`; `check_composition(html_text, current_dir: Path) -> list[str]` (строки по-русски; пусто — всё в порядке).

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_media_sync.py`:

```python
#!/usr/bin/env python3
"""Медиа в current/assets: жёсткая ссылка, иначе копия; ссылки композиции не выходят наружу."""

from __future__ import annotations

import errno
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

from studio.montage import MontageError, media_sync  # noqa: E402


class SyncTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.source = self.base / "media" / "клип сцены 1.MP4"
        self.source.parent.mkdir()
        self.source.write_bytes(b"video-bytes")
        self.assets = self.base / "montage" / "current" / "assets"

    def test_hard_link_when_possible_then_exists(self):
        synced = media_sync.sync_media([("asset-1", self.source)], self.assets)
        target = self.assets / "asset-1.mp4"
        self.assertEqual(synced["asset-1"]["src"], "assets/asset-1.mp4")
        self.assertIn(synced["asset-1"]["method"], ("link", "copy"))
        if synced["asset-1"]["method"] == "link":
            self.assertTrue(os.path.samefile(self.source, target))
        again = media_sync.sync_media([("asset-1", self.source)], self.assets)
        self.assertEqual(again["asset-1"]["method"], "exists")

    def test_copy_when_link_is_impossible(self):
        with mock.patch.object(media_sync.os, "link", side_effect=OSError(errno.EXDEV, "cross-device")):
            method = media_sync.link_or_copy(self.source, self.assets / "asset-1.mp4")
        self.assertEqual(method, "copy")
        self.assertEqual((self.assets / "asset-1.mp4").read_bytes(), b"video-bytes")
        self.assertFalse(os.path.samefile(self.source, self.assets / "asset-1.mp4"))
        self.assertEqual(list(self.assets.glob(".*.part")), [])

    def test_other_file_with_same_name_is_refused(self):
        self.assets.mkdir(parents=True)
        (self.assets / "asset-1.mp4").write_bytes(b"something else entirely")
        with self.assertRaises(MontageError):
            media_sync.link_or_copy(self.source, self.assets / "asset-1.mp4")


class ReferenceTests(unittest.TestCase):
    HTML = """<html><head>
      <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter">
      <script src="//cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
      <style>@import "https://x.example/a.css"; .a { background: url(file:///etc/x.png); }
             .b { background: url('assets/ok.png'); }</style></head>
      <body><video src="assets/a.mp4"></video><audio src="../media/v.wav"></audio>
      <img src="/abs/x.png"><img src="data:image/png;base64,AA"><a href="#top">.</a>
      <div style="background:url(https://y.example/b.png)"></div></body></html>"""

    def test_external_references(self):
        self.assertEqual(media_sync.external_references(self.HTML), [
            "https://fonts.googleapis.com/css2?family=Inter",
            "//cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js",
            "https://x.example/a.css", "file:///etc/x.png", "https://y.example/b.png"])

    def test_missing_and_escaping_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            current = Path(temp)
            (current / "assets").mkdir()
            (current / "assets" / "a.mp4").write_bytes(b"x")
            (current / "assets" / "ok.png").write_bytes(b"x")
            self.assertEqual(media_sync.missing_sources(self.HTML, current),
                             ["../media/v.wav", "/abs/x.png"])
            problems = media_sync.check_composition(self.HTML, current)
        self.assertIn("внешняя ссылка: https://x.example/a.css", problems)
        self.assertIn("файла нет в папке монтажа: ../media/v.wav", problems)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_media_sync.py' -v`
Expected: FAIL — `ImportError: cannot import name 'media_sync'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/media_sync.py`:

```python
"""Медиа композиции и её ссылки.

Файлы из <workspace>/media попадают в current/assets жёсткой ссылкой (тот же
файл, место на диске не тратится), а если ссылка невозможна (другой диск,
файловая система без ссылок) — копией. Симлинки не используются: на Windows
они требуют прав. Имя в assets — id ассета: уникально и не меняется.
Проверка ссылок нужна потому, что lint HyperFrames внешнюю таблицу стилей не
ловит (проба 0.8.75), а внешняя ссылка — это сеть при сборке.
"""

from __future__ import annotations

import os
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Iterable

from . import MontageError

ASSETS_DIR = "assets"
_URL_ATTRS = frozenset({"src", "href", "poster", "data-src"})
_CSS_URL = re.compile(r"url\(\s*(['\"]?)([^'\")]+)\1\s*\)|@import\s+(['\"])([^'\"]+)\3", re.I)
_SCHEME = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//)", re.I)


def asset_filename(asset_id: str, source: Path) -> str:
    return f"{asset_id}{Path(source).suffix.lower()}"


def link_or_copy(source: Path, target: Path) -> str:
    """'link' | 'copy' | 'exists'. Другой файл с тем же именем — отказ."""

    source, target = Path(source), Path(target)
    if target.exists():
        if os.path.samefile(source, target) or target.stat().st_size == source.stat().st_size:
            return "exists"
        raise MontageError(f"в assets уже лежит другой файл {target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
        return "link"
    except OSError:
        temporary = target.with_name(f".{target.name}.part")
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
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
    parser = _Refs()
    parser.feed(html_text)
    parser.close()
    return [ref for ref in parser.refs if ref and not ref.startswith("#")]


def external_references(html_text: str) -> list[str]:
    """Всё со схемой или «//хост»; встроенные data: — не ссылка наружу."""

    return [ref for ref in references(html_text)
            if _SCHEME.match(ref) and not ref.lower().startswith("data:")]


def missing_sources(html_text: str, current_dir: Path) -> list[str]:
    missing = []
    for ref in references(html_text):
        if _SCHEME.match(ref):
            continue
        path = PurePosixPath(ref.split("?", 1)[0].split("#", 1)[0])
        if path.is_absolute() or ".." in path.parts or not (Path(current_dir) / path).is_file():
            missing.append(ref)
    return missing


def check_composition(html_text: str, current_dir: Path) -> list[str]:
    """Что мешает собрать ролик без сети; пустой список — всё в порядке."""

    problems = [f"внешняя ссылка: {ref}" for ref in external_references(html_text)]
    problems += [f"файла нет в папке монтажа: {ref}"
                 for ref in missing_sources(html_text, current_dir)]
    return problems
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_media_sync.py' -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/media_sync.py skills/aimaster/scripts/test_montage_media_sync.py
git commit -m "feat(montage): hard-link-or-copy media and composition reference checks"
```

---

### Task 9: План черновика из проекта

**Files:**
- Create: `skills/aimaster/studio/montage/draft_plan.py`
- Modify: `skills/aimaster/scripts/montage_testkit.py` (добавить `video_state`)
- Test: `skills/aimaster/scripts/test_montage_draft_plan.py`

**Interfaces:**
- Consumes: `domain_positions.position_specs(state)`, `domain_positions.current_member(state, spec, "result", missing_ok=True)`; `probe.MediaInfo`; `AUDIO_LAYER_NAMES`; `MontageError`.
- Produces:
  - `draft_plan.TRANSITION = 0.4`, `TITLE_INSET = 0.2`, `MIN_TITLE = 0.5`, `DEFAULT_VOLUMES = {"voice": 1.0, "music": 0.3, "fx": 0.8, "atmos": 0.5}`, `VIDEO_VOLUME = {False: 1.0, True: 0.3}`, `LAYER_FADE_OUT = {"music": 1.0, "atmos": 1.0}`.
  - `@dataclass(frozen=True) ClipPlan(clip_id, layer, start, duration, scene_id=None, asset_id=None, media_start=0.0, volume=None, fade_in=0.0, fade_out=0.0, visual_fade=False, has_audio=False, text=None)`.
  - `@dataclass(frozen=True) DraftPlan(duration: float, clips: tuple[ClipPlan, ...])` с `media_assets() -> list[str]` и `first_video_asset() -> str | None`.
  - `scene_ranges(state) -> dict[str, tuple[float, float]]`; `scene_text(scene) -> str`; `video_sources(state, *, strict=True) -> list[tuple[dict | None, str]]`; `audio_sources(state) -> dict[str, str]`; `plan_draft(state, media: Callable[[str], MediaInfo]) -> DraftPlan`.
  - Идентификаторы клипов: видео `v-<n>` (по порядку сцен), титры `t-<n>` (номер сцены), звук `a-<layer>`.
  - `montage_testkit.video_state(scenes, *, audio=None, gen_mode="per_scene", oneshot_asset=None, mode="guided", project_id="p") -> dict`; `scenes` — список `(scene_id, title, text, duration_ms, asset_id | None)`.

- [ ] **Step 1: Write the failing test**

В `skills/aimaster/scripts/montage_testkit.py` добавить в конец:

```python
def video_state(scenes, *, audio=None, gen_mode="per_scene", oneshot_asset=None, mode="guided",
                project_id="p") -> dict:
    """Видеопроект на шаге «Сборка»: всё до звука одобрено, у позиций выбраны результаты.

    scenes — [(scene_id, title, text, duration_ms, asset_id | None)];
    audio — {слой: asset_id}; oneshot_asset — общее видео для gen_mode=one_shot."""

    state = {
        "revision": 0,
        "project": {"id": project_id, "title": "Проба монтажа", "type": "video", "mode": mode,
                    "status": "active", "order": 1},
        "milestones": {"scenario": "approved", "image_plan": "approved",
                       "image_results": "approved", "motion": "approved", "audio": "approved"},
        "script": {"active_version_id": "s1", "versions": [
            {"version_id": "s1", "parent_version_id": None, "text": "сценарий", "reason": "начало"}]},
        "gen_mode": gen_mode, "history": [], "stage_decisions": [], "references": [],
        "image_prompts": [], "motion_prompts": [], "image_results": [], "video_results": [],
        "audio_layers": [], "audio_prompts": [], "audio_results": [], "applied_action_ids": [],
        "scenes": [],
    }
    cursor = 0
    for order, (scene_id, title, text, duration_ms, asset) in enumerate(scenes, start=1):
        version = f"result:scene:{scene_id}:video-v1"
        linked = bool(asset) and gen_mode == "per_scene"
        state["scenes"].append({
            "scene_id": scene_id, "order": order, "title": title, "duration_ms": duration_ms,
            "start_ms": cursor, "end_ms": cursor + duration_ms,
            "links": {"video_result_id": version} if linked else {},
            "script_block": {"active_version_id": f"b-{scene_id}", "versions": [
                {"version_id": f"b-{scene_id}", "parent_version_id": None, "text": text,
                 "reason": "начало"}]}})
        cursor += duration_ms
        if linked:
            state["video_results"].append({
                "result_id": f"result:scene:{scene_id}:video", "version_id": version,
                "scene_id": scene_id, "parent_version_id": None, "asset_id": asset,
                "status": "ready", "decision": "approved"})
    if gen_mode == "one_shot" and oneshot_asset:
        state["oneshot"] = {"links": {"video_result_id": "result:oneshot-v1"}}
        state["video_results"].append({
            "result_id": "result:oneshot", "version_id": "result:oneshot-v1",
            "parent_version_id": None, "asset_id": oneshot_asset, "status": "ready",
            "decision": "approved"})
    for layer, asset in (audio or {}).items():
        version = f"result:audio:{layer}-v1"
        state["audio_layers"].append({"layer": layer, "links": {"audio_result_id": version}})
        state["audio_results"].append({
            "result_id": f"result:audio:{layer}", "version_id": version, "parent_version_id": None,
            "asset_id": asset, "status": "ready", "decision": "approved"})
    return state
```

`skills/aimaster/scripts/test_montage_draft_plan.py`:

```python
#!/usr/bin/env python3
"""План черновика: порядок сцен, окна сцен, выбранные результаты, звук, титры, переходы."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import video_state  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.draft_plan import plan_draft  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402
from studio.projection import validate_state  # noqa: E402

MEDIA = {
    "asset-a": MediaInfo(2.0, 108, 192, True, True),
    "asset-b": MediaInfo(1.5, 108, 192, True, False),
    "asset-o": MediaInfo(3.0, 108, 192, True, True),
    "asset-v": MediaInfo(5.0, None, None, False, True),
    "asset-m": MediaInfo(60.0, None, None, False, True),
}
SCENES = [("s1", "Сад", "Барсик идёт по саду", 2000, "asset-a"),
          ("s2", "Клубок", "Находит клубок", 2000, "asset-b")]


def by_layer(plan, *layers):
    return [clip for clip in plan.clips if clip.layer in layers]


class DraftPlanTests(unittest.TestCase):
    def test_fixture_is_a_valid_project(self):
        validate_state(video_state(SCENES, audio={"voice": "asset-v"}))

    def test_clips_follow_scene_order_and_windows(self):
        plan = plan_draft(video_state(SCENES), MEDIA.__getitem__)
        videos = by_layer(plan, "video")
        self.assertEqual([(c.clip_id, c.scene_id, c.start, c.duration) for c in videos],
                         [("v-1", "s1", 0.0, 2.0), ("v-2", "s2", 2.0, 1.5)])
        self.assertEqual(plan.duration, 3.5)
        self.assertEqual([c.visual_fade for c in videos], [False, True])
        self.assertEqual((videos[0].volume, videos[0].fade_in, videos[0].fade_out), (1.0, 0.0, 0.4))
        self.assertEqual((videos[1].volume, videos[1].has_audio), (None, False))
        self.assertEqual(plan.first_video_asset(), "asset-a")

    def test_titles_from_active_scene_text(self):
        plan = plan_draft(video_state(SCENES), MEDIA.__getitem__)
        self.assertEqual([(c.clip_id, c.start, c.duration, c.text) for c in by_layer(plan, "titles")],
                         [("t-1", 0.2, 1.6, "Барсик идёт по саду"), ("t-2", 2.2, 1.1, "Находит клубок")])

    def test_audio_layers_and_video_under_them(self):
        plan = plan_draft(video_state(SCENES, audio={"voice": "asset-v", "music": "asset-m"}),
                          MEDIA.__getitem__)
        audio = {clip.layer: clip for clip in by_layer(plan, "voice", "music")}
        self.assertEqual((audio["voice"].clip_id, audio["voice"].volume, audio["voice"].duration),
                         ("a-voice", 1.0, 3.5))
        self.assertEqual((audio["music"].volume, audio["music"].fade_out), (0.3, 1.0))
        self.assertEqual(by_layer(plan, "video")[0].volume, 0.3)
        self.assertEqual(plan.media_assets(), ["asset-a", "asset-b", "asset-v", "asset-m"])

    def test_missing_scene_video_is_named(self):
        state = video_state([SCENES[0], ("s2", "Клубок", "Находит клубок", 2000, None)])
        with self.assertRaises(MontageError) as caught:
            plan_draft(state, MEDIA.__getitem__)
        self.assertIn("Клубок", str(caught.exception))

    def test_photo_project_has_no_montage(self):
        state = video_state(SCENES)
        state["project"]["type"] = "photo"
        with self.assertRaises(MontageError) as caught:
            plan_draft(state, MEDIA.__getitem__)
        self.assertIn("фото", str(caught.exception))

    def test_one_shot_is_one_clip_over_the_story(self):
        state = video_state([("s1", "Сад", "Барсик в саду", 2000, None),
                             ("s2", "Клубок", "Клубок", 2000, None)],
                            gen_mode="one_shot", oneshot_asset="asset-o")
        plan = plan_draft(state, MEDIA.__getitem__)
        self.assertEqual([(c.clip_id, c.scene_id, c.start, c.duration) for c in by_layer(plan, "video")],
                         [("v-1", None, 0.0, 3.0)])
        self.assertEqual([(c.clip_id, c.start, c.duration) for c in by_layer(plan, "titles")],
                         [("t-1", 0.2, 1.6), ("t-2", 2.2, 0.6)])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_draft_plan.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage.draft_plan'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/draft_plan.py`:

```python
"""Проект → план черновика: какие клипы, где, с какой громкостью (чистая функция).

Видео — по порядку сцен, каждый клип в окне своей сцены и не длиннее исходника;
выбранный результат берётся по указателю позиции (`current_member`), а не по
порядку списка. Звук — один текущий файл на слой от начала ролика. Титры —
активная версия текста сцены. Переход — проявление следующего клипа (CSS в
draft_html) и мягкие края его звука (`data-fade-in/out` в HyperFrames — это
громкость, не картинка).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..domain_positions import current_member, position_specs
from . import AUDIO_LAYER_NAMES, MontageError
from .probe import MediaInfo

TRANSITION = 0.4
TITLE_INSET = 0.2
MIN_TITLE = 0.5
DEFAULT_VOLUMES = {"voice": 1.0, "music": 0.3, "fx": 0.8, "atmos": 0.5}
VIDEO_VOLUME = {False: 1.0, True: 0.3}  # без звуковых слоёв / под ними
LAYER_FADE_OUT = {"music": 1.0, "atmos": 1.0}


@dataclass(frozen=True)
class ClipPlan:
    clip_id: str
    layer: str
    start: float
    duration: float
    scene_id: str | None = None
    asset_id: str | None = None
    media_start: float = 0.0
    volume: float | None = None
    fade_in: float = 0.0
    fade_out: float = 0.0
    visual_fade: bool = False
    has_audio: bool = False
    text: str | None = None


@dataclass(frozen=True)
class DraftPlan:
    duration: float
    clips: tuple[ClipPlan, ...]

    def media_assets(self) -> list[str]:
        return list(dict.fromkeys(clip.asset_id for clip in self.clips if clip.asset_id))

    def first_video_asset(self) -> str | None:
        return next((c.asset_id for c in self.clips if c.layer == "video" and c.asset_id), None)


def _ordered(state) -> list[dict]:
    return sorted(state.get("scenes", []), key=lambda scene: scene.get("order", 0))


def scene_ranges(state) -> dict[str, tuple[float, float]]:
    """Окно сцены в секундах; у старых записей без start_ms — по длительностям."""

    ranges, cursor = {}, 0
    for scene in _ordered(state):
        duration = scene.get("duration_ms") or (scene.get("end_ms", 0) - scene.get("start_ms", 0))
        start = scene.get("start_ms", cursor)
        ranges[scene["scene_id"]] = (round(start / 1000, 3), round((start + duration) / 1000, 3))
        cursor = start + duration
    return ranges


def scene_text(scene: dict) -> str:
    block = scene.get("script_block") or {}
    active = next((v for v in block.get("versions", [])
                   if v.get("version_id") == block.get("active_version_id")), {})
    return " ".join(str(active.get("text", "")).split())


def _current_asset(state, spec) -> str | None:
    if spec is None:
        return None
    result = current_member(state, spec, "result", missing_ok=True)
    return result.get("asset_id") if result else None


def video_sources(state, *, strict=True) -> list[tuple[dict | None, str]]:
    """[(сцена или None для one_shot, asset_id)] по порядку сценария."""

    specs = {spec["position_id"]: spec for spec in position_specs(state)}
    if state.get("gen_mode", "per_scene") == "one_shot":
        asset = _current_asset(state, specs.get("pos:oneshot"))
        if asset:
            return [(None, asset)]
        if strict:
            raise MontageError("нет выбранного общего видео (one_shot)")
        return []
    found, missing = [], []
    for scene in _ordered(state):
        asset = _current_asset(state, specs.get(f"pos:scene:{scene['scene_id']}:video"))
        if asset:
            found.append((scene, asset))
        else:
            missing.append(scene.get("title") or scene["scene_id"])
    if strict and (missing or not found):
        raise MontageError("нет выбранного видео у сцен: " + (", ".join(missing) or "сцен нет"))
    return found


def audio_sources(state) -> dict[str, str]:
    specs = {spec["position_id"]: spec for spec in position_specs(state)}
    sources = {}
    for layer in AUDIO_LAYER_NAMES:
        asset = _current_asset(state, specs.get(f"pos:audio:{layer}"))
        if asset:
            sources[layer] = asset
    return sources


def _video_clips(state, videos, media, under_layers) -> list[ClipPlan]:
    ranges = scene_ranges(state)
    story_end = max((end for _start, end in ranges.values()), default=0.0)
    clips = []
    for index, (scene, asset) in enumerate(videos, start=1):
        info = media(asset)
        start, end = ranges[scene["scene_id"]] if scene else (0.0, story_end or info.duration)
        fade = TRANSITION if info.has_audio else 0.0
        clips.append(ClipPlan(
            f"v-{index}", "video", start, round(min(end - start, info.duration), 3),
            scene_id=scene["scene_id"] if scene else None, asset_id=asset,
            volume=VIDEO_VOLUME[under_layers] if info.has_audio else None,
            fade_in=fade if index > 1 else 0.0, fade_out=fade, visual_fade=index > 1,
            has_audio=info.has_audio))
    return clips


def _title_clips(state, total: float) -> list[ClipPlan]:
    ranges = scene_ranges(state)
    clips = []
    for index, scene in enumerate(_ordered(state), start=1):
        text = scene_text(scene)
        start, end = ranges[scene["scene_id"]]
        start, end = start + TITLE_INSET, min(end, total) - TITLE_INSET
        if text and end - start >= MIN_TITLE:
            clips.append(ClipPlan(f"t-{index}", "titles", round(start, 3), round(end - start, 3),
                                  scene_id=scene["scene_id"], text=text))
    return clips


def plan_draft(state: dict, media: Callable[[str], MediaInfo]) -> DraftPlan:
    if (state.get("project") or {}).get("type") == "photo":
        raise MontageError("у фото-проекта монтажа нет: его сборка — принятая картинка")
    audio = audio_sources(state)
    clips = _video_clips(state, video_sources(state), media, bool(audio))
    total = round(max(clip.start + clip.duration for clip in clips), 3)
    clips += _title_clips(state, total)
    for layer, asset in audio.items():
        info = media(asset)
        clips.append(ClipPlan(f"a-{layer}", layer, 0.0, round(min(info.duration, total), 3),
                              asset_id=asset, volume=DEFAULT_VOLUMES[layer],
                              fade_out=LAYER_FADE_OUT.get(layer, 0.0), has_audio=True))
    return DraftPlan(duration=total, clips=tuple(clips))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_draft_plan.py' -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/draft_plan.py skills/aimaster/scripts/montage_testkit.py skills/aimaster/scripts/test_montage_draft_plan.py
git commit -m "feat(montage): draft plan from chosen scene videos, sound layers and scene texts"
```

---

### Task 10: Черновик — HTML композиции и `montage/current/`

**Files:**
- Create: `skills/aimaster/studio/montage/draft_html.py`
- Create: `skills/aimaster/studio/montage/draft.py`
- Test: `skills/aimaster/scripts/test_montage_draft.py`

**Interfaces:**
- Consumes: `draft_plan.plan_draft/video_sources/audio_sources/TRANSITION/ClipPlan/DraftPlan`; `canvas.canvas_for/Canvas`; `media_sync.sync_media`; `html_doc.element_attrs/set_attr/fmt_number`; `paths.MontagePaths`; `probe.probe_media/MediaInfo`; `platform_compat.replace_file`; `TRACK_OF_LAYER`.
- Produces:
  - `draft_html.render_draft_html(plan: DraftPlan, canvas: Canvas, sources: Mapping[str, str]) -> str`.
  - `draft.HYPERFRAMES_CONFIG = {"media": {"autoProxy": True}}`.
  - `@dataclass(frozen=True) draft.DraftResult(canvas: Canvas, duration: float, clips: int, media: dict)`.
  - `draft.write_text_atomic(path: Path, text: str) -> None`.
  - `draft.build_current(paths, state, resolve: Callable[[str], Path], *, probe=probe_media) -> DraftResult`; `draft.create_draft(...) -> DraftResult` (отказ, если `index.html` уже есть); `draft.rebuild_draft(paths, state, resolve, *, probe=probe_media) -> tuple[DraftResult, Path | None]` (прежний `current/index.html` — в `.undo/before-rebuild-*.html`, путь вторым элементом).
  - `draft.stale_clips(html_text, state) -> list[{"clip", "layer", "scene_id", "asset_id", "current_asset_id"}]`; `draft.refresh_draft(paths, state, resolve, *, probe=probe_media) -> list[dict]`.
  - Разметка черновика: атрибуты `data-am-layer`, `data-am-scene`, `data-am-asset`; классы `am-video`, `am-fade-in`, `am-title`.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_draft.py`:

```python
#!/usr/bin/env python3
"""Черновик: эталонная разметка, без GSAP и внешних ссылок; обновление только устаревших клипов."""

from __future__ import annotations

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

from montage_testkit import video_state  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.draft import create_draft, rebuild_draft, refresh_draft, stale_clips  # noqa: E402
from studio.montage.html_doc import element_attrs  # noqa: E402
from studio.montage.media_sync import external_references, missing_sources  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402

SCENES = [("s1", "Сад", "Барсик идёт по саду", 2000, "asset-a"),
          ("s2", "Клубок", "Находит клубок", 2000, "asset-b")]
ROOT = ('<div id="root" data-composition-id="main" data-start="0" data-duration="3.5" '
        'data-width="108" data-height="192" data-no-timeline>')
V1 = ('<video id="v-1" class="am-video" src="assets/asset-a.mp4" data-media-start="0" '
      'data-start="0" data-duration="2" data-track-index="0" data-am-layer="video" '
      'data-am-scene="s1" data-am-asset="asset-a" data-has-audio="true" data-volume="0.3" '
      'data-fade-out="0.4" playsinline></video>')
V2 = ('<video id="v-2" class="am-video am-fade-in" src="assets/asset-b.mp4" data-media-start="0" '
      'data-start="2" data-duration="1.5" data-track-index="0" data-am-layer="video" '
      'data-am-scene="s2" data-am-asset="asset-b" muted playsinline></video>')
T1 = ('<div id="t-1" class="clip am-title" data-start="0.2" data-duration="1.6" '
      'data-track-index="1" data-am-layer="titles" data-am-scene="s1"><span>Барсик идёт по саду</span></div>')
VOICE = ('<audio id="a-voice" src="assets/asset-v.wav" data-media-start="0" data-start="0" '
         'data-duration="3.5" data-track-index="2" data-am-layer="voice" data-am-asset="asset-v" '
         'data-volume="1"></audio>')


class DraftTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        self.media = base / "media"
        self.media.mkdir()
        self.infos = {"asset-a": MediaInfo(2.0, 108, 192, True, True),
                      "asset-b": MediaInfo(1.5, 108, 192, True, False),
                      "asset-c": MediaInfo(1.0, 108, 192, True, True),
                      "asset-v": MediaInfo(5.0, None, None, False, True)}
        for asset in self.infos:
            suffix = ".wav" if asset == "asset-v" else ".mp4"
            (self.media / f"{asset}{suffix}").write_bytes(asset.encode())
        self.paths = montage_paths(base / "projects" / "p")

    def resolve(self, asset):
        return next(self.media.glob(f"{asset}.*"))

    def probe(self, path):
        return self.infos[Path(path).stem]

    def draft(self, state):
        return create_draft(self.paths, state, self.resolve, probe=self.probe)

    def test_draft_is_the_reference_composition(self):
        result = self.draft(video_state(SCENES, audio={"voice": "asset-v"}))
        text = self.paths.index.read_text(encoding="utf-8")
        self.assertEqual((result.canvas, result.duration, result.clips), (Canvas(108, 192), 3.5, 5))
        for line in (ROOT, V1, V2, T1, VOICE):
            self.assertIn(line, text)
        self.assertNotIn("gsap", text.lower())
        self.assertNotIn("<script", text)
        self.assertIn("font-family: sans-serif", text)
        self.assertEqual(external_references(text), [])
        self.assertEqual(missing_sources(text, self.paths.current), [])
        config = json.loads((self.paths.current / "hyperframes.json").read_text(encoding="utf-8"))
        self.assertEqual(config, {"media": {"autoProxy": True}})

    def test_second_draft_is_refused(self):
        self.draft(video_state(SCENES))
        with self.assertRaises(MontageError) as caught:
            self.draft(video_state(SCENES))
        self.assertIn("--refresh", str(caught.exception))

    def test_refresh_replaces_only_the_stale_clip(self):
        self.draft(video_state(SCENES))
        before = element_attrs(self.paths.index.read_text(encoding="utf-8"))
        newer = video_state([SCENES[0], ("s2", "Клубок", "Находит клубок", 2000, "asset-c")])
        stale = refresh_draft(self.paths, newer, self.resolve, probe=self.probe)
        self.assertEqual([item["clip"] for item in stale], ["v-2"])
        after = element_attrs(self.paths.index.read_text(encoding="utf-8"))
        self.assertEqual((after["v-2"]["src"], after["v-2"]["data-am-asset"], after["v-2"]["data-duration"]),
                         ("assets/asset-c.mp4", "asset-c", "1"))
        self.assertEqual(after["v-1"], before["v-1"])
        self.assertEqual(stale_clips(self.paths.index.read_text(encoding="utf-8"), newer), [])

    def test_rebuild_keeps_the_old_draft_in_undo(self):
        self.draft(video_state(SCENES))
        original = self.paths.index.read_text(encoding="utf-8")
        self.paths.index.write_text(original + "<!-- правка в столе -->", encoding="utf-8")
        result, backup = rebuild_draft(self.paths, video_state(SCENES), self.resolve, probe=self.probe)
        self.assertEqual(result.clips, 4)
        self.assertEqual(self.paths.index.read_text(encoding="utf-8"), original)
        self.assertEqual(backup.parent, self.paths.undo)
        self.assertTrue(backup.read_text(encoding="utf-8").endswith("<!-- правка в столе -->"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_draft.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage.draft'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/draft_html.py`:

```python
"""План черновика → index.html композиции HyperFrames.

Без GSAP и внешних ссылок. Корень помечен data-no-timeline: без таймлайна
рантайм иначе ждёт его 45 с на каждом рендере. Переход между клипами —
CSS-анимация проявления, которую рантайм HyperFrames перематывает покадрово
(проба 0.8.75: яркость кадров 17 → 49 → 93). Шрифт титров — системный
sans-serif: такие семейства HyperFrames не тянет с Google Fonts.
"""

from __future__ import annotations

import html
from typing import Mapping

from . import TRACK_OF_LAYER
from .canvas import Canvas
from .draft_plan import TRANSITION, ClipPlan, DraftPlan
from .html_doc import fmt_number as fmt

_STYLE = """      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {w}px; height: {h}px; overflow: hidden; background: #000; }}
      #root {{ position: relative; width: {w}px; height: {h}px; overflow: hidden; background: #000; }}
      .am-video {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; z-index: 1; }}
      .am-fade-in {{ animation: am-fade-in {t}s linear both; }}
      @keyframes am-fade-in {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
      .am-title {{ position: absolute; left: {pad}px; right: {pad}px; bottom: {bottom}px; z-index: 5;
        display: flex; justify-content: center; text-align: center; font-family: sans-serif; }}
      .am-title span {{ background: rgba(0, 0, 0, 0.6); color: #fff; font-size: {font}px;
        font-weight: 700; line-height: 1.25; padding: {vpad}px {hpad}px; border-radius: {radius}px; }}"""


def _attrs(pairs) -> str:
    parts = []
    for name, value in pairs:
        if value is None or value is False:
            continue
        parts.append(name if value is True else f'{name}="{html.escape(str(value), quote=True)}"')
    return " ".join(parts)


def _common(clip: ClipPlan, layer: str) -> list:
    return [("data-start", fmt(clip.start)), ("data-duration", fmt(clip.duration)),
            ("data-track-index", TRACK_OF_LAYER[layer]), ("data-am-layer", layer),
            ("data-am-scene", clip.scene_id), ("data-am-asset", clip.asset_id)]


def _sound(clip: ClipPlan) -> list:
    return [("data-volume", fmt(clip.volume if clip.volume is not None else 1)),
            ("data-fade-in", fmt(clip.fade_in) if clip.fade_in else None),
            ("data-fade-out", fmt(clip.fade_out) if clip.fade_out else None)]


def _element(clip: ClipPlan, sources: Mapping[str, str]) -> str:
    if clip.layer == "titles":
        pairs = [("id", clip.clip_id), ("class", "clip am-title")] + _common(clip, "titles")
        return f"<div {_attrs(pairs)}><span>{html.escape(clip.text or '', quote=False)}</span></div>"
    media = [("src", sources[clip.asset_id]), ("data-media-start", fmt(clip.media_start))]
    if clip.layer == "video":
        classes = "am-video am-fade-in" if clip.visual_fade else "am-video"
        pairs = [("id", clip.clip_id), ("class", classes)] + media + _common(clip, "video")
        pairs += ([("data-has-audio", "true")] + _sound(clip)) if clip.has_audio else [("muted", True)]
        return f"<video {_attrs(pairs + [('playsinline', True)])}></video>"
    pairs = [("id", clip.clip_id)] + media + _common(clip, clip.layer) + _sound(clip)
    return f"<audio {_attrs(pairs)}></audio>"


def render_draft_html(plan: DraftPlan, canvas: Canvas, sources: Mapping[str, str]) -> str:
    scale = canvas.width / 1080
    style = _STYLE.format(w=canvas.width, h=canvas.height, t=fmt(TRANSITION),
                          pad=round(60 * scale), bottom=round(canvas.height * 0.12),
                          font=max(24, round(64 * scale)), vpad=round(16 * scale),
                          hpad=round(32 * scale), radius=round(16 * scale))
    root = _attrs([("id", "root"), ("data-composition-id", "main"), ("data-start", "0"),
                   ("data-duration", fmt(plan.duration)), ("data-width", canvas.width),
                   ("data-height", canvas.height), ("data-no-timeline", True)])
    body = ["      " + _element(clip, sources) for clip in plan.clips]
    return "\n".join([
        "<!doctype html>", '<html lang="ru">', "  <head>", '    <meta charset="UTF-8" />',
        f'    <meta name="viewport" content="width={canvas.width}, height={canvas.height}" />',
        "    <style>", style, "    </style>", "  </head>", "  <body>", f"    <div {root}>",
        *body, "    </div>", "  </body>", "</html>", ""])
```

`skills/aimaster/studio/montage/draft.py`:

```python
"""Черновой монтаж в <проект>/montage/current: создать, обновить устаревшие клипы, пересобрать."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..platform_compat import replace_file
from . import MontageError
from .canvas import Canvas, canvas_for
from .draft_html import render_draft_html
from .draft_plan import audio_sources, plan_draft, video_sources
from .html_doc import element_attrs, fmt_number, set_attr
from .media_sync import sync_media
from .paths import MontagePaths
from .probe import MediaInfo, probe_media

HYPERFRAMES_CONFIG = {"media": {"autoProxy": True}}


@dataclass(frozen=True)
class DraftResult:
    canvas: Canvas
    duration: float
    clips: int
    media: dict


def write_text_atomic(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    replace_file(temporary, path)


def _prober(resolve, probe):
    cache: dict[str, MediaInfo] = {}

    def media(asset_id: str) -> MediaInfo:
        if asset_id not in cache:
            cache[asset_id] = probe(resolve(asset_id))
        return cache[asset_id]
    return media


def build_current(paths: MontagePaths, state: dict, resolve: Callable[[str], Path], *,
                  probe=probe_media) -> DraftResult:
    media = _prober(resolve, probe)
    plan = plan_draft(state, media)
    first = plan.first_video_asset()
    canvas = canvas_for(media(first) if first else None)
    synced = sync_media(((asset, resolve(asset)) for asset in plan.media_assets()), paths.assets)
    sources = {asset: item["src"] for asset, item in synced.items()}
    write_text_atomic(paths.current / "hyperframes.json",
                      json.dumps(HYPERFRAMES_CONFIG, indent=2) + "\n")
    write_text_atomic(paths.index, render_draft_html(plan, canvas, sources))
    return DraftResult(canvas, plan.duration, len(plan.clips), synced)


def create_draft(paths, state, resolve, *, probe=probe_media) -> DraftResult:
    if paths.index.exists():
        raise MontageError("черновик уже есть: montage draft --refresh заменит устаревшие клипы, "
                           "--rebuild соберёт его заново")
    return build_current(paths, state, resolve, probe=probe)


def rebuild_draft(paths, state, resolve, *, probe=probe_media) -> tuple[DraftResult, Path | None]:
    """Черновик заново из проекта. Прежний current/index.html (с правками из стола)
    не теряется: он уходит в .undo/before-rebuild-*.html, путь — вторым элементом."""

    backup = None
    if paths.index.is_file():
        paths.undo.mkdir(parents=True, exist_ok=True)
        backup = paths.undo / (f"before-rebuild-{time.strftime('%Y%m%d-%H%M%S')}"
                               f"-{time.time_ns() % 1_000_000_000:09d}.html")
        shutil.copy2(paths.index, backup)
    return build_current(paths, state, resolve, probe=probe), backup


def stale_clips(html_text: str, state: dict) -> list[dict]:
    """Клипы, чей исходник уже не выбранный результат своей сцены или слоя."""

    wanted = {("video", scene["scene_id"] if scene else None): asset
              for scene, asset in video_sources(state, strict=False)}
    wanted.update({(layer, None): asset for layer, asset in audio_sources(state).items()})
    stale = []
    for clip_id, attrs in element_attrs(html_text).items():
        layer, asset = attrs.get("data-am-layer"), attrs.get("data-am-asset")
        if not layer or not asset:
            continue
        scene = attrs.get("data-am-scene") or None
        current = wanted.get((layer, scene if layer == "video" else None))
        if current and current != asset:
            stale.append({"clip": clip_id, "layer": layer, "scene_id": scene, "asset_id": asset,
                          "current_asset_id": current})
    return stale


def refresh_draft(paths, state, resolve, *, probe=probe_media) -> list[dict]:
    """Меняет исходник только у устаревших клипов. Место на дорожке не трогает;
    если новый исходник короче — укорачивает клип до его длины."""

    if not paths.index.exists():
        raise MontageError("черновика ещё нет: сначала montage draft")
    text = paths.index.read_text(encoding="utf-8")
    stale = stale_clips(text, state)
    if not stale:
        return []
    synced = sync_media(((item["current_asset_id"], resolve(item["current_asset_id"]))
                         for item in stale), paths.assets)
    for item in stale:
        clip, asset = item["clip"], item["current_asset_id"]
        info = probe(resolve(asset))
        attrs = element_attrs(text)[clip]
        media_start = float(attrs.get("data-media-start") or 0)
        if media_start >= info.duration:
            media_start = 0.0
            text = set_attr(text, clip, "data-media-start", "0")
        text = set_attr(text, clip, "src", synced[asset]["src"])
        text = set_attr(text, clip, "data-am-asset", asset)
        if float(attrs.get("data-duration") or 0) > info.duration - media_start:
            text = set_attr(text, clip, "data-duration", fmt_number(info.duration - media_start))
    write_text_atomic(paths.index, text)
    return stale
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_draft.py' -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/draft_html.py skills/aimaster/studio/montage/draft.py skills/aimaster/scripts/test_montage_draft.py
git commit -m "feat(montage): GSAP-free offline draft composition with refresh of stale clips"
```

---
### Task 11: Модель монтажа и смысловой diff по-русски

**Files:**
- Create: `skills/aimaster/studio/montage/model.py`
- Create: `skills/aimaster/studio/montage/model_diff.py`
- Modify: `skills/aimaster/scripts/montage_testkit.py` (добавить `timeline_from_html`, `fake_engine`, `FakeHyperframes`)
- Test: `skills/aimaster/scripts/test_montage_model.py`

**Interfaces:**
- Consumes: `engine.Engine`; `engine_cli.EngineRunner`, `engine_cli.EngineResult`; `html_doc.element_attrs/element_span/set_attr/root_duration/fmt_number`; `LAYERS`, `LAYER_LABELS`, `MontageError`.
- Produces:
  - `@dataclass(frozen=True) model.Clip(id, layer, kind, start, duration, media_start=0.0, volume=None, fade_in=0.0, fade_out=0.0, scene_id=None, asset_id=None, src=None, text=None)` со свойством `end`.
  - `@dataclass(frozen=True) model.Model(duration: float, clips: tuple[Clip, ...])` с `to_dict()`, `Model.from_dict(data)`, `clip(clip_id) -> Clip` (иначе `MontageError`).
  - `model.build_model(timeline: dict, html_text: str) -> Model`; `model.model_hash(model) -> str` (16 hex); `model.read_model(engine, current_dir: Path, *, cache_dir: Path | None = None, runner=None) -> Model`; `model.layers_view(model) -> list[{"layer", "label", "clips": [{"id", "kind", "start", "duration", "media_start", "volume", "scene_id", "asset_id", "text"}]}]` (порядок `LAYERS`, все шесть дорожек всегда).
  - `model_diff.fmt_time(seconds) -> "м:сс.д"`, `model_diff.fmt_len(seconds) -> "3,5 с"`, `model_diff.clip_name(clip, names) -> str`, `model_diff.diff_models(old: Model | None, new: Model, *, names: Mapping[str, str] | None = None) -> list[str]`.
  - `montage_testkit.timeline_from_html(html_text) -> dict` (форма вывода `timeline --json` 0.8.75), `montage_testkit.fake_engine(prefix) -> Engine`, `class montage_testkit.FakeHyperframes(*, lint_report=None, render_bytes=None, render_log="[INFO] done", refuse=None)` — методы `json(...)`, `run(...)` как у `EngineRunner`, список `calls`, словарь `refuse` (`{"move": "причина"}`).

- [ ] **Step 1: Write the failing test**

В `skills/aimaster/scripts/montage_testkit.py` — в импорты добавить:

```python
from studio.montage import MontageError  # noqa: E402
from studio.montage.engine import Engine  # noqa: E402
from studio.montage.engine_cli import EngineResult  # noqa: E402
from studio.montage.html_doc import (  # noqa: E402
    element_attrs, element_span, fmt_number, root_duration, set_attr)
```

и в конец файла:

```python
def fake_engine(prefix: Path) -> Engine:
    return Engine(node="node", script=Path(prefix) / "hyperframes.mjs", prefix=Path(prefix),
                  version="0.8.75", browser=None)


def timeline_from_html(html_text: str) -> dict:
    """Вывод `hyperframes timeline --json` 0.8.75 для нашей разметки (поля, что читает model.py)."""

    attrs = element_attrs(html_text)
    tracks: dict[str, list] = {}
    for element_id, data in attrs.items():
        if element_id == "root" or "data-start" not in data:
            continue
        tag = data["_tag"]
        kind = tag if tag in ("video", "audio", "img") else "div"
        track = {"video": "video", "img": "video", "audio": "audio"}.get(kind, "graphics")
        start, duration = float(data["data-start"]), float(data.get("data-duration") or 0)
        tracks.setdefault(track, []).append({
            "id": element_id, "elementId": element_id, "kind": kind, "trackKind": track,
            "start": start, "duration": duration, "end": round(start + duration, 3),
            "src": data.get("src"),
            "volume": float(data["data-volume"]) if "data-volume" in data else None,
            "trackIndex": int(data.get("data-track-index") or 0), "hfId": data.get("data-hf-id")})
    return {"timeline": {"duration": float(attrs["root"]["data-duration"]),
                         "tracks": [{"kind": kind, "rows": rows} for kind, rows in tracks.items()]},
            "_meta": {"version": "0.8.75"}}


def _opt(args, name):
    return args[args.index(name) + 1] if name in args else None


class FakeHyperframes:
    """Подмена EngineRunner: ведёт себя как CLI HyperFrames 0.8.75 на наших композициях
    (проба: move не выходит за корень; trim не трогает data-media-start; split ставит
    data-media-start новой части и зовёт её <id>-2; set volume=; delete; lint; render)."""

    def __init__(self, *, lint_report=None, render_bytes=None, render_log="[INFO] done", refuse=None):
        self.calls: list[list[str]] = []
        self.lint_report = lint_report or {"ok": True, "errorCount": 0, "findings": []}
        self.render_bytes = render_bytes
        self.render_log = render_log
        self.refuse = dict(refuse or {})

    def json(self, engine, args, *, cwd, timeout, ok_codes=(0,)):
        args = [str(item) for item in args]
        self.calls.append(args)
        index = Path(cwd) / "index.html"
        if args[0] == "lint":
            return dict(self.lint_report)
        if args == ["timeline", "--json"]:
            return timeline_from_html(index.read_text(encoding="utf-8"))
        if args[0] == "timeline":
            return self._mutate(index, args[1:])
        raise AssertionError(f"неожиданная команда {args}")

    def run(self, engine, args, *, cwd, timeout):
        args = [str(item) for item in args]
        self.calls.append(args)
        if args[0] != "render":
            raise AssertionError(f"неожиданная команда {args}")
        if self.render_bytes is None:
            return EngineResult(1, "", "render failed: browser crashed")
        Path(_opt(args, "--output")).write_bytes(self.render_bytes)
        return EngineResult(0, self.render_log, "")

    def _mutate(self, index: Path, args: list[str]) -> dict:
        op, ref = args[0], args[1].lstrip("#")
        if op in self.refuse:
            raise MontageError(f"HyperFrames отказал: {self.refuse[op]}")
        text = index.read_text(encoding="utf-8")
        data = element_attrs(text)[ref]
        start, duration = float(data["data-start"]), float(data.get("data-duration") or 0)
        if op == "move":
            root, at = root_duration(text), float(args[2])
            if at + duration > root + 1e-6:
                raise MontageError(f"HyperFrames отказал: move would end at {at + duration}, "
                                   f"beyond composition duration {root}")
            text = set_attr(text, ref, "data-start", args[2])
        elif op == "trim":
            for flag, attr in (("--start", "data-start"), ("--duration", "data-duration")):
                if _opt(args, flag) is not None:
                    text = set_attr(text, ref, attr, _opt(args, flag))
        elif op == "split":
            at = float(args[2])
            first = round(at - start, 3)
            media = float(data.get("data-media-start") or 0)
            begin, end = element_span(text, ref)
            piece = text[begin:end]
            for attr, value in (("data-start", fmt_number(at)),
                                ("data-duration", fmt_number(duration - first)),
                                ("data-media-start", fmt_number(media + first)), ("id", f"{ref}-2")):
                piece = set_attr(piece, ref, attr, value)
            text = set_attr(text, ref, "data-duration", fmt_number(first))
            _begin, end = element_span(text, ref)
            text = text[:end] + piece + text[end:]
        elif op == "delete":
            begin, end = element_span(text, ref)
            text = text[:begin] + text[end:]
        elif op == "set":
            field, value = args[2].split("=", 1)
            text = set_attr(text, ref, f"data-{field}", value)
        else:
            raise AssertionError(f"неожиданная правка {op}")
        index.write_text(text, encoding="utf-8")
        return {"ok": True, "receipt": {"file": "index.html", "changed": True}, "file": "index.html"}
```

`skills/aimaster/scripts/test_montage_model.py`:

```python
#!/usr/bin/env python3
"""Модель монтажа из timeline --json + наших пометок; хэш не видит правок Studio; diff по-русски."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import FakeHyperframes, fake_engine, timeline_from_html, video_state  # noqa: E402
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.draft_html import render_draft_html  # noqa: E402
from studio.montage.draft_plan import plan_draft  # noqa: E402
from studio.montage.html_doc import element_span, insert_before_root_end, set_attr, set_text  # noqa: E402
from studio.montage.model import Model, build_model, layers_view, model_hash, read_model  # noqa: E402
from studio.montage.model_diff import diff_models, fmt_len, fmt_time  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402

MEDIA = {"asset-a": MediaInfo(2.0, 108, 192, True, True),
         "asset-b": MediaInfo(1.5, 108, 192, True, False),
         "asset-v": MediaInfo(5.0, None, None, False, True)}
SOURCES = {"asset-a": "assets/asset-a.mp4", "asset-b": "assets/asset-b.mp4",
           "asset-v": "assets/asset-v.wav"}
SCENES = [("s1", "Сад", "Барсик идёт по саду", 2000, "asset-a"),
          ("s2", "Клубок", "Находит клубок", 2000, "asset-b")]
NAMES = {"s1": "сцены 1 «Сад»", "s2": "сцены 2 «Клубок»"}


def draft_html() -> str:
    plan = plan_draft(video_state(SCENES, audio={"voice": "asset-v"}), MEDIA.__getitem__)
    return render_draft_html(plan, Canvas(108, 192), SOURCES)


def model_of(text: str) -> Model:
    return build_model(timeline_from_html(text), text)


class ModelTests(unittest.TestCase):
    def test_build_reads_layers_scenes_and_media_start(self):
        model = model_of(draft_html())
        self.assertEqual(model.duration, 3.5)
        self.assertEqual([c.id for c in model.clips], ["v-1", "v-2", "t-1", "t-2", "a-voice"])
        clip = model.clip("v-1")
        self.assertEqual((clip.layer, clip.scene_id, clip.asset_id, clip.fade_out), ("video", "s1", "asset-a", 0.4))
        self.assertEqual(model.clip("t-1").text, "Барсик идёт по саду")
        self.assertEqual(model.clip("a-voice").layer, "voice")

    def test_hash_ignores_studio_ids_rows_and_doctype(self):
        text = draft_html()
        studio = set_attr(set_attr(text, "a-voice", "data-hf-id", "hf-y1f4"), "a-voice", "data-track-index", "0")
        studio = studio.replace("<!doctype html>", "<!DOCTYPE html>")
        self.assertEqual(model_hash(model_of(text)), model_hash(model_of(studio)))
        self.assertNotEqual(model_hash(model_of(text)), model_hash(model_of(set_attr(text, "v-2", "data-start", "2.5"))))

    def test_unmarked_clip_falls_back_by_kind(self):
        text = draft_html().replace(' data-am-layer="voice"', "")
        self.assertEqual(model_of(text).clip("a-voice").layer, "music")

    def test_layers_view_has_all_six_tracks_in_order(self):
        view = layers_view(model_of(draft_html()))
        self.assertEqual([item["layer"] for item in view], ["video", "titles", "voice", "music", "fx", "atmos"])
        self.assertEqual(view[0]["label"], "Видео")
        self.assertEqual([clip["id"] for clip in view[0]["clips"]], ["v-1", "v-2"])
        self.assertEqual(view[3]["clips"], [])

    def test_round_trip_and_cache(self):
        model = model_of(draft_html())
        self.assertEqual(Model.from_dict(model.to_dict()), model)
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "current").mkdir()
            (base / "current" / "index.html").write_text(draft_html(), encoding="utf-8")
            runner = FakeHyperframes()
            first = read_model(fake_engine(base), base / "current", cache_dir=base / ".cache", runner=runner)
            second = read_model(fake_engine(base), base / "current", cache_dir=base / ".cache", runner=runner)
        self.assertEqual(first, second)
        self.assertEqual(runner.calls, [["timeline", "--json"]])


class DiffTests(unittest.TestCase):
    def setUp(self):
        self.text = draft_html()
        self.old = model_of(self.text)

    def diff(self, text):
        return diff_models(self.old, model_of(text), names=NAMES)

    def test_formats(self):
        self.assertEqual((fmt_time(65.3), fmt_len(3.5)), ("1:05.3", "3,5 с"))

    def test_first_version(self):
        self.assertEqual(diff_models(None, self.old), ["черновой монтаж: 5 клипов, 3,5 с"])

    def test_trim_head_is_one_line(self):
        text = self.text
        for attr, value in (("data-start", "0.5"), ("data-duration", "1.5"), ("data-media-start", "0.5")):
            text = set_attr(text, "v-1", attr, value)
        self.assertEqual(self.diff(text), ["клип сцены 1 «Сад»: начало обрезано на 0,5 с"])

    def test_move_and_longer_video(self):
        text = set_attr(set_attr(self.text, "v-2", "data-start", "2.5"), "root", "data-duration", "4")
        self.assertEqual(self.diff(text), ["длина ролика 3,5 с → 4,0 с",
                                           "клип сцены 2 «Клубок»: сдвинут 0:02.0 → 0:02.5"])

    def test_split_is_reported_once(self):
        with tempfile.TemporaryDirectory() as temp:
            index = Path(temp) / "index.html"
            index.write_text(self.text, encoding="utf-8")
            FakeHyperframes().json(None, ["timeline", "split", "#v-1", "1", "--dir", ".", "--json"],
                                   cwd=Path(temp), timeout=1)
            text = index.read_text(encoding="utf-8")
        self.assertEqual(self.diff(text), ["клип сцены 1 «Сад»: разрезан на 0:01.0"])

    def test_sound_and_titles(self):
        text = set_attr(self.text, "a-voice", "data-volume", "0.5")
        text = set_attr(text, "a-voice", "data-fade-in", "0.5")
        text = set_text(text, "t-1", "Кот")
        self.assertEqual(self.diff(text), [
            "титр «Кот»: текст «Барсик идёт по саду» → «Кот»",
            "звук «Голос» (a-voice): громкость 100% → 50%",
            "звук «Голос» (a-voice): плавное появление звука 0,5 с"])

    def test_added_and_removed(self):
        begin, end = element_span(self.text, "t-2")
        text = self.text[:begin] + self.text[end:]
        text = insert_before_root_end(text, '<div id="t-3" class="clip am-title" data-start="1" '
                                            'data-duration="1" data-am-layer="titles"><span>Новый</span></div>')
        self.assertEqual(self.diff(text), ["добавлен титр «Новый» с 0:01.0", "удалён титр «Находит клубок»"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_model.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage.model'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/model.py`:

```python
"""Нейтральная модель монтажа: время клипов — из `timeline --json`, наши пометки
(слой, сцена, ассет, кусок исходника, края звука, текст титра) — из index.html:
строки `timeline --json` 0.8.75 не содержат `data-media-start`.

В модель не входят `data-hf-id` и номер строки Studio (`data-track-index`,
Studio меняет его при перетаскивании): поэтому нормализация разметки при
открытии стола не делает монтаж «изменённым». Такая модель — основа схемы
слоёв дашборда (план Б) и будущего своего стола (вариант 2).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import LAYER_LABELS, LAYERS, MontageError
from .engine import Engine
from .engine_cli import EngineRunner
from .html_doc import element_attrs

CLI_TIMEOUT = 120
_FALLBACK_LAYER = {"video": "video", "img": "video", "image": "video", "audio": "music"}


@dataclass(frozen=True)
class Clip:
    id: str
    layer: str
    kind: str
    start: float
    duration: float
    media_start: float = 0.0
    volume: float | None = None
    fade_in: float = 0.0
    fade_out: float = 0.0
    scene_id: str | None = None
    asset_id: str | None = None
    src: str | None = None
    text: str | None = None

    @property
    def end(self) -> float:
        return round(self.start + self.duration, 3)


@dataclass(frozen=True)
class Model:
    duration: float
    clips: tuple[Clip, ...]

    def to_dict(self) -> dict:
        return {"duration": self.duration, "clips": [asdict(clip) for clip in self.clips]}

    @classmethod
    def from_dict(cls, data: dict) -> "Model":
        return cls(float(data["duration"]), tuple(Clip(**clip) for clip in data.get("clips", [])))

    def clip(self, clip_id: str) -> Clip:
        for clip in self.clips:
            if clip.id == clip_id:
                return clip
        raise MontageError(f"в монтаже нет клипа {clip_id}")


def _num(value, default=0.0) -> float:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return default


def _rows(timeline: dict):
    for track in (timeline.get("timeline") or {}).get("tracks", []):
        yield from track.get("rows", [])


def build_model(timeline: dict, html_text: str) -> Model:
    attrs = element_attrs(html_text)
    clips = []
    for row in _rows(timeline):
        element_id = row.get("elementId") or row.get("id")
        mark = attrs.get(element_id, {})
        kind = str(row.get("kind") or mark.get("_tag") or "")
        layer = mark.get("data-am-layer")
        if layer not in LAYERS:
            layer = _FALLBACK_LAYER.get(kind, "titles")
        volume = row.get("volume")
        clips.append(Clip(
            id=element_id, layer=layer, kind=kind,
            start=_num(row.get("start")), duration=_num(row.get("duration")),
            media_start=_num(mark.get("data-media-start") or mark.get("data-playback-start")),
            volume=None if volume is None else _num(volume),
            fade_in=_num(mark.get("data-fade-in")), fade_out=_num(mark.get("data-fade-out")),
            scene_id=mark.get("data-am-scene") or None, asset_id=mark.get("data-am-asset") or None,
            src=row.get("src"), text=(mark.get("_text") or None) if layer == "titles" else None))
    order = {layer: index for index, layer in enumerate(LAYERS)}
    clips.sort(key=lambda clip: (order[clip.layer], clip.start, clip.id))
    return Model(_num((timeline.get("timeline") or {}).get("duration")), tuple(clips))


def model_hash(model: Model) -> str:
    canonical = json.dumps(model.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def read_model(engine: Engine, current_dir: Path, *, cache_dir: Path | None = None,
               runner=None) -> Model:
    """Модель текущего монтажа; кэш — по содержимому index.html и версии движка."""

    runner = runner or EngineRunner()
    html_text = (Path(current_dir) / "index.html").read_text(encoding="utf-8")
    key = hashlib.sha256(f"{engine.version}\0{html_text}".encode("utf-8")).hexdigest()[:24]
    cached = Path(cache_dir) / f"model-{key}.json" if cache_dir else None
    if cached is not None and cached.is_file():
        try:
            return Model.from_dict(json.loads(cached.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, KeyError):
            pass
    timeline = runner.json(engine, ["timeline", "--json"], cwd=Path(current_dir), timeout=CLI_TIMEOUT)
    model = build_model(timeline, html_text)
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(model.to_dict(), ensure_ascii=False), encoding="utf-8")
    return model


def layers_view(model: Model) -> list[dict]:
    """Схема слоёв для экрана «Сборка»: все шесть дорожек в постоянном порядке."""

    keys = ("id", "kind", "start", "duration", "media_start", "volume", "scene_id", "asset_id", "text")
    return [{"layer": layer, "label": LAYER_LABELS[layer],
             "clips": [{key: getattr(clip, key) for key in keys}
                       for clip in model.clips if clip.layer == layer]}
            for layer in LAYERS]
```

`skills/aimaster/studio/montage/model_diff.py`:

```python
"""Смысловой diff двух моделей монтажа: строки по-русски, чтобы агент пересказал
человеку, что поменялось с прошлой сборки. Обрезка начала (сдвиг начала вместе с
куском исходника) — одна строка, разрез — одна строка, без «укорочен/добавлен»."""

from __future__ import annotations

from typing import Mapping

from . import LAYER_LABELS
from .model import Clip, Model

EPS = 0.01


def fmt_time(seconds: float) -> str:
    minutes, rest = divmod(max(0.0, float(seconds)), 60)
    return f"{int(minutes)}:{rest:04.1f}"


def fmt_len(seconds: float) -> str:
    return f"{float(seconds):.1f}".replace(".", ",") + " с"


def clip_name(clip: Clip, names: Mapping[str, str]) -> str:
    if clip.layer == "titles":
        return f"титр «{clip.text or clip.id}»"
    if clip.layer == "video":
        scene = names.get(clip.scene_id) if clip.scene_id else None
        return f"клип {scene}" if scene else f"клип {clip.id}"
    return f"звук «{LAYER_LABELS[clip.layer]}» ({clip.id})"


def _timing(old: Clip, new: Clip, name: str, split_parent: bool) -> list[str]:
    shift, head = new.start - old.start, new.media_start - old.media_start
    if abs(shift) > EPS and abs(head) > EPS and abs(shift - head) <= EPS:
        verb = "обрезано" if head > 0 else "возвращено"
        return [f"{name}: начало {verb} на {fmt_len(abs(head))}"]
    out = []
    if abs(shift) > EPS:
        out.append(f"{name}: сдвинут {fmt_time(old.start)} → {fmt_time(new.start)}")
    if abs(head) > EPS:
        out.append(f"{name}: из исходника берётся кусок с {fmt_time(new.media_start)}")
    if abs(new.duration - old.duration) > EPS and not split_parent:
        verb = "укорочен" if new.duration < old.duration else "удлинён"
        out.append(f"{name}: {verb} до {fmt_len(new.duration)}")
    return out


def _changed(old: Clip, new: Clip, name: str, split_parent: bool) -> list[str]:
    out = []
    if new.layer == "titles" and new.text != old.text:
        out.append(f"{name}: текст «{old.text}» → «{new.text}»")
    out += _timing(old, new, name, split_parent)
    if new.volume is not None and abs((old.volume or 0) - new.volume) > EPS:
        out.append(f"{name}: громкость {round((old.volume or 0) * 100)}% → {round(new.volume * 100)}%")
    for label, before, after in (("плавное появление звука", old.fade_in, new.fade_in),
                                 ("плавное затухание звука", old.fade_out, new.fade_out)):
        if abs(after - before) > EPS:
            out.append(f"{name}: {label} {fmt_len(after)}" if after else f"{name}: {label} убрано")
    if new.asset_id and old.asset_id and new.asset_id != old.asset_id:
        out.append(f"{name}: заменён исходник")
    if new.layer != old.layer:
        out.append(f"{name}: перенесён на дорожку «{LAYER_LABELS[new.layer]}»")
    return out


def _split_pieces(before: dict, after: dict) -> dict[str, str]:
    """{новая часть: исходный клип}: часть начинается там, где исходный теперь кончается."""

    pieces = {}
    for piece_id in sorted(after.keys() - before.keys()):
        piece = after[piece_id]
        for parent_id in sorted(before.keys() & after.keys()):
            parent = after[parent_id]
            if piece.src and parent.src == piece.src and parent.layer == piece.layer \
                    and abs(parent.end - piece.start) <= EPS \
                    and before[parent_id].end >= piece.end - EPS:
                pieces[piece_id] = parent_id
                break
    return pieces


def diff_models(old: Model | None, new: Model, *, names: Mapping[str, str] | None = None) -> list[str]:
    names = names or {}
    if old is None:
        return [f"черновой монтаж: {len(new.clips)} клипов, {fmt_len(new.duration)}"]
    before = {clip.id: clip for clip in old.clips}
    after = {clip.id: clip for clip in new.clips}
    changes = []
    if abs(new.duration - old.duration) > EPS:
        changes.append(f"длина ролика {fmt_len(old.duration)} → {fmt_len(new.duration)}")
    pieces = _split_pieces(before, after)
    for piece_id, parent_id in pieces.items():
        changes.append(f"{clip_name(after[parent_id], names)}: разрезан на {fmt_time(after[piece_id].start)}")
    changes += [f"добавлен {clip_name(clip, names)} с {fmt_time(clip.start)}"
                for clip in new.clips if clip.id not in before and clip.id not in pieces]
    changes += [f"удалён {clip_name(clip, names)}" for clip in old.clips if clip.id not in after]
    parents = set(pieces.values())
    for clip in new.clips:
        if clip.id in before:
            changes += _changed(before[clip.id], clip, clip_name(clip, names), clip.id in parents)
    return changes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_model.py' -v`
Expected: PASS (12 tests).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/model.py skills/aimaster/studio/montage/model_diff.py skills/aimaster/scripts/montage_testkit.py skills/aimaster/scripts/test_montage_model.py
git commit -m "feat(montage): neutral montage model, Studio-proof hash and Russian semantic diff"
```

---

### Task 12: Версии монтажа

**Files:**
- Create: `skills/aimaster/studio/montage/versions.py`
- Test: `skills/aimaster/scripts/test_montage_versions.py`

**Interfaces:**
- Consumes: `model.Model`; `paths.MontagePaths/VERSION_ID/version_name/version_number`; `platform_compat.replace_file`; `MontageError`.
- Produces:
  - `versions.BY_VALUES = ("agent", "owner", "autopilot")`.
  - `@dataclass(frozen=True) versions.VersionMeta(version, created_at, by, based_on, summary, changes: tuple[str, ...], asset_id, model_hash)` с `to_dict()` и `VersionMeta.from_dict(data)` — это содержимое `versions/vNNN/meta.json`.
  - `next_version_id(paths) -> str`; `list_versions(paths) -> list[VersionMeta]` (по номеру); `read_meta(paths, version_id) -> VersionMeta`; `read_version_model(paths, version_id) -> Model`.
  - `stage_version(paths, meta, model) -> Path` (скрытая `.vNNN.staging`); `publish_version(paths, staging, version_id) -> Path`; `discard_staging(staging) -> None`.
  - `restore_files(paths, version_id) -> Path | None` (прежний `current/index.html` сохраняется в `.undo/before-restore-*.html`, путь возвращается).
  - `has_unrendered_changes(current_hash: str | None, current: VersionMeta | None) -> bool`.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_versions.py`:

```python
#!/usr/bin/env python3
"""Версии: v001, v002…; снимок публикуется целиком; не перезаписываются; возврат с резервной копией."""

from __future__ import annotations

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

from studio.montage import MontageError  # noqa: E402
from studio.montage.model import Clip, Model  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.versions import (  # noqa: E402
    VersionMeta, discard_staging, has_unrendered_changes, list_versions, next_version_id,
    publish_version, read_meta, read_version_model, restore_files, stage_version)

MODEL = Model(1.0, (Clip(id="v-1", layer="video", kind="video", start=0.0, duration=1.0),))


def meta(version, based_on=None, model_hash="h1"):
    return VersionMeta(version=version, created_at="2026-09-25T10:00:00+00:00", by="agent",
                       based_on=based_on, summary="Черновой монтаж",
                       changes=("черновой монтаж: 1 клипов, 1,0 с",), asset_id="asset-x",
                       model_hash=model_hash)


class VersionsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.paths = montage_paths(Path(temp.name).resolve() / "p")
        self.paths.current.mkdir(parents=True)
        self.paths.index.write_text("<html>v1</html>", encoding="utf-8")

    def publish(self, version, **kwargs):
        staging = stage_version(self.paths, meta(version, **kwargs), MODEL)
        return publish_version(self.paths, staging, version)

    def test_first_version_is_published_whole(self):
        self.assertEqual(next_version_id(self.paths), "v001")
        staging = stage_version(self.paths, meta("v001"), MODEL)
        self.assertFalse(self.paths.version_dir("v001").exists())
        final = publish_version(self.paths, staging, "v001")
        self.assertEqual((final / "index.html").read_text(encoding="utf-8"), "<html>v1</html>")
        self.assertEqual(json.loads((final / "meta.json").read_text(encoding="utf-8"))["version"], "v001")
        self.assertEqual(read_version_model(self.paths, "v001"), MODEL)
        self.assertEqual(list_versions(self.paths), [meta("v001")])
        self.assertEqual(next_version_id(self.paths), "v002")

    def test_versions_are_never_overwritten(self):
        self.publish("v001")
        with self.assertRaises(MontageError) as caught:
            stage_version(self.paths, meta("v001"), MODEL)
        self.assertIn("не перезаписываются", str(caught.exception))

    def test_discarded_staging_leaves_no_version(self):
        discard_staging(stage_version(self.paths, meta("v001"), MODEL))
        self.assertEqual(list_versions(self.paths), [])
        self.assertEqual(list(self.paths.versions.iterdir()), [])

    def test_list_ignores_staging_and_foreign_folders(self):
        self.publish("v001")
        (self.paths.versions / ".v002.staging").mkdir()
        (self.paths.versions / "notes").mkdir()
        self.assertEqual([m.version for m in list_versions(self.paths)], ["v001"])
        with self.assertRaises(MontageError):
            read_meta(self.paths, "v009")

    def test_restore_copies_the_snapshot_and_keeps_a_backup(self):
        self.publish("v001")
        self.paths.index.write_text("<html>v2 edited</html>", encoding="utf-8")
        backup = restore_files(self.paths, "v001")
        self.assertEqual(self.paths.index.read_text(encoding="utf-8"), "<html>v1</html>")
        self.assertEqual(backup.read_text(encoding="utf-8"), "<html>v2 edited</html>")
        self.assertEqual(backup.parent, self.paths.undo)
        with self.assertRaises(MontageError):
            restore_files(self.paths, "v007")

    def test_unrendered_changes(self):
        self.assertFalse(has_unrendered_changes("h1", meta("v001", model_hash="h1")))
        self.assertTrue(has_unrendered_changes("h2", meta("v001", model_hash="h1")))
        self.assertTrue(has_unrendered_changes("h1", None))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_versions.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage.versions'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/versions.py`:

```python
"""Версии монтажа: неизменяемые снимки versions/vNNN/{index.html, meta.json, model.json}.

Снимок готовится в скрытой .vNNN.staging рядом и публикуется переименованием
только после того, как версия записана в state, — видимая версия всегда
согласована с разделом montage проекта. Версии не удаляются и не перезаписываются.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ..platform_compat import replace_file
from . import MontageError
from .model import Model
from .paths import VERSION_ID, MontagePaths, version_name, version_number

BY_VALUES = ("agent", "owner", "autopilot")


@dataclass(frozen=True)
class VersionMeta:
    version: str
    created_at: str
    by: str
    based_on: str | None
    summary: str
    changes: tuple[str, ...]
    asset_id: str
    model_hash: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["changes"] = list(self.changes)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "VersionMeta":
        return cls(version=data["version"], created_at=data["created_at"], by=data["by"],
                   based_on=data.get("based_on"), summary=data.get("summary", ""),
                   changes=tuple(data.get("changes", [])), asset_id=data["asset_id"],
                   model_hash=data["model_hash"])


def _published(paths: MontagePaths) -> list[str]:
    if not paths.versions.is_dir():
        return []
    names = [item.name for item in paths.versions.iterdir()
             if item.is_dir() and VERSION_ID.fullmatch(item.name) and (item / "meta.json").is_file()]
    return sorted(names, key=version_number)


def next_version_id(paths: MontagePaths) -> str:
    return version_name(max((version_number(name) for name in _published(paths)), default=0) + 1)


def read_meta(paths: MontagePaths, version_id: str) -> VersionMeta:
    try:
        data = json.loads((paths.version_dir(version_id) / "meta.json").read_text(encoding="utf-8"))
        return VersionMeta.from_dict(data)
    except (OSError, ValueError, KeyError) as error:
        raise MontageError(f"нет версии {version_id}") from error


def list_versions(paths: MontagePaths) -> list[VersionMeta]:
    return [read_meta(paths, name) for name in _published(paths)]


def read_version_model(paths: MontagePaths, version_id: str) -> Model:
    try:
        data = json.loads((paths.version_dir(version_id) / "model.json").read_text(encoding="utf-8"))
        return Model.from_dict(data)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise MontageError(f"у версии {version_id} нет модели монтажа") from error


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stage_version(paths: MontagePaths, meta: VersionMeta, model: Model) -> Path:
    if paths.version_dir(meta.version).exists():
        raise MontageError(f"версия {meta.version} уже есть — версии не перезаписываются")
    staging = paths.versions / f".{meta.version}.staging"
    if staging.exists():
        shutil.rmtree(staging)  # недоделанная прошлая попытка той же версии
    staging.mkdir(parents=True)
    shutil.copy2(paths.index, staging / "index.html")
    _write_json(staging / "meta.json", meta.to_dict())
    _write_json(staging / "model.json", model.to_dict())
    return staging


def publish_version(paths: MontagePaths, staging: Path, version_id: str) -> Path:
    final = paths.version_dir(version_id)
    os.rename(staging, final)
    return final


def discard_staging(staging: Path) -> None:
    shutil.rmtree(staging, ignore_errors=True)


def restore_files(paths: MontagePaths, version_id: str) -> Path | None:
    """Кладёт снимок версии в current/index.html; прежний current — в .undo/."""

    source = paths.version_dir(version_id) / "index.html"
    if not source.is_file():
        raise MontageError(f"нет версии {version_id}")
    backup = None
    if paths.index.is_file():
        paths.undo.mkdir(parents=True, exist_ok=True)
        backup = paths.undo / (f"before-restore-{time.strftime('%Y%m%d-%H%M%S')}"
                               f"-{time.time_ns() % 1_000_000_000:09d}.html")
        shutil.copy2(paths.index, backup)
    temporary = paths.index.with_name(".index.restore.tmp")
    shutil.copy2(source, temporary)
    replace_file(temporary, paths.index)
    return backup


def has_unrendered_changes(current_hash: str | None, current: VersionMeta | None) -> bool:
    return current is None or current_hash != current.model_hash
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_versions.py' -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/versions.py skills/aimaster/scripts/test_montage_versions.py
git commit -m "feat(montage): immutable montage versions with staged publish and restore"
```

---
### Task 13: Раздел `montage` в state — транзакция с `assembly`, история, проекция

**Files:**
- Create: `skills/aimaster/studio/montage/montage_state.py`
- Modify: `skills/aimaster/studio/domain.py` (`HISTORY_KINDS` — три вида)
- Modify: `skills/aimaster/studio/projection.py` (`_STATE_KEYS`, `_sanitize_montage`, `build_snapshot`, `validate_state`)
- Modify: `skills/aimaster/studio/authoring_qa.py` (выделить `apply_assembly`)
- Modify: `skills/aimaster/studio/store.py` (`ProjectStore.project_dir`)
- Modify: `skills/aimaster/studio/static/ui/history-panel.js` (подписи трёх видов)
- Modify: `skills/aimaster/scripts/montage_testkit.py` (`tiny_mp4`, `tiny_wav`, `Seeded`, `seed_workspace`)
- Test: `skills/aimaster/scripts/test_montage_state.py`

**Interfaces:**
- Consumes: `authoring_support.mutate/require_project/require_stage_not_approved/require_result_asset_role/open_assets/open_store`; `assets.AssetIndex.resolve/role_of`; `domain.append_history`; `canvas.Canvas`; `versions.VersionMeta`; `MontageError`.
- Produces:
  - `domain.HISTORY_KINDS["montage-drafted"] = frozenset()`, `["montage-built"] = frozenset({"target_id"})`, `["montage-restored"] = frozenset({"target_id"})`.
  - `authoring_qa.apply_assembly(state: dict, mime_type: str, asset_id: str, caption: str | None) -> None` (тело прежнего `set_assembly` без истории).
  - `store.ProjectStore.project_dir(project_id: str) -> Path`.
  - Форма `state["montage"]`: `{"current_version": "vNNN" | None, "versions": [{"id", "asset_id", "created_at", "by", "based_on", "summary"}], "canvas": {"width", "height"}}`; в снапшоте (`active_project["montage"]`, с шага `assembly`) у каждой версии ещё `asset_url`.
  - `montage_state.montage_section(state) -> dict`; `montage_state.check_writable(state) -> None`; `montage_state.record_draft(store, project_id, expected_revision, *, canvas: Canvas) -> {"project_id", "revision"}`; `montage_state.record_version(store, assets, project_id, expected_revision, *, meta: VersionMeta) -> {"project_id", "revision"}`; `montage_state.record_restore(store, assets, project_id, expected_revision, *, version_id: str, actor: str = "agent") -> {"project_id", "revision"}`.
  - `montage_testkit.tiny_mp4(tag=b"x") -> bytes`, `tiny_wav(samples=8) -> bytes`, `@dataclass Seeded(workspace, project_id, media, ids)`, `seed_workspace(base: Path, files: dict[str, bytes], build_state) -> Seeded`.

- [ ] **Step 1: Write the failing test**

В `skills/aimaster/scripts/montage_testkit.py` — в импорты добавить `import json`, `import struct`, `from dataclasses import dataclass` и `from studio.authoring_support import open_assets  # noqa: E402`; в конец файла:

```python
def tiny_mp4(tag: bytes = b"x") -> bytes:
    """Минимальный MP4, который принимает AssetIndex (ftyp + mdat). Не проигрывается."""

    ftyp = struct.pack(">I", 16) + b"ftypisom" + struct.pack(">I", 0x200)
    return ftyp + struct.pack(">I", 8 + len(tag)) + b"mdat" + tag


def tiny_wav(samples: int = 8) -> bytes:
    fmt = struct.pack("<HHIIHH", 1, 1, 8000, 16000, 2, 16)
    data = b"\x00\x00" * samples
    body = (b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", len(data)) + data)
    return b"RIFF" + struct.pack("<I", len(body)) + body


@dataclass
class Seeded:
    workspace: Path
    project_id: str
    media: Path
    ids: dict


def seed_workspace(base: Path, files: dict, build_state) -> Seeded:
    """Рабочая папка с проектом «p»: файлы из files кладутся в media/ и регистрируются
    с ролью result, state.json собирает build_state({имя файла: asset_id})."""

    workspace = Path(base) / "рабочая папка"
    project_dir = workspace / "projects" / "p"
    project_dir.mkdir(parents=True)
    media = workspace / "media"
    media.mkdir()
    index = open_assets(workspace)
    ids = {}
    for name, data in files.items():
        (media / name).write_bytes(data)
        ids[name] = index.register(f"media/{name}", "result")["asset_id"]
    (project_dir / "state.json").write_text(
        json.dumps(build_state(ids), ensure_ascii=False, indent=2), encoding="utf-8")
    return Seeded(workspace, "p", media, ids)
```

`skills/aimaster/scripts/test_montage_state.py`:

```python
#!/usr/bin/env python3
"""state["montage"]: черновик, версия, возврат — вместе с assembly и историей, одной транзакцией."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import seed_workspace, tiny_mp4, tiny_wav, video_state  # noqa: E402
from studio.authoring_support import AuthoringError, open_assets, open_store  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.montage_state import (  # noqa: E402
    check_writable, record_draft, record_restore, record_version)
from studio.montage.versions import VersionMeta  # noqa: E402
from studio.projection import ProjectionError, build_snapshot, validate_state  # noqa: E402


class StateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        files = {"a.mp4": tiny_mp4(b"a"), "v1.mp4": tiny_mp4(b"v1"), "v2.mp4": tiny_mp4(b"v2"),
                 "voice.wav": tiny_wav()}
        self.seed = seed_workspace(Path(temp.name).resolve(), files, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"])], audio={"voice": ids["voice.wav"]}))
        self.store = open_store(self.seed.workspace)
        self.assets = open_assets(self.seed.workspace)

    def meta(self, version, file, based_on=None):
        return VersionMeta(version=version, created_at="2026-09-25T10:00:00+00:00", by="agent",
                           based_on=based_on, summary=f"Сборка {version}", changes=(),
                           asset_id=self.seed.ids[file], model_hash="h")

    def load(self):
        return self.store.load("p")

    def test_draft_records_canvas_and_history(self):
        result = record_draft(self.store, "p", 0, canvas=Canvas(108, 192))
        state = self.load()
        self.assertEqual(result["revision"], 1)
        self.assertEqual(state["montage"], {"current_version": None, "versions": [],
                                            "canvas": {"width": 108, "height": 192}})
        self.assertEqual(state["history"][-1]["kind"], "montage-drafted")

    def test_version_sets_assembly_in_the_same_transaction(self):
        record_draft(self.store, "p", 0, canvas=Canvas(108, 192))
        result = record_version(self.store, self.assets, "p", 1, meta=self.meta("v001", "v1.mp4"))
        state = self.load()
        self.assertEqual(result["revision"], 2)
        self.assertEqual(state["montage"]["current_version"], "v001")
        self.assertEqual(state["montage"]["versions"], [{
            "id": "v001", "asset_id": self.seed.ids["v1.mp4"], "created_at": "2026-09-25T10:00:00+00:00",
            "by": "agent", "based_on": None, "summary": "Сборка v001"}])
        self.assertEqual(state["assembly"], {"status": "ready", "asset_id": self.seed.ids["v1.mp4"],
                                             "summary": "Сборка v001"})
        self.assertEqual((state["history"][-1]["kind"], state["history"][-1]["params"]),
                         ("montage-built", {"target_id": "v001"}))

    def test_restore_points_assembly_back(self):
        record_draft(self.store, "p", 0, canvas=Canvas(108, 192))
        record_version(self.store, self.assets, "p", 1, meta=self.meta("v001", "v1.mp4"))
        record_version(self.store, self.assets, "p", 2, meta=self.meta("v002", "v2.mp4", "v001"))
        record_restore(self.store, self.assets, "p", 3, version_id="v001", actor="you")
        state = self.load()
        self.assertEqual(state["montage"]["current_version"], "v001")
        self.assertEqual(state["assembly"]["asset_id"], self.seed.ids["v1.mp4"])
        self.assertEqual((state["history"][-1]["kind"], state["history"][-1]["actor"]),
                         ("montage-restored", "you"))

    def test_refusals(self):
        record_draft(self.store, "p", 0, canvas=Canvas(108, 192))
        record_version(self.store, self.assets, "p", 1, meta=self.meta("v001", "v1.mp4"))
        with self.assertRaises(MontageError):
            record_restore(self.store, self.assets, "p", 2, version_id="v009")
        with self.assertRaises(MontageError):
            record_version(self.store, self.assets, "p", 2, meta=self.meta("v001", "v2.mp4"))
        with self.assertRaises(MontageError):
            check_writable({"project": {"type": "photo"}, "milestones": {}})

    def test_approved_assembly_is_not_reopened(self):
        def approve(state):
            state["milestones"]["assembly"] = "approved"
        self.store.transact("p", 0, approve)
        with self.assertRaises(AuthoringError):
            record_draft(self.store, "p", 1, canvas=Canvas(108, 192))

    def test_validation_rejects_broken_sections(self):
        base = video_state([("s1", "Сад", "текст", 2000, "asset-a")])
        broken = [
            {"current_version": "v002", "versions": [], "canvas": {"width": 1, "height": 1}},
            {"current_version": None, "versions": [{"id": "001", "asset_id": "a", "created_at": "t",
                                                    "by": "agent", "based_on": None, "summary": ""}],
             "canvas": {"width": 1, "height": 1}},
            {"current_version": None, "versions": [], "canvas": {"width": 0, "height": 1}},
            {"current_version": None, "versions": [], "canvas": {"width": 1, "height": 1}, "x": 1},
        ]
        for section in broken:
            with self.subTest(section=section), self.assertRaises(ProjectionError):
                validate_state({**base, "montage": section})
        photo = {**base, "project": {**base["project"], "type": "photo"},
                 "montage": {"current_version": None, "versions": [], "canvas": {"width": 1, "height": 1}}}
        with self.assertRaises(ProjectionError):
            validate_state(photo)

    def test_snapshot_shows_versions_with_asset_urls(self):
        record_draft(self.store, "p", 0, canvas=Canvas(108, 192))
        record_version(self.store, self.assets, "p", 1, meta=self.meta("v001", "v1.mp4"))
        snapshot = build_snapshot(self.store.list_projects(), self.load(),
                                  asset_url=lambda asset: f"/assets/{asset}")
        montage = snapshot["active_project"]["montage"]
        self.assertEqual(montage["current_version"], "v001")
        self.assertEqual(montage["versions"][0]["asset_url"], f"/assets/{self.seed.ids['v1.mp4']}")
        self.assertEqual(self.store.project_dir("p"), self.seed.workspace.resolve() / "projects" / "p")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_state.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage.montage_state'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/domain.py` — в `HISTORY_KINDS` сразу после строки `"autopilot-grant": frozenset({"action", "target_id"}),`:

```python
    # Спецификация 2026-09-25 (монтаж): черновик собран, собрана версия vNNN,
    # текущей стала версия vNNN.
    "montage-drafted": frozenset(),
    "montage-built": frozenset({"target_id"}),
    "montage-restored": frozenset({"target_id"}),
```

`skills/aimaster/studio/authoring_qa.py` — перед `def set_assembly(` добавить:

```python
def apply_assembly(state: dict, mime_type: str, asset_id: str, caption: str | None) -> None:
    """Запись `state["assembly"]` с проверками — общая для `assembly set` и версии
    монтажа (`studio/montage/montage_state.py`), чтобы правило было одно."""

    project = require_project(state)
    require_stage_not_approved(state, "assembly", "assembly set")
    if project.get("type") == "photo":
        require_image_mime(mime_type, "a photo project's assembly asset")
    else:
        require_video_mime(mime_type, "a video/mixed project's assembly asset")
    payload = {"status": "ready", "asset_id": asset_id}
    if caption is not None:
        payload["summary"] = caption
    state["assembly"] = payload
```

и тело `mutator` внутри `set_assembly` заменить на:

```python
    def mutator(state):
        apply_assembly(state, mime_type, asset_id, caption)
        domain.append_history(state, "agent", "assembly-ready", "assembly")
```

`skills/aimaster/studio/store.py` — после метода `load`:

```python
    def project_dir(self, project_id: str) -> Path:
        """Папка проекта (там, где state.json) — для файлов рядом с состоянием, например montage/."""

        return self._find(project_id)
```

`skills/aimaster/studio/projection.py`:

- в `_STATE_KEYS` после строки `"assembly",` добавить строку `"montage",`;
- сразу после функции `_sanitize_assembly` добавить:

```python
_MONTAGE_KEYS = {"current_version", "versions", "canvas"}
_MONTAGE_VERSION_KEYS = {"id", "asset_id", "created_at", "by", "based_on", "summary"}
_MONTAGE_BY = {"agent", "owner", "autopilot"}
_MONTAGE_VERSION_ID = re.compile(r"v\d{3,}")


def _sanitize_montage(value, asset_url):
    """Спецификация 2026-09-25 (монтаж): версии, текущая версия, размер кадра.
    Схема самого монтажа живёт в montage/current/index.html, не в state."""

    value = _exact_keys(value, _MONTAGE_KEYS, "montage")
    versions, seen = [], []
    for position, item in enumerate(_list(value.get("versions", []), "montage.versions")):
        context = f"montage.versions[{position}]"
        item = _exact_keys(item, _MONTAGE_VERSION_KEYS, context)
        version_id = _string(item.get("id"), f"{context}.id")
        if not _MONTAGE_VERSION_ID.fullmatch(version_id) or version_id in seen:
            raise ProjectionError(f"{context}.id must be a unique vNNN")
        based_on = item.get("based_on")
        if based_on is not None and based_on not in seen:
            raise ProjectionError(f"{context}.based_on must name an earlier version")
        seen.append(version_id)
        entry = {
            "id": version_id,
            "asset_id": _string(item.get("asset_id"), f"{context}.asset_id"),
            "created_at": _string(item.get("created_at"), f"{context}.created_at"),
            "by": _enum(item.get("by"), _MONTAGE_BY, f"{context}.by"),
            "based_on": based_on,
            "summary": _safe_system_text(item.get("summary", ""), f"{context}.summary"),
        }
        versions.append(_add_asset_url(entry, context, asset_url))
    current = value.get("current_version")
    if current is not None and current not in seen:
        raise ProjectionError("montage.current_version must name a recorded version")
    canvas = _exact_keys(value.get("canvas", {"width": 1080, "height": 1920}),
                         {"width", "height"}, "montage.canvas")
    size = {key: _non_negative_integer(canvas.get(key), f"montage.canvas.{key}")
            for key in ("width", "height")}
    if not all(size.values()):
        raise ProjectionError("montage.canvas sides must be positive")
    return {"current_version": current, "versions": versions, "canvas": size}
```

- в `build_snapshot` внутри блока `if _stage_reached(sequence, stage_index, "assembly"):` сразу после присваивания `active_project["assembly"] = _sanitize_assembly(...)`:

```python
        if "montage" in state:
            active_project["montage"] = _sanitize_montage(state["montage"], asset_url)
```

- в `validate_state` сразу после `if "assembly" in state: _sanitize_assembly(...)`:

```python
    if "montage" in state:
        if project_type == "photo":
            raise ProjectionError("photo projects cannot contain montage")
        _sanitize_montage(state["montage"], _identity_asset_url)
```

`skills/aimaster/studio/static/ui/history-panel.js` — после строки `"assembly-ready": () => "Финал собран",`:

```js
  "montage-drafted": () => "Черновой монтаж собран",
  "montage-built": (entry) => {
    const id = entry?.params?.target_id;
    return typeof id === "string" && id ? `Монтаж: собрана версия ${id}` : "Монтаж: собрана версия";
  },
  "montage-restored": (entry) => {
    const id = entry?.params?.target_id;
    return typeof id === "string" && id ? `Монтаж: текущей стала версия ${id}` : "Монтаж: выбрана другая версия";
  },
```

`skills/aimaster/studio/montage/montage_state.py`:

```python
"""Раздел state["montage"]: черновик, собранная версия, возврат к версии.

Каждая запись — одна транзакция `authoring_support.mutate` (с validate_state):
версия и `assembly` меняются вместе, иначе дашборд показал бы одно, а «Принять»
приняло бы другое. Запись в историю проекта — в той же транзакции.
"""

from __future__ import annotations

from .. import domain
from ..assets import AssetIndex
from ..authoring_qa import apply_assembly
from ..authoring_support import (mutate, require_project, require_result_asset_role,
                                 require_stage_not_approved)
from ..store import ProjectStore
from . import MontageError
from .canvas import DEFAULT_HEIGHT, DEFAULT_WIDTH, Canvas
from .versions import VersionMeta


def montage_section(state: dict) -> dict:
    section = state.get("montage")
    if isinstance(section, dict):
        return section
    return {"current_version": None, "versions": [],
            "canvas": {"width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT}}


def check_writable(state: dict) -> None:
    project = require_project(state)
    if project.get("type") == "photo":
        raise MontageError("у фото-проекта монтажа нет: его сборка — принятая картинка")
    require_stage_not_approved(state, "assembly", "montage")


def record_draft(store: ProjectStore, project_id: str, expected_revision: int, *,
                 canvas: Canvas) -> dict:
    def mutator(state):
        check_writable(state)
        section = montage_section(state)
        section["canvas"] = canvas.to_dict()
        state["montage"] = section
        domain.append_history(state, "agent", "montage-drafted", "assembly")

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "revision": new_state["revision"]}


def record_version(store: ProjectStore, assets: AssetIndex, project_id: str,
                   expected_revision: int, *, meta: VersionMeta) -> dict:
    _, mime_type = assets.resolve(meta.asset_id)
    require_result_asset_role(assets.role_of(meta.asset_id), "a montage version")

    def mutator(state):
        check_writable(state)
        section = montage_section(state)
        if any(item["id"] == meta.version for item in section["versions"]):
            raise MontageError(f"версия {meta.version} уже записана — версии не перезаписываются")
        section["versions"].append({"id": meta.version, "asset_id": meta.asset_id,
                                    "created_at": meta.created_at, "by": meta.by,
                                    "based_on": meta.based_on, "summary": meta.summary})
        section["current_version"] = meta.version
        state["montage"] = section
        apply_assembly(state, mime_type, meta.asset_id, meta.summary or None)
        domain.append_history(state, "agent", "montage-built", "assembly", target_id=meta.version)

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "revision": new_state["revision"]}


def record_restore(store: ProjectStore, assets: AssetIndex, project_id: str,
                   expected_revision: int, *, version_id: str, actor: str = "agent") -> dict:
    def mutator(state):
        check_writable(state)
        section = montage_section(state)
        entry = next((item for item in section["versions"] if item["id"] == version_id), None)
        if entry is None:
            raise MontageError(f"нет версии {version_id}")
        _, mime_type = assets.resolve(entry["asset_id"])
        section["current_version"] = version_id
        state["montage"] = section
        apply_assembly(state, mime_type, entry["asset_id"], entry.get("summary") or None)
        domain.append_history(state, actor, "montage-restored", "assembly", target_id=version_id)

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "revision": new_state["revision"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_state.py' -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Full checks (статика тронута)**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check && node --experimental-vm-modules --no-warnings skills/aimaster/scripts/check_static_modules.mjs && node --test skills/aimaster/studio/static/ui/v2/*.test.mjs`
Expected: всё зелёное; прежние тесты `assembly set` проходят без изменений.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/montage_state.py skills/aimaster/studio/domain.py skills/aimaster/studio/projection.py skills/aimaster/studio/authoring_qa.py skills/aimaster/studio/store.py skills/aimaster/studio/static/ui/history-panel.js skills/aimaster/scripts/montage_testkit.py skills/aimaster/scripts/test_montage_state.py
git commit -m "feat(montage): montage section in state, written with assembly and history in one transaction"
```

---

### Task 14: Правки агента, выровненные под Studio, и откат

**Files:**
- Create: `skills/aimaster/studio/montage/edit_ops.py`
- Create: `skills/aimaster/studio/montage/edit.py`
- Test: `skills/aimaster/scripts/test_montage_edit.py`

**Interfaces:**
- Consumes: `model.read_model/model_hash/Model.clip`; `engine_cli.EngineRunner`; `draft.write_text_atomic`; `html_doc.element_attrs/set_attr/set_text/insert_before_root_end/root_duration/fmt_number/ROOT_ID`; `paths.MontagePaths`; `TRACK_OF_LAYER`; `MontageError`.
- Produces:
  - `edit.OPS = ("move", "trim-start", "trim-end", "split", "delete", "volume", "fade", "title-add", "title-text", "undo")`.
  - `@dataclass(frozen=True) edit.EditRequest(op, clip=None, at=None, seconds=None, duration=None, value=None, fade_in=None, fade_out=None, text=None)`.
  - `@dataclass(frozen=True) edit.EditContext(engine, paths, runner)`.
  - `edit.apply_edit(engine, paths, request, *, expected_model_hash=None, runner=None) -> {"op", "clip", "model_hash_before", "model_hash", "duration", "receipt"}`; для `undo` — `{"op": "undo", "ok": True, "restored": <имя снимка>}`.
  - `edit.undo_last(paths) -> dict`.
  - `edit_ops.need(value, flag, op)`, `edit_ops.CLIP_OPS: dict[str, Callable[[EditContext, Clip, EditRequest], dict]]`, `edit_ops.title_add(ctx, request) -> {"ok", "new_clip"}`; у `split` квитанция дополнена `new_clip`.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_edit.py`:

```python
#!/usr/bin/env python3
"""Правки: как мышью в Studio (обрезка начала двигает исходник, сдвиг за конец удлиняет ролик),
проверка «монтаж не менялся», откат только своей последней правки."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import FakeHyperframes, fake_engine, video_state  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.draft_html import render_draft_html  # noqa: E402
from studio.montage.draft_plan import plan_draft  # noqa: E402
from studio.montage.edit import EditRequest, apply_edit  # noqa: E402
from studio.montage.html_doc import element_attrs  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402

MEDIA = {"asset-a": MediaInfo(2.0, 108, 192, True, True),
         "asset-b": MediaInfo(1.5, 108, 192, True, False),
         "asset-v": MediaInfo(5.0, None, None, False, True)}
SOURCES = {"asset-a": "assets/asset-a.mp4", "asset-b": "assets/asset-b.mp4",
           "asset-v": "assets/asset-v.wav"}
SCENES = [("s1", "Сад", "Барсик идёт по саду", 2000, "asset-a"),
          ("s2", "Клубок", "Находит клубок", 2000, "asset-b")]


class EditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        self.paths = montage_paths(base / "p")
        self.paths.current.mkdir(parents=True)
        plan = plan_draft(video_state(SCENES, audio={"voice": "asset-v"}), MEDIA.__getitem__)
        self.paths.index.write_text(render_draft_html(plan, Canvas(108, 192), SOURCES), encoding="utf-8")
        self.runner = FakeHyperframes()
        self.engine = fake_engine(base / "engine")

    def edit(self, **kwargs):
        expected = kwargs.pop("expected_model_hash", None)
        return apply_edit(self.engine, self.paths, EditRequest(**kwargs),
                          expected_model_hash=expected, runner=self.runner)

    def text(self):
        return self.paths.index.read_text(encoding="utf-8")

    def attrs(self):
        return element_attrs(self.text())

    def test_trim_start_moves_media_start_like_studio(self):
        result = self.edit(op="trim-start", clip="v-1", seconds=0.5)
        clip = self.attrs()["v-1"]
        self.assertEqual((clip["data-start"], clip["data-duration"], clip["data-media-start"]),
                         ("0.5", "1.5", "0.5"))
        self.assertIn(["timeline", "trim", "#v-1", "--start", "0.5", "--duration", "1.5",
                       "--dir", ".", "--json"], self.runner.calls)
        self.assertNotEqual(result["model_hash"], result["model_hash_before"])

    def test_move_past_the_end_extends_the_root(self):
        self.edit(op="move", clip="v-2", at=3.0)
        self.assertEqual((self.attrs()["root"]["data-duration"], self.attrs()["v-2"]["data-start"]),
                         ("4.5", "3"))

    def test_split_drops_the_fade_on_the_new_piece(self):
        result = self.edit(op="split", clip="v-2", at=2.5)
        self.assertEqual(result["receipt"]["new_clip"], "v-2-2")
        attrs = self.attrs()
        self.assertEqual((attrs["v-2"]["class"], attrs["v-2-2"]["class"]),
                         ("am-video am-fade-in", "am-video"))
        self.assertEqual(attrs["v-2-2"]["data-media-start"], "0.5")

    def test_titles(self):
        result = self.edit(op="title-add", text="Финал <3", at=3.0, duration=1.0)
        self.assertEqual(result["receipt"]["new_clip"], "t-3")
        self.assertEqual((self.attrs()["t-3"]["_text"], self.attrs()["root"]["data-duration"]),
                         ("Финал <3", "4"))
        self.edit(op="title-text", clip="t-1", text="Кот & мяч")
        self.assertEqual(self.attrs()["t-1"]["_text"], "Кот & мяч")

    def test_volume_and_fade(self):
        self.edit(op="volume", clip="a-voice", value=0.5)
        self.assertEqual(self.attrs()["a-voice"]["data-volume"], "0.5")
        with self.assertRaises(MontageError):
            self.edit(op="volume", clip="a-voice", value=5)
        with self.assertRaises(MontageError):
            self.edit(op="volume", clip="t-1", value=0.5)
        self.edit(op="fade", clip="a-voice", fade_in=0.5)
        self.assertEqual(self.attrs()["a-voice"]["data-fade-in"], "0.5")
        self.edit(op="fade", clip="a-voice", fade_in=0)
        self.assertNotIn("data-fade-in", self.attrs()["a-voice"])

    def test_stale_hash_is_refused_and_nothing_changes(self):
        before = self.text()
        with self.assertRaises(MontageError) as caught:
            self.edit(op="delete", clip="t-2", expected_model_hash="0" * 16)
        self.assertIn("изменился", str(caught.exception))
        self.assertEqual(self.text(), before)

    def test_refused_cli_edit_restores_the_file(self):
        self.runner.refuse["move"] = "#v-1 would overlap #v-2 at 3.4-5.4"
        before = self.text()
        with self.assertRaises(MontageError):
            self.edit(op="move", clip="v-1", at=3.4)
        self.assertEqual(self.text(), before)

    def test_undo_own_last_edit_only(self):
        before = self.text()
        self.edit(op="delete", clip="t-2")
        self.assertNotIn("t-2", self.attrs())
        self.assertEqual(self.edit(op="undo")["op"], "undo")
        self.assertEqual(self.text(), before)
        self.edit(op="delete", clip="t-2")
        self.paths.index.write_text(self.text() + " ", encoding="utf-8")  # правка мышью в столе
        with self.assertRaises(MontageError):
            self.edit(op="undo")

    def test_unknown_op_and_missing_clip_flag(self):
        with self.assertRaises(MontageError):
            self.edit(op="jump")
        with self.assertRaises(MontageError) as caught:
            self.edit(op="move", at=1.0)
        self.assertIn("--clip", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_edit.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage.edit'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/edit_ops.py`:

```python
"""Операции правки поверх CLI HyperFrames, выровненные под Studio.

CLI и Studio расходятся (проба 0.8.75): `timeline trim --start` двигает начало
клипа, но не `data-media-start`, а Studio двигает и его; `move` за конец ролика
CLI отклоняет, а Studio удлиняет корень. Поэтому операция = вызов CLI + наша
точечная правка атрибутов с тем же результатом, что мышь в Studio.
"""

from __future__ import annotations

import html
import re

from . import TRACK_OF_LAYER, MontageError
from .draft import write_text_atomic
from .html_doc import (ROOT_ID, element_attrs, fmt_number as fmt, insert_before_root_end,
                       root_duration, set_attr, set_text)

CLI_TIMEOUT = 120
MAX_VOLUME = 3.98
_TITLE_ID = re.compile(r"t-(\d+)")


def need(value, flag: str, op: str):
    if value is None:
        raise MontageError(f"для правки {op} нужен --{flag}")
    return value


def cli(ctx, args) -> dict:
    return ctx.runner.json(ctx.engine, ["timeline", *args, "--dir", ".", "--json"],
                           cwd=ctx.paths.current, timeout=CLI_TIMEOUT)


def patch(ctx, change) -> None:
    write_text_atomic(ctx.paths.index, change(ctx.paths.index.read_text(encoding="utf-8")))


def extend_root(ctx, end: float) -> None:
    patch(ctx, lambda text: set_attr(text, ROOT_ID, "data-duration", fmt(end))
          if end > root_duration(text) + 1e-6 else text)


def _sound_clip(clip, op: str) -> None:
    if clip.kind not in ("video", "audio"):
        raise MontageError(f"правка {op} — только для видео и звука, а {clip.id} — {clip.kind}")


def move(ctx, clip, req):
    at = need(req.at, "at", req.op)
    if at < 0:
        raise MontageError("начало клипа не может быть меньше нуля")
    extend_root(ctx, at + clip.duration)
    return cli(ctx, ["move", "#" + clip.id, fmt(at)])


def trim_start(ctx, clip, req):
    cut = need(req.seconds, "seconds", req.op)
    start, duration, media = clip.start + cut, clip.duration - cut, clip.media_start + cut
    if duration <= 0:
        raise MontageError("после обрезки от клипа ничего не останется")
    if start < 0 or (clip.kind in ("video", "audio") and media < 0):
        raise MontageError("вернуть больше, чем было срезано, нельзя")
    receipt = cli(ctx, ["trim", "#" + clip.id, "--start", fmt(start), "--duration", fmt(duration)])
    if clip.kind in ("video", "audio"):
        patch(ctx, lambda text: set_attr(text, clip.id, "data-media-start", fmt(media)))
    return receipt


def trim_end(ctx, clip, req):
    duration = need(req.duration, "duration", req.op)
    if duration <= 0:
        raise MontageError("длина клипа должна быть больше нуля")
    extend_root(ctx, clip.start + duration)
    return cli(ctx, ["trim", "#" + clip.id, "--duration", fmt(duration)])


def split(ctx, clip, req):
    at = need(req.at, "at", req.op)
    if not clip.start + 1e-3 < at < clip.end - 1e-3:
        raise MontageError(f"момент разреза должен быть внутри клипа ({clip.start}–{clip.end} с)")
    before = set(element_attrs(ctx.paths.index.read_text(encoding="utf-8")))
    receipt = cli(ctx, ["split", "#" + clip.id, fmt(at)])
    after = element_attrs(ctx.paths.index.read_text(encoding="utf-8"))
    pieces = sorted(set(after) - before)
    for piece in pieces:
        classes = after[piece].get("class", "").split()
        if "am-fade-in" in classes:  # проявление нужно на стыке сцен, не на разрезе
            kept = " ".join(name for name in classes if name != "am-fade-in")
            patch(ctx, lambda text, p=piece, k=kept: set_attr(text, p, "class", k))
    return {**receipt, "new_clip": pieces[0] if pieces else None}


def delete(ctx, clip, req):
    return cli(ctx, ["delete", "#" + clip.id])


def volume(ctx, clip, req):
    value = need(req.value, "value", req.op)
    _sound_clip(clip, req.op)
    if not 0 <= value <= MAX_VOLUME:
        raise MontageError(f"громкость — от 0 до {MAX_VOLUME}")
    return cli(ctx, ["set", "#" + clip.id, f"volume={fmt(value)}"])


def fade(ctx, clip, req):
    _sound_clip(clip, req.op)
    if req.fade_in is None and req.fade_out is None:
        raise MontageError("для правки fade нужен --fade-in или --fade-out")
    for name, value in (("data-fade-in", req.fade_in), ("data-fade-out", req.fade_out)):
        if value is None:
            continue
        if not 0 <= value <= clip.duration:
            raise MontageError(f"плавный край — от 0 до длины клипа ({clip.duration} с)")
        patch(ctx, lambda text, n=name, v=value: set_attr(text, clip.id, n, fmt(v) if v > 0 else None))
    return {"ok": True}


def title_add(ctx, req):
    text = need(req.text, "text", req.op)
    start, duration = need(req.at, "at", req.op), need(req.duration, "duration", req.op)
    if not text.strip() or start < 0 or duration <= 0:
        raise MontageError("титру нужны текст, начало не меньше нуля и длина больше нуля")
    ids = element_attrs(ctx.paths.index.read_text(encoding="utf-8"))
    number = max((int(m.group(1)) for m in map(_TITLE_ID.fullmatch, ids) if m), default=0) + 1
    new_id = f"t-{number}"
    fragment = (f'<div id="{new_id}" class="clip am-title" data-start="{fmt(start)}" '
                f'data-duration="{fmt(duration)}" data-track-index="{TRACK_OF_LAYER["titles"]}" '
                f'data-am-layer="titles"><span>{html.escape(text, quote=False)}</span></div>')
    extend_root(ctx, start + duration)
    patch(ctx, lambda current: insert_before_root_end(current, fragment))
    return {"ok": True, "new_clip": new_id}


def title_text(ctx, clip, req):
    text = need(req.text, "text", req.op)
    if clip.layer != "titles":
        raise MontageError(f"{clip.id} — не титр")
    patch(ctx, lambda current: set_text(current, clip.id, text))
    return {"ok": True}


CLIP_OPS = {"move": move, "trim-start": trim_start, "trim-end": trim_end, "split": split,
            "delete": delete, "volume": volume, "fade": fade, "title-text": title_text}
```

`skills/aimaster/studio/montage/edit.py`:

```python
"""Правка монтажа агентом: снимок для отката, проверка «монтаж не менялся», undo.

Перед каждой правкой current/index.html копируется в .undo/, после неё рядом
пишется хэш получившегося файла. `undo` возвращает последний снимок, только если
файл с тех пор не меняли (например, мышью в монтажном столе)."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import MontageError
from .draft import write_text_atomic
from .edit_ops import CLIP_OPS, need, title_add
from .engine import Engine
from .engine_cli import EngineRunner
from .model import model_hash, read_model
from .paths import MontagePaths

OPS = ("move", "trim-start", "trim-end", "split", "delete", "volume", "fade", "title-add",
       "title-text", "undo")


@dataclass(frozen=True)
class EditRequest:
    op: str
    clip: str | None = None
    at: float | None = None        # move — новое начало; split — момент; title-add — начало
    seconds: float | None = None   # trim-start — сколько срезать с начала (минус — вернуть)
    duration: float | None = None  # trim-end — новая длина; title-add — длина
    value: float | None = None     # volume — 0…3.98
    fade_in: float | None = None
    fade_out: float | None = None
    text: str | None = None


@dataclass(frozen=True)
class EditContext:
    engine: Engine
    paths: MontagePaths
    runner: object


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _snapshot(paths: MontagePaths) -> Path:
    paths.undo.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns() % 1_000_000_000:09d}"
    target = paths.undo / f"edit-{stamp}.html"
    target.write_bytes(paths.index.read_bytes())
    return target


def undo_last(paths: MontagePaths) -> dict:
    snapshots = sorted(paths.undo.glob("edit-*.html")) if paths.undo.is_dir() else []
    if not snapshots:
        raise MontageError("отменять нечего")
    latest, note = snapshots[-1], snapshots[-1].with_suffix(".json")
    try:
        after = json.loads(note.read_text(encoding="utf-8")).get("after")
    except (OSError, ValueError):
        after = None
    if after and after != _sha(paths.index):
        raise MontageError("после этой правки монтаж меняли (например, в монтажном столе) — "
                           "откат стёр бы и те изменения")
    write_text_atomic(paths.index, latest.read_text(encoding="utf-8"))
    latest.unlink()
    note.unlink(missing_ok=True)
    return {"ok": True, "restored": latest.name}


def apply_edit(engine: Engine, paths: MontagePaths, request: EditRequest, *,
               expected_model_hash: str | None = None, runner=None) -> dict:
    if request.op not in OPS:
        raise MontageError(f"неизвестная правка {request.op}; можно: {', '.join(OPS)}")
    if not paths.index.is_file():
        raise MontageError("черновика ещё нет: сначала montage draft")
    if request.op == "undo":
        return {"op": "undo", **undo_last(paths)}
    ctx = EditContext(engine, paths, runner or EngineRunner())
    model = read_model(engine, paths.current, cache_dir=paths.cache, runner=ctx.runner)
    before = model_hash(model)
    if expected_model_hash and expected_model_hash != before:
        raise MontageError("монтаж изменился с тех пор, как вы его читали (например, в монтажном "
                           "столе): прочитайте montage status и повторите")
    clip = None if request.op == "title-add" else model.clip(need(request.clip, "clip", request.op))
    snapshot = _snapshot(paths)
    try:
        receipt = title_add(ctx, request) if clip is None else CLIP_OPS[request.op](ctx, clip, request)
    except BaseException:
        write_text_atomic(paths.index, snapshot.read_text(encoding="utf-8"))
        snapshot.unlink(missing_ok=True)
        raise
    snapshot.with_suffix(".json").write_text(
        json.dumps({"after": _sha(paths.index), "op": request.op}), encoding="utf-8")
    after = read_model(engine, paths.current, cache_dir=paths.cache, runner=ctx.runner)
    return {"op": request.op, "clip": request.clip, "model_hash_before": before,
            "model_hash": model_hash(after), "duration": after.duration, "receipt": receipt}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_edit.py' -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/edit_ops.py skills/aimaster/studio/montage/edit.py skills/aimaster/scripts/test_montage_edit.py
git commit -m "feat(montage): Studio-aligned agent edits with stale-model guard and own-edit undo"
```

---
### Task 15: Сборка версии — проверка, рендер, ffprobe, ассет, версия, `assembly`

**Files:**
- Create: `skills/aimaster/studio/montage/context.py`
- Create: `skills/aimaster/studio/montage/verify.py`
- Create: `skills/aimaster/studio/montage/render.py`
- Test: `skills/aimaster/scripts/test_montage_render.py`

**Interfaces:**
- Consumes: `workspace.resolve_workspace_paths`, `workspace.MAX_ASSET_BYTES`; `authoring_support.open_store/open_assets`; `store.ProjectStore.project_dir/load`, `store.RevisionConflict`; `engine.require_engine/load_pin/Engine`; `engine_cli.EngineRunner/frames_cache`; `media_sync.check_composition`; `model.read_model/model_hash/Model`; `model_diff.diff_models`; `montage_state.check_writable/montage_section/record_version`; `versions.*`; `paths.render_output`; `probe.probe_media/MediaInfo`; `canvas.Canvas`; `html_doc.element_attrs/ROOT_ID`.
- Produces:
  - `@dataclass(frozen=True) context.ProjectContext(workspace, project_id, store, assets, state, project_dir, media_root)` со свойствами `paths`, `revision`, `mode` и методами `resolve(asset_id) -> Path`, `scene_names() -> {scene_id: "сцены N «Название»"}`; `context.open_context(workspace, project_id) -> ProjectContext`.
  - `verify.FONT_MARKERS`, `verify.SCRIPT_MARKERS`; `verify.network_markers(log_text) -> list[str]` (все следы сети — в `warnings` версии); `verify.unexpected_network(log_text) -> list[str]` (только CDN-скрипты — это ошибка; подкачка Inter с Google Fonts — известное ограничение HyperFrames); `verify.lint_problems(report) -> list[str]`; `verify.output_problems(info, *, duration, canvas, needs_audio) -> list[str]`; `verify.DURATION_TOLERANCE = 0.1`.
  - `@dataclass(frozen=True) render.RenderOutcome(version, asset_id, path, duration, changes: list, warnings: list, revision)`.
  - `render.render_version(ctx, expected_revision, *, by=None, summary=None, engine=None, runner=None, probe=probe_media) -> RenderOutcome`. Лог рендера — `montage/.logs/render-vNNN.log`; `warnings` — строки лога со следами сети.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_render.py`:

```python
#!/usr/bin/env python3
"""Сборка: v001 → ассет result → assembly; ошибка на любом шаге — ни версии, ни файла."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import (FakeHyperframes, fake_engine, seed_workspace, tiny_mp4,  # noqa: E402
                             tiny_wav, video_state)
from studio.authoring_support import open_assets, open_store  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.context import open_context  # noqa: E402
from studio.montage.draft import build_current  # noqa: E402
from studio.montage.edit import EditRequest, apply_edit  # noqa: E402
from studio.montage.html_doc import set_attr  # noqa: E402
from studio.montage.montage_state import record_draft  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402
from studio.montage.render import render_version  # noqa: E402
from studio.montage.verify import network_markers, unexpected_network  # noqa: E402
from studio.montage.versions import read_meta  # noqa: E402
from studio.store import RevisionConflict  # noqa: E402


class RenderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        files = {"a.mp4": tiny_mp4(b"a"), "b.mp4": tiny_mp4(b"b"), "v.wav": tiny_wav()}
        self.seed = seed_workspace(base, files, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"]),
             ("s2", "Клубок", "Находит клубок", 2000, ids["b.mp4"])], audio={"voice": ids["v.wav"]}))
        self.infos = {"a.mp4": MediaInfo(2.0, 108, 192, True, True),
                      "b.mp4": MediaInfo(1.5, 108, 192, True, False),
                      "v.wav": MediaInfo(5.0, None, None, False, True)}
        self.output_info = MediaInfo(3.5, 108, 192, True, True)
        self.engine = fake_engine(base / "engine")
        ctx = open_context(self.seed.workspace, "p")
        build_current(ctx.paths, ctx.state, ctx.resolve, probe=self.probe)
        record_draft(ctx.store, "p", 0, canvas=Canvas(108, 192))
        self.output = self.seed.workspace.resolve() / "media" / "p" / "montage" / "v001.mp4"

    def probe(self, path):
        return self.infos.get(Path(path).name, self.output_info)

    def render(self, runner=None, **kwargs):
        ctx = open_context(self.seed.workspace, "p")
        runner = runner or FakeHyperframes(render_bytes=tiny_mp4(b"out-1"))
        return render_version(ctx, ctx.revision, engine=self.engine, runner=runner,
                              probe=self.probe, **kwargs)

    def state(self):
        return open_store(self.seed.workspace).load("p")

    def test_first_render_is_v001_and_becomes_the_assembly(self):
        outcome = self.render()
        self.assertEqual((outcome.version, Path(outcome.path)), ("v001", self.output))
        self.assertTrue(self.output.is_file())
        self.assertEqual(open_assets(self.seed.workspace).role_of(outcome.asset_id), "result")
        state = self.state()
        self.assertEqual(state["montage"]["current_version"], "v001")
        self.assertEqual(state["assembly"]["asset_id"], outcome.asset_id)
        self.assertEqual(outcome.changes, ["черновой монтаж: 5 клипов, 3,5 с"])
        self.assertEqual(outcome.warnings, [])
        meta = read_meta(open_context(self.seed.workspace, "p").paths, "v001")
        self.assertEqual((meta.by, meta.based_on, meta.summary), ("agent", None, "Черновой монтаж"))

    def test_second_render_tells_what_changed(self):
        self.render()
        ctx = open_context(self.seed.workspace, "p")
        apply_edit(self.engine, ctx.paths, EditRequest(op="trim-start", clip="v-1", seconds=0.5),
                   runner=FakeHyperframes())
        outcome = self.render(FakeHyperframes(render_bytes=tiny_mp4(b"out-2")))
        self.assertEqual(outcome.version, "v002")
        self.assertEqual(outcome.changes, ["клип сцены 1 «Сад»: начало обрезано на 0,5 с"])
        meta = read_meta(ctx.paths, "v002")
        self.assertEqual((meta.based_on, meta.summary), ("v001", "клип сцены 1 «Сад»: начало обрезано на 0,5 с"))

    def test_lint_error_means_no_render_and_no_version(self):
        runner = FakeHyperframes(render_bytes=tiny_mp4(b"x"), lint_report={"ok": False, "findings": [
            {"severity": "error", "code": "missing_local_asset", "message": "нет файла"}]})
        with self.assertRaises(MontageError) as caught:
            self.render(runner)
        self.assertIn("missing_local_asset", str(caught.exception))
        self.assertNotIn("render", [call[0] for call in runner.calls])
        self.assertFalse(self.output.exists())
        self.assertIsNone(self.state()["montage"]["current_version"])

    def test_external_url_is_refused_before_the_engine(self):
        ctx = open_context(self.seed.workspace, "p")
        text = ctx.paths.index.read_text(encoding="utf-8")
        ctx.paths.index.write_text(set_attr(text, "t-1", "style", "background:url(https://x.example/y.png)"),
                                   encoding="utf-8")
        runner = FakeHyperframes(render_bytes=tiny_mp4(b"x"))
        with self.assertRaises(MontageError) as caught:
            self.render(runner)
        self.assertIn("внешняя ссылка", str(caught.exception))
        self.assertEqual(runner.calls, [])

    def test_bad_output_is_deleted_and_not_recorded(self):
        self.output_info = MediaInfo(2.0, 108, 192, True, True)
        with self.assertRaises(MontageError) as caught:
            self.render()
        self.assertIn("длительность", str(caught.exception))
        self.assertFalse(self.output.exists())
        self.assertEqual(self.state()["montage"]["versions"], [])

    def test_failed_render_is_a_clear_message(self):
        with self.assertRaises(MontageError) as caught:
            self.render(FakeHyperframes(render_bytes=None))
        self.assertIn("Сборка не удалась", str(caught.exception))
        self.assertTrue((open_context(self.seed.workspace, "p").paths.logs / "render-v001.log").is_file())

    def test_stale_revision_is_refused_before_any_work(self):
        ctx = open_context(self.seed.workspace, "p")
        runner = FakeHyperframes(render_bytes=tiny_mp4(b"x"))
        with self.assertRaises(RevisionConflict):
            render_version(ctx, ctx.revision - 1, engine=self.engine, runner=runner, probe=self.probe)
        self.assertEqual(runner.calls, [])

    def test_network_traces_become_warnings(self):
        runner = FakeHyperframes(render_bytes=tiny_mp4(b"x"), render_log=(
            '[INFO] [Compiler] Fetched 11 font face(s) for "Inter" from Google Fonts'))
        self.assertEqual(len(self.render(runner).warnings), 1)

    def test_known_font_fetch_is_not_unexpected_network(self):
        cdn = "[INFO] [Compiler] Inlined CDN script: https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
        log = '[INFO] [Compiler] Fetched 11 font face(s) for "Inter" from Google Fonts\n' + cdn
        self.assertEqual(len(network_markers(log)), 2)
        self.assertEqual(unexpected_network(log), [cdn])

    def test_autopilot_projects_sign_versions_as_autopilot(self):
        store = open_store(self.seed.workspace)

        def autopilot(state):
            state["project"]["mode"] = "autopilot"
        store.transact("p", 1, autopilot)
        self.render()
        self.assertEqual(read_meta(open_context(self.seed.workspace, "p").paths, "v001").by, "autopilot")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_render.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'studio.montage.context'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/context.py`:

```python
"""Всё о проекте, что нужно монтажу: хранилище, ассеты, state, папки, имена сцен."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..assets import AssetIndex
from ..authoring_support import open_assets, open_store
from ..store import ProjectStore
from ..workspace import resolve_workspace_paths
from .paths import MontagePaths, montage_paths


@dataclass(frozen=True)
class ProjectContext:
    workspace: Path
    project_id: str
    store: ProjectStore
    assets: AssetIndex
    state: dict
    project_dir: Path
    media_root: Path

    @property
    def paths(self) -> MontagePaths:
        return montage_paths(self.project_dir)

    @property
    def revision(self) -> int:
        return self.state.get("revision")

    @property
    def mode(self) -> str:
        return (self.state.get("project") or {}).get("mode", "guided")

    def resolve(self, asset_id: str) -> Path:
        return self.assets.resolve(asset_id)[0]

    def scene_names(self) -> dict[str, str]:
        scenes = sorted(self.state.get("scenes", []), key=lambda scene: scene.get("order", 0))
        return {scene["scene_id"]: f"сцены {index} «{scene.get('title') or scene['scene_id']}»"
                for index, scene in enumerate(scenes, start=1)}


def open_context(workspace, project_id: str) -> ProjectContext:
    workspace_path, _projects, media_root, _private = resolve_workspace_paths(workspace)
    store = open_store(workspace_path)
    return ProjectContext(workspace=workspace_path, project_id=project_id, store=store,
                          assets=open_assets(workspace_path), state=store.load(project_id),
                          project_dir=store.project_dir(project_id), media_root=media_root)
```

`skills/aimaster/studio/montage/verify.py`:

```python
"""Проверки сборки: ошибки lint, выход ffprobe, следы сетевых запросов в логе рендера."""

from __future__ import annotations

from .canvas import Canvas
from .probe import MediaInfo

# HyperFrames 0.8.75 сам подменяет первичное sans-serif на Inter и докачивает его
# кириллицу с Google Fonts, если есть сеть (без сети берёт системный шрифт): это
# известное ограничение, а не ошибка черновика. CDN-скрипт — всегда ошибка.
FONT_MARKERS = ("from Google Fonts", "fonts.googleapis.com", "FONT_FETCH")
SCRIPT_MARKERS = ("Inlined CDN script", "Failed to download CDN script", "cdn.jsdelivr.net")
DURATION_TOLERANCE = 0.1  # три кадра при 30 к/с: контейнер округляет длину по кадрам и звуку


def _lines(log_text: str, markers) -> list[str]:
    return [line.strip()[:300] for line in (log_text or "").splitlines()
            if any(marker in line for marker in markers)]


def network_markers(log_text: str) -> list[str]:
    return _lines(log_text, FONT_MARKERS + SCRIPT_MARKERS)


def unexpected_network(log_text: str) -> list[str]:
    return _lines(log_text, SCRIPT_MARKERS)


def lint_problems(report: dict) -> list[str]:
    problems = [f"{item.get('code')}: {item.get('message')}"
                for item in report.get("findings") or [] if item.get("severity") == "error"]
    if report.get("ok") is False and not problems:
        problems.append("lint не прошёл, но не назвал ошибок")
    return problems


def output_problems(info: MediaInfo, *, duration: float, canvas: Canvas,
                    needs_audio: bool) -> list[str]:
    problems = []
    if not info.has_video:
        problems.append("в файле нет видео")
    if abs(info.duration - duration) > DURATION_TOLERANCE:
        problems.append(f"длительность {info.duration:.2f} с вместо {duration:.2f} с")
    if (info.width, info.height) != (canvas.width, canvas.height):
        problems.append(f"кадр {info.width}×{info.height} вместо {canvas.width}×{canvas.height}")
    if needs_audio and not info.has_audio:
        problems.append("в ролике нет звука, хотя в монтаже есть звуковые клипы")
    return problems
```

`skills/aimaster/studio/montage/render.py`:

```python
"""Сборка версии: ссылки композиции → lint → MP4 → ffprobe → ассет с ролью result в
media/<проект>/montage/vNNN.mp4 → снимок версии → state (montage + assembly) одной
транзакцией. Ошибка на любом шаге — версии нет, свой MP4 удалён, текущая версия та же.
Сборка локальная и бесплатная: разрешения на трату не нужно (`assemble` вне
GRANT_REQUIRED_ACTIONS)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..store import RevisionConflict
from ..workspace import MAX_ASSET_BYTES
from . import AUDIO_LAYER_NAMES, MontageError
from .canvas import Canvas
from .context import ProjectContext
from .engine import Engine, load_pin, require_engine
from .engine_cli import EngineRunner, frames_cache
from .html_doc import ROOT_ID, element_attrs
from .media_sync import check_composition
from .model import Model, model_hash, read_model
from .model_diff import diff_models
from .montage_state import check_writable, montage_section, record_version
from .paths import render_output
from .probe import probe_media
from .verify import lint_problems, network_markers, output_problems
from .versions import (BY_VALUES, VersionMeta, discard_staging, next_version_id, publish_version,
                       read_version_model, stage_version)


@dataclass(frozen=True)
class RenderOutcome:
    version: str
    asset_id: str
    path: str
    duration: float
    changes: list
    warnings: list
    revision: int


def _canvas(html_text: str) -> Canvas:
    root = element_attrs(html_text).get(ROOT_ID, {})
    return Canvas(int(root.get("data-width") or 1080), int(root.get("data-height") or 1920))


def _summary(base: str | None, changes: list[str]) -> str:
    if base is None:
        return "Черновой монтаж"
    if not changes:
        return "Пересборка без изменений"
    more = f" и ещё {len(changes) - 3}" if len(changes) > 3 else ""
    return "; ".join(changes[:3]) + more


def _preflight(ctx, engine, runner) -> tuple[Model, str]:
    html_text = ctx.paths.index.read_text(encoding="utf-8")
    problems = check_composition(html_text, ctx.paths.current)
    if problems:
        raise MontageError("Монтаж нельзя собрать: " + "; ".join(problems))
    report = runner.json(engine, ["lint", ".", "--json"], cwd=ctx.paths.current,
                         timeout=load_pin()["timeouts"]["cli"], ok_codes=(0, 1))
    problems = lint_problems(report)
    if problems:
        raise MontageError("Проверка монтажа (lint) нашла ошибки: " + "; ".join(problems))
    return read_model(engine, ctx.paths.current, cache_dir=ctx.paths.cache, runner=runner), html_text


def _render(ctx, engine, runner, version_id) -> tuple[Path, str]:
    pin = load_pin()
    output = render_output(ctx.media_root, ctx.project_id, version_id)
    if output.exists():
        raise MontageError(f"{output.name} уже есть — версии не перезаписываются")
    output.parent.mkdir(parents=True, exist_ok=True)
    result = runner.run(engine, ["render", ".", "--output", str(output), "--quality",
                                 pin["render_quality"], "--frames-cache-dir",
                                 str(frames_cache(engine)), "--quiet"],
                        cwd=ctx.paths.current, timeout=pin["timeouts"]["render"])
    log = f"{result.stdout}\n{result.stderr}"
    ctx.paths.logs.mkdir(parents=True, exist_ok=True)
    (ctx.paths.logs / f"render-{version_id}.log").write_text(log, encoding="utf-8")
    if result.code != 0 or not output.is_file():
        output.unlink(missing_ok=True)
        why = "не уложилась по времени" if result.timed_out else (result.stderr or result.stdout).strip()[-500:]
        raise MontageError(f"Сборка не удалась: {why}")
    return output, log


def _checked_asset(ctx, output: Path, model: Model, html_text: str, probe) -> tuple[str, float]:
    try:
        info = probe(output)
        needs_audio = any(clip.layer in AUDIO_LAYER_NAMES for clip in model.clips)
        problems = output_problems(info, duration=model.duration, canvas=_canvas(html_text),
                                   needs_audio=needs_audio)
        if problems:
            raise MontageError("Собранный ролик не прошёл проверку: " + "; ".join(problems))
        if output.stat().st_size > MAX_ASSET_BYTES:
            raise MontageError(f"Ролик больше {MAX_ASSET_BYTES // 2 ** 20} МБ — такой файл студия "
                               "не примет; сократите монтаж")
        asset = ctx.assets.register(output.relative_to(ctx.workspace).as_posix(), "result")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return asset["asset_id"], info.duration


def render_version(ctx: ProjectContext, expected_revision: int, *, by: str | None = None,
                   summary: str | None = None, engine: Engine | None = None, runner=None,
                   probe=probe_media) -> RenderOutcome:
    if ctx.revision != expected_revision:
        raise RevisionConflict(expected_revision, ctx.revision)
    check_writable(ctx.state)
    if by is not None and by not in BY_VALUES:
        raise MontageError(f"--by: одно из {', '.join(BY_VALUES)}")
    if not ctx.paths.index.is_file():
        raise MontageError("черновика ещё нет: сначала montage draft")
    engine = engine or require_engine()
    runner = runner or EngineRunner()
    model, html_text = _preflight(ctx, engine, runner)
    base = montage_section(ctx.state)["current_version"]
    version_id = next_version_id(ctx.paths)
    output, log = _render(ctx, engine, runner, version_id)
    asset_id, duration = _checked_asset(ctx, output, model, html_text, probe)
    old = read_version_model(ctx.paths, base) if base else None
    changes = diff_models(old, model, names=ctx.scene_names())
    meta = VersionMeta(version=version_id,
                       created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       by=by or ("autopilot" if ctx.mode == "autopilot" else "agent"),
                       based_on=base, summary=summary or _summary(base, changes),
                       changes=tuple(changes), asset_id=asset_id, model_hash=model_hash(model))
    staging = stage_version(ctx.paths, meta, model)
    try:
        written = record_version(ctx.store, ctx.assets, ctx.project_id, expected_revision, meta=meta)
    except BaseException:
        discard_staging(staging)
        output.unlink(missing_ok=True)
        raise
    publish_version(ctx.paths, staging, version_id)
    return RenderOutcome(version_id, asset_id, str(output), duration, changes,
                         network_markers(log), written["revision"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_render.py' -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/context.py skills/aimaster/studio/montage/verify.py skills/aimaster/studio/montage/render.py skills/aimaster/scripts/test_montage_render.py
git commit -m "feat(montage): render a checked MP4 version and make it the assembly"
```

---

### Task 16: Монтажный стол — `Desk` и `StudioDesk`

**Files:**
- Create: `skills/aimaster/studio/montage/proc.py`
- Create: `skills/aimaster/studio/montage/desk.py`
- Test: `skills/aimaster/scripts/test_montage_desk.py`

**Interfaces:**
- Consumes: `engine_cli.popen_engine(engine, args, *, cwd, log_path, popen=...)`; `engine.load_pin()["timeouts"]["preview_start"]`; `paths.MontagePaths` (`desk_file`, `logs`, `current`, `index`); `platform_compat.IS_WINDOWS`; `MontageError`.
- Produces:
  - `proc.process_alive(pid: int) -> bool`; `proc.kill_tree(pid: int, *, run=subprocess.run, wait: float = 5.0) -> None`; `proc.taskkill_path() -> str`.
  - `desk.Desk` (Protocol: `open(paths) -> dict`, `close(paths) -> dict`, `status(paths) -> dict`).
  - `desk.free_port() -> int`; `desk.port_answers(port, timeout=1.0) -> bool`.
  - `class desk.StudioDesk(engine: Engine | None, *, popen=None, clock=time.monotonic, sleep=time.sleep, alive=process_alive, answers=port_answers, kill=kill_tree)`; ответы: `{"state": "open", "url", "port", "pid", "started_at"}` или `{"state": "closed"}`; запись `montage/.desk.json` — `{"pid", "port", "url", "started_at"}`.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_desk.py`:

```python
#!/usr/bin/env python3
"""Монтажный стол: один процесс preview на проект, адрес из его JSON, остановка с детьми."""

from __future__ import annotations

import json
import subprocess
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

from montage_testkit import fake_engine  # noqa: E402
from studio.montage import MontageError, proc  # noqa: E402
from studio.montage.desk import StudioDesk, port_answers  # noqa: E402
from studio.montage.engine import Engine  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402

FAKE_PREVIEW = r'''
import json, socket, sys
port = int(sys.argv[sys.argv.index("--port") + 1])
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", port))
server.listen(5)
print(json.dumps({"schemaVersion": 1, "operation": "start", "ok": True, "result": {
    "state": "started", "port": port, "studioUrl": f"http://127.0.0.1:{port}/#project/current",
    "ready": True}}), flush=True)
while True:
    connection, _ = server.accept()
    connection.close()
'''


class _Draft(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.paths = montage_paths(self.base / "p")
        self.paths.current.mkdir(parents=True)
        self.paths.index.write_text("<html></html>", encoding="utf-8")
        self.killed = []


class DeskUnitTests(_Draft):
    def popen_ready(self, argv, **kwargs):
        self.argv = argv
        port = int(argv[argv.index("--port") + 1])
        line = {"ok": True, "result": {"port": port, "ready": True,
                                       "studioUrl": f"http://127.0.0.1:{port}/#project/current"}}
        kwargs["stdout"].write((json.dumps(line) + "\n").encode())
        return mock.Mock(pid=4242, poll=mock.Mock(return_value=None))

    def desk(self, popen, alive=True, clock=time.monotonic):
        return StudioDesk(fake_engine(self.base / "engine"), popen=popen, clock=clock,
                          sleep=lambda seconds: None, alive=lambda pid: alive,
                          answers=lambda port: alive, kill=self.killed.append)

    def test_open_writes_the_record_and_reuses_it(self):
        first = self.desk(self.popen_ready).open(self.paths)
        self.assertEqual(first["state"], "open")
        self.assertTrue(first["url"].startswith("http://127.0.0.1:"))
        self.assertEqual(self.argv[2:7], ["preview", ".", "--foreground", "--json", "--no-open"])
        self.assertTrue(self.paths.desk_file.is_file())
        second = self.desk(lambda *a, **k: self.fail("второй процесс не нужен")).open(self.paths)
        self.assertEqual((second["url"], second["pid"]), (first["url"], 4242))

    def test_dead_process_means_closed_and_forgotten(self):
        self.desk(self.popen_ready).open(self.paths)
        self.assertEqual(self.desk(self.popen_ready, alive=False).status(self.paths), {"state": "closed"})
        self.assertFalse(self.paths.desk_file.exists())

    def test_close_kills_and_forgets(self):
        self.desk(self.popen_ready).open(self.paths)
        self.assertEqual(self.desk(self.popen_ready).close(self.paths), {"state": "closed"})
        self.assertEqual(self.killed, [4242])
        self.assertFalse(self.paths.desk_file.exists())

    def test_start_timeout_kills_and_explains(self):
        ticks = iter([0, 0, 100, 100, 100])
        silent = lambda argv, **kwargs: mock.Mock(pid=77, poll=mock.Mock(return_value=None))  # noqa: E731
        with self.assertRaises(MontageError) as caught:
            self.desk(silent, alive=False, clock=lambda: next(ticks)).open(self.paths)
        self.assertIn("не запустился", str(caught.exception))
        self.assertEqual(self.killed, [77])

    def test_no_draft_no_desk(self):
        self.paths.index.unlink()
        with self.assertRaises(MontageError):
            self.desk(self.popen_ready).open(self.paths)

    def test_windows_stop_uses_taskkill_by_full_path(self):
        calls = []
        with mock.patch.object(proc, "IS_WINDOWS", True), \
                mock.patch.object(proc, "process_alive", return_value=True):
            proc.kill_tree(4242, run=lambda argv, **kwargs: calls.append((argv, kwargs)))
        argv, kwargs = calls[0]
        self.assertTrue(argv[0].lower().endswith("system32\\taskkill.exe")
                        or argv[0].lower().endswith("system32/taskkill.exe"))
        self.assertEqual(argv[1:], ["/PID", "4242", "/T", "/F"])
        self.assertNotIn("shell", kwargs)


class DeskRealProcessTests(_Draft):
    def test_detached_preview_is_found_and_stopped(self):
        script = self.base / "fake_preview.py"
        script.write_text(FAKE_PREVIEW, encoding="utf-8")
        engine = Engine(node=sys.executable, script=script, prefix=self.base / "engine",
                        version="0.8.75", browser=None)
        desk = StudioDesk(engine)
        opened = desk.open(self.paths)
        try:
            self.assertEqual(desk.status(self.paths)["state"], "open")
            self.assertTrue(port_answers(opened["port"]))
        finally:
            desk.close(self.paths)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and proc.process_alive(opened["pid"]):
            time.sleep(0.1)
        self.assertFalse(proc.process_alive(opened["pid"]))
        self.assertEqual(desk.status(self.paths), {"state": "closed"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_desk.py' -v`
Expected: FAIL — `ImportError: cannot import name 'proc'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/proc.py`:

```python
"""Жив ли процесс и как остановить его вместе с детьми — без оболочки."""

from __future__ import annotations

import os
import signal
import subprocess
import time

from ..platform_compat import IS_WINDOWS

STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _windows_alive(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return bool(ok) and code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def process_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if IS_WINDOWS:
        return _windows_alive(pid)
    try:
        reaped, _status = os.waitpid(pid, os.WNOHANG)  # свой завершившийся ребёнок — прибрать
        if reaped == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def taskkill_path() -> str:
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or "C:\\Windows"
    return os.path.join(root, "System32", "taskkill.exe")


def kill_tree(pid: int, *, run=subprocess.run, wait: float = 5.0) -> None:
    """Windows — taskkill /T /F по полному пути; POSIX — сигнал группе: процесс стола
    запущен в своей сессии (start_new_session), его номер равен номеру группы."""

    if not process_alive(pid):
        return
    if IS_WINDOWS:
        run([taskkill_path(), "/PID", str(pid), "/T", "/F"], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline and process_alive(pid):
        time.sleep(0.1)
    if process_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
```

`skills/aimaster/studio/montage/desk.py`:

```python
"""Монтажный стол: интерфейс Desk и реализация StudioDesk — HyperFrames Studio в
соседней вкладке. Один процесс `preview` на проект; pid, порт и адрес — в
montage/.desk.json. Вариант 2 (свой стол внутри дашборда) — другая реализация того
же интерфейса. Остановка по простою и при выходе сервера дашборда — план Б.
"""

from __future__ import annotations

import json
import socket
import time
from datetime import datetime, timezone
from typing import Protocol

from . import MontageError
from .engine import Engine, load_pin
from .engine_cli import popen_engine
from .paths import MontagePaths
from .proc import kill_tree, process_alive


class Desk(Protocol):
    def open(self, paths: MontagePaths) -> dict: ...

    def close(self, paths: MontagePaths) -> dict: ...

    def status(self, paths: MontagePaths) -> dict: ...


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def port_answers(port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _read_record(paths: MontagePaths) -> dict | None:
    try:
        record = json.loads(paths.desk_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) and {"pid", "port", "url"} <= set(record) else None


def _ready_line(log_path) -> dict | None:
    """Первая строка `preview --json`: {"ok": true, "result": {"studioUrl", "ready": true, …}}."""

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if not line.strip().startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        result = payload.get("result") or {}
        if payload.get("ok") and result.get("ready") and result.get("studioUrl"):
            return result
    return None


class StudioDesk:
    def __init__(self, engine: Engine | None, *, popen=None, clock=time.monotonic,
                 sleep=time.sleep, alive=process_alive, answers=port_answers, kill=kill_tree):
        self.engine, self.popen, self.clock, self.sleep = engine, popen, clock, sleep
        self.alive, self.answers, self.kill = alive, answers, kill

    def status(self, paths: MontagePaths) -> dict:
        record = _read_record(paths)
        if record and self.alive(record["pid"]) and self.answers(record["port"]):
            return {"state": "open", **{key: record[key] for key in ("url", "port", "pid", "started_at")
                                        if key in record}}
        paths.desk_file.unlink(missing_ok=True)  # процесса нет — запись устарела
        return {"state": "closed"}

    def open(self, paths: MontagePaths) -> dict:
        if not paths.index.is_file():
            raise MontageError("черновика ещё нет: сначала montage draft")
        current = self.status(paths)
        if current["state"] == "open":
            return current
        if self.engine is None:
            raise MontageError("Монтажный движок не готов: монтажный стол не запустить")
        port, log = free_port(), paths.logs / "desk.log"
        extra = {} if self.popen is None else {"popen": self.popen}
        process = popen_engine(self.engine, ["preview", ".", "--foreground", "--json", "--no-open",
                                             "--port", str(port)],
                               cwd=paths.current, log_path=log, **extra)
        timeout = load_pin()["timeouts"]["preview_start"]
        deadline = self.clock() + timeout
        while self.clock() < deadline:
            ready = _ready_line(log)
            if ready:
                record = {"pid": process.pid, "port": int(ready.get("port") or port),
                          "url": ready["studioUrl"],
                          "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                paths.desk_file.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
                return {"state": "open", **record}
            if process.poll() is not None:
                break
            self.sleep(0.2)
        self.kill(process.pid)
        tail = log.read_text(encoding="utf-8", errors="replace").strip()[-300:] if log.exists() else ""
        raise MontageError(f"Монтажный стол не запустился за {timeout} с: {tail}")

    def close(self, paths: MontagePaths) -> dict:
        record = _read_record(paths)
        if record and self.alive(record["pid"]):
            self.kill(record["pid"])
        paths.desk_file.unlink(missing_ok=True)
        return {"state": "closed"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_desk.py' -v`
Expected: PASS (7 tests; реальный процесс поднимается и останавливается на этой ОС).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/proc.py skills/aimaster/studio/montage/desk.py skills/aimaster/scripts/test_montage_desk.py
git commit -m "feat(montage): montage desk interface and HyperFrames Studio implementation"
```

---
### Task 17: Состояние монтажа и вход `service` для CLI и дашборда

**Files:**
- Create: `skills/aimaster/studio/montage/status.py`
- Create: `skills/aimaster/studio/montage/service.py`
- Test: `skills/aimaster/scripts/test_montage_service.py`

**Interfaces:**
- Consumes: `context.open_context/ProjectContext`; `engine.locate/require_engine/load_pin/Engine`; `draft.create_draft/rebuild_draft/refresh_draft/stale_clips/write_text_atomic`; `edit.EditRequest/apply_edit`; `model.read_model/model_hash/layers_view`; `model_diff.diff_models`; `montage_state.check_writable/montage_section/record_draft/record_restore`; `render.render_version`; `versions.list_versions/read_version_model/has_unrendered_changes/restore_files`; `desk.StudioDesk/Desk`; `store.RevisionConflict`; `assets.AssetError`; `probe.probe_media`.
- Produces:
  - `status.montage_status(ctx, engine: Engine | None, reason: str, *, runner=None, desk=None) -> dict` — форма ответа описана в разделе «Контракт для плана Б».
  - `service.DRAFT_MODES = ("new", "refresh", "rebuild")`.
  - `service.draft(workspace, project_id, expected_revision, *, mode="new", engine=None, runner=None, probe=None) -> {"project_id", "revision", "canvas", "duration", "clips", "current", "backup"}` (`backup` — путь прежнего черновика при `rebuild`, иначе `None`; для `refresh` — `{"project_id", "revision", "refreshed": [...]}`).
  - `service.status(workspace, project_id, *, locate=None, runner=None, desk=None) -> dict`.
  - `service.diff(workspace, project_id, *, against=None, engine=None, runner=None) -> {"project_id", "base", "model_hash", "changes", "unrendered_changes"}`.
  - `service.edit(workspace, project_id, expected_revision, request: EditRequest, *, expected_model_hash=None, engine=None, runner=None) -> dict` (поля `apply_edit` + `project_id`, `revision`).
  - `service.render(workspace, project_id, expected_revision, *, by=None, summary=None, engine=None, runner=None, probe=None) -> dict` (поля `RenderOutcome` + `project_id`).
  - `service.restore(workspace, project_id, expected_revision, version_id, *, actor="agent") -> {"project_id", "revision", "current_version", "backup"}`.
  - `service.open_desk(workspace, project_id, *, engine=None, desk=None) -> dict`; `service.close_desk(workspace, project_id, *, desk=None) -> dict`.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_service.py`:

```python
#!/usr/bin/env python3
"""Вход service: полный цикл черновик → сборка → правка → diff → сборка → возврат, без движка — понятный отказ."""

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

from montage_testkit import (FakeHyperframes, fake_engine, seed_workspace, tiny_mp4,  # noqa: E402
                             tiny_wav, video_state)
from studio.authoring_support import open_assets, open_store  # noqa: E402
from studio.montage import MontageError, service  # noqa: E402
from studio.montage.edit import EditRequest  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402
from studio.store import RevisionConflict  # noqa: E402


class ServiceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        files = {"a.mp4": tiny_mp4(b"a"), "b.mp4": tiny_mp4(b"b"), "c.mp4": tiny_mp4(b"c"),
                 "v.wav": tiny_wav()}
        self.seed = seed_workspace(Path(temp.name).resolve(), files, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"]),
             ("s2", "Клубок", "Находит клубок", 2000, ids["b.mp4"])], audio={"voice": ids["v.wav"]}))
        self.ws = self.seed.workspace
        self.infos = {"a.mp4": MediaInfo(2.0, 108, 192, True, True),
                      "b.mp4": MediaInfo(1.5, 108, 192, True, False),
                      "c.mp4": MediaInfo(1.0, 108, 192, True, True),
                      "v.wav": MediaInfo(5.0, None, None, False, True)}
        self.engine = fake_engine(Path(temp.name) / "engine")
        self.runner = FakeHyperframes(render_bytes=tiny_mp4(b"out-1"))

    def probe(self, path):
        return self.infos.get(Path(path).name, MediaInfo(3.5, 108, 192, True, True))

    def kw(self, probe=False):
        extra = {"probe": self.probe} if probe else {}
        return {"engine": self.engine, "runner": self.runner, **extra}

    def status(self):
        return service.status(self.ws, "p", locate=lambda: (self.engine, ""), runner=self.runner)

    def test_full_cycle(self):
        drafted = service.draft(self.ws, "p", 0, **self.kw(probe=True))
        self.assertEqual((drafted["revision"], drafted["canvas"], drafted["clips"]),
                         (1, {"width": 108, "height": 192}, 5))
        status = self.status()
        self.assertEqual((status["exists"], status["unrendered_changes"], status["engine"]["state"]),
                         (True, True, "installed"))
        self.assertEqual([layer["layer"] for layer in status["layers"]][:3], ["video", "titles", "voice"])
        first = service.render(self.ws, "p", 1, **self.kw(probe=True))
        self.assertEqual((first["version"], first["revision"]), ("v001", 2))
        self.assertIs(self.status()["unrendered_changes"], False)
        service.edit(self.ws, "p", 2, EditRequest(op="trim-start", clip="v-1", seconds=0.5), **self.kw())
        diff = service.diff(self.ws, "p", **self.kw())
        self.assertEqual((diff["base"], diff["changes"], diff["unrendered_changes"]),
                         ("v001", ["клип сцены 1 «Сад»: начало обрезано на 0,5 с"], True))
        self.runner.render_bytes = tiny_mp4(b"out-2")
        second = service.render(self.ws, "p", 2, **self.kw(probe=True))
        self.assertEqual(second["version"], "v002")
        restored = service.restore(self.ws, "p", 3, "v001")
        self.assertEqual((restored["current_version"], restored["revision"]), ("v001", 4))
        status = self.status()
        self.assertEqual((status["current_version"], status["unrendered_changes"]), ("v001", False))
        self.assertTrue(status["paths"]["output"].endswith("v001.mp4"))
        state = open_store(self.ws).load("p")
        self.assertEqual(state["assembly"]["asset_id"], first["asset_id"])
        self.assertEqual([h["kind"] for h in state["history"]],
                         ["montage-drafted", "montage-built", "montage-built", "montage-restored"])

    def test_status_without_engine_still_answers(self):
        status = service.status(self.ws, "p", locate=lambda: (None, "не найден Node.js"))
        self.assertEqual((status["engine"]["state"], status["engine"]["reason"], status["exists"]),
                         ("missing", "не найден Node.js", False))
        self.assertEqual((status["current_version"], status["versions"], status["desk"]),
                         (None, [], {"state": "closed"}))

    def test_draft_without_engine_refuses_and_writes_nothing(self):
        with mock.patch.object(service, "require_engine",
                               side_effect=MontageError("Монтажный движок не готов: не найден Node.js")):
            with self.assertRaises(MontageError):
                service.draft(self.ws, "p", 0, probe=self.probe)
        self.assertFalse((self.ws / "projects" / "p" / "montage").exists())

    def test_stale_revision_is_refused(self):
        with self.assertRaises(RevisionConflict):
            service.draft(self.ws, "p", 5, **self.kw(probe=True))

    def test_refresh_after_a_new_scene_video(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        store = open_store(self.ws)

        def new_video(state):
            for item in state["video_results"]:
                if item["scene_id"] == "s2":
                    item["asset_id"] = self.seed.ids["c.mp4"]
        store.transact("p", 1, new_video)
        self.assertEqual([item["clip"] for item in self.status()["stale_clips"]], ["v-2"])
        refreshed = service.draft(self.ws, "p", 2, mode="refresh", **self.kw(probe=True))
        self.assertEqual([item["clip"] for item in refreshed["refreshed"]], ["v-2"])
        self.assertEqual(self.status()["stale_clips"], [])

    def test_rebuild_keeps_the_edited_draft_as_backup(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        service.edit(self.ws, "p", 1, EditRequest(op="delete", clip="t-2"), **self.kw())
        rebuilt = service.draft(self.ws, "p", 1, mode="rebuild", **self.kw(probe=True))
        self.assertEqual(rebuilt["revision"], 2)
        self.assertNotIn('id="t-2"', Path(rebuilt["backup"]).read_text(encoding="utf-8"))
        titles = next(layer for layer in self.status()["layers"] if layer["layer"] == "titles")
        self.assertEqual([clip["id"] for clip in titles["clips"]], ["t-1", "t-2"])

    def test_restore_unknown_version(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        with self.assertRaises(MontageError):
            service.restore(self.ws, "p", 1, "v009")
        self.assertIsNotNone(open_assets(self.ws))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_service.py' -v`
Expected: FAIL — `ImportError: cannot import name 'service'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/studio/montage/status.py`:

```python
"""Состояние монтажа проекта одним словарём — для `montage status` и снапшота дашборда (план Б)."""

from __future__ import annotations

from ..assets import AssetError
from .context import ProjectContext
from .desk import StudioDesk
from .draft import stale_clips
from .engine import Engine, load_pin
from .model import layers_view, model_hash, read_model
from .montage_state import montage_section
from .versions import has_unrendered_changes, list_versions


def _base(ctx: ProjectContext, engine: Engine | None, reason: str) -> dict:
    section = montage_section(ctx.state) if "montage" in ctx.state else None
    return {
        "project_id": ctx.project_id, "revision": ctx.revision,
        "engine": {"state": "installed" if engine else "missing",
                   "version": engine.version if engine else None,
                   "wanted": load_pin()["version"], "reason": reason},
        "exists": ctx.paths.index.is_file(),
        "current_version": section["current_version"] if section else None,
        "versions": list(section["versions"]) if section else [],
        "canvas": section["canvas"] if section else None,
        "model_hash": None, "duration": None, "unrendered_changes": None, "layers": [],
        "stale_clips": [], "desk": {"state": "closed"},
        "paths": {"current": str(ctx.paths.current), "output": None},
    }


def montage_status(ctx: ProjectContext, engine: Engine | None, reason: str, *, runner=None,
                   desk=None) -> dict:
    result = _base(ctx, engine, reason)
    paths = ctx.paths
    if result["exists"]:
        result["stale_clips"] = stale_clips(paths.index.read_text(encoding="utf-8"), ctx.state)
        result["desk"] = (desk or StudioDesk(engine)).status(paths)
        if engine is not None:
            model = read_model(engine, paths.current, cache_dir=paths.cache, runner=runner)
            current = next((meta for meta in list_versions(paths)
                            if meta.version == result["current_version"]), None)
            result.update(model_hash=model_hash(model), duration=model.duration,
                          layers=layers_view(model),
                          unrendered_changes=has_unrendered_changes(model_hash(model), current))
    entry = next((item for item in result["versions"] if item["id"] == result["current_version"]), None)
    if entry is not None:
        try:
            result["paths"]["output"] = str(ctx.resolve(entry["asset_id"]))
        except (AssetError, OSError, ValueError):
            result["paths"]["output"] = None
    return result
```

`skills/aimaster/studio/montage/service.py`:

```python
"""Вход в монтаж для CLI (`creator_studio.py montage …`) и дашборда (план Б).

Каждая функция открывает проект заново: state и монтаж могли поменять дашборд,
Studio или другой агент. Меняющие функции сверяют expected_revision до работы."""

from __future__ import annotations

from dataclasses import asdict

from ..store import RevisionConflict
from . import MontageError
from .context import open_context
from .desk import StudioDesk
from .draft import create_draft, rebuild_draft, refresh_draft, write_text_atomic
from .edit import EditRequest, apply_edit
from .engine import locate as locate_engine
from .engine import require_engine
from .model import model_hash, read_model
from .model_diff import diff_models
from .montage_state import check_writable, montage_section, record_draft, record_restore
from .probe import probe_media
from .render import render_version
from .status import montage_status
from .versions import has_unrendered_changes, list_versions, read_version_model, restore_files

DRAFT_MODES = ("new", "refresh", "rebuild")


def _fresh(ctx, expected_revision: int) -> None:
    if ctx.revision != expected_revision:
        raise RevisionConflict(expected_revision, ctx.revision)
    check_writable(ctx.state)


def _current_meta(ctx):
    current = montage_section(ctx.state)["current_version"]
    return next((meta for meta in list_versions(ctx.paths) if meta.version == current), None)


def draft(workspace, project_id, expected_revision, *, mode="new", engine=None, runner=None,
          probe=None) -> dict:
    if mode not in DRAFT_MODES:
        raise MontageError(f"режим черновика — одно из {', '.join(DRAFT_MODES)}")
    ctx = open_context(workspace, project_id)
    _fresh(ctx, expected_revision)
    engine = engine or require_engine()
    probe = probe or probe_media
    if mode == "refresh":
        refreshed = refresh_draft(ctx.paths, ctx.state, ctx.resolve, probe=probe)
        return {"project_id": project_id, "revision": ctx.revision, "refreshed": refreshed}
    if mode == "rebuild":
        result, backup = rebuild_draft(ctx.paths, ctx.state, ctx.resolve, probe=probe)
    else:
        result, backup = create_draft(ctx.paths, ctx.state, ctx.resolve, probe=probe), None
    written = record_draft(ctx.store, project_id, expected_revision, canvas=result.canvas)
    return {"project_id": project_id, "revision": written["revision"],
            "canvas": result.canvas.to_dict(), "duration": result.duration, "clips": result.clips,
            "current": str(ctx.paths.current), "backup": str(backup) if backup else None}


def status(workspace, project_id, *, locate=None, runner=None, desk=None) -> dict:
    ctx = open_context(workspace, project_id)
    engine, reason = (locate or locate_engine)()
    return montage_status(ctx, engine, reason, runner=runner, desk=desk)


def diff(workspace, project_id, *, against=None, engine=None, runner=None) -> dict:
    ctx = open_context(workspace, project_id)
    if not ctx.paths.index.is_file():
        raise MontageError("черновика ещё нет: сначала montage draft")
    engine = engine or require_engine()
    model = read_model(engine, ctx.paths.current, cache_dir=ctx.paths.cache, runner=runner)
    base = against or montage_section(ctx.state)["current_version"]
    old = read_version_model(ctx.paths, base) if base else None
    return {"project_id": project_id, "base": base, "model_hash": model_hash(model),
            "changes": diff_models(old, model, names=ctx.scene_names()),
            "unrendered_changes": has_unrendered_changes(model_hash(model), _current_meta(ctx))}


def edit(workspace, project_id, expected_revision, request: EditRequest, *,
         expected_model_hash=None, engine=None, runner=None) -> dict:
    ctx = open_context(workspace, project_id)
    _fresh(ctx, expected_revision)
    result = apply_edit(engine or require_engine(), ctx.paths, request,
                        expected_model_hash=expected_model_hash, runner=runner)
    return {"project_id": project_id, "revision": ctx.revision, **result}


def render(workspace, project_id, expected_revision, *, by=None, summary=None, engine=None,
           runner=None, probe=None) -> dict:
    ctx = open_context(workspace, project_id)
    outcome = render_version(ctx, expected_revision, by=by, summary=summary, engine=engine,
                             runner=runner, probe=probe or probe_media)
    return {"project_id": project_id, **asdict(outcome)}


def restore(workspace, project_id, expected_revision, version_id, *, actor="agent") -> dict:
    ctx = open_context(workspace, project_id)
    _fresh(ctx, expected_revision)
    if version_id not in [item["id"] for item in montage_section(ctx.state)["versions"]]:
        raise MontageError(f"нет версии {version_id}")
    previous = ctx.paths.index.read_text(encoding="utf-8") if ctx.paths.index.is_file() else None
    backup = restore_files(ctx.paths, version_id)
    try:
        written = record_restore(ctx.store, ctx.assets, project_id, expected_revision,
                                 version_id=version_id, actor=actor)
    except BaseException:
        if previous is not None:
            write_text_atomic(ctx.paths.index, previous)
        raise
    return {"project_id": project_id, "revision": written["revision"],
            "current_version": version_id, "backup": str(backup) if backup else None}


def open_desk(workspace, project_id, *, engine=None, desk=None) -> dict:
    ctx = open_context(workspace, project_id)
    return {"project_id": project_id,
            **(desk or StudioDesk(engine or require_engine())).open(ctx.paths)}


def close_desk(workspace, project_id, *, desk=None) -> dict:
    ctx = open_context(workspace, project_id)
    return {"project_id": project_id, **(desk or StudioDesk(None)).close(ctx.paths)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_service.py' -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/studio/montage/status.py skills/aimaster/studio/montage/service.py skills/aimaster/scripts/test_montage_service.py
git commit -m "feat(montage): montage status and service entry points for CLI and dashboard"
```

---

### Task 18: CLI `creator_studio.py montage …`

**Files:**
- Create: `skills/aimaster/scripts/creator_studio_montage.py`
- Modify: `skills/aimaster/scripts/creator_studio.py` (импорт, `build_parser`, `MontageError` в `main`, докстринг)
- Test: `skills/aimaster/scripts/test_montage_cli.py`

**Interfaces:**
- Consumes: `service.draft/status/diff/edit/render/restore/open_desk/close_desk`; `edit.OPS/EditRequest`; `versions.BY_VALUES`; `MontageError`; `creator_studio.DOMAIN_ERROR_EXIT_CODE = 3`.
- Produces:
  - `creator_studio_montage.add_montage_subcommands(subparsers) -> None`.
  - Команды (флаг `--json` принимается у всех; вывод — всегда один JSON-объект):
    - `montage draft WS P --expected-revision N [--refresh | --rebuild]`
    - `montage status WS P`
    - `montage diff WS P [--against vNNN]`
    - `montage edit WS P OP [--clip ID] [--at S] [--seconds S] [--duration S] [--value V] [--fade-in S] [--fade-out S] [--text T] --expected-revision N [--expected-model-hash H]`
    - `montage render WS P --expected-revision N [--by agent|owner|autopilot] [--summary TEXT]`
    - `montage restore WS P VERSION --expected-revision N`
    - `montage open WS P`, `montage close WS P`
  - Код выхода 3 и одна строка `creator_studio.py: error: <текст>` на любой `MontageError`.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_cli.py`:

```python
#!/usr/bin/env python3
"""CLI montage: разбор аргументов, вызов service, JSON, код 3 без traceback."""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import creator_studio  # noqa: E402
import creator_studio_montage  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.edit import EditRequest  # noqa: E402


def parse(*argv):
    return creator_studio.build_parser().parse_args(list(argv))


class CliTests(unittest.TestCase):
    def test_every_subcommand_parses(self):
        args = parse("montage", "draft", "WS", "p", "--expected-revision", "3", "--refresh", "--json")
        self.assertEqual((args.subcommand, args.expected_revision, args.refresh, args.rebuild),
                         ("draft", 3, True, False))
        args = parse("montage", "edit", "WS", "p", "trim-start", "--clip", "v-1", "--seconds", "0.5",
                     "--expected-revision", "2", "--expected-model-hash", "abc")
        self.assertEqual((args.op, args.clip, args.seconds, args.expected_model_hash),
                         ("trim-start", "v-1", 0.5, "abc"))
        self.assertEqual(parse("montage", "restore", "WS", "p", "v001", "--expected-revision", "4").version,
                         "v001")
        for name in ("status", "diff", "open", "close"):
            self.assertEqual(parse("montage", name, "WS", "p").subcommand, name)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse("montage", "render", "WS", "p")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse("montage", "draft", "WS", "p", "--expected-revision", "1", "--refresh", "--rebuild")

    def run_handler(self, name, *argv):
        buffer = io.StringIO()
        with mock.patch.object(creator_studio_montage.service, name, return_value={"ok": 1}) as call, \
                redirect_stdout(buffer):
            args = parse("montage", *argv)
            args.handler(args)
        return call, json.loads(buffer.getvalue())

    def test_handlers_call_service_and_print_json(self):
        call, printed = self.run_handler("render", "render", "WS", "p", "--expected-revision", "2",
                                         "--by", "owner")
        self.assertEqual(printed, {"ok": 1})
        call.assert_called_once_with(Path("WS"), "p", 2, by="owner", summary=None)
        call, _ = self.run_handler("draft", "draft", "WS", "p", "--expected-revision", "0", "--rebuild")
        call.assert_called_once_with(Path("WS"), "p", 0, mode="rebuild")
        call, _ = self.run_handler("restore", "restore", "WS", "p", "v002", "--expected-revision", "7")
        call.assert_called_once_with(Path("WS"), "p", 7, "v002")
        call, _ = self.run_handler("open_desk", "open", "WS", "p")
        call.assert_called_once_with(Path("WS"), "p")

    def test_edit_builds_the_request(self):
        call, _ = self.run_handler("edit", "edit", "WS", "p", "volume", "--clip", "a-voice",
                                   "--value", "0.5", "--expected-revision", "3")
        call.assert_called_once_with(Path("WS"), "p", 3, EditRequest(op="volume", clip="a-voice", value=0.5),
                                     expected_model_hash=None)

    def test_domain_error_exits_3_without_traceback(self):
        errors = io.StringIO()
        with mock.patch.object(creator_studio_montage.service, "status",
                               side_effect=MontageError("Монтажный движок не готов: не найден Node.js")), \
                mock.patch.object(sys, "argv", ["creator_studio.py", "montage", "status", "WS", "p"]), \
                redirect_stderr(errors), self.assertRaises(SystemExit) as caught:
            creator_studio.main()
        self.assertEqual(caught.exception.code, 3)
        self.assertIn("не готов", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_cli.py' -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'creator_studio_montage'`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/scripts/creator_studio_montage.py`:

```python
"""`creator_studio.py montage …` — монтаж на HyperFrames (спецификация 2026-09-25).

draft | status | diff | edit <op> | render | restore <vNNN> | open | close.
Каждая команда печатает один JSON-объект (флаг --json принимается для
единообразия со спецификацией). Меняющие команды требуют --expected-revision.
Регистрирует creator_studio.build_parser; провайдеров и сети (кроме
127.0.0.1 монтажного стола) команды не трогают.
"""

from __future__ import annotations

import json
from pathlib import Path

from studio.montage import service
from studio.montage.edit import OPS, EditRequest
from studio.montage.versions import BY_VALUES


def _print(payload):
    print(json.dumps(payload, ensure_ascii=False))


def command_montage_draft(args):
    mode = "refresh" if args.refresh else "rebuild" if args.rebuild else "new"
    _print(service.draft(args.workspace, args.project, args.expected_revision, mode=mode))


def command_montage_status(args):
    _print(service.status(args.workspace, args.project))


def command_montage_diff(args):
    _print(service.diff(args.workspace, args.project, against=args.against))


def command_montage_edit(args):
    request = EditRequest(op=args.op, clip=args.clip, at=args.at, seconds=args.seconds,
                          duration=args.duration, value=args.value, fade_in=args.fade_in,
                          fade_out=args.fade_out, text=args.text)
    _print(service.edit(args.workspace, args.project, args.expected_revision, request,
                        expected_model_hash=args.expected_model_hash))


def command_montage_render(args):
    _print(service.render(args.workspace, args.project, args.expected_revision, by=args.by,
                          summary=args.summary))


def command_montage_restore(args):
    _print(service.restore(args.workspace, args.project, args.expected_revision, args.version))


def command_montage_open(args):
    _print(service.open_desk(args.workspace, args.project))


def command_montage_close(args):
    _print(service.close_desk(args.workspace, args.project))


def add_montage_subcommands(subparsers) -> None:
    montage = subparsers.add_parser("montage", help="монтаж ролика на HyperFrames")
    sub = montage.add_subparsers(dest="subcommand", required=True)

    def command(name, help_text, handler, *, writes=False):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("workspace", type=Path)
        parser.add_argument("project")
        parser.add_argument("--json", action="store_true", help="вывод JSON (включён всегда)")
        if writes:
            parser.add_argument("--expected-revision", required=True, type=int,
                                dest="expected_revision")
        parser.set_defaults(handler=handler)
        return parser

    draft = command("draft", "черновой монтаж из выбранных видео, звука и текста сцен",
                    command_montage_draft, writes=True)
    mode = draft.add_mutually_exclusive_group()
    mode.add_argument("--refresh", action="store_true", help="заменить только устаревшие клипы")
    mode.add_argument("--rebuild", action="store_true",
                      help="собрать черновик заново (прежний уходит в montage/.undo)")
    command("status", "состояние монтажа, версии, стол, движок", command_montage_status)
    diff = command("diff", "что изменилось с текущей (или указанной) версии", command_montage_diff)
    diff.add_argument("--against", default=None, help="версия vNNN для сравнения")
    edit = command("edit", "одна правка монтажа", command_montage_edit, writes=True)
    edit.add_argument("op", choices=OPS)
    edit.add_argument("--clip")
    for flag in ("--at", "--seconds", "--duration", "--value", "--fade-in", "--fade-out"):
        edit.add_argument(flag, type=float, dest=flag[2:].replace("-", "_"))
    edit.add_argument("--text")
    edit.add_argument("--expected-model-hash", dest="expected_model_hash")
    render = command("render", "собрать MP4 новой версией", command_montage_render, writes=True)
    render.add_argument("--by", choices=BY_VALUES)
    render.add_argument("--summary")
    restore = command("restore", "сделать версию текущей", command_montage_restore, writes=True)
    restore.add_argument("version")
    command("open", "открыть монтажный стол (HyperFrames Studio)", command_montage_open)
    command("close", "закрыть монтажный стол", command_montage_close)
```

Правки `skills/aimaster/scripts/creator_studio.py`:

- после строки `from creator_studio_workspace import add_workspace_subcommands  # noqa: E402`:

```python
from creator_studio_montage import add_montage_subcommands  # noqa: E402
from studio.montage import MontageError  # noqa: E402
```

- в `build_parser` после `add_workspace_subcommands(subparsers)`: `add_montage_subcommands(subparsers)`;
- в `main` в кортеж `except (...)` после `QuestionError,` добавить строку `MontageError,`;
- в докстринг модуля последним абзацем:

```
`montage draft|status|diff|edit|render|restore|open|close` (spec 2026-09-25)
is the HyperFrames montage of video/mixed projects — see
`skills/aimaster/scripts/creator_studio_montage.py` and `references/montage.md`.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_cli.py' -v`
Expected: PASS (4 tests). Затем: `python3 skills/aimaster/scripts/creator_studio.py montage --help` — печатает восемь подкоманд.

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/scripts/creator_studio_montage.py skills/aimaster/scripts/creator_studio.py skills/aimaster/scripts/test_montage_cli.py
git commit -m "feat(cli): creator_studio.py montage draft|status|diff|edit|render|restore|open|close"
```

---
### Task 19: Сквозной тест на настоящем движке, шаг монтажа в смоуке, CI на черновике навыка

**Files:**
- Create: `skills/aimaster/scripts/test_montage_e2e.py`
- Modify: `skills/aimaster/scripts/montage_ci_check.py` (композиция — из кода черновика, проверки — из `verify`/`media_sync`)
- Modify: `skills/aimaster/scripts/test_montage_ci_check.py`
- Modify: `skills/aimaster/scripts/smoke_clean_machine.py` (`run_refused`, `step_montage`, список шагов, докстринг)
- Modify: `.github/workflows/ci.yml` (шаг сквозного теста в `montage-engine`)

**Interfaces:**
- Consumes: всё из задач 1–18: `service.*`, `engine.locate`, `desk.port_answers`, `media_sync.external_references/missing_sources/sync_media`, `draft_plan.plan_draft`, `draft_html.render_draft_html`, `draft.HYPERFRAMES_CONFIG`, `canvas.canvas_for/Canvas`, `verify.lint_problems/network_markers/output_problems`, `montage_testkit.make_clip/make_tone/seed_workspace/video_state/ffmpeg_or_skip`.
- Produces: `montage_ci_check.build_draft(comp: Path) -> str` (вместо `COMPOSITION` и `external_urls`, которые удаляются); переменная окружения `AIMASTER_REQUIRE_ENGINE=1` — сквозной тест без движка падает, а не пропускается; шаг смоука «монтаж: статус и понятный отказ».

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_e2e.py`:

```python
#!/usr/bin/env python3
"""Сквозной монтаж на настоящем HyperFrames: черновик → сборка → правка → diff → сборка →
возврат → стол. Без движка — пропуск; на CI (AIMASTER_REQUIRE_ENGINE=1) — падение."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import montage_testkit  # noqa: E402
from montage_testkit import make_clip, make_tone, seed_workspace, video_state  # noqa: E402
from studio.montage import engine, service  # noqa: E402
from studio.montage.desk import port_answers  # noqa: E402
from studio.montage.edit import EditRequest  # noqa: E402
from studio.montage.media_sync import external_references  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import probe_media  # noqa: E402


class RealEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        found, reason = engine.locate()
        if found is None:
            message = f"монтажный движок не установлен: {reason}"
            if os.environ.get("AIMASTER_REQUIRE_ENGINE") == "1":
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        montage_testkit.ffmpeg_or_skip()

    def test_draft_render_edit_diff_restore_desk(self):
        with tempfile.TemporaryDirectory(prefix="aimaster-e2e-") as temp:
            base = Path(temp) / "проверка монтажа"
            sources = base / "исходники"
            files = {
                "a.mp4": make_clip(sources / "a.mp4", 2.0, size=(540, 960), color="red", freq=440).read_bytes(),
                "b.mp4": make_clip(sources / "b.mp4", 1.0, size=(540, 960), color="blue", freq=660).read_bytes(),
                "v.wav": make_tone(sources / "v.wav", 3.0).read_bytes(),
            }
            seed = seed_workspace(base, files, lambda ids: video_state(
                [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"]),
                 ("s2", "Клубок", "Находит клубок", 1000, ids["b.mp4"])], audio={"voice": ids["v.wav"]}))
            ws = seed.workspace
            drafted = service.draft(ws, "p", 0)
            index = montage_paths(ws.resolve() / "projects" / "p").index
            self.assertEqual(external_references(index.read_text(encoding="utf-8")), [])
            self.assertEqual(drafted["canvas"], {"width": 540, "height": 960})

            first = service.render(ws, "p", drafted["revision"])
            info = probe_media(Path(first["path"]))
            self.assertAlmostEqual(info.duration, 3.0, delta=0.1)
            self.assertEqual((info.width, info.height, info.has_audio), (540, 960, True))
            unexpected = [line for line in first["warnings"] if "Google Fonts" not in line]
            self.assertEqual(unexpected, [], "сборка тянула из сети что-то кроме шрифта Inter")

            service.edit(ws, "p", first["revision"], EditRequest(op="trim-start", clip="v-1", seconds=0.5))
            status = service.status(ws, "p")
            video = next(layer for layer in status["layers"] if layer["layer"] == "video")
            self.assertEqual(video["clips"][0]["media_start"], 0.5)
            self.assertIs(status["unrendered_changes"], True)
            self.assertEqual(service.diff(ws, "p")["changes"],
                             ["клип сцены 1 «Сад»: начало обрезано на 0,5 с"])

            second = service.render(ws, "p", first["revision"])
            self.assertEqual(second["version"], "v002")
            service.restore(ws, "p", second["revision"], "v001")
            status = service.status(ws, "p")
            self.assertEqual((status["current_version"], status["unrendered_changes"]), ("v001", False))

            desk = service.open_desk(ws, "p")
            try:
                self.assertTrue(desk["url"].startswith("http://127.0.0.1:"))
                self.assertTrue(port_answers(desk["port"]))
            finally:
                service.close_desk(ws, "p")


if __name__ == "__main__":
    unittest.main()
```

`skills/aimaster/scripts/test_montage_ci_check.py` заменить целиком:

```python
#!/usr/bin/env python3
"""Проверка движка для CI: без движка — понятный JSON; черновик навыка готов к сборке без сети."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import montage_ci_check  # noqa: E402
import montage_testkit  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.media_sync import external_references, missing_sources  # noqa: E402


class CiCheckTests(unittest.TestCase):
    def test_missing_engine_is_json_not_traceback(self):
        buffer = io.StringIO()
        with mock.patch.object(montage_ci_check, "require_engine",
                               side_effect=MontageError("Монтажный движок не готов: не найден Node.js")), \
                redirect_stdout(buffer):
            code = montage_ci_check.main(["--json"])
        report = json.loads(buffer.getvalue())
        self.assertEqual(code, 1)
        self.assertIs(report["ok"], False)
        self.assertIn("не готов", report["problems"][0])

    def test_skill_draft_is_ready_for_an_offline_build(self):
        montage_testkit.ffmpeg_or_skip()
        with tempfile.TemporaryDirectory() as temp:
            comp = Path(temp) / "проверка монтажа" / "ролик 1"
            html_text = montage_ci_check.build_draft(comp)
            self.assertEqual(external_references(html_text), [])
            self.assertEqual(missing_sources(html_text, comp), [])
        self.assertIn("data-no-timeline", html_text)
        self.assertNotIn("gsap", html_text.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_ci_check.py' -v`
Expected: FAIL — `AttributeError: module 'montage_ci_check' has no attribute 'build_draft'` (если ffmpeg есть; без ffmpeg — `skipped` у второго теста, тогда сначала сделать шаг 3 и проверить сквозным тестом).
Run: `AIMASTER_REQUIRE_ENGINE=1 python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_e2e.py' -v`
Expected на машине с движком из задачи 6: PASS уже сейчас — это проверка задач 7–18 на настоящем CLI; без движка — `AssertionError: монтажный движок не установлен`.

- [ ] **Step 3: Write minimal implementation**

`skills/aimaster/scripts/montage_ci_check.py` заменить целиком:

```python
#!/usr/bin/env python3
"""Проверка монтажного движка на CI: черновик 3 с из клипов ffmpeg, собранный кодом навыка.

    python skills/aimaster/scripts/montage_ci_check.py --json [--offline]

Черновик строится теми же модулями, что `montage draft` (plan_draft →
render_draft_html → sync_media), в папке с кириллицей и пробелами; затем lint,
рендер, ffprobe, проверка внешних ссылок композиции и следов сети в логе
рендера. --offline только помечает запуск: сеть отрезают снаружи (см.
.github/workflows/ci.yml).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import asdict
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS.parent), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import montage_testkit  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.canvas import Canvas, canvas_for  # noqa: E402
from studio.montage.draft import HYPERFRAMES_CONFIG  # noqa: E402
from studio.montage.draft_html import render_draft_html  # noqa: E402
from studio.montage.draft_plan import plan_draft  # noqa: E402
from studio.montage.engine import require_engine  # noqa: E402
from studio.montage.engine_cli import frames_cache, run_engine, run_engine_json  # noqa: E402
from studio.montage.media_sync import external_references, sync_media  # noqa: E402
from studio.montage.probe import probe_media  # noqa: E402
from studio.montage.verify import (FONT_MARKERS, lint_problems, network_markers,  # noqa: E402
                                   output_problems, unexpected_network)
from studio.platform_compat import ensure_utf8_stdio  # noqa: E402

SIZE = (540, 960)
DURATION = 3.0


def build_draft(comp: Path) -> str:
    sources = comp.parent / "исходники"
    files = {
        "clip-1": montage_testkit.make_clip(sources / "clip-1.mp4", 2.0, size=SIZE, color="red", freq=440),
        "clip-2": montage_testkit.make_clip(sources / "clip-2.mp4", 1.0, size=SIZE, color="blue", freq=660),
        "voice": montage_testkit.make_tone(sources / "voice.wav", DURATION, freq=220),
    }
    state = montage_testkit.video_state([("s1", "Сад", "Проверка монтажа", 2000, "clip-1"),
                                         ("s2", "Клубок", "Без сети", 1000, "clip-2")],
                                        audio={"voice": "voice"})
    infos = {name: probe_media(path) for name, path in files.items()}
    plan = plan_draft(state, infos.__getitem__)
    synced = sync_media(((name, files[name]) for name in plan.media_assets()), comp / "assets")
    html_text = render_draft_html(plan, canvas_for(infos[plan.first_video_asset()]),
                                  {name: item["src"] for name, item in synced.items()})
    (comp / "hyperframes.json").write_text(json.dumps(HYPERFRAMES_CONFIG, indent=2) + "\n",
                                           encoding="utf-8")
    (comp / "index.html").write_text(html_text, encoding="utf-8")
    return html_text


def check(offline: bool) -> dict:
    report = {"ok": False, "offline": offline, "problems": []}
    engine = require_engine()
    report["engine"] = engine.version
    with tempfile.TemporaryDirectory(prefix="aimaster-montage-") as temp:
        comp = Path(temp) / "проверка монтажа" / "ролик 1"
        html_text = build_draft(comp)
        report["external_urls"] = external_references(html_text)
        lint = run_engine_json(engine, ["lint", ".", "--json"], cwd=comp, timeout=120, ok_codes=(0, 1))
        report["lint_errors"] = lint_problems(lint)
        output = comp.parent / "итог ролика.mp4"
        started = time.monotonic()
        result = run_engine(engine, ["render", ".", "--output", str(output), "--quality", "draft",
                                     "--frames-cache-dir", str(frames_cache(engine)), "--quiet"],
                            cwd=comp, timeout=900)
        report["render_seconds"] = round(time.monotonic() - started, 1)
        log = result.stdout + "\n" + result.stderr
        report["network_markers"] = unexpected_network(log)
        report["known_network"] = [line for line in network_markers(log)
                                   if any(marker in line for marker in FONT_MARKERS)]
        if result.code != 0 or not output.is_file():
            tail = (result.stderr or result.stdout).strip()[-600:]
            report["problems"].append(f"рендер завершился с кодом {result.code}: {tail}")
        else:
            info = probe_media(output)
            report["probe"] = asdict(info)
            report["problems"] += output_problems(info, duration=DURATION, canvas=Canvas(*SIZE),
                                                  needs_audio=True)
    report["problems"] += [f"внешняя ссылка: {url}" for url in report["external_urls"]]
    report["problems"] += [f"lint: {error}" for error in report["lint_errors"]]
    report["problems"] += [f"сеть: {line}" for line in report["network_markers"]]
    report["ok"] = not report["problems"]
    return report


def main(argv=None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Проверка монтажного движка на CI.")
    parser.add_argument("--json", action="store_true", help="вывод JSON")
    parser.add_argument("--offline", action="store_true", help="пометить запуск без сети")
    args = parser.parse_args(argv)
    try:
        report = check(args.offline)
    except (MontageError, OSError, subprocess.SubprocessError, unittest.SkipTest) as error:
        report = {"ok": False, "offline": args.offline, "problems": [str(error)]}
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else "\n".join(["ОК" if report["ok"] else "НЕ ПРОЙДЕНО", *report["problems"]]))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

`skills/aimaster/scripts/smoke_clean_machine.py`:

- в докстринге фразу `(очередь отменяется) → сервер` заменить на `(очередь отменяется) → монтаж: статус и понятный отказ без видео или без движка → сервер`;
- после функции `run_json` добавить:

```python
def run_refused(env: dict, *argv) -> str:
    """Команда должна отказать кодом 3 (доменный отказ); возвращает stderr."""
    cmd = python_argv() + [str(item) for item in argv]
    proc = subprocess.run(cmd, env=env, cwd=str(SKILL), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, timeout=180)
    expect(proc.returncode == 3, "команда %s: ждали код 3, получили %s; stderr: %s"
           % (" ".join(str(a) for a in argv[:3]), proc.returncode, decode(proc.stderr)[-800:]))
    return decode(proc.stderr)
```

- после функции `step_autopilot` добавить:

```python
def step_montage(env: dict, workspace: Path) -> None:
    status = cli(env, "montage", "status", workspace, PROJECT, "--json")
    expect(status.get("exists") is False and status.get("current_version") is None,
           "montage status: неожиданная форма %s" % json.dumps(status, ensure_ascii=False)[:800])
    state = status["engine"]["state"]
    expect(state in ("installed", "missing"), "montage status: engine.state=%s" % state)
    err = run_refused(env, CLI, "montage", "draft", workspace, PROJECT,
                      "--expected-revision", status["revision"])
    wanted = "Монтажный движок не готов" if state == "missing" else "нет выбранного видео"
    expect(wanted in err and "Traceback" not in err,
           "montage draft: ждали отказ «%s», получили %s" % (wanted, err[-800:]))
    log("  монтаж: движок %s, черновик без видео отклонён понятной фразой" % state)
```

- в кортеж `steps` после строки `("автопилотный проект", …),` добавить:

```python
        ("монтаж: статус и понятный отказ", lambda: step_montage(env, workspace)),
```

В `.github/workflows/ci.yml`, задача `montage-engine`, после шага «Render a 3-second clip…» (перед шагом «Render without network») добавить:

```yaml
      - name: Montage end-to-end on the real engine (draft, render, edit, diff, restore, desk)
        env:
          AIMASTER_REQUIRE_ENGINE: "1"
        run: python -m unittest discover -s skills/aimaster/scripts -p "test_montage_e2e.py" -v
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_ci_check.py' -v`
Expected: PASS (2 tests; второй — skipped без ffmpeg).
Run: `AIMASTER_REQUIRE_ENGINE=1 python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_e2e.py' -v && python3 skills/aimaster/scripts/montage_ci_check.py --json && python3 skills/aimaster/scripts/smoke_clean_machine.py`
Expected: сквозной тест PASS; `montage_ci_check` — `"ok": true`, `"network_markers": []`; смоук — строка «монтаж: движок missing, черновик без видео отклонён понятной фразой» (в смоуке HOME подменён, движка там нет) и «✓ смоук пройден».

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit and watch CI**

```bash
git add skills/aimaster/scripts/test_montage_e2e.py skills/aimaster/scripts/montage_ci_check.py skills/aimaster/scripts/test_montage_ci_check.py skills/aimaster/scripts/smoke_clean_machine.py .github/workflows/ci.yml
git commit -m "test(montage): real-engine end-to-end, smoke montage step, CI builds the skill's own draft"
git push
gh run watch --exit-status
```
Expected: все задачи CI зелёные, в `montage · windows-latest` сквозной тест прошёл целиком (в том числе стол: `taskkill` остановил `preview`).

---

### Task 20: Канон — `montage.md`, сборка, автопилот, CLI, SKILL.md

**Files:**
- Create: `skills/aimaster/references/montage.md`
- Modify: `skills/aimaster/references/phases/06-assembly.md` (переписать)
- Modify: `skills/aimaster/references/autopilot.md` (шаг 6 и «Allowed stops»)
- Modify: `skills/aimaster/references/creator-studio.md` (раздел «Questions and assembly»)
- Modify: `skills/aimaster/SKILL.md` («Studio workflow»)
- Test: `skills/aimaster/scripts/test_montage_docs.py`

**Interfaces:**
- Consumes: `edit.OPS`; имена команд CLI из задачи 18.
- Produces: канон, по которому агент ведёт монтаж; тест, который держит канон согласованным с CLI.

- [ ] **Step 1: Write the failing test**

`skills/aimaster/scripts/test_montage_docs.py`:

```python
#!/usr/bin/env python3
"""Канон монтажа называет каждую команду и правку CLI и связан со входами навыка."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage.edit import OPS  # noqa: E402


class DocsTests(unittest.TestCase):
    def test_canon_names_every_command_and_edit(self):
        text = (_SKILL_ROOT / "references" / "montage.md").read_text(encoding="utf-8")
        for command in ("montage draft", "montage status", "montage diff", "montage edit",
                        "montage render", "montage restore", "montage open", "montage close",
                        "--refresh", "--rebuild", "--expected-revision", "--expected-model-hash"):
            self.assertIn(command, text)
        for op in OPS:
            self.assertIn(f"`{op}", text)

    def test_canon_is_linked_from_the_entry_points(self):
        for rel in ("SKILL.md", "references/creator-studio.md", "references/autopilot.md",
                    "references/phases/06-assembly.md"):
            self.assertIn("montage.md", (_SKILL_ROOT / rel).read_text(encoding="utf-8"), rel)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_docs.py' -v`
Expected: FAIL — `FileNotFoundError: … references/montage.md`.

- [ ] **Step 3: Write the canon**

`skills/aimaster/references/montage.md` (канон навыка пишется по-английски, как соседние файлы `references/`; фразы для человека — по-русски):

````markdown
# Montage

The assembly of `video` and `mixed` projects is a montage on HyperFrames, the
pinned open-source engine (`studio/montage/engine.json`). The montage lives in
`<project>/montage/current/index.html`; every build becomes an immutable
version `vNNN` with its MP4 in `<workspace>/media/<project>/montage/vNNN.mp4`,
registered as the `assembly`. Photo projects are not touched: their assembly is
the accepted image (`assembly set`).

## When to start

After every scene video (or the one-shot video) is chosen and `motion` and
`audio` are approved. The montage writes into the `assembly` stage and is
refused once `assembly` is approved.

## Engine check

Run `montage status WS P` first. `engine.state: installed` — go on.
`missing` — `engine.reason` says what is absent (Node.js 22+, HyperFrames
0.8.75 or its render browser). Say it in one sentence and give the command
`python3 <skill>/scripts/install.py --install-deps` (free and local, about
225 MB: the npm package and a headless Chrome). In `guided`, ask before running
it; in `autopilot` it is an allowed stop — installing software is outside the
autopilot authorization. Never run `npx hyperframes`, `hyperframes init`,
`npm install -g` or HyperFrames' own skill installer: the skill runs its pinned
engine itself.

## Commands

Every command prints one JSON object. Changing commands need
`--expected-revision N`; take it from `montage status`. A refusal exits with
code 3 and one Russian sentence: relay it as is.

| Command | What it does |
|---|---|
| `montage draft WS P --expected-revision N` | first draft from the chosen scene videos, sound layers and scene texts |
| `montage draft … --refresh` | replace only clips whose scene or layer got a new chosen result (`stale_clips` in `status`) |
| `montage draft … --rebuild` | build the draft again from the project; the previous `index.html` goes to `montage/.undo/` |
| `montage status WS P` | engine, versions, current version, `layers`, `model_hash`, `unrendered_changes`, `stale_clips`, desk, `paths.output` |
| `montage diff WS P [--against vNNN]` | Russian list of changes since the current (or given) version |
| `montage edit WS P OP … --expected-revision N [--expected-model-hash H]` | one edit (below) |
| `montage render WS P --expected-revision N [--by agent\|owner\|autopilot] [--summary "…"]` | reference check → lint → MP4 → checks → new version → assembly |
| `montage restore WS P vNNN --expected-revision N` | make an earlier version current again |
| `montage open WS P` / `montage close WS P` | start / stop the montage desk (HyperFrames Studio) |

Edit operations (`OP`):

- `move --clip ID --at S` — new start; moving past the end makes the video longer;
- `trim-start --clip ID --seconds S` — cut S seconds off the start (the source
  is cut too, exactly as the mouse does in Studio); a negative value gives them back;
- `trim-end --clip ID --duration S` — new length;
- `split --clip ID --at S` — cut in two at S seconds of the video;
- `delete --clip ID`;
- `volume --clip ID --value V` — 0…3.98, 1 = as recorded;
- `fade --clip ID [--fade-in S] [--fade-out S]` — soft sound edges; 0 removes;
- `title-add --text T --at S --duration S`; `title-text --clip ID --text T`;
- `undo` — take back your own last edit; refused if the montage changed after
  it (for example in the desk).

Clip ids come from `status.layers`: videos `v-N`, titles `t-N`, sound
`a-voice`, `a-music`, `a-fx`, `a-atmos`; a split piece gets `<id>-2`.

## What the draft contains

- videos in scenario order, each inside its scene window and never longer than
  its source; the chosen result of each position, not the newest file;
- sound layers voice / music / fx / atmos from 0 s; volumes 1.0 / 0.3 / 0.8 /
  0.5; music and atmosphere fade out over 1 s; scene videos play at 0.3 under
  sound layers and at 1.0 without them;
- titles = the active text of each scene;
- transition = 0.4 s fade-in of the next clip plus soft sound edges;
- no GSAP, no external URLs, no web fonts (`sans-serif`), root with
  `data-no-timeline`: a build works without the network.

## Guided flow

1. `montage draft` → `montage render` → show v1: the dashboard's assembly
   screen, or the path `status.paths.output`.
2. Wait. The user writes edits in chat (apply them with `montage edit`) or edits
   with the mouse in the desk (`montage open`, give the `url`).
3. On «собери» (or the dashboard prompt «Собрать ролик → чат»): `montage diff`,
   retell the changes, `montage render`, show the new version.
4. «Сделай текущей vN» / «верни прошлую» — `montage restore`. Versions are never
   deleted.
5. Approval stays the user's: `stage approve` only on their word.

## Autopilot flow

`montage draft` → `montage render` → review the MP4: duration, frame size and
sound are checked by the render itself; look at frames if a viewer is
available, otherwise say the visual check was not performed. Fix a visible
defect with `montage edit` and render again. Then `stage approve` and the final
report. No questions.

## Retelling a diff

`montage diff` returns ready Russian lines («клип сцены 1 «Сад»: начало
обрезано на 0,5 с»). Retell them briefly, grouped by scene, in plain words;
never paste ids or file names. Empty `changes` means nothing changed since the
last version: say so and do not build a duplicate. If the user edited in the
desk, say that you took their edits as they are.

## Montage desk

`montage open` starts HyperFrames Studio on 127.0.0.1 for this project and
returns `url`; open it in a new tab (host capability) or give the link. Edits
save to `current/index.html` by themselves. Studio's interface is English only.
When the user is done: `montage close`. Before your own edits while the desk
may be open, read `montage status` and pass its `model_hash` as
`--expected-model-hash`: a concurrent mouse edit then refuses your edit instead
of being overwritten.

## HyperFrames skills

The ten core HyperFrames skills of the same version are installed with this
skill. Use them only for what the draft does not do (animated titles, intros,
effects). This skill leads the montage: never start a new HyperFrames project,
never run `hyperframes init`, never install HyperFrames workflow skills
(`figma`, `slideshow`, …), never reference files outside `montage/current/`.
Animate with CSS `@keyframes` on the clip element: the HyperFrames runtime seeks
CSS animations frame by frame. GSAP from a CDN and web fonts need the network
and are refused by the build check.

## Rules

- The reference check and `lint` run before every build; a failure means no
  version: name the error and the clip.
- Never edit or delete anything in `montage/versions/` or a version's MP4.
- A failed build leaves no version and keeps the current one.
- After a new scene video is chosen, `status.stale_clips` lists the clips to
  update: `montage draft --refresh`.

## Known limitations

- Studio's interface is English only.
- Studio sends its own usage analytics (PostHog) unless the key
  `hyperframes-studio:telemetryDisabled=1` is set on its page origin; a desk
  opened from chat does not set it.
- A build larger than 128 MB is refused (the studio's asset limit).
- HyperFrames 0.8.75 replaces the generic `sans-serif` with its Inter font and,
  when online, downloads Inter's Cyrillic glyphs from Google Fonts on every
  build (the line «Fetched … "Inter" from Google Fonts» lands in the version's
  `warnings`). Offline it silently uses a system sans-serif instead, so the same
  montage may look slightly different on and off the network. A warning about a
  CDN script, on the other hand, is a defect: report it.
````

`skills/aimaster/references/phases/06-assembly.md` заменить целиком:

```markdown
# Assembly

**Creator Studio projects (`video`, `mixed`):** the assembly is the montage on
HyperFrames. Enter after every scene video (or the one-shot video) is chosen
and `motion`/`audio` are approved: `montage draft` → `montage render` → show
the version. In `guided`, wait for «собери» or edits; in `autopilot`, continue
to acceptance yourself. Commands, rules and errors: [montage](../montage.md).
Photo projects: `assembly set` with the accepted image.

**Legacy T2 projects only** (SKILL.md, «Legacy projects only»): enter only after
all active motion revisions are approved. Preview the intended assembly. With an
available montage adapter and fresh permission, assemble; otherwise create a
handoff containing sources, active artifacts and revisions, order, durations,
script, prompts, QA, and comments.
```

`skills/aimaster/references/autopilot.md`:

- шаг 6 (строки `6. **\`assembly\`.** Produce the assembly (\`assembly set\`), review it, then the` / `final report.`) заменить на:

```markdown
6. **`assembly`.** Photo: `assembly set` with the accepted image, then the final
   report. Video/mixed: the [montage](montage.md) — `montage status` (engine
   must be `installed`), `montage draft`, `montage render`; review the MP4
   (duration, frame size and sound are checked by the render; frames visually
   when a viewer is available, otherwise say the visual check was not
   performed); fix a defect with `montage edit` and render again. Then
   `stage approve` and the final report.
```

- в «Allowed stops» после пункта про `action enqueue` … `autopilot`. добавить:

```markdown
- the montage engine is missing (`montage status` → `engine.state: missing`):
  installing software is outside the autopilot authorization; the resume
  command is `python3 <skill>/scripts/install.py --install-deps`.
```

`skills/aimaster/references/creator-studio.md` — перед заголовком `## Jobs, grants and the active operator` вставить:

````markdown
For `video` and `mixed` projects the assembly is made by the montage commands —
see [montage](montage.md). `assembly set` stays for photo projects and for a
finished file the user brings.

```bash
creator_studio.py montage draft WS P --expected-revision N [--refresh | --rebuild]
creator_studio.py montage status WS P
creator_studio.py montage diff WS P [--against vNNN]
creator_studio.py montage edit WS P OP [--clip ID] [--at S] [--seconds S] [--duration S] \
  [--value V] [--fade-in S] [--fade-out S] [--text T] --expected-revision N [--expected-model-hash H]
creator_studio.py montage render WS P --expected-revision N [--by agent|owner|autopilot] [--summary "…"]
creator_studio.py montage restore WS P vNNN --expected-revision N
creator_studio.py montage open WS P
creator_studio.py montage close WS P
```

````

`skills/aimaster/SKILL.md`, раздел «Studio workflow» — сразу после пункта `- Video stages: … Photo skips \`motion\` and \`audio\`.` добавить пункт:

```markdown
- Assembly of `video`/`mixed` projects is the montage on HyperFrames: read
  [montage](references/montage.md) before the `assembly` stage. Photo projects
  keep `assembly set` with the accepted image.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_montage_docs.py' -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Full checks**

Run: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py' && python3 -m compileall -q skills/aimaster && git diff --check`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add skills/aimaster/references/montage.md skills/aimaster/references/phases/06-assembly.md skills/aimaster/references/autopilot.md skills/aimaster/references/creator-studio.md skills/aimaster/SKILL.md skills/aimaster/scripts/test_montage_docs.py
git commit -m "docs(montage): montage canon, assembly phase, autopilot step, CLI reference"
```

---
## Контракт для плана Б (экран «Сборка», эндпоинты, Mini App)

План Б опирается только на перечисленное ниже; внутренности модулей он не трогает.

**1. Хранимая часть — `state["montage"]` и снапшот.** С шага `assembly` `projection.build_snapshot` кладёт в `active_project["montage"]`:

```json
{
  "current_version": "v002",
  "versions": [
    {"id": "v001", "asset_id": "asset-…", "asset_url": "/assets/asset-…", "created_at": "2026-09-25T10:00:00+00:00",
     "by": "agent", "based_on": null, "summary": "Черновой монтаж"},
    {"id": "v002", "asset_id": "asset-…", "asset_url": "/assets/asset-…", "created_at": "2026-09-25T10:12:03+00:00",
     "by": "owner", "based_on": "v001", "summary": "клип сцены 1 «Сад»: начало обрезано на 0,5 с"}
  ],
  "canvas": {"width": 1080, "height": 1920}
}
```

`by` ∈ `agent|owner|autopilot`. Раздела нет — монтажа ещё не было. Текущая версия всегда совпадает с `assembly.asset_id`.

**2. Живая часть — `service.status(workspace, project_id, *, locate=None, runner=None, desk=None) -> dict`:**

```json
{
  "project_id": "p", "revision": 4,
  "engine": {"state": "installed", "version": "0.8.75", "wanted": "0.8.75", "reason": ""},
  "exists": true,
  "current_version": "v002",
  "versions": ["…как в снапшоте, без asset_url…"],
  "canvas": {"width": 1080, "height": 1920},
  "model_hash": "3f0c2a9b1d7e4c55",
  "duration": 15.0,
  "unrendered_changes": false,
  "layers": [
    {"layer": "video", "label": "Видео", "clips": [
      {"id": "v-1", "kind": "video", "start": 0.5, "duration": 4.5, "media_start": 0.5, "volume": 0.3,
       "scene_id": "s1", "asset_id": "asset-…", "text": null}]},
    {"layer": "titles", "label": "Титры", "clips": [
      {"id": "t-1", "kind": "div", "start": 0.2, "duration": 4.6, "media_start": 0.0, "volume": null,
       "scene_id": "s1", "asset_id": null, "text": "Барсик идёт по саду"}]},
    {"layer": "voice", "label": "Голос", "clips": []},
    {"layer": "music", "label": "Музыка", "clips": []},
    {"layer": "fx", "label": "Шумы", "clips": []},
    {"layer": "atmos", "label": "Атмосфера", "clips": []}
  ],
  "stale_clips": [{"clip": "v-2", "layer": "video", "scene_id": "s2", "asset_id": "asset-old", "current_asset_id": "asset-new"}],
  "desk": {"state": "open", "url": "http://127.0.0.1:52811/#project/current", "port": 52811, "pid": 4242, "started_at": "…"},
  "paths": {"current": "/…/projects/p/montage/current", "output": "/…/media/p/montage/v002.mp4"}
}
```

Без движка: `engine.state = "missing"`, `reason` по-русски, `model_hash/duration/unrendered_changes = null`, `layers = []`, `desk = {"state": "closed"}` — остальное заполнено. `layers` — всегда шесть дорожек в порядке `LAYERS`; «Есть несобранные правки» = `unrendered_changes is True`. Повторный вызов дёшев: модель кэшируется по содержимому `index.html` (`montage/.cache/model-*.json`), движок зовётся только после правки.

**3. Функции для эндпоинтов и кнопок** (все открывают проект заново, отказ — `MontageError` с русским текстом, устаревшая ревизия — `store.RevisionConflict`, запрет по стадии — `AuthoringError`):

| Действие экрана | Вызов | Ответ |
|---|---|---|
| «Сделать текущей» (`POST …/montage/restore`, Origin + CSRF) | `service.restore(ws, pid, expected_revision, version_id, actor="you")` | `{"project_id", "revision", "current_version", "backup"}` |
| «Открыть монтажный стол» (`POST …/montage/desk`) | `service.open_desk(ws, pid)` | `{"project_id", "state": "open", "url", "port", "pid", "started_at"}` — URL оборачивается страницей-переходником с `hyperframes-studio:telemetryDisabled=1` (план Б) |
| закрыть стол | `service.close_desk(ws, pid)` | `{"project_id", "state": "closed"}` |
| «Показать в папке» | путь `status["paths"]["output"]` | — |
| «Скачать» | `versions[i].asset_id` → существующий `/assets/<id>`; имя файла `<project-id>-vNNN.mp4` | — |
| «Собрать ролик → чат» | промпт агенту: `montage diff` → пересказ → `montage render --by owner` | — |

**4. Интерфейсы для варианта 2 и схемы слоёв:** `desk.Desk` (`open/close/status(paths) -> dict`, формы ответа — как у `StudioDesk`); `model.Model`/`model.Clip` (поля — задача 11); `model.layers_view(model)`; `model_diff.diff_models(old, new, names=...)`; `versions.VersionMeta` и `versions.list_versions(paths)` (`meta.json` хранит ещё `changes[]` и `model_hash`); `paths.montage_paths(project_dir)`; `context.open_context(ws, pid)`.

**5. История проекта:** виды `montage-drafted`, `montage-built` (`target_id` = vNNN), `montage-restored` (`target_id`); подписи уже есть в `static/ui/history-panel.js`.

**6. Чего план А не делает (остаётся плану Б и этапу 4):** HTTP-эндпоинты (reveal, restore, desk, download с `Content-Disposition`), страница-переходник Studio с отключением телеметрии, экран «Сборка» и его модели (`node --test`), промпт `screen-prompts.js::assembleFinal`, остановка стола по простою и при выходе сервера дашборда, Mini App и «Прислать в Telegram».

## Решения плана, которых нет в спецификации, и вопросы владельцу

Решения (приняты, чтобы план был исполнимым; каждое проверено прогоном):

1. **Переход — CSS, а не `data-fade-*`.** В HyperFrames `data-fade-in/out` меняют только громкость; картинка проявляется CSS-анимацией, которую рантайм перематывает покадрово. `data-fade-*` остаются для мягких краёв звука.
2. **Свой HOME движка** (`<prefix>/home`): браузер, кэши и настройки HyperFrames не попадают в домашнюю папку человека; `--update` и удаление — одна папка.
3. **Скиллы — только ядро (10 из 21)**, из тега v0.8.75, со сверкой хэшей; сценарные (`figma`, `slideshow`, `general-video`, …) не ставятся — нет конфликта имён, монтажом руководит aimaster.
4. **`draft --rebuild`** (в спецификации нет): черновик заново из проекта, прежний `index.html` уходит в `montage/.undo/` — ничего не теряется.
5. **Откат правки агента** — собственный снимок в `.undo/` на каждую правку (покрывает и наши точечные правки атрибутов, которых квитанции HyperFrames не видят); квитанция HyperFrames всё равно возвращается в ответе.
6. **Установка скиллов с GitHub** работает и на Python с python.org без «Install Certificates.command» (системный набор сертификатов).
7. **Канон `references/montage.md` — по-английски**, как соседние файлы `references/`; всё, что видит человек (ошибки, diff, CLI-помощь), — по-русски.

Вопросы, которые без владельца не решить:

1. **Скилл `hyperframes` объявляет себя «обязательной точкой входа для любого видео».** Поставленный глобально в `~/.claude/skills` и `~/.agents/skills`, он будет срабатывать во всех проектах и может перехватывать другие видео-задачи (Remotion, «сделай монтаж»). Ставить ли ядро глобально, как решено в спецификации, или только по запросу / в другое место?
2. **Шрифт.** При доступной сети HyperFrames на каждой сборке ходит в Google Fonts за кириллицей Inter; без сети берёт системный шрифт — ролик может чуть отличаться. Положить в навык свободный шрифт с кириллицей (OFL, ~300 КБ) и объявлять его в черновике — тогда сборка полностью автономна и одинакова везде?
3. **GSAP для скиллов HyperFrames.** Их анимации держатся на GSAP с CDN, а наша проверка сборки внешние скрипты запрещает. Ставить ли `gsap` локально вместе с движком (npm, закреплённая версия) и разрешить его в `assets/`?
4. **`references/phases/06-assembly.md` в SKILL.md объявлен файлом старого формата T2.** План переписывает его как указатель на монтаж и сохраняет старый текст для T2. Так?
5. **Автопилот без движка.** План считает это разрешённой остановкой (установка программ не входит в полномочия автопилота). Или автопилоту можно ставить движок самому?
6. **Титры из текста сцены.** Текст сцены — описание кадра, а не реплика; титры могут выглядеть странно. Оставить (как в спецификации) или по умолчанию титров не делать?
7. **Предел 128 МБ на ассет** (`MAX_ASSET_BYTES`) при качестве CRF 18: длинный ролик будет отклонён. Поднять предел для результатов монтажа, снизить качество или оставить отказ?

## Самопроверка

**1. Покрытие спецификации.**

| Требование спецификации | Задача |
|---|---|
| `engine.json`: пакет, версия, выпуск скиллов | 1 |
| `engine.py`: поиск, запуск без оболочки по полному пути (Windows — `node.exe` + скрипт), переменные, тайм-ауты, `--frames-cache-dir`, JSON | 1, 2 |
| `--install-deps`: Node ≥ 22 (winget/brew/инструкция Linux), HyperFrames через `npm install --prefix`, предзагрузка браузера с сообщением, скиллы той же версии с пометкой и `conflict`, раздел `montage` в JSON, `--update` | 4, 5 |
| CI: реальная установка на трёх ОС, черновик из клипов ffmpeg, `lint`, рендер 3 с, ffprobe, нет внешних URL, рендер без сети на Linux | 6, 19 |
| `canvas.py` | 3 |
| `media_sync.py` (жёсткая ссылка / копия, `src` внутри папки) | 8 |
| `draft.py` (клипы по `order`, `current_member`, аудиослои, титры, переходы, без GSAP и внешних URL), `draft --refresh` | 9, 10 |
| `model.py` (дорожки и клипы, хэш, смысловой diff) | 11 |
| `versions.py` (создать, список, сделать текущей, «несобранные правки») | 12 |
| Раздел `montage` в state через транзакцию с `expected_revision`, история, проекция/валидация | 13 |
| `edit.py` (обрезка начала сдвигает исходник, сдвиг за конец удлиняет корень, громкость, разрез, удаление, титры) | 14 |
| `render.py` (lint → рендер → ffprobe → ассет `result` в `media/<id>/montage/vNNN.mp4` → версия → `assembly`; ошибка — версии нет) | 15 |
| `desk.py` (интерфейс, `StudioDesk`, один процесс на проект, тайм-аут старта — процесс убит) | 16 |
| CLI `montage draft|status|diff|edit|render|restore|open|close`, `--json`, `--expected-revision` | 17, 18 |
| Канон: `06-assembly.md`, `montage.md`, `autopilot.md`, `creator-studio.md`, `SKILL.md` | 20 |
| Сквозная проверка на тестовых клипах, шаг в смоуке | 19 |
| GSAP только если нужен рантайму | факты пробы: не нужен; задача 6/19 подтверждает |

Этапы 3–5 спецификации (экран, телефон, выпуск) — вне плана А; их опора описана в «Контракте для плана Б».

**2. Заглушки.** Поиск по плану слов «TBD», «TODO», «implement later», «подобно задаче», «добавить обработку ошибок» пуст; каждый шаг с кодом содержит код целиком, у каждой правки существующего файла указан точный якорь.

**3. Согласованность имён.** Сигнатуры из блоков Interfaces совпадают с кодом задач: `run_engine/run_engine_json/EngineRunner.json|run`, `read_model(..., runner=)`, `apply_edit(..., runner=)`, `render_version(ctx, expected_revision, *, by, summary, engine, runner, probe)`, `service.*(…, engine=None, runner=None, probe=None)`, `StudioDesk(engine, *, popen, clock, sleep, alive, answers, kill)`, `rebuild_draft(...) -> (DraftResult, backup)`.

**4. Прогон кода плана (2026-09-25).** Весь код и все правки плана были перенесены скриптом в копию репозитория во временной папке и проверены: `python3 -m unittest discover -s skills/aimaster/scripts -p 'test_*.py'` — 449 тестов, OK (8 пропусков — Windows-ветки и тесты, которым нужен движок в папке по умолчанию); `compileall` — чисто; `check_static_modules.mjs` — 104 модуля; `node --test` v2 — зелёный. На настоящем HyperFrames 0.8.75 (поставлен установщиком плана в отдельную временную папку, скиллы — в подменённый HOME): установка движка, браузера и 10 скиллов со сверкой хэшей, `montage_ci_check.py` обеих редакций (`ok: true`), сквозной тест `test_montage_e2e.py` (черновик → сборка → обрезка начала через настоящий CLI → diff одной строкой → v002 → возврат → настоящий монтажный стол открылся и закрылся) и смоук чистой машины в обеих ветках (движок есть / нет). Прогон нашёл и план исправил: пустое хранилище сертификатов Python с python.org, подкачку Inter с Google Fonts, два слишком длинных модуля установщика.

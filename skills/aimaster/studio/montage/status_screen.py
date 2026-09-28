"""Состояние монтажа для экрана «Сборка» дашборда — двумя частями.

`montage status` (status.py) для опроса раз в несколько секунд дорог: хэши
~370 файлов скиллов, `timeline --json` после каждой правки на столе (до
120 с), сверка устаревших клипов. Экрану это нужно реже:

- `cheap_status` — то, что меняют действия человека и что должно быть видно
  сразу: движок, текущая версия, файл ролика, ключ текста index.html и флаг
  несобранных правок, если модель этого текста уже лежит в кэше;
- `model_status` — схема слоёв, хэш, флаг несобранных правок и устаревшие
  клипы; экран просит её, когда сменился ключ index.html, текущая версия
  (сборка не трогает index.html — ключ тогда прежний) или ревизия проекта.

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

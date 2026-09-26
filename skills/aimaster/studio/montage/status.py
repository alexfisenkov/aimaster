"""Состояние монтажа проекта одним словарём — для `montage status` и снапшота
дашборда (план Б, «Контракт для плана Б», п. 2). Отвечает всегда: без движка,
когда движок не смог прочитать монтаж (`model_error`), когда проект не
сравнить с черновиком (`stale_error`), когда снимок версии повреждён —
экран «Сборка» должен показать версии и путь к файлу в любом случае."""

from __future__ import annotations

from . import MontageError
from .context import ProjectContext
from .desk import StudioDesk
from .engine import Engine, install_command, load_pin
from .index_io import read_index
from .model import layers_view, model_hash, read_model
from .montage_state import montage_section
from .paths import render_output
from .stale import stale_clips
from .versions import current_meta, has_unrendered_changes
from .workspace_skills import skills_summary

STALE_KEYS = ("clip", "layer", "scene_id", "asset_id", "current_asset_id", "reason", "cause",
              "audio_change")


def _base(ctx: ProjectContext, engine: Engine | None, reason: str) -> dict:
    section = montage_section(ctx.state) if "montage" in ctx.state else None
    return {
        "project_id": ctx.project_id, "revision": ctx.revision,
        "engine": {"state": "installed" if engine else "missing",
                   "version": engine.version if engine else None,
                   "wanted": load_pin()["version"], "reason": reason,
                   "install": None if engine else install_command()},
        "skills": skills_summary(ctx.workspace, create=False),
        "exists": ctx.paths.index.is_file(),
        "current_version": section["current_version"] if section else None,
        "versions": list(section["versions"]) if section else [],
        "canvas": section["canvas"] if section else None,
        "model_hash": None, "duration": None, "unrendered_changes": None, "layers": [],
        "model_error": None, "stale_error": None, "stale_clips": [], "desk": {"state": "closed"},
        "paths": {"current": str(ctx.paths.current), "output": None},
    }


def _stale(ctx: ProjectContext) -> dict:
    """Одна форма записи для всех трёх исходов stale_clips: audio_change
    ставит только refresh, здесь его ещё нет — None."""

    try:
        items = stale_clips(read_index(ctx.paths.index), ctx.state)
    except MontageError as error:
        return {"stale_error": str(error)}
    return {"stale_clips": [{key: item.get(key) for key in STALE_KEYS} for item in items]}


def _model_part(ctx: ProjectContext, engine: Engine, current_version, runner) -> dict:
    paths = ctx.paths
    try:
        model = read_model(engine, paths.current, cache_dir=paths.cache, runner=runner)
    except MontageError as error:
        return {"model_error": str(error)}
    digest = model_hash(model)
    return {"model_hash": digest, "duration": model.duration, "layers": layers_view(model),
            "unrendered_changes": has_unrendered_changes(digest, current_meta(paths, current_version))}


def montage_status(ctx: ProjectContext, engine: Engine | None, reason: str, *, runner=None,
                   desk=None) -> dict:
    result = _base(ctx, engine, reason)
    if result["exists"]:
        result.update(_stale(ctx))
        result["desk"] = (desk or StudioDesk(engine)).status(ctx.paths)
        if engine is not None:
            result.update(_model_part(ctx, engine, result["current_version"], runner))
    if result["current_version"]:
        # Путь MP4 версии задан раскладкой (paths.render_output); проверять
        # файл через AssetIndex (чтение до 2 ГиБ и sha256) на каждый опрос
        # экрана незачем — это делает запись версии и «Сделать текущей».
        output = render_output(ctx.media_root, ctx.project_id, result["current_version"])
        result["paths"]["output"] = str(output) if output.is_file() else None
    return result

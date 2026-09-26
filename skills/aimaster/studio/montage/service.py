"""Вход в монтаж для CLI (`creator_studio.py montage …`) и дашборда (план Б).

Каждая функция открывает проект заново: state и монтаж могли поменять дашборд,
Studio или другой агент. Меняющие функции сверяют expected_revision до работы.
Здесь — рабочая копия (черновик, правка, GSAP, стол, состояние); версии
(сборка, diff, возврат) — в `service_versions.py`, имена переэкспортированы."""

from __future__ import annotations

from . import MontageError
from .context import open_context
from .desk import StudioDesk
from .draft import create_draft, rebuild_draft
from .edit import EditRequest, apply_edit
from .engine import locate as locate_engine
from .engine import require_engine
from .index_io import read_index
from .montage_state import check_writable, record_draft
from .probe import probe_media
from .refresh import refresh_draft
from .service_versions import diff, fresh, put_back_index, render, restore
from .status import montage_status
from .vendor import vendor_gsap
from .workspace_skills import skills_summary

__all__ = ["DRAFT_MODES", "close_desk", "diff", "draft", "edit", "gsap", "open_desk", "render",
           "restore", "status"]
DRAFT_MODES = ("new", "refresh", "rebuild")


def _split_stale(stale: list[dict]) -> dict:
    """refresh правит только записи без reason; остальные («нет принятого»,
    «нужен --rebuild») — отдельным списком, чтобы агент их увидел."""

    return {"refreshed": [item for item in stale if item.get("reason") is None],
            "not_refreshed": [item for item in stale if item.get("reason") is not None]}


def draft(workspace, project_id, expected_revision, *, mode="new", engine=None, runner=None,
          probe=None) -> dict:
    if mode not in DRAFT_MODES:
        raise MontageError(f"режим черновика — одно из {', '.join(DRAFT_MODES)}")
    ctx = open_context(workspace, project_id)
    fresh(ctx, expected_revision)
    engine = engine or require_engine()
    probe = probe or probe_media
    if mode == "refresh":
        stale = refresh_draft(ctx.paths, ctx.state, ctx.resolve, probe=probe)
        return {"project_id": project_id, "revision": ctx.revision, **_split_stale(stale),
                "skills": skills_summary(ctx.workspace)}
    previous = read_index(ctx.paths.index) if ctx.paths.index.is_file() else None
    if mode == "rebuild":
        result, backup = rebuild_draft(ctx.paths, ctx.state, ctx.resolve, probe=probe,
                                       engine_prefix=engine.prefix)
    else:
        result, backup = create_draft(ctx.paths, ctx.state, ctx.resolve, probe=probe,
                                      engine_prefix=engine.prefix), None
    drafted = read_index(ctx.paths.index)
    try:
        written = record_draft(ctx.store, project_id, expected_revision, canvas=result.canvas)
    except BaseException as error:
        put_back_index(ctx.paths, previous, drafted, error)
        raise
    return {"project_id": project_id, "revision": written["revision"],
            "canvas": result.canvas.to_dict(), "duration": result.duration, "clips": result.clips,
            "current": str(ctx.paths.current), "backup": str(backup) if backup else None,
            "skills": skills_summary(ctx.workspace)}


def gsap(workspace, project_id, *, plugins=(), engine=None) -> dict:
    ctx = open_context(workspace, project_id)
    check_writable(ctx.state)
    return {"project_id": project_id,
            **vendor_gsap(engine or require_engine(), ctx.paths, plugins=tuple(plugins))}


def status(workspace, project_id, *, locate=None, runner=None, desk=None) -> dict:
    ctx = open_context(workspace, project_id)
    engine, reason = (locate or locate_engine)()
    return montage_status(ctx, engine, reason, runner=runner, desk=desk)


def edit(workspace, project_id, expected_revision, request: EditRequest, *,
         expected_model_hash=None, engine=None, runner=None) -> dict:
    ctx = open_context(workspace, project_id)
    fresh(ctx, expected_revision)
    result = apply_edit(engine or require_engine(), ctx.paths, request,
                        expected_model_hash=expected_model_hash, runner=runner)
    return {"project_id": project_id, "revision": ctx.revision, **result}


def open_desk(workspace, project_id, *, engine=None, desk=None) -> dict:
    ctx = open_context(workspace, project_id)
    return {"project_id": project_id,
            **(desk or StudioDesk(engine or require_engine())).open(ctx.paths)}


def close_desk(workspace, project_id, *, desk=None) -> dict:
    ctx = open_context(workspace, project_id, guard=False)  # своё Studio — остановить и в «грязной» папке
    return {"project_id": project_id, **(desk or StudioDesk(None)).close(ctx.paths)}

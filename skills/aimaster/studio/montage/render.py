"""Сборка версии монтажа: под одним замком сборки — ссылки композиции → lint →
MP4 → ffprobe → «index.html не меняли во время сборки» → ассет с ролью result в
media/<проект>/montage/vNNN.mp4 → снимок версии → state (montage + assembly +
история) одной транзакцией → публикация снимка. Ошибка на любом шаге — версии
нет, свой MP4 удалён, текущая версия та же. Сборка локальная и бесплатная:
разрешения на трату не нужно (`assemble` вне GRANT_REQUIRED_ACTIONS)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..assets import AssetError
from . import MontageError
from .context import ProjectContext, project_mode, scene_names
from .engine import Engine, require_engine
from .engine_cli import EngineRunner
from .index_io import read_index
from .model import model_hash
from .montage_state import check_writable, montage_section, record_version, require_revision
from .probe import probe_media
from .render_steps import checked_output, normalized_index, preflight, remove_output, render_mp4
from .summary_text import auto_summary, checked_summary
from .version_diff import base_model, changes_since
from .version_staging import (build_lock, discard_staging, publish_version, settle_orphans,
                              stage_version)
from .versions import BY_VALUES, VersionMeta, next_version_id


@dataclass(frozen=True)
class RenderOutcome:
    version: str
    asset_id: str
    path: str
    duration: float
    changes: list
    warnings: list
    revision: int


def _fresh_state(ctx: ProjectContext, expected_revision: int) -> dict:
    """State заново под замком: пока ждали, другая сборка могла записать версию."""

    state = ctx.store.load(ctx.project_id)
    require_revision(state, expected_revision)
    check_writable(state)
    return state


def _drop_output(ctx: ProjectContext, output, asset_id: str | None) -> None:
    """Сборка не записана: свой MP4 и его строку в AssetIndex — убрать (best effort)."""

    remove_output(output)
    if asset_id:
        try:
            ctx.assets.forget(asset_id)
        except Exception:  # noqa: BLE001 — уборка не подменяет исходную ошибку своей
            pass


def _recorded(ctx: ProjectContext, version_id: str) -> bool:
    """Записана ли версия, хотя record_version бросил исключение. Не узнать —
    считаем записанной: удалить файлы записанной версии хуже, чем оставить
    лишнее (его разберут settle_orphans и следующая сборка)."""

    try:
        state = ctx.store.load(ctx.project_id)
        return any(item.get("id") == version_id for item in montage_section(state)["versions"])
    except Exception:  # noqa: BLE001
        return True


def _register(ctx: ProjectContext, output) -> str:
    try:
        return ctx.assets.register(output.relative_to(ctx.workspace).as_posix(), "result")["asset_id"]
    except AssetError as error:
        raise MontageError(f"собранный ролик {output.name} студия не приняла как файл") from error


def _build(ctx, state, expected_revision, *, by, summary, engine, runner, probe) -> RenderOutcome:
    section = montage_section(state)
    recorded = [item["id"] for item in section["versions"]]
    settle_orphans(ctx.paths, recorded)
    version_id = next_version_id(ctx.paths, recorded_ids=recorded)
    base = section["current_version"]
    old, problem = base_model(ctx.paths, base)
    text = normalized_index(ctx.paths, old, trusted=problem is None)
    model, warnings = preflight(ctx.paths, engine, runner, text)
    output = render_mp4(ctx, engine, runner, version_id)
    asset_id = None
    try:
        duration = checked_output(output, model, text, probe, recorded_canvas=section.get("canvas"))
        if read_index(ctx.paths.index) != text:
            raise MontageError("монтаж поменяли во время сборки (например, в монтажном столе) — "
                               "эта сборка не записана; соберите ещё раз")
        asset_id = _register(ctx, output)
        changes = changes_since(base, old, problem, model, scene_names(state))
        meta = VersionMeta(
            version=version_id, created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            by=by or ("autopilot" if project_mode(state) == "autopilot" else "agent"),
            based_on=base, summary=summary or auto_summary(base, changes), changes=tuple(changes),
            asset_id=asset_id, model_hash=model_hash(model))
        staging = stage_version(ctx.paths, meta, model, index_text=text)
    except BaseException:
        _drop_output(ctx, output, asset_id)
        raise
    try:
        written = record_version(ctx.store, ctx.assets, ctx.project_id, expected_revision, meta=meta)
    except BaseException:
        if not _recorded(ctx, version_id):
            discard_staging(staging)
            _drop_output(ctx, output, asset_id)
        raise
    try:
        publish_version(ctx.paths, staging, version_id)
    except OSError:
        warnings = warnings + [f"снимок версии {version_id} ещё не в versions/ — его опубликует "
                               "следующая сборка; версия записана"]
    return RenderOutcome(version_id, asset_id, str(output), duration, changes, warnings,
                         written["revision"])


def render_version(ctx: ProjectContext, expected_revision: int, *, by: str | None = None,
                   summary: str | None = None, engine: Engine | None = None, runner=None,
                   probe=probe_media) -> RenderOutcome:
    require_revision(ctx.state, expected_revision)
    check_writable(ctx.state)
    if by is not None and by not in BY_VALUES:
        raise MontageError(f"--by: одно из {', '.join(BY_VALUES)}")
    summary = checked_summary(summary)
    if not ctx.paths.index.is_file():
        raise MontageError("черновика ещё нет: сначала montage draft")
    engine = engine or require_engine()
    runner = runner or EngineRunner()
    with build_lock(ctx.paths):
        state = _fresh_state(ctx, expected_revision)
        return _build(ctx, state, expected_revision, by=by, summary=summary, engine=engine,
                      runner=runner, probe=probe)

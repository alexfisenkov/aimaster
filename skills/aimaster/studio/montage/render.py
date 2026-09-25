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
from ..store import RevisionConflict
from . import MontageError
from .context import ProjectContext, project_mode, scene_names
from .engine import Engine, require_engine
from .engine_cli import EngineRunner
from .index_io import read_index
from .model import Model, model_hash
from .model_diff import diff_models
from .montage_format import clips_count, fmt_len
from .montage_state import check_writable, montage_section, record_version
from .probe import probe_media
from .render_steps import checked_output, normalized_index, preflight, remove_output, render_mp4
from .version_staging import (build_lock, discard_staging, publish_version, settle_orphans,
                              stage_version)
from .versions import BY_VALUES, VersionMeta, next_version_id, read_version_model


@dataclass(frozen=True)
class RenderOutcome:
    version: str
    asset_id: str
    path: str
    duration: float
    changes: list
    warnings: list
    revision: int


def _summary(base: str | None, changes: list[str]) -> str:
    if base is None:
        return "Черновой монтаж"
    if not changes:
        return "Пересборка без изменений"
    more = f" и ещё {len(changes) - 3}" if len(changes) > 3 else ""
    return "; ".join(changes[:3]) + more


def _base_model(paths, base: str | None) -> tuple[Model | None, bool]:
    """(модель текущей версии, её снимок потерян). Потерянный снимок (state
    версию знает, папки нет) — не повод блокировать все следующие сборки."""

    if base is None:
        return None, False
    try:
        return read_version_model(paths, base), False
    except MontageError:
        return None, True


def _changes(base: str | None, old: Model | None, lost: bool, model: Model, names) -> list[str]:
    if lost:
        return [f"снимка прежней версии {base} нет на диске — изменения сравнить не с чем; "
                f"в монтаже {clips_count(len(model.clips))}, {fmt_len(model.duration)}"]
    return diff_models(old, model, names=names)


def _fresh_state(ctx: ProjectContext, expected_revision: int) -> dict:
    """State заново под замком: пока ждали, другая сборка могла записать версию."""

    state = ctx.store.load(ctx.project_id)
    if state.get("revision") != expected_revision:
        raise RevisionConflict(expected_revision, state.get("revision"))
    check_writable(state)
    return state


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
    old, lost = _base_model(ctx.paths, base)
    text = normalized_index(ctx.paths, old)
    model, warnings = preflight(ctx.paths, engine, runner, text)
    output = render_mp4(ctx, engine, runner, version_id)
    try:
        duration = checked_output(output, model, text, probe, recorded_canvas=section.get("canvas"))
        if read_index(ctx.paths.index) != text:
            raise MontageError("монтаж поменяли во время сборки (например, в монтажном столе) — "
                               "эта сборка не записана; соберите ещё раз")
        asset_id = _register(ctx, output)
        changes = _changes(base, old, lost, model, scene_names(state))
        meta = VersionMeta(
            version=version_id, created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            by=by or ("autopilot" if project_mode(state) == "autopilot" else "agent"),
            based_on=base, summary=summary or _summary(base, changes), changes=tuple(changes),
            asset_id=asset_id, model_hash=model_hash(model))
        staging = stage_version(ctx.paths, meta, model, index_text=text)
    except BaseException:
        remove_output(output)
        raise
    try:
        written = record_version(ctx.store, ctx.assets, ctx.project_id, expected_revision, meta=meta)
    except BaseException:
        discard_staging(staging)
        remove_output(output)
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
    if ctx.revision != expected_revision:
        raise RevisionConflict(expected_revision, ctx.revision)
    check_writable(ctx.state)
    if by is not None and by not in BY_VALUES:
        raise MontageError(f"--by: одно из {', '.join(BY_VALUES)}")
    if not ctx.paths.index.is_file():
        raise MontageError("черновика ещё нет: сначала montage draft")
    engine = engine or require_engine()
    runner = runner or EngineRunner()
    with build_lock(ctx.paths):
        state = _fresh_state(ctx, expected_revision)
        return _build(ctx, state, expected_revision, by=by, summary=summary, engine=engine,
                      runner=runner, probe=probe)

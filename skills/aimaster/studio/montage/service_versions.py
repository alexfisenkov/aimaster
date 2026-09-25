"""Вход `service` для версий: сборка, diff, «сделать текущей» — и общие для
всего `service` проверки ревизии и возврат index.html при сбое записи state.
Публичные имена отсюда переэкспортирует `service.py`."""

from __future__ import annotations

from dataclasses import asdict

from ..store import RevisionConflict
from . import MontageError
from .context import open_context
from .engine import require_engine
from .index_io import read_index, write_index
from .model import model_hash, read_model
from .montage_state import check_writable, montage_section, record_restore
from .paths import VERSION_ID
from .probe import probe_media
from .render import render_version
from .version_diff import base_model, changes_since
from .version_staging import build_lock, settle_orphans
from .versions import has_unrendered_changes, list_versions, read_version_model, restore_files


def fresh(ctx, expected_revision: int) -> None:
    if ctx.revision != expected_revision:
        raise RevisionConflict(expected_revision, ctx.revision)
    check_writable(ctx.state)


def put_back_index(paths, previous: str | None) -> None:
    """Запись в state не удалась — current/index.html как до вызова: иначе
    повтор упёрся бы в «черновик уже есть», а state о нём не знает."""

    if previous is not None:
        write_index(paths.index, previous)
        return
    try:
        paths.index.unlink(missing_ok=True)
    except OSError:
        pass  # уборка при уже случившейся ошибке — не подменяет её своей


def render(workspace, project_id, expected_revision, *, by=None, summary=None, engine=None,
           runner=None, probe=None) -> dict:
    ctx = open_context(workspace, project_id)
    outcome = render_version(ctx, expected_revision, by=by, summary=summary, engine=engine,
                             runner=runner, probe=probe or probe_media)
    return {"project_id": project_id, **asdict(outcome)}


def diff(workspace, project_id, *, against=None, engine=None, runner=None) -> dict:
    ctx = open_context(workspace, project_id)
    if not ctx.paths.index.is_file():
        raise MontageError("черновика ещё нет: сначала montage draft")
    if against is not None and not VERSION_ID.fullmatch(str(against)):
        raise MontageError("--against: версия вида v001")
    model = read_model(engine or require_engine(), ctx.paths.current, cache_dir=ctx.paths.cache,
                       runner=runner)
    current = montage_section(ctx.state)["current_version"]
    base = against or current
    if against:
        old, lost = read_version_model(ctx.paths, against), False
    else:
        old, lost = base_model(ctx.paths, base)
    meta = next((item for item in list_versions(ctx.paths) if item.version == current), None)
    return {"project_id": project_id, "base": base, "model_hash": model_hash(model),
            "changes": changes_since(base, old, lost, model, ctx.scene_names()),
            "unrendered_changes": has_unrendered_changes(model_hash(model), meta)}


def restore(workspace, project_id, expected_revision, version_id, *, actor="agent") -> dict:
    """Под замком сборки: не посреди чужой сборки, и снимок, который прошлая
    сборка записала в state, но не успела опубликовать, сперва публикуется."""

    ctx = open_context(workspace, project_id)
    fresh(ctx, expected_revision)
    recorded = [item["id"] for item in montage_section(ctx.state)["versions"]]
    if version_id not in recorded:
        raise MontageError(f"нет версии {version_id}")
    with build_lock(ctx.paths):
        settle_orphans(ctx.paths, recorded)
        previous = read_index(ctx.paths.index) if ctx.paths.index.is_file() else None
        backup = restore_files(ctx.paths, version_id)
        try:
            written = record_restore(ctx.store, ctx.assets, project_id, expected_revision,
                                     version_id=version_id, actor=actor)
        except BaseException:
            put_back_index(ctx.paths, previous)
            raise
    return {"project_id": project_id, "revision": written["revision"],
            "current_version": version_id, "backup": str(backup) if backup else None}

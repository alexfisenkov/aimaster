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

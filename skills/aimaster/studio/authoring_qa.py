"""Chat-authored assembly (final deliverable) result.

Ticket 12 repair, condition 15 and поправка оркестратора 4: one of six
`authoring_*` responsibility modules split out of the former monolithic
`authoring.py`. It owned `qa set` and `assembly set`; the `qa` stage is gone
(G12, ticket 22), so `assembly set` is all that is left. The file keeps
its old name for now: other documents and tests still cite
`authoring_qa.set_assembly`, and nothing else depends on the name.

`set_assembly` does not check whether the project has actually *reached*
`assembly` before writing: like every other write in this package (see
`authoring.py`'s original module docstring), data written ahead of its
stage is hidden by `projection.build_snapshot`'s own stage gate until the
project actually reaches `assembly` -- there is no per-scene nested
structure here the way `scenes[].links` has, so nothing can leak ahead of
schedule the way ticket 12 repair condition 4 found for prompts/results. It
*does* refuse once the `assembly` milestone is already `approved` (ticket 12
repair, condition 2, `authoring_support.require_stage_not_approved`):
writing ahead of a stage is fine, silently reopening one the dashboard
already approved is not. It goes through `authoring_support.mutate`, which
runs `projection.validate_state` before committing (condition 1) -- a
malformed `assembly` payload is refused at write time, not only once a
later snapshot request reaches that stage.
"""

from __future__ import annotations

from . import domain
from .assets import AssetIndex
from .authoring_support import (
    AuthoringError,
    mutate,
    optional_bounded_text,
    require_image_mime,
    require_project,
    require_result_asset_role,
    require_stage_not_approved,
    require_video_mime,
    safe_id,
)
from .store import ProjectStore


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


def require_no_montage(state: dict) -> None:
    """Видео- или смешанный проект с разделом `montage`: сборку ведёт монтаж
    (версии, «сделать текущей»), и `assembly set` в обход него разошёлся бы с
    `montage.current_version`. Фото-проекты монтажа не знают."""

    if require_project(state).get("type") != "photo" and "montage" in state:
        raise AuthoringError(
            "у этого проекта сборку ведёт монтаж: assembly set её не меняет — "
            "новую версию собирает montage render, прежнюю возвращает montage restore"
        )


def set_assembly(
    store: ProjectStore,
    assets_index: AssetIndex,
    project_id: str,
    expected_revision: int,
    *,
    asset_id: str,
    caption: str | None = None,
) -> dict:
    """Write `state["assembly"]`: the final deliverable's asset, plus an
    optional free-text summary (ticket 12 repair, поправка оркестратора
    4). `--caption` maps onto `assembly.summary` -- `projection.
    _sanitize_assembly`'s own key for this field; the CLI flag name
    follows the ticket's own wording, the state's key follows the
    schema ticket 01 already fixed.

    The asset's mime type must match the *project's* type (blocking
    condition 3, "у фото-проекта видео нет нигде" -- applied here too,
    not only to `result add-version`/`reference add`, since assembly is
    one more place an asset gets attached to a project): an image for a
    photo project, a video for a video/mixed one. It must also have been
    registered with the `result` role (ticket 12 repair, condition 6),
    the same rule `add_result_version` applies.

    Refuses once the `assembly` milestone is already `approved` (ticket
    12 repair, condition 2). Unlike every earlier stage, `assembly` is
    the *last* one in both `VIDEO_STAGES`/`PHOTO_STAGES`, so
    `derive_view_stage` never moves `current_stage` past it even once
    approved -- `require_stage_not_approved` reads `state["milestones"]`
    directly rather than relying on the current stage having moved on,
    the same reason `authoring_milestones.set_milestone` already checks
    `assembly` explicitly for its own `ready`/`blocked` writes.
    """

    safe_id(asset_id, "asset_id")
    caption = optional_bounded_text(caption, "caption")

    _, mime_type = assets_index.resolve(asset_id)
    require_result_asset_role(assets_index.role_of(asset_id), "an assembly asset")

    def mutator(state):
        require_no_montage(state)
        apply_assembly(state, mime_type, asset_id, caption)
        domain.append_history(state, "agent", "assembly-ready", "assembly")

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "revision": new_state["revision"]}

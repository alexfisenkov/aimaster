"""Chat-authored results (asset-backed) and references.

Ticket 12 repair, condition 15: one of six `authoring_*` responsibility
modules split out of the former monolithic `authoring.py` -- this one owns
`result add-version` and `reference add`, the two writes that link a
registered `AssetIndex` entry into canonical project state. See
`authoring_support.py`'s module docstring for the split's rationale.
"""

from __future__ import annotations

from . import domain
from .assets import AssetIndex, VIDEO_REFERENCE_ROLE
from .authoring_support import (
    AuthoringError,
    find_scene,
    mutate,
    optional_bounded_text,
    require_image_mime,
    require_owning_scene_matches,
    require_project,
    require_reference_asset_role,
    require_result_asset_role,
    require_stage_not_approved,
    require_video_mime,
    require_video_reference_asset_role,
    require_voice_asset,
    resolve_current_group_member,
    safe_id,
    scene_links,
)
from .decision_cards import STAGE_COLLECTIONS
from .store import ProjectStore


_RESULT_KIND_FIELDS = {
    "image": ("image_results", "image_result_id"),
    "video": ("video_results", "video_result_id"),
}
# Ticket 12 repair, condition 2: the milestone that owns each result
# kind's own collection -- `image_results` from `image_results` onward,
# `video_results` only from `motion` onward. Ticket 17 condition 5:
# derived from `decision_cards.STAGE_COLLECTIONS` (the dashboard's own
# "collection -> (stage, id key)" map) rather than a second, hand-copied
# `{"image": "image_results", "video": "motion"}` literal that could
# silently drift from it -- `_RESULT_KIND_FIELDS` above already names
# each kind's own collection, so this only has to look up the stage half.
_RESULT_KIND_STAGE = {
    kind: STAGE_COLLECTIONS[collection][0] for kind, (collection, _link_key) in _RESULT_KIND_FIELDS.items()
}
# Ticket 13 (spec §3/§7, "куда девать подгруженные элементы"): a fresh
# reference for a *regenerated* image/motion prompt is added during the
# same generation stage the prompt/result themselves are -- ticket 12's
# original rule gated every reference on `image_plan` alone, which
# blocked a new reference the moment the plan was approved, before
# regeneration could ever use one. The qualifying stage is project-type
# specific: a photo project has no `motion` stage at all, so
# `image_results` is its own last generation stage; a video/mixed
# project's is `motion`. Approving that stage is what finally closes
# this door -- `image_plan`'s own approval no longer does, on its own.
# Ticket 17 condition 5: reads `_RESULT_KIND_STAGE` above (itself derived
# from `decision_cards.STAGE_COLLECTIONS`) instead of a third, hand-copied
# `"image_results"`/`"motion"` pair -- a photo project's own result kind
# is always `image`, a video/mixed project's always `video`, so this is
# the exact same stage `_RESULT_KIND_STAGE` already names for that kind.
def _reference_final_stage(project_type: str) -> str:
    return "image_results" if project_type == "photo" else "audio"


def _require_reference_writable(state: dict, label: str) -> None:
    project = require_project(state)
    sequence = domain._stage_sequence(state)
    current = domain.derive_view_stage(state)["current_stage"]
    final_stage = _reference_final_stage(project.get("type"))
    if sequence.index(current) < sequence.index("image_plan") or sequence.index(current) > sequence.index(final_stage):
        raise AuthoringError(f"{label} is available from image_plan through {final_stage}")
    require_stage_not_approved(state, final_stage, label)


def add_result_version(
    store: ProjectStore,
    assets_index: AssetIndex,
    project_id: str,
    expected_revision: int,
    *,
    scene_id: str | None = None,
    kind: str | None = None,
    asset_id: str,
    result_id: str | None = None,
    caption: str | None = None,
    target: str | None = None,
) -> dict:
    """Link a registered asset to a scene's image/video result.

    The asset must already resolve through `assets_index`, and its mime
    type must actually match `kind` (ticket 12 repair, blocking condition
    3: `resolve()`'s return value used to be discarded once existence was
    confirmed, so a video file could be linked in as an `image` result
    and vice versa). Both checks run *before* the state mutation, so a
    bad `asset_id` -- unknown, or the wrong media type -- never gets
    written into canonical state.

    Versioning follows `domain.append_result_version` for the "append
    beside current" case (ticket 12 repair, condition 13 -- the result
    twin of `authoring_scenes.add_prompt_version`'s use of `domain.
    append_prompt_version`); the very first version of a brand-new group
    goes through `domain.start_result_version` instead (ticket 17
    condition 5 -- the result twin of `add_prompt_version`'s own
    `domain.start_prompt_version`), the same asymmetry `add_prompt_
    version` has, now built by one shared domain helper on both sides
    instead of each `authoring_*` module hand-rolling its own copy (which
    had quietly diverged on whether the dict even carried a
    `parent_version_id` at all).
    `require_owning_scene_matches` refuses an explicit `--result-id` that
    names a different scene's group, for the same reason it refuses one
    for `--prompt-id`. `hidden`/`retired`/`decisions` are left unset on a
    freshly created version (they belong to the dashboard's own
    hide/retire/approve decisions, ticket 11), and this function never
    touches `scene.linkage_status` -- an earlier `review_linkage` a scene
    edit set stays exactly as it was.

    Ticket 12 repair, condition 6: the asset must have been registered
    with the `result` role -- one registered as a character/object/
    product/style/location reference must not be linkable in here, the
    mirror of `add_reference`'s own check below.

    Scenario prose and scene descriptions are independent (D01), so the
    result binds to its owning scene without a scenario-version guard.
    """

    if target is not None:
        if scene_id is not None or kind is not None or result_id is not None:
            raise AuthoringError("--target cannot be combined with scene, kind or result-id")
        from .authoring_positions import add_position_version
        return add_position_version(store, project_id, expected_revision,
            target=target, side="result", assets=assets_index, asset_id=asset_id, caption=caption)
    if kind not in _RESULT_KIND_FIELDS:
        raise AuthoringError("result kind must be image or video")
    safe_id(asset_id, "asset_id")
    if result_id is not None:
        safe_id(result_id, "result_id")
    caption = optional_bounded_text(caption, "caption")
    list_key, link_key = _RESULT_KIND_FIELDS[kind]

    # Fail before ever touching `state.json`: an asset that does not
    # resolve (never registered, or changed/deleted since), or that
    # resolves to the wrong media type for `kind`, must not be linked
    # into canonical state at all.
    _, mime_type = assets_index.resolve(asset_id)
    if kind == "image":
        require_image_mime(mime_type, "an image result's asset")
    else:
        require_video_mime(mime_type, "a video result's asset")
    require_result_asset_role(assets_index.role_of(asset_id), "a result's asset")

    def mutator(state):
        project = require_project(state)
        if kind == "video" and project.get("type") == "photo":
            raise AuthoringError("a photo project cannot have video results")
        require_stage_not_approved(state, _RESULT_KIND_STAGE[kind], "result add-version")
        scene = find_scene(state, scene_id)
        items = state.setdefault(list_key, [])
        if not isinstance(items, list):
            raise AuthoringError(f"{list_key} must be a list")
        links = scene_links(scene)
        from .domain_positions import scene_group_id
        group_result_id = scene_group_id(state, scene, kind, "result", list_key, link_key, result_id)
        group = [
            item
            for item in items
            if isinstance(item, dict) and item.get("result_id") == group_result_id
        ]

        if not group:
            new_version = domain.start_result_version(
                group_result_id, asset_id, scene_id=scene_id, caption=caption
            )
            items.append(new_version)
            version_id = new_version["version_id"]
        else:
            current = resolve_current_group_member(group, links.get(link_key))
            require_owning_scene_matches(current, scene_id, f"result_id {group_result_id!r}")
            new_version = domain.append_result_version(
                state, current, asset_id, list_key=list_key, link_key=link_key, caption=caption
            )
            version_id = new_version["version_id"]

        links[link_key] = version_id
        domain.append_history(
            state,
            "agent",
            "result-ready",
            _RESULT_KIND_STAGE[kind],
            target_id=group_result_id,
        )
        return group_result_id, version_id

    (returned_result_id, version_id), new_state = mutate(
        store, project_id, expected_revision, mutator
    )
    return {
        "project_id": project_id,
        "result_id": returned_result_id,
        "version_id": version_id,
        "revision": new_state["revision"],
    }


def add_reference(
    store: ProjectStore,
    assets_index: AssetIndex,
    project_id: str,
    expected_revision: int,
    *,
    kind: str,
    name: str | None = None,
    asset_id: str | None = None,
    source: str = "upload",
    usage: str = "reference",
    scene_id: str | None = None,
    all_scenes: bool = False,
) -> dict:
    """Create a tagged project or scene-local reference.

    Tag allocation and every inclusion link are written by the shared domain
    mutation while ``ProjectStore.transact`` holds the project lock.
    """

    name = optional_bounded_text(name, "name")
    if scene_id is not None:
        safe_id(scene_id, "scene_id")
    if asset_id is not None:
        safe_id(asset_id, "asset_id")
        _, mime_type = assets_index.resolve(asset_id)
        role = assets_index.role_of(asset_id)
        if kind == "video":
            require_video_mime(mime_type, "a video reference's asset")
            require_video_reference_asset_role(role, "a video reference's asset")
        else:
            require_image_mime(mime_type, "an image reference's asset")
            require_reference_asset_role(role, "an image reference's asset")

    def mutator(state):
        _require_reference_writable(state, "reference add")
        try:
            entry = domain.add_reference(
                state,
                kind=kind,
                name=name,
                source=source,
                usage=usage,
                scene_id=scene_id,
                all_scenes=all_scenes,
            )
        except domain.DomainValidationError as error:
            raise AuthoringError(str(error)) from error
        if asset_id is not None:
            domain.find_reference(state, entry["reference_id"])["asset_id"] = asset_id
        return entry["reference_id"]

    reference_id, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "reference_id": reference_id, "revision": new_state["revision"]}


def edit_reference(
    store: ProjectStore,
    project_id: str,
    expected_revision: int,
    *,
    reference_id: str,
    field: str,
    value,
) -> dict:
    safe_id(reference_id, "reference_id")

    def mutator(state):
        _require_reference_writable(state, "reference edit")
        try:
            domain.edit_reference(state, reference_id, field, value)
        except domain.DomainValidationError as error:
            raise AuthoringError(str(error)) from error

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "reference_id": reference_id, "revision": new_state["revision"]}


def attach_reference(
    store: ProjectStore,
    assets_index: AssetIndex,
    project_id: str,
    expected_revision: int,
    *,
    reference_id: str,
    asset_id: str,
) -> dict:
    safe_id(reference_id, "reference_id")
    safe_id(asset_id, "asset_id")
    _, mime_type = assets_index.resolve(asset_id)
    role = assets_index.role_of(asset_id)
    if role == "voice" or mime_type.startswith("audio/"):
        require_voice_asset(mime_type, role, "a voice reference's asset")
        attachment_kind = "voice"
    elif role == VIDEO_REFERENCE_ROLE or mime_type.startswith("video/"):
        require_video_mime(mime_type, "a video reference's asset")
        require_video_reference_asset_role(role, "a video reference's asset")
        attachment_kind = "video"
    else:
        require_image_mime(mime_type, "an image reference's asset")
        require_reference_asset_role(role, "an image reference's asset")
        attachment_kind = "image"

    def mutator(state):
        _require_reference_writable(state, "reference attach")
        try:
            domain.attach_reference_asset(
                state, reference_id, asset_id, attachment_kind=attachment_kind
            )
        except domain.DomainValidationError as error:
            raise AuthoringError(str(error)) from error

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "reference_id": reference_id, "revision": new_state["revision"]}


def toggle_scene_reference(
    store: ProjectStore,
    project_id: str,
    expected_revision: int,
    *,
    scene_id: str,
    reference_id: str,
    on: bool,
) -> dict:
    safe_id(scene_id, "scene_id")
    safe_id(reference_id, "reference_id")

    def mutator(state):
        _require_reference_writable(state, "reference toggle")
        try:
            domain.toggle_scene_reference(state, scene_id, reference_id, on)
        except domain.DomainValidationError as error:
            raise AuthoringError(str(error)) from error

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "reference_id": reference_id, "revision": new_state["revision"]}

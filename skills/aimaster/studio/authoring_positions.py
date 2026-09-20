"""Chat authoring for an explicitly addressed generation position."""
from . import domain
from .authoring_support import (
    _AUTHOR, AuthoringError, mutate, non_empty_text, optional_bounded_text,
    require_audio_mime, require_image_mime, require_video_mime,
    require_result_asset_role, require_stage_not_approved, safe_id,
)
from .decision_cards import STAGE_COLLECTIONS
from .domain_positions import resolve_position, owner_links, current_member


def add_position_version(store, project_id, revision, *, target, side,
                         text=None, reason=None, assets=None, asset_id=None, caption=None):
    """One owner lookup and one transaction for first and subsequent versions."""
    safe_id(target, "target")
    if side == "prompt":
        non_empty_text(text, "text")
        non_empty_text(reason, "reason")
    else:
        safe_id(asset_id, "asset_id")
        caption = optional_bounded_text(caption, "caption")

    def apply(state):
        spec = resolve_position(state, target)
        collection = spec[side + "_collection"]
        generation_stage = STAGE_COLLECTIONS[spec["result_collection"]][0]
        stage = domain.derive_view_stage(state)["current_stage"]
        sequence = domain._stage_sequence(state)
        earliest = generation_stage if side == "result" or spec["kind"] == "audio" else "image_plan"
        if sequence.index(stage) < sequence.index(earliest):
            raise AuthoringError("position is not writable before its stage")
        require_stage_not_approved(state, generation_stage, side + " add-version")
        if side == "result":
            _, mime = assets.resolve(asset_id)
            guard = {"image_results": require_image_mime, "video_results": require_video_mime,
                     "audio_results": require_audio_mime}[collection]
            guard(mime, "a position result's asset")
            require_result_asset_role(assets.role_of(asset_id), "a position result's asset")
        else:
            try:
                domain.validate_prompt_tags(text, spec)
                basis = domain.prompt_basis(state, spec)
            except domain.DomainValidationError as error:
                raise AuthoringError(str(error)) from error
        current = current_member(state, spec, side)
        group_id = spec[side + "_group_id"]
        items = state.get(collection, [])
        if current is None and any(item.get(side + "_id") == group_id for item in items):
            raise AuthoringError("existing group has no current owner link")
        if current is not None and current.get(side + "_id") != group_id:
            # A compatible legacy scene group keeps its existing identity/history.
            group_id = current[side + "_id"]
        if current is None:
            if side == "prompt":
                version = domain.start_prompt_version(
                    group_id, text, reason, _AUTHOR,
                    scene_id=spec.get("scene_id"), basis=basis,
                )
            else:
                version = domain.start_result_version(group_id, asset_id, scene_id=spec.get("scene_id"), caption=caption)
            state.setdefault(collection, []).append(version)
        elif side == "prompt":
            version = domain.append_prompt_version(state, current, text, reason, _AUTHOR,
                list_key=collection, link_key=spec["prompt_link"], basis=basis)
        else:
            version = domain.append_result_version(state, current, asset_id,
                list_key=collection, link_key=spec["result_link"], caption=caption)
        owner_links(state, spec, create=True)[spec[side + "_link"]] = version["version_id"]
        history_stage = STAGE_COLLECTIONS[collection][0]
        domain.append_history(state, "agent", side + "-ready", history_stage, target_id=group_id)
        return group_id, version["version_id"]

    (group_id, version_id), state = mutate(store, project_id, revision, apply)
    return {"project_id": project_id, side + "_id": group_id,
            "version_id": version_id, "revision": state["revision"]}

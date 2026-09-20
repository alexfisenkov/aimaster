"""Generation positions and their version owners; no I/O or stored statuses.

Identity is constructed from existing owners, never decoded by splitting a
user-supplied scene ID. Scene IDs can themselves contain ':' and '-vN'.
"""
from __future__ import annotations

import re

from .domain import DomainValidationError, frame_basis

AUDIO_LAYERS = ("atmos", "fx", "music", "voice")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def require_position_id(value):
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise DomainValidationError("position/group/version id must fit the safe 128-character format")
    return value


def _spec(body, kind, owner_kind, owner_id, prompt_collection, result_collection,
          prompt_link, result_link, **public):
    return dict(position_id="pos:" + body, kind=kind,
        prompt_group_id="prompt:" + body, result_group_id="result:" + body,
        owner_kind=owner_kind, owner_id=owner_id,
        prompt_collection=prompt_collection, result_collection=result_collection,
        prompt_link=prompt_link, result_link=result_link, **public)


def position_specs(state, *, include_inactive=False):
    """Enumerate the plan, or all retained owners for relinking old material."""
    photo = state.get("project", {}).get("type") == "photo"
    specs = []
    for ref in state.get("references", []):
        if ref.get("role") == "video":
            continue
        if include_inactive or ref.get("source", "upload") == "generate":
            tag = ref["reference_id"]
            specs.append(_spec(f"ref:{tag}", "reference", "reference", tag,
                "image_prompts", "image_results", "image_prompt_version_id", "image_result_id", tag=tag))
    for scene in sorted(state.get("scenes", []), key=lambda item: item.get("order", 0)):
        sid = scene["scene_id"]
        if photo or include_inactive:
            specs.append(_spec(f"scene:{sid}:image", "image", "scene", sid,
                "image_prompts", "image_results", "image_prompt_version_id", "image_result_id", scene_id=sid))
        if photo:
            continue
        basis = frame_basis(scene)
        for edge in ("first", "last"):
            if include_inactive or basis["need_" + edge]:
                specs.append(_spec(f"frame:{sid}:{edge}", edge + "_frame", "scene", sid,
                    "image_prompts", "image_results", edge + "_frame_prompt_version_id",
                    edge + "_frame_result_id", scene_id=sid))
        if include_inactive or state.get("gen_mode", "per_scene") == "per_scene":
            specs.append(_spec(f"scene:{sid}:video", "video", "scene", sid,
                "motion_prompts", "video_results", "motion_prompt_version_id", "video_result_id", scene_id=sid))
    if not photo:
        if include_inactive or state.get("gen_mode", "per_scene") == "one_shot":
            specs.append(_spec("oneshot", "oneshot", "oneshot", "oneshot",
                "motion_prompts", "video_results", "motion_prompt_version_id", "video_result_id"))
        for layer in AUDIO_LAYERS:
            specs.append(_spec(f"audio:{layer}", "audio", "audio", layer,
                "audio_prompts", "audio_results", "audio_prompt_version_id", "audio_result_id", layer=layer))
    return specs


def resolve_position(state, target):
    require_position_id(target)
    matches = [item for item in position_specs(state) if item["position_id"] == target]
    if len(matches) != 1:
        raise DomainValidationError("target must name exactly one active generation position")
    spec = matches[0]
    for key in ("prompt_group_id", "result_group_id"):
        require_position_id(spec[key] + "-v1")
    return spec


def group_owner(state, group_id, list_key):
    """Find a typed group's exact owner, including material outside today's plan."""
    side = "prompt" if group_id.startswith("prompt:") else "result" if group_id.startswith("result:") else None
    if side is None:
        return None  # legacy IDs keep the original scene-link semantics
    matches = [item for item in position_specs(state, include_inactive=True)
        if item[side + "_group_id"] == group_id and item[side + "_collection"] == list_key]
    if len(matches) != 1:
        raise DomainValidationError("typed version group has no unique owner in its collection")
    return matches[0]


def owner_links(state, spec, *, create=False):
    kind, identity = spec["owner_kind"], spec["owner_id"]
    if kind == "oneshot":
        owner = state.setdefault("oneshot", {"links": {}}) if create else state.get("oneshot")
    else:
        collection, key = {"scene": ("scenes", "scene_id"),
            "reference": ("references", "reference_id"), "audio": ("audio_layers", "layer")}[kind]
        owners = state.get(collection, [])
        matches = [item for item in owners if item.get(key) == identity]
        if len(matches) > 1:
            raise DomainValidationError("duplicate position owner")
        owner = matches[0] if matches else None
        if owner is None and create and kind == "audio":
            owner = {"layer": identity, "links": {}}
            state.setdefault(collection, []).append(owner)
    if owner is None:
        if create:
            raise DomainValidationError("position owner is missing")
        return {}
    links = owner.setdefault("links", {}) if create else owner.get("links", {})
    if not isinstance(links, dict):
        raise DomainValidationError("owner.links must be an object")
    return links


def current_member(state, spec, side, *, missing_ok=False):
    """Follow the owner pointer; never select the newest sibling by list order."""
    linked = owner_links(state, spec).get(spec[side + "_link"])
    if not linked:
        return None
    matches = [item for item in state.get(spec[side + "_collection"], [])
        if item.get("version_id", item.get(side + "_id")) == linked]
    if not matches and missing_ok:
        return None
    if len(matches) != 1:
        raise DomainValidationError("current owner link must name one version")
    item = matches[0]
    if "scene_id" in item and item["scene_id"] != spec.get("scene_id"):
        raise DomainValidationError("current version belongs to another scene")
    # Typed links may not be redirected to another position's group.
    gid = item.get(side + "_id", "")
    if gid.startswith(("prompt:", "result:")) and gid != spec[side + "_group_id"]:
        raise DomainValidationError("current version belongs to another position")
    return item


def current_prompt_spec(state, collection, prompt):
    """Return the sole owner whose link names this exact prompt version."""
    if not isinstance(prompt, dict):
        raise DomainValidationError("prompt must be an object")
    identity = prompt.get("version_id", prompt.get("prompt_id"))
    legacy_link = {
        "image_prompts": "image_prompt_version_id",
        "motion_prompts": "motion_prompt_version_id",
        "audio_prompts": "audio_prompt_version_id",
    }.get(collection)
    matches = []
    for spec in position_specs(state, include_inactive=True):
        if spec["prompt_collection"] != collection:
            continue
        linked = owner_links(state, spec).get(spec["prompt_link"])
        if linked == identity:
            matches.append(spec)
    if not matches:
        group_id = prompt.get("prompt_id")
        legacy_matches = []
        for spec in position_specs(state, include_inactive=True):
            if spec["prompt_collection"] != collection or spec["owner_kind"] != "scene":
                continue
            if spec["prompt_link"] != legacy_link:
                continue
            owner = next((scene for scene in state.get("scenes", [])
                          if isinstance(scene, dict) and scene.get("scene_id") == spec["owner_id"]), None)
            links = owner.get("links", {}) if isinstance(owner, dict) else {}
            legacy_ids = links.get("prompt_version_ids", []) if isinstance(links, dict) else []
            if isinstance(legacy_ids, list) and (identity in legacy_ids or group_id in legacy_ids):
                legacy_matches.append(spec)
        matches = legacy_matches
    if not matches and isinstance(prompt.get("scene_id"), str):
        matches = [
            spec for spec in position_specs(state, include_inactive=True)
            if spec["prompt_collection"] == collection
            and spec["owner_kind"] == "scene"
            and spec["owner_id"] == prompt["scene_id"]
            and spec["prompt_link"] == legacy_link
        ]
    if len(matches) != 1:
        raise DomainValidationError("current prompt must have exactly one owner link")
    return matches[0]


def scene_group_id(state, scene, kind, side, collection, link_key, explicit=None):
    """Preserve linked legacy groups; new scene-form defaults are namespaced."""
    group_id = explicit
    if group_id is None:
        linked = scene.get("links", {}).get(link_key)
        matches = [item for item in state.get(collection, [])
            if item.get("version_id", item.get(side + "_id")) == linked] if linked else []
        if len(matches) > 1:
            raise DomainValidationError("ambiguous current scene version")
        if matches:
            if matches[0].get("scene_id", scene["scene_id"]) != scene["scene_id"]:
                raise DomainValidationError("current group belongs to another scene")
            group_id = matches[0][side + "_id"]
        else:
            media = "video" if kind in {"motion", "video"} else "image"
            group_id = f"{side}:scene:{scene['scene_id']}:{media}"
    require_position_id(group_id + "-v1")
    owner = group_owner(state, group_id, collection)
    if owner is not None and (owner["owner_kind"] != "scene" or owner["owner_id"] != scene["scene_id"]
                              or owner[side + "_link"] != link_key):
        raise DomainValidationError("group belongs to another owner or position")
    return group_id


def derive_positions(state):
    from .decision_cards import STAGE_COLLECTIONS
    positions = []
    for spec in position_specs(state):
        position = {key: spec[key] for key in ("position_id", "kind", "scene_id", "tag", "layer",
            "prompt_group_id", "result_group_id") if key in spec}
        position.update(stage=STAGE_COLLECTIONS[spec["result_collection"]][0], required=True, status="none")
        result = current_member(state, spec, "result")
        targets = {spec["position_id"], spec["result_group_id"]}
        if result:
            targets.update(filter(None, (result.get("result_id"), result.get("version_id"))))
            position["result_group_id"] = result["result_id"]
            position["status"] = "accepted" if result.get("decision") == "approved" and not result.get("retired") else "ready"
            targets.update(item.get("version_id") for item in state.get(spec["result_collection"], [])
                           if item.get("result_id") == result["result_id"] and item.get("version_id"))
        prompt = current_member(state, spec, "prompt")
        if prompt:
            position["prompt_group_id"] = prompt["prompt_id"]
        if any(action.get("target_id") in targets and action.get("status") in {"queued", "running"}
               for action in state.get("actions", [])):
            position["status"] = "working"
        positions.append(position)
    from .domain import _stage_sequence
    sequence = _stage_sequence(state)
    return sorted((position for position in positions if position["stage"] in sequence),
                  key=lambda position: sequence.index(position["stage"]))

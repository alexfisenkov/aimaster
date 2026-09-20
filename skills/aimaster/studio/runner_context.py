"""Canonical, untrusted creative context for the four new operator actions.

This module never selects a provider, executes a prompt or touches a grant.
Its input is the same fresh state that the runner used for the claim gate.
"""
from . import domain
from .decision_cards import STAGE_COLLECTIONS, PROMPT_EDIT_COLLECTIONS_BY_STAGE
from .domain_positions import current_member, position_specs, resolve_position
from .stage_readiness import require_accepted_frames

CONTEXT_ACTION_TYPES = frozenset({"generate", "prompts-generate", "prompt-refresh", "assemble"})


def _scene(state, identity):
    matches = [s for s in state.get("scenes", []) if s.get("scene_id") == identity]
    if len(matches) != 1:
        raise domain.DomainValidationError("target must name one scene")
    return matches[0]


def _refresh_specs(state, target):
    view = domain.derive_view_stage(state)
    collections = PROMPT_EDIT_COLLECTIONS_BY_STAGE.get(view["current_stage"], ())
    if target.startswith("pos:"):
        specs = [resolve_position(state, target)]
    else:
        _scene(state, target)
        specs = [s for s in position_specs(state) if s.get("scene_id") == target or s["kind"] == "oneshot"]
    specs = [s for s in specs if s["prompt_collection"] in collections]
    if not specs:
        raise domain.DomainValidationError("target has no writable prompts on this stage")
    return specs


def new_action_target_stage(state, action_type, target):
    """Strict targets for new actions; never the legacy unknown-id fallback."""
    if action_type == "generate":
        return STAGE_COLLECTIONS[resolve_position(state, target)["result_collection"]][0]
    if action_type == "prompt-refresh":
        _refresh_specs(state, target)
        return domain.derive_view_stage(state)["current_stage"]
    expected = {"prompts-generate": ("project", "image_plan"),
                "assemble": ("final", "assembly"),
                "set-mode": ("project", domain.derive_view_stage(state)["current_stage"])}
    expected_target, stage = expected[action_type]
    if target != expected_target:
        raise domain.DomainValidationError("action target is not supported")
    return stage


def _ordered_scenes(state):
    return sorted(state.get("scenes", []), key=lambda s: s.get("order", 0))


def _included_references(state, spec, *, for_generation=False):
    """Explicit scene membership; static images never inherit voice assets."""
    kind = spec["kind"]
    scenes = _ordered_scenes(state)
    if spec.get("scene_id"):
        scenes = [_scene(state, spec["scene_id"])]
    if kind == "reference":
        # Reference defaults may cite a project style, independently of scene
        # membership. A local style is never borrowed by another owner.
        refs = [r for r in state.get("references", []) if r.get("role") == "style"
                and not r.get("local") and r.get("reference_id") != spec["owner_id"]]
        if for_generation:
            prompt = current_member(state, spec, "prompt", missing_ok=True)
            used_tags = set(domain.extract_tags(prompt["text"])) if prompt else set()
            refs = [r for r in refs if r.get("tag", r["reference_id"]) in used_tags]
        voice = False
    else:
        if kind == "audio":
            scenes = scenes[-1:] if spec.get("layer") == "voice" else []
        allowed_ids = {identity for scene in scenes for identity in scene.get("links", {}).get("reference_ids", [])}
        refs = [r for r in state.get("references", []) if r.get("reference_id") in allowed_ids]
        voice = kind in {"video", "oneshot"} or (kind == "audio" and spec.get("layer") == "voice")
    result = []
    for ref in refs:
        item = {"reference_id": ref["reference_id"], "kind": ref.get("role"), "name": ref.get("label", "")}
        if kind != "audio":
            item["tag"] = ref.get("tag", ref["reference_id"])
            asset = ref.get("asset_id")
            if ref.get("source") == "generate":
                ref_spec = resolve_position(state, "pos:ref:" + ref["reference_id"])
                current = current_member(state, ref_spec, "result", missing_ok=True)
                asset = current.get("asset_id") if current and current.get("decision") == "approved" and not current.get("retired") else None
            if asset:
                item["asset_id"] = asset
        data = ref.get("voice", {})
        if voice and ref.get("role") == "character" and data.get("enabled") and data.get("tag") and data.get("asset_id"):
            item["voice"] = {"tag": data["tag"], "asset_id": data["asset_id"]}
        if "tag" in item or "voice" in item:
            result.append(item)
    return result


def _scene_context(scene):
    block = scene.get("script_block", {})
    active = next((v for v in block.get("versions", []) if v.get("version_id") == block.get("active_version_id")), {})
    result = {"scene_id": scene["scene_id"], "title": scene.get("title", ""),
              "text": active.get("text", ""), "order": scene.get("order", 0)}
    for key in ("duration_ms", "start_ms", "end_ms"):
        if key in scene:
            result[key] = scene[key]
    return result


def _position_context(state, spec, *, for_generation=False):
    item = {key: spec[key] for key in ("position_id", "kind", "scene_id", "tag", "layer") if key in spec}
    item["stage"] = STAGE_COLLECTIONS[spec["result_collection"]][0]
    prompt = current_member(state, spec, "prompt", missing_ok=True)
    item["prompt"] = ({"version_id": prompt.get("version_id", prompt["prompt_id"]), "text": prompt["text"]} if prompt else None)
    item["references"] = _included_references(state, spec, for_generation=for_generation)
    item["allowed_tags"] = [tag for ref in item["references"] for tag in
        (ref.get("tag"), ref.get("voice", {}).get("tag")) if tag]
    if spec.get("scene_id"):
        item["scene"] = _scene_context(_scene(state, spec["scene_id"]))
    if spec["kind"] == "video":
        scene = _scene(state, spec["scene_id"])
        mode = domain.frame_basis(scene)["video_mode"]
        item["video_mode"] = mode
        item["frames"] = []
        for edge in (("first", "last") if mode == "firstlast" else ("first",) if mode == "first" else ()):
            frame = resolve_position(state, f"pos:frame:{scene['scene_id']}:{edge}")
            current = current_member(state, frame, "result", missing_ok=True)
            if current and current.get("decision") == "approved" and not current.get("retired"):
                item["frames"].append({"edge": edge, "asset_id": current["asset_id"], "version_id": current.get("version_id", current["result_id"])})
    return item


def build_action_context(state, action):
    """Validate one new job and return explicit operator data, never authority."""
    kind, target = action["action_type"], action["target_id"]
    stage = domain.derive_view_stage(state)["current_stage"]
    if new_action_target_stage(state, kind, target) != stage:
        raise domain.DomainValidationError("action belongs to another current stage")
    positions = domain.derive_positions(state)
    if kind == "generate":
        spec = resolve_position(state, target)
        position = next(p for p in positions if p["position_id"] == target)
        if position["status"] != "none":
            raise domain.DomainValidationError("generation position is not empty or is busy")
        prompt = current_member(state, spec, "prompt", missing_ok=True)
        if not prompt or not isinstance(prompt.get("text"), str) or not prompt["text"].strip():
            raise domain.DomainValidationError("generation requires a current prompt")
        if spec["kind"] == "video":
            scene = _scene(state, spec["scene_id"])
            require_accepted_frames(state, spec["scene_id"], domain.frame_basis(scene)["video_mode"])
        specs = [spec]
    elif kind == "prompts-generate":
        specs = [s for s in position_specs(state) if s["prompt_collection"] in {"image_prompts", "motion_prompts"}]
    elif kind == "prompt-refresh":
        specs = _refresh_specs(state, target)
    else:  # Assembly gets accepted material only, not rejected/retired siblings.
        accepted = {p["position_id"] for p in positions if p["status"] == "accepted"}
        specs = [s for s in position_specs(state) if s["position_id"] in accepted]
    context = {"state_revision": state["revision"], "stage": stage,
               "positions": [_position_context(state, spec, for_generation=kind == "generate") for spec in specs]}
    if state["project"]["type"] != "photo":
        context["gen_mode"] = state.get("gen_mode", "per_scene")
    if kind == "generate":
        item = context["positions"][0]
        if set(domain.extract_tags(item["prompt"]["text"])) - set(item["allowed_tags"]):
            raise domain.DomainValidationError("prompt contains excluded or unavailable reference tags")
        if any(ref.get("tag") and (not isinstance(ref.get("asset_id"), str) or not ref["asset_id"].strip())
               for ref in item["references"]):
            raise domain.DomainValidationError("generation requires every included image reference asset")
    if kind in {"prompts-generate", "assemble"} or any(s["kind"] == "oneshot" for s in specs):
        context["scenes"] = [_scene_context(s) for s in _ordered_scenes(state)]
    if kind == "assemble":
        for spec, item in zip(specs, context["positions"]):
            result = current_member(state, spec, "result")
            item["result"] = {"version_id": result.get("version_id", result["result_id"]), "asset_id": result["asset_id"]}
    return context

"""Current-stage approval metadata and shared generation prerequisites.

No stored readiness flags or browser copy of the position rules. The same
function is used inside the decision transaction and by the projection.
"""
from . import domain
from .domain_positions import current_member, resolve_position

READINESS_REASONS = frozenset({"blocked", "already_approved", "incomplete_storyboard",
                              "missing_prompts", "unaccepted_positions",
                              "missing_final_material", "assembly_choice_required", "stale_assembly"})


def _has_final_material(state):
    mode = state.get("project", {}).get("assembly_mode", "montage")
    if mode == "materials":
        from .completion import materials_ready
        return materials_ready(state)
    if state.get("assembly", {}).get("kind") == "materials":
        return False
    if state.get("project", {}).get("type") == "photo":
        return any(
            position.get("kind") == "image"
            and position.get("stage") == "image_results"
            and position.get("status") == "accepted"
            for position in domain.derive_positions(state)
        )
    assembly = state.get("assembly")
    return (
        isinstance(assembly, dict)
        and assembly.get("status") == "ready"
        and isinstance(assembly.get("asset_id"), str)
        and bool(assembly["asset_id"].strip())
    )


def stage_readiness(state, *, project_directory=None):
    view = domain.derive_view_stage(state)
    stage = view["current_stage"]
    result = {"stage": stage, "can_approve": True, "reason": None}
    positions = domain.derive_positions(state) if stage in {"image_plan", "image_results", "motion", "audio"} else []
    if stage == "image_plan":
        result["image_position_count"] = sum(p["stage"] == "image_results" for p in positions)
    if view["gate_status"] in {"blocked", "approved"}:
        result["reason"] = "blocked" if view["gate_status"] == "blocked" else "already_approved"
    elif stage == "scenario":
        try:
            domain.require_storyboard_complete(state)
        except domain.DomainValidationError:
            result["reason"] = "incomplete_storyboard"
        if (state.get("project", {}).get("mode") == "autopilot"
                and state.get("project", {}).get("assembly_mode", "montage") is None):
            result["reason"] = "assembly_choice_required"
    elif stage in {"image_plan", "motion"}:
        for position in positions:
            target_stage = "image_results" if stage == "image_plan" else "motion"
            if not position["required"] or position["stage"] != target_stage:
                continue
            spec = resolve_position(state, position["position_id"])
            prompt = current_member(state, spec, "prompt", missing_ok=True)
            if (not prompt or not isinstance(prompt.get("text"), str) or not prompt["text"].strip()
                    or prompt.get("status") == "rejected"
                    or domain.compute_prompt_stale(state, prompt, spec)):
                result["reason"] = "missing_prompts"
                break
            if stage == "motion" and spec["kind"] == "video":
                try:
                    scene = next(s for s in state.get("scenes", []) if s.get("scene_id") == spec["scene_id"])
                    domain.require_continuity_choice(state, spec["scene_id"])
                    require_accepted_frames(state, spec["scene_id"], domain.frame_basis(scene)["video_mode"])
                except (StopIteration, domain.DomainValidationError):
                    result["reason"] = "unaccepted_positions"
                    break
        if stage == "motion" and result["reason"] is None and any(
                p["required"] and p["stage"] == stage and p["status"] != "accepted" for p in positions):
            result["reason"] = "unaccepted_positions"
    elif stage in {"image_results", "audio"}:
        if any(p["required"] and p["stage"] == stage and p["status"] != "accepted" for p in positions):
            result["reason"] = "unaccepted_positions"
    elif stage == "assembly":
        if state.get("project", {}).get("assembly_mode", "montage") is None:
            result["reason"] = "assembly_choice_required"
        elif not _has_final_material(state):
            result["reason"] = "missing_final_material"
        elif project_directory is not None and state.get("project", {}).get("assembly_mode", "montage") == "montage":
            from .completion import CompletionError, verify_montage_sources
            try:
                verify_montage_sources(state, project_directory)
            except CompletionError:
                result["reason"] = "stale_assembly"
    result["can_approve"] = result["reason"] is None
    return result


def require_accepted_frames(state, scene_id, mode):
    """Both the video-mode decision and paid claim enforce the same frame gate."""
    if mode == "references":
        return
    scene = next((s for s in state.get("scenes", []) if s.get("scene_id") == scene_id), None)
    if scene is None:
        raise domain.DomainValidationError("video scene is missing")
    basis = domain.frame_basis(scene)
    edges = ("first", "last") if mode == "firstlast" else ("first",)
    positions = {p["position_id"]: p for p in domain.derive_positions(state)}
    for edge in edges:
        target = f"pos:frame:{scene_id}:{edge}"
        if not basis["need_" + edge] or positions.get(target, {}).get("status") != "accepted":
            raise domain.DomainValidationError("video mode requires accepted planned frames")

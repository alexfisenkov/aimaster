"""Chat-authored scene splits and per-scene image/motion prompts.

Ticket 12 repair, condition 15: one of six `authoring_*` responsibility
modules split out of the former monolithic `authoring.py` -- this one owns
`scenes set` and `prompt add-version`. See `authoring_support.py`'s module
docstring for the split's rationale.

Ticket 15 repair, поправка оркестратора 1 (G05): this module also owns
`edit_scene_block` -- the CLI's `scene edit <workspace> <project>
<scene_id> --expected-revision N --text TEXT --reason TEXT`, chat's own
door onto a scene block's `edit`, now that `domain._STAGE_ACTIONS`
admits `edit` at `scenario` too (the one stage after a reopen where
nothing else is even visible yet). It belongs here, not in `authoring_
milestones.py` alongside `reopen_scenario`, because it edits a *scene*,
the same subject `scenes set`/`prompt add-version` above already own --
not a milestone.
"""

from __future__ import annotations

from . import decision_stages, domain
from .decision_reorder import plan_reorder
from .decision_planners import plan_scene_frame_plan, plan_set_gen_mode, plan_set_video_mode
from .authoring_support import (
    _AUTHOR,
    AuthoringError,
    find_scene,
    mutate,
    non_empty_text,
    require_owning_scene_matches,
    require_project,
    require_stage_not_approved,
    resolve_current_group_member,
    safe_id,
    scene_has_edited_block_history,
    scene_has_linked_materials,
    scene_links,
)
from .store import ProjectStore
from .workspace import MAX_TEXT_BYTES


_PROMPT_KIND_FIELDS = {
    "image": ("image_prompts", "image_prompt_version_id"),
    "motion": ("motion_prompts", "motion_prompt_version_id"),
}
_PROMPT_HISTORY_STAGE = {"image": "image_plan", "motion": "motion"}
# Ticket 13 (spec §3/§7, "перегенерировать промпт"): which milestone
# `add_prompt_version` refuses to write past once it is `approved`. Not
# each kind's *planning* milestone (ticket 12's original rule gated an
# image prompt on `image_plan` itself, which blocked every regeneration
# the moment the plan was approved -- exactly the bug this ticket fixes)
# but each kind's own *generation* stage, the one that actually consumes
# a regenerated prompt: `image_results` for an image prompt, `motion`
# for a motion prompt (unchanged for motion -- it was already gated on
# its own generation stage, not on a separate planning one). Approving
# `image_plan` no longer closes this door at all; approving
# `image_results`/`motion` itself is what finally does.
_PROMPT_KIND_STAGE = {"image": "image_results", "motion": "motion"}


def _refuse_if_scenes_are_not_replaceable(existing) -> None:
    """Refuse `scenes set` if it would silently discard something.

    Two ways an existing scene is not safely replaceable (ticket 12
    repair, blocking condition 8, extending the review's original
    links-only check):

    - it already has a populated `links` entry (a prompt/result/
      reference already points at it) -- overwriting it would discard
      that link without the review decision §3 requires; or
    - its `script_block.versions` history is already longer than one
      entry -- an `edit` decision (ticket 11, `domain.
      append_scene_block_version`) already versioned this scene's own
      text at least once, and `_build_initial_scene` below always starts
      a scene at a fresh, single-entry `-block-v1` history, which would
      silently erase every edit made since.

    Refuses the whole call rather than attempting a partial merge: which
    of the *new* payload's fields should still apply to an
    already-edited scene is not this ticket's decision to make silently.

    The two underlying facts checked below live once, in
    `authoring_support.scene_has_linked_materials` and
    `scene_has_edited_block_history`.
    """

    if not isinstance(existing, list):
        return
    for scene in existing:
        if scene_has_linked_materials(scene):
            raise AuthoringError(
                "scenes already have linked prompts or results; "
                "scenes set would discard them"
            )
        if scene_has_edited_block_history(scene):
            raise AuthoringError(
                "scenes already have edited script-block history; "
                "scenes set would discard it"
            )


def _build_initial_scene(raw, position, needs_timeline) -> dict:
    if not isinstance(raw, dict):
        raise AuthoringError(f"scenes[{position}] must be an object")
    allowed = {"scene_id", "title", "text", "duration_ms"}
    unknown = set(raw) - allowed
    if unknown:
        raise AuthoringError(f"unknown scenes[{position}] keys: {sorted(unknown)!r}")
    scene_id = raw.get("scene_id")
    safe_id(scene_id, f"scenes[{position}].scene_id")
    text = raw.get("text")
    non_empty_text(text, f"scenes[{position}].text")
    title = raw.get("title", f"Кадр {position + 1}")
    if not isinstance(title, str) or len(title) > 200:
        raise AuthoringError(f"scenes[{position}].title must be a string of at most 200 characters")

    block_version_id = f"{scene_id}-block-v1"
    block_version = {
        "version_id": block_version_id,
        "parent_version_id": None,
        "text": text,
        "reason": "scenes set",
        "author": _AUTHOR,
    }
    scene = {
        "scene_id": scene_id,
        "order": position + 1,
        "title": title,
        "script_block": {
            "active_version_id": block_version_id,
            "versions": [block_version],
        },
        "links": {},
        "linkage_status": "current",
    }
    if needs_timeline:
        if "duration_ms" not in raw:
            raise AuthoringError(
                f"scenes[{position}] requires duration_ms for this project type"
            )
        scene["duration_ms"] = raw["duration_ms"]
        scene["need_first"] = False
        scene["need_last"] = False
        scene["video_mode"] = "references"
    elif "duration_ms" in raw:
        raise AuthoringError(f"scenes[{position}] must not set duration_ms for a photo project")
    return scene


def set_scenes(
    store: ProjectStore, project_id: str, expected_revision: int, scenes_input: list
) -> dict:
    """Create or replace the storyboard while `scenario` is current.

    A full replace of `state["scenes"]`, not an incremental append: this
    is the initial population step (spec §2.1's `image_plan` gate), not
    the dashboard's own `edit`/`reorder` decisions. Refuses when the
    project is not currently at `image_plan`, or when
    `_refuse_if_scenes_are_not_replaceable` finds an existing scene this
    call would silently discard.
    """

    if not isinstance(scenes_input, list) or not scenes_input:
        raise AuthoringError("scenes payload must be a non-empty list")

    def mutator(state):
        project = require_project(state)
        view = domain.derive_view_stage(state)
        if view["current_stage"] != "scenario":
            raise AuthoringError(
                f"scenes can be set only at scenario (current stage: "
                f"{view['current_stage']!r})"
            )
        _refuse_if_scenes_are_not_replaceable(state.get("scenes"))
        needs_timeline = project.get("type") in {"video", "mixed"}
        built = []
        seen_ids = set()
        for position, raw in enumerate(scenes_input):
            scene = _build_initial_scene(raw, position, needs_timeline)
            if scene["scene_id"] in seen_ids:
                raise AuthoringError(f"duplicate scene_id: {scene['scene_id']}")
            seen_ids.add(scene["scene_id"])
            built.append(scene)
        state["scenes"] = built
        try:
            domain.recompute_scene_ranges(state)
        except domain.DomainValidationError as error:
            raise AuthoringError(str(error)) from error
        domain.append_history(state, "agent", "scenes-ready", "scenario")
        return [scene["scene_id"] for scene in built]

    scene_ids, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "scene_ids": scene_ids, "revision": new_state["revision"]}


def add_scene(store: ProjectStore, project_id: str, expected_revision: int) -> dict:
    """Chat door onto the same deterministic scene-add mutation as dashboard."""

    def mutator(state):
        try:
            return domain.add_scene(state, _AUTHOR)
        except domain.DomainValidationError as error:
            raise AuthoringError(str(error)) from error

    scene, new_state = mutate(store, project_id, expected_revision, mutator)
    return {
        "project_id": project_id,
        "scene_id": scene["scene_id"],
        "revision": new_state["revision"],
    }


def set_scene_frame_plan(
    store: ProjectStore, project_id: str, expected_revision: int, *, scene_id: str, first=None, last=None
) -> dict:
    """Chat door onto the same frame-plan mutation as the decision worker."""

    planned = plan_scene_frame_plan(
        scene_id, {key: value for key, value in (("first", first), ("last", last)) if value is not None}
    )

    def mutator(state):
        decision_stages.ensure_action_allowed(state, "scene-frame-plan")
        planned(state)
        decision_stages.apply_project_status(state)

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "scene_id": scene_id, "revision": new_state["revision"]}


def set_video_mode(
    store: ProjectStore, project_id: str, expected_revision: int, *, scene_id: str, mode: str
) -> dict:
    """Chat door onto the same video-mode mutation as the decision worker."""

    planned = plan_set_video_mode(scene_id, {"mode": mode})

    def mutator(state):
        decision_stages.ensure_action_allowed(state, "set-video-mode")
        planned(state)
        decision_stages.apply_project_status(state)

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "scene_id": scene_id, "mode": mode, "revision": new_state["revision"]}


def set_continuity_strategy(
    store: ProjectStore,
    project_id: str,
    expected_revision: int,
    *,
    scene_id: str,
    strategy: str,
) -> dict:
    """Persist the chat-approved transition choice before video generation."""

    def mutator(state):
        decision_stages.ensure_action_allowed(state, "set-video-mode")
        domain.set_continuity_strategy(state, scene_id, strategy)
        decision_stages.apply_project_status(state)

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {
        "project_id": project_id,
        "scene_id": scene_id,
        "strategy": strategy,
        "revision": new_state["revision"],
    }


def set_gen_mode(store: ProjectStore, project_id: str, expected_revision: int, mode: str) -> dict:
    """Chat door onto the same project generation-mode mutation as the worker."""

    planned = plan_set_gen_mode("project", {"mode": mode})

    def mutator(state):
        decision_stages.ensure_action_allowed(state, "set-gen-mode")
        planned(state)
        decision_stages.apply_project_status(state)

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "mode": mode, "revision": new_state["revision"]}


def reorder_scenes(
    store: ProjectStore,
    project_id: str,
    expected_revision: int,
    order: list[str],
) -> dict:
    """Chat door onto the dashboard's exact scenes reorder planner."""

    planned = plan_reorder("scenes", {"order": order})

    def mutator(state):
        decision_stages.ensure_action_allowed(state, "reorder")
        planned(state)
        decision_stages.apply_project_status(state)

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {
        "project_id": project_id,
        "scene_ids": list(order),
        "revision": new_state["revision"],
    }


def add_prompt_version(
    store: ProjectStore,
    project_id: str,
    expected_revision: int,
    *,
    scene_id: str | None = None,
    kind: str | None = None,
    text: str,
    reason: str,
    prompt_id: str | None = None,
    target: str | None = None,
) -> dict:
    """Create or version an image/motion prompt for one scene.

    No `prompt_id`: the very first version of a brand-new group
    (`{scene_id}-{kind}`, `-v1`), through `domain.start_prompt_version`
    (ticket 17 condition 5) -- `domain.append_prompt_version` only knows
    how to append *beside* an existing member, not create a group's first
    one, so this is a separate domain helper rather than that same
    function somehow doing both; before this repair each `authoring_*`
    module hand-rolled its own first-version dict here, and they had
    quietly diverged on whether it even carried a `parent_version_id`.
    An existing `prompt_id` (explicit, or that same default naming a
    group already created earlier): a new version beside whichever member
    the scene's link currently names, through `domain.append_prompt_
    version` itself (ticket 12 repair, condition 13) -- passing this
    kind's own `list_key`/`link_key` (`image_prompts`/
    `image_prompt_version_id` or `motion_prompts`/
    `motion_prompt_version_id`) so both prompt kinds share the one
    versioning rule instead of a second, hand-written copy of it living
    in this module. That domain helper also relinks the scene's own link
    and tolerates a `current` still missing its own `version_id` (a
    prompt without one no longer crashes the CLI with a bare `KeyError`).

    `require_owning_scene_matches` refuses an explicit `--prompt-id` that
    actually belongs to a *different* scene, before any version is
    appended -- without it, `_resolve_current_group_member`'s
    single-member fallback would happily append beside that other
    scene's prompt and repoint *this* scene's link at it.

    Scenario prose and scene descriptions are independent (D01), so a
    prompt can attach to its owning scene regardless of which scenario
    version is active.
    """

    if target is not None:
        if scene_id is not None or kind is not None or prompt_id is not None:
            raise AuthoringError("--target cannot be combined with scene, kind or prompt-id")
        from .authoring_positions import add_position_version
        return add_position_version(store, project_id, expected_revision,
            target=target, side="prompt", text=text, reason=reason)
    if kind not in _PROMPT_KIND_FIELDS:
        raise AuthoringError("prompt kind must be image or motion")
    non_empty_text(text, "text")
    non_empty_text(reason, "reason")
    if prompt_id is not None:
        safe_id(prompt_id, "prompt_id")
    list_key, link_key = _PROMPT_KIND_FIELDS[kind]

    def mutator(state):
        project = require_project(state)
        if kind == "motion" and project.get("type") == "photo":
            raise AuthoringError("a photo project cannot have motion prompts")
        require_stage_not_approved(state, _PROMPT_KIND_STAGE[kind], "prompt add-version")
        scene = find_scene(state, scene_id)
        items = state.setdefault(list_key, [])
        if not isinstance(items, list):
            raise AuthoringError(f"{list_key} must be a list")
        links = scene_links(scene)
        from .domain_positions import scene_group_id
        group_prompt_id = scene_group_id(state, scene, kind, "prompt", list_key, link_key, prompt_id)
        specs = [
            item for item in domain.position_specs(state, include_inactive=True)
            if item.get("owner_kind") == "scene"
            and item.get("owner_id") == scene_id
            and item.get("prompt_collection") == list_key
            and item.get("prompt_link") == link_key
        ]
        if len(specs) != 1:
            raise AuthoringError("prompt scene owner is missing or ambiguous")
        spec = specs[0]
        try:
            domain.validate_prompt_tags(text, spec)
            basis = domain.prompt_basis(state, spec)
        except domain.DomainValidationError as error:
            raise AuthoringError(str(error)) from error
        group = [
            item
            for item in items
            if isinstance(item, dict) and item.get("prompt_id") == group_prompt_id
        ]

        if not group:
            new_version = domain.start_prompt_version(
                group_prompt_id, text, reason, _AUTHOR, scene_id=scene_id, basis=basis
            )
            items.append(new_version)
            version_id = new_version["version_id"]
        else:
            current = resolve_current_group_member(group, links.get(link_key))
            require_owning_scene_matches(current, scene_id, f"prompt_id {group_prompt_id!r}")
            new_version = domain.append_prompt_version(
                state, current, text, reason, _AUTHOR,
                list_key=list_key, link_key=link_key, basis=basis,
            )
            version_id = new_version["version_id"]

        links[link_key] = version_id
        domain.append_history(
            state,
            "agent",
            "prompt-ready",
            _PROMPT_HISTORY_STAGE[kind],
            target_id=group_prompt_id,
        )
        return group_prompt_id, version_id

    (returned_prompt_id, version_id), new_state = mutate(
        store, project_id, expected_revision, mutator
    )
    return {
        "project_id": project_id,
        "prompt_id": returned_prompt_id,
        "version_id": version_id,
        "revision": new_state["revision"],
    }


def edit_scene_block(
    store: ProjectStore,
    project_id: str,
    expected_revision: int,
    *,
    scene_id: str,
    text: str | None = None,
    reason: str | None = None,
    field: str | None = None,
    value=None,
) -> dict:
    """Chat's own door onto a scene block's `edit` (ticket 15 repair,
    поправка оркестратора 1) -- the CLI's `scene edit <workspace>
    <project> <scene_id> --expected-revision N --text TEXT --reason
    TEXT`.

    Gated by the exact same `decision_stages.ensure_action_allowed(state,
    "edit")` the dashboard's `edit` action runs through `decision_
    planners.plan_mutation` -- not a second, hand-rolled stage check --
    so the two doors can never allow this at a different set of stages.
    Today that means `scenario` (after a reopen -- the one thing a
    reopen exists to let someone do, spec §7) and `image_plan`
    (`domain._STAGE_ACTIONS`); `edit` is not listed anywhere else, so
    this refuses everywhere else too, the same as the dashboard's own
    `edit` on a scene card would.

    Calls `domain.append_scene_block_version` directly -- the same
    helper `decision_planners.plan_edit` calls once it has determined
    `target_id` names a scene rather than a prompt (this door never has
    that ambiguity: `scene_id` is its own, separate argument, never a
    bare `target_id` that could also mean a prompt group). One new
    block version and -- per that helper's own rule -- `review_linkage`
    on this scene if its own `links` are non-empty. The independent
    scenario text is not changed.
    """

    if field is None:
        field = "text"
        value = text
    elif text is not None:
        raise AuthoringError("scene edit accepts either field/value or legacy text, not both")
    if field == "text":
        non_empty_text(value, "value")
    if reason is None:
        reason = "правка в чате"
    non_empty_text(reason, "reason")
    safe_id(scene_id, "scene_id")

    def mutator(state):
        decision_stages.ensure_action_allowed(state, "edit")
        try:
            return domain.edit_scene_field(
                state, scene_id, field, value, reason, _AUTHOR
            )
        except domain.DomainValidationError as error:
            raise AuthoringError(str(error)) from error

    outcome, new_state = mutate(store, project_id, expected_revision, mutator)
    result = {
        "project_id": project_id,
        "scene_id": scene_id,
        "field": field,
        "revision": new_state["revision"],
    }
    if "version_id" in outcome:
        result["version_id"] = outcome["version_id"]
    return result

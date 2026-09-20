"""One planner per decision action type, dispatched by `plan_mutation`.

Every planner returns a `mutate(state)` callable that `DecisionWorker.
_apply` (`studio/decisions.py`) runs inside `ProjectStore.transact` --
against the state `transact` just re-read from disk, never a state the
browser observed earlier. For nine of the ten `DECISION_ACTION_TYPES`,
`plan_mutation` wraps whichever planner `action["action_type"]` selects
with the two checks every one of those needs regardless of its own shape:
`decision_stages.ensure_action_allowed` first, `decision_stages.
apply_project_status` last (see that module for why both run
unconditionally, not only for milestone decisions).

`plan_reorder` lives in its own sibling module, `decision_reorder.py`,
next to the collection registry it alone reads -- the other eight
planners here share no such per-collection registry, so they stay
together in this one module.

`reopen-scenario` (ticket 15, G05) is the tenth type and is not a
planner in `PLANNERS` at all: unlike every other type, it needs the
`ActionLedger` itself (to refuse while another action for the project is
queued/running), which the uniform `planner(target_id, payload) ->
mutate` shape has no room to carry, and it is not always reached through
this module's own generic wrapper -- the CLI/chat door
(`authoring_milestones.reopen_scenario`) never is. `plan_mutation` below
special-cases it to `decision_stages.build_reopen_mutation`, the one
function (ticket 15 repair, поправка 4) both doors call unchanged for
the whole thing: allowed-check, pending-action check, the transition
itself and the status recompute, in one place. See that function's own
docstring.
"""

from __future__ import annotations

from . import decision_stages
from .decision_cards import (
    PROMPT_STAGE,
    PROMPT_COLLECTIONS,
    resolve_prompt_for_edit,
    resolve_stage_card,
    resolve_stage_prompt,
    resolve_stage_result,
)
from .decision_reorder import plan_reorder
from .decision_stages import (
    MILESTONE_TARGETS,
    apply_project_status,
    ensure_action_allowed,
    plan_milestone,
)
from .decision_support import DecisionError, append_decision, extract_comment
from .domain import (
    DomainValidationError,
    add_reference,
    append_history,
    append_prompt_version,
    append_script_version,
    add_scene,
    derive_view_stage,
    edit_reference,
    edit_scene_field,
    prompt_basis,
    set_gen_mode,
    set_scene_frame_plan,
    set_video_mode,
    toggle_scene_reference,
    validate_prompt_tags,
)


_DECISION_AUTHOR = "dashboard"


def plan_approve_scenario(_target_id, payload):
    return plan_milestone("scenario", True, payload)


def plan_approve(target_id, payload):
    if target_id in MILESTONE_TARGETS:
        return plan_milestone(target_id, True, payload)
    return _plan_card_decision(target_id, "approved", payload)


def plan_reject(target_id, payload):
    if target_id in MILESTONE_TARGETS:
        return plan_milestone(target_id, False, payload)
    return _plan_card_decision(target_id, "rejected", payload)


def _plan_card_decision(target_id, decision_value, payload):
    """`approve`/`reject` on a prompt or a result card -- resolved through
    whichever of `resolve_stage_prompt`/`resolve_stage_result` the
    project's current stage owns (a prompt only at `image_plan`, a result
    only at `image_results`/`motion`)."""

    comment = extract_comment(payload)

    def mutate(state):
        stage = derive_view_stage(state)["current_stage"]
        collection, target = resolve_stage_card(state, target_id, payload)
        if collection in PROMPT_COLLECTIONS:
            target["status"] = decision_value
        else:
            target["decision"] = decision_value
        append_decision(target, decision_value, comment)
        append_history(
            state,
            "you",
            "accepted" if decision_value == "approved" else "rejected",
            stage,
            **({"target_id": target_id} if decision_value == "approved" else {}),
        )

    return mutate


def _plan_visibility(target_id, hidden, payload):
    def mutate(state):
        stage = derive_view_stage(state)["current_stage"]
        target = resolve_stage_result(state, target_id, payload)
        target["hidden"] = hidden
        append_history(state, "you", "hidden" if hidden else "unhidden", stage)

    return mutate


def plan_hide(target_id, payload):
    return _plan_visibility(target_id, True, payload)


def plan_unhide(target_id, payload):
    return _plan_visibility(target_id, False, payload)


def _plan_retirement(target_id, retired, payload):
    def mutate(state):
        stage = derive_view_stage(state)["current_stage"]
        target = resolve_stage_result(state, target_id, payload)
        # `retired` and `decision` are orthogonal: this never reads or
        # writes `decision`/`decisions` in either direction.
        target["retired"] = retired
        append_history(state, "you", "retired" if retired else "restored", stage)

    return mutate


def plan_retire(target_id, payload):
    return _plan_retirement(target_id, True, payload)


def plan_restore(target_id, payload):
    return _plan_retirement(target_id, False, payload)


def plan_edit(target_id, payload):
    """`edit` on a scene block (`target_id` = `scene_id`) or a prompt.

    A scene is looked up directly (its own id is always unique, never a
    version group); a prompt goes through `resolve_stage_prompt`, so an
    edit at any stage but `image_plan` refuses the same way approve/reject
    already do -- `ensure_action_allowed` also refuses `edit` itself
    outside `image_plan`, but the collection-level check applies the same
    rule every other card action uses, not a second one.

    Scenario prose and scene descriptions are independent (D01), so
    neither branch needs a scenario-to-scene synchronization guard.
    """

    if not isinstance(payload, dict):
        raise DecisionError("edit payload must be an object")

    def mutate(state):
        stage = derive_view_stage(state)["current_stage"]
        reason = payload.get("reason", "правка в дашборде")
        if not isinstance(reason, str) or not reason.strip():
            raise DecisionError("edit payload.reason must be a non-empty string")
        if target_id == "scenario":
            text = payload.get("text")
            if stage != "scenario" or not isinstance(text, str) or not text.strip():
                raise DecisionError("scenario edit requires non-empty payload.text at scenario")
            append_script_version(state, text, reason, _DECISION_AUTHOR)
            append_history(state, "you", "scenario-edited", "scenario")
            return
        scenes = state.get("scenes")
        is_scene = isinstance(scenes, list) and any(
            isinstance(scene, dict) and scene.get("scene_id") == target_id
            for scene in scenes
        )
        if is_scene:
            if stage != "scenario":
                raise DecisionError("scene fields can only be edited at the scenario stage")
            field = payload.get("field", "text")
            value = payload.get("value") if "field" in payload else payload.get("text")
            try:
                edit_scene_field(state, target_id, field, value, reason, _DECISION_AUTHOR)
            except DomainValidationError as error:
                raise DecisionError(str(error)) from error
            return
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise DecisionError("edit payload.text must be a non-empty string")
        collection, prompt = resolve_prompt_for_edit(state, target_id, payload)
        from .domain_positions import current_prompt_spec
        try:
            spec = current_prompt_spec(state, collection, prompt)
            validate_prompt_tags(text, spec)
            basis = prompt_basis(state, spec)
        except DomainValidationError as error:
            raise DecisionError(str(error)) from error
        link_key = {"image_prompts": "image_prompt_version_id", "motion_prompts": "motion_prompt_version_id",
                    "audio_prompts": "audio_prompt_version_id"}[collection]
        append_prompt_version(state, prompt, text, reason, _DECISION_AUTHOR,
                              list_key=collection, link_key=link_key, basis=basis)
        append_history(state, "you", "prompt-edited", stage, target_id=target_id)

    return mutate


def plan_scene_add(target_id, payload):
    if target_id != "scenes" or payload not in ({}, None):
        raise DecisionError("scene-add requires target 'scenes' and an empty payload")

    def mutate(state):
        try:
            add_scene(state, _DECISION_AUTHOR)
        except DomainValidationError as error:
            raise DecisionError(str(error)) from error

    return mutate


def plan_reference_add(target_id, payload):
    if target_id != "references" or not isinstance(payload, dict):
        raise DecisionError("reference-add requires target 'references' and an object payload")
    if set(payload) - {"kind", "name", "source", "scene_id"} or "kind" not in payload:
        raise DecisionError("reference-add payload has unsupported or missing fields")
    if "scene_id" in payload and (not isinstance(payload["scene_id"], str) or not payload["scene_id"]):
        raise DecisionError("scene_id must name an existing scene")

    def mutate(state):
        try:
            add_reference(
                state,
                kind=payload["kind"],
                name=payload.get("name"),
                source=payload.get("source", "upload"),
                scene_id=payload.get("scene_id"),
            )
        except DomainValidationError as error:
            raise DecisionError(str(error)) from error

    return mutate


def plan_reference_edit(target_id, payload):
    if not isinstance(payload, dict) or set(payload) != {"field", "value"}:
        raise DecisionError("reference-edit payload must contain field and value")

    def mutate(state):
        try:
            edit_reference(state, target_id, payload["field"], payload["value"])
        except DomainValidationError as error:
            raise DecisionError(str(error)) from error

    return mutate


def plan_scene_reference_toggle(target_id, payload):
    if not isinstance(payload, dict) or set(payload) != {"scene_id", "on"}:
        raise DecisionError("scene-reference-toggle payload must contain scene_id and on")

    def mutate(state):
        try:
            toggle_scene_reference(state, payload["scene_id"], target_id, payload["on"])
        except DomainValidationError as error:
            raise DecisionError(str(error)) from error

    return mutate


def plan_scene_frame_plan(target_id, payload):
    if (
        not isinstance(payload, dict)
        or not payload
        or set(payload) - {"first", "last"}
        or not all(isinstance(value, bool) for value in payload.values())
    ):
        raise DecisionError("scene-frame-plan payload must contain first and/or last booleans")

    def mutate(state):
        try:
            set_scene_frame_plan(state, target_id, first=payload.get("first"), last=payload.get("last"))
        except DomainValidationError as error:
            raise DecisionError(str(error)) from error

    return mutate


def plan_set_gen_mode(target_id, payload):
    if target_id != "project" or not isinstance(payload, dict) or set(payload) != {"mode"}:
        raise DecisionError("set-gen-mode requires target project and payload.mode")

    def mutate(state):
        try:
            set_gen_mode(state, payload["mode"])
        except DomainValidationError as error:
            raise DecisionError(str(error)) from error

    return mutate


def plan_set_video_mode(target_id, payload):
    if not isinstance(payload, dict) or set(payload) != {"mode"}:
        raise DecisionError("set-video-mode payload must contain mode")

    def mutate(state):
        try:
            from .stage_readiness import require_accepted_frames
            require_accepted_frames(state, target_id, payload["mode"])
            set_video_mode(state, target_id, payload["mode"])
        except DomainValidationError as error:
            raise DecisionError(str(error)) from error

    return mutate


def plan_set_mode(target_id, payload):
    if target_id != "project" or not isinstance(payload, dict) or set(payload) != {"mode"}:
        raise DecisionError("set-mode requires project target and mode payload")
    mode = payload["mode"]
    if not isinstance(mode, str) or mode not in {"guided", "autopilot"}:
        raise DecisionError("mode must be guided or autopilot")

    def mutate(state):
        state["project"]["mode"] = mode
        append_history(state, "you", "mode-set", derive_view_stage(state)["current_stage"], mode=mode)

    return mutate


PLANNERS = {
    "set-mode": plan_set_mode,
    "approve-scenario": plan_approve_scenario,
    "approve": plan_approve,
    "reject": plan_reject,
    "edit": plan_edit,
    "hide": plan_hide,
    "unhide": plan_unhide,
    "retire": plan_retire,
    "restore": plan_restore,
    "reorder": plan_reorder,
    "scene-add": plan_scene_add,
    "reference-add": plan_reference_add,
    "reference-edit": plan_reference_edit,
    "scene-reference-toggle": plan_scene_reference_toggle,
    "scene-frame-plan": plan_scene_frame_plan,
    "set-gen-mode": plan_set_gen_mode,
    "set-video-mode": plan_set_video_mode,
}

# The one decision type `PLANNERS` deliberately does not cover -- see the
# module docstring for why `reopen-scenario` cannot share the uniform
# `planner(target_id, payload) -> mutate` shape every entry above has.
# `decisions.DECISION_ACTION_TYPES`'s own completeness check (`studio/
# decisions.py`) reads this alongside `PLANNERS` rather than expecting the
# type to appear in `PLANNERS` itself, so a real gap (a decision type
# nobody builds a mutation for at all) still fails loudly at import time.
#
# `_REOPEN_ACTION_TYPE` is the *only* place this literal is spelled out
# (ticket 15 repair, поправка оркестратора 13: "особый тип мутации назван
# в одном месте") -- `plan_mutation`'s own dispatch below compares against
# this name, not a second `"reopen-scenario"` string of its own that could
# quietly drift from the frozenset here.
_REOPEN_ACTION_TYPE = "reopen-scenario"
_DEDICATED_MUTATION_TYPES = frozenset({_REOPEN_ACTION_TYPE})


def plan_mutation(action: dict, ledger=None):
    """Build the one `mutate(state)` callable `DecisionWorker._apply` runs
    for `action`.

    `reopen-scenario` is special-cased first, to `decision_stages.
    build_reopen_mutation` -- the one function both reopen doors share
    (see the module docstring) -- rather than through `PLANNERS` and this
    function's own generic wrapping below, since that wrapping assumes
    every planner needs only `(target_id, payload)`, and building a
    reopen's mutation needs `ledger`/`project_id` too. `ledger` is
    accepted here, not required, for every *other* action type's sake --
    nothing in this build passes anything but `decisions.py`, and no
    change is needed there -- but a `reopen-scenario` action with no
    `ledger` supplied is a caller bug, not a legitimate "no ledger
    needed" case: `decision_stages.build_reopen_mutation`'s own
    `mutate(state)` reads it unconditionally
    (`ensure_no_pending_actions`), so a missing one would otherwise
    surface only once that `mutate` actually runs, as an opaque
    `AttributeError` from deep inside `ProjectStore.transact` --
    indistinguishable, to `DecisionWorker._apply`'s own broad `except
    Exception`, from a legitimate business-rule refusal. Ticket 15
    repair, поправка оркестратора 13: "ledger обязателен там, где его
    читают" -- required eagerly, here, before any transaction begins,
    with a `TypeError` (a caller-usage mistake, not a `DecisionError`
    refusal) that names exactly what is missing.

    Every other type is wrapped with the two checks every one of them
    needs: `ensure_action_allowed` first (against the state `transact`
    just re-read, not one the browser observed earlier), `apply_project_
    status` last -- unconditionally, since a decision on one stage can be
    what moves `current_stage` into `assembly`, and `project.status`
    must reflect that regardless of which stage's own decision caused it.
    """

    if action["action_type"] == _REOPEN_ACTION_TYPE:
        if ledger is None:
            raise TypeError(
                f"plan_mutation requires ledger for {_REOPEN_ACTION_TYPE!r}"
            )
        return decision_stages.build_reopen_mutation(
            ledger,
            action["project_id"],
            action["payload"],
            exclude_action_id=action.get("action_id"),
        )

    planner = PLANNERS.get(action["action_type"])
    if planner is None:  # pragma: no cover - claim_next already filters this
        raise DecisionError(f"unsupported decision action_type: {action['action_type']!r}")
    inner_mutate = planner(action["target_id"], action["payload"])

    def mutate(state):
        ensure_action_allowed(state, action["action_type"])
        if ledger is not None and action["action_type"] == "approve" and action["target_id"] in MILESTONE_TARGETS:
            from .stage_readiness import stage_readiness
            readiness = stage_readiness({**state, "actions": ledger.pending_actions(
                action["project_id"], exclude_action_id=action.get("action_id"))})
            if not readiness["can_approve"]:
                raise DecisionError(readiness["reason"])
        inner_mutate(state)
        apply_project_status(state)

    return mutate

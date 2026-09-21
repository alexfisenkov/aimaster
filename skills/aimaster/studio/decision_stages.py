"""Stage/milestone rules: what a decision may touch now, and what it means
for the project's own coarse status afterward.

Every decision-type mutation is gated the same way, in two steps, both run
against the state `ProjectStore.transact` just re-read from disk -- the
canonical `derive_view_stage`, never a state the browser observed earlier:

1. `ensure_action_allowed` refuses an `action_type` the current stage does
   not list at all. Most of `ledger.ACTION_TYPES` are valid at more than
   one stage, so this alone cannot tell "approve the audio milestone" apart
   from "approve a card at image_results" -- it only rules out stages that
   do not offer the type at all (`edit` outside `image_plan`, or anything
   but `continue-in-chat` while a question blocks the project).
2. `plan_milestone` (for `approve-scenario`, and for `approve`/`reject`
   naming a milestone as their `target_id`) additionally refuses unless
   that milestone is genuinely the project's current stage right now --
   `"approve"` alone does not say *which* milestone, so this is the check
   that actually pins one to the stage it names.

One planner, `plan_milestone`, covers every milestone of either stage
sequence (six for a video, four for a photo) -- `scenario` included,
reached through the dedicated `approve-scenario` action type
rather than through `approve`/`target_id="scenario"`
(`decision_planners.plan_approve_scenario` calls it directly). Every
milestone's decision history lands in the same place, `state[
"stage_decisions"]`, in the same `{"stage", "decision", "comment"}` shape
-- the one form `projection.py` projects into the browser snapshot for a
stage the project has actually reached (see that module).

`build_reopen_mutation` (ticket 15, G05) is not a planner in that same
two-step sense -- it is reached by *two* doors, only one of which
(`decision_planners.plan_mutation`, for the dashboard) runs the usual
`ensure_action_allowed`/`apply_project_status` wrapping around it, so it
folds both of those, plus the ledger-backed "nothing queued/running for
this project" gate no other decision needs, into itself. See its own
docstring for the full, ordered list.
"""

from __future__ import annotations

from .decision_support import DecisionError, extract_comment
from .domain import (
    PHOTO_STAGES,
    VIDEO_STAGES,
    append_history,
    _stage_sequence,
    derive_project_status,
    derive_view_stage,
    require_storyboard_complete,
    DomainValidationError,
)


# Every stage a whole-milestone decision (`approve`/`reject` naming the
# stage itself as `target_id`) can target -- `scenario` is excluded
# because it is reached only through the dedicated `approve-scenario`
# action type, used by `decision_planners.plan_approve`/`plan_reject` to
# tell a milestone-shaped `target_id` apart from a card id.
#
# Derived from the two stage tuples, not a literal of its own: a stage
# added to (or dropped from) a sequence -- `audio` arriving, `qa` leaving --
# changes what can be approved in the same edit, and no second list can
# name a stage the sequences no longer have.
MILESTONE_TARGETS = frozenset(VIDEO_STAGES + PHOTO_STAGES) - {"scenario"}


def ensure_action_allowed(state: dict, action_type: str) -> None:
    """Refuse an `action_type` the current canonical state does not list."""

    view = derive_view_stage(state)
    if action_type not in view["allowed_actions"]:
        raise DecisionError(
            f"action_type {action_type!r} is not allowed at stage "
            f"{view['current_stage']!r} (gate_status={view['gate_status']!r})"
        )


def plan_milestone(stage: str, is_approve: bool, payload):
    """`approve-scenario`, and `approve`/`reject` naming a milestone stage.

    One rule for all six milestones: the named stage must be the
    project's current stage right now, its status becomes
    `approved`/`draft`, and `{"stage", "decision", "comment"}` is appended
    to the shared `state["stage_decisions"]` history. A milestone key
    absent from `state["milestones"]` reads as `"draft"`, matching
    `derive_view_stage` -- the first decision for a stage is what first
    creates its key.

    Ticket 08 repair to remedy 1, condition 14: an *approve* additionally
    refuses once `stage` already reads `approved`. This only ever bites
    on `sequence[-1]` (`assembly` -- see `domain.derive_view_stage`): every
    earlier milestone leaves `current_stage` the moment it is approved,
    so `view["current_stage"] != stage` above already refuses a second
    approval on its own there. `assembly` is `derive_view_stage`'s one
    stage that *stays* `current_stage` forever once reached, approved or
    not, so without this a finished project kept accepting a second
    `approve target_id="assembly"` and silently appended a second
    `"approved"` entry to `stage_decisions` for a project that was
    already `done`. A *reject* is unaffected on purpose -- rejecting a
    `done` project back to `review` is the path task 11 already relies
    on (`decision_stages.apply_project_status`), and stays available
    after `assembly` is approved.

    Scenario prose and scene descriptions are independent (D01), so
    milestone approval has no scenario-to-scene synchronization gate.
    """

    comment = extract_comment(payload)
    decision_value = "approved" if is_approve else "rejected"
    new_status = "approved" if is_approve else "draft"

    def mutate(state):
        view = derive_view_stage(state)
        if view["current_stage"] != stage:
            raise DecisionError(
                f"{stage} is not the current stage (current: {view['current_stage']!r})"
            )
        if is_approve and view["gate_status"] == "approved":
            raise DecisionError(f"{stage} is already approved")
        if is_approve:
            from .stage_readiness import stage_readiness
            readiness = stage_readiness(state)
            if not readiness["can_approve"]:
                raise DecisionError(readiness["reason"])
        milestones = state.get("milestones")
        if not isinstance(milestones, dict):
            raise DecisionError("milestones must be an object")
        milestones[stage] = new_status
        history = state.setdefault("stage_decisions", [])
        if not isinstance(history, list):
            raise DecisionError("stage_decisions must be a list")
        history.append({"stage": stage, "decision": decision_value, "comment": comment})
        append_history(
            state,
            "you",
            "stage-approved" if is_approve else "stage-rework",
            stage,
        )

    return mutate


def apply_project_status(state: dict) -> None:
    """Recompute `project.status` from milestones/current stage alone
    (spec §18.13 п. 3, `domain.derive_project_status`).

    `done` once `assembly` is approved; `review` while `assembly` is the
    current stage and not approved (`assembly` never leaves `current_stage`
    once reached, so `gate_status` is what actually tells the two apart);
    `active` otherwise. Idempotent and cheap, so
    `decision_planners.plan_mutation` runs it after every decision, not
    only a milestone one: a decision on an *earlier* stage can still be
    what moves `current_stage` into `assembly`, and rejecting `assembly`
    after the project was `done` must return it to `review`.
    """

    project = state.get("project")
    if not isinstance(project, dict):
        raise DecisionError("project must be an object")
    project["status"] = derive_project_status(derive_view_stage(state))


def build_reopen_mutation(ledger, project_id: str, payload, *, exclude_action_id=None):
    """`reopen-scenario`'s entire transition (ticket 15, G05: owner's
    answer 17.09.2026 -- "да можно и даже нужно возвращаться что бы
    править сценарий"). The one function ticket 15's repair (поправка
    оркестратора 4, "одно правило и одна функция") asks for: both reopen
    doors call this, unchanged, to get their `mutate(state)` --
    `decision_planners.plan_mutation` for the dashboard's `POST
    /api/actions` -> ledger -> `DecisionWorker` path, `authoring_
    milestones.reopen_scenario` for the CLI's `scenario reopen` (chat's
    door). Neither door hand-rolls any part of this itself any more (the
    craft review's own finding: a hand-rolled "scenario approved and not
    blocked" check here used to duplicate, and could silently drift from,
    `domain._STAGE_ACTIONS` -- gone now, replaced by the one real gate
    every other action already goes through).

    Returns a `mutate(state)` callable meant to run exactly once, inside
    `ProjectStore.transact` (both callers already run it there) -- in
    order:

    1. `ensure_action_allowed(state, "reopen-scenario")` -- the same
       `allowed_actions` `derive_view_stage` computes for every other
       action, never a second, hand-rolled rule. Refuses
       (`decision_stages.DecisionError`, a `ValueError`) at the
       `scenario` stage itself (ticket 15's own acceptance criterion:
       "на стадии scenario ... reopen-scenario не разрешён" --
       `_STAGE_ACTIONS["scenario"]` never lists it) and while the
       project is `blocked` (spec §7: a reopen must not silently answer
       or discard a pending question -- `blocked` replaces the whole
       `allowed_actions` list with `["continue-in-chat"]`). Places no
       other requirement on `current_stage`: a finished project's
       `assembly` stays `current_stage` forever once approved
       (`plan_milestone`'s own docstring), and G05 explicitly allows
       reopening from there too ("завершённые видео- и фотопроекты").
    2. `ensure_no_pending_actions(ledger, project_id, exclude_action_id=
       exclude_action_id)` -- a *fresh* read, run here rather than only
       once earlier by the caller, because this is the point that
       actually runs while `ProjectStore.transact` holds the project's
       own file lock (see that method's own docstring: the mutation
       callback runs between the lock being taken and the write landing
       on disk). Ticket 15's craft review demonstrated the single-check,
       checked-before-`store.transact` version losing this exact race: a
       `vary`/`regenerate` enqueue that starts after an early check
       passes can still fully commit (through `ledger.enqueue`'s own
       before/after revision re-check) before this transition's write
       ever lands, leaving a paid action queued for a stage this reopen
       is about to hide. Running the check here instead means any such
       enqueue that has *actually committed* by the time this line runs
       -- including one that landed in the gap between an earlier,
       now-redundant check and this one -- is caught, and the whole
       mutation aborts (`ProjectStore.transact` writes nothing once its
       mutation callback raises): the reopen itself is refused rather
       than silently coexisting with a paid action now queued for a
       stage about to disappear.
    3. Demotes `milestones["scenario"]`, and every milestone after it
       (`domain._stage_sequence(state)` -- the one place project type
       picks `PHOTO_STAGES`/`VIDEO_STAGES`, not a second, hand-rolled
       copy of that choice here), back to `draft`.
    4. Appends `{"stage": "scenario", "decision": "reopened", "comment"}`
       to the shared `state["stage_decisions"]` history
       (`projection._STAGE_DECISION_VALUES` allows "reopened" there, and
       `projection._sanitize_stage_decision` allows it only paired with
       `stage == "scenario"` -- never on a prompt's/result's own
       card-level `decisions[]`, and never on any other stage's own
       history entry).
    5. `apply_project_status(state)` -- the same recompute every other
       decision runs after its own mutation. Folded in here explicitly,
       unlike `plan_milestone`'s transition (which relies on `decision_
       planners.plan_mutation`'s own generic wrapper to run it
       afterward): `reopen-scenario` is not reached through that generic
       wrapper any more (see `decision_planners.plan_mutation`), and the
       CLI/chat door never was, so this step must be self-sufficient for
       both callers rather than assuming a wrapper neither can rely on.

    Scenes, prompts, results, references, assembly, their versions and
    every card decision are untouched, except that scene-local
    `continuity_strategy` choices are cleared because a reopened scenario can
    change which scene precedes which. Otherwise only `milestones`,
    `stage_decisions` and (via step 5) `project.status` change here.
    A milestone key the current sequences do not name (`qa`, written by a
    project file of the old stage model) is not touched either: nothing
    reads it any more.
    """

    comment = extract_comment(payload)

    def mutate(state):
        ensure_action_allowed(state, "reopen-scenario")
        ensure_no_pending_actions(ledger, project_id, exclude_action_id=exclude_action_id)
        milestones = state.get("milestones")
        if not isinstance(milestones, dict):
            raise DecisionError("milestones must be an object")
        for stage in _stage_sequence(state):
            milestones[stage] = "draft"
        for scene in state.get("scenes", []):
            if isinstance(scene, dict):
                for key in (
                    "continuity_strategy",
                    "continuity_previous_scene_id",
                    "continuity_source_result_id",
                    "continuity_first_frame_result_id",
                ):
                    scene.pop(key, None)
        history = state.setdefault("stage_decisions", [])
        if not isinstance(history, list):
            raise DecisionError("stage_decisions must be a list")
        history.append({"stage": "scenario", "decision": "reopened", "comment": comment})
        append_history(state, "you", "scenario-reopened", "scenario")
        apply_project_status(state)

    return mutate


def ensure_no_pending_actions(ledger, project_id: str, *, exclude_action_id=None) -> None:
    """Refuse `reopen-scenario` while `project_id` has another action
    `queued`/`running` (ticket 15, G05 -- "Пока у проекта есть действие
    queued или running (кроме самого возврата), возврат отклоняется").

    The one caller is `build_reopen_mutation` above, which runs this as
    the first thing its returned `mutate(state)` does -- itself always
    run inside `ProjectStore.transact`, i.e. *while* the project's own
    file lock is held (see that function's own docstring, step 2, for
    why the timing matters). `exclude_action_id` is the reopen action's
    own id for the dashboard door (already `running` by the time
    `claim_next` handed it over -- excluded so the check does not refuse
    itself); the CLI/chat door never creates a ledger row of its own, so
    it passes nothing to exclude. `ActionLedger.has_pending_actions` is a
    single, un-transacted `SELECT` -- cheap enough to run while that file
    lock is held, and always a *fresh* read, never a value cached from
    before the lock was taken.
    """

    if ledger.has_pending_actions(project_id, exclude_action_id=exclude_action_id):
        raise DecisionError(
            "reopen-scenario is refused while another action for this "
            "project is queued or running"
        )

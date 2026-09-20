"""Chat-authored `ready`/`blocked` milestone status, and the chat door
onto G05's scenario-reopen transition.

Ticket 12 repair, condition 15: one of six `authoring_*` responsibility
modules split out of the former monolithic `authoring.py` -- this one owns
`milestone set`. See `authoring_support.py`'s module docstring for the
split's rationale.

Ticket 15 (G05): this is also the file the ticket names for chat's own
door onto `reopen-scenario` ("модуль записи вех из чата (authoring_
milestones.py или рядом)") -- `reopen_scenario` below, the CLI's
`scenario reopen`. It belongs next to `set_milestone` because both are
chat-authored writes to `state["milestones"]`; unlike `set_milestone`
(which only ever writes `ready`/`blocked`, never `approved`),
`reopen_scenario` needs the durable `ActionLedger` too -- to refuse while
another action for the project is still `queued`/`running` -- so this
module gains that one new dependency alongside the usual `ProjectStore`.
"""

from __future__ import annotations

from . import decision_stages, domain
from .authoring_support import AuthoringError, mutate, optional_bounded_text
from .ledger import ActionLedger
from .store import ProjectStore


_MILESTONE_SETTABLE_STATUSES = frozenset({"ready", "blocked"})


def set_milestone(
    store: ProjectStore, project_id: str, expected_revision: int, stage: str, status: str
) -> dict:
    """Mark the current stage `ready` or `blocked` -- never `approved`.

    Approval is exclusively a dashboard decision (`approve-scenario`/
    `approve`, applied by `decisions.DecisionWorker`); this only sets the
    two statuses that decision path leaves alone. Refuses a `stage` that
    is not genuinely the project's current stage right now, the same
    safety check `decision_stages.plan_milestone` applies to a dashboard
    milestone decision.

    Also refuses outright if that milestone is already `approved`
    (ticket 12 repair, blocking condition 7): for every stage but the
    sequence's last one, `derive_view_stage` already moves
    `current_stage` past an approved milestone, so `stage != current_stage`
    alone would already catch it there -- but the *last* stage
    (`assembly`, in both `VIDEO_STAGES` and `PHOTO_STAGES`) stays
    `current_stage` even once approved (there is nowhere further to
    move), so without this explicit check `milestone set assembly
    ready|blocked` could silently revoke the dashboard's own approval of
    the final deliverable.
    """

    if status not in _MILESTONE_SETTABLE_STATUSES:
        raise AuthoringError("milestone status must be ready or blocked")

    def mutator(state):
        view = domain.derive_view_stage(state)
        if stage != view["current_stage"]:
            raise AuthoringError(
                f"{stage!r} is not the current stage (current: {view['current_stage']!r})"
            )
        milestones = state.get("milestones")
        if not isinstance(milestones, dict):
            raise AuthoringError("milestones must be an object")
        if milestones.get(stage, "draft") == "approved":
            raise AuthoringError(
                f"{stage!r} is already approved by the dashboard; "
                "milestone set cannot revoke it"
            )
        milestones[stage] = status
        domain.append_history(
            state,
            "agent",
            "stage-ready" if status == "ready" else "stage-blocked",
            stage,
        )

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {
        "project_id": project_id,
        "stage": stage,
        "status": status,
        "revision": new_state["revision"],
    }


def reopen_scenario(
    store: ProjectStore,
    ledger: ActionLedger,
    project_id: str,
    expected_revision: int,
    *,
    comment: str | None = None,
) -> dict:
    """Chat's own door onto G05's reopen transition (ticket 15) -- the
    CLI's `scenario reopen <workspace> <project> --expected-revision N
    [--comment TEXT]`.

    Calls `decision_stages.build_reopen_mutation` -- the one function
    (ticket 15 repair, поправка 4) both reopen doors share unchanged --
    to get its `mutate(state)`, then runs that inside `store.transact`
    exactly like every other chat-authored write in this package (see
    `authoring_support.mutate`). This function adds nothing to *what* the
    transition does or *when* it refuses; see `build_reopen_mutation`'s
    own docstring for the full, ordered list, including *why* its
    ledger-pending check runs from inside that `mutate(state)` rather
    than only once, earlier, here.

    `comment` is bounded the same way every other optional chat-authored
    free-text field in this package is (`authoring_support.
    optional_bounded_text`) -- the dashboard's own `POST /api/actions`
    has no equivalent bound beyond its 64 KiB request body, but a CLI
    `--comment` has no such intrinsic limit of its own. No
    `exclude_action_id`: this door never creates a ledger row of its own
    for chat to exclude.
    """

    comment = optional_bounded_text(comment, "comment")
    payload = {"comment": comment} if comment is not None else {}
    mutator = decision_stages.build_reopen_mutation(ledger, project_id, payload)

    _, new_state = mutate(store, project_id, expected_revision, mutator)
    return {"project_id": project_id, "revision": new_state["revision"]}

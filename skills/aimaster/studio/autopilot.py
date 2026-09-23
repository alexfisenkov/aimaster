"""Autopilot spending policy: a paid action in an `autopilot` project
authorizes itself.

Spec 2026-09-23 §2 (owner decision: spend without confirmation and without
a limit). `ActionLedger.enqueue` consults this policy only when a
`GRANT_REQUIRED_ACTIONS` member finds no free chat-issued grant. In a
`guided` project nothing changes: the action lands in `needs_chat` exactly
as before.

The history fact is written through `ProjectStore.transact` while the
ledger's own SQLite transaction is still open, so a refused history write
(a concurrent revision change, the mode switched back to `guided`) rolls
the self-issued grant and the action back together.
"""

from __future__ import annotations

from .domain import DomainValidationError, _stage_sequence, append_history, derive_view_stage
from .store import ProjectStore

AUTOPILOT_NOTICE = "Автопилот тратит кредиты без подтверждения"
AUTOPILOT_ISSUER = "autopilot"
AUTOPILOT_HISTORY_KIND = "autopilot-grant"


class AutopilotModeChanged(RuntimeError):
    """The project left autopilot between the mode read and the history write."""


def _history_stage(state, action_type, target_id):
    # Local import: projection imports domain/runner_context helpers that
    # import this package's other modules; keep this module import-light.
    from .projection import ActionTargetError, ProjectionError, action_target_stage

    sequence = _stage_sequence(state)
    try:
        stage = action_target_stage(state, action_type, target_id, sequence)
    except (ActionTargetError, ProjectionError, DomainValidationError):
        stage = None
    if stage in sequence:
        return stage
    return derive_view_stage(state)["current_stage"]


def autopilot_grant_still_valid(ledger, action, state) -> bool:
    """False when `action` rides a self-issued autopilot grant but the
    project is no longer in autopilot (checked at claim time)."""

    grant_id = action.get("grant_id")
    if not grant_id or ledger.grant_issuer(grant_id) != AUTOPILOT_ISSUER:
        return True
    project = state.get("project")
    return isinstance(project, dict) and project.get("mode") == "autopilot"


def stop_autopilot_spending(ledger, project_id, mode) -> list[str]:
    """After a mode change: leaving autopilot cancels its queued paid actions."""

    if mode == "autopilot" or ledger is None:
        return []
    return ledger.cancel_autopilot_queued(project_id)


class StoreAutopilotPolicy:
    """Reads the project mode and records `autopilot-grant` in its history."""

    def __init__(self, store: ProjectStore):
        self.store = store

    def is_autopilot(self, project_id) -> bool:
        state = self.store.load(project_id)
        project = state.get("project")
        return isinstance(project, dict) and project.get("mode") == "autopilot"

    def record_grant(self, project_id, expected_revision, action_type, target_id) -> dict:
        def mutation(state):
            project = state.get("project")
            if not isinstance(project, dict) or project.get("mode") != "autopilot":
                raise AutopilotModeChanged("project is no longer in autopilot mode")
            append_history(
                state,
                "agent",
                AUTOPILOT_HISTORY_KIND,
                _history_stage(state, action_type, target_id),
                action=action_type,
                target_id=target_id,
            )

        return self.store.transact(project_id, expected_revision, mutation)

"""Direct chat door for the same local decision planners as the dashboard."""

from __future__ import annotations

from .authoring_support import mutate
from .decision_planners import plan_mutation
from .decision_receipts import append_applied_marker, operation_receipt, receipt_status
from .decision_support import DecisionError
from .domain import DomainValidationError, derive_view_stage
from .domain_positions import current_member, resolve_position
from .store import RevisionConflict


class OperationConflict(DecisionError):
    """An operation id was reused for a different direct request."""


def _resolve_target(state: dict, action_type: str, target_id: str) -> str:
    if not isinstance(target_id, str) or not target_id.startswith("pos:"):
        return target_id
    try:
        spec = resolve_position(state, target_id)
        stage = derive_view_stage(state)["current_stage"]
        side = "prompt" if action_type == "edit" or (
            action_type in {"approve", "reject"} and stage == "image_plan"
        ) else "result"
        member = current_member(state, spec, side)
    except DomainValidationError as error:
        raise DecisionError("position target has no unambiguous current version") from error
    version_id = member.get("version_id") if isinstance(member, dict) else None
    if not isinstance(version_id, str) or not version_id:
        raise DecisionError("position target has no unambiguous current version")
    return version_id


def apply(
    store,
    ledger,
    project_id: str,
    expected_revision: int,
    *,
    action_type: str,
    target_id: str,
    payload: dict,
    operation_id: str | None = None,
) -> dict:
    """Apply one non-provider decision immediately, with optional replay proof."""

    if not isinstance(payload, dict):
        raise DecisionError("payload must be an object")
    operation_hash = receipt = None
    if operation_id is not None:
        operation_hash, receipt = operation_receipt(
            operation_id, action_type, target_id, payload, expected_revision
        )

        existing = receipt_status(store.load(project_id), operation_hash, receipt)
        if existing == "match":
            return {"project_id": project_id, "revision": expected_revision + 1, "replayed": True}
        if existing == "conflict":
            raise OperationConflict("operation_id belongs to a different request")

    def mutator(state):
        if receipt is not None:
            existing = receipt_status(state, operation_hash, receipt)
            if existing == "match":
                raise DecisionError("operation receipt raced with this transaction")
            if existing == "conflict":
                raise OperationConflict("operation_id belongs to a different request")
        action = {
            "project_id": project_id,
            "action_type": action_type,
            "target_id": _resolve_target(state, action_type, target_id),
            "payload": payload,
        }
        plan_mutation(action, ledger=ledger)(state)
        if receipt is not None:
            append_applied_marker(state, receipt)

    try:
        _, state = mutate(store, project_id, expected_revision, mutator)
    except RevisionConflict:
        if receipt is None:
            raise
        existing = receipt_status(store.load(project_id), operation_hash, receipt)
        if existing == "match":
            return {"project_id": project_id, "revision": expected_revision + 1, "replayed": True}
        if existing == "conflict":
            raise OperationConflict("operation_id belongs to a different request")
        raise
    return {"project_id": project_id, "revision": state["revision"], "replayed": False}

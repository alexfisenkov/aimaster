"""Private, bounded operation receipts for direct chat decisions."""

from __future__ import annotations

import hashlib
import json

from .decision_support import DecisionError
from .questions import _SAFE_ID


APPLIED_ACTION_IDS_WINDOW = 64
_PREFIX = "op:v1:"


def _markers(state: dict) -> list[str]:
    markers = state.get("applied_action_ids")
    return list(markers) if isinstance(markers, list) else []


def append_applied_marker(state: dict, marker: str) -> None:
    if not isinstance(marker, str) or not marker:
        raise DecisionError("applied action marker must be a non-empty string")
    state["applied_action_ids"] = [*_markers(state), marker][-APPLIED_ACTION_IDS_WINDOW:]


def operation_receipt(operation_id: str, action_type: str, target_id: str, payload: dict, revision: int) -> tuple[str, str]:
    if not isinstance(operation_id, str) or not _SAFE_ID.fullmatch(operation_id):
        raise DecisionError("operation_id must be a safe opaque identifier")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise DecisionError("expected_revision must be a non-negative integer")
    operation_hash = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
    try:
        encoded = json.dumps(
            {
                "action_type": action_type,
                "target_id": target_id,
                "payload": payload,
                "original_revision": revision,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DecisionError("operation request must be JSON-compatible") from error
    request_hash = hashlib.sha256(encoded).hexdigest()
    return operation_hash, f"{_PREFIX}{operation_hash}:{request_hash}"


def receipt_status(state: dict, operation_hash: str, receipt: str) -> str | None:
    matching = [
        item for item in _markers(state)
        if isinstance(item, str) and item.startswith(f"{_PREFIX}{operation_hash}:")
    ]
    if len(matching) > 1:
        raise DecisionError("operation receipt is ambiguous")
    if not matching:
        return None
    return "match" if matching[0] == receipt else "conflict"

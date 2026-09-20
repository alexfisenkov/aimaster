"""Small helpers shared by every decision planner and stage rule.

`DecisionError` is the one exception a planner raises for anything the
current canonical state does not allow: a bad payload, a missing target, a
stage that does not own the collection being addressed. `DecisionWorker.
_apply` (`studio/decisions.py`) catches it the same way as any other
failure and always ends the action `failed`, never `outcome_unknown` --
that status is reserved for a crash between an external call and
recording its result, and a decision never makes one.

`extract_comment`/`append_decision` implement the one append-only shape a
prompt's or a result's own `decisions` history uses,
`{"decision": ..., "comment": ...}`. `decision_stages.plan_milestone` does
not reuse `append_decision` itself: a milestone's history entry carries an
extra `"stage"` key (see that module).
"""

from __future__ import annotations


class DecisionError(ValueError):
    """A decision cannot be applied to the current canonical state."""


def extract_comment(payload) -> str:
    """`payload["comment"]`, defaulting to `""` -- never anything but a string."""

    if not isinstance(payload, dict):
        return ""
    comment = payload.get("comment", "")
    if not isinstance(comment, str):
        raise DecisionError("payload.comment must be a string")
    return comment


def append_decision(entity: dict, decision_value: str, comment: str) -> None:
    """Append `{"decision": ..., "comment": ...}` to `entity["decisions"]`."""

    history = entity.setdefault("decisions", [])
    if not isinstance(history, list):
        raise DecisionError("decisions history must be a list")
    history.append({"decision": decision_value, "comment": comment})

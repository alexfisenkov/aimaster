"""`reorder`'s own planner, kept next to the registry it reads.

Split out of `decision_planners.py` (2026-09-17 repair): `reorder` is the
one decision whose validity depends on a per-collection registry --
`REORDERABLE_COLLECTIONS` below -- rather than a single fixed rule, so that
registry lives here, beside the one planner that reads it, instead of
inside the shared eight-planner module. Both this module and
`decision_cards.py`'s own resolvers read the same
`decision_cards.STAGE_COLLECTIONS`; neither keeps a second copy of which
stage owns which collection.
"""

from __future__ import annotations

from .decision_cards import STAGE_COLLECTIONS, card_identity
from .decision_support import DecisionError
from .domain import append_history, derive_view_stage, recompute_scene_ranges


# The collections `reorder` may address, named outright: a collection is
# reorderable because someone decided so here, never because it happens to
# be a `decision_cards.STAGE_COLLECTIONS` entry (the registry this used to be
# subtracted from made every collection added there reorderable, silently).
# `image_prompts` is not among them -- a versioned prompt group has no
# single order to reorder, only version history. Each collection's own
# state key equals its `target_id`, so no separate name mapping is needed.
REORDERABLE_COLLECTIONS = frozenset({"scenes", "image_results", "video_results"})
_HISTORY_KIND_BY_COLLECTION = {
    "scenes": "scenes-reordered",
    "image_results": "image-results-reordered",
    "video_results": "video-results-reordered",
}

# Loud at import, like `decisions.py`'s own completeness check: `plan_reorder`
# reads `STAGE_COLLECTIONS[target_id]` for every member above.
if not REORDERABLE_COLLECTIONS <= set(STAGE_COLLECTIONS):
    raise RuntimeError(
        "decision_reorder.REORDERABLE_COLLECTIONS must name only "
        "decision_cards.STAGE_COLLECTIONS entries"
    )
if set(_HISTORY_KIND_BY_COLLECTION) != set(REORDERABLE_COLLECTIONS):
    raise RuntimeError("every reorderable collection must have one history kind")


def plan_reorder(target_id, payload):
    """Reorder a whole collection (`scenes`/`image_results`/
    `video_results`) with a full, duplicate-free `payload["order"]`.

    `order` names each item by `card_identity` -- the same identity
    `decision_cards.resolve_card` uses for a single-target decision, so a
    singleton item that already carries its own `version_id` is addressed
    by that id here too, never by its bare group id.
    """

    if target_id not in REORDERABLE_COLLECTIONS:
        raise DecisionError(f"unsupported reorder target: {target_id!r}")
    if not isinstance(payload, dict):
        raise DecisionError("reorder payload must be an object")
    order = payload.get("order")
    if (
        not isinstance(order, list)
        or not order
        or not all(isinstance(item, str) and item for item in order)
        or len(set(order)) != len(order)
    ):
        raise DecisionError("reorder payload.order must be a list of distinct ids")
    expected_stage, id_key = STAGE_COLLECTIONS[target_id]
    state_key = target_id

    def mutate(state):
        view = derive_view_stage(state)
        if view["current_stage"] != expected_stage:
            raise DecisionError(
                f"{target_id!r} is not reorderable at stage "
                f"{view['current_stage']!r} (only at {expected_stage!r})"
            )
        items = state.get(state_key)
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise DecisionError(f"{state_key} must be a list")
        current_ids = [card_identity(item, id_key) for item in items]
        if len(current_ids) != len(order) or set(current_ids) != set(order):
            # Full-order-only: a payload missing an id, repeating one, or
            # naming one that no longer exists is refused outright rather
            # than partially applied.
            raise DecisionError("reorder must supply every current id exactly once")
        by_id = {card_identity(item, id_key): item for item in items}
        if state_key == "scenes":
            # `order` is renumbered from 1, and the list itself (not just
            # the field) is put in the new sequence -- both, not either.
            for position, item_id in enumerate(order, start=1):
                by_id[item_id]["order"] = position
        items[:] = [by_id[item_id] for item_id in order]
        if state_key == "scenes":
            recompute_scene_ranges(state)
        append_history(state, "you", _HISTORY_KIND_BY_COLLECTION[target_id], expected_stage)

    return mutate

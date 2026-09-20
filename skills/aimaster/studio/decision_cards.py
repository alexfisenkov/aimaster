"""Card/version resolution: one identity rule, scoped to the collection the
project's current stage owns.

`card_identity` names the one canonical id a list item is addressed by --
its own `version_id` when it has one, its group id (`prompt_id`/
`result_id`) otherwise. `resolve_card` (approve/reject/hide/unhide/retire/
restore/edit, through `resolve_stage_prompt`/`resolve_stage_result` below)
and `decision_reorder.plan_reorder`'s full-order validation both match
against this same identity: a singleton item that already carries its own
`version_id` is addressed by that id everywhere, never by its bare group
id in one place and its version id in another.

`STAGE_COLLECTIONS` is the one "collection -> (stage, id key)" map every
stage-scoped lookup in this build reads: which single stage owns each
addressable collection, and which field identifies one of its items.
`resolve_stage_prompt`/`resolve_stage_result` below read it to find the
collection a card decision may act on *now*; `decision_reorder.plan_reorder`
reads the very same map to find the collection (and stage) a `reorder`
`target_id` names. Neither keeps its own copy, and neither can drift from
the other about which stage owns what. Which of its entries `reorder` may
address is a separate, explicit decision (`decision_reorder.
REORDERABLE_COLLECTIONS`).
"""

from __future__ import annotations

from .decision_support import DecisionError
from .domain import derive_view_stage


# The one authoritative "collection -> (stage, id key)" map. `scenes` is
# reorderable but never a card-decision target; `image_prompts` is a
# card-decision target but never reorderable (a versioned prompt group has
# no single order) -- both `resolve_stage_prompt`/`resolve_stage_result`
# and `decision_reorder.plan_reorder` read this same dict for *where* a
# collection lives, so neither keeps a second copy of which stage owns what.
# Which entries a card decision addresses follows from the id key (see
# `PROMPT_COLLECTIONS`/`RESULT_COLLECTIONS` below); which a `reorder` may
# address is an explicit set (`decision_reorder.REORDERABLE_COLLECTIONS`),
# never inferred from mere membership here.
STAGE_COLLECTIONS = {
    "image_prompts": ("image_plan", "prompt_id"),
    "motion_prompts": ("image_plan", "prompt_id"),
    "scenes": ("scenario", "scene_id"),
    "image_results": ("image_results", "result_id"),
    "video_results": ("motion", "result_id"),
    "audio_prompts": ("audio", "prompt_id"),
    "audio_results": ("audio", "result_id"),
}

# The one stage `image_prompts` belongs to -- derived from
# `STAGE_COLLECTIONS` above, not an independently authored constant, so it
# cannot name a different stage than the map itself does.
PROMPT_STAGE = STAGE_COLLECTIONS["image_prompts"][0]


def _collections_addressed_by(id_key: str) -> tuple[str, ...]:
    return tuple(name for name, (_, key) in STAGE_COLLECTIONS.items() if key == id_key)


# The two kinds of card a decision can address, told by the id field their
# `STAGE_COLLECTIONS` entry names, in that map's own order (stage order):
# a versioned prompt (`prompt_id`) or a versioned result (`result_id`).
# `scenes` is neither. `projection.action_target_stage`'s two search tuples
# and `_RESULT_COLLECTIONS_BY_STAGE` below are built from these, so a
# collection joins them by being added to `STAGE_COLLECTIONS` -- there is no
# second literal list of result collections left to forget.
PROMPT_COLLECTIONS = _collections_addressed_by("prompt_id")
RESULT_COLLECTIONS = _collections_addressed_by("result_id")

# Editing follows the step where the prompt is visible, not only the stage
# where its collection first appears. Other card decisions keep using the
# single owner stage in STAGE_COLLECTIONS.
PROMPT_EDIT_COLLECTIONS_BY_STAGE = {
    "image_plan": ("image_prompts", "motion_prompts"),
    "image_results": ("image_prompts",),
    "motion": ("motion_prompts",),
    "audio": ("audio_prompts",),
}

# The collection a result-card decision (approve/reject/hide/unhide/retire/
# restore) addresses, keyed by the one stage that owns it. `image_prompts`
# is looked up directly by `resolve_stage_prompt`, since it is the only
# prompt-shaped entry, and `scenes` is never a card-decision target.
_RESULT_COLLECTIONS_BY_STAGE = {
    STAGE_COLLECTIONS[name][0]: (name, STAGE_COLLECTIONS[name][1])
    for name in RESULT_COLLECTIONS
}


def card_identity(item: dict, id_key: str):
    """The one canonical id `resolve_card` and `reorder` both address an
    item by: its own `version_id` when it has one, its group id otherwise.
    """

    version_id = item.get("version_id")
    return version_id if isinstance(version_id, str) and version_id else item.get(id_key)


def resolve_card(items, id_key: str, target_id, payload):
    """Resolve exactly one entity in a same-group-id version list, or `None`.

    Two addressing modes. `target_id` may itself equal an item's own
    `card_identity` directly -- the common case, and the only way to name
    one specific version once its group has more than one member.
    `target_id` may instead name the group id, paired with an explicit
    `payload["version_id"]` that picks one member out of the group --
    useful when a caller only knows the stable group id. A
    `payload["version_id"]` that is *present* but not a non-empty string
    refuses outright (`None`), never silently falling back to plain
    `target_id` resolution as if no disambiguator had been supplied.
    """

    if not isinstance(items, list):
        return None
    candidates = [item for item in items if isinstance(item, dict)]
    payload_version_id = payload.get("version_id") if isinstance(payload, dict) else None
    if payload_version_id is not None:
        if not isinstance(payload_version_id, str) or not payload_version_id:
            return None
        matches = [
            item
            for item in candidates
            if item.get(id_key) == target_id and item.get("version_id") == payload_version_id
        ]
        return matches[0] if len(matches) == 1 else None
    matches = [item for item in candidates if card_identity(item, id_key) == target_id]
    return matches[0] if len(matches) == 1 else None


def resolve_stage_prompt(state: dict, target_id, payload) -> dict:
    """Resolve a prompt in any registered prompt collection at its own stage."""

    return resolve_stage_card(state, target_id, payload, collections=PROMPT_COLLECTIONS)[1]


def resolve_prompt_for_edit(state: dict, target_id, payload):
    """Resolve one prompt from the exact collection visible at this stage."""

    stage = derive_view_stage(state)["current_stage"]
    collections = PROMPT_EDIT_COLLECTIONS_BY_STAGE.get(stage, ())
    matches = []
    for name in collections:
        _stage, id_key = STAGE_COLLECTIONS[name]
        target = resolve_card(state.get(name), id_key, target_id, payload)
        if target is not None:
            matches.append((name, target))
    if len(matches) != 1:
        raise DecisionError("prompt edit target is missing or ambiguous at the current stage")
    return matches[0]


def resolve_stage_result(state: dict, target_id, payload) -> dict:
    """The one result entry `target_id` names, in whichever of
    `image_results`/`video_results` the current stage owns."""

    return resolve_stage_card(state, target_id, payload, collections=RESULT_COLLECTIONS)[1]


def resolve_stage_card(state, target_id, payload, *, collections=None):
    """Resolve exactly one version before applying its collection's stage guard."""
    if collections is None:
        collections = PROMPT_COLLECTIONS + RESULT_COLLECTIONS
    matches = []
    for name in collections:
        stage, id_key = STAGE_COLLECTIONS[name]
        target = resolve_card(state.get(name), id_key, target_id, payload)
        if target is not None:
            matches.append((name, target))
    if len(matches) != 1:
        raise DecisionError("card target is missing or ambiguous across collections")
    name, target = matches[0]
    if derive_view_stage(state)["current_stage"] != STAGE_COLLECTIONS[name][0]:
        raise DecisionError("card does not belong to the current stage")
    return name, target

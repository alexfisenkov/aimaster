"""Canonical creator-studio invariants.

The browser receives a stage derived from durable milestones.  Version helpers
only append records and switch active pointers; existing history is never
rewritten.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable


# The one place the stage sequences are spelled out (spec §18.2, G10-G13).
# Everything else -- `_stage_sequence` below, the projection's section gates,
# `decision_stages.MILESTONE_TARGETS`, the milestone reset a reopen performs
# -- reads these two tuples through `_stage_sequence`, never a second list.
# There is no `qa` stage any more (G12); a project file written before that
# still names `qa` in `milestones`, `stage_decisions` or a `qa` state key,
# and `projection` keeps reading those without ever projecting them.
VIDEO_STAGES = (
    "scenario",
    "image_plan",
    "image_results",
    "motion",
    "audio",
    "assembly",
)
PHOTO_STAGES = ("scenario", "image_plan", "image_results", "assembly")
MILESTONE_STATUSES = {"draft", "ready", "approved", "blocked"}

# Browser-visible decision history is deliberately smaller than either a
# ledger payload or a creative record.  Values are ids/enums only; free-form
# text, comments and prompts stay in their owning records and can never leak
# through the history panel.
HISTORY_KINDS = {
    "stage-approved": frozenset(),
    "stage-rework": frozenset(),
    "stage-ready": frozenset(),
    "stage-blocked": frozenset(),
    "scenario-reopened": frozenset(),
    "scenario-edited": frozenset(),
    "scene-edited": frozenset({"scene_id", "field"}),
    "scene-added": frozenset(),
    "scenes-reordered": frozenset(),
    "image-results-reordered": frozenset(),
    "video-results-reordered": frozenset(),
    "prompt-edited": frozenset({"target_id"}),
    "accepted": frozenset({"target_id"}),
    "rejected": frozenset(),
    "hidden": frozenset(),
    "unhidden": frozenset(),
    "retired": frozenset(),
    "restored": frozenset(),
    "reference-added": frozenset({"tag"}),
    "reference-edited": frozenset({"tag", "field"}),
    "reference-attached": frozenset({"tag", "field"}),
    "scene-reference-enabled": frozenset({"scene_id", "tag"}),
    "scene-reference-disabled": frozenset({"scene_id", "tag"}),
    "mode-set": frozenset({"mode"}),
    "result-ready": frozenset({"target_id"}),
    "prompt-ready": frozenset({"target_id"}),
    "script-ready": frozenset(),
    "scenes-ready": frozenset(),
    "assembly-ready": frozenset(),
    "frame-plan-set": frozenset({"scene_id", "first", "last"}),
    "gen-mode-set": frozenset({"mode"}),
    "video-mode-set": frozenset({"scene_id", "mode"}),
}
_HISTORY_ACTORS = frozenset({"you", "agent"})
_HISTORY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_HISTORY_FIELDS = frozenset({"text", "title", "duration"})
_HISTORY_REFERENCE_FIELDS = frozenset({"name", "source", "usage", "voice_enabled"})
_HISTORY_ATTACHMENT_FIELDS = frozenset({"asset", "voice_asset"})
_HISTORY_MODES = frozenset({"guided", "autopilot"})
_GENERATION_MODES = frozenset({"per_scene", "one_shot"})
_VIDEO_MODES = frozenset({"first", "firstlast", "references"})
_REFERENCE_TAG_PREFIXES = frozenset({"IMG", "VID", "VOICE"})
_PROMPT_TAG = re.compile(r"@((?:IMG|VID|VOICE)_\d+)(?![A-Za-z0-9_])")
_VIDEO_REFERENCE_USAGES = frozenset({"reference", "motion", "continue", "edit"})
_REFERENCE_ACTIONS = (
    "reference-add",
    "reference-edit",
    "scene-reference-toggle",
)

# What a stage where a result card is decided (`image_results`, `motion`,
# `audio`) lets the dashboard do -- one list, so the three can never drift.
# `reorder` is here because two of the three own an orderable result
# collection (`decision_reorder.REORDERABLE_COLLECTIONS`); `audio` shares the
# list on purpose (its layers arrive with the audio-layer tickets) and its
# `reorder` reaches no collection until then -- `decision_reorder.plan_reorder`
# refuses a collection outside its own stage.
_RESULT_STAGE_ACTIONS = (
    "approve",
    "reject",
    "edit",
    "vary",
    "regenerate",
    "generate",
    "prompt-refresh",
    "hide",
    "unhide",
    "retire",
    "restore",
    "reorder",
    *_REFERENCE_ACTIONS,
    "reopen-scenario",
    "continue-in-chat",
)

# `reorder` added by ticket 11 (поправка оркестратора 2026-09-16) only to
# the stages where an order actually exists and matters: `image_plan`
# orders `scenes[]` (their existing `order` field), `image_results`/
# `motion` order their result cards. `scenario` (nothing to order yet) and
# `assembly` (a single object, not an orderable collection) do not get it.
#
# `reopen-scenario` added by ticket 15 (G05, owner's answer 17.09.2026:
# "да можно и даже нужно возвращаться что бы править сценарий") to every
# stage *after* `scenario` -- never to `scenario` itself, where there is
# nothing approved yet to reopen (ticket 15's own acceptance criterion).
# A `blocked` gate already replaces this whole list with
# `["continue-in-chat"]` below, so blocking a pending question out of
# `reopen-scenario` needs no extra entry here -- see `derive_view_stage`.
#
# `edit` added to `scenario` itself by ticket 15's repair (поправка
# оркестратора 1, 2026-09-17): after a reopen the only reachable stage is
# `scenario` again, and the one thing a reopen exists to let someone do is
# edit a scene's own block there -- `decision_planners.plan_edit` already
# branches a scene-shaped `target_id` away from prompt resolution (which
# stays `image_plan`-only), so admitting `edit` here only ever reaches
# that branch: a prompt `target_id` still falls through to
# `resolve_stage_prompt`, which still refuses outside `image_plan`
# exactly as before. See that function's own docstring.
#
# Every stage of either sequence has exactly one entry (a test pins that in
# both directions), so `derive_view_stage` can name a stage without an
# entry as the domain error it is instead of a bare `KeyError`.
_STAGE_ACTIONS = {
    "scenario": [
        "approve-scenario",
        "revise-scenario",
        "edit",
        "reorder",
        "scene-add",
        "continue-in-chat",
    ],
    "image_plan": [
        "approve",
        "reject",
        "edit",
        *_REFERENCE_ACTIONS,
        "scene-frame-plan",
        "set-gen-mode",
        "prompts-generate",
        "prompt-refresh",
        "reopen-scenario",
        "continue-in-chat",
    ],
    "image_results": list(_RESULT_STAGE_ACTIONS),
    "motion": [*_RESULT_STAGE_ACTIONS, "set-video-mode"],
    "audio": list(_RESULT_STAGE_ACTIONS),
    "assembly": ["approve", "reject", "reopen-scenario", "continue-in-chat", "assemble"],
}
for _actions in _STAGE_ACTIONS.values():
    _actions.append("set-mode")


class DomainValidationError(ValueError):
    """Canonical state violates a domain invariant."""


def next_tag(state: dict, prefix: str) -> str:
    """Return the lowest free deterministic reference tag.

    Callers allocate while holding ``ProjectStore.transact``'s project lock;
    this helper deliberately reads only the candidate state passed to that
    transaction and never time, randomness or a preloaded snapshot.
    """

    _require_mapping(state, "state")
    if prefix not in _REFERENCE_TAG_PREFIXES:
        raise DomainValidationError("reference tag prefix must be IMG, VID or VOICE")
    references = state.get("references", [])
    if not isinstance(references, list):
        raise DomainValidationError("references must be a list")
    pattern = re.compile(rf"{prefix}_(\d+)\Z")
    used = set()
    for position, reference in enumerate(references):
        reference = _require_mapping(reference, f"references[{position}]")
        if prefix in {"IMG", "VID"}:
            candidates = (reference.get("tag"), reference.get("reference_id"))
        else:
            voice = reference.get("voice", {})
            if not isinstance(voice, dict):
                raise DomainValidationError(f"references[{position}].voice must be an object")
            candidates = (voice.get("tag"),)
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            match = pattern.fullmatch(candidate)
            if match and int(match.group(1)) > 0:
                used.add(int(match.group(1)))
    number = 1
    while number in used:
        number += 1
    return f"{prefix}_{number:02d}"


def _reference_collection(state: dict) -> list[dict]:
    references = state.setdefault("references", [])
    if not isinstance(references, list) or not all(
        isinstance(reference, dict) for reference in references
    ):
        raise DomainValidationError("references must be a list of objects")
    return references


def find_reference(state: dict, reference_id: str) -> dict:
    matches = [
        reference
        for reference in _reference_collection(state)
        if reference.get("reference_id") == reference_id
    ]
    if len(matches) != 1:
        raise DomainValidationError(f"unknown or duplicate reference_id: {reference_id!r}")
    return matches[0]


def add_reference(
    state: dict,
    *,
    kind: str,
    name: str | None,
    source: str,
    usage: str = "reference",
    scene_id: str | None = None,
    all_scenes: bool = False,
) -> dict:
    """Add one canonical reference and allocate its tag in this mutation."""

    if kind not in {"character", "product", "location", "style", "video"}:
        raise DomainValidationError("reference kind is not supported")
    if kind == "video" and state.get("project", {}).get("type") == "photo":
        raise DomainValidationError("video references require video/mixed project")
    if source not in {"upload", "generate"}:
        raise DomainValidationError("reference source must be upload or generate")
    if kind == "video" and source != "upload":
        raise DomainValidationError("a video reference must use upload source")
    if kind == "video" and usage not in _VIDEO_REFERENCE_USAGES:
        raise DomainValidationError("video reference usage is not supported")
    if name is not None and (not isinstance(name, str) or len(name) > 200):
        raise DomainValidationError("reference name must be a string of at most 200 characters")
    if scene_id is not None and all_scenes:
        raise DomainValidationError("a local reference cannot also target all scenes")
    scenes = state.get("scenes", [])
    if not isinstance(scenes, list) or not all(isinstance(scene, dict) for scene in scenes):
        raise DomainValidationError("scenes must be a list of objects")
    local_scene = None
    if scene_id is not None:
        matches = [scene for scene in scenes if scene.get("scene_id") == scene_id]
        if len(matches) != 1:
            raise DomainValidationError(f"unknown or duplicate scene_id: {scene_id!r}")
        local_scene = matches[0]

    tag = next_tag(state, "VID" if kind == "video" else "IMG")
    entry = {
        "reference_id": tag,
        "role": kind,
        "tag": tag,
        "label": name if name is not None else tag,
        "source": source,
        "local": local_scene is not None,
        "voice": {"enabled": False},
    }
    if kind == "video":
        entry["usage"] = usage
    if local_scene is not None:
        entry["scene_id"] = scene_id
    _reference_collection(state).append(entry)

    targets = [local_scene] if local_scene is not None else scenes if all_scenes or kind == "style" else []
    for scene in targets:
        links = scene.setdefault("links", {})
        if not isinstance(links, dict):
            raise DomainValidationError("scene.links must be an object")
        reference_ids = links.setdefault("reference_ids", [])
        if not isinstance(reference_ids, list):
            raise DomainValidationError("scene.links.reference_ids must be a list")
        if tag not in reference_ids:
            reference_ids.append(tag)
    append_history(
        state, "you", "reference-added", derive_view_stage(state)["current_stage"], tag=tag
    )
    _ensure_reference_default_prompt(state, entry)
    return copy.deepcopy(entry)


def edit_reference(state: dict, reference_id: str, field: str, value) -> dict:
    reference = find_reference(state, reference_id)
    previous_source = reference.get("source")
    if field == "name":
        if not isinstance(value, str) or len(value) > 200:
            raise DomainValidationError("reference name must be a string of at most 200 characters")
        reference["label"] = value
    elif field == "source":
        if value not in {"upload", "generate"}:
            raise DomainValidationError("reference source must be upload or generate")
        if reference.get("role") == "video" and value != "upload":
            raise DomainValidationError("a video reference must use upload source")
        reference["source"] = value
    elif field == "usage":
        if reference.get("role") != "video":
            raise DomainValidationError("only a video reference can have usage")
        if value not in _VIDEO_REFERENCE_USAGES:
            raise DomainValidationError("video reference usage is not supported")
        reference["usage"] = value
    elif field == "voice_enabled":
        if not isinstance(value, bool):
            raise DomainValidationError("voice_enabled must be a boolean")
        if reference.get("role") != "character":
            raise DomainValidationError("only a character reference can have a voice")
        voice = reference.setdefault("voice", {"enabled": False})
        if not isinstance(voice, dict):
            raise DomainValidationError("reference.voice must be an object")
        if value and "tag" not in voice:
            voice["tag"] = next_tag(state, "VOICE")
        voice["enabled"] = value
    else:
        raise DomainValidationError("reference edit field is not supported")
    append_history(
        state,
        "you",
        "reference-edited",
        derive_view_stage(state)["current_stage"],
        tag=reference_id,
        field=field,
    )
    if field == "source" and previous_source == "upload" and value == "generate":
        _ensure_reference_default_prompt(state, reference)
    return copy.deepcopy(reference)


def attach_reference_asset(
    state: dict, reference_id: str, asset_id: str, *, attachment_kind: str
) -> dict:
    reference = find_reference(state, reference_id)
    if attachment_kind == "voice":
        if reference.get("role") != "character":
            raise DomainValidationError("only a character reference can have a voice")
        voice_state = reference.get("voice")
        if not isinstance(voice_state, dict) or voice_state.get("enabled") is not True:
            raise DomainValidationError("voice must be enabled before attaching its file")
        voice_state["asset_id"] = asset_id
        field = "voice_asset"
    elif attachment_kind == "video":
        if reference.get("role") != "video":
            raise DomainValidationError("a video asset requires a video reference")
        reference["asset_id"] = asset_id
        field = "asset"
    elif attachment_kind == "image":
        if reference.get("role") == "video":
            raise DomainValidationError("a video reference requires a video asset")
        reference["asset_id"] = asset_id
        field = "asset"
    else:
        raise DomainValidationError("reference attachment kind is not supported")
    append_history(
        state,
        "you",
        "reference-attached",
        derive_view_stage(state)["current_stage"],
        tag=reference_id,
        field=field,
    )
    return copy.deepcopy(reference)


def toggle_scene_reference(state: dict, scene_id: str, reference_id: str, on: bool) -> dict:
    if not isinstance(on, bool):
        raise DomainValidationError("reference toggle value must be a boolean")
    reference = find_reference(state, reference_id)
    if reference.get("local") is True:
        raise DomainValidationError("a local reference is fixed to its own scene")
    scenes = state.get("scenes", [])
    matches = [scene for scene in scenes if isinstance(scene, dict) and scene.get("scene_id") == scene_id]
    if len(matches) != 1:
        raise DomainValidationError(f"unknown or duplicate scene_id: {scene_id!r}")
    links = matches[0].setdefault("links", {})
    if not isinstance(links, dict):
        raise DomainValidationError("scene.links must be an object")
    reference_ids = links.setdefault("reference_ids", [])
    if not isinstance(reference_ids, list):
        raise DomainValidationError("scene.links.reference_ids must be a list")
    if on and reference_id not in reference_ids:
        reference_ids.append(reference_id)
    if not on:
        reference_ids[:] = [item for item in reference_ids if item != reference_id]
    append_history(
        state,
        "you",
        "scene-reference-enabled" if on else "scene-reference-disabled",
        derive_view_stage(state)["current_stage"],
        scene_id=scene_id,
        tag=reference_id,
    )
    return copy.deepcopy(reference)


def _video_scene(state: dict, scene_id: str) -> dict:
    project = _require_mapping(state.get("project"), "project")
    if project.get("type") not in {"video", "mixed"}:
        raise DomainValidationError("photo projects do not have frame or video modes")
    scene_id = _require_non_empty_string(scene_id, "scene_id")
    scenes = state.get("scenes", [])
    matches = [scene for scene in scenes if isinstance(scene, dict) and scene.get("scene_id") == scene_id]
    if len(matches) != 1:
        raise DomainValidationError(f"unknown or duplicate scene_id: {scene_id}")
    return matches[0]


def frame_basis(scene: dict) -> dict:
    """Return the stable, non-creative basis future prompt work reads."""

    scene = _require_mapping(scene, "scene")
    first = scene.get("need_first", False)
    last = scene.get("need_last", False)
    if not isinstance(first, bool) or not isinstance(last, bool):
        raise DomainValidationError("scene frame plan flags must be booleans")
    mode = scene.get("video_mode", "first" if first else "references")
    if not isinstance(mode, str) or mode not in _VIDEO_MODES:
        raise DomainValidationError("scene video_mode is not supported")
    if mode == "first" and not first:
        raise DomainValidationError("video_mode first requires need_first")
    if mode == "firstlast" and not (first and last):
        raise DomainValidationError("video_mode firstlast requires need_first and need_last")
    return {"need_first": first, "need_last": last, "video_mode": mode}


def extract_tags(text: str) -> list[str]:
    """Return canonical prompt tags once, in their first-seen order."""

    if not isinstance(text, str):
        raise DomainValidationError("prompt text must be a string")
    found = []
    seen = set()
    for match in _PROMPT_TAG.finditer(text):
        tag = match.group(1)
        if tag not in seen:
            found.append(tag)
            seen.add(tag)
    return found


def missing_tags(text: str, included_tags) -> list[str]:
    """Return included canonical tags absent from ``text``, without reordering."""

    if not isinstance(included_tags, (list, tuple)):
        raise DomainValidationError("included_tags must be a list or tuple")
    present = set(extract_tags(text))
    missing = []
    seen = set()
    for tag in included_tags:
        if not isinstance(tag, str) or not re.fullmatch(r"(?:IMG|VID|VOICE)_\d+", tag):
            raise DomainValidationError("included tag must use IMG_NN, VID_NN or VOICE_NN")
        if tag not in present and tag not in seen:
            missing.append(tag)
            seen.add(tag)
    return missing


def default_reference_prompt(kind: str, style_tag: str | None = None) -> str:
    """Build the canonical first prompt for a generated reference."""

    defaults = {
        "character": "портрет в рост, нейтральный фон, ровный свет, лицо и одежда целиком",
        "product": "предметная съёмка, нейтральный фон, несколько ракурсов, точная форма и материал",
        "location": "общий план без людей, характерный свет и глубина",
        "style": "палитра, характер света и оптика, эталон картинки",
    }
    if kind not in defaults:
        raise DomainValidationError("reference kind is not supported")
    prompt = defaults[kind]
    if kind != "style" and style_tag is not None:
        if not isinstance(style_tag, str) or not re.fullmatch(r"IMG_\d+", style_tag):
            raise DomainValidationError("style tag must use IMG_NN")
        prompt += f", в стиле @{style_tag}"
    return prompt


def _lowest_style_tag(state: dict) -> str | None:
    candidates = []
    for reference in state.get("references", []):
        if not isinstance(reference, dict) or reference.get("role") != "style":
            continue
        tag = reference.get("tag", reference.get("reference_id"))
        match = re.fullmatch(r"IMG_(\d+)", tag) if isinstance(tag, str) else None
        if match:
            candidates.append((int(match.group(1)), tag))
    return min(candidates)[1] if candidates else None


def _ensure_reference_default_prompt(state: dict, reference: dict) -> dict | None:
    """Create a generated reference's first prompt only at an explicit write."""

    if reference.get("source") != "generate" or reference.get("role") == "video":
        return None
    links = reference.setdefault("links", {})
    if not isinstance(links, dict):
        raise DomainValidationError("reference.links must be an object")
    if links.get("image_prompt_version_id"):
        return None
    specs = [
        spec for spec in position_specs(state)
        if spec.get("owner_kind") == "reference"
        and spec.get("owner_id") == reference.get("reference_id")
    ]
    if len(specs) != 1:
        raise DomainValidationError("generated reference prompt owner is missing or ambiguous")
    spec = specs[0]
    group_id = spec["prompt_group_id"]
    prompts = state.setdefault("image_prompts", [])
    if not isinstance(prompts, list) or not all(isinstance(item, dict) for item in prompts):
        raise DomainValidationError("image_prompts must be a list of objects")
    # Never adopt or overwrite an unlinked pre-existing history implicitly.
    if any(item.get("prompt_id") == group_id for item in prompts):
        return None
    kind = "product" if reference.get("role") == "object" else reference.get("role")
    style_tag = None if kind == "style" else _lowest_style_tag(state)
    prompt = start_prompt_version(
        group_id,
        default_reference_prompt(kind, style_tag),
        "дефолт по виду референса",
        "agent",
        basis=prompt_basis(state, spec),
    )
    prompts.append(prompt)
    links["image_prompt_version_id"] = prompt["version_id"]
    append_history(state, "agent", "prompt-ready", "image_plan", target_id=group_id)
    return copy.deepcopy(prompt)


def _active_block_version_id(scene: dict):
    block = scene.get("script_block", {})
    if not isinstance(block, dict):
        raise DomainValidationError("scene.script_block must be an object")
    active = block.get("active_version_id")
    if active is not None and (not isinstance(active, str) or not active):
        raise DomainValidationError("scene.script_block.active_version_id must be a string or null")
    return active


def _scene_prompt_basis(
    state: dict, scene: dict, *, include_video_references: bool = False
) -> dict:
    title = scene.get("title", "")
    if not isinstance(title, str):
        raise DomainValidationError("scene.title must be a string")
    links = scene.get("links", {})
    if not isinstance(links, dict):
        raise DomainValidationError("scene.links must be an object")
    reference_ids = links.get("reference_ids", [])
    if not isinstance(reference_ids, list) or not all(isinstance(item, str) for item in reference_ids):
        raise DomainValidationError("scene.links.reference_ids must be a list of strings")
    video_references_by_id = {
        item.get("reference_id"): item
        for item in state.get("references", [])
        if isinstance(item, dict) and item.get("role") == "video"
    }
    effective_reference_ids = (
        reference_ids
        if include_video_references
        else [identity for identity in reference_ids if identity not in video_references_by_id]
    )
    basis = {
        "title": title,
        "block_version_id": _active_block_version_id(scene),
        "reference_ids": sorted(set(effective_reference_ids)),
    }
    if include_video_references:
        video_references = [
            {
                "reference_id": identity,
                "role": "video",
                "asset_id": video_references_by_id[identity].get("asset_id"),
                "usage": video_references_by_id[identity].get("usage", "reference"),
            }
            for identity in sorted(set(reference_ids))
            if identity in video_references_by_id
        ]
        # Preserve every pre-video-reference prompt basis byte-for-byte. The
        # key appears only once a scene actually includes a video reference;
        # removing the final one then makes the old populated basis stale.
        if video_references:
            basis["video_references"] = video_references
    if state.get("project", {}).get("type") != "photo":
        duration = scene.get("duration_ms")
        if duration is None:
            start, end = scene.get("start_ms"), scene.get("end_ms")
            if (isinstance(start, int) and not isinstance(start, bool)
                    and isinstance(end, int) and not isinstance(end, bool)):
                duration = end - start
        if not isinstance(duration, int) or isinstance(duration, bool):
            raise DomainValidationError("video scene duration_ms must be an integer")
        plan = frame_basis(scene)
        basis.update(
            duration_ms=duration,
            need_first=plan["need_first"],
            need_last=plan["need_last"],
            gen_mode=state.get("gen_mode", "per_scene"),
        )
    return basis


def prompt_basis(state: dict, spec: dict) -> dict:
    """Snapshot the private source facts one prompt version was built from."""

    _require_mapping(state, "state")
    spec = _require_mapping(spec, "position spec")
    owner_kind = spec.get("owner_kind")
    owner_id = spec.get("owner_id")
    if owner_kind == "scene":
        matches = [item for item in state.get("scenes", [])
                   if isinstance(item, dict) and item.get("scene_id") == owner_id]
        if len(matches) != 1:
            raise DomainValidationError("prompt scene owner is missing or duplicated")
        return _scene_prompt_basis(
            state,
            matches[0],
            include_video_references=spec.get("kind") == "video",
        )
    if owner_kind == "reference":
        matches = [item for item in state.get("references", [])
                   if isinstance(item, dict) and item.get("reference_id") == owner_id]
        if len(matches) != 1:
            raise DomainValidationError("prompt reference owner is missing or duplicated")
        reference = matches[0]
        label, kind = reference.get("label", ""), reference.get("role")
        if not isinstance(label, str) or kind not in {"character", "product", "object", "location", "style"}:
            raise DomainValidationError("prompt reference owner is invalid")
        return {"label": label, "kind": "product" if kind == "object" else kind}
    if owner_kind == "oneshot":
        scenes = sorted(
            (item for item in state.get("scenes", []) if isinstance(item, dict)),
            key=lambda item: (item.get("order", 0), item.get("scene_id", "")),
        )
        return {
            "gen_mode": state.get("gen_mode", "per_scene"),
            "scenes": [
                {
                    "scene_id": scene.get("scene_id"),
                    **_scene_prompt_basis(
                        state, scene, include_video_references=True
                    ),
                }
                for scene in scenes
            ],
        }
    if owner_kind == "audio":
        return {"gen_mode": state.get("gen_mode", "per_scene")}
    raise DomainValidationError("prompt position owner is not supported")


def compute_prompt_stale(state: dict, prompt: dict, spec: dict) -> bool:
    """Compare a current prompt version's private basis with live owner facts."""

    prompt = _require_mapping(prompt, "prompt")
    return prompt.get("basis") != prompt_basis(state, spec)


def validate_prompt_tags(text: str, spec: dict) -> None:
    """Keep voice references out of prompts for static image positions."""

    spec = _require_mapping(spec, "position spec")
    if spec.get("kind") in {"reference", "image", "first_frame", "last_frame"}:
        if any(tag.startswith(("VID_", "VOICE_")) for tag in extract_tags(text)):
            raise DomainValidationError(
                "@VID_NN and @VOICE_NN are not allowed in a static image prompt"
            )


def set_scene_frame_plan(state: dict, scene_id: str, *, first=None, last=None) -> dict:
    """Change one video scene's requested frames and repair an invalid mode."""

    if first is None and last is None:
        raise DomainValidationError("frame plan requires first or last")
    if first is not None and not isinstance(first, bool):
        raise DomainValidationError("frame plan first must be a boolean")
    if last is not None and not isinstance(last, bool):
        raise DomainValidationError("frame plan last must be a boolean")
    scene = _video_scene(state, scene_id)
    basis = frame_basis(scene)
    next_first = basis["need_first"] if first is None else first
    next_last = basis["need_last"] if last is None else last
    scene["need_first"] = next_first
    scene["need_last"] = next_last
    mode = basis["video_mode"]
    if mode == "first" and not next_first:
        mode = "references"
    elif mode == "firstlast" and not (next_first and next_last):
        mode = "first" if next_first else "references"
    scene["video_mode"] = mode
    append_history(
        state, "you", "frame-plan-set", "image_plan", scene_id=scene_id,
        first=next_first, last=next_last,
    )
    if mode != basis["video_mode"]:
        append_history(state, "you", "video-mode-set", "image_plan", scene_id=scene_id, mode=mode)
    return frame_basis(scene)


def set_video_mode(state: dict, scene_id: str, mode: str) -> dict:
    """Select a valid motion mode for one video scene."""

    if not isinstance(mode, str) or mode not in _VIDEO_MODES:
        raise DomainValidationError("video mode must be first, firstlast or references")
    scene = _video_scene(state, scene_id)
    basis = frame_basis(scene)
    if mode == "first" and not basis["need_first"]:
        raise DomainValidationError("video_mode first requires need_first")
    if mode == "firstlast" and not (basis["need_first"] and basis["need_last"]):
        raise DomainValidationError("video_mode firstlast requires need_first and need_last")
    scene["video_mode"] = mode
    append_history(state, "you", "video-mode-set", "motion", scene_id=scene_id, mode=mode)
    return frame_basis(scene)


def set_gen_mode(state: dict, mode: str) -> str:
    """Set the video-only generation topology at the frame-plan stage."""

    project = _require_mapping(state.get("project"), "project")
    if project.get("type") not in {"video", "mixed"}:
        raise DomainValidationError("photo projects do not have gen_mode")
    if not isinstance(mode, str) or mode not in _GENERATION_MODES:
        raise DomainValidationError("gen mode must be per_scene or one_shot")
    state["gen_mode"] = mode
    append_history(state, "you", "gen-mode-set", "image_plan", mode=mode)
    return mode


def _validate_history_params(kind: str, params) -> dict:
    if not isinstance(params, dict):
        raise DomainValidationError("history.params must be an object")
    expected = HISTORY_KINDS.get(kind)
    if expected is None:
        raise DomainValidationError(f"unknown history kind: {kind!r}")
    if set(params) != set(expected):
        raise DomainValidationError(
            f"history params for {kind!r} must be exactly {sorted(expected)!r}"
        )
    for key in ("scene_id", "target_id", "tag"):
        if key in params and (
            not isinstance(params[key], str) or _HISTORY_ID.fullmatch(params[key]) is None
        ):
            raise DomainValidationError(f"history.params.{key} must be a safe identifier")
    if "field" in params:
        allowed_fields = (
            _HISTORY_REFERENCE_FIELDS
            if kind == "reference-edited"
            else _HISTORY_ATTACHMENT_FIELDS
            if kind == "reference-attached"
            else _HISTORY_FIELDS
        )
        if params["field"] not in allowed_fields:
            raise DomainValidationError("history.params.field is not supported")
    if "mode" in params:
        modes = _HISTORY_MODES if kind == "mode-set" else _GENERATION_MODES if kind == "gen-mode-set" else _VIDEO_MODES
        if not isinstance(params["mode"], str) or params["mode"] not in modes:
            raise DomainValidationError("history.params.mode is not supported")
    for key in ("first", "last"):
        if key in params and not isinstance(params[key], bool):
            raise DomainValidationError(f"history.params.{key} must be a boolean")
    return copy.deepcopy(params)


def validate_history(state: dict) -> list[dict]:
    """Validate and copy the append-only deterministic history journal."""

    _require_mapping(state, "state")
    history = state.get("history", [])
    if not isinstance(history, list):
        raise DomainValidationError("history must be a list")
    stages = set(_stage_sequence(state))
    validated = []
    previous_seq = 0
    required_keys = {"seq", "actor", "kind", "stage", "params"}
    for position, raw in enumerate(history):
        if not isinstance(raw, dict) or set(raw) != required_keys:
            raise DomainValidationError(
                f"history[{position}] must contain exactly {sorted(required_keys)!r}"
            )
        seq = raw["seq"]
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            raise DomainValidationError(f"history[{position}].seq must be a positive integer")
        if seq <= previous_seq:
            raise DomainValidationError("history seq values must be strictly increasing")
        previous_seq = seq
        actor = raw["actor"]
        if actor not in _HISTORY_ACTORS:
            raise DomainValidationError(f"history[{position}].actor is not supported")
        kind = raw["kind"]
        if not isinstance(kind, str) or kind not in HISTORY_KINDS:
            raise DomainValidationError(f"unknown history kind: {kind!r}")
        stage = raw["stage"]
        if stage not in stages:
            raise DomainValidationError(f"history[{position}].stage is not in this project flow")
        validated.append(
            {
                "seq": seq,
                "actor": actor,
                "kind": kind,
                "stage": stage,
                "params": _validate_history_params(kind, raw["params"]),
            }
        )
    return validated


def append_history(state: dict, actor: str, kind: str, stage: str, **params) -> dict:
    """Append one deterministic history fact and return an isolated copy."""

    existing = validate_history(state)
    if actor not in _HISTORY_ACTORS:
        raise DomainValidationError("history actor must be 'you' or 'agent'")
    stages = set(_stage_sequence(state))
    if stage not in stages:
        raise DomainValidationError("history stage is not in this project flow")
    clean_params = _validate_history_params(kind, params)
    entry = {
        "seq": max((item["seq"] for item in existing), default=0) + 1,
        "actor": actor,
        "kind": kind,
        "stage": stage,
        "params": clean_params,
    }
    history = state.setdefault("history", [])
    history.append(copy.deepcopy(entry))
    return copy.deepcopy(entry)


def _require_mapping(value, label):
    if not isinstance(value, dict):
        raise DomainValidationError(f"{label} must be an object")
    return value


def _require_non_empty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise DomainValidationError(f"{label} must be a non-empty string")
    return value


def _require_non_negative_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DomainValidationError(f"{label} must be a non-negative integer")
    return value


def _stage_sequence(state):
    project = _require_mapping(state.get("project"), "project")
    project_type = project.get("type")
    if project_type == "photo":
        return PHOTO_STAGES
    if project_type in {"video", "mixed"}:
        return VIDEO_STAGES
    raise DomainValidationError("project.type must be photo, video or mixed")


def derive_view_stage(state: dict) -> dict:
    """Derive the only workflow stage the browser may currently expose."""

    _require_mapping(state, "state")
    revision = _require_non_negative_integer(state.get("revision"), "revision")
    milestones = _require_mapping(state.get("milestones"), "milestones")
    sequence = _stage_sequence(state)

    completed = []
    current_stage = sequence[-1]
    gate_status = "approved"
    for stage in sequence:
        status = milestones.get(stage, "draft")
        if status not in MILESTONE_STATUSES:
            raise DomainValidationError(
                f"milestones.{stage} must be draft, ready, approved or blocked"
            )
        if status == "approved" and stage != sequence[-1]:
            completed.append(stage)
            continue
        current_stage = stage
        gate_status = status
        break

    raw_blocking = state.get("blocking_question_ids", [])
    if not isinstance(raw_blocking, list) or not all(
        isinstance(value, str) and value for value in raw_blocking
    ):
        raise DomainValidationError(
            "blocking_question_ids must be a list of non-empty strings"
        )
    blocking_question_ids = list(dict.fromkeys(raw_blocking))
    if blocking_question_ids:
        gate_status = "blocked"

    # A stage of a sequence with no `_STAGE_ACTIONS` entry is a defect of the
    # registry, not of the project: it is named as one, and named even while
    # the gate is `blocked` (which would otherwise never read the entry).
    stage_actions = _STAGE_ACTIONS.get(current_stage)
    if stage_actions is None:
        raise DomainValidationError(
            f"no allowed actions are registered for stage {current_stage!r}"
        )
    allowed_actions = (
        ["continue-in-chat", "set-mode"] if gate_status == "blocked" else list(stage_actions)
    )
    return {
        "current_stage": current_stage,
        "completed_stages": completed,
        "stage_revision": revision,
        "gate_status": gate_status,
        "blocking_question_ids": blocking_question_ids,
        "allowed_actions": allowed_actions,
    }


def derive_project_status(view_stage: dict) -> str:
    """The `project.status` a derived `view_stage` implies (spec §18.13
    п. 3): `done` once `assembly` is approved, `review` while `assembly` is
    the current stage, `active` otherwise.

    Pure and shared. `decision_stages.apply_project_status` stores it after
    every decision; `projection.build_snapshot` reports it instead of the
    stored value, so a project file written under another stage model (no
    `audio` milestone, a completed video that now stands on `audio`) is
    never shown as `done` while its own stage says otherwise. `assembly`
    is `sequence[-1]` of both sequences and, once reached, never stops
    being the current stage -- `gate_status` is what tells `done` from
    `review`.
    """

    if view_stage["current_stage"] == "assembly":
        return "done" if view_stage["gate_status"] == "approved" else "review"
    return "active"


def validate_scene_ranges(scenes: Iterable[dict]) -> list[dict]:
    """Return validated scene copies with every time overlap made explicit."""

    if not isinstance(scenes, (list, tuple)):
        raise DomainValidationError("scenes must be a list")
    validated = []
    ids = set()
    for position, raw_scene in enumerate(scenes):
        scene = copy.deepcopy(_require_mapping(raw_scene, f"scenes[{position}]"))
        scene_id = _require_non_empty_string(
            scene.get("scene_id"), f"scenes[{position}].scene_id"
        )
        if scene_id in ids:
            raise DomainValidationError(f"duplicate scene_id: {scene_id}")
        ids.add(scene_id)
        start = _require_non_negative_integer(
            scene.get("start_ms"), f"scenes[{position}].start_ms"
        )
        end = _require_non_negative_integer(
            scene.get("end_ms"), f"scenes[{position}].end_ms"
        )
        if end <= start:
            raise DomainValidationError(
                f"scenes[{position}].end_ms must be greater than start_ms"
            )
        scene["overlap_scene_ids"] = []
        validated.append(scene)

    for left_index, left in enumerate(validated):
        for right in validated[left_index + 1 :]:
            if left["start_ms"] < right["end_ms"] and right["start_ms"] < left["end_ms"]:
                left["overlap_scene_ids"].append(right["scene_id"])
                right["overlap_scene_ids"].append(left["scene_id"])
    return validated


def _scene_duration_ms(scene: dict, label: str) -> int:
    """Return a canonical duration, accepting old stored ranges read-only."""

    if "duration_ms" in scene:
        duration = scene["duration_ms"]
    else:
        start = _require_non_negative_integer(scene.get("start_ms"), f"{label}.start_ms")
        end = _require_non_negative_integer(scene.get("end_ms"), f"{label}.end_ms")
        duration = end - start
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int)
        or duration < 1000
        or duration % 1000 != 0
    ):
        raise DomainValidationError(
            f"{label}.duration_ms must be an integer multiple of 1000 and at least 1000"
        )
    return duration


def recompute_scene_ranges(state: dict) -> list[dict]:
    """Rebuild derived scene ranges from order and duration in-place."""

    _require_mapping(state, "state")
    project = _require_mapping(state.get("project"), "project")
    scenes = state.get("scenes")
    if not isinstance(scenes, list) or not all(isinstance(scene, dict) for scene in scenes):
        raise DomainValidationError("scenes must be a list of objects")
    if project.get("type") == "photo":
        for scene in scenes:
            for key in ("duration_ms", "start_ms", "end_ms", "overlap_scene_ids"):
                scene.pop(key, None)
        return scenes

    ordered = sorted(scenes, key=lambda scene: scene.get("order", 0))
    cursor = 0
    for position, scene in enumerate(ordered):
        duration = _scene_duration_ms(scene, f"scenes[{position}]")
        scene["duration_ms"] = duration
        scene["start_ms"] = cursor
        cursor += duration
        scene["end_ms"] = cursor
        scene.pop("overlap_scene_ids", None)
    return scenes


def require_storyboard_complete(state: dict) -> None:
    scenes = state.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise DomainValidationError("scenario requires at least one scene")
    project = _require_mapping(state.get("project"), "project")
    if project.get("type") != "photo":
        for position, scene in enumerate(scenes):
            _scene_duration_ms(scene, f"scenes[{position}]")


def _version_container(state):
    script = _require_mapping(state.get("script"), "script")
    versions = script.get("versions")
    if not isinstance(versions, list) or not all(
        isinstance(version, dict) for version in versions
    ):
        raise DomainValidationError("script.versions must be a list of objects")
    active = script.get("active_version_id")
    known_ids = [version.get("version_id") for version in versions]
    if len(set(known_ids)) != len(known_ids) or any(
        not isinstance(version_id, str) or not version_id for version_id in known_ids
    ):
        raise DomainValidationError("script version ids must be unique strings")
    if active is not None and active not in known_ids:
        raise DomainValidationError("script.active_version_id must reference history")
    return script, versions, active


def append_script_version(
    state: dict, text: str, reason: str, author: str
) -> dict:
    """Append and activate a script version without touching older records."""

    _require_mapping(state, "state")
    text = _require_non_empty_string(text, "text")
    reason = _require_non_empty_string(reason, "reason")
    author = _require_non_empty_string(author, "author")
    script, versions, parent = _version_container(state)
    version = {
        "version_id": f"script-v{len(versions) + 1}",
        "parent_version_id": parent,
        "text": text,
        "reason": reason,
        "author": author,
    }
    if any(item["version_id"] == version["version_id"] for item in versions):
        raise DomainValidationError("next script version id already exists")
    versions.append(copy.deepcopy(version))
    script["active_version_id"] = version["version_id"]
    return copy.deepcopy(version)


def append_scene_block_version(
    state: dict, scene_id: str, text: str, reason: str, author: str
) -> dict:
    """Append one immutable scene-description version.

    Scenario prose and scene descriptions are independent texts (D01).
    Editing a scene therefore never appends, activates or otherwise
    changes a whole-script version. Existing links stay attached to the
    scene and are only flagged for review.
    """

    _require_mapping(state, "state")
    scene_id = _require_non_empty_string(scene_id, "scene_id")
    text = _require_non_empty_string(text, "text")
    reason = _require_non_empty_string(reason, "reason")
    author = _require_non_empty_string(author, "author")
    scenes = state.get("scenes")
    if not isinstance(scenes, list):
        raise DomainValidationError("scenes must be a list")
    matches = [scene for scene in scenes if scene.get("scene_id") == scene_id]
    if len(matches) != 1:
        raise DomainValidationError(f"unknown or duplicate scene_id: {scene_id}")

    candidate = copy.deepcopy(state)
    candidate_scene = next(
        scene for scene in candidate["scenes"] if scene.get("scene_id") == scene_id
    )
    block = _require_mapping(
        candidate_scene.get("script_block"), "scene.script_block"
    )
    versions = block.get("versions")
    if not isinstance(versions, list) or not all(
        isinstance(version, dict) for version in versions
    ):
        raise DomainValidationError("scene.script_block.versions must be a list")
    active = block.get("active_version_id")
    known_ids = [version.get("version_id") for version in versions]
    if active is not None and active not in known_ids:
        raise DomainValidationError(
            "scene.script_block.active_version_id must reference history"
        )
    block_version_id = f"{scene_id}-block-v{len(versions) + 1}"
    if block_version_id in known_ids:
        raise DomainValidationError("next scene block version id already exists")
    block_version = {
        "version_id": block_version_id,
        "parent_version_id": active,
        "text": text,
        "reason": reason,
        "author": author,
    }
    versions.append(copy.deepcopy(block_version))
    block["active_version_id"] = block_version_id

    links = candidate_scene.get("links", {})
    if not isinstance(links, dict):
        raise DomainValidationError("scene.links must be an object")
    if any(value for value in links.values()):
        candidate_scene["linkage_status"] = "review_linkage"

    state.clear()
    state.update(candidate)
    return copy.deepcopy(block_version)


def edit_scene_field(
    state: dict,
    scene_id: str,
    field: str,
    value,
    reason: str,
    author: str,
) -> dict:
    """Apply one stage-1 scene edit for both dashboard and chat doors."""

    view = derive_view_stage(state)
    if view["current_stage"] != "scenario":
        raise DomainValidationError("scene fields can be edited only at scenario")
    if field not in {"text", "title", "duration_ms"}:
        raise DomainValidationError("scene edit field must be text, title or duration_ms")
    scene_id = _require_non_empty_string(scene_id, "scene_id")
    scenes = state.get("scenes")
    if not isinstance(scenes, list):
        raise DomainValidationError("scenes must be a list")
    matches = [scene for scene in scenes if scene.get("scene_id") == scene_id]
    if len(matches) != 1:
        raise DomainValidationError(f"unknown or duplicate scene_id: {scene_id}")

    result = {"field": field}
    if field == "text":
        version = append_scene_block_version(state, scene_id, value, reason, author)
        result["version_id"] = version["version_id"]
    elif field == "title":
        if not isinstance(value, str) or len(value) > 200:
            raise DomainValidationError("scene title must be a string of at most 200 characters")
        matches[0]["title"] = value
    else:
        project = _require_mapping(state.get("project"), "project")
        if project.get("type") == "photo":
            raise DomainValidationError("photo scenes do not have duration_ms")
        duration = _scene_duration_ms({"duration_ms": value}, "scene")
        matches[0]["duration_ms"] = duration
        recompute_scene_ranges(state)

    append_history(
        state,
        "you",
        "scene-edited",
        "scenario",
        scene_id=scene_id,
        field="duration" if field == "duration_ms" else field,
    )
    return result


def add_scene(state: dict, author: str) -> dict:
    """Append one deterministic default scene for dashboard or chat."""

    if derive_view_stage(state)["current_stage"] != "scenario":
        raise DomainValidationError("scenes can be added only at scenario")
    scenes = state.setdefault("scenes", [])
    if not isinstance(scenes, list) or not all(isinstance(scene, dict) for scene in scenes):
        raise DomainValidationError("scenes must be a list of objects")
    used = {scene.get("scene_id") for scene in scenes}
    number = 1
    while f"scene-{number}" in used:
        number += 1
    scene_id = f"scene-{number}"
    block_version_id = f"{scene_id}-block-v1"
    scene = {
        "scene_id": scene_id,
        "order": len(scenes) + 1,
        "title": f"Кадр {number}",
        "script_block": {
            "active_version_id": block_version_id,
            "versions": [
                {
                    "version_id": block_version_id,
                    "parent_version_id": None,
                    "text": "",
                    "reason": "scene add",
                    "author": author,
                }
            ],
        },
        "links": {},
        "linkage_status": "current",
    }
    if _require_mapping(state.get("project"), "project").get("type") != "photo":
        scene["duration_ms"] = 4000
        scene["need_first"] = False
        scene["need_last"] = False
        scene["video_mode"] = "references"
    scenes.append(scene)
    recompute_scene_ranges(state)
    append_history(state, "you", "scene-added", "scenario")
    return copy.deepcopy(scene)


_PROMPT_LIST_KEY = "image_prompts"
_PROMPT_LINK_KEY = "image_prompt_version_id"


def _group_version_ids(items, group_key, group_value) -> set[str]:
    """Every `-vN` id already used by `group_value`'s group in `items`."""

    return {
        item["version_id"]
        for item in items
        if item.get(group_key) == group_value
        and isinstance(item.get("version_id"), str)
        and item["version_id"]
    }


def _lowest_free_version_id(group_value, taken) -> str:
    """The lowest `{group_value}-vN` not already in `taken`.

    Used only to retrofit an identity onto a group member that predates
    this call and has no `version_id` of its own yet (see
    `_append_group_version` below) -- filling that one gap is deliberate,
    unlike a brand-new sibling's own number, which never reuses a gap
    (`_next_group_version_id`).
    """

    number = 1
    while f"{group_value}-v{number}" in taken:
        number += 1
    return f"{group_value}-v{number}"


def _next_group_version_id(group_value, taken) -> str:
    """The highest `-vN` already in `taken`, plus one -- never a lower,
    merely-unused slot a gap might leave behind.

    Ticket 12 repair, condition 8: version ids form an append-only causal
    chain (`parent_version_id` names the sibling a version was appended
    beside); if `taken` were `{-v1, -v3}` (say `-v2`'s record were ever
    removed by something outside this module), the lowest-free rule
    `_lowest_free_version_id` uses would hand out `-v2` again for an
    unrelated, later version -- this always grows past the highest number
    actually in use instead, so a new version's number can never collide
    with, or be mistaken for, an older one a gap left behind. With no gap
    at all (the common case, `{-v1}`, `{-v1, -v2}`, ...) this agrees with
    the lowest-free rule exactly, which is why every existing test written
    against the old, always-contiguous-group behavior still passes.
    """

    highest = 0
    prefix = f"{group_value}-v"
    for version_id in taken:
        suffix = version_id[len(prefix):] if version_id.startswith(prefix) else ""
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{group_value}-v{highest + 1}"


def _append_group_version(
    state: dict,
    current: dict,
    extra_fields: dict,
    *,
    group_key: str,
    list_key: str,
    link_key: str,
) -> dict:
    """Append an immutable new version beside `current` in its own group
    (`state[list_key]`, whose members share one `group_key` value -- a
    prompt's `prompt_id` or a result's `result_id`), and repoint the
    owning scene's single `link_key` link at it.

    Ticket 12 repair, condition 8: the one function `append_prompt_
    version` and `append_result_version` below both call for their
    shared half -- numbering a new sibling and relinking the scene that
    pointed at the version it was appended beside. Before this repair
    each kept its own, separately hand-written copy of that exact
    algorithm (a `next_available_version_id` closure plus a relinking
    loop, byte-for-byte the same shape twice); a dead third copy,
    `authoring_support.next_group_version_id`, claimed callers that in
    fact never called it and has been removed. `extra_fields` is
    whatever is specific to a prompt (`text`/`reason`/`author`/`status`)
    or a result (`asset_id`/`status`/`caption`) -- the envelope around it
    (`group_key`, `version_id`, `parent_version_id`, and `scene_id`
    copied from `current` only when `current` actually has one) is built
    here, identically for both, so a prompt and a result version can
    never diverge on how either is assigned.

    A prompt/result group has no separate `versions: []` container the
    way `script`/`scene.script_block` do -- every version is its own
    sibling entry in `state[list_key]` sharing `group_key`. Editing one
    appends a new sibling (existing entries, including `current`, are
    never rewritten) and repoints every scene whose `links[link_key]`
    names the version being edited at the freshly appended one, without
    a review flag, since nothing about a *scene's own* content changed
    here -- only which version of the prompt/result it currently points
    at.

    `current` is the exact group member being edited, already resolved
    by the caller (`decision_cards.resolve_card`/`authoring_support.
    resolve_current_group_member`, which is what makes this safe when
    the group holds more than one version) -- this function does not
    re-resolve a target from a bare id.

    Two data-integrity rules:

    - Only a `scene_id` actually present on `current` is copied onto the
      new version -- a prompt/result never scene-linked in the first
      place must not gain a materialized `scene_id: null`, which
      `projection._sanitize_prompt`/`_sanitize_result` (an allowlisted
      string field) would reject outright, taking the whole snapshot
      down with it.
    - `current` missing its own `version_id` -- the first edit ever made
      to a still-unversioned group member -- is assigned the lowest
      `-vN` not already used by any member of its group, *before* the
      new sibling's own number is computed, so `parent_version_id` names
      it instead of `None` and it stays individually addressable
      afterwards. The group is never assumed to be a singleton: a
      sibling may already own `-v1` (e.g. from an earlier,
      independently-versioned edit), so both the id assigned here and
      the new version's own id skip every `-vN` already taken by any
      current member of the group, rather than deriving either from the
      group's size alone. Scene links still name the bare `group_key`
      value at this point (no version existed yet when they were set),
      so relinking below still keys off that value, not the version id
      just assigned to `current`.
    """

    _require_mapping(state, "state")
    _require_mapping(current, "current")
    group_value = _require_non_empty_string(current.get(group_key), f"current.{group_key}")
    items = state.get(list_key)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise DomainValidationError(f"{list_key} must be a list of objects")

    from .domain_positions import group_owner, owner_links, require_position_id
    owner = group_owner(state, group_value, list_key)
    if owner is not None:
        side = "prompt" if group_key == "prompt_id" else "result"
        link_key = owner[side + "_link"]
    taken = _group_version_ids(items, group_key, group_value)
    current_version_id = current.get("version_id")
    if isinstance(current_version_id, str) and current_version_id:
        old_identity = current_version_id
    else:
        # The source has no identity of its own yet -- give it the lowest
        # id not already used in its group, before it gets a sibling,
        # instead of leaving it an unaddressable second member of a
        # now-ambiguous group. Never assumes `-v1` is free: a sibling may
        # already own it.
        old_identity = group_value
        current_version_id = _lowest_free_version_id(group_value, taken)
        taken = taken | {current_version_id}
    new_version_id = _next_group_version_id(group_value, taken)

    if owner is not None:
        require_position_id(current_version_id)
        require_position_id(new_version_id)
    # Validate both identities before retrofitting a legacy source version.
    current["version_id"] = current_version_id
    new_version = {
        group_key: group_value,
        "version_id": new_version_id,
        "parent_version_id": current["version_id"],
        **extra_fields,
    }
    if "scene_id" in current:
        # Copy only a key the source actually has.
        new_version["scene_id"] = current["scene_id"]
    items.append(copy.deepcopy(new_version))

    if owner is not None:
        links = owner_links(state, owner, create=True)
        if links.get(link_key) == old_identity:
            links[link_key] = new_version_id
        return copy.deepcopy(new_version)

    scenes = state.get("scenes")
    if isinstance(scenes, list):
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            links = scene.get("links")
            if isinstance(links, dict) and links.get(link_key) == old_identity:
                links[link_key] = new_version_id

    return copy.deepcopy(new_version)


def _build_first_group_version(
    group_value: str,
    extra_fields: dict,
    *,
    group_key: str,
    scene_id: str | None = None,
) -> dict:
    """Build a brand-new group's very first version -- the
    `_append_group_version` twin for when there is no existing `current`
    to append beside at all, since that function's whole contract
    (numbering against an already-populated group, relinking whichever
    scene pointed at the sibling being edited) assumes one already exists
    in `state[list_key]`.

    Ticket 17 condition 5: `authoring_scenes.add_prompt_version` and
    `authoring_media.add_result_version` used to each hand-roll this
    envelope separately for their own "no existing group yet" branch --
    and had quietly diverged doing it: a prompt's first version carried
    `parent_version_id: None`, a result's omitted the key entirely, for no
    reason tied to any actual rule difference between the two (confirmed
    against `projection._PROMPT_SOURCE_KEYS`/`_RESULT_KEYS`, which already
    allowlist `parent_version_id` as an optional field on either, and
    against every other module in this package, none of which branches on
    whether the key is present at all). Always `{group_value}-v1` -- the
    lowest possible id for a group that, by definition, has no other
    member yet -- never `_lowest_free_version_id`/`_next_group_version_id`,
    which exist only to reconcile against an already-populated group's own
    history. `scene_id` is copied only when the caller actually has one,
    mirroring `_append_group_version`'s own "only a key the source
    actually has" rule -- a prompt/result never scene-linked in the first
    place must not gain a materialized `scene_id: null`, which
    `projection._sanitize_prompt`/`_sanitize_result` (an allowlisted
    *string* field) would reject outright.
    """

    version = {
        group_key: group_value,
        "version_id": f"{group_value}-v1",
        "parent_version_id": None,
        **extra_fields,
    }
    if scene_id is not None:
        version["scene_id"] = scene_id
    return version


def start_prompt_version(
    group_value: str,
    text: str,
    reason: str,
    author: str,
    *,
    scene_id: str | None = None,
    basis: dict | None = None,
) -> dict:
    """Build the first version of a brand-new prompt group -- the
    `append_prompt_version` twin for when there is no existing sibling to
    append beside (ticket 17 condition 5). Same field validation and
    `extra_fields` shape as `append_prompt_version`, so a prompt's first
    and every later version are built by rules that can never quietly
    diverge on what a "prompt version" contains.
    """

    text = _require_non_empty_string(text, "text")
    reason = _require_non_empty_string(reason, "reason")
    author = _require_non_empty_string(author, "author")
    extra_fields = {"text": text, "reason": reason, "author": author, "status": "pending"}
    if basis is not None:
        extra_fields["basis"] = copy.deepcopy(_require_mapping(basis, "basis"))
    return _build_first_group_version(group_value, extra_fields, group_key="prompt_id", scene_id=scene_id)


def start_result_version(
    group_value: str,
    asset_id: str,
    *,
    scene_id: str | None = None,
    caption: str | None = None,
) -> dict:
    """Build the first version of a brand-new result group -- the
    `append_result_version` twin for when there is no existing sibling to
    append beside (ticket 17 condition 5). Same field validation and
    `extra_fields` shape as `append_result_version`, so a result's first
    and every later version are built by rules that can never quietly
    diverge on what a "result version" contains.
    """

    asset_id = _require_non_empty_string(asset_id, "asset_id")
    if caption is not None and not isinstance(caption, str):
        raise DomainValidationError("caption must be a string")
    extra_fields = {"asset_id": asset_id, "status": "ready"}
    if caption is not None:
        extra_fields["caption"] = caption
    return _build_first_group_version(group_value, extra_fields, group_key="result_id", scene_id=scene_id)


def append_prompt_version(
    state: dict,
    current: dict,
    text: str,
    reason: str,
    author: str,
    *,
    list_key: str = _PROMPT_LIST_KEY,
    link_key: str = _PROMPT_LINK_KEY,
    basis: dict | None = None,
) -> dict:
    """Append an immutable new prompt version beside `current`, through
    the shared `_append_group_version` (ticket 12 repair, condition 8).

    `list_key`/`link_key` default to `_PROMPT_LIST_KEY`/`_PROMPT_LINK_KEY`
    (`image_prompts`/`image_prompt_version_id`) so every existing caller
    (`decision_planners.plan_edit`, which only ever edits an `image_plan`
    card) is unaffected. Repair, 2026-09-17 (ticket 12, condition 13):
    `studio.authoring.add_prompt_version` passes `motion_prompts`/
    `motion_prompt_version_id` explicitly for a motion prompt's own
    group, so both prompt kinds share this one versioning rule instead of
    `authoring.py` re-implementing it a second time.
    """

    text = _require_non_empty_string(text, "text")
    reason = _require_non_empty_string(reason, "reason")
    author = _require_non_empty_string(author, "author")
    extra_fields = {"text": text, "reason": reason, "author": author, "status": "pending"}
    if basis is not None:
        extra_fields["basis"] = copy.deepcopy(_require_mapping(basis, "basis"))
    return _append_group_version(
        state, current, extra_fields, group_key="prompt_id", list_key=list_key, link_key=link_key
    )


def append_result_version(
    state: dict,
    current: dict,
    asset_id: str,
    *,
    list_key: str,
    link_key: str,
    caption: str | None = None,
) -> dict:
    """Append an immutable new result version beside `current`, in
    `state[list_key]` (`image_results`/`video_results`), through the
    shared `_append_group_version` (ticket 12 repair, condition 8) --
    the result twin of `append_prompt_version` above. Unlike a prompt, a
    result carries no `text`/`reason`/`author`, only the asset it points
    at and an optional `caption`; that is the entire difference between
    the two, now expressed as `extra_fields` rather than as a second,
    separately hand-written numbering/relinking algorithm.
    """

    asset_id = _require_non_empty_string(asset_id, "asset_id")
    if caption is not None and not isinstance(caption, str):
        raise DomainValidationError("caption must be a string")
    extra_fields = {"asset_id": asset_id, "status": "ready"}
    if caption is not None:
        extra_fields["caption"] = caption
    return _append_group_version(
        state, current, extra_fields, group_key="result_id", list_key=list_key, link_key=link_key
    )


def derive_positions(state: dict) -> list[dict]:
    """Public domain entry: all generation positions, with derived statuses."""
    from .domain_positions import derive_positions as derive
    return derive(state)


def position_specs(state: dict, *, include_inactive: bool = False) -> list[dict]:
    """Public domain entry for prompt/result owner specifications."""
    from .domain_positions import position_specs as specs
    return specs(state, include_inactive=include_inactive)

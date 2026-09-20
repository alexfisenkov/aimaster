"""Strict browser-safe projection of creator-studio state."""

from __future__ import annotations

import copy
import re

from .decision_cards import (
    PROMPT_COLLECTIONS,
    RESULT_COLLECTIONS,
    STAGE_COLLECTIONS,
    card_identity,
)
from .domain import (
    PHOTO_STAGES,
    VIDEO_STAGES,
    DomainValidationError,
    _stage_sequence,
    derive_project_status,
    derive_view_stage,
    compute_prompt_stale,
    frame_basis,
    validate_history,
)


PUBLIC_KEYS = {
    "revision",
    "projects",
    "active_project",
    "view_stage",
    "questions",
    "actions",
}

# `applied_action_ids` is `decisions.DecisionWorker`'s own crash-recovery
# marker: allowlisted here purely so a project that has ever recorded it
# never fails `build_snapshot`, but never threaded into any nested
# sanitizer below -- it never appears in a snapshot. `stage_decisions` is
# the shared append-only history every milestone decision
# (`approve-scenario`, and `approve`/`reject` naming a stage) writes to;
# unlike `applied_action_ids`, `build_snapshot` below *does* render it --
# filtered to only a stage the project has actually reached -- into
# `active_project.stage_decisions`. Rendering that history in the
# dashboard UI itself is task 08's job, not this module's.
#
# Keys and stage names of the stage model this build no longer has (G12: the
# `qa` stage is gone) stay *readable*: a project file written before that
# still carries a `qa` state key and `stage_decisions` entries for stage
# `qa`, and neither may turn its snapshot -- or a later chat write, which
# runs `validate_state` -- into an error. They are only ever read past:
# `build_snapshot` never projects them (no reached stage is named `qa`), no
# writer produces them, and their content is not looked at, so a legacy
# value can neither leak nor break anything. Both sets are named here so the
# tolerance is one visible, testable decision rather than a stray literal.
_LEGACY_STATE_KEYS = frozenset({"qa"})
_LEGACY_STAGE_NAMES = frozenset({"qa"})
_STATE_KEYS = {
    "revision",
    "project",
    "milestones",
    "script",
    "scenes",
    "questions",
    "actions",
    "blocking_question_ids",
    "image_prompts",
    "references",
    "image_results",
    "motion_prompts",
    "video_results",
    "oneshot",
    "audio_layers",
    "audio_prompts",
    "audio_results",
    "assembly",
    "applied_action_ids",
    "stage_decisions",
    "history",
    "gen_mode",
} | _LEGACY_STATE_KEYS
_PROJECT_KEYS = {"id", "title", "type", "mode", "status", "order", "revision", "stage"}
_SCRIPT_KEYS = {"active_version_id", "versions"}
# Legacy scene-block versions may still carry `script_version_id` from
# the pre-D01 aggregate-script model. New writers no longer emit it, but
# the source/public allowlist keeps old projects readable and reviewable.
_VERSION_SOURCE_KEYS = {
    "version_id",
    "parent_version_id",
    "text",
    "reason",
    "author",
    "script_version_id",
}
_VERSION_PUBLIC_KEYS = _VERSION_SOURCE_KEYS - {"author"}
_SCENE_KEYS = {
    "scene_id",
    "order",
    "title",
    "duration_ms",
    "start_ms",
    "end_ms",
    "content",
    "script_block",
    "links",
    "linkage_status",
    "overlap_scene_ids",
    "need_first",
    "need_last",
    "video_mode",
}
# Ticket 15 repair, поправка оркестратора 8: the reduced scene view stage
# 1 exposes after a reopen (G05) -- identity, order, a video scene's own
# time range, its script block (active text and every version) and
# `linkage_status`. Never `links` (nothing at `image_plan` or later has
# been reached yet, so a link into that material must not leak either)
# and never `content`/`overlap_scene_ids`, which stage 1 has no use for.
# `_sanitize_scenario_stage_scene` below filters `_sanitize_scene`'s own,
# fully-validated output down to this set -- the full sanitizer still
# runs first, so a malformed scene fails exactly as loudly at `scenario`
# as it already does at `image_plan`, never discovered later once the
# project happens to reach that stage for real.
_SCENARIO_STAGE_SCENE_KEYS = {
    "scene_id",
    "order",
    "title",
    "duration_ms",
    "start_ms",
    "end_ms",
    "script_block",
    "linkage_status",
}
_LINK_KEYS = {
    "prompt_version_ids",
    "result_ids",
    "reference_ids",
    "image_prompt_version_id",
    "image_result_id",
    "motion_prompt_version_id",
    "video_result_id",
    "script_block_version_id",
    "first_frame_prompt_version_id",
    "first_frame_result_id",
    "last_frame_prompt_version_id",
    "last_frame_result_id",
}
_PROMPT_SOURCE_KEYS = {
    "prompt_id",
    "version_id",
    "parent_version_id",
    "scene_id",
    "text",
    "reason",
    "author",
    "status",
    "decisions",
    "basis",
}
_PROMPT_PUBLIC_KEYS = _PROMPT_SOURCE_KEYS - {"author", "basis"}
_REFERENCE_KEYS = {
    "links",
    "reference_id",
    "role",
    "tag",
    "label",
    "asset_id",
    "source",
    "local",
    "scene_id",
    "voice",
}
_REFERENCE_VOICE_KEYS = {"enabled", "tag", "asset_id"}
_REFERENCE_KIND_BY_ROLE = {
    "character": "character",
    "object": "product",
    "product": "product",
    "location": "location",
    "style": "style",
}
_REFERENCE_SOURCES = {"upload", "generate"}
_RESULT_KEYS = {
    "result_id",
    "scene_id",
    "asset_id",
    "status",
    "version_id",
    # Ticket 12 repair, condition 13: `domain.append_result_version` gives
    # a versioned result the same `parent_version_id` a prompt version
    # already carries (see `_VERSION_SOURCE_KEYS`) -- allowlisted here so
    # a chat-authored second result version does not fail
    # `build_snapshot` outright the first time one is written.
    "parent_version_id",
    "caption",
    "decision",
    "hidden",
    "retired",
    "decisions",
}
# `retired` marks a result excluded from the active flow without touching
# its `decision`; `decisions` is the append-only `{decision, comment}`
# history `approve`/`reject` record on a prompt or a result (see
# `_DECISION_ENTRY_KEYS` below). Neither carries an author or a timestamp
# -- the comment is the user's own text, nothing else about who or when.
_DECISION_ENTRY_KEYS = {"decision", "comment"}
_DECISION_VALUES = {"approved", "rejected"}
# Every milestone-level decision (`approve-scenario`, and `approve`/
# `reject` naming a milestone stage as `target_id` -- `scenario` through
# `assembly`) shares one history, `state["stage_decisions"]`, in one entry
# shape: no per-stage container, no author, no timestamp. Projected only
# for a stage the project has actually reached (`build_snapshot` filters
# by `completed_stages`/`current_stage`) -- never a future one.
_STAGE_DECISION_KEYS = {"stage", "decision", "comment"}
# Ticket 15 (G05): `reopen-scenario` writes `{"stage": "scenario",
# "decision": "reopened", ...}` to that same `stage_decisions` history --
# a *stage*-level value only. A prompt's/result's own card-level
# `decisions[]` (`_DECISION_ENTRY_KEYS`/`_DECISION_VALUES` above) never
# gets "reopened": nothing in this codebase ever writes it there, and
# "reopened" naming a single prompt/result version would not mean
# anything -- only the whole scenario milestone can be reopened. Two
# separate constants, not one shared set, so a card sanitizer and the
# stage sanitizer can never silently drift onto the same allowed values
# by accident (see `_sanitize_decision_entry`/`_sanitize_stage_decision`
# below, the only two callers).
_STAGE_DECISION_VALUES = _DECISION_VALUES | {"reopened"}
_MILESTONE_STAGE_NAMES = set(VIDEO_STAGES) | set(PHOTO_STAGES) | _LEGACY_STAGE_NAMES
_QUESTION_SOURCE_KEYS = {
    "question_id",
    "project_id",
    "revision",
    "text",
    "kind",
    "options",
    "allow_custom",
    "required",
    "validation",
    "expires_at",
    "resume_token",
    "status",
    "answer",
    "answered_by",
}
_QUESTION_PUBLIC_KEYS = _QUESTION_SOURCE_KEYS - {"resume_token", "answered_by"}
_OPTION_KEYS = {"id", "label", "description"}
_VALIDATION_KEYS = {
    "min_length",
    "max_length",
    "min_items",
    "max_items",
    "pattern",
    "allowed_values",
}
_ACTION_SOURCE_KEYS = {
    "action_id",
    "project_id",
    "revision",
    "action_type",
    "target_id",
    "status",
    "public_result",
    "message",
}
_PUBLIC_RESULT_KEYS = {
    "status",
    "message",
    "result_id",
    "asset_id",
    "asset_url",
    "question_id",
    "action_id",
}
_ACTION_TYPES = {
    "approve-scenario",
    "revise-scenario",
    "continue-in-chat",
    "approve",
    "reject",
    "edit",
    "vary",
    "regenerate",
    "hide",
    "unhide",
    "retire",
    "restore",
    "reorder",
    "scene-add",
    "reference-add",
    "reference-edit",
    "scene-reference-toggle",
    "scene-frame-plan",
    "set-gen-mode",
    "set-video-mode",
    "set-mode",
    "generate",
    "prompts-generate",
    "prompt-refresh",
    "assemble",
    # Ticket 15 (G05) -- kept in lockstep with `ledger.ACTION_TYPES`.
    "reopen-scenario",
}
_ACTION_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "needs_chat",
    "needs_chat_setup",
    "outcome_unknown",
}
_PUBLIC_RESULT_STATUSES = _ACTION_STATUSES | {
    "pending",
    "ready",
    "approved",
    "rejected",
    "available",
    "unavailable",
    "complete",
}
_LINKAGE_STATUSES = {"current", "review_linkage"}
_FORBIDDEN_PUBLIC_RESULT_VALUE = re.compile(
    r"provider|mcp|model|auth|cost|quota|token|path|provenance|credential|cookie|secret|syntx|magnific",
    re.IGNORECASE,
)
_EVENT_KEYS = {"event_id", "revision", "event_type", "payload"}
_EVENT_TYPES = {
    "project_updated",
    "action_updated",
    "question_updated",
    "snapshot_required",
}
_EVENT_PAYLOAD_KEYS = {
    "project_id",
    "action_id",
    "question_id",
    "target_id",
    "status",
    "message",
    "current_stage",
    "stage_revision",
    "answer",
    "public_result",
    "reason",
}


class ProjectionError(ValueError):
    """Input cannot be represented by the public browser contract."""


class ActionTargetError(ProjectionError):
    """Ambiguous or invalid typed target; never the permissive legacy None case."""


def _object(value, context):
    if not isinstance(value, dict):
        raise ProjectionError(f"{context} must be an object")
    return value


def _list(value, context):
    if not isinstance(value, list):
        raise ProjectionError(f"{context} must be a list")
    return value


def _exact_keys(value, allowed, context):
    value = _object(value, context)
    unknown = set(value) - allowed
    if unknown:
        raise ProjectionError(f"unknown {context} keys: {sorted(unknown)!r}")
    return value


def _string(value, context, *, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        qualifier = "" if allow_empty else "non-empty "
        raise ProjectionError(f"{context} must be a {qualifier}string")
    return value


def _optional_string(value, context):
    if value is None:
        return None
    return _string(value, context)


def _non_negative_integer(value, context):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProjectionError(f"{context} must be a non-negative integer")
    return value


def _boolean(value, context):
    if not isinstance(value, bool):
        raise ProjectionError(f"{context} must be a boolean")
    return value


def _enum(value, allowed, context):
    value = _string(value, context)
    if value not in allowed:
        raise ProjectionError(f"{context} has an unsupported value")
    return value


def _string_list(value, context):
    return [
        _string(item, f"{context}[{index}]")
        for index, item in enumerate(_list(value, context))
    ]


def _safe_system_text(value, context):
    value = _string(value, context, allow_empty=True)
    if _FORBIDDEN_PUBLIC_RESULT_VALUE.search(value):
        raise ProjectionError(f"{context} contains private routing data")
    return value


def _sanitize_project(project, context="project"):
    project = _exact_keys(project, _PROJECT_KEYS, context)
    result = {}
    for key, value in project.items():
        field = f"{context}.{key}"
        if key == "revision":
            result[key] = _non_negative_integer(value, field)
        elif key == "order":
            result[key] = _non_negative_integer(value, field)
        elif key == "type":
            result[key] = _enum(value, {"photo", "video", "mixed"}, field)
        elif key == "stage":
            result[key] = _enum(value, set(PHOTO_STAGES + VIDEO_STAGES), field)
        else:
            result[key] = _string(value, field)
    return result


def _sanitize_script(script, context="script", *, allow_empty_text=False):
    script = _exact_keys(script, _SCRIPT_KEYS, context)
    versions = []
    for index, version in enumerate(_list(script.get("versions", []), f"{context}.versions")):
        version_context = f"{context}.versions[{index}]"
        version = _exact_keys(version, _VERSION_SOURCE_KEYS, version_context)
        sanitized = {}
        for key, value in version.items():
            if key not in _VERSION_PUBLIC_KEYS:
                continue
            field = f"{version_context}.{key}"
            if key == "parent_version_id":
                sanitized[key] = _optional_string(value, field)
            elif key == "text":
                sanitized[key] = _string(value, field, allow_empty=allow_empty_text)
            else:
                sanitized[key] = _string(value, field)
        versions.append(sanitized)
    active_version_id = _optional_string(
        script.get("active_version_id"), f"{context}.active_version_id"
    )
    return {
        "active_version_id": active_version_id,
        "versions": versions,
    }


def _sanitize_scene(scene, index, *, project_type, hidden_link_keys=frozenset()):
    context = f"scenes[{index}]"
    scene = _exact_keys(scene, _SCENE_KEYS, context)
    result = {}
    for key, value in scene.items():
        field = f"{context}.{key}"
        if key in {"scene_id"}:
            result[key] = _string(value, field)
        elif key in {"order", "duration_ms", "start_ms", "end_ms"}:
            result[key] = _non_negative_integer(value, field)
        elif key in {"need_first", "need_last"}:
            if not isinstance(value, bool):
                raise ProjectionError(f"{field} must be a boolean")
            result[key] = value
        elif key == "video_mode":
            result[key] = _enum(value, {"first", "firstlast", "references"}, field)
        elif key == "title":
            result[key] = _string(value, field, allow_empty=True)
            if len(result[key]) > 200:
                raise ProjectionError(f"{field} must be at most 200 characters")
        elif key == "content":
            result[key] = _string(value, field, allow_empty=True)
        elif key == "linkage_status":
            result[key] = _enum(value, _LINKAGE_STATUSES, field)
        elif key == "overlap_scene_ids":
            _string_list(value, field)  # legacy source key: validate, never project
    result.setdefault("title", f"Кадр {result.get('order', index + 1)}")
    if project_type == "photo":
        if any(
            key in result
            for key in (
                "duration_ms",
                "start_ms",
                "end_ms",
                "need_first",
                "need_last",
                "video_mode",
            )
        ):
            raise ProjectionError(f"{context} must not contain timeline fields for photo")
    else:
        if "duration_ms" not in result:
            if "start_ms" not in result or "end_ms" not in result:
                raise ProjectionError(f"{context} requires duration_ms")
            result["duration_ms"] = result["end_ms"] - result["start_ms"]
        duration = result["duration_ms"]
        if duration < 1000 or duration % 1000 != 0:
            raise ProjectionError(
                f"{context}.duration_ms must be a multiple of 1000 and at least 1000"
            )
        try:
            result.update(frame_basis(scene))
        except DomainValidationError as error:
            raise ProjectionError(str(error)) from error
    if "start_ms" in result and "end_ms" in result and result["end_ms"] <= result["start_ms"]:
        raise ProjectionError(f"{context}.end_ms must be greater than start_ms")
    if "script_block" in scene:
        result["script_block"] = _sanitize_script(
            scene["script_block"], f"{context}.script_block", allow_empty_text=True
        )
    if "links" in scene:
        links = _exact_keys(scene["links"], _LINK_KEYS, f"{context}.links")
        result["links"] = {}
        for key, value in links.items():
            # Ticket 12 repair, condition 4: a link written ahead of its
            # own stage (chat is free to write `result add-version
            # --kind video` while the project is still at `image_plan`,
            # for example) must not leak into the snapshot's `scenes[]`
            # before that stage is reached, even though the *scene* it
            # belongs to is already visible and the top-level
            # `image_results`/`motion_prompts`/`video_results` collection
            # this id points into is correctly hidden by the `stage_index`
            # guards below. `hidden_link_keys` (computed once in
            # `build_snapshot`) is the one place that decides this, so a
            # future stage-gated key only needs adding there.
            if key in hidden_link_keys:
                continue
            field = f"{context}.links.{key}"
            result["links"][key] = (
                _string_list(value, field)
                if key.endswith("_ids")
                else _optional_string(value, field)
            )
    return result


def _sanitize_scenario_stage_scene(scene, index, *, project_type):
    """Ticket 15 repair, поправка оркестратора 8: stage 1's own reduced
    scene view -- everything `_sanitize_scene` above validates, kept only
    where its key is one of `_SCENARIO_STAGE_SCENE_KEYS`. Runs the full
    sanitizer first (no `hidden_link_keys`, so `links` is validated too
    if present -- the same structural check every other stage's scene
    already gets), then filters the *output*: a malformed scene still
    fails loudly here exactly as it would at `image_plan`, and `links`
    itself is dropped from what stage 1 ever sees, never partially
    rendered.
    """

    sanitized = _sanitize_scene(scene, index, project_type=project_type)
    return {key: value for key, value in sanitized.items() if key in _SCENARIO_STAGE_SCENE_KEYS}


def _sanitize_decision_entry(entry, context):
    entry = _exact_keys(entry, _DECISION_ENTRY_KEYS, context)
    result = {}
    for key, value in entry.items():
        field = f"{context}.{key}"
        if key == "decision":
            result[key] = _enum(value, _DECISION_VALUES, field)
        else:
            result[key] = _string(value, field, allow_empty=True)
    return result


def _sanitize_decisions(value, context):
    return [
        _sanitize_decision_entry(entry, f"{context}[{index}]")
        for index, entry in enumerate(_list(value, context))
    ]


def _sanitize_stage_decision(entry, context):
    entry = _exact_keys(entry, _STAGE_DECISION_KEYS, context)
    # Ticket 15 repair, craft finding 8: `_STAGE_DECISION_VALUES` allows
    # "reopened" as a *value*, and `_MILESTONE_STAGE_NAMES` allows every
    # stage as a *stage* -- checked independently below, so neither alone
    # stops `{"stage": "image_plan", "decision": "reopened"}` from passing.
    # Only `reopen-scenario` ever writes "reopened", and it always pairs
    # it with `stage: "scenario"` (`decision_stages.build_reopen_
    # mutation`) -- nothing else in this domain can be "reopened", so a
    # different stage naming it is not a shape this build ever produces
    # legitimately.
    if entry.get("decision") == "reopened" and entry.get("stage") != "scenario":
        raise ProjectionError(
            f"{context}.decision 'reopened' is only valid for stage 'scenario'"
        )
    result = {}
    for key, value in entry.items():
        field = f"{context}.{key}"
        if key == "stage":
            result[key] = _enum(value, _MILESTONE_STAGE_NAMES, field)
        elif key == "decision":
            result[key] = _enum(value, _STAGE_DECISION_VALUES, field)
        else:
            result[key] = _string(value, field, allow_empty=True)
    return result


_NO_DERIVED_STALE = object()


def _sanitize_prompt(prompt, context, *, stale=_NO_DERIVED_STALE):
    prompt = _exact_keys(prompt, _PROMPT_SOURCE_KEYS, context)
    result = {}
    for key, value in prompt.items():
        if key not in _PROMPT_PUBLIC_KEYS:
            if key == "basis" and not isinstance(value, dict):
                raise ProjectionError(f"{context}.basis must be an object")
            continue
        field = f"{context}.{key}"
        if key == "parent_version_id":
            result[key] = _optional_string(value, field)
        elif key == "decisions":
            result[key] = _sanitize_decisions(value, field)
        else:
            result[key] = _string(value, field, allow_empty=key == "text")
    if stale is not _NO_DERIVED_STALE:
        if not isinstance(stale, bool):
            raise ProjectionError(f"{context}.stale must be a boolean")
        result["stale"] = stale
    return result


def _current_prompt_staleness(state):
    """Map only owner-linked current prompt versions to derived stale flags."""
    from .domain_positions import current_member, position_specs
    stale_by_version = {}
    try:
        for spec in position_specs(state, include_inactive=True):
            prompt = current_member(state, spec, "prompt", missing_ok=True)
            if prompt is None:
                continue
            identity = prompt.get("version_id", prompt.get("prompt_id"))
            if not isinstance(identity, str) or not identity:
                raise DomainValidationError("current prompt has no identity")
            key = (spec["prompt_collection"], identity)
            stale_by_version[key] = stale_by_version.get(key, False) or compute_prompt_stale(
                state, prompt, spec
            )
    except DomainValidationError as error:
        raise ProjectionError(str(error)) from error
    return stale_by_version


def _sanitize_reference(reference, context, asset_url, *, hidden_link_keys=frozenset()):
    reference = _exact_keys(reference, _REFERENCE_KEYS, context)
    reference_id = _string(reference.get("reference_id"), f"{context}.reference_id")
    role = _string(reference.get("role"), f"{context}.role")
    kind = _REFERENCE_KIND_BY_ROLE.get(role)
    if kind is None:
        raise ProjectionError(f"{context}.role is not supported")
    tag = _string(reference.get("tag", reference_id), f"{context}.tag")
    source = _enum(reference.get("source", "upload"), _REFERENCE_SOURCES, f"{context}.source")
    local = reference.get("local", "scene_id" in reference)
    local = _boolean(local, f"{context}.local")
    result = {
        "reference_id": reference_id,
        "kind": kind,
        "tag": tag,
        "label": _string(reference.get("label", ""), f"{context}.label", allow_empty=True),
        "source": source,
        "local": local,
        "has_asset": "asset_id" in reference,
    }
    if "scene_id" in reference:
        result["scene_id"] = _string(reference["scene_id"], f"{context}.scene_id")
    if "asset_id" in reference:
        result["asset_id"] = _string(reference["asset_id"], f"{context}.asset_id")
        result = _add_asset_url(result, context, asset_url)

    voice = _exact_keys(reference.get("voice", {"enabled": False}), _REFERENCE_VOICE_KEYS, f"{context}.voice")
    clean_voice = {"enabled": _boolean(voice.get("enabled"), f"{context}.voice.enabled")}
    if "tag" in voice:
        clean_voice["tag"] = _string(voice["tag"], f"{context}.voice.tag")
    if "asset_id" in voice:
        clean_voice["asset_id"] = _string(voice["asset_id"], f"{context}.voice.asset_id")
        clean_voice = _add_asset_url(clean_voice, f"{context}.voice", asset_url)
    result["voice"] = clean_voice
    if "links" in reference:
        result["links"] = _sanitize_owner_links(reference["links"],
            {"image_prompt_version_id", "image_result_id"}, context + ".links", hidden_link_keys)
    return result


def _sanitize_owner_links(links, allowed, context, hidden=frozenset()):
    links = _exact_keys(links, allowed, context)
    clean = {key: _string(value, f"{context}.{key}") for key, value in links.items()}
    return {key: value for key, value in clean.items() if key not in hidden}


def _sanitize_oneshot(value, *, hidden=frozenset()):
    value = _exact_keys(value, {"links"}, "oneshot")
    return {"links": _sanitize_owner_links(value.get("links", {}),
        {"motion_prompt_version_id", "video_result_id"}, "oneshot.links", hidden)}


def _sanitize_audio_layers(value):
    from .domain_positions import AUDIO_LAYERS
    layers = []
    seen = set()
    for item in _list(value, "audio_layers"):
        item = _exact_keys(item, {"layer", "links"}, "audio_layers entry")
        layer = _enum(item.get("layer"), AUDIO_LAYERS, "audio layer")
        if layer in seen:
            raise ProjectionError("duplicate audio layer")
        seen.add(layer)
        layers.append({"layer": layer, "links": _sanitize_owner_links(item.get("links", {}),
            {"audio_prompt_version_id", "audio_result_id"}, "audio layer links")})
    return layers


def _sanitize_result(item, context, asset_url):
    item = _exact_keys(item, _RESULT_KEYS, context)
    result = {}
    for key, value in item.items():
        field = f"{context}.{key}"
        if key in {"hidden", "retired"}:
            result[key] = _boolean(value, field)
        elif key in {"decision", "parent_version_id"}:
            result[key] = _optional_string(value, field)
        elif key == "decisions":
            result[key] = _sanitize_decisions(value, field)
        else:
            result[key] = _string(value, field, allow_empty=key == "caption")
    return _add_asset_url(result, context, asset_url)


def _add_asset_url(result, context, asset_url):
    if "asset_id" in result:
        url = asset_url(result["asset_id"])
        url = _string(url, f"{context}.asset_url")
        if not url.startswith("/assets/") or ".." in url.split("/"):
            raise ProjectionError(f"{context} asset URL must use /assets/{{asset_id}}")
        result["asset_url"] = url
    return result


def _sanitize_question(question, index):
    question = _exact_keys(question, _QUESTION_SOURCE_KEYS, f"questions[{index}]")
    result = {}
    for key, value in question.items():
        if key not in _QUESTION_PUBLIC_KEYS or key in {"options", "validation"}:
            continue
        field = f"questions[{index}].{key}"
        if key == "revision":
            result[key] = _non_negative_integer(value, field)
        elif key in {"allow_custom", "required"}:
            result[key] = _boolean(value, field)
        elif key == "expires_at":
            result[key] = _optional_string(value, field)
        elif key == "answer":
            result[key] = (
                _string_list(value, field)
                if isinstance(value, list)
                else _optional_string(value, field)
            )
        else:
            result[key] = _string(value, field, allow_empty=key == "text")
    if "options" in question:
        result["options"] = [
            {
                key: _string(value, f"questions[{index}].options[{option_index}].{key}", allow_empty=key == "description")
                for key, value in _exact_keys(
                    option,
                    _OPTION_KEYS,
                    f"questions[{index}].options[{option_index}]",
                ).items()
            }
            for option_index, option in enumerate(
                _list(question["options"], f"questions[{index}].options")
            )
        ]
    if "validation" in question:
        validation = _exact_keys(
            question["validation"],
            _VALIDATION_KEYS,
            f"questions[{index}].validation",
        )
        result["validation"] = {}
        for key, value in validation.items():
            field = f"questions[{index}].validation.{key}"
            if key in {"min_length", "max_length", "min_items", "max_items"}:
                result["validation"][key] = _non_negative_integer(value, field)
            elif key == "allowed_values":
                result["validation"][key] = _string_list(value, field)
            else:
                result["validation"][key] = _string(value, field)
    return result


def _sanitize_public_result(value, context):
    value = _exact_keys(value, _PUBLIC_RESULT_KEYS, context)
    result = {}
    for key, item in value.items():
        field = f"{context}.{key}"
        if key == "status":
            result[key] = _enum(item, _PUBLIC_RESULT_STATUSES, field)
        elif key == "asset_url":
            item = _string(item, field)
            if not item.startswith("/assets/") or ".." in item.split("/"):
                raise ProjectionError(f"{field} must use /assets/{{asset_id}}")
            result[key] = item
        else:
            result[key] = _safe_system_text(item, field)
    return result


def _sanitize_action(action, index):
    context = f"actions[{index}]"
    action = _exact_keys(action, _ACTION_SOURCE_KEYS, context)
    result = {}
    for key, value in action.items():
        field = f"{context}.{key}"
        if key == "revision":
            result[key] = _non_negative_integer(value, field)
        elif key == "action_type":
            result[key] = _enum(value, _ACTION_TYPES, field)
        elif key == "status":
            result[key] = _enum(value, _ACTION_STATUSES, field)
        elif key == "public_result":
            result[key] = _sanitize_public_result(value, field)
        elif key == "message":
            result[key] = _safe_system_text(value, field)
        else:
            result[key] = _string(value, field, allow_empty=key == "message")
    return result


def _sanitize_assembly(value, asset_url):
    # `assembly`'s own decision history is not a key here -- it lives in
    # `state["stage_decisions"]`, the same shared history every milestone
    # uses (see `_STAGE_DECISION_KEYS`).
    value = _exact_keys(value, {"status", "asset_id", "summary"}, "assembly")
    result = {}
    for key, item in value.items():
        field = f"assembly.{key}"
        if key == "summary":
            result[key] = _safe_system_text(item, field)
        else:
            result[key] = _string(item, field)
    return _add_asset_url(result, "assembly", asset_url)


# Ticket 15 repair, поправка оркестратора 11: "принадлежность цели
# зависит от типа действия" -- `vary`/`regenerate` (and the other four
# result-only card decisions, `hide`/`unhide`/`retire`/`restore`) only
# ever resolve a target through `decision_cards.resolve_stage_result`,
# never `resolve_stage_prompt` -- so `action_target_stage` below only
# ever searches `image_results`/`video_results` for one of these, never
# `image_prompts`. Every other type that can name a card at all
# (`approve`/`reject`/`edit`) may also resolve a *prompt*
# (`decision_cards.resolve_stage_prompt`), so those additionally search
# `image_prompts`.
_RESULT_ONLY_ACTION_TYPES = frozenset({"vary", "regenerate", "generate", "hide", "unhide", "retire", "restore"})
# Built from `decision_cards`' own groupings of `STAGE_COLLECTIONS`, never a
# literal of collection names of this module's own: a result collection added
# there is searched here in the same edit.
_CARD_RESULT_COLLECTIONS = RESULT_COLLECTIONS
_CARD_PROMPT_AND_RESULT_COLLECTIONS = PROMPT_COLLECTIONS + RESULT_COLLECTIONS


def _stage_reached(sequence, stage_index, stage):
    """Whether `stage` is a step of this project's own `sequence` and the
    project stands on it or past it (`stage_index` is the current stage's
    position in `sequence`).

    The one form every section gate in `build_snapshot` takes. A photo
    project's sequence has no `motion` and no `audio`, so a gate on either
    is simply never open for it -- there is no `sequence.index(...)` on a
    stage the sequence lacks (a bare `ValueError`, a 400 on `GET /snapshot`)
    and no second, hand-written "not a photo" test to keep in step with
    the sequences.
    """

    return stage in sequence and stage_index >= sequence.index(stage)


def action_target_stage(state, action_type, target_id, sequence):
    """Resolve milestone, collection, position or version-group ownership.

    Card/group matches must identify one collection and group. An ambiguous
    legacy ID raises ActionTargetError; snapshots exclude that action and the
    runner's existing ProjectionError guard refuses it and releases its grant.
    Unknown typed IDs fail the same way. Only untyped, unresolved legacy
    conversational targets retain the historical None=current-stage fallback.

    Result-only actions never borrow prompt ownership. New position IDs resolve
    against exact existing owners, not by splitting arbitrary scene IDs.
    """

    if action_type in {"generate", "prompts-generate", "prompt-refresh", "assemble", "set-mode"}:
        from .runner_context import new_action_target_stage
        try:
            return new_action_target_stage(state, action_type, target_id)
        except DomainValidationError as error:
            raise ActionTargetError(str(error)) from error
    if action_type == "reference-add" and target_id == "references":
        return "image_plan"
    if action_type == "set-gen-mode" and target_id == "project":
        return "image_plan"
    if action_type in {"scene-frame-plan", "set-video-mode"}:
        scenes = state.get("scenes", [])
        if isinstance(scenes, list) and any(
            isinstance(scene, dict) and scene.get("scene_id") == target_id
            for scene in scenes
        ):
            return "image_plan" if action_type == "scene-frame-plan" else "motion"
    if action_type in {"reference-edit", "scene-reference-toggle"}:
        references = state.get("references", [])
        if isinstance(references, list) and any(
            isinstance(reference, dict) and reference.get("reference_id") == target_id
            for reference in references
        ):
            return "image_plan"

    result_only = action_type in _RESULT_ONLY_ACTION_TYPES
    if not result_only:
        if target_id in sequence:
            return target_id
        collection = STAGE_COLLECTIONS.get(target_id)
        if collection is not None:
            return collection[0]

    collection_names = _CARD_RESULT_COLLECTIONS if result_only else _CARD_PROMPT_AND_RESULT_COLLECTIONS
    matches = set()
    for collection_name in collection_names:
        stage, id_key = STAGE_COLLECTIONS[collection_name]
        items = state.get(collection_name)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and (card_identity(item, id_key) == target_id or item.get(id_key) == target_id):
                matches.add((collection_name, item.get(id_key), stage))
    if len(matches) > 1:
        raise ActionTargetError("action target is ambiguous across version groups or collections")
    if matches:
        return next(iter(matches))[2]
    if isinstance(target_id, str) and target_id.startswith(("pos:", "prompt:", "result:")):
        if result_only:
            raise ActionTargetError("result-only actions require an existing result card or group")
        from .domain_positions import resolve_position
        try:
            spec = resolve_position(state, target_id)
        except DomainValidationError as error:
            raise ActionTargetError(str(error)) from error
        return STAGE_COLLECTIONS[spec["result_collection"]][0]
    return None


def build_snapshot(
    index: list[dict], state: dict, *, asset_url, pending_actions=None
) -> dict:
    """Build a strict progressive snapshot or fail before returning any data."""

    _list(index, "index")
    state = _exact_keys(state, _STATE_KEYS, "state")
    revision = _non_negative_integer(state.get("revision"), "state.revision")
    projects = [
        _sanitize_project(project, f"projects[{position}]")
        for position, project in enumerate(index)
    ]
    project = _sanitize_project(state.get("project"), "active_project")
    try:
        view_stage = derive_view_stage(state)
    except DomainValidationError as error:
        raise ProjectionError(str(error)) from error
    # Ticket 15 repair, поправка оркестратора 13: read from `domain.
    # _stage_sequence` -- the one place project type picks `PHOTO_STAGES`/
    # `VIDEO_STAGES` -- rather than a second, hand-rolled copy of that
    # same choice here. Never raises in practice at this point: `derive_
    # view_stage` above already called this exact function against this
    # exact `state` and would have raised first if it could.
    sequence = _stage_sequence(state)
    stage_index = sequence.index(view_stage["current_stage"])
    prompt_staleness = _current_prompt_staleness(state)

    def project_prompt(item, collection, position):
        identity = item.get("version_id", item.get("prompt_id")) if isinstance(item, dict) else None
        return _sanitize_prompt(
            item,
            f"{collection}[{position}]",
            stale=prompt_staleness.get((collection, identity), _NO_DERIVED_STALE),
        )

    # `project.status` is reported from the derived stage, not from the
    # stored value (`domain.derive_project_status`): a completed project
    # file of the old stage model has no `audio` milestone, so it now stands
    # on `audio` and must not read `done`. The stored value is rewritten by
    # the next decision (`decision_stages.apply_project_status`); the index
    # entry of this same project is kept in step so one snapshot never
    # disagrees with itself. A state that carries no `status` gets none.
    if "status" in project:
        derived_status = derive_project_status(view_stage)
        project["status"] = derived_status
        for entry in projects:
            if entry.get("id") == project.get("id") and "status" in entry:
                entry["status"] = derived_status

    active_project = copy.deepcopy(project)
    from .stage_readiness import stage_readiness
    position_state = state
    if pending_actions is not None:
        position_state = {**state, "actions": [*state.get("actions", []), *pending_actions]}
    try:
        active_project["stage_readiness"] = stage_readiness(position_state)
    except DomainValidationError as error:
        raise ProjectionError(str(error)) from error
    active_project["stage"] = view_stage["current_stage"]
    # Validate new owners even while hidden; reading never materializes them.
    oneshot = _sanitize_oneshot(state.get("oneshot", {}))
    audio_layers = _sanitize_audio_layers(state.get("audio_layers", []))
    for name in ("audio_prompts", "audio_results"):
        for position, item in enumerate(_list(state.get(name, []), name)):
            if name == "audio_prompts":
                project_prompt(item, name, position)
            else:
                _sanitize_result(item, f"{name}[{position}]", asset_url)
    if _stage_reached(sequence, stage_index, "image_plan") and project["type"] in {"video", "mixed"}:
        active_project["gen_mode"] = _enum(
            state.get("gen_mode", "per_scene"), {"per_scene", "one_shot"}, "gen_mode"
        )
    active_project["script"] = _sanitize_script(state.get("script", {}))
    # `stage_decisions` unifies every milestone's decision history --
    # `scenario` through `assembly` -- in one `{stage, decision, comment}`
    # shape (see `_STAGE_DECISION_KEYS`). Every entry is validated first,
    # exactly like `questions`/`actions` below, then filtered to only a
    # stage the project has actually reached: never a future one, even if
    # canonical state somehow named one.
    all_stage_decisions = [
        _sanitize_stage_decision(entry, f"stage_decisions[{position}]")
        for position, entry in enumerate(
            _list(state.get("stage_decisions", []), "stage_decisions")
        )
    ]
    reached_stages = set(view_stage["completed_stages"]) | {view_stage["current_stage"]}
    active_project["stage_decisions"] = [
        entry for entry in all_stage_decisions if entry["stage"] in reached_stages
    ]
    try:
        reached_history = [
            entry
            for entry in validate_history(state)
            if entry["stage"] in reached_stages
        ]
    except DomainValidationError as error:
        raise ProjectionError(str(error)) from error
    active_project["history"] = sorted(reached_history, key=lambda entry: entry["seq"])[-200:]
    if _stage_reached(sequence, stage_index, "image_plan"):
        # Ticket 12 repair, condition 4: the four kind-specific singular
        # link keys that name a version living in a collection this same
        # `build_snapshot` call is about to gate below by
        # `_stage_reached` -- computed once, from the exact same
        # conditions those gates use, so the two can never disagree about
        # whether a given key's target is visible yet.
        hidden_link_keys = set()
        if not _stage_reached(sequence, stage_index, "image_results"):
            hidden_link_keys.add("image_result_id")
            hidden_link_keys.update({"first_frame_result_id", "last_frame_result_id"})
        if not _stage_reached(sequence, stage_index, "motion"):
            hidden_link_keys.add("video_result_id")
        if project["type"] == "photo":
            hidden_link_keys.add("motion_prompt_version_id")
        active_project["scenes"] = [
            _sanitize_scene(
                scene,
                position,
                project_type=project["type"],
                hidden_link_keys=hidden_link_keys,
            )
            for position, scene in enumerate(_list(state.get("scenes", []), "scenes"))
        ]
        if not _stage_reached(sequence, stage_index, "motion"):
            for scene in active_project["scenes"]:
                scene.pop("video_mode", None)
        active_project["image_prompts"] = [
            project_prompt(item, "image_prompts", position)
            for position, item in enumerate(
                _list(state.get("image_prompts", []), "image_prompts")
            )
        ]
        active_project["references"] = [
            _sanitize_reference(item, f"references[{position}]", asset_url, hidden_link_keys=hidden_link_keys)
            for position, item in enumerate(
                _list(state.get("references", []), "references")
            )
        ]
        if project["type"] != "photo":
            active_project["motion_prompts"] = [
                project_prompt(item, "motion_prompts", position)
                for position, item in enumerate(_list(state.get("motion_prompts", []), "motion_prompts"))
            ]
            active_project["oneshot"] = _sanitize_oneshot(state.get("oneshot", {}), hidden=hidden_link_keys)
    elif view_stage["current_stage"] == "scenario":
        # Ticket 15 repair, поправка оркестратора 8: right after a reopen
        # (G05), `scenario` is the only reachable stage again, but the
        # scenes an earlier `image_plan` pass built are still there in
        # canonical state, untouched -- without this, the dashboard has
        # no way to address the one thing a reopen exists to let someone
        # do, editing a scene's own block (`edit`, admitted at `scenario`
        # by ticket 15's first repair). No materials from any later
        # stage, and never `links`: see `_sanitize_scenario_stage_scene`.
        # Absent entirely (not merely empty) before the first `scenes
        # set` has ever run, same as every stage before this one --
        # `raw_scenes` is `[]` and the truthiness check below skips it.
        raw_scenes = _list(state.get("scenes", []), "scenes")
        if raw_scenes:
            active_project["scenes"] = [
                _sanitize_scenario_stage_scene(
                    scene, position, project_type=project["type"]
                )
                for position, scene in enumerate(raw_scenes)
            ]
    if _stage_reached(sequence, stage_index, "image_results"):
        active_project["image_results"] = [
            _sanitize_result(item, f"image_results[{position}]", asset_url)
            for position, item in enumerate(
                _list(state.get("image_results", []), "image_results")
            )
        ]
    if _stage_reached(sequence, stage_index, "motion"):
        active_project["motion_prompts"] = [
            project_prompt(item, "motion_prompts", position)
            for position, item in enumerate(
                _list(state.get("motion_prompts", []), "motion_prompts")
            )
        ]
        active_project["video_results"] = [
            _sanitize_result(item, f"video_results[{position}]", asset_url)
            for position, item in enumerate(
                _list(state.get("video_results", []), "video_results")
            )
        ]
    if _stage_reached(sequence, stage_index, "assembly"):
        active_project["assembly"] = _sanitize_assembly(
            state.get("assembly", {}), asset_url
        )
    if _stage_reached(sequence, stage_index, "audio"):
        from .domain_positions import AUDIO_LAYERS
        by_layer = {item["layer"]: item for item in audio_layers}
        active_project["audio_layers"] = [by_layer.get(layer, {"layer": layer, "links": {}}) for layer in AUDIO_LAYERS]
        active_project["audio_prompts"] = [
            project_prompt(item, "audio_prompts", position)
            for position, item in enumerate(state.get("audio_prompts", []))]
        active_project["audio_results"] = [
            _sanitize_result(item, f"audio_results[{position}]", asset_url)
            for position, item in enumerate(state.get("audio_results", []))]

    all_questions = [
        _sanitize_question(question, position)
        for position, question in enumerate(
            _list(state.get("questions", []), "questions")
        )
    ]
    questions = [
        question for question in all_questions if question.get("status", "pending") == "pending"
    ]
    all_actions = [
        _sanitize_action(action, position)
        for position, action in enumerate(_list(state.get("actions", []), "actions"))
    ]
    def _target_stage_reached(action):
        # Ticket 15 repair, поправка 3: `action_type in allowed_actions`
        # alone only rules out a *type* the current stage never offers at
        # all -- it cannot tell a `continue-in-chat`/`approve`/`reject`
        # left over from before a reopen (whose own `target_id` still
        # names a stage/card that is no longer reached) from a fresh one
        # the current stage actually owns, since those same types stay
        # valid at several stages. `_sanitize_action` already passes a
        # present `target_id` through unchanged (a plain allowlisted
        # string, `_ACTION_SOURCE_KEYS`), so reading it back off the
        # already-sanitized `action` here is exactly the raw value.
        # Unresolved (`action_target_stage` returns `None`) is *not*
        # excluded -- see that function's own docstring: it only ever has
        # evidence to exclude a target it can positively place at a
        # specific, unreached stage. `action_type` is passed alongside
        # `target_id` (ticket 15 repair, поправка 11): which collections
        # are even searched depends on it, which is what decides the
        # winner of a shared-id collision too (see that function's own
        # docstring for why search order alone already settles it).
        try:
            target_stage = action_target_stage(
                state, action.get("action_type"), action.get("target_id"), sequence
            )
        except ActionTargetError:
            return False
        return target_stage is None or target_stage in reached_stages

    actions = [
        action
        for action in all_actions
        if action.get("action_type") in view_stage["allowed_actions"] and _target_stage_reached(action)
    ]
    from .domain import derive_positions
    try:
        active_project["positions"] = [position for position in derive_positions(position_state)
                                      if position["stage"] in reached_stages]
    except DomainValidationError as error:
        raise ProjectionError(str(error)) from error
    snapshot = {
        "revision": revision,
        "projects": projects,
        "active_project": active_project,
        "view_stage": view_stage,
        "questions": questions,
        "actions": actions,
    }
    if set(snapshot) != PUBLIC_KEYS:
        raise ProjectionError("public snapshot key contract changed")
    return snapshot


def _identity_asset_url(asset_id):
    # `validate_state` below never serves a byte or needs a real route --
    # it only needs `_add_asset_url`'s own shape check (starts with
    # `/assets/`, no `..`) to run against whatever `asset_id` a section
    # carries, exactly as `build_snapshot`'s real `asset_url` callback
    # would eventually require once that section becomes visible.
    return f"/assets/{asset_id}"


def validate_state(state: dict) -> None:
    """Run every section's own sanitizer against `state`, regardless of
    which stage `derive_view_stage` currently exposes to the browser.

    Ticket 12 repair, condition 1. `build_snapshot` above intentionally
    *hides* a section ahead of its own stage (the `_stage_reached` gates
    before each `active_project[...] = _sanitize_*` line) -- that gate
    decides what the browser sees *right now*, not whether the underlying
    data is well-formed. A chat-authored write (`studio.authoring`) is
    free to write into a future section before its stage is reached
    (`assembly set` while the project is still at `image_plan`, by design
    -- see `authoring_qa.py`'s own module docstring), so a malformed write
    there used to surface only
    once the project's own milestones advanced far enough for
    `build_snapshot` to finally sanitize it -- turning every snapshot
    request from that point on into a `ProjectionError` (a 500), long
    after the write that actually caused it had already exited 0. This
    function is the one place `studio.authoring_support.mutate` calls,
    inside `ProjectStore.transact`'s own mutation callback and therefore
    before any commit, to catch that at write time instead (`code 3`),
    on the exact same rules `build_snapshot` itself enforces -- every
    per-section sanitizer below is the very function `build_snapshot`
    calls once a stage reaches it, never a second, hand-copied check.

    Never renders anything and never hides a section by stage or
    `project_type`: every section present in `state` is sanitized if it
    is structurally applicable at all (a photo project's `motion_prompts`/
    `video_results`, if a caller ever managed to write them, still get
    validated as prompt/result lists -- `authoring_scenes.add_prompt_
    version`/`authoring_media.add_result_version` already refuse that
    combination themselves, so this is defense in depth, not a stage
    gate of its own).

    A legacy `qa` state key (`_LEGACY_STATE_KEYS`) passes the closed-keys
    check above and is then left alone: it is neither validated nor
    projected, so a project file of the old stage model still accepts a
    write from chat.
    """

    state = _exact_keys(state, _STATE_KEYS, "state")
    _non_negative_integer(state.get("revision"), "state.revision")
    _sanitize_project(state.get("project"), "project")
    project_type = state["project"]["type"]
    if "gen_mode" in state:
        if project_type == "photo":
            raise ProjectionError("photo projects must not contain gen_mode")
        _enum(state["gen_mode"], {"per_scene", "one_shot"}, "gen_mode")
    try:
        derive_view_stage(state)
    except DomainValidationError as error:
        raise ProjectionError(str(error)) from error

    _sanitize_script(state.get("script", {}))
    for position, scene in enumerate(_list(state.get("scenes", []), "scenes")):
        _sanitize_scene(
            scene, position, project_type=state["project"]["type"]
        )
    for position, item in enumerate(_list(state.get("image_prompts", []), "image_prompts")):
        _sanitize_prompt(item, f"image_prompts[{position}]")
    for position, item in enumerate(_list(state.get("references", []), "references")):
        _sanitize_reference(item, f"references[{position}]", _identity_asset_url)
    for position, item in enumerate(_list(state.get("image_results", []), "image_results")):
        _sanitize_result(item, f"image_results[{position}]", _identity_asset_url)
    for position, item in enumerate(_list(state.get("motion_prompts", []), "motion_prompts")):
        _sanitize_prompt(item, f"motion_prompts[{position}]")
    for position, item in enumerate(_list(state.get("video_results", []), "video_results")):
        _sanitize_result(item, f"video_results[{position}]", _identity_asset_url)
    _sanitize_oneshot(state.get("oneshot", {}))
    _sanitize_audio_layers(state.get("audio_layers", []))
    for position, item in enumerate(_list(state.get("audio_prompts", []), "audio_prompts")):
        _sanitize_prompt(item, f"audio_prompts[{position}]")
    for position, item in enumerate(_list(state.get("audio_results", []), "audio_results")):
        _sanitize_result(item, f"audio_results[{position}]", _identity_asset_url)
    if project_type == "photo" and any(key in state for key in ("oneshot", "audio_layers", "audio_prompts", "audio_results")):
        raise ProjectionError("photo projects cannot contain oneshot or audio owners")
    if "assembly" in state:
        _sanitize_assembly(state["assembly"], _identity_asset_url)
    for position, question in enumerate(_list(state.get("questions", []), "questions")):
        _sanitize_question(question, position)
    for position, action in enumerate(_list(state.get("actions", []), "actions")):
        _sanitize_action(action, position)
    for position, entry in enumerate(
        _list(state.get("stage_decisions", []), "stage_decisions")
    ):
        _sanitize_stage_decision(entry, f"stage_decisions[{position}]")
    try:
        validate_history(state)
    except DomainValidationError as error:
        raise ProjectionError(str(error)) from error


def sanitize_event(event: dict) -> dict:
    """Validate and copy one browser event without permissive passthrough."""

    event = _exact_keys(event, _EVENT_KEYS, "event")
    if set(event) != _EVENT_KEYS:
        raise ProjectionError("event requires event_id, revision, event_type and payload")
    event_id = _non_negative_integer(event["event_id"], "event.event_id")
    revision = _non_negative_integer(event["revision"], "event.revision")
    if event["event_type"] not in _EVENT_TYPES:
        raise ProjectionError(f"unknown event_type: {event['event_type']}")
    payload = _exact_keys(event["payload"], _EVENT_PAYLOAD_KEYS, "event.payload")
    sanitized_payload = {}
    for key, value in payload.items():
        field = f"event.payload.{key}"
        if key == "stage_revision":
            sanitized_payload[key] = _non_negative_integer(value, field)
        elif key == "current_stage":
            sanitized_payload[key] = _enum(
                value, set(VIDEO_STAGES) | set(PHOTO_STAGES), field
            )
        elif key == "public_result":
            sanitized_payload[key] = _sanitize_public_result(value, field)
        elif key == "answer" and isinstance(value, list):
            sanitized_payload[key] = _string_list(value, field)
        elif key in {"message", "reason"}:
            sanitized_payload[key] = _safe_system_text(value, field)
        elif key == "status":
            sanitized_payload[key] = _enum(value, _PUBLIC_RESULT_STATUSES, field)
        else:
            sanitized_payload[key] = _string(value, field)
    return {
        "event_id": event_id,
        "revision": revision,
        "event_type": event["event_type"],
        "payload": sanitized_payload,
    }

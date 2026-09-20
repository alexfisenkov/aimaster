"""Shared helpers for every `studio.authoring_*` module.

Ticket 12 repair, condition 15: `authoring.py` grew past 700 lines and one
responsibility -- projects/script, scenes, media/references, questions,
milestones, QA/assembly all mixed into one file, the way `decisions.py`
used to before ticket 11 split it into `decision_support`/`decision_stages`/
`decision_cards`/`decision_planners`/`decision_reorder`. This module is
this build's `decision_support.py`: the openers, id/text validators, mime
and asset-role checks, and the shared `require_stage_not_approved` guard
every `authoring_*` module needs, none of it specific to one
responsibility. Version numbering/relinking is not here -- it lives in
`domain._append_group_version` (condition 8), the one function both a
prompt's and a result's `add_*_version` call for that half of their work.

Nothing here calls a provider, opens a socket outside the loopback
workspace, or writes a credential. Every write still goes through
`ProjectStore.transact(project_id, expected_revision, mutation)` for an
atomic, optimistic-concurrency write to `state.json`, and (ticket 12
repair, condition 1) `mutate` below also runs `projection.validate_state`
on the result before that transaction commits, so a write that would
make some *future* stage's snapshot fail is refused now instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .assets import (
    REFERENCE_ROLES, RESULT_ROLE, VIDEO_REFERENCE_ROLE, VOICE_ROLE, AssetIndex,
)
from .projection import ProjectionError, validate_state
from .questions import QuestionStore, _SAFE_ID
from .store import ProjectStore
from .workspace import (
    ASSETS_DB_NAME,
    MAX_ASSET_BYTES,
    MAX_TEXT_BYTES,
    QUESTIONS_DB_NAME,
    resolve_workspace_paths,
)


_AUTHOR = "chat"

# Ticket 12 repair, condition 14: the same safe-opaque-identifier rule
# `studio/questions.py` already enforces for `question_id`/`project_id`/
# option ids -- imported directly (above) rather than re-declared with a
# different length limit (this module used to cap at 64 characters,
# `questions.py` at 128), so the two can never quietly drift apart again.

# Ticket 12 repair, condition 11: the ceiling itself now lives in
# `workspace.py` (`MAX_TEXT_BYTES`), alongside `MAX_ASSET_BYTES` -- this
# module's own text-size helpers (`non_empty_text`/`optional_bounded_text`)
# keep the private, underscore-prefixed name every call site below already
# defaults to, so only the *value*'s source moved, not this module's own
# public surface.
_MAX_TEXT_BYTES = MAX_TEXT_BYTES

_IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_VIDEO_MIME_TYPES = frozenset({"video/mp4", "video/webm"})
# Ticket 26: exactly the MIME types `assets._EXTENSION_MIME` gives `.mp3`/`.wav`.
_AUDIO_MIME_TYPES = frozenset({"audio/mpeg", "audio/wav"})


class AuthoringError(ValueError):
    """A chat-authored write violates a canonical or workspace invariant.

    A `ValueError` subclass on purpose: `scripts/creator_studio.py`'s
    `main()` already exits with the domain-error code for any
    `ValueError` it catches, so this needs no change there to get the
    ticket's "код 3" behavior.
    """


def safe_id(value, label):
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise AuthoringError(f"{label} must be a safe opaque identifier")
    return value


def non_empty_text(value, label, *, max_bytes=_MAX_TEXT_BYTES):
    if not isinstance(value, str) or not value.strip():
        raise AuthoringError(f"{label} must be a non-empty string")
    if len(value.encode("utf-8")) > max_bytes:
        raise AuthoringError(f"{label} must be at most {max_bytes} bytes (UTF-8)")
    return value


def optional_bounded_text(value, label, *, max_bytes=_MAX_TEXT_BYTES, allow_empty=True):
    """`value` unchanged if `None`; otherwise a size-checked string.

    Used for every optional free-text field (`label`, `caption`, a QA
    `summary`/`message`) that used to be checked with a bare
    `isinstance(value, str)` and no size limit at all.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise AuthoringError(f"{label} must be a string")
    if not allow_empty and not value.strip():
        raise AuthoringError(f"{label} must be a non-empty string")
    if len(value.encode("utf-8")) > max_bytes:
        raise AuthoringError(f"{label} must be at most {max_bytes} bytes (UTF-8)")
    return value


def require_project(state) -> dict:
    project = state.get("project")
    if not isinstance(project, dict):
        raise AuthoringError("project is missing from state")
    return project


def find_scene(state, scene_id) -> dict:
    scenes = state.get("scenes")
    if not isinstance(scenes, list):
        raise AuthoringError("project has no scenes yet")
    matches = [
        scene
        for scene in scenes
        if isinstance(scene, dict) and scene.get("scene_id") == scene_id
    ]
    if len(matches) != 1:
        raise AuthoringError(f"unknown or duplicate scene_id: {scene_id!r}")
    return matches[0]


def scene_has_linked_materials(scene) -> bool:
    """Whether `scene["links"]` already points at a prompt/result/
    reference -- one of the two facts that make a scene not safely
    replaceable by a wholesale rewrite (`scenes set`; ticket 15 repair,
    поправка 2: also `script add-version` over an existing scene set).
    Shared so the two callers' *rule* can never quietly diverge, only
    each one's own refusal message -- see `authoring_scenes.
    _refuse_if_scenes_are_not_replaceable` and `authoring_projects.
    _refuse_if_scenes_block_a_script_rewrite`.
    """

    if not isinstance(scene, dict):
        return False
    links = scene.get("links")
    return isinstance(links, dict) and any(links.values())


def scene_has_edited_block_history(scene) -> bool:
    """Whether `scene["script_block"]["versions"]` already has more than
    its initial entry -- the other fact `scene_has_linked_materials`'s
    own docstring describes. An `edit`/`scene edit` decision (`domain.
    append_scene_block_version`) is the only thing that ever appends a
    second entry; `_build_initial_scene` always starts a scene at exactly
    one.
    """

    if not isinstance(scene, dict):
        return False
    block = scene.get("script_block")
    versions = block.get("versions") if isinstance(block, dict) else None
    return isinstance(versions, list) and len(versions) > 1


def scene_links(scene) -> dict:
    links = scene.setdefault("links", {})
    if not isinstance(links, dict):
        raise AuthoringError("scene.links must be an object")
    return links


def resolve_current_group_member(group, linked_version_id) -> dict:
    """Which existing member of `group` a new version is appended beside.

    Prefers the one the scene's own link already names -- the version the
    dashboard/chat most recently made current. Falls back to the group's
    only member when there is exactly one (unambiguous even without a
    link). Otherwise refuses: which version is "current" cannot be
    guessed, mirroring `decision_cards.resolve_card`'s own refusal for an
    ambiguous group id.
    """

    if linked_version_id is not None:
        matches = [item for item in group if item.get("version_id") == linked_version_id]
        if len(matches) == 1:
            return matches[0]
    if len(group) == 1:
        return group[0]
    raise AuthoringError(
        "cannot resolve which version to add beside; pass an explicit id "
        "that matches the scene's current link"
    )


def require_owning_scene_matches(current, scene_id, label) -> None:
    """Refuse an explicit `--prompt-id`/`--result-id` that names a group
    already owned by a *different* scene.

    Ticket 12 repair, condition 13: with no check here, an explicit id
    naming another scene's group would silently create a new version
    inside that group and repoint *this* call's `scene_id` link at it --
    cross-linking two scenes' prompts/results. The default id
    (`f"{scene_id}-{kind}"`, never passed explicitly) can never trigger
    this: it is derived from the very `scene_id` being written, so it can
    only ever name a group that scene itself already owns.
    """

    owning_scene_id = current.get("scene_id")
    if owning_scene_id is not None and owning_scene_id != scene_id:
        raise AuthoringError(
            f"{label} belongs to scene {owning_scene_id!r}, not {scene_id!r}"
        )


def require_stage_not_approved(state: dict, stage: str, label: str) -> None:
    """Refuse a write into `stage`'s own section once that milestone is
    already `approved`.

    Ticket 12 repair, condition 2 (spec §3, "не переписывает молча"):
    approval is exclusively a dashboard decision
    (`decisions.DecisionWorker`) and, once granted, must not be silently
    reopened by a later chat-authored write landing in the data that
    same stage owns -- `result add-version --kind image` once
    `image_results` is approved, `--kind video` once `motion` is
    approved, `qa set` once `qa` is approved, `assembly set` once
    `assembly` is approved. A milestone key absent from
    `state["milestones"]` reads as `"draft"`, matching `derive_view_stage`
    and `authoring_milestones.set_milestone`'s own check for the same
    rule (`add_script_version`'s own `scenario` check, and `set_scenes`'s
    current-stage check, predate this shared helper and are left as they
    are).

    Ticket 13 (spec §3/§7, "перегенерировать промпт"): `prompt
    add-version`/`reference add` call this with each kind's own
    *generation* stage, not its *planning* one -- `--kind image`'s own
    door closes on `image_results`, never on `image_plan` (which used to
    block every regeneration the moment the plan was approved);
    `--kind motion` closes on `motion`, unchanged. `reference add`
    closes on `image_results` for a photo project (its own last
    generation stage) or `motion` for a video/mixed one. See
    `authoring_scenes._PROMPT_KIND_STAGE` and
    `authoring_media._reference_final_stage` for exactly which stage
    each call passes here.
    """

    milestones = state.get("milestones")
    if not isinstance(milestones, dict):
        raise AuthoringError("milestones must be an object")
    if milestones.get(stage, "draft") == "approved":
        raise AuthoringError(f"{stage} is already approved; {label} cannot modify it")


def require_image_mime(mime_type: str, label: str) -> None:
    if mime_type not in _IMAGE_MIME_TYPES:
        raise AuthoringError(f"{label} must resolve to an image asset")


def require_video_mime(mime_type: str, label: str) -> None:
    if mime_type not in _VIDEO_MIME_TYPES:
        raise AuthoringError(f"{label} must resolve to a video asset")


def require_audio_mime(mime_type: str, label: str) -> None:
    """Refuse anything that is not an MP3 or WAV asset (ticket 26).

    The counterpart of `require_image_mime`/`require_video_mime`: a call
    site that links a registered asset in as *audio* -- a character's voice
    reference (spec §18.4) or a sound layer's result (§18.5) -- passes the
    `mime_type` `AssetIndex.resolve` returned. Audio never satisfies the
    image or video checks, and an image or video never satisfies this one.
    """

    if mime_type not in _AUDIO_MIME_TYPES:
        raise AuthoringError(f"{label} must resolve to an audio asset")


def require_result_asset_role(role: str, label: str) -> None:
    """Refuse an asset that was not registered with the `result` role.

    Ticket 12 repair, condition 6: `add_result_version`/`set_assembly`
    both link a registered asset into canonical state as a scene/
    assembly *result* -- an asset registered for a reference (character/
    object/product/style/location) must not be usable there, the mirror
    of `require_reference_asset_role` below; ticket 26: nor one registered
    `voice`, which is a voice reference, not a result. See `assets.py`'s
    own `RESULT_ROLE`/`REFERENCE_ROLES`/`VOICE_ROLE` comment for the full
    picture.
    """

    if role != RESULT_ROLE:
        raise AuthoringError(f"{label} must be registered with the result role")


def require_reference_asset_role(role: str, label: str) -> None:
    """Refuse an asset that was not registered with an image-reference role.

    Ticket 12 repair, condition 6: `add_reference` links a registered
    asset in as a character/object/product/style/location reference --
    an asset registered `result` (i.e. meant to back a scene/assembly
    result) must not be usable there. Ticket 26: nor may one registered
    `voice` -- `VOICE_ROLE` is deliberately outside `REFERENCE_ROLES`, so
    this same membership test already refuses a voice file as an *image*
    reference.
    """

    if role not in REFERENCE_ROLES:
        raise AuthoringError(f"{label} must be registered with a reference role")


def require_video_reference_asset_role(role: str, label: str) -> None:
    if role != VIDEO_REFERENCE_ROLE:
        raise AuthoringError(
            f"{label} must be registered with the video_reference role"
        )


def require_voice_asset_role(role: str, label: str) -> None:
    """Refuse an asset that was not registered with the `voice` role.

    Ticket 26 (spec §18.4): the check a character's voice reference must
    pass, together with `require_audio_mime`. It refuses `result` and every
    image-reference role, so a reference image or a sound layer's result
    can never be linked in as a voice.
    """

    if role != VOICE_ROLE:
        raise AuthoringError(f"{label} must be registered with the voice role")


def require_voice_asset(mime_type: str, role: str, label: str) -> None:
    """Apply the inseparable MIME-and-role contract for a voice reference."""

    require_audio_mime(mime_type, label)
    require_voice_asset_role(role, label)


def mutate(store: ProjectStore, project_id: str, expected_revision: int, mutator: Callable):
    """Run `mutator(state) -> result` inside one `store.transact` call,
    then validate the resulting state before it commits.

    `ProjectStore.transact`'s own `mutation` callback return value is
    discarded (its contract is `Callable[[dict], None]`); every write
    below needs to hand something back to the CLI (a new version id, a
    scene list) beyond the new revision, so the result is stashed in a
    closure-captured slot instead.

    Ticket 12 repair, condition 1: `validate_state` runs every section's
    projection sanitizer against the mutated `state`, still inside
    `ProjectStore.transact`'s own mutation callback -- and therefore
    still before `transact` commits anything to disk. A write that would
    make some *future* stage's snapshot request fail (an empty/`None`
    `qa.checks[].label`, a `qa.summary`/`assembly.summary` containing a
    forbidden word `projection._safe_system_text` rejects, ...) is
    refused here instead, as `AuthoringError` (CLI exit code 3), before
    it ever reaches `state.json` -- not discovered later as a 500 on
    every snapshot request once the project's own stage catches up to
    the section that was already broken.
    """

    outcome: dict = {}

    def mutation(state):
        outcome["result"] = mutator(state)
        try:
            validate_state(state)
        except ProjectionError as error:
            raise AuthoringError(str(error)) from error

    new_state = store.transact(project_id, expected_revision, mutation)
    return outcome["result"], new_state


def open_store(workspace) -> ProjectStore:
    _, project_root, _, _ = resolve_workspace_paths(workspace)
    return ProjectStore(project_root, excluded=())


def open_assets(workspace) -> AssetIndex:
    workspace_path, _, media_root, private_root = resolve_workspace_paths(workspace)
    return AssetIndex(
        workspace_path,
        (media_root,),
        max_bytes=MAX_ASSET_BYTES,
        db_path=private_root / ASSETS_DB_NAME,
    )


def open_questions(workspace) -> QuestionStore:
    _, _, _, private_root = resolve_workspace_paths(workspace)
    return QuestionStore(private_root / QUESTIONS_DB_NAME)


def new_project_directory(store: ProjectStore, project_id: str) -> Path:
    """Create and return `<project_root>/<project_id>`, or refuse if it
    already exists on disk (a duplicate id is already refused by the
    caller's own `list_projects()` check; this catches a directory left
    behind some other way, e.g. a previous, only-partially-failed create).
    """

    project_root = store.root
    project_root.mkdir(parents=True, exist_ok=True)
    project_dir = project_root / project_id
    if project_dir.exists():
        raise AuthoringError(f"project directory already exists: {project_id}")
    project_dir.mkdir(parents=True)
    return project_dir

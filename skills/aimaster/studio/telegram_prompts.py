"""The «Промпты» card: references, the one-shot prompt, prompts per frame."""

from __future__ import annotations

from .telegram_text import assemble, clip
from .telegram_view import (
    TITLE_LIMIT,
    heading,
    items,
    mapping,
    project_of,
    scene_tail,
    scene_title,
    scenes_of,
)


_PROMPT_TEXT_LIMIT = 600
_REFERENCE_KINDS = {
    "character": "персонаж",
    "product": "продукт",
    "location": "локация",
    "style": "стиль",
    "other": "прочее",
    "video": "видеореференс",
}
# The four owner links a scene may carry, in the order the dashboard's own
# frame card lays them out (ui/frame-card.js), with the collection each one
# names.  A link the current stage must not expose yet is already absent
# from the snapshot (`projection.build_snapshot`'s `hidden_link_keys`), so
# a photo project simply has no motion entry to find here.
_SCENE_PROMPT_SLOTS = (
    ("image_prompt_version_id", "image_prompts", "Изображение"),
    ("first_frame_prompt_version_id", "image_prompts", "Первый кадр"),
    ("last_frame_prompt_version_id", "image_prompts", "Последний кадр"),
    ("motion_prompt_version_id", "motion_prompts", "Движение"),
)
_PROMPT_COLLECTIONS = ("image_prompts", "motion_prompts", "audio_prompts")


def _prompt_index(project, collection):
    """Address one collection's prompts by version id, then by group id."""

    index = {}
    for prompt in items(project.get(collection)):
        if not isinstance(prompt, dict):
            continue
        for key in ("version_id", "prompt_id"):
            identity = prompt.get(key)
            if isinstance(identity, str) and identity:
                index.setdefault(identity, prompt)
    return index


def _prompt_marks(prompt):
    marks = []
    if prompt.get("stale") is True:
        marks.append("устарел")
    decisions = [entry for entry in items(prompt.get("decisions")) if isinstance(entry, dict)]
    if decisions:
        decision = decisions[-1].get("decision")
        if decision == "approved":
            marks.append("принят")
        elif decision == "rejected":
            marks.append("нужны правки")
    return marks


def _prompt_line(label, prompt):
    text = clip(prompt.get("text"), _PROMPT_TEXT_LIMIT)
    marks = _prompt_marks(prompt)
    suffix = f" [{', '.join(marks)}]" if marks else ""
    return f"   {label}{suffix}: {text}" if text else f"   {label}{suffix}: текста пока нет"


def _reference_lines(project):
    lines = []
    for reference in items(project.get("references")):
        if not isinstance(reference, dict):
            continue
        tag = reference.get("tag") or reference.get("reference_id")
        if not isinstance(tag, str) or not tag:
            continue
        name = clip(reference.get("label"), TITLE_LIMIT)
        kind = _REFERENCE_KINDS.get(reference.get("kind"), "референс")
        note = kind
        if reference.get("source") == "generate":
            note += ", будет сгенерирован"
        elif reference.get("has_asset") is not True:
            note += ", файла пока нет"
        lines.append(f"   {tag} — {name or kind} ({note})")
        voice = mapping(reference.get("voice"))
        voice_tag = voice.get("tag")
        if voice.get("enabled") is True and isinstance(voice_tag, str) and voice_tag:
            lines.append(f"   {voice_tag} — голос: {name or kind}")
    return lines


def _scene_blocks(project, indexes):
    blocks = []
    for position, scene in enumerate(scenes_of(project), 1):
        links = mapping(scene.get("links"))
        lines = []
        for key, collection, label in _SCENE_PROMPT_SLOTS:
            identity = links.get(key)
            prompt = indexes[collection].get(identity) if isinstance(identity, str) else None
            if prompt is not None:
                lines.append(_prompt_line(label, prompt))
        if lines:
            blocks.append([f"{position}. {scene_title(scene, position)}", *lines])
    return blocks


def render_prompts(snapshot):
    project = project_of(snapshot)
    indexes = {name: _prompt_index(project, name) for name in _PROMPT_COLLECTIONS}
    header = heading(snapshot, "prompts")
    blocks = _scene_blocks(project, indexes)
    oneshot_id = mapping(mapping(project.get("oneshot")).get("links")).get(
        "motion_prompt_version_id"
    )
    oneshot = indexes["motion_prompts"].get(oneshot_id) if isinstance(oneshot_id, str) else None
    references = _reference_lines(project)
    if not blocks and oneshot is None and not references:
        header.extend(["", "Промптов пока нет — они появятся на шаге «Кадры и промпты»."])
        return assemble(header, [])
    if references:
        header.extend(["", "Референсы:", *references])
    if oneshot is not None:
        header.extend(["", "Ролик целиком", _prompt_line("Движение", oneshot)])
    if blocks:
        header.extend(["", "По кадрам:"])
    return assemble(header, blocks, tail=scene_tail)

"""The «Сценарий» card: approval state, the active text, the storyboard."""

from __future__ import annotations

from .telegram_text import assemble, clip, seconds_label
from .telegram_view import (
    COMMENT_LIMIT,
    heading,
    items,
    mapping,
    project_of,
    scene_tail,
    scene_text,
    scene_title,
    scenes_of,
    view_of,
)


_SCRIPT_TEXT_LIMIT = 3000


def _active_script_text(project):
    script = mapping(project.get("script"))
    active = script.get("active_version_id")
    for version in items(script.get("versions")):
        if isinstance(version, dict) and version.get("version_id") == active:
            return clip(version.get("text"), _SCRIPT_TEXT_LIMIT, collapse=False)
    return ""


def scenario_status(snapshot):
    """How the data itself expresses the scenario's standing, in words.

    The shared milestone history (`active_project.stage_decisions`) is
    authoritative once it has an entry for `scenario`; before the first
    decision the current stage's own gate says whether the owner is
    looking at a draft, at something offered for review, or at a stage
    held up by an unanswered question.
    """

    project = project_of(snapshot)
    view = view_of(snapshot)
    history = [
        entry
        for entry in items(project.get("stage_decisions"))
        if isinstance(entry, dict) and entry.get("stage") == "scenario"
    ]
    last = history[-1] if history else None
    decision = last.get("decision") if last else None
    if decision == "approved":
        return "одобрен"
    if decision == "rejected":
        comment = clip(last.get("comment"), COMMENT_LIMIT)
        return f"нужны правки: {comment}" if comment else "нужны правки"
    if decision == "reopened":
        return "открыт заново"
    if view.get("current_stage") != "scenario":
        return "одобрен"
    return {
        "ready": "на проверке",
        "blocked": "ждёт вашего ответа",
        "approved": "одобрен",
    }.get(view.get("gate_status"), "черновик")


def render_scenario(snapshot):
    project = project_of(snapshot)
    header = heading(snapshot, "scenario")
    header.append(f"Сценарий: {scenario_status(snapshot)}")
    text = _active_script_text(project)
    header.append("")
    if text:
        header.append("Текст сценария:")
        header.extend(text.splitlines())
    else:
        header.append("Сценария пока нет.")
    scenes = scenes_of(project)
    header.append("")
    header.append("Раскадровка:" if scenes else "Раскадровки пока нет.")
    blocks = []
    for position, scene in enumerate(scenes, 1):
        line = f"{position}. {scene_title(scene, position)}"
        body = scene_text(scene)
        if body:
            line += f" — {body}"
        duration = seconds_label(scene.get("duration_ms"))
        if duration:
            line += f" ({duration})"
        blocks.append([line])
    return assemble(header, blocks, tail=scene_tail)

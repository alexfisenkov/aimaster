"""The «Результаты» card: variants per frame, sound layers, the final cut.

Media files themselves never travel through the bot -- the Telegram client
here speaks JSON only -- so the card counts and names what exists and points
at the Mini App for the pictures.
"""

from __future__ import annotations

from .telegram_text import assemble, clip, plural
from .telegram_view import (
    COMMENT_LIMIT,
    heading,
    items,
    mapping,
    project_of,
    scene_tail,
    scene_title,
    scenes_of,
)


_CAPTION_LIMIT = 60
_AUDIO_LAYERS = (
    ("voice", "Голос"),
    ("music", "Музыка"),
    ("fx", "Эффекты"),
    ("atmos", "Атмосфера"),
)
_MEDIA_NOTE = "Медиа — в AI Мастерской (кнопка выше)."


def _result_state(item):
    if item.get("retired") is True:
        return "retired"
    if item.get("decision") == "approved":
        return "approved"
    if item.get("decision") == "rejected":
        return "rejected"
    if item.get("hidden") is True:
        return "hidden"
    return "waiting"


def _current_versions(entries):
    """Group results the way the dashboard does: one strip per `result_id`.

    A group's own current version is its last appended one (`domain.
    append_result_version` only ever appends), so an earlier version is
    history, not a second variant still waiting for a decision.
    """

    groups = {}
    for entry in entries:
        identity = entry.get("result_id") or entry.get("version_id")
        groups.setdefault(identity, []).append(entry)
    current = [versions[-1] for versions in groups.values()]
    superseded = sum(len(versions) - 1 for versions in groups.values())
    return current, superseded


def _results_line(label, entries):
    if not entries:
        return f"   {label}: пока нет"
    current, superseded = _current_versions(entries)
    counted = {"approved": [], "rejected": [], "retired": [], "hidden": [], "waiting": []}
    for entry in current:
        counted[_result_state(entry)].append(entry)
    total = len(current)
    parts = [f"{total} {plural(total, 'вариант', 'варианта', 'вариантов')}"]
    if counted["approved"]:
        caption = clip(counted["approved"][-1].get("caption"), _CAPTION_LIMIT)
        parts.append(f"принят «{caption}»" if caption else "принят")
    waiting = len(counted["waiting"])
    if waiting:
        parts.append(f"{waiting} {plural(waiting, 'ждёт', 'ждут', 'ждут')} решения")
    if counted["rejected"]:
        parts.append(f"{len(counted['rejected'])} с правками")
    if counted["hidden"]:
        parts.append(f"{len(counted['hidden'])} скрыто")
    if counted["retired"]:
        parts.append(f"{len(counted['retired'])} убрано из работы")
    if superseded:
        parts.append(
            f"ещё {superseded} {plural(superseded, 'версия', 'версии', 'версий')} в истории"
        )
    return f"   {label}: " + " · ".join(parts)


def _by_scene(project, collection, scene_id):
    return [
        entry
        for entry in items(project.get(collection))
        if isinstance(entry, dict) and entry.get("scene_id") == scene_id
    ]


def _without_scene(project, collection):
    return [
        entry
        for entry in items(project.get(collection))
        if isinstance(entry, dict) and not isinstance(entry.get("scene_id"), str)
    ]


def _audio_lines(project):
    """One line per sound layer, or nothing while `audio` is out of reach."""

    if "audio_results" not in project:
        return []
    results = [entry for entry in items(project.get("audio_results")) if isinstance(entry, dict)]
    by_result = {entry.get("result_id"): entry for entry in results}
    by_version = {entry.get("version_id"): entry for entry in results}
    links = {
        mapping(entry).get("layer"): mapping(mapping(entry).get("links"))
        for entry in items(project.get("audio_layers"))
    }
    lines = ["", "Звук:"]
    for layer, name in _AUDIO_LAYERS:
        identity = links.get(layer, {}).get("audio_result_id")
        current = by_version.get(identity) or by_result.get(identity)
        lines.append(_results_line(name, [current] if current is not None else []))
    return lines


def _assembly_lines(project):
    if "assembly" not in project:
        return []
    assembly = mapping(project.get("assembly"))
    if not assembly:
        return ["", "Финальной сборки пока нет."]
    line = "Финальная сборка: " + ("готова" if assembly.get("status") == "ready" else "в работе")
    summary = clip(assembly.get("summary"), COMMENT_LIMIT)
    if summary:
        line += f" — {summary}"
    return ["", line]


def render_results(snapshot, *, mini_app_url=None):
    project = project_of(snapshot)
    header = heading(snapshot, "results")
    has_images = "image_results" in project
    has_videos = "video_results" in project
    blocks = []
    for position, scene in enumerate(scenes_of(project), 1):
        scene_id = scene.get("scene_id")
        lines = []
        if has_images:
            lines.append(_results_line("Изображения", _by_scene(project, "image_results", scene_id)))
        if has_videos:
            lines.append(_results_line("Видео", _by_scene(project, "video_results", scene_id)))
        if lines:
            blocks.append([f"{position}. {scene_title(scene, position)}", *lines])
    footer = []
    if has_videos:
        loose = _without_scene(project, "video_results")
        if loose:
            footer.extend(["", "Ролик целиком", _results_line("Видео", loose)])
    footer.extend(_audio_lines(project))
    footer.extend(_assembly_lines(project))
    if not blocks and not footer:
        header.extend(["", "Результатов пока нет."])
        return assemble(header, [])
    header.extend(["", "По кадрам:" if blocks else "Результатов по кадрам пока нет."])
    if mini_app_url:
        footer.extend(["", _MEDIA_NOTE])
    return assemble(header, blocks, footer=footer, tail=scene_tail)

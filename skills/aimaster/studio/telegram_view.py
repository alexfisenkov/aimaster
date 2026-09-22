"""Shared reading of one public snapshot for the Telegram section cards.

Every renderer in ``telegram_scenario``/``telegram_prompts``/
``telegram_results`` reads its project through these accessors, so the
section cards can only ever see what ``projection.build_snapshot`` -- the
exact document ``GET /api/projects/<id>/snapshot`` hands the dashboard --
has already allowlisted.  Canonical state is never opened here: no
filesystem path, no grant, no idempotency marker exists to leak.  Asset
URLs *are* in the snapshot and are deliberately never rendered; media
lives behind the Mini App button.
"""

from __future__ import annotations

from .telegram_text import clip, plural


PROJECT_TYPES = {"photo": "Фото", "video": "Видео", "mixed": "Фото и видео"}
STAGES = {
    "scenario": "Сценарий",
    "image_plan": "Кадры и промпты",
    "image_results": "Изображения",
    "motion": "Видео",
    "audio": "Звук",
    "assembly": "Сборка",
}
STATUSES = {"active": "В работе", "review": "На проверке", "done": "Готово"}
SECTION_LABELS = {
    "scenario": "Сценарий",
    "prompts": "Промпты",
    "results": "Результаты",
    "chat": "Чат",
}

SCENE_TEXT_LIMIT = 300
COMMENT_LIMIT = 200
TITLE_LIMIT = 80


def items(value):
    return value if isinstance(value, list) else []


def mapping(value):
    return value if isinstance(value, dict) else {}


def project_of(snapshot):
    return mapping(mapping(snapshot).get("active_project"))


def view_of(snapshot):
    return mapping(mapping(snapshot).get("view_stage"))


def scenes_of(project):
    return sorted(
        (scene for scene in items(project.get("scenes")) if isinstance(scene, dict)),
        key=lambda scene: scene.get("order") if isinstance(scene.get("order"), int) else 0,
    )


def scene_title(scene, position):
    return clip(scene.get("title"), TITLE_LIMIT) or f"Кадр {position}"


def scene_text(scene):
    """The scene's own active block text, falling back to legacy `content`."""

    block = mapping(scene.get("script_block"))
    active = block.get("active_version_id")
    for version in items(block.get("versions")):
        if isinstance(version, dict) and version.get("version_id") == active:
            text = clip(version.get("text"), SCENE_TEXT_LIMIT)
            if text:
                return text
    return clip(scene.get("content"), SCENE_TEXT_LIMIT)


def state_line(snapshot):
    """One human line: project type, the step it stands on, its status."""

    project = project_of(snapshot)
    view = view_of(snapshot)
    parts = []
    type_label = PROJECT_TYPES.get(project.get("type"))
    if type_label:
        parts.append(type_label)
    stage_label = STAGES.get(view.get("current_stage") or project.get("stage"))
    if stage_label:
        parts.append(f"шаг: {stage_label}")
    status_label = STATUSES.get(project.get("status"))
    if status_label:
        parts.append(status_label)
    if view.get("gate_status") == "blocked":
        parts.append("ждёт вашего ответа")
    return " · ".join(parts) if parts else "Состояние проекта пока не определено."


def heading(snapshot, section):
    """The two lines every section opens with; line one is a fixed contract."""

    project = project_of(snapshot)
    title = clip(project.get("title"), TITLE_LIMIT) or project.get("id") or "проект"
    return [f"Проект «{title}» · {SECTION_LABELS[section]}", state_line(snapshot)]


def scene_tail(dropped):
    """The one line that says where the scenes past the budget live."""

    return f"…ещё {dropped} {plural(dropped, 'сцена', 'сцены', 'сцен')} — в AI Мастерской."

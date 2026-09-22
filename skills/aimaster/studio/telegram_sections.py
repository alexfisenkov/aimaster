"""One entry point onto the Telegram project cards.

`telegram_bot` asks here and nowhere else: which Russian word names a step
or a section (`telegram_view`), and what one button press answers with.
Each section owns its own module -- `telegram_scenario`, `telegram_prompts`,
`telegram_results` -- so a change to one card cannot disturb another.

Every card is built from one already-validated public snapshot, the exact
document `GET /api/projects/<id>/snapshot` hands the dashboard.  Output is
plain text and is sent without `parse_mode`, so a scene description that
happens to contain `*` or `_` stays the owner's own text.
"""

from __future__ import annotations

from .telegram_prompts import render_prompts
from .telegram_results import render_results
from .telegram_scenario import render_scenario
from .telegram_text import clip
from .telegram_view import (
    PROJECT_TYPES,
    SECTION_LABELS,
    STAGES,
    STATUSES,
    items,
    mapping,
    project_of,
    scenes_of,
    state_line,
)


__all__ = [
    "PROJECT_TYPES",
    "SECTION_LABELS",
    "STAGES",
    "STATUSES",
    "render_section",
    "render_selection",
    "state_line",
]

_QUESTION_LIMIT = 200
_PROMPT_COLLECTIONS = ("image_prompts", "motion_prompts", "audio_prompts")
_RESULT_COLLECTIONS = ("image_results", "video_results", "audio_results")


def render_selection(snapshot, opening_line):
    """The short card a project button answers with: state, counts, question.

    `opening_line` stays the first line verbatim: pressing a project button
    must keep saying that the project is selected and that a plain message
    is how the next task is given.
    """

    project = project_of(snapshot)
    prompts = sum(len(items(project.get(name))) for name in _PROMPT_COLLECTIONS)
    results = sum(len(items(project.get(name))) for name in _RESULT_COLLECTIONS)
    lines = [
        opening_line,
        state_line(snapshot),
        f"Сцен: {len(scenes_of(project))} · промптов: {prompts} · результатов: {results}",
    ]
    questions = [
        item for item in items(mapping(snapshot).get("questions")) if isinstance(item, dict)
    ]
    if questions:
        text = clip(questions[0].get("text"), _QUESTION_LIMIT)
        lines.append(f"Вопрос к вам: {text}" if text else "Есть вопрос к вам.")
    return "\n".join(lines)


def render_section(snapshot, action, *, mini_app_url=None):
    """Render one navigation section of an already-built public snapshot."""

    if action == "scenario":
        return render_scenario(snapshot)
    if action == "prompts":
        return render_prompts(snapshot)
    if action == "results":
        return render_results(snapshot, mini_app_url=mini_app_url)
    raise KeyError(action)

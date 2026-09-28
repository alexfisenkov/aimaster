"""Вход `service` для экрана «Сборка» дашборда. Как и остальной `service`,
каждый вызов открывает проект заново через `open_context` (проверка ссылок
в папке монтажа). Ответы — для браузера: без абсолютных путей, без pid и
порта стола; вместо адреса Studio — адрес страницы-переходника
(`desk_opener`), которая выключает аналитику Studio."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import MontageError
from .context import open_context
from .desk_opener import opener_file, opener_url
from .desk_record import loopback_url
from .montage_state import montage_section
from .paths import MontagePaths, render_output
from .service import open_desk
from .service_versions import restore
from .status_screen import cheap_status, model_status, shown_output

DeskState = Callable[[MontagePaths], dict]
_NOTES = ("note", "forgotten")


def desk_view(desk: dict, paths: MontagePaths) -> dict:
    """Адрес — только `http://127.0.0.1:<порт>`; переходник — только если его
    файл на месте (иначе Studio ответила бы на ссылку 404)."""

    view = {"state": desk.get("state", "closed")}
    url = desk.get("url")
    if view["state"] == "open" and loopback_url(url):
        page = opener_url(url) if opener_file(paths).is_file() else None
        view.update(url=page or url, telemetry_off=page is not None)
    view.update({key: desk[key] for key in _NOTES if isinstance(desk.get(key), str)})
    return view


def assembly_approved(state: dict) -> bool:
    """Ролик принят («Принять ролик», `stage approve`): монтаж больше не меняют."""

    milestones = state.get("milestones")
    return isinstance(milestones, dict) and milestones.get("assembly") == "approved"


def screen_status(workspace, project_id, *, locate, desk_state: DeskState) -> dict:
    ctx = open_context(workspace, project_id)
    if (ctx.state.get("project") or {}).get("type") == "photo":
        return {"project_id": project_id, "revision": ctx.revision, "applicable": False}
    engine, reason = locate()
    result = {"applicable": True, "approved": assembly_approved(ctx.state),
              **cheap_status(ctx, engine, reason)}
    result["desk"] = (desk_view(desk_state(ctx.paths), ctx.paths) if result["exists"]
                      else {"state": "closed"})
    return result


def screen_model(workspace, project_id, *, locate, runner=None) -> dict:
    ctx = open_context(workspace, project_id)
    engine, _reason = locate()
    return model_status(ctx, engine, runner=runner)


def open_desk_for_screen(workspace, project_id, *, desk) -> tuple[dict, MontagePaths]:
    opened = open_desk(workspace, project_id, desk=desk)
    paths = open_context(workspace, project_id, guard=False).paths
    return {"project_id": project_id, **desk_view(opened, paths)}, paths


def restore_as_owner(workspace, project_id, expected_revision, version_id) -> dict:
    """«Сделать текущей» с экрана — действие человека: в истории «Вы»."""

    result = restore(workspace, project_id, expected_revision, version_id, actor="you")
    return {key: result[key] for key in ("project_id", "revision", "current_version")}


def current_output(workspace, project_id) -> tuple[Path, str]:
    """MP4 текущей версии (для «Показать в папке») и его путь для показа."""

    ctx = open_context(workspace, project_id)
    current = montage_section(ctx.state)["current_version"] if "montage" in ctx.state else None
    if not current:
        raise MontageError("ролик ещё не собран — показывать в папке нечего")
    shown = shown_output(ctx, current)
    if shown is None:
        raise MontageError(f"файла ролика {current} нет в папке media/{project_id}/montage — "
                           "соберите ролик заново")
    return render_output(ctx.media_root, project_id, current), shown

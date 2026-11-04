"""Маршруты экрана «Сборка»: `/api/projects/<id>/montage…`.

    GET  …/montage             дешёвое состояние (экран спрашивает раз в 5 с)
    GET  …/montage/model       схема слоёв (когда сменился index_key, версия или ревизия)
    POST …/montage/desk        {} → открыть стол; адрес страницы-переходника
    POST …/montage/desk/close  {} → закрыть стол
    POST …/montage/restore     {"version": "v001", "expected_revision": N}
    POST …/montage/reveal      {} → «Показать в папке» (файл текущей версии)

Любой POST доходит сюда только после `_authorize_write` (Origin и CSRF) — его
зовёт `StudioApplication.handle` до разбора маршрута. Тело POST — ровно по
схеме: у стола и папки это `{}`, путь к файлу из запроса не берётся никогда.
Отказ монтажа и запрет по стадии — 422 `montage_refused` с русским текстом в
`message`: запрет по стадии (`AuthoringError`) — наследник ValueError, и
`handle` превратил бы его в немой 400. Устаревшая ревизия — 409
`revision_conflict`, как у `/api/actions`."""

from __future__ import annotations

import re

from .authoring_support import AuthoringError
from .ledger import InvalidAction
from .montage import MontageError
from .montage.paths import VERSION_ID

ROUTE = re.compile(r"/api/projects/([^/]+)/montage(?:/(model|desk|desk/close|restore|reveal|styles|preview|build|export|preset|edit|save-style|open-edit))?")
_GET = {None: "status", "model": "model"}
_POST = {"desk": "open_desk", "desk/close": "close_desk", "reveal": "reveal"}
_RESTORE_KEYS = {"version", "expected_revision"}
_FAMILY_KEYS = {
    "preview": {"style", "duration"}, "build": {"expected_revision", "style", "improve"},
    "export": {"version"}, "preset": {"expected_revision", "expected_model_hash", "style"},
    "edit": {"expected_revision", "expected_model_hash", "edit"},
    "save-style": {"identity", "label"}, "open-edit": {"expected_revision"},
}


def match(path: str) -> tuple[str, str | None] | None:
    found = ROUTE.fullmatch(path)
    return (found.group(1), found.group(2)) if found else None


def _restore_args(request: dict) -> tuple[str, int]:
    version, revision = request["version"], request["expected_revision"]
    if not isinstance(version, str) or not VERSION_ID.fullmatch(version):
        raise InvalidAction("version must look like v001")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise InvalidAction("expected_revision must be a non-negative integer")
    return version, revision


def route(app, screen, method, project_id, part, headers, body):
    if screen is None:
        return app.error_response(404, "not_found")
    try:
        if method == "GET" and part == "styles":
            return app._json_response(200, screen.family(part, project_id, {}))
        if method == "POST" and part in _FAMILY_KEYS:
            request = app._parse_json(headers, body, _FAMILY_KEYS[part])
            if "expected_revision" in request and (type(request["expected_revision"]) is not int or request["expected_revision"] < 0):
                raise InvalidAction("invalid revision")
            if "expected_model_hash" in request and (not isinstance(request["expected_model_hash"], str) or not re.fullmatch(r"[a-f0-9]{16}", request["expected_model_hash"])):
                raise InvalidAction("current model hash is required")
            if part == "build" and type(request["improve"]) is not bool:
                raise InvalidAction("improve must be boolean")
            if part == "edit":
                from .montage.edit import EditRequest
                from dataclasses import fields
                if not isinstance(request["edit"], dict) or not set(request["edit"]).issubset({field.name for field in fields(EditRequest)}):
                    raise InvalidAction("typed edit required")
            return app._json_response(200, screen.family(part, project_id, request))
        if method == "GET" and part in _GET:
            return app._json_response(200, getattr(screen, _GET[part])(project_id))
        if method == "POST" and part == "restore":
            version, revision = _restore_args(app._parse_json(headers, body, _RESTORE_KEYS))
            return app._json_response(200, screen.restore(project_id, version, revision))
        if method == "POST" and part in _POST:
            app._parse_json(headers, body, set())
            return app._json_response(200, getattr(screen, _POST[part])(project_id))
    except (MontageError, AuthoringError) as error:
        from .agent_bridge import _sanitize_output
        return app.error_response(422, "montage_refused", message=_sanitize_output(str(error)))
    return app.error_response(404, "not_found")

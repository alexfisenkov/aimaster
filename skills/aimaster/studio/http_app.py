"""Testable, browser-safe HTTP boundary for the local creator studio."""

from __future__ import annotations

import copy
import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping
from urllib.parse import unquote, urlsplit

from .assets import AssetError, AssetIndex
from .ledger import (
    ActionLedger,
    ActionRequest,
    IdempotencyConflict,
    InvalidAction,
    LedgerError,
)
from .projection import ProjectionError, _sanitize_project, build_snapshot, sanitize_event
from .questions import (
    LateAnswerConflict,
    QuestionError,
    QuestionStore,
    QuestionValidationError,
)
from .store import ProjectNotFound, ProjectStore, RevisionConflict, StoreError


MAX_BODY_BYTES = 64 * 1024
_JSON_TYPE = "application/json; charset=utf-8"
_SSE_TYPE = "text/event-stream; charset=utf-8"
_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "img-src 'self'; media-src 'self'; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
_ACTION_KEYS = {
    "project_id",
    "action_type",
    "target_id",
    "payload",
    "expected_revision",
    "idempotency_key",
}
_ANSWER_KEYS = {"revision", "answer"}
_SINGLE_BYTE_RANGE = re.compile(r"bytes=(\d*)-(\d*)", re.IGNORECASE)

# Static UI hosting (amendment 2026-09-16 to ticket 05): only `GET /` and
# `GET /static/<path>` are served, only these three extensions are ever
# returned, and everything else — including a path that resolves outside
# this root, even via a symlink — is a 404. No directory listing.
_STATIC_ROOT = Path(__file__).resolve().parent / "static"
_STATIC_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
}


def _resolve_static(relative_path: str) -> Path | None:
    """Resolve a `/static/<relative_path>` request inside `_STATIC_ROOT`.

    Returns ``None`` (never raises) for anything that is not an existing
    regular file strictly inside the static root: absolute paths, empty or
    ``.``/``..`` segments (which also rejects ``//`` and a trailing slash),
    and any symlink that would resolve outside the root.
    """

    if not isinstance(relative_path, str) or not relative_path or relative_path.startswith("/"):
        return None
    segments = relative_path.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return None
    try:
        root = _STATIC_ROOT.resolve(strict=True)
        candidate = (root / relative_path).resolve(strict=True)
    except (OSError, ValueError):
        return None
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


def _security_headers(content_type: str) -> dict[str, str]:
    return {
        "Content-Type": content_type,
        "Cache-Control": "no-store",
        "Content-Security-Policy": _CSP,
        "Cross-Origin-Resource-Policy": "same-origin",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }


def _json_bytes(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidAction("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_value):
    raise InvalidAction("non-finite JSON number")


class StudioApplication:
    """Route HTTP-shaped requests without owning a socket or external operation."""

    def __init__(
        self,
        store: ProjectStore,
        ledger: ActionLedger,
        assets: AssetIndex,
        questions: QuestionStore,
        *,
        origin: str,
        csrf_token: str | None = None,
        event_source: Callable[[], Iterable[dict]] | None = None,
        max_body_bytes: int = MAX_BODY_BYTES,
    ):
        parsed_origin = urlsplit(origin)
        if (
            parsed_origin.scheme != "http"
            or parsed_origin.hostname != "127.0.0.1"
            or parsed_origin.port is None
            or parsed_origin.path
            or parsed_origin.query
            or parsed_origin.fragment
            or parsed_origin.username is not None
            or parsed_origin.password is not None
        ):
            raise ValueError("origin must be an exact IPv4 loopback HTTP origin")
        if (
            isinstance(max_body_bytes, bool)
            or not isinstance(max_body_bytes, int)
            or max_body_bytes <= 0
        ):
            raise ValueError("max_body_bytes must be a positive integer")
        if csrf_token is not None and (
            not isinstance(csrf_token, str) or not csrf_token
        ):
            raise ValueError("csrf_token must be a non-empty string")
        if event_source is not None and not callable(event_source):
            raise TypeError("event_source must be callable")
        self.store = store
        self.ledger = ledger
        self.assets = assets
        self.questions = questions
        self.origin = origin
        self.authority = parsed_origin.netloc
        self.csrf_token = csrf_token or secrets.token_urlsafe(32)
        self.event_source = event_source or (lambda: ())
        self.max_body_bytes = max_body_bytes

    @staticmethod
    def _headers(headers) -> dict[str, str]:
        if isinstance(headers, Mapping):
            items = headers.items()
        else:
            try:
                items = iter(headers)
            except TypeError as error:
                raise ValueError("headers must be a mapping or pairs") from error
        normalized = {}
        for key, value in items:
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("header names and values must be strings")
            lowered = key.casefold()
            if lowered in normalized:
                raise ValueError("duplicate request header")
            normalized[lowered] = value
        return normalized

    @staticmethod
    def _response(
        status: int,
        body: bytes,
        content_type: str,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Response:
        headers = _security_headers(content_type)
        if extra_headers:
            headers.update(extra_headers)
        return Response(status, headers, body)

    @classmethod
    def _json_response(cls, status: int, value) -> Response:
        return cls._response(status, _json_bytes(value), _JSON_TYPE)

    @classmethod
    def error_response(cls, status: int, code: str, **public_fields) -> Response:
        error = {"code": code}
        error.update(public_fields)
        return cls._json_response(status, {"error": error})

    def _parse_json(self, headers, body, expected_keys):
        if headers.get("content-type") != "application/json":
            raise InvalidAction("Content-Type must be application/json")
        if not isinstance(body, bytes):
            raise InvalidAction("body must be bytes")
        if len(body) > self.max_body_bytes:
            raise OverflowError("request body is too large")
        try:
            value = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidAction("body must contain one JSON value") from error
        if not isinstance(value, dict) or set(value) != expected_keys:
            raise InvalidAction("request keys do not match the route schema")
        return value

    def _authorize_write(self, headers):
        supplied_origin = headers.get("origin")
        supplied_token = headers.get("x-csrf-token")
        if supplied_origin != self.origin:
            raise PermissionError("forbidden origin")
        if supplied_token is None or not secrets.compare_digest(
            supplied_token, self.csrf_token
        ):
            raise PermissionError("invalid csrf token")

    @staticmethod
    def _path(raw_path):
        if not isinstance(raw_path, str) or not raw_path.startswith("/"):
            raise ValueError("request target must be origin-form")
        parsed = urlsplit(raw_path)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("query and absolute request targets are unsupported")
        try:
            return unquote(parsed.path, errors="strict")
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("request path is malformed") from error

    def handle(self, method, path, headers, body) -> Response:
        """Handle one request and return only a sanitized, fully buffered response."""

        try:
            request_headers = self._headers(headers)
            if request_headers.get("host") != self.authority:
                return self.error_response(403, "forbidden")
            if not isinstance(method, str):
                raise ValueError("method must be text")
            method = method.upper()
            request_path = self._path(path)
            if not isinstance(body, bytes):
                raise ValueError("body must be bytes")
            if len(body) > self.max_body_bytes:
                return self.error_response(413, "payload_too_large")
            if method == "POST":
                self._authorize_write(request_headers)
            elif body:
                return self.error_response(400, "bad_request")

            if method == "GET" and request_path == "/api/session":
                return self._json_response(200, {"csrf_token": self.csrf_token})
            if method == "GET" and request_path == "/api/projects":
                return self._projects()
            if method == "GET" and request_path == "/api/events":
                return self._events(request_headers)
            if method == "GET" and request_path.startswith("/api/projects/"):
                suffix = request_path.removeprefix("/api/projects/")
                if suffix.endswith("/snapshot"):
                    project_id = suffix[: -len("/snapshot")]
                    if project_id and "/" not in project_id:
                        return self._snapshot(project_id)
            if method == "GET" and request_path.startswith("/assets/"):
                asset_id = request_path.removeprefix("/assets/")
                if asset_id and "/" not in asset_id:
                    return self._asset(asset_id, request_headers.get("range"))
            if method == "GET" and request_path == "/":
                return self._static_file("index.html")
            if method == "GET" and request_path.startswith("/static/"):
                return self._static_file(request_path.removeprefix("/static/"))
            if method == "POST" and request_path == "/api/actions":
                return self._action(request_headers, body)
            if method == "POST" and request_path.startswith("/api/questions/"):
                suffix = request_path.removeprefix("/api/questions/")
                if suffix.endswith("/answers"):
                    question_id = suffix[: -len("/answers")]
                    if question_id and "/" not in question_id:
                        return self._answer(question_id, request_headers, body)
            if method in {"GET", "POST"}:
                return self.error_response(404, "not_found")
            response = self.error_response(405, "method_not_allowed")
            response.headers["Allow"] = "GET, POST"
            return response
        except PermissionError:
            return self.error_response(403, "forbidden")
        except OverflowError:
            return self.error_response(413, "payload_too_large")
        except RevisionConflict as error:
            return self.error_response(
                409, "revision_conflict", current_revision=error.current_revision
            )
        except ProjectionError:
            return self.error_response(500, "internal_error")
        except (InvalidAction, QuestionValidationError, ValueError, TypeError):
            return self.error_response(400, "bad_request")
        except IdempotencyConflict:
            return self.error_response(409, "idempotency_conflict")
        except (ProjectNotFound, AssetError, QuestionError):
            return self.error_response(404, "not_found")
        except (StoreError, LedgerError, OSError):
            return self.error_response(500, "internal_error")
        except Exception:
            return self.error_response(500, "internal_error")

    def _projects(self):
        projects = [
            _sanitize_project(item, f"projects[{index}]")
            for index, item in enumerate(self.store.list_projects())
        ]
        return self._json_response(200, {"projects": projects})

    def _snapshot(self, project_id):
        state = self.store.load(project_id)
        state = copy.deepcopy(state)
        state["questions"] = self.questions.pending(project_id)
        # Ticket 08 repair to remedy 1, condition 13: filled from the
        # ledger the same way `questions` above is filled from
        # `QuestionStore.pending` -- `state.json` itself never carries
        # `actions` (the ledger, not `ProjectStore`, is their source of
        # truth), so a reload previously reported an empty list
        # regardless of what the ledger actually held.
        state["actions"] = self.ledger.latest_actions_by_target(project_id)
        snapshot = build_snapshot(
            self.store.list_projects(),
            state,
            asset_url=lambda asset_id: f"/assets/{asset_id}",
            pending_actions=self.ledger.pending_actions(project_id),
        )
        return self._json_response(200, snapshot)

    def _action(self, headers, body):
        request = self._parse_json(headers, body, _ACTION_KEYS)
        action = self.ledger.enqueue(
            request["project_id"],
            ActionRequest(
                action_type=request["action_type"],
                target_id=request["target_id"],
                payload=request["payload"],
                expected_revision=request["expected_revision"],
                idempotency_key=request["idempotency_key"],
            ),
        )
        return self._json_response(
            202,
            {
                "action_id": action["action_id"],
                "revision": action["revision"],
                "status": action["status"],
            },
        )

    def _answer(self, question_id, headers, body):
        request = self._parse_json(headers, body, _ANSWER_KEYS)
        try:
            accepted = self.questions.answer(
                question_id, request["revision"], request["answer"], "dashboard"
            )
        except LateAnswerConflict as error:
            response = self.error_response(409, "already_answered")
            payload = json.loads(response.body)
            payload["accepted_answer"] = error.accepted_answer
            return self._json_response(409, payload)
        return self._json_response(200, accepted)

    @staticmethod
    def _requested_byte_range(value, length):
        if value is None or "," in value:
            return None
        match = _SINGLE_BYTE_RANGE.fullmatch(value.strip())
        if not match or not any(match.groups()):
            return None
        first, last = match.groups()
        if first:
            start = int(first)
            if start >= length:
                return "unsatisfiable"
            end = int(last) if last else length - 1
            if end < start:
                return None
            return start, min(end, length - 1)
        suffix = int(last)
        if suffix <= 0 or length <= 0:
            return "unsatisfiable"
        return max(0, length - suffix), length - 1

    def _asset(self, asset_id, range_header=None):
        path, mime_type = self.assets.resolve(asset_id)
        body = path.read_bytes()
        confirmed_path, confirmed_mime = self.assets.resolve(asset_id)
        if confirmed_path != path or confirmed_mime != mime_type:
            raise AssetError("asset identity changed while it was read")
        requested = self._requested_byte_range(range_header, len(body))
        headers = {"Accept-Ranges": "bytes"}
        if requested == "unsatisfiable":
            headers["Content-Range"] = f"bytes */{len(body)}"
            return self._response(416, b"", mime_type, headers)
        if requested is None:
            return self._response(200, body, mime_type, headers)
        start, end = requested
        headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
        return self._response(206, body[start : end + 1], mime_type, headers)

    def _static_file(self, relative_path: str) -> Response:
        resolved = _resolve_static(relative_path)
        if resolved is None:
            return self.error_response(404, "not_found")
        content_type = _STATIC_MIME_TYPES.get(resolved.suffix)
        if content_type is None:
            return self.error_response(404, "not_found")
        return self._response(200, resolved.read_bytes(), content_type)

    @staticmethod
    def _sse_frame(event):
        return (
            f"id: {event['event_id']}\n"
            f"event: {event['event_type']}\n"
            f"data: {_json_bytes(event).decode('utf-8')}\n\n"
        ).encode("utf-8")

    @staticmethod
    def _resync_event(raw_event, after_id, reason):
        raw_id = raw_event.get("event_id") if isinstance(raw_event, dict) else None
        event_id = (
            raw_id
            if isinstance(raw_id, int) and not isinstance(raw_id, bool) and raw_id >= 0
            else after_id + 1
        )
        raw_revision = raw_event.get("revision") if isinstance(raw_event, dict) else None
        revision = (
            raw_revision
            if isinstance(raw_revision, int)
            and not isinstance(raw_revision, bool)
            and raw_revision >= 0
            else 0
        )
        return sanitize_event(
            {
                "event_id": event_id,
                "revision": revision,
                "event_type": "snapshot_required",
                "payload": {"reason": reason},
            }
        )

    def _events(self, headers):
        raw_after = headers.get("last-event-id")
        if raw_after is None:
            after_id = -1
            has_cursor = False
        else:
            if not raw_after.isascii() or not raw_after.isdecimal():
                raise ValueError("Last-Event-ID must be a non-negative integer")
            after_id = int(raw_after)
            has_cursor = True
        raw_events = self.event_source()
        if not isinstance(raw_events, Iterable):
            raise TypeError("event source must return an iterable")
        selected = []
        for raw_event in raw_events:
            raw_id = raw_event.get("event_id") if isinstance(raw_event, dict) else None
            if isinstance(raw_id, int) and not isinstance(raw_id, bool) and raw_id <= after_id:
                continue
            selected.append(raw_event)
        if not selected:
            return self._response(200, b": keep-alive\n\n", _SSE_TYPE)

        expected_id = after_id + 1 if has_cursor else None
        previous_revision = None
        sanitized = []
        for raw_event in selected:
            raw_type = raw_event.get("event_type") if isinstance(raw_event, dict) else None
            if raw_type not in {
                "project_updated",
                "action_updated",
                "question_updated",
                "snapshot_required",
            }:
                signal = self._resync_event(raw_event, after_id, "unknown_event_type")
                return self._response(200, self._sse_frame(signal), _SSE_TYPE)
            try:
                event = sanitize_event(raw_event)
            except ProjectionError:
                signal = self._resync_event(raw_event, after_id, "invalid_event")
                return self._response(200, self._sse_frame(signal), _SSE_TYPE)
            if expected_id is not None and event["event_id"] != expected_id:
                signal = self._resync_event(raw_event, after_id, "event_gap")
                return self._response(200, self._sse_frame(signal), _SSE_TYPE)
            if previous_revision is not None and (
                event["revision"] < previous_revision
                or event["revision"] > previous_revision + 1
            ):
                signal = self._resync_event(raw_event, after_id, "revision_gap")
                return self._response(200, self._sse_frame(signal), _SSE_TYPE)
            sanitized.append(event)
            expected_id = event["event_id"] + 1
            previous_revision = event["revision"]
        return self._response(
            200, b"".join(self._sse_frame(event) for event in sanitized), _SSE_TYPE
        )

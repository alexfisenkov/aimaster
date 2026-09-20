"""Strict IPv4-loopback HTTP server for the local creator studio."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .assets import AssetIndex
from .decisions import DecisionWorker
from .events import LedgerEventSource
from .http_app import MAX_BODY_BYTES, StudioApplication
from .ledger import ActionLedger
from .questions import QuestionStore
from .store import ProjectStore
from .workspace import (
    ACTIONS_DB_NAME,
    ASSETS_DB_NAME,
    MAX_ASSET_BYTES,
    QUESTIONS_DB_NAME,
    resolve_workspace_paths,
)


class _LoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class _WakingLedger:
    """Wraps `ActionLedger` so a successful `enqueue` wakes the decision
    worker immediately, instead of leaving it to the next fallback poll.

    `http_app.StudioApplication` calls only `self.ledger.enqueue(...)` on
    whatever ledger-shaped object it is given (`_action`, its one route
    that writes); every other ledger method it might ever call is
    forwarded unchanged through `__getattr__`. This lets `serve()` add the
    wake-up at the one call site that actually creates new decision work
    -- `POST /api/actions` -- without editing `http_app.py` itself.
    """

    def __init__(self, ledger: ActionLedger, wake_event: threading.Event):
        self._ledger = ledger
        self._wake_event = wake_event

    def __getattr__(self, name):
        return getattr(self._ledger, name)

    def enqueue(self, project_id, request):
        action = self._ledger.enqueue(project_id, request)
        self._wake_event.set()
        return action


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _dispatch(self):
        try:
            raw_length = self.headers.get("Content-Length", "0")
            content_length = int(raw_length)
            if content_length < 0:
                raise ValueError
        except ValueError:
            response = self.server.application.error_response(400, "bad_request")
            self.close_connection = True
            self._write(response)
            return
        if content_length > MAX_BODY_BYTES:
            response = self.server.application.error_response(413, "payload_too_large")
            self.close_connection = True
            self._write(response)
            return
        body = self.rfile.read(content_length) if content_length else b""
        response = self.server.application.handle(
            self.command,
            self.path,
            list(self.headers.items()),
            body,
        )
        self._write(response)

    def _write(self, response):
        self.send_response(response.status)
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)

    do_GET = _dispatch
    do_POST = _dispatch
    do_HEAD = _dispatch
    do_OPTIONS = _dispatch
    do_PUT = _dispatch
    do_PATCH = _dispatch
    do_DELETE = _dispatch

    def log_message(self, format, *args):
        return


@dataclass(slots=True)
class RunningServer:
    base_url: str
    application: StudioApplication
    _server: _LoopbackHTTPServer
    _thread: threading.Thread
    _decision_worker: DecisionWorker
    _closed: bool = field(default=False, init=False)

    def close(self):
        if self._closed:
            return
        self._closed = True
        # Ticket 11: the decision worker's own background thread stops
        # first (it only reads/writes the store and ledger, never the
        # socket), then the HTTP server -- neither ordering can leak a
        # thread, but stopping the worker first means no new decision
        # starts applying after the HTTP layer that reported it has
        # already gone down.
        self._decision_worker.stop()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def serve(workspace: Path, host: str = "127.0.0.1", port: int = 0) -> RunningServer:
    """Start the studio on an OS-assigned port, never outside IPv4 loopback."""

    if host != "127.0.0.1":
        raise ValueError("creator studio may bind only to 127.0.0.1")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("port must be an integer between 0 and 65535")

    # Repair, 2026-09-16 (ticket 09, condition 13; filenames centralized in
    # the second repair, condition 5): `resolve_workspace_paths` and the
    # `actions.sqlite3`/`questions.sqlite3` names both live in
    # `studio/workspace.py` now — the one canonical resolver for
    # `projects/`/`media/`/`.studio/`, shared with the CLI
    # (`runner.open_ledger`) instead of either module keeping its own copy.
    workspace, project_root, media_root, private_root = resolve_workspace_paths(workspace)
    # Repair, 2026-09-17 (ticket 12 repair, condition 1): `media_root` no
    # longer falls back to `workspace` when absent (see
    # `workspace.resolve_workspace_paths`) -- a security boundary has no
    # safe fallback. A running server creates its own dedicated, empty
    # `media/` directory instead: it should not refuse to start just
    # because chat has not registered anything yet, and this keeps the
    # allowed root a real subdirectory, never the workspace itself.
    media_root.mkdir(parents=True, exist_ok=True)
    actions_db_path = private_root / ACTIONS_DB_NAME
    store = ProjectStore(project_root, excluded=())
    ledger = ActionLedger(
        actions_db_path,
        revision_resolver=lambda project_id: store.load(project_id)["revision"],
    )
    questions = QuestionStore(private_root / QUESTIONS_DB_NAME)
    # Ticket 12: `db_path` is explicit and shared with the authoring CLI
    # (`studio.authoring.open_assets`, via the same `resolve_workspace_paths`
    # call) so both open the identical durable `AssetIndex` file -- an asset
    # the CLI registers as a separate process resolves here without a
    # restart, and the reverse.
    assets = AssetIndex(
        workspace,
        (media_root,),
        max_bytes=MAX_ASSET_BYTES,
        db_path=private_root / ASSETS_DB_NAME,
    )
    # Repair, 2026-09-16 (ticket 09, condition 1): events are read straight
    # out of the ledger's own durable `action_events` table — `ActionLedger`
    # is the only writer, inside its own transaction, so there is no second
    # journal and no gap for a crash to drop an event into. `claim`/
    # `finish`/`recover` run as a separate CLI process from this one;
    # SQLite WAL lets both safely read/write the same file concurrently.
    # See `studio/events.py`. Ticket 11: `store` is passed too, so a
    # succeeded decision's event can carry `current_stage`/`stage_revision`
    # (`events._decision_stage_fields`) -- read-only, never written here.
    events = LedgerEventSource(actions_db_path, store=store)

    # The decision worker waits on this between polls; `_WakingLedger`
    # below sets it the moment `POST /api/actions` enqueues new work, so
    # the worker does not have to wait out its own fallback poll interval
    # to notice. Created once here so both sides -- the worker and the
    # wrapped ledger the HTTP layer writes through -- share the exact same
    # `threading.Event`.
    wake_event = threading.Event()
    decision_worker = DecisionWorker(store, ledger, wake_event=wake_event)

    httpd = _LoopbackHTTPServer((host, port), _Handler)
    assigned_port = httpd.server_address[1]
    base_url = f"http://127.0.0.1:{assigned_port}"
    application = StudioApplication(
        store,
        _WakingLedger(ledger, wake_event),
        assets,
        questions,
        origin=base_url,
        event_source=events,
    )
    httpd.application = application
    thread = threading.Thread(
        target=httpd.serve_forever,
        name=f"creator-studio-{assigned_port}",
        daemon=True,
    )
    thread.start()

    # Ticket 11: the in-process worker that actually applies a dashboard
    # decision (`approve-scenario`, `approve`/`reject`, `edit`, `hide`/
    # `unhide`, `retire`/`restore`, `reorder`) to canonical state. It reads
    # the same `store`/`ledger` the HTTP layer above uses -- `ProjectStore`
    # and `ActionLedger` are already safe for concurrent access from
    # multiple threads (per-project file lock; SQLite WAL) -- and claims
    # only `decisions.DECISION_ACTION_TYPES`, the queue's chat-only actions
    # (`runner.CHAT_ACTION_TYPES`) are never touched here. Started after the
    # HTTP thread so a worker failure can never prevent the server itself
    # from coming up; stopped from `RunningServer.close()`.
    decision_worker.start()

    return RunningServer(base_url, application, httpd, thread, decision_worker)

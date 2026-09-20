"""Ledger-derived, durable event source for `StudioApplication`.

Repair, 2026-09-16 (ticket 09, condition 1). The first build of this task
kept a *second* journal (`runner.EventLog`, now deleted) and wrote to it
from `Runner.claim`/`finish`/`recover` right after each ledger call
committed. That shape has two holes: a crash between the ledger commit and
the second write drops the event forever, and nothing made a browser
`POST /api/actions` observable at all — `StudioApplication._action`
(`http_app.py`, task 04/05's zone, not touched here) calls
`ActionLedger.enqueue` directly and never knew the old `EventLog` existed.

`ActionLedger` already appends one `action_events` row *inside the same
SQLite transaction* as every status transition — `enqueue`, `claim_next`,
`finish`, and both `recover_inflight` branches (see `studio/ledger.py`).
That table is already the atomic, durable source of truth for "what
changed and when"; this module only reads it. `project_id` and
`target_id` are not columns on `action_events` itself, but they are set
once on `actions` at INSERT time and never updated afterwards (only
`status`/`worker_id`/`public_result_json`/`external_id`/`updated_at`
change), so a join against the current `actions` row is exactly as
trustworthy as storing a second copy of those two columns would have been
— without a schema change or a second write path.

Second repair, 2026-09-16 (ticket 09, condition 2). Ticket 11's in-process
decision worker is documented (interfaces.md, "Из таска 09"/"Из таска 11")
to call `ActionLedger.finish` directly — bypassing `Runner` and
`adapters.validate_public_result` entirely, because normalizing a
decision's own result is that worker's job, not this reader's.
`ActionLedger.finish` itself only redacts credential-shaped values; it
does not enforce the browser-safety allowlist. A single such row (an
unknown key, or free text that trips `projection._safe_system_text`'s
denylist) used to make `sanitize_event` raise inside `_row_to_event`,
`read_all` propagate that unguarded, and `StudioApplication.handle`'s
blanket `except ProjectionError: 500` take down the *entire* `/api/events`
response — forever, since the bad row never leaves the table. See
`_row_to_event` below for the fix: one bad row becomes one
`snapshot_required` resync at its own id, and every row around it is
still served normally.

Addition, 2026-09-16 (ticket 11). A *decision* (`decisions.DECISION_
ACTION_TYPES` — everything in `ledger.ACTION_TYPES` that is not a chat
action) that reaches `succeeded` changed the project's canonical state,
not just one action's own bookkeeping — the dashboard needs to know to
refetch the project snapshot, which a plain `action_updated` row does not
signal on its own. That transition becomes `event_type: "project_updated"`
here, with `current_stage`/`stage_revision` attached, entirely at *read*
time: no second write, no second row. `project_id`/`target_id` were
already read this way (via the `actions` join, see the first repair note
above); `current_stage`/`stage_revision` are the same idea taken one step
further — read fresh from the project's own durable `state.json`
(`ProjectStore.load` + `domain.derive_view_stage`, both already the
single source of truth for stage) rather than duplicated into a second
place that could drift from it. A `store` this reader cannot use (not
given, or the read itself fails) degrades the same way a bad row does —
one `snapshot_required` resync at that row's own id, never a raised
exception and never a `project_updated` missing the fields the ticket 11
acceptance criteria require it to carry.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .decisions import DECISION_ACTION_TYPES
from .domain import derive_view_stage
from .projection import ProjectionError, sanitize_event


_SELECT_ACTION_EVENTS = """
    SELECT
        ae.event_id AS event_id,
        ae.action_id AS action_id,
        ae.to_status AS to_status,
        ae.detail_json AS detail_json,
        a.project_id AS project_id,
        a.target_id AS target_id,
        a.action_type AS action_type
    FROM action_events ae
    JOIN actions a ON a.action_id = ae.action_id
    ORDER BY ae.event_id ASC
"""


def _resync_for_row(row: sqlite3.Row) -> dict:
    """One `snapshot_required` resync standing in for a row served raw.

    Second repair, condition 2. Reuses the bad row's own `event_id` (and
    `revision`, kept equal to it by the same convention `_row_to_event`
    uses below) instead of skipping it, so the id/revision sequence
    `http_app._events` walks stays gapless: a client that reconnects with
    `Last-Event-ID` set to this id resumes with whatever comes right after
    it — no repeated resync, no spurious `event_gap`. This dict is built
    from fixed, known-safe values only, so `sanitize_event` here cannot
    itself fail.
    """

    return sanitize_event(
        {
            "event_id": row["event_id"],
            "revision": row["event_id"],
            "event_type": "snapshot_required",
            "payload": {"reason": "invalid_event"},
        }
    )


def _decision_stage_fields(store, project_id):
    """`current_stage`/`stage_revision` for one project, or `None` to degrade.

    Addition, ticket 11. `None` covers every reason this cannot be
    answered right now — no `store` was given, the project is gone, or its
    `state.json` fails a domain check — uniformly, so the caller always has
    a single safe fallback (`_resync_for_row`) rather than a set of cases
    to keep in sync with `ProjectStore`/`domain`'s own exception types.
    """

    if store is None:
        return None
    try:
        view_stage = derive_view_stage(store.load(project_id))
    except Exception:
        return None
    return {
        "current_stage": view_stage["current_stage"],
        "stage_revision": view_stage["stage_revision"],
    }


def _cached_decision_stage_fields(store, project_id, stage_cache):
    """`_decision_stage_fields`, read at most once per project per `read_all()` call.

    Without this cache, every `succeeded` decision row for the same
    project would re-read that project's `state.json` from disk — a
    project history with N such rows would cost N reads for one
    `/api/events` request instead of one. `stage_cache` is a plain dict
    `read_all` creates fresh for its own call and passes down through
    every row of *that* call only — never stored on `self`, since a
    decision can succeed *between* two separate `/api/events` requests and
    the second one must see the fresh stage, not a stale one from the
    first. A project that failed to load is cached too (as `None`): a
    deleted or corrupt project degrades every one of its rows to
    `_resync_for_row` without retrying the failing load for each.
    """

    if project_id not in stage_cache:
        stage_cache[project_id] = _decision_stage_fields(store, project_id)
    return stage_cache[project_id]


def _row_to_event(row: sqlite3.Row, store, stage_cache: dict) -> dict:
    """Convert one `action_events` row; never raises past this function.

    Second repair, condition 2 (see the module docstring): a row this
    reader cannot serve raw — an unknown `public_result` key, or text that
    trips the browser-safety denylist — degrades to `_resync_for_row`
    instead of raising out of `read_all`.

    Addition, ticket 11: a *decision* action (`action_type` outside
    `decisions.DECISION_ACTION_TYPES`'s complement, i.e. not a chat action)
    that reached `succeeded` is reclassified `project_updated` with
    `current_stage`/`stage_revision` attached — see
    `_cached_decision_stage_fields` and the module docstring. Every other
    row (every chat-action transition, and every non-succeeded decision
    transition — `queued`, `running`, `failed`, ...) is unaffected and
    stays `action_updated`, exactly as before this ticket.
    """

    detail = json.loads(row["detail_json"])
    payload = {
        "project_id": row["project_id"],
        "action_id": row["action_id"],
        "target_id": row["target_id"],
        "status": row["to_status"],
    }
    public_result = detail.get("public_result") if isinstance(detail, dict) else None
    if isinstance(public_result, dict):
        payload["public_result"] = public_result

    event_type = "action_updated"
    if row["action_type"] in DECISION_ACTION_TYPES and row["to_status"] == "succeeded":
        stage_fields = _cached_decision_stage_fields(store, row["project_id"], stage_cache)
        if stage_fields is None:
            return _resync_for_row(row)
        event_type = "project_updated"
        payload.update(stage_fields)

    try:
        return sanitize_event(
            {
                # `event_id` is already a gapless, strictly increasing SQLite
                # AUTOINCREMENT sequence — a rolled-back transaction never
                # advances it (see `ActionLedger._transaction`). Reusing it as
                # `revision` too keeps `revision` monotonic across every
                # project and action mixed into one stream, which is what
                # `http_app._events`'s gap detector requires. A project's own
                # canonical revision (`ActionRequest.expected_revision`) is a
                # *different* number that jumps around between projects and
                # has no business being the SSE cursor (ticket 09 repair,
                # condition 2).
                "event_id": row["event_id"],
                "revision": row["event_id"],
                "event_type": event_type,
                "payload": payload,
            }
        )
    except ProjectionError:
        return _resync_for_row(row)


class LedgerEventSource:
    """`Callable[[], Iterable[dict]]` reading `action_events` as `event_source`.

    A read-only view over the ledger's own SQLite file — `ActionLedger` is
    the only writer, always inside its own transaction, so there is no
    second commit for a crash to land between. Every row is re-validated
    through `projection.sanitize_event` before it can leave this module:
    an unknown key or a disallowed value never reaches `/api/events` raw.
    That row does not make `read_all` raise either — `_row_to_event`
    degrades it to one `snapshot_required` resync at its own id instead,
    so one bad row can no longer take the whole stream down with it; see
    that function.

    `store` is optional and read-only here (never written): without it
    every row behaves exactly as `action_updated`, which is what every
    caller that constructs this class positionally, with no `store`,
    keeps getting. `server.serve()` passes its own `ProjectStore` so a
    succeeded decision can carry `current_stage`/`stage_revision` — see
    `_decision_stage_fields`. `read_all()` reads a project's `state.json`
    at most once per call, not once per historical decision row for that
    project — see `_cached_decision_stage_fields`.
    """

    def __init__(self, ledger_db_path, *, store=None):
        self.ledger_db_path = Path(ledger_db_path)
        self.store = store

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.ledger_db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def read_all(self) -> list[dict]:
        if not self.ledger_db_path.exists():
            return []
        connection = self._connect()
        try:
            rows = connection.execute(_SELECT_ACTION_EVENTS).fetchall()
        finally:
            connection.close()
        # One cache per call (condition 7), never per instance: a decision
        # can succeed between two separate `/api/events` requests, and the
        # next request must see that fresh stage, not one memoized on `self`
        # from an earlier call.
        stage_cache: dict = {}
        return [_row_to_event(row, self.store, stage_cache) for row in rows]

    def __call__(self) -> Iterable[dict]:
        return self.read_all()

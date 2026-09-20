"""Durable action, one-use grant and recovery ledger.

The ledger owns authorization reservation and action lifecycle only.  It never
executes an external operation and never persists values whose field names mark
them as credentials.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .status_messages import STATUS_MESSAGE_RU
from .store import RevisionConflict


ACTION_TYPES = frozenset(
    {
        "approve-scenario",
        "revise-scenario",
        "continue-in-chat",
        "approve",
        "reject",
        "edit",
        "vary",
        "regenerate",
        "hide",
        "unhide",
        "retire",
        "restore",
        "reorder",
        "scene-add",
        "reference-add",
        "reference-edit",
        "scene-reference-toggle",
        "scene-frame-plan",
        "set-gen-mode",
        "set-video-mode",
        "set-mode",
        "generate",
        "prompts-generate",
        "prompt-refresh",
        "assemble",
        # Ticket 15 (G05): the dashboard's door onto
        # `decision_stages.build_reopen_mutation` -- claimed by
        # `decisions.DecisionWorker` (it is not a `runner.
        # CHAT_ACTION_TYPES` member), never granted (not in
        # `GRANT_REQUIRED_ACTIONS` below).
        "reopen-scenario",
    }
)
ACTION_STATUSES = frozenset(
    {
        "queued",
        "running",
        "succeeded",
        "failed",
        "needs_chat",
        "needs_chat_setup",
        "outcome_unknown",
    }
)
TERMINAL_STATUSES = frozenset(
    {"succeeded", "failed", "needs_chat", "needs_chat_setup", "outcome_unknown"}
)
GRANT_REQUIRED_ACTIONS = frozenset({"vary", "regenerate", "generate"})
_GENERATION_CLASS = "generation"
_REDACTED = "[redacted]"
_SECRET_FIELD = re.compile(
    r"(?:^|[_-])(token|password|passwd|secret|credential|cookie|authorization|"
    r"api[_-]?key|access[_-]?key|private[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"\b(?:authorization|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
    r"password|passwd|secret|credential)\s*[:=]\s*(?:bearer\s+)?\S+",
    re.IGNORECASE,
)
_SAFE_EXTERNAL_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_CREDENTIAL_ID_MARKERS = (
    "accesstoken",
    "refreshtoken",
    "apikey",
    "secretkey",
    "accesskey",
    "privatekey",
    "authorization",
    "credential",
    "password",
    "passwd",
    "bearer",
    "cookie",
    "secret",
    "token",
)


class LedgerError(RuntimeError):
    """Base action-ledger failure."""


class InvalidAction(LedgerError, ValueError):
    """An action request does not satisfy the ledger contract."""


class IdempotencyConflict(LedgerError):
    """An idempotency key was reused for a different action request."""


class InvalidTransition(LedgerError):
    """An action cannot move from its durable current state as requested."""


class ActionNotFound(LedgerError):
    """No durable action exists for the supplied id."""


class RevisionResolutionError(LedgerError):
    """The canonical project revision could not be resolved safely."""


@dataclass(frozen=True, slots=True)
class ActionRequest:
    action_type: str
    target_id: str
    payload: dict
    expected_revision: int
    idempotency_key: str


def _utc_now():
    return datetime.now(timezone.utc)


def _timestamp(value=None):
    current = _utc_now() if value is None else value
    return current.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _non_empty_string(value, label):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise InvalidAction(f"{label} must be a non-empty string")
    return value


def _revision(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidAction("expected_revision must be a non-negative integer")
    return value


def _external_id(value):
    if value is None:
        return None
    normalized = (
        re.sub(r"[^a-z0-9]", "", value.casefold())
        if isinstance(value, str)
        else ""
    )
    if (
        not isinstance(value, str)
        or not _SAFE_EXTERNAL_ID.fullmatch(value)
        or any(marker in normalized for marker in _CREDENTIAL_ID_MARKERS)
    ):
        raise InvalidAction("external_id must be a safe opaque identifier")
    return value


def _redact(value, *, field_name=None, depth=0):
    if depth > 32:
        raise InvalidAction("payload nesting is too deep")
    if field_name is not None and _SECRET_FIELD.search(field_name):
        return _REDACTED
    if isinstance(value, str):
        return _REDACTED if _SECRET_VALUE.search(value) else value
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidAction("payload keys must be strings")
            cleaned[key] = _redact(item, field_name=key, depth=depth + 1)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth=depth + 1) for item in value]
    raise InvalidAction("payload values must be JSON-compatible")


def _json(value):
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise InvalidAction("payload values must be JSON-compatible") from error


def _expiry(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as error:
            raise InvalidAction("expires_at must be an ISO-8601 timestamp") from error
    else:
        raise InvalidAction("expires_at must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidAction("expires_at must include a timezone")
    parsed = parsed.astimezone(timezone.utc)
    return _timestamp(parsed), parsed.timestamp()


def normalize_recovery_decision(decision) -> dict:
    """Normalize one raw verifier decision into a plain `{"status": ..., ...}` dict.

    Repair, 2026-09-16 (ticket 09 third repair, condition 4): a non-dict
    decision, and a decision whose `status` is neither `"not_started"` nor
    a member of `TERMINAL_STATUSES`, used to be normalized twice — once
    here for `recover_inflight`'s own direct callers (this module's own
    tests included), and a second, line-for-line copy of the same checks
    inside `runner.Runner.recover`'s `validated_verifier` wrapper, purely
    so that wrapper could inspect `status` before deciding whether to call
    `adapters.validate_public_result`. Both call this shared function now
    instead — `Runner`'s wrapper to decide what to do next, and
    `recover_inflight` again on the wrapper's own return value, which is
    already normalized and so passes through unchanged. Never inspects or
    validates `public_result`'s *content* — that stays adapters-only; this
    only decides what `status` a decision means.

    Repair, 2026-09-16 (ticket 09, second attempt, condition 2): a bare
    string used to be special-cased as shorthand for
    `{"status": <that string>}` — so a verifier returning literally
    `"not_started"` could requeue an action, and one returning
    `"succeeded"` could finish it, with no dict, no other field, ever
    inspected. That shorthand is gone: an unrecognized decision — missing
    `status`, an unfamiliar `status`, a bare string, or anything else that
    is not a dict — is treated identically now and always becomes
    `outcome_unknown`, never `"not_started"`. An unrecognized decision can
    therefore never put an action back in `queued` (spec §9); only a dict
    that actually carries `status: "not_started"` can.
    """

    if not isinstance(decision, dict):
        return {"status": "outcome_unknown"}
    status = decision.get("status")
    if status != "not_started" and status not in TERMINAL_STATUSES:
        decision = {**decision, "status": "outcome_unknown"}
    return decision


class ActionLedger:
    """SQLite-backed source of truth for action authorization and lifecycle."""

    def __init__(self, db_path, revision_resolver=None):
        if revision_resolver is not None and not callable(revision_resolver):
            raise TypeError("revision_resolver must be callable")
        self.db_path = Path(db_path)
        self.revision_resolver = revision_resolver
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(
            self.db_path,
            timeout=30,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self):
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS grants (
                    grant_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    action_class TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    expires_epoch REAL NOT NULL,
                    issued_at TEXT NOT NULL,
                    reserved_action_id TEXT UNIQUE,
                    reserved_at TEXT
                );

                CREATE TABLE IF NOT EXISTS actions (
                    action_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    expected_revision INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    grant_id TEXT UNIQUE REFERENCES grants(grant_id),
                    status TEXT NOT NULL,
                    worker_id TEXT,
                    public_result_json TEXT,
                    external_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS action_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id TEXT NOT NULL REFERENCES actions(action_id),
                    from_status TEXT,
                    to_status TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS actions_claimable
                    ON actions(status, created_at, action_id);
                CREATE INDEX IF NOT EXISTS grants_available
                    ON grants(project_id, action_class, expires_epoch, issued_at)
                    WHERE reserved_action_id IS NULL;
                CREATE INDEX IF NOT EXISTS actions_latest_by_target
                    ON actions(project_id, action_type, target_id, created_at, action_id);

                CREATE TRIGGER IF NOT EXISTS action_events_no_update
                BEFORE UPDATE ON action_events
                BEGIN
                    SELECT RAISE(ABORT, 'action_events are append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS action_events_no_delete
                BEFORE DELETE ON action_events
                BEGIN
                    SELECT RAISE(ABORT, 'action_events are append-only');
                END;
                """
            )
        finally:
            connection.close()
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    @contextmanager
    def _transaction(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _event(connection, action_id, from_status, to_status, detail=None):
        connection.execute(
            "INSERT INTO action_events "
            "(action_id, from_status, to_status, detail_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                action_id,
                from_status,
                to_status,
                _json(_redact(detail or {})),
                _timestamp(),
            ),
        )

    @staticmethod
    def _action(row):
        if row is None:
            return None
        result = {
            "action_id": row["action_id"],
            "project_id": row["project_id"],
            "revision": row["expected_revision"],
            "action_type": row["action_type"],
            "target_id": row["target_id"],
            "payload": json.loads(row["payload_json"]),
            "idempotency_key": row["idempotency_key"],
            "grant_id": row["grant_id"],
            "status": row["status"],
            "worker_id": row["worker_id"],
            "public_result": (
                json.loads(row["public_result_json"])
                if row["public_result_json"] is not None
                else None
            ),
            "external_id": row["external_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        return copy.deepcopy(result)

    @staticmethod
    def _fetch_action(connection, action_id):
        return connection.execute(
            "SELECT * FROM actions WHERE action_id = ?", (action_id,)
        ).fetchone()

    def _resolve_revision(self, project_id):
        if self.revision_resolver is None:
            raise RevisionResolutionError("canonical revision resolver is required")
        try:
            revision = self.revision_resolver(project_id)
        except RevisionConflict:
            raise
        except Exception as error:
            raise RevisionResolutionError("cannot resolve canonical revision") from error
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise RevisionResolutionError(
                "canonical revision must be a non-negative integer"
            )
        return revision

    def _verify_revision(self, project_id, expected_revision):
        current_revision = self._resolve_revision(project_id)
        if current_revision != expected_revision:
            raise RevisionConflict(expected_revision, current_revision)

    def issue_grant(self, project_id, action_class, expires_at) -> str:
        project_id = _non_empty_string(project_id, "project_id")
        action_class = _non_empty_string(action_class, "action_class")
        if action_class not in GRANT_REQUIRED_ACTIONS | {_GENERATION_CLASS}:
            raise InvalidAction("action_class does not authorize an external action")
        expires_text, expires_epoch = _expiry(expires_at)
        grant_id = f"grant-{uuid.uuid4().hex}"
        with self._transaction() as connection:
            connection.execute(
                "INSERT INTO grants "
                "(grant_id, project_id, action_class, expires_at, expires_epoch, issued_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    grant_id,
                    project_id,
                    action_class,
                    expires_text,
                    expires_epoch,
                    _timestamp(),
                ),
            )
        return grant_id

    def enqueue(self, project_id, request) -> dict:
        project_id = _non_empty_string(project_id, "project_id")
        if not isinstance(request, ActionRequest):
            raise InvalidAction("request must be an ActionRequest")
        action_type = _non_empty_string(request.action_type, "action_type")
        if action_type not in ACTION_TYPES:
            raise InvalidAction("unsupported action_type")
        target_id = _non_empty_string(request.target_id, "target_id")
        idempotency_key = _non_empty_string(
            request.idempotency_key, "idempotency_key"
        )
        expected_revision = _revision(request.expected_revision)
        if not isinstance(request.payload, dict):
            raise InvalidAction("payload must be an object")
        redacted_payload = _redact(request.payload)
        if redacted_payload != request.payload:
            raise InvalidAction(
                "payload contains credential-like text that cannot be persisted unchanged"
            )
        payload_json = _json(redacted_payload)

        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM actions WHERE project_id = ? AND idempotency_key = ?",
                (project_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                same_request = (
                    existing["action_type"] == action_type
                    and existing["target_id"] == target_id
                    and existing["payload_json"] == payload_json
                    and existing["expected_revision"] == expected_revision
                )
                if not same_request:
                    raise IdempotencyConflict(
                        "idempotency key belongs to a different action request"
                    )
                return self._action(existing)

            self._verify_revision(project_id, expected_revision)

            action_id = f"action-{uuid.uuid4().hex}"
            grant_id = None
            status = "queued"
            if action_type in GRANT_REQUIRED_ACTIONS:
                grant = connection.execute(
                    "SELECT grant_id FROM grants "
                    "WHERE project_id = ? AND action_class IN (?, ?) "
                    "AND reserved_action_id IS NULL AND expires_epoch > ? "
                    "ORDER BY CASE action_class WHEN ? THEN 0 ELSE 1 END, "
                    "expires_epoch, issued_at, grant_id LIMIT 1",
                    (
                        project_id,
                        action_type,
                        _GENERATION_CLASS,
                        _utc_now().timestamp(),
                        action_type,
                    ),
                ).fetchone()
                if grant is None:
                    status = "needs_chat"
                else:
                    grant_id = grant["grant_id"]
                    reserved = connection.execute(
                        "UPDATE grants SET reserved_action_id = ?, reserved_at = ? "
                        "WHERE grant_id = ? AND reserved_action_id IS NULL",
                        (action_id, _timestamp(), grant_id),
                    )
                    if reserved.rowcount != 1:
                        raise LedgerError("grant reservation lost inside transaction")

            now = _timestamp()
            connection.execute(
                "INSERT INTO actions "
                "(action_id, project_id, action_type, target_id, payload_json, "
                "expected_revision, idempotency_key, grant_id, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    action_id,
                    project_id,
                    action_type,
                    target_id,
                    payload_json,
                    expected_revision,
                    idempotency_key,
                    grant_id,
                    status,
                    now,
                    now,
                ),
            )
            self._event(
                connection,
                action_id,
                None,
                status,
                {"grant_id": grant_id, "grant_reserved": grant_id is not None},
            )
            # Resolve again after every planned mutation.  A canonical change
            # observed while this SQLite transaction is open rolls back the
            # action, event and any one-use grant reservation together.
            self._verify_revision(project_id, expected_revision)
            return self._action(self._fetch_action(connection, action_id))

    def claim_next(self, worker_id, action_types=None) -> dict | None:
        worker_id = _non_empty_string(worker_id, "worker_id")
        if action_types is None:
            with self._transaction() as connection:
                row = connection.execute(
                    "SELECT * FROM actions WHERE status = 'queued' "
                    "ORDER BY created_at, action_id LIMIT 1"
                ).fetchone()
                return self._claim_row(connection, row, worker_id)

        # Amendment 2026-09-16 (ticket 09, point 5): an explicit filter lets
        # the chat runner and the in-process decision worker (task 11) split
        # ACTION_TYPES into two disjoint claimable queues without either one
        # ever seeing the other's rows. `None` above keeps the original,
        # unfiltered query byte-for-byte so default behaviour is unchanged.
        action_types = frozenset(action_types)
        if not action_types or not action_types.issubset(ACTION_TYPES):
            raise InvalidAction("action_types must be a non-empty subset of ACTION_TYPES")
        placeholders = ", ".join("?" for _ in action_types)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM actions WHERE status = 'queued' "
                f"AND action_type IN ({placeholders}) "
                "ORDER BY created_at, action_id LIMIT 1",
                tuple(action_types),
            ).fetchone()
            return self._claim_row(connection, row, worker_id)

    def _claim_row(self, connection, row, worker_id):
        if row is None:
            return None
        action_id = row["action_id"]
        changed = connection.execute(
            "UPDATE actions SET status = 'running', worker_id = ?, updated_at = ? "
            "WHERE action_id = ? AND status = 'queued'",
            (worker_id, _timestamp(), action_id),
        )
        if changed.rowcount != 1:
            raise LedgerError("action claim lost inside transaction")
        self._event(
            connection,
            action_id,
            "queued",
            "running",
            {"worker_id": worker_id},
        )
        return self._action(self._fetch_action(connection, action_id))

    def finish(self, action_id, status, public_result, external_id=None) -> dict:
        return self._finish(action_id, status, public_result, external_id, release_grant=False)

    def finish_and_release_grant(self, action_id, status, public_result, external_id=None) -> dict:
        """`finish`, plus releasing this action's own reserved grant (if
        it had one) back to available, in the very same atomic
        transaction as the status change.

        Ticket 15 repair, поправка оркестратора 12 ("отказ шлюза
        освобождает зарезервированный grant: разрешение на один запуск не
        сгорает без запуска"). The one caller, `runner.Runner.
        _refuse_claim`, finishes an action a claim-time gate refused
        *before* it was ever handed to chat: a `vary`/`regenerate`
        reserves a grant at `enqueue` time (see `enqueue` above), and that
        reservation authorizes exactly one external attempt. If the gate
        refuses the action before any external call was ever made, that
        attempt never happened, so the reservation must not be spent by
        this refusal — the same still-fresh grant is available to a
        follow-up `enqueue` for the same project/class, with no new grant
        needed from chat. This also clears the refused action's own
        `grant_id` back to `NULL` (never merely `grants.reserved_
        action_id`, the grant row's own half): `actions.grant_id` is
        `UNIQUE`, so a grant can back at most one action row across the
        table's whole history, and a follow-up `enqueue` reserving the
        now-available grant would otherwise fail its own `INSERT` the
        instant it tried to claim a `grant_id` this row still held.

        Every other finisher is different, and must not release anything:
        plain `finish` (a chat-reported outcome once a job package
        genuinely reached chat — the grant *was* already spent the
        instant `Runner.claim` handed it out, regardless of what status
        the action eventually finishes with) and `_finish_recovered`
        (recovery resolves an action already claimed the same way).
        Releasing there too would let the same one-use grant authorize a
        second external attempt after the first one actually happened —
        exactly the silent auto-retry spec §5 forbids.

        Same validation and idempotent-retry contract as `finish`: a
        second call with byte-identical `status`/`public_result`/
        `external_id` against an already-matching terminal row returns
        that row rather than re-executing (the grant, if any, was already
        released by the call that actually made the transition, so
        nothing here needs to run again).

        Craft review, third pass: this method and `finish` used to be
        two independently hand-written copies of the same argument
        checks, idempotent-retry short circuit and status-transition
        rules, with only the grant-release block actually different
        between them. `_finish` below is now the one implementation;
        `release_grant` is the sole difference between the two public
        names, not a second body to keep in sync by hand whenever either
        one changes. Neither `finish`'s nor `_finish_recovered`'s own
        behavior changes here -- `_finish_recovered` was never part of
        this duplication (it never released a grant, and its own
        idempotent-retry rule is deliberately looser, see its own
        docstring) and is not touched by this merge at all.
        """

        return self._finish(action_id, status, public_result, external_id, release_grant=True)

    def _finish(
        self, action_id, status, public_result, external_id, *, release_grant: bool
    ) -> dict:
        """`finish`'s and `finish_and_release_grant`'s shared body.

        Argument validation, the idempotent-retry short circuit and the
        `running -> terminal` transition are identical either way;
        `release_grant` alone decides whether this call also releases
        the action's own reserved grant (see `finish_and_release_grant`'s
        own docstring for why a refused claim needs that release and a
        genuinely-dispatched `finish` must not get one) and whether the
        recorded event carries a `grant_released` key at all -- `finish`
        itself never wrote that key, and still does not: it is added to
        `detail` only when `release_grant` is true, exactly the shape
        each public method already had before this merge.
        """

        action_id = _non_empty_string(action_id, "action_id")
        status = _non_empty_string(status, "status")
        if status not in TERMINAL_STATUSES:
            raise InvalidTransition("finish requires a terminal action status")
        if not isinstance(public_result, dict):
            raise InvalidAction("public_result must be an object")
        public_result_json = _json(_redact(public_result))
        external_id = _external_id(external_id)

        with self._transaction() as connection:
            row = self._fetch_action(connection, action_id)
            if row is None:
                raise ActionNotFound(action_id)
            if row["status"] in TERMINAL_STATUSES:
                if (
                    row["status"] == status
                    and row["public_result_json"] == public_result_json
                    and row["external_id"] == external_id
                ):
                    return self._action(row)
                raise InvalidTransition(
                    f"action is already terminal: {row['status']}"
                )
            if row["status"] != "running":
                raise InvalidTransition(
                    f"cannot finish action from status: {row['status']}"
                )
            connection.execute(
                "UPDATE actions SET status = ?, public_result_json = ?, "
                "external_id = ?, updated_at = ? WHERE action_id = ?",
                (status, public_result_json, external_id, _timestamp(), action_id),
            )
            detail = {
                "external_id_recorded": external_id is not None,
                "public_result": json.loads(public_result_json),
            }
            if release_grant:
                grant_released = False
                if row["grant_id"] is not None:
                    released = connection.execute(
                        "UPDATE grants SET reserved_action_id = NULL, reserved_at = NULL "
                        "WHERE grant_id = ? AND reserved_action_id = ?",
                        (row["grant_id"], action_id),
                    )
                    grant_released = released.rowcount == 1
                    if grant_released:
                        # `actions.grant_id` is `UNIQUE` (see
                        # `_initialize`): a grant can back at most one
                        # action *row* across the table's whole history,
                        # so merely clearing the grant's own `reserved_
                        # action_id` is not enough to make it reusable --
                        # a fresh `enqueue` reserving this same grant
                        # would find it "available" and then fail its own
                        # `INSERT` with an `IntegrityError` the moment it
                        # tried to claim a `grant_id` this refused row
                        # still references. Clearing it here (NULL is
                        # never unique-constrained, and every other
                        # non-grant-required action already carries one)
                        # is what actually frees the grant for reuse.
                        # Nothing about the original reservation is lost:
                        # `enqueue`'s own `action_events` row already
                        # recorded it durably, append-only, and is
                        # untouched here.
                        connection.execute(
                            "UPDATE actions SET grant_id = NULL WHERE action_id = ?",
                            (action_id,),
                        )
                detail["grant_released"] = grant_released
            self._event(connection, action_id, "running", status, detail)
            return self._action(self._fetch_action(connection, action_id))

    def recover_inflight(self, verifier, action_types=None) -> list[dict]:
        if not callable(verifier):
            raise TypeError("verifier must be callable")
        connection = self._connect()
        try:
            if action_types is None:
                # Unfiltered: byte-for-byte the original query, so every
                # existing caller (the CLI's `recover`, `Runner.recover`)
                # keeps recovering every in-flight action regardless of type.
                rows = connection.execute(
                    "SELECT * FROM actions WHERE status = 'running' "
                    "ORDER BY created_at, action_id"
                ).fetchall()
            else:
                # Mirrors `claim_next`'s own filtered branch: lets a caller
                # that owns only one partition of `ACTION_TYPES` (e.g.
                # `decisions.DecisionWorker`) recover just its own in-flight
                # rows, never a different owner's.
                action_types = frozenset(action_types)
                if not action_types or not action_types.issubset(ACTION_TYPES):
                    raise InvalidAction(
                        "action_types must be a non-empty subset of ACTION_TYPES"
                    )
                placeholders = ", ".join("?" for _ in action_types)
                rows = connection.execute(
                    "SELECT * FROM actions WHERE status = 'running' "
                    f"AND action_type IN ({placeholders}) "
                    "ORDER BY created_at, action_id",
                    tuple(action_types),
                ).fetchall()
        finally:
            connection.close()

        recovered = []
        for row in rows:
            action = self._action(row)
            try:
                decision = normalize_recovery_decision(verifier(copy.deepcopy(action)))
            except ValueError:
                # Repair, 2026-09-16 (ticket 09 third repair, condition 2;
                # refined in the second attempt, conditions 4-5): a
                # verifier that raises for THIS action (e.g.
                # `runner.Runner.recover`'s wrapper raises
                # `adapters.PublicResultError` — a `ValueError` subclass —
                # for a `public_result` it cannot accept) is isolated to
                # this action alone. Nothing is written for it, and the
                # loop moves on to every other in-flight action instead of
                # aborting the whole recovery pass.
                #
                # Distinguishable from a genuine recovery two ways now.
                # First, `refusal` names *why*: a `ValueError` here means
                # the verifier ran and reported something this ledger will
                # not accept — condition 4 — as opposed to the verifier
                # itself failing to run at all (below). Second, `get_action`
                # re-reads the row fresh from the database *after* this
                # attempt rather than reusing `action`, the snapshot taken
                # *before* the verifier ever ran (condition 5) — for this
                # action that snapshot is expected to still match, since
                # nothing here wrote to it, but a caller should never be
                # handed a pre-attempt copy when a live re-read costs
                # nothing and is what every other branch of this method
                # already does.
                recovered.append(
                    {**self.get_action(action["action_id"]), "refusal": "invalid_result"}
                )
                continue
            except Exception:
                # Same isolation as above, for a verifier that fails on its
                # own terms — a bug, a timeout, a broken connection —
                # rather than reporting a result this ledger refuses.
                # `refusal` tells the two apart for a caller (e.g. the CLI's
                # `recover` command) that wants to report *why* nothing
                # could be confirmed for this action, not just that nothing
                # was.
                recovered.append(
                    {**self.get_action(action["action_id"]), "refusal": "verifier_error"}
                )
                continue
            status = decision["status"]
            if status == "not_started":
                result = self._requeue_recovered(action["action_id"])
            else:
                public_result = decision.get("public_result")
                if not isinstance(public_result, dict):
                    # Repair, 2026-09-16 (condition 3, kept in the third
                    # repair): no fabricated English prose here any more
                    # ("External outcome requires verification" /
                    # "Recovered action"). The allowlisted, Russian public
                    # status message is `status_messages.STATUS_MESSAGE_RU`'s
                    # alone to set, and the `Runner`-driven path always
                    # supplies a fully canonicalized `public_result` (via
                    # `validate_public_result`) before this is ever
                    # reached. A caller that talks to `ActionLedger`
                    # directly (this module's own tests) and supplies no
                    # message gets none echoed back — never an invented
                    # one.
                    public_result = {"status": status}
                try:
                    external_id = _external_id(decision.get("external_id"))
                except InvalidAction:
                    status = "outcome_unknown"
                    external_id = None
                    # Repair, 2026-09-16 (ticket 09, second attempt,
                    # condition 1 — approach change from the third repair's
                    # condition 4). `status` is forced to `outcome_unknown`
                    # here because the verifier's own `external_id` could
                    # not be trusted — but the third repair kept whatever
                    # `message` the pre-override `public_result` already
                    # carried, reasoning that dropping a field the caller
                    # supplied was itself a regression. That was wrong: in
                    # the `Runner`-driven path `message` was already
                    # canonicalized by `adapters.validate_public_result`
                    # for whatever status the verifier *originally*
                    # reported (typically `"Готово."` for `succeeded`), and
                    # a stale message naming the wrong outcome is worse
                    # than a dropped field — it is the one piece of text a
                    # person actually reads. `STATUS_MESSAGE_RU` is this
                    # module's and `adapters.py`'s shared, single-owner
                    # source for that text (see `studio/status_messages.py`),
                    # so `status` and `message` are corrected together:
                    # whichever status ends up recorded, the message always
                    # names that same status, never one it overrode.
                    public_result = {
                        **public_result,
                        "status": status,
                        "message": STATUS_MESSAGE_RU[status],
                    }
                result = self._finish_recovered(
                    action["action_id"],
                    status,
                    public_result,
                    external_id,
                )
            if result is not None:
                recovered.append(result)
        return recovered

    def _requeue_recovered(self, action_id):
        with self._transaction() as connection:
            row = self._fetch_action(connection, action_id)
            if row is None or row["status"] != "running":
                return None
            connection.execute(
                "UPDATE actions SET status = 'queued', worker_id = NULL, updated_at = ? "
                "WHERE action_id = ? AND status = 'running'",
                (_timestamp(), action_id),
            )
            self._event(
                connection,
                action_id,
                "running",
                "queued",
                {"recovery": "verified_not_started"},
            )
            return self._action(self._fetch_action(connection, action_id))

    def _finish_recovered(self, action_id, status, public_result, external_id):
        with self._transaction() as connection:
            row = self._fetch_action(connection, action_id)
            if row is None or row["status"] != "running":
                return None
            cleaned_result = _redact(public_result)
            result_json = _json(cleaned_result)
            external_id = _external_id(external_id)
            connection.execute(
                "UPDATE actions SET status = ?, public_result_json = ?, "
                "external_id = ?, updated_at = ? WHERE action_id = ?",
                (status, result_json, external_id, _timestamp(), action_id),
            )
            self._event(
                connection,
                action_id,
                "running",
                status,
                {
                    "recovery": "verified" if status != "outcome_unknown" else "uncertain",
                    "external_id_recorded": external_id is not None,
                    "public_result": cleaned_result,
                },
            )
            return self._action(self._fetch_action(connection, action_id))

    def get_action(self, action_id) -> dict:
        action_id = _non_empty_string(action_id, "action_id")
        connection = self._connect()
        try:
            row = self._fetch_action(connection, action_id)
        finally:
            connection.close()
        if row is None:
            raise ActionNotFound(action_id)
        return self._action(row)

    def latest_actions_by_target(self, project_id) -> list[dict]:
        """Return this project's most recent action for every distinct
        `(action_type, target_id)` pair it has ever queued.

        Ticket 08 repair to remedy 1, condition 13: `http_app._snapshot`
        needs this to fill `state["actions"]` the same way it already
        fills `state["questions"]` from `QuestionStore.pending` -- without
        it, a reload showed a paid `vary`/`regenerate` control as freshly
        idle and let a second click race the first (spec §5: reload must
        return the same action, never start a second one), and an
        `outcome_unknown` action became invisible the moment the tab that
        POSTed it closed.

        Ticket 08 repair 2, condition 3: this used to assemble a
        superset dict (including every field this docstring still lists
        as forbidden) and lean on `projection._ACTION_SOURCE_KEYS`,
        imported here, to filter it back down -- a second, silent copy of
        the very check `projection._sanitize_action` already makes, and a
        strictly weaker one: an unexpected key there is a hard
        `ProjectionError`, an unexpected key here just quietly vanished,
        so this module's own filter could drift from projection's without
        either ever failing loudly. It never leaned on the filter for
        anything real in the first place -- the `SELECT` two lines below
        never reads `payload_json`, `idempotency_key`, `grant_id`,
        `worker_id`, `external_id` or either timestamp column, so none of
        them could reach `results` even before the filter ran. Now there
        is exactly one place that decides this shape: this method builds
        the public dict directly, by construction, from that same closed
        column list; `http_app._snapshot` (the only caller) hands the
        result straight to `state["actions"]`, and `projection.
        build_snapshot`'s own `_sanitize_action` is the sole allowlist
        check it passes through -- loud, not silent, if the two ever
        disagree. `public_result` is kept only once `finish`/recovery has
        actually recorded one (a `vary`/`regenerate` enqueued straight to
        `needs_chat` for want of a free grant never has one). `message`
        is kept only for a terminal status (`TERMINAL_STATUSES`), always
        `status_messages.STATUS_MESSAGE_RU[status]` -- the very table
        `recover_inflight` itself already defers to -- never a stored
        `public_result`'s own `message`, and never invented here;
        `queued`/`running` carry no `message` key at all.

        "Latest" per pair is the row with the greatest `(created_at,
        action_id)`. `action_id` (a random hex, not a clock) only breaks
        a tie between two rows `_timestamp()` stamped in the same
        microsecond -- it never substitutes for creation order on its
        own. The returned list is ordered by `(action_type, target_id)`
        instead -- stable and independent of insertion order, so two
        calls against an unchanged ledger are byte-for-byte identical
        regardless of how many superseded attempts a pair has
        accumulated.

        `actions_latest_by_target` (see `_initialize`) keys on exactly
        `(project_id, action_type, target_id, created_at, action_id)`,
        so the `WHERE project_id = ?` filter and the correlated
        `NOT EXISTS` below both resolve through that one index -- a
        lookup scoped to this project, never a scan of every project's
        actions. `CREATE INDEX IF NOT EXISTS` means a database opened
        from before this method existed gains the index on its next
        `ActionLedger(...)` construction; no migration step required.
        """

        project_id = _non_empty_string(project_id, "project_id")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT action_id, project_id, expected_revision, action_type, "
                "target_id, status, public_result_json FROM actions AS a "
                "WHERE project_id = ? AND NOT EXISTS ("
                "SELECT 1 FROM actions AS newer "
                "WHERE newer.project_id = a.project_id "
                "AND newer.action_type = a.action_type "
                "AND newer.target_id = a.target_id "
                "AND (newer.created_at > a.created_at "
                "OR (newer.created_at = a.created_at AND newer.action_id > a.action_id))"
                ") ORDER BY a.action_type, a.target_id",
                (project_id,),
            ).fetchall()
        finally:
            connection.close()

        results = []
        for row in rows:
            status = row["status"]
            entry = {
                "action_id": row["action_id"],
                "project_id": row["project_id"],
                "revision": row["expected_revision"],
                "action_type": row["action_type"],
                "target_id": row["target_id"],
                "status": status,
            }
            if row["public_result_json"] is not None:
                entry["public_result"] = json.loads(row["public_result_json"])
            message = STATUS_MESSAGE_RU.get(status)
            if message is not None:
                entry["message"] = message
            results.append(entry)
        return results

    def pending_actions(self, project_id, *, exclude_action_id=None) -> list[dict]:
        """Every unfinished action, not latest-per-pair (which can hide a job)."""
        project_id = _non_empty_string(project_id, "project_id")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT action_id, action_type, target_id, status FROM actions "
                "WHERE project_id = ? AND status IN ('queued', 'running') "
                "AND (? IS NULL OR action_id != ?) ORDER BY created_at, action_id",
                (project_id, exclude_action_id, exclude_action_id),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def has_pending_actions(self, project_id, *, exclude_action_id=None) -> bool:
        """Whether `project_id` currently has any action `queued`/
        `running`, other than `exclude_action_id`.

        Ticket 15 (G05): `reopen-scenario` must refuse while anything for
        this project is still in flight -- "ничего платного не должно
        выполняться для стадии, которая скрылась" (nothing paid may keep
        running for a stage the reopen is about to hide). Shared by both
        reopen doors: `decisions.DecisionWorker._apply` calls this with
        `exclude_action_id` set to the reopen action's own id (already
        `running` by the time `claim_next` handed it over, so it must not
        refuse itself); `authoring_milestones.reopen_scenario` (the
        CLI/chat door) never creates a ledger row of its own, so it calls
        this with no exclusion at all.

        One plain, read-only `SELECT` -- deliberately not wrapped in
        `self._transaction()` -- so this holds no lock beyond that single
        query, in particular never overlapping the separate
        `ProjectStore.transact` file lock either caller takes next for
        the actual state mutation (the "reads the ledger once, holds no
        lock past it" the ticket calls for).
        """

        project_id = _non_empty_string(project_id, "project_id")
        connection = self._connect()
        try:
            if exclude_action_id is None:
                row = connection.execute(
                    "SELECT 1 FROM actions WHERE project_id = ? "
                    "AND status IN ('queued', 'running') LIMIT 1",
                    (project_id,),
                ).fetchone()
            else:
                exclude_action_id = _non_empty_string(
                    exclude_action_id, "exclude_action_id"
                )
                row = connection.execute(
                    "SELECT 1 FROM actions WHERE project_id = ? "
                    "AND status IN ('queued', 'running') AND action_id != ? LIMIT 1",
                    (project_id, exclude_action_id),
                ).fetchone()
        finally:
            connection.close()
        return row is not None

    def count_reserved_grants(self) -> int:
        connection = self._connect()
        try:
            return connection.execute(
                "SELECT COUNT(*) FROM grants WHERE reserved_action_id IS NOT NULL"
            ).fetchone()[0]
        finally:
            connection.close()

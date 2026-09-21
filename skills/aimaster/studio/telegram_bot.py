"""Offline core for the dedicated owner-only Studio Telegram bot.

No HTTP client lives here.  The controller accepts already-decoded Telegram
updates, gates them by private chat and owner id before touching project data,
and returns plain reply values for the entrypoint to deliver.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import authoring
from .authoring_questions import resolve_cli_answer
from .chat_decisions import OperationConflict, apply as apply_chat_decision
from .decision_cards import resolve_stage_card
from .decision_support import DecisionError
from .domain import DomainValidationError, derive_view_stage
from .domain_positions import current_member, position_specs
from .ledger import ActionRequest, IdempotencyConflict, InvalidAction, LedgerError
from .questions import LateAnswerConflict, QuestionError, secure_sqlite_path
from .runner import open_ledger
from .store import RevisionConflict, StoreError
from .workspace import resolve_workspace_paths


TELEGRAM_DB_NAME = "telegram_bot.sqlite3"
_TERMINAL_UPDATE_WINDOW = 256

_PROJECT_TYPES = {"photo": "Фото", "video": "Видео", "mixed": "Фото и видео"}
_STAGES = {
    "scenario": "Сценарий",
    "image_plan": "Кадры и промпты",
    "image_results": "Изображения",
    "motion": "Видео",
    "audio": "Звук",
    "assembly": "Сборка",
}
_STATUSES = {"active": "В работе", "review": "На проверке", "done": "Готово"}
_CARD_ACTIONS = {"approve", "reject", "hide", "unhide", "retire", "restore"}
_RESULT_ACTIONS = {"hide", "unhide", "retire", "restore", "vary", "regenerate"}
_PAID_ACTIONS = {"vary", "regenerate"}
_COMMANDS = {
    "/projects",
    "/open",
    "/approve",
    "/reject",
    "/hide",
    "/unhide",
    "/retire",
    "/restore",
    "/stage-approve",
    "/stage-reject",
    "/vary",
    "/regenerate",
    "/help",
}

_INBOX_STATUSES = {"queued", "processing", "done", "outcome_unknown"}
_MAX_CALLBACK_DATA_BYTES = 64


class TelegramBotError(RuntimeError):
    """The local Telegram controller or its private journal refused input."""


@dataclass(frozen=True, slots=True)
class TelegramReply:
    chat_id: int
    text: str
    update_id: int


def project_menu_payloads(projects) -> list[dict[str, str]]:
    """Build safe, deterministic project-selection callback payloads.

    Delivery as an inline keyboard and callback handling are transport concerns;
    this offline helper only exposes the bounded Bot API payload contract.
    """

    payloads = []
    for project in projects:
        if not isinstance(project, dict):
            raise TelegramBotError("project menu entry must be an object")
        project_id = project.get("id")
        title = project.get("title")
        if not isinstance(project_id, str) or not project_id:
            raise TelegramBotError("project menu id must be a non-empty string")
        if not isinstance(title, str) or not title:
            raise TelegramBotError("project menu title must be a non-empty string")
        callback_data = f"project:{project_id}"
        if len(callback_data.encode("utf-8")) > _MAX_CALLBACK_DATA_BYTES:
            raise TelegramBotError("project menu callback data is too large")
        payloads.append({"text": title, "callback_data": callback_data})
    return sorted(payloads, key=lambda item: (item["text"], item["callback_data"]))


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _canonical(value) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise TelegramBotError("Telegram update must be JSON-compatible") from error


def _fingerprint(update: dict) -> str:
    return hashlib.sha256(_canonical(update).encode("utf-8")).hexdigest()


class TelegramBotState:
    """Private SQLite selections, immutable update requests and reply outbox."""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _secure(self):
        secure_sqlite_path(self.db_path, error=TelegramBotError)

    def _connect(self):
        self._secure()
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 30000")
            self._secure()
            return connection
        except Exception:
            connection.close()
            raise

    def _initialize(self):
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            self._secure()
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS selections (
                    chat_id INTEGER PRIMARY KEY,
                    workspace TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    question_id TEXT,
                    question_revision INTEGER,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS updates (
                    update_id INTEGER PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    chat_id INTEGER,
                    request_json TEXT,
                    reply_text TEXT,
                    delivered INTEGER NOT NULL DEFAULT 0,
                    action_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    update_id INTEGER NOT NULL UNIQUE,
                    chat_id INTEGER NOT NULL,
                    workspace TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    outcome_text TEXT
                );

                CREATE INDEX IF NOT EXISTS inbox_next_item
                    ON inbox(status, id);
                """
            )
        finally:
            connection.close()
        self._secure()

    @contextmanager
    def _transaction(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._secure()
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _row(connection, update_id):
        return connection.execute(
            "SELECT * FROM updates WHERE update_id = ?", (update_id,)
        ).fetchone()

    @staticmethod
    def _public_update(row):
        if row is None:
            return None
        result = dict(row)
        encoded_request = result.pop("request_json", None)
        result["request"] = json.loads(encoded_request) if encoded_request is not None else None
        result["delivered"] = bool(result["delivered"])
        return result

    @staticmethod
    def _advance(connection, update_id):
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'next_offset'"
        ).fetchone()
        current = int(row["value"]) if row is not None else 0
        value = max(current, update_id + 1)
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES ('next_offset', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(value),),
        )

    @staticmethod
    def _prune_terminal(connection):
        """Bound replay history without removing uncertain or undelivered work."""

        connection.execute(
            "DELETE FROM updates WHERE update_id IN ("
            "SELECT update_id FROM updates WHERE status='ignored' OR "
            "(status IN ('done','outcome_unknown') AND delivered=1) "
            "AND NOT EXISTS (SELECT 1 FROM inbox WHERE inbox.update_id=updates.update_id "
            "AND inbox.status IN ('queued','processing')) "
            "ORDER BY update_id DESC LIMIT -1 OFFSET ?)",
            (_TERMINAL_UPDATE_WINDOW,),
        )

    def update_record(self, update_id):
        connection = self._connect()
        try:
            return self._public_update(self._row(connection, update_id))
        finally:
            connection.close()

    def begin(self, update_id, fingerprint, chat_id, request):
        if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
            raise TelegramBotError("update_id must be a non-negative integer")
        encoded = _canonical(request)
        now = _timestamp()
        with self._transaction() as connection:
            existing = self._row(connection, update_id)
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise TelegramBotError("update_id belongs to different content")
                return self._public_update(existing)
            connection.execute(
                "INSERT INTO updates(update_id, fingerprint, status, chat_id, "
                "request_json, created_at, updated_at) VALUES (?, ?, 'executing', ?, ?, ?, ?)",
                (update_id, fingerprint, chat_id, encoded, now, now),
            )
            return self._public_update(self._row(connection, update_id))

    def record_ignored(self, update_id, fingerprint):
        now = _timestamp()
        with self._transaction() as connection:
            existing = self._row(connection, update_id)
            if existing is not None and existing["fingerprint"] != fingerprint:
                raise TelegramBotError("update_id belongs to different content")
            if existing is None:
                connection.execute(
                    "INSERT INTO updates(update_id, fingerprint, status, delivered, created_at, updated_at) "
                    "VALUES (?, ?, 'ignored', 1, ?, ?)",
                    (update_id, fingerprint, now, now),
                )
            self._advance(connection, update_id)
            self._prune_terminal(connection)

    def complete(self, update_id, text, *, action_id=None, status="done"):
        if status not in {"done", "outcome_unknown"}:
            raise TelegramBotError("unsupported terminal update status")
        now = _timestamp()
        with self._transaction() as connection:
            row = self._row(connection, update_id)
            if row is None:
                raise TelegramBotError("cannot complete an unknown update")
            connection.execute(
                "UPDATE updates SET status=?, reply_text=?, delivered=0, action_id=?, updated_at=? "
                "WHERE update_id=?",
                (status, text, action_id, now, update_id),
            )
            self._advance(connection, update_id)
            return self._public_update(self._row(connection, update_id))

    def complete_open(self, update_id, chat_id, workspace, project_id, text):
        now = _timestamp()
        with self._transaction() as connection:
            row = self._row(connection, update_id)
            if row is None:
                raise TelegramBotError("cannot complete an unknown update")
            connection.execute(
                "INSERT INTO selections(chat_id,workspace,project_id,question_id,question_revision,updated_at) "
                "VALUES (?, ?, ?, NULL, NULL, ?) ON CONFLICT(chat_id) DO UPDATE SET "
                "workspace=excluded.workspace, project_id=excluded.project_id, "
                "question_id=NULL, question_revision=NULL, updated_at=excluded.updated_at",
                (chat_id, str(workspace), project_id, now),
            )
            connection.execute(
                "UPDATE updates SET status='done', reply_text=?, delivered=0, updated_at=? "
                "WHERE update_id=?",
                (text, now, update_id),
            )
            self._advance(connection, update_id)
            return self._public_update(self._row(connection, update_id))

    def selection(self, chat_id):
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM selections WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            return dict(row) if row is not None else None
        finally:
            connection.close()

    def set_question(self, chat_id, project_id, question_id, revision):
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE selections SET question_id=?, question_revision=?, updated_at=? "
                "WHERE chat_id=? AND project_id=?",
                (question_id, revision, _timestamp(), chat_id, project_id),
            )
            return changed.rowcount == 1

    def clear_question(self, chat_id, project_id):
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE selections SET question_id=NULL, question_revision=NULL, updated_at=? "
                "WHERE chat_id=? AND project_id=?",
                (_timestamp(), chat_id, project_id),
            )
            return changed.rowcount == 1

    def pending_replies(self, owner_id):
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM updates WHERE reply_text IS NOT NULL AND delivered=0 "
                "AND status IN ('done','outcome_unknown') AND chat_id=? ORDER BY update_id",
                (owner_id,),
            ).fetchall()
            return [
                TelegramReply(row["chat_id"], row["reply_text"], row["update_id"])
                for row in rows
            ]
        finally:
            connection.close()

    def mark_delivered(self, update_id):
        with self._transaction() as connection:
            connection.execute(
                "UPDATE updates SET delivered=1, updated_at=? WHERE update_id=?",
                (_timestamp(), update_id),
            )
            self._prune_terminal(connection)

    def next_offset(self):
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key='next_offset'"
            ).fetchone()
            return int(row["value"]) if row is not None else 0
        finally:
            connection.close()

    def paired_owner(self):
        """Return the locally paired Telegram owner id, if setup has one."""

        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key='paired_owner_id'"
            ).fetchone()
            return int(row["value"]) if row is not None else None
        finally:
            connection.close()

    def pair_owner(self, owner_id):
        """Persist the one owner id; changing an existing pairing is refused."""

        if isinstance(owner_id, bool) or not isinstance(owner_id, int) or owner_id <= 0:
            raise TelegramBotError("owner id must be a positive integer")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key='paired_owner_id'"
            ).fetchone()
            if row is not None:
                paired_owner = int(row["value"])
                if paired_owner != owner_id:
                    raise TelegramBotError("Telegram owner is already paired")
                return paired_owner
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES ('paired_owner_id', ?)",
                (str(owner_id),),
            )
            return owner_id

    @staticmethod
    def _public_inbox(row):
        if row is None:
            return None
        return dict(row)

    def enqueue_inbox(self, *, update_id, chat_id, workspace, project_id, text):
        """Atomically record one selected-project free-form request.

        ``update_id`` is the idempotency boundary inherited from Telegram, so a
        polling replay cannot create a second local Codex job.
        """

        if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
            raise TelegramBotError("update_id must be a non-negative integer")
        if isinstance(chat_id, bool) or not isinstance(chat_id, int) or chat_id <= 0:
            raise TelegramBotError("chat id must be a positive integer")
        if not isinstance(workspace, str) or not workspace:
            raise TelegramBotError("workspace must be a non-empty string")
        if not isinstance(project_id, str) or not project_id:
            raise TelegramBotError("project id must be a non-empty string")
        if not isinstance(text, str) or not text.strip():
            raise TelegramBotError("inbox text must be a non-empty string")
        idempotency_key = f"telegram:{update_id}"
        now = _timestamp()
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM inbox WHERE update_id=?", (update_id,)
            ).fetchone()
            if row is not None:
                if (
                    row["chat_id"] != chat_id
                    or row["workspace"] != workspace
                    or row["project_id"] != project_id
                    or row["text"] != text
                ):
                    raise TelegramBotError("update_id belongs to different inbox content")
                return self._public_inbox(row)
            connection.execute(
                "INSERT INTO inbox(update_id,chat_id,workspace,project_id,text,"
                "idempotency_key,status,created_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)",
                (update_id, chat_id, workspace, project_id, text, idempotency_key, now),
            )
            row = connection.execute(
                "SELECT * FROM inbox WHERE update_id=?", (update_id,)
            ).fetchone()
            return self._public_inbox(row)

    def dequeue_inbox(self):
        """Claim the oldest queued item for a single local bridge worker."""

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM inbox WHERE status='queued' ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE inbox SET status='processing', started_at=? WHERE id=?",
                (_timestamp(), row["id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM inbox WHERE id=?", (row["id"],)
            ).fetchone()
            return self._public_inbox(claimed)

    def complete_inbox(self, item_id, status, outcome_text):
        if status not in {"done", "outcome_unknown"}:
            raise TelegramBotError("unsupported inbox terminal status")
        if not isinstance(item_id, int) or isinstance(item_id, bool) or item_id <= 0:
            raise TelegramBotError("inbox id must be a positive integer")
        if not isinstance(outcome_text, str) or not outcome_text.strip():
            raise TelegramBotError("inbox outcome must be non-empty text")
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE inbox SET status=?, outcome_text=?, completed_at=? "
                "WHERE id=? AND status='processing'",
                (status, outcome_text.strip(), _timestamp(), item_id),
            )
            if changed.rowcount != 1:
                raise TelegramBotError("inbox item is not processing")
            row = connection.execute("SELECT * FROM inbox WHERE id=?", (item_id,)).fetchone()
            connection.execute(
                "UPDATE updates SET reply_text=?, delivered=0, status=?, updated_at=? "
                "WHERE update_id=?",
                (outcome_text.strip(), status, _timestamp(), row["update_id"]),
            )
            if connection.execute(
                "SELECT 1 FROM updates WHERE update_id=?", (row["update_id"],)
            ).fetchone() is None:
                raise TelegramBotError("Telegram outbox update was not found")
            return self._public_inbox(row)

class TelegramBotController:
    """Owner-only deterministic command and question controller."""

    def __init__(
        self,
        workspace,
        owner_id,
        *,
        store_factory=None,
        ledger_factory=None,
        questions_factory=None,
        state=None,
        pairing_code=None,
    ):
        if owner_id is not None and (
            isinstance(owner_id, bool) or not isinstance(owner_id, int) or owner_id <= 0
        ):
            raise TelegramBotError("owner id must be a positive integer")
        workspace_path, _, _, private_root = resolve_workspace_paths(workspace)
        self.workspace = workspace_path
        self.state = state or TelegramBotState(private_root / TELEGRAM_DB_NAME)
        paired_owner = self.state.paired_owner()
        if owner_id is not None and paired_owner is not None and owner_id != paired_owner:
            raise TelegramBotError("Telegram owner does not match local pairing")
        if owner_id is None and not isinstance(pairing_code, str):
            raise TelegramBotError("pairing code is required before owner-only startup")
        self.owner_id = owner_id if owner_id is not None else paired_owner
        self.pairing_code = pairing_code
        self._store_factory = store_factory or (lambda: authoring.open_store(self.workspace))
        self._ledger_factory = ledger_factory or (lambda: open_ledger(self.workspace))
        self._questions_factory = questions_factory or (
            lambda: authoring.open_questions(self.workspace)
        )
        self._store = None
        self._ledger = None
        self._questions = None

    @property
    def store(self):
        if self._store is None:
            self._store = self._store_factory()
        return self._store

    @property
    def ledger(self):
        if self._ledger is None:
            self._ledger = self._ledger_factory()
        return self._ledger

    @property
    def questions(self):
        if self._questions is None:
            self._questions = self._questions_factory()
        return self._questions

    def next_offset(self):
        return self.state.next_offset()

    def pending_replies(self):
        return self.state.pending_replies(self.owner_id)

    def mark_delivered(self, update_id):
        self.state.mark_delivered(update_id)

    @staticmethod
    def _envelope(update):
        if not isinstance(update, dict):
            return None
        update_id = update.get("update_id")
        if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
            return None
        message = update.get("message")
        if not isinstance(message, dict):
            return update_id, None, None, None, None
        sender = message.get("from")
        chat = message.get("chat")
        sender_id = sender.get("id") if isinstance(sender, dict) else None
        chat_id = chat.get("id") if isinstance(chat, dict) else None
        if isinstance(sender_id, bool) or not isinstance(sender_id, int):
            sender_id = None
        if isinstance(chat_id, bool) or not isinstance(chat_id, int):
            chat_id = None
        chat_type = chat.get("type") if isinstance(chat, dict) else None
        text = message.get("text")
        return update_id, sender_id, chat_id, chat_type, text

    def handle_update(self, update) -> list[TelegramReply]:
        envelope = self._envelope(update)
        if envelope is None:
            return []
        update_id, sender_id, chat_id, chat_type, text = envelope
        fingerprint = _fingerprint(update)

        # A bot configured locally but not yet paired accepts exactly the
        # owner's first private /start.  No project store, ledger or question
        # surface is opened on this path.
        if self.owner_id is None:
            if (
                sender_id is None
                or sender_id != chat_id
                or chat_type != "private"
                or not isinstance(text, str)
                or not text.strip().lower().startswith("/start")
            ):
                self.state.record_ignored(update_id, fingerprint)
                return []
            parts = text.strip().split(maxsplit=1)
            if self.pairing_code is not None and (len(parts) != 2 or parts[1] != self.pairing_code):
                self.state.record_ignored(update_id, fingerprint)
                return []
            self.owner_id = self.state.pair_owner(sender_id)
            existing = self.state.begin(
                update_id,
                fingerprint,
                chat_id,
                {"kind": "reply", "text": "Telegram owner paired."},
            )
            return self._execute(update_id, chat_id, existing["request"])

        # Security boundary: no selection, project, question or ledger access
        # occurs before both checks pass. Only the private update cursor is
        # advanced so Telegram does not redeliver a foreign update forever.
        if (
            sender_id != self.owner_id
            or chat_type != "private"
            or chat_id != self.owner_id
        ):
            self.state.record_ignored(update_id, fingerprint)
            return []
        if not isinstance(text, str) or not text.strip():
            self.state.record_ignored(update_id, fingerprint)
            return []

        existing = self.state.update_record(update_id)
        if existing is None and update_id < self.state.next_offset():
            # Already-consumed terminal history may have been pruned. The
            # durable polling cursor is still authoritative: an old id never
            # becomes a fresh command merely because its row was compacted.
            return []
        if existing is not None:
            if existing["fingerprint"] != fingerprint:
                raise TelegramBotError("update_id belongs to different content")
            if existing["status"] in {"done", "outcome_unknown"}:
                if existing["reply_text"] and not existing["delivered"]:
                    return [TelegramReply(chat_id, existing["reply_text"], update_id)]
                return []
            if existing["status"] == "ignored":
                return []
            request = existing["request"]
        else:
            try:
                request = self._prepare_request(chat_id, text.strip())
            except (DecisionError, DomainValidationError, InvalidAction,
                    IdempotencyConflict, LedgerError, QuestionError, StoreError,
                    TelegramBotError, ValueError) as error:
                # A malformed/obsolete command is a known refusal, not a bot
                # process failure. Persist the deterministic refusal before it
                # can be delivered, just like every successful command.
                request = {"kind": "reply", "text": f"Команда отклонена: {error}"}
            existing = self.state.begin(update_id, fingerprint, chat_id, request)

        try:
            return self._execute(update_id, chat_id, existing["request"])
        except RevisionConflict:
            text = "Исход команды не подтверждён. Проверьте проект; повтор автоматически не выполнен."
            self.state.complete(update_id, text, status="outcome_unknown")
            return [TelegramReply(chat_id, text, update_id)]
        except OperationConflict:
            text = "Повтор update_id не совпадает с исходной командой; действие не выполнено."
            self.state.complete(update_id, text, status="outcome_unknown")
            return [TelegramReply(chat_id, text, update_id)]
        except (DecisionError, DomainValidationError, InvalidAction, IdempotencyConflict,
                LedgerError, QuestionError, StoreError, TelegramBotError, ValueError) as error:
            text = f"Команда отклонена: {error}"
            self.state.complete(update_id, text)
            return [TelegramReply(chat_id, text, update_id)]

    def _prepare_request(self, chat_id, text):
        command_token, separator, remainder = text.partition(" ")
        command = command_token.split("@", 1)[0].lower()
        remainder = remainder.strip() if separator else ""
        if command.startswith("/"):
            if command not in _COMMANDS:
                return {"kind": "reply", "text": "Неизвестная команда. Используйте /help."}
            if command == "/help":
                return {"kind": "reply", "text": self._help_text()}
            if command == "/projects":
                return {"kind": "projects"}
            if command == "/open":
                if not remainder or " " in remainder:
                    return {"kind": "reply", "text": "Формат: /open <project_id>."}
                project = self.store.load(remainder)
                return {
                    "kind": "open",
                    "project_id": remainder,
                    "title": project["project"].get("title") or remainder,
                }

            selection = self.state.selection(chat_id)
            if selection is None or selection["workspace"] != str(self.workspace):
                return {"kind": "reply", "text": "Сначала выберите проект: /open <project_id>."}
            project_id = selection["project_id"]
            state = self.store.load(project_id)
            revision = state["revision"]
            if command in {"/stage-approve", "/stage-reject"}:
                stage = derive_view_stage(state)["current_stage"]
                if command == "/stage-approve":
                    action_type = "approve-scenario" if stage == "scenario" else "approve"
                    payload = {}
                elif stage == "scenario":
                    return {
                        "kind": "reply",
                        "text": "Доработка сценария продолжается в чате с агентом.",
                    }
                else:
                    action_type = "reject"
                    payload = {"comment": remainder} if remainder else {}
                return {
                    "kind": "decision",
                    "project_id": project_id,
                    "expected_revision": revision,
                    "action_type": action_type,
                    "target_id": stage,
                    "payload": payload,
                }

            action_type = command[1:]
            candidates = self._eligible_targets(state, action_type)
            target_id, comment, refusal = self._target_and_comment(
                action_type, remainder, candidates
            )
            if refusal is not None:
                return {"kind": "reply", "text": refusal}
            payload = {}
            if comment:
                payload["note" if action_type == "vary" else "comment"] = comment
            kind = "paid" if action_type in _PAID_ACTIONS else "decision"
            return {
                "kind": kind,
                "project_id": project_id,
                "expected_revision": revision,
                "action_type": action_type,
                "target_id": target_id,
                "payload": payload,
                "resolved_target_id": candidates[target_id],
            }

        selection = self.state.selection(chat_id)
        if selection is None:
            return {"kind": "reply", "text": "Сначала выберите проект: /open <project_id>."}
        project_id = selection["project_id"]
        question = self._selected_or_first_question(chat_id, project_id)
        if question is None:
            return {
                "kind": "inbox",
                "project_id": project_id,
                "text": text,
            }
        if question["kind"] in {"single", "multi"} and text.isdigit():
            answer = resolve_cli_answer(
                question,
                answer_text=None,
                answer_option_number=[text],
                answer_option_id=[],
            )
        else:
            answer = resolve_cli_answer(
                question,
                answer_text=text,
                answer_option_number=[],
                answer_option_id=[],
            )
        return {
            "kind": "question",
            "project_id": project_id,
            "question_id": question["question_id"],
            "question_revision": question["revision"],
            "answer": answer,
        }

    def _execute(self, update_id, chat_id, request):
        kind = request["kind"]
        if kind == "reply":
            text = request["text"]
            self.state.complete(update_id, text)
            return [TelegramReply(chat_id, text, update_id)]
        if kind == "projects":
            text = self._projects_text()
            self.state.complete(update_id, text)
            return [TelegramReply(chat_id, text, update_id)]
        if kind == "open":
            text = f"Открыт проект «{request['title']}»."
            self.state.complete_open(
                update_id,
                chat_id,
                self.workspace,
                request["project_id"],
                text,
            )
            question_text = self._show_first_question(chat_id, request["project_id"])
            if question_text:
                text = f"{text}\n\n{question_text}"
                self.state.complete(update_id, text)
            return [TelegramReply(chat_id, text, update_id)]
        if kind == "decision":
            result = apply_chat_decision(
                self.store,
                self.ledger,
                request["project_id"],
                request["expected_revision"],
                action_type=request["action_type"],
                target_id=request["target_id"],
                payload=request["payload"],
                operation_id=f"telegram-{update_id}",
            )
            text = "Решение уже применено." if result["replayed"] else "Решение принято."
            self.state.complete(update_id, text)
            return [TelegramReply(chat_id, text, update_id)]
        if kind == "paid":
            target_id = request["resolved_target_id"]
            action = self.ledger.enqueue(
                request["project_id"],
                ActionRequest(
                    request["action_type"],
                    target_id,
                    request["payload"],
                    request["expected_revision"],
                    f"telegram-{update_id}",
                ),
            )
            if action["status"] == "queued":
                text = "Платное действие поставлено в очередь по ранее выданному разрешению."
            else:
                text = "Нужно разрешение в чате. После его выдачи отправьте новую команду."
            self.state.complete(update_id, text, action_id=action["action_id"])
            return [TelegramReply(chat_id, text, update_id)]
        if kind == "question":
            try:
                authoring.answer_question(
                    self.questions,
                    request["question_id"],
                    request["question_revision"],
                    request["answer"],
                    "telegram",
                )
                text = "Ответ принят."
            except LateAnswerConflict:
                text = "Ответ уже принят в другом канале."
            self.state.clear_question(chat_id, request["project_id"])
            next_question = self._show_first_question(chat_id, request["project_id"])
            if next_question:
                text = f"{text}\n\n{next_question}"
            self.state.complete(update_id, text)
            return [TelegramReply(chat_id, text, update_id)]
        if kind == "inbox":
            self.state.enqueue_inbox(
                update_id=update_id,
                chat_id=chat_id,
                workspace=str(self.workspace),
                project_id=request["project_id"],
                text=request["text"],
            )
            text = "Запрос принят и ожидает локального агента на Mac."
            self.state.complete(update_id, text)
            return [TelegramReply(chat_id, text, update_id)]
        raise TelegramBotError("unsupported stored request kind")

    def _projects_text(self):
        projects = self.store.list_projects()
        if not projects:
            return "Проектов пока нет."
        lines = ["Проекты:"]
        for project in projects:
            type_label = _PROJECT_TYPES.get(project.get("type"))
            stage_label = _STAGES.get(project.get("stage"))
            status_label = _STATUSES.get(project.get("status"))
            title = project.get("title")
            if not all(isinstance(item, str) and item for item in (
                project.get("id"), title, type_label, stage_label, status_label
            )):
                raise TelegramBotError("project index contains an unknown public value")
            lines.append(
                f"{project['id']} · {title} · {type_label} · {stage_label} · {status_label}"
            )
        return "\n".join(lines)

    @staticmethod
    def _help_text():
        return (
            "Команды: /projects, /open <project_id>, /approve [target], "
            "/reject [target] <текст>, /hide|/unhide|/retire|/restore [target], "
            "/stage-approve, /stage-reject <текст>, /vary [target] [текст], "
            "/regenerate [target]."
        )

    def _eligible_targets(self, state, action_type):
        if action_type not in _CARD_ACTIONS | _PAID_ACTIONS:
            return {}
        view = derive_view_stage(state)
        if action_type not in view["allowed_actions"]:
            return {}
        candidates = {}
        side = "result" if action_type in _RESULT_ACTIONS or view["current_stage"] != "image_plan" else "prompt"
        for spec in position_specs(state):
            member = current_member(state, spec, side, missing_ok=True)
            if not isinstance(member, dict):
                continue
            version_id = member.get("version_id")
            if not isinstance(version_id, str) or not version_id:
                continue
            try:
                resolve_stage_card(state, version_id, {})
            except (DecisionError, DomainValidationError):
                continue
            candidates[spec["position_id"]] = version_id
            candidates[version_id] = version_id
        # Return aliases in a deterministic order while preserving position ids
        # as the identifiers offered to the owner.
        return candidates

    @staticmethod
    def _position_ids(candidates):
        return sorted(key for key in candidates if key.startswith("pos:"))

    def _target_and_comment(self, action_type, remainder, candidates):
        position_ids = self._position_ids(candidates)
        if not position_ids:
            return None, None, "Для этой команды сейчас нет допустимой цели."
        first, separator, tail = remainder.partition(" ")
        if remainder and first in candidates:
            target = first
            comment = tail.strip() if separator else ""
        elif len(position_ids) == 1:
            target = position_ids[0]
            comment = remainder
        else:
            return (
                None,
                None,
                "Укажите цель: " + ", ".join(position_ids),
            )
        if action_type not in {"reject", "vary"} and comment:
            return None, None, f"Команда /{action_type} не принимает текст после цели."
        return target, comment, None

    def _selected_or_first_question(self, chat_id, project_id):
        selection = self.state.selection(chat_id)
        if (
            selection
            and selection.get("project_id") == project_id
            and selection.get("question_id")
        ):
            question = self.questions.get(selection["question_id"])
            # Keep the exact shown question until this chat answers it. If
            # another channel won meanwhile, QuestionStore.answer supplies the
            # authoritative LateAnswerConflict and the controller can report
            # that race instead of silently treating the prompt as unrelated.
            if question is not None:
                return question
        pending = self.questions.pending(project_id)
        if not pending:
            self.state.clear_question(chat_id, project_id)
            return None
        question = pending[0]
        if not self.state.set_question(
            chat_id, project_id, question["question_id"], question["revision"]
        ):
            return None
        return question

    def _show_first_question(self, chat_id, project_id):
        question = self._selected_or_first_question(chat_id, project_id)
        return self._question_text(question) if question is not None else None

    @staticmethod
    def _question_text(question):
        lines = [question["text"]]
        for index, option in enumerate(question.get("options") or [], 1):
            label = option.get("label")
            if isinstance(label, str) and label:
                lines.append(f"{index}. {label}")
        if question.get("allow_custom") or question.get("kind") == "free_text":
            lines.append("Можно написать свой вариант текстом.")
        return "\n".join(lines)

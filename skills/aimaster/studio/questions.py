"""Durable one-answer question lifecycle shared by every input channel."""

from __future__ import annotations

import copy
import json
import re
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .store import RevisionConflict


QUESTION_KINDS = frozenset({"single", "multi", "free_text", "confirm"})
QUESTION_CHANNELS = frozenset({"dashboard", "chat", "telegram"})
_QUESTION_KEYS = {
    "question_id",
    "project_id",
    "revision",
    "text",
    "kind",
    "options",
    "allow_custom",
    "required",
    "validation",
    "expires_at",
    "resume_token",
}
_OPTION_KEYS = {"id", "label", "description"}
_VALIDATION_KEYS = {
    "min_length",
    "max_length",
    "min_items",
    "max_items",
    "pattern",
    "allowed_values",
}
_SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


class QuestionError(RuntimeError):
    """Base failure for question persistence or answering."""


class QuestionValidationError(QuestionError, ValueError):
    """A question or answer violates the shared contract."""


class QuestionNotFound(QuestionError):
    """A durable question id is unknown."""


class QuestionExpired(QuestionError):
    """A pending question can no longer accept an answer."""


class LateAnswerConflict(QuestionError):
    """Another channel already committed the accepted public answer."""

    def __init__(self, accepted_answer):
        self.accepted_answer = copy.deepcopy(accepted_answer)
        super().__init__("question already has an accepted answer")


def secure_sqlite_path(db_path, *, error=QuestionError) -> None:
    """Fail closed on a planted symlink; force `.../*.sqlite3` (and its
    `-wal`/`-shm` siblings) to mode `0600`.

    Ticket 12 repair, blocking condition 6: `AssetIndex`
    (`studio/assets.py`) needed this exact same guard for
    `.studio/assets.sqlite3`, and the instruction was explicit -- reuse
    this check, do not write a third copy (`ActionLedger.__init__` has
    its own, silent, `try: os.chmod(...); except OSError: pass`, which is
    the second). Pulled out of `QuestionStore._secure_sqlite_files` as a
    module-level function, parameterized on which exception type to
    raise, so each caller's own domain-error taxonomy stays intact
    (`QuestionError` here, `AssetError` for `AssetIndex`) while the
    algorithm itself lives in exactly one place. `QuestionStore` keeps its
    own `_secure_sqlite_files` as a one-line wrapper (`self.db_path`,
    `error=QuestionError`) so every existing internal call site is
    unchanged.

    Ticket 08 repair to remedy 1, condition 15: a `-wal`/`-shm` sidecar
    that existed for the `lstat()` above can still vanish before
    `chmod()` or the mode-verifying re-`lstat()` runs -- SQLite drops
    those files the moment the last connection on the database
    checkpoints and closes, and `AssetIndex._connect` calls this on
    every single connection it opens, so a concurrent `/assets/` request
    or snapshot read can land in exactly that window. A file that is
    gone *now* is exactly as absent as one the first `lstat()` never
    found: skipped, not a reason to fail every *other* file this call
    still needs to secure (an `AssetError` here previously surfaced to
    the browser as a spurious `/assets/` 404 on an otherwise-healthy
    file). A symlink or a non-regular file is judged before this window,
    from the first `lstat()`'s own `metadata`, so that fail-closed check
    is unaffected.
    """

    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{db_path}{suffix}")
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as os_error:
            raise error("cannot inspect private SQLite files") from os_error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise error("private SQLite paths must be regular files")
        try:
            path.chmod(0o600)
            secured_mode = stat.S_IMODE(path.lstat().st_mode)
        except FileNotFoundError:
            continue
        except OSError as os_error:
            raise error("cannot secure private SQLite files") from os_error
        if secured_mode != 0o600:
            raise error("private SQLite files require mode 0600")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    current = _now() if value is None else value.astimezone(timezone.utc)
    return current.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _identifier(value, label):
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise QuestionValidationError(f"{label} must be a safe opaque identifier")
    return value


def _text(value, label, *, allow_empty=False, max_bytes=16_000):
    if not isinstance(value, str) or "\x00" in value:
        raise QuestionValidationError(f"{label} must be text")
    if not allow_empty and not value.strip():
        raise QuestionValidationError(f"{label} must be non-empty")
    if len(value.encode("utf-8")) > max_bytes:
        raise QuestionValidationError(f"{label} is too long")
    return value


def _non_negative_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QuestionValidationError(f"{label} must be a non-negative integer")
    return value


def _expiry(value):
    if value is None:
        return None, None
    if not isinstance(value, str) or not value.strip():
        raise QuestionValidationError(
            "expires_at must be null or an ISO-8601 timestamp"
        )
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise QuestionValidationError("expires_at must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QuestionValidationError("expires_at must include a timezone")
    parsed = parsed.astimezone(timezone.utc)
    return _timestamp(parsed), parsed.timestamp()


def _validation(raw, kind):
    if not isinstance(raw, dict) or set(raw) - _VALIDATION_KEYS:
        raise QuestionValidationError("validation contains unknown fields")
    result = {}
    for key, value in raw.items():
        if key in {"min_length", "max_length", "min_items", "max_items"}:
            result[key] = _non_negative_integer(value, f"validation.{key}")
        elif key == "pattern":
            pattern = _text(value, "validation.pattern", max_bytes=1024)
            try:
                re.compile(pattern)
            except re.error as error:
                raise QuestionValidationError("validation.pattern is invalid") from error
            result[key] = pattern
        else:
            if not isinstance(value, list) or not value:
                raise QuestionValidationError(
                    "validation.allowed_values must be a non-empty list"
                )
            result[key] = [
                _text(item, "validation.allowed_values item") for item in value
            ]
            if len(set(result[key])) != len(result[key]):
                raise QuestionValidationError("validation.allowed_values must be unique")
    if result.get("min_length", 0) > result.get("max_length", float("inf")):
        raise QuestionValidationError("validation min_length exceeds max_length")
    if result.get("min_items", 0) > result.get("max_items", float("inf")):
        raise QuestionValidationError("validation min_items exceeds max_items")
    if kind != "multi" and ({"min_items", "max_items"} & result.keys()):
        raise QuestionValidationError("item limits apply only to multi questions")
    if kind == "multi" and ({"min_length", "max_length", "pattern"} & result.keys()):
        raise QuestionValidationError("text limits do not apply to multi questions")
    return result


def _normalize_question(raw):
    if not isinstance(raw, dict) or set(raw) != _QUESTION_KEYS:
        raise QuestionValidationError(
            "question keys must match the canonical schema exactly"
        )
    question_id = _identifier(raw["question_id"], "question_id")
    project_id = _identifier(raw["project_id"], "project_id")
    revision = _non_negative_integer(raw["revision"], "revision")
    text = _text(raw["text"], "text")
    kind = raw["kind"]
    if kind not in QUESTION_KINDS:
        raise QuestionValidationError("unsupported question kind")
    if not isinstance(raw["allow_custom"], bool) or not isinstance(
        raw["required"], bool
    ):
        raise QuestionValidationError("allow_custom and required must be booleans")
    if not isinstance(raw["options"], list) or len(raw["options"]) > 20:
        raise QuestionValidationError("options must be a bounded list")
    options = []
    for index, option in enumerate(raw["options"]):
        if not isinstance(option, dict) or set(option) != _OPTION_KEYS:
            raise QuestionValidationError(f"options[{index}] keys are invalid")
        options.append(
            {
                "id": _identifier(option["id"], f"options[{index}].id"),
                "label": _text(
                    option["label"], f"options[{index}].label", max_bytes=1024
                ),
                "description": _text(
                    option["description"],
                    f"options[{index}].description",
                    allow_empty=True,
                    max_bytes=4096,
                ),
            }
        )
    option_ids = [option["id"] for option in options]
    if len(set(option_ids)) != len(option_ids):
        raise QuestionValidationError("option ids must be unique")
    if kind in {"single", "multi"} and not options:
        raise QuestionValidationError("choice questions require options")
    if kind in {"free_text", "confirm"} and options:
        raise QuestionValidationError(f"{kind} questions cannot declare options")
    validation = _validation(raw["validation"], kind)
    expires_at, expires_epoch = _expiry(raw["expires_at"])
    resume_token = _text(raw["resume_token"], "resume_token", max_bytes=4096)
    return {
        "question_id": question_id,
        "project_id": project_id,
        "revision": revision,
        "text": text,
        "kind": kind,
        "options": options,
        "allow_custom": raw["allow_custom"],
        "required": raw["required"],
        "validation": validation,
        "expires_at": expires_at,
        "expires_epoch": expires_epoch,
        "resume_token": resume_token,
    }


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
        raise QuestionValidationError("answer must be JSON-compatible") from error


class QuestionStore:
    """SQLite question store with transactional first-answer-wins semantics."""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _secure_sqlite_files(self):
        secure_sqlite_path(self.db_path, error=QuestionError)

    def _connect(self):
        self._secure_sqlite_files()
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 30000")
            self._secure_sqlite_files()
            return connection
        except Exception:
            connection.close()
            raise

    def _initialize(self):
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            self._secure_sqlite_files()
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS questions (
                    question_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    allow_custom INTEGER NOT NULL,
                    required INTEGER NOT NULL,
                    validation_json TEXT NOT NULL,
                    expires_at TEXT,
                    expires_epoch REAL,
                    resume_token TEXT NOT NULL,
                    answer_json TEXT,
                    answered_by TEXT,
                    answered_at TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS questions_pending
                    ON questions(project_id, answer_json, expires_epoch, created_at);
                """
            )
        finally:
            connection.close()
        self._secure_sqlite_files()

    @contextmanager
    def _transaction(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._secure_sqlite_files()
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _public_question(row):
        answer = (
            json.loads(row["answer_json"])
            if row["answer_json"] is not None
            else None
        )
        return {
            "question_id": row["question_id"],
            "project_id": row["project_id"],
            "revision": row["revision"],
            "text": row["text"],
            "kind": row["kind"],
            "options": json.loads(row["options_json"]),
            "allow_custom": bool(row["allow_custom"]),
            "required": bool(row["required"]),
            "validation": json.loads(row["validation_json"]),
            "expires_at": row["expires_at"],
            "status": "answered" if row["answer_json"] is not None else "pending",
            "answer": answer,
        }

    @staticmethod
    def _accepted_public(row):
        return {
            "question_id": row["question_id"],
            "project_id": row["project_id"],
            "revision": row["revision"],
            "status": "answered",
            "answer": json.loads(row["answer_json"]),
        }

    @staticmethod
    def _fetch(connection, question_id):
        return connection.execute(
            "SELECT * FROM questions WHERE question_id = ?", (question_id,)
        ).fetchone()

    def create(self, question: dict):
        value = _normalize_question(copy.deepcopy(question))
        with self._transaction() as connection:
            try:
                connection.execute(
                    "INSERT INTO questions "
                    "(question_id, project_id, revision, text, kind, options_json, "
                    "allow_custom, required, validation_json, expires_at, expires_epoch, "
                    "resume_token, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        value["question_id"],
                        value["project_id"],
                        value["revision"],
                        value["text"],
                        value["kind"],
                        _json(value["options"]),
                        int(value["allow_custom"]),
                        int(value["required"]),
                        _json(value["validation"]),
                        value["expires_at"],
                        value["expires_epoch"],
                        value["resume_token"],
                        _timestamp(),
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise QuestionValidationError("question_id already exists") from error
            return copy.deepcopy(
                self._public_question(self._fetch(connection, value["question_id"]))
            )

    @staticmethod
    def _normalize_answer(row, answer):
        kind = row["kind"]
        required = bool(row["required"])
        allow_custom = bool(row["allow_custom"])
        options = json.loads(row["options_json"])
        option_ids = {option["id"] for option in options}
        validation = json.loads(row["validation_json"])

        if answer is None:
            if required:
                raise QuestionValidationError("answer is required")
            return None
        if kind == "confirm":
            if not isinstance(answer, bool):
                raise QuestionValidationError("confirm answer must be boolean")
            return "yes" if answer else "no"
        if kind == "multi":
            if not isinstance(answer, list) or any(
                not isinstance(item, str) for item in answer
            ):
                raise QuestionValidationError("multi answer must be a list of strings")
            if len(set(answer)) != len(answer):
                raise QuestionValidationError("multi answer values must be unique")
            if required and not answer:
                raise QuestionValidationError("answer is required")
            if any(item not in option_ids for item in answer) and not allow_custom:
                raise QuestionValidationError("custom answers are not allowed")
            value = [_text(item, "answer item", max_bytes=4096) for item in answer]
            if len(value) < validation.get("min_items", 0) or len(
                value
            ) > validation.get("max_items", float("inf")):
                raise QuestionValidationError("multi answer violates item limits")
            if "allowed_values" in validation and any(
                item not in validation["allowed_values"] for item in value
            ):
                raise QuestionValidationError(
                    "answer contains a value outside allowed_values"
                )
            return value
        if not isinstance(answer, str):
            raise QuestionValidationError("answer must be text")
        value = _text(answer, "answer", allow_empty=not required, max_bytes=16_000)
        if kind == "single" and value not in option_ids and not allow_custom:
            raise QuestionValidationError("custom answers are not allowed")
        length = len(value)
        if length < validation.get("min_length", 0) or length > validation.get(
            "max_length", float("inf")
        ):
            raise QuestionValidationError("answer violates text length limits")
        if "pattern" in validation and re.fullmatch(validation["pattern"], value) is None:
            raise QuestionValidationError("answer does not match validation pattern")
        if "allowed_values" in validation and value not in validation["allowed_values"]:
            raise QuestionValidationError("answer is outside allowed_values")
        return value

    def answer(self, question_id, revision, answer, channel) -> dict:
        question_id = _identifier(question_id, "question_id")
        revision = _non_negative_integer(revision, "revision")
        if channel not in QUESTION_CHANNELS:
            raise QuestionValidationError("unsupported answer channel")
        with self._transaction() as connection:
            row = self._fetch(connection, question_id)
            if row is None:
                raise QuestionNotFound(question_id)
            if row["answer_json"] is not None:
                raise LateAnswerConflict(self._accepted_public(row))
            if row["revision"] != revision:
                raise RevisionConflict(revision, row["revision"])
            if (
                row["expires_epoch"] is not None
                and row["expires_epoch"] <= _now().timestamp()
            ):
                raise QuestionExpired(question_id)
            normalized_answer = self._normalize_answer(row, copy.deepcopy(answer))
            changed = connection.execute(
                "UPDATE questions SET answer_json = ?, answered_by = ?, answered_at = ? "
                "WHERE question_id = ? AND answer_json IS NULL",
                (_json(normalized_answer), channel, _timestamp(), question_id),
            )
            if changed.rowcount != 1:
                winner = self._fetch(connection, question_id)
                raise LateAnswerConflict(self._accepted_public(winner))
            return copy.deepcopy(
                self._accepted_public(self._fetch(connection, question_id))
            )

    def get(self, question_id) -> dict | None:
        """The one question named by `question_id`, in the same public
        shape `pending()`/`list_for_project()` return, or `None`.

        Ticket 12 repair, condition 7: `question_id` is already this
        table's primary key, so no `project_id` is needed to look one up
        -- `scripts/creator_studio.py`'s `command_question_answer` uses
        this to read a question's `kind`/`options` before it can decide
        how to interpret `--answer-option-number`/`--answer-option-id`/
        `--answer-text` unambiguously, and `question answer` itself takes
        no `--project` flag to scope a `list_for_project` call by.
        """

        question_id = _identifier(question_id, "question_id")
        connection = self._connect()
        try:
            row = self._fetch(connection, question_id)
            return copy.deepcopy(self._public_question(row)) if row is not None else None
        finally:
            connection.close()

    def pending(self, project_id) -> list[dict]:
        project_id = _identifier(project_id, "project_id")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM questions WHERE project_id = ? AND answer_json IS NULL "
                "AND (expires_epoch IS NULL OR expires_epoch > ?) "
                "ORDER BY created_at, question_id",
                (project_id, _now().timestamp()),
            ).fetchall()
            return [copy.deepcopy(self._public_question(row)) for row in rows]
        finally:
            connection.close()

    def list_for_project(self, project_id) -> list[dict]:
        """Every question ever created for `project_id`, pending or
        answered -- unlike `pending`, which is scoped to the browser's own
        `questions[]` projection and only ever returns unanswered,
        unexpired rows.

        Ticket 12 repair, poправка оркестратора 1 (R14/R56i/G04): the
        chat-facing `question list` CLI command must show an
        already-accepted answer too, including one committed through the
        dashboard's own `POST /api/questions/{id}/answers` (`channel=
        "dashboard"`) -- `pending` intentionally never surfaces that at
        all, by design, since the browser has no use for an answered
        question.
        """

        project_id = _identifier(project_id, "project_id")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM questions WHERE project_id = ? "
                "ORDER BY created_at, question_id",
                (project_id,),
            ).fetchall()
            return [copy.deepcopy(self._public_question(row)) for row in rows]
        finally:
            connection.close()

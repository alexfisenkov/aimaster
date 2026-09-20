"""Chat-authored questions, answers and listings.

Ticket 12 repair, condition 15: one of six `authoring_*` responsibility
modules split out of the former monolithic `authoring.py` -- this one owns
`question create`, `question answer` and `question list`. See
`authoring_support.py`'s module docstring for the split's rationale.
"""

from __future__ import annotations

import secrets

from .authoring_support import AuthoringError
from .questions import QuestionStore
from .store import ProjectStore


_ANSWER_CHANNELS = frozenset({"chat", "telegram"})
# Ticket 13 (spec §6, "confirm понимает да/нет"): added alongside the
# original yes/no/true/false/1/0 forms, not in place of them.
_CONFIRM_TRUE = frozenset({"yes", "true", "1", "да"})
_CONFIRM_FALSE = frozenset({"no", "false", "0", "нет"})


def create_question(
    store: ProjectStore,
    questions_store: QuestionStore,
    project_id: str,
    *,
    question_id: str,
    text: str,
    kind: str,
    options: list,
    allow_custom: bool,
    required: bool,
    expires_at: str | None = None,
    validation: dict | None = None,
) -> dict:
    """Insert one pending question, per the §6 contract.

    `project_id`/`revision` are filled in from the live project (a plain
    `store.load`, not a `transact` -- this never mutates `state.json`).
    `resume_token` is generated here and never surfaced to the CLI's
    stdout: `QuestionStore.create`'s own public projection already drops
    it, and nothing above ever gets to see it either. `validation` (§6,
    ticket 12 repair поправка оркестратора 2) defaults to `{}` when the
    CLI's own `--validation` flag is absent (`None`, which `QuestionStore.
    create`'s own schema would otherwise reject outright -- it requires
    an object, never `None`); given one, it is passed straight through,
    unvalidated here, to `QuestionStore.create`, which already checks its
    shape against `question["kind"]` (ticket 12 repair, condition 9: this
    wrapper does not re-check what `QuestionStore.create` already will,
    it only fills in the one default `create` itself has no way to).

    This never sets `state["blocking_question_ids"]` -- the question
    shows up in `build_snapshot`'s `questions[]` regardless (`_snapshot`
    reads `QuestionStore.pending`, not `state.json`), without also
    gating the stage. Wiring a question to a hard gate needs a
    symmetrical "clear it on answer" path this ticket does not ask for.
    """

    if validation is None:
        validation = {}

    state = store.load(project_id)
    question = {
        "question_id": question_id,
        "project_id": project_id,
        "revision": state["revision"],
        "text": text,
        "kind": kind,
        "options": options,
        "allow_custom": allow_custom,
        "required": required,
        "validation": validation,
        "expires_at": expires_at,
        "resume_token": secrets.token_urlsafe(24),
    }
    created = questions_store.create(question)
    return {
        "project_id": project_id,
        "question_id": created["question_id"],
        "revision": created["revision"],
    }


def answer_question(
    questions_store: QuestionStore,
    question_id: str,
    revision: int,
    answer,
    channel: str,
) -> dict:
    """Answer a pending question from chat or Telegram (§6, R14/R56i/G04;
    ticket 12 repair поправка оркестратора 1).

    Goes through the exact same `QuestionStore.answer` the dashboard's
    own `POST /api/questions/{id}/answers` route uses -- first accepted
    answer wins across every channel, a later one gets
    `LateAnswerConflict` naming the answer that already won. The one
    thing this wrapper adds is narrowing `channel` to `chat`/`telegram`
    (narrower than `QuestionStore`'s own `QUESTION_CHANNELS`, which also
    allows `dashboard`): this CLI speaks for chat/Telegram only, the HTTP
    route is the one and only writer of a `dashboard` answer.

    Ticket 12 repair, condition 9: `question_id`/`revision` are no
    longer re-validated here -- `QuestionStore.answer` already checks
    both (`questions._identifier`/`_non_negative_integer`) and raises its
    own `QuestionValidationError`, a `QuestionError` the CLI's `main`
    already maps to exit code 3 exactly like `AuthoringError`, so
    duplicating either check here caught nothing a caller could not
    already get from `answer` itself.
    """

    if channel not in _ANSWER_CHANNELS:
        raise AuthoringError("channel must be chat or telegram")
    return questions_store.answer(question_id, revision, answer, channel)


def list_questions(questions_store: QuestionStore, project_id: str) -> list:
    """Every question for `project_id`, pending or answered (ticket 12
    repair поправка оркестратора 1) -- including one a dashboard click
    already answered through the `dashboard` channel, which `pending`
    intentionally never shows.
    """

    return questions_store.list_for_project(project_id)


def _resolve_option_by_position(token: str, options: list) -> str:
    """`token` is a 1-based position (`"2"` -> the second option's own
    id); return that option's own id.

    Ticket 13 (spec §6's numbered fallback, "ответ номером 1/2/3";
    replaces ticket 12's own `_resolve_option_token`): the former merged
    `--answer-option` flag guessed a token's meaning from its own shape
    (`isdigit()` -> a position, otherwise a literal id) -- so an option
    whose own id happened to be a digit string could never be selected
    by that id unless it also sat at that same position. `--answer-
    option-number` (this function) always means a position, never a
    literal id; `--answer-option-id` (plain pass-through in
    `resolve_cli_answer` below) always means the literal id, never
    re-interpreted as one, however it is spelled.
    """

    if not isinstance(token, str) or not token.isdigit():
        raise AuthoringError(
            f"--answer-option-number must be a positive integer, got {token!r}"
        )
    position = int(token)
    if position < 1 or position > len(options):
        raise AuthoringError(
            f"--answer-option-number {token!r} is out of range (1-{len(options)})"
        )
    return options[position - 1]["id"]


def resolve_cli_answer(
    question: dict,
    *,
    answer_text,
    answer_option_number: list,
    answer_option_id: list,
) -> object:
    """Turn `question answer`'s CLI flags into the one unambiguous Python
    value `QuestionStore.answer` expects for `question["kind"]`.

    Ticket 12 repair, condition 7: never "try JSON, then fall back to a
    raw string" -- the CLI's own old `--answer` flag did exactly that,
    which silently turned a `free_text` answer of `"2026"` into the
    integer `2026` (a valid JSON number) instead of keeping it the string
    `"2026"` `QuestionStore._normalize_answer` requires for that kind.
    Which of `answer_text`/`answer_option_number`/`answer_option_id` is
    legal, and what it means, is decided by `question["kind"]` alone,
    never by guessing at a value's own shape.

    Ticket 13 (spec §6, "Тесты краснеют на смешивании"): the single
    `--answer-option` flag this replaces is gone -- it could never
    select an option by a numeric-looking id unless that id also
    happened to sit at that same position (see `_resolve_option_by_
    position` above). `answer_option_number`/`answer_option_id` are
    each always a list (the CLI's own flags are both `action="append"`,
    default `[]`); `answer_text` is `None` when its own flag is absent.
    Exactly one of "`answer_text` given" / "at least one option flag
    given" must hold. For `multi`, the two option lists may be combined
    freely -- every `answer_option_number` entry resolves first, in its
    own order, then every `answer_option_id` entry, in its own order.
    """

    has_text = answer_text is not None
    has_option = bool(answer_option_number) or bool(answer_option_id)
    if has_text == has_option:
        raise AuthoringError(
            "exactly one of --answer-text or "
            "--answer-option-number/--answer-option-id is required"
        )

    kind = question.get("kind")
    if kind == "confirm":
        if has_option:
            raise AuthoringError(
                "confirm questions take --answer-text yes/no, not "
                "--answer-option-number/--answer-option-id"
            )
        normalized = answer_text.strip().lower()
        if normalized in _CONFIRM_TRUE:
            return True
        if normalized in _CONFIRM_FALSE:
            return False
        raise AuthoringError("confirm answer must be yes/no (or true/false, да/нет)")

    if kind == "free_text":
        if has_option:
            raise AuthoringError(
                "free_text questions take --answer-text, not "
                "--answer-option-number/--answer-option-id"
            )
        return answer_text

    if kind in {"single", "multi"}:
        if has_text:
            # A question with options still allows free-form custom text
            # when `allow_custom` is set -- `QuestionStore._normalize_
            # answer` itself is the one place that decides whether this
            # particular question actually allows it, not this function.
            return [answer_text] if kind == "multi" else answer_text
        options = question.get("options") or []
        resolved = [
            _resolve_option_by_position(token, options) for token in answer_option_number
        ]
        resolved.extend(answer_option_id)
        if kind == "single":
            if len(resolved) != 1:
                raise AuthoringError(
                    "single questions take exactly one "
                    "--answer-option-number or --answer-option-id"
                )
            return resolved[0]
        return resolved

    raise AuthoringError(f"unsupported question kind: {kind!r}")

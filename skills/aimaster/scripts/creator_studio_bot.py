#!/usr/bin/env python3
"""Explicit long-polling entrypoint for the dedicated Studio Telegram bot.

Importing this module does not read environment variables and does not open a
network connection.  Network I/O begins only after ``main`` validates the two
required environment variables and constructs the controller.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib import request


_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from studio.telegram_bot import TelegramBotController, TelegramBotError  # noqa: E402


class TelegramApiError(RuntimeError):
    """A sanitized Bot API transport or response error."""


_TELEGRAM_TEXT_LIMIT = 4096


def _text_chunks(text: str, limit: int = _TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Split plain text on Unicode-scalar boundaries within UTF-16 limits."""

    if not isinstance(text, str):
        raise TelegramApiError("Telegram message text must be a string")
    chunks = []
    current = []
    current_units = 0
    for character in text:
        units = 2 if ord(character) > 0xFFFF else 1
        if current and current_units + units > limit:
            chunks.append("".join(current))
            current = []
            current_units = 0
        current.append(character)
        current_units += units
    chunks.append("".join(current))
    return chunks


class TelegramBotApi:
    """Small standard-library Bot API client with an injectable opener."""

    def __init__(self, token: str, *, opener=request.urlopen):
        if not isinstance(token, str) or not token:
            raise TelegramApiError("Telegram token is required")
        self._base_url = f"https://api.telegram.org/bot{token}/"
        self._opener = opener

    def _call(self, method: str, payload: dict, *, timeout: int):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        outgoing = request.Request(
            self._base_url + method,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(outgoing, timeout=max(timeout + 5, 5)) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
        except Exception as error:
            # urllib exceptions commonly include their full URL, and the Bot
            # API URL contains the credential. Never interpolate `error`.
            raise TelegramApiError("Telegram request failed") from None
        if len(raw) > 2 * 1024 * 1024:
            raise TelegramApiError("Telegram response is too large")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TelegramApiError("Telegram returned an invalid response") from None
        if not isinstance(decoded, dict) or decoded.get("ok") is not True:
            raise TelegramApiError("Telegram rejected the request")
        return decoded.get("result")

    def get_updates(self, offset: int, timeout: int):
        result = self._call(
            "getUpdates",
            {"offset": offset, "timeout": timeout, "allowed_updates": ["message", "callback_query"]},
            timeout=timeout,
        )
        if not isinstance(result, list):
            raise TelegramApiError("Telegram updates response is invalid")
        return result

    def send_message(self, chat_id: int, text: str, reply_markup=None):
        result = None
        chunks = _text_chunks(text)
        for chunk in chunks:
            payload = {"chat_id": chat_id, "text": chunk}
            if reply_markup is not None and chunk == chunks[-1]:
                payload["reply_markup"] = reply_markup
            result = self._call(
                "sendMessage",
                payload,
                timeout=10,
            )
            if not isinstance(result, dict):
                raise TelegramApiError("Telegram delivery response is invalid")
        return result

    def answer_callback_query(self, query_id: str):
        self._call("answerCallbackQuery", {"callback_query_id": query_id}, timeout=10)

    def set_chat_menu_button(self, url: str):
        if not isinstance(url, str) or not url.startswith("https://"):
            raise TelegramApiError("Mini App URL must use HTTPS")
        mini_url = url if url.endswith("#mini-app") else url + "#mini-app"
        result = self._call(
            "setChatMenuButton",
            {"menu_button": {"type": "web_app", "text": "AI Мастерская", "web_app": {"url": mini_url}}},
            timeout=10,
        )
        if result is not True:
            raise TelegramApiError("Telegram did not accept the Mini App menu")
        return result


def _deliver_pending(controller, api):
    for reply in controller.pending_replies():
        api.send_message(reply.chat_id, reply.text, reply.reply_markup)
        # A crash after send_message but before this durable mark can produce a
        # duplicate outbound message on restart. Incoming project mutations are
        # idempotent; Telegram delivery itself is deliberately not called
        # exactly-once.
        controller.mark_delivered(reply.update_id)


def run_poll_iteration(controller, api, *, timeout=30, after_iteration=None):
    """Deliver the outbox, fetch one update batch and process it in order."""

    _deliver_pending(controller, api)
    updates = api.get_updates(controller.next_offset(), timeout)
    valid = [
        item for item in updates
        if isinstance(item, dict)
        and isinstance(item.get("update_id"), int)
        and not isinstance(item.get("update_id"), bool)
    ]
    for update in sorted(valid, key=lambda item: item["update_id"]):
        replies = controller.handle_update(update)
        for reply in replies:
            if reply.callback_query_id:
                api.answer_callback_query(reply.callback_query_id)
            api.send_message(reply.chat_id, reply.text, reply.reply_markup)
            controller.mark_delivered(reply.update_id)
    if after_iteration is not None:
        after_iteration(controller)
    return controller.next_offset()


def build_parser():
    parser = argparse.ArgumentParser(description="Run the owner-only Studio Telegram bot")
    parser.add_argument("--workspace", required=True, type=Path)
    return parser


def main(
    argv=None,
    *,
    environ=None,
    api_factory=TelegramBotApi,
    iterations=None,
    credential=None,
    owner_id=None,
    allow_pairing=False,
    after_iteration=None,
    pairing_code=None,
):
    """Run polling with injected local secrets or legacy environment values.

    The transport setup entrypoint passes the token directly from local secure
    storage, so it does not need to recreate a credential-bearing environment.
    """

    args = build_parser().parse_args(argv)
    environment = os.environ if environ is None else environ
    if credential is None:
        credential = environment.get("TELEGRAM_STUDIO_BOT_TOKEN")
    owner_value = owner_id if owner_id is not None else environment.get("TELEGRAM_STUDIO_OWNER_ID")
    if not credential or (owner_value is None or owner_value == "") and not allow_pairing:
        print(
            "TELEGRAM_STUDIO_BOT_TOKEN and TELEGRAM_STUDIO_OWNER_ID are required",
            file=sys.stderr,
        )
        return 2
    if owner_value is None or owner_value == "":
        owner_id = None
    else:
        try:
            owner_id = int(owner_value)
        except (TypeError, ValueError):
            print("TELEGRAM_STUDIO_OWNER_ID must be an integer", file=sys.stderr)
            return 2
    try:
        controller = TelegramBotController(args.workspace, owner_id, pairing_code=pairing_code)
        api = api_factory(credential)
        completed = 0
        while iterations is None or completed < iterations:
            run_poll_iteration(controller, api, after_iteration=after_iteration)
            completed += 1
    except (TelegramBotError, TelegramApiError, OSError, ValueError):
        print("Telegram Studio bot stopped because of a local or transport error", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

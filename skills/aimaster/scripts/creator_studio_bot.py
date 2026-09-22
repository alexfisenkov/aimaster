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
import re
import shutil
import ssl
import subprocess
import sys
import time
from pathlib import Path
from urllib import error as urllib_error
from urllib import request


_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from studio.telegram_bot import TelegramBotController, TelegramBotError  # noqa: E402


class TelegramApiError(RuntimeError):
    """A sanitized Bot API transport or response error.

    ``retryable`` says whether the same request may succeed later (network
    blips, 5xx, 429).  A 4xx answer is Telegram rejecting this exact
    request, so repeating it can only fail the same way.
    """

    def __init__(self, message, *, status=None, retryable=True):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


_TELEGRAM_TEXT_LIMIT = 4096

_DEFAULT_API_ORIGIN = "https://api.telegram.org"
API_ORIGIN_VARIABLE = "AIMASTER_TELEGRAM_API_ORIGIN"
_LOOPBACK_ORIGIN = re.compile(r"^http://127\.0\.0\.1:(?:[1-9][0-9]{0,4})$")


def resolve_api_origin(environ=None) -> str:
    """Return the Bot API origin, allowing only a loopback test override.

    The default stays ``https://api.telegram.org``.  A local end-to-end run
    may point the transport at its own mock server, but only at IPv4
    loopback: the origin carries the bot token in the path, so no override
    may ever direct it at a host that is not this machine.
    """

    environment = os.environ if environ is None else environ
    override = environment.get(API_ORIGIN_VARIABLE)
    if override is None or override == "":
        return _DEFAULT_API_ORIGIN
    if not _LOOPBACK_ORIGIN.fullmatch(override):
        raise TelegramApiError("Telegram API origin override must be an IPv4 loopback HTTP origin")
    return override


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


def _telegram_description(error) -> str:
    """': <description>' from a Bot API error body, or '' when unreadable."""

    try:
        decoded = json.loads(error.read(4096).decode("utf-8", "replace"))
    except Exception:
        return ""
    description = decoded.get("description") if isinstance(decoded, dict) else None
    if not isinstance(description, str) or not description:
        return ""
    return ": " + description[:200]


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _macos_system_roots() -> str:
    """Export the macOS system root certificates as PEM text ("" if not macOS)."""

    if sys.platform != "darwin" or not shutil.which("security"):
        return ""
    keychain = "/System/Library/Keychains/SystemRootCertificates.keychain"
    try:
        completed = subprocess.run(
            ["security", "find-certificate", "-a", "-p", keychain],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout if completed.returncode == 0 else ""


def build_ssl_context(*, certifi_path=None, system_roots=_macos_system_roots) -> ssl.SSLContext:
    """A verifying TLS context that works on a Python without root certificates.

    python.org builds ship with an empty OpenSSL trust store until the user
    runs «Install Certificates.command», so every HTTPS call fails with
    CERTIFICATE_VERIFY_FAILED while curl (macOS trust) works.  When the
    default store is empty, load certifi's bundle if it is installed,
    otherwise the macOS system roots.  Verification is never disabled.
    """

    context = ssl.create_default_context()
    if context.cert_store_stats().get("x509_ca", 0) > 0:
        return context
    if certifi_path is None:
        try:
            import certifi
            certifi_path = certifi.where()
        except ImportError:
            certifi_path = ""
    if certifi_path:
        try:
            context.load_verify_locations(cafile=certifi_path)
            return context
        except (OSError, ssl.SSLError):
            pass
    roots = system_roots()
    if roots:
        try:
            context.load_verify_locations(cadata=roots)
        except ssl.SSLError:
            pass
    return context


def default_opener():
    """urlopen equivalent that verifies TLS with `build_ssl_context`."""

    return request.build_opener(request.HTTPSHandler(context=build_ssl_context())).open


class TelegramBotApi:
    """Small standard-library Bot API client with an injectable opener."""

    def __init__(self, token: str, *, opener=request.urlopen, environ=None):
        if not isinstance(token, str) or not token:
            raise TelegramApiError("Telegram token is required")
        origin = resolve_api_origin(environ)
        self._base_url = f"{origin}/bot{token}/"
        if opener is request.urlopen:
            if origin != _DEFAULT_API_ORIGIN:
                # A loopback override must stay on this machine: a local
                # server answering 3xx could otherwise send the token-bearing
                # URL to any host, because urlopen follows redirects by default.
                opener = request.build_opener(_NoRedirect).open
            else:
                opener = default_opener()
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
        except urllib_error.HTTPError as error:
            # Telegram's `description` names the problem ("message is too
            # long", "chat not found") and never carries the token; the
            # exception's own text would carry the credential-bearing URL.
            status = error.code
            description = _telegram_description(error)
            error.close()
            raise TelegramApiError(
                f"Telegram rejected {method}: HTTP {status}{description}",
                status=status,
                retryable=status == 429 or status >= 500,
            ) from None
        except Exception as error:
            # urllib exceptions commonly include their full URL, and the Bot
            # API URL contains the credential. Never interpolate `error`.
            reason = getattr(error, "reason", None)
            kind = type(reason).__name__ if reason is not None else type(error).__name__
            raise TelegramApiError(f"Telegram request failed ({method}: {kind})") from None
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
        for index, chunk in enumerate(chunks):
            payload = {"chat_id": chat_id, "text": chunk}
            if reply_markup is not None and index == len(chunks) - 1:
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

    def reset_chat_menu_button(self):
        """Return the chat menu to its default when no public URL is live.

        A menu button keeps pointing at the last URL it was given, so a
        tunnel that died would otherwise leave the owner one tap away from
        an empty screen until a new tunnel is published.
        """

        result = self._call(
            "setChatMenuButton",
            {"menu_button": {"type": "default"}},
            timeout=10,
        )
        if result is not True:
            raise TelegramApiError("Telegram did not reset the Mini App menu")
        return result


_REJECTED_REPLY_TEXT = "Не удалось отправить ответ: Telegram отклонил сообщение ({status}). Откройте раздел в AI Мастерской."


def _send_reply(controller, api, reply):
    """Send one reply; a reply Telegram rejects is replaced, not retried forever.

    A durable reply that Telegram answers with 4xx would otherwise be resent
    on every restart and stop the transport each time.  Transient failures
    (network, 5xx, 429) propagate so the caller can retry the iteration.
    """

    try:
        api.send_message(reply.chat_id, reply.text, reply.reply_markup)
    except TelegramApiError as error:
        if error.retryable:
            raise
        print(f"{error}. Ответ заменён уведомлением.", file=sys.stderr, flush=True)
        api.send_message(
            reply.chat_id,
            _REJECTED_REPLY_TEXT.format(status=error.status),
            reply.reply_markup,
        )
    # A crash after send_message but before this durable mark can produce a
    # duplicate outbound message on restart. Incoming project mutations are
    # idempotent; Telegram delivery itself is deliberately not called
    # exactly-once.
    controller.mark_delivered(reply.update_id)


def _deliver_pending(controller, api):
    for reply in controller.pending_replies():
        _send_reply(controller, api, reply)


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
            _send_reply(controller, api, reply)
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
    sleep=time.sleep,
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
        failures = 0
        while iterations is None or completed < iterations:
            try:
                run_poll_iteration(controller, api, after_iteration=after_iteration)
            except TelegramApiError as error:
                # A network blip or a Telegram-side error must not stop the
                # transport: the owner would find a dead bot after the first
                # dropped packet.  Wait a little longer each time and go on.
                failures += 1
                delay = min(30.0, float(2 ** min(failures, 5)))
                print(f"{error}. Повтор через {delay:.0f} с.", file=sys.stderr, flush=True)
                sleep(delay)
                completed += 1
                continue
            failures = 0
            completed += 1
    except (TelegramBotError, OSError, ValueError) as error:
        print(
            f"Telegram Studio bot stopped because of a local error ({type(error).__name__})",
            file=sys.stderr,
        )
        return 3
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

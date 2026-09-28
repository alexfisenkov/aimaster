"""Telegram Mini App authentication adapter for the existing Studio app."""

from __future__ import annotations

import hashlib
import hmac
import json
import posixpath
import re
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qsl, unquote, urlsplit

from .http_app import Response
from .http_write import write_response
from .loopback_http import LoopbackThreadingHTTPServer

# План Б (экран «Сборка»): монтажный стол и «Показать в папке» — только на
# компьютере владельца. Через шлюз (телефон, туннель) их нет: Studio наружу не
# выставляется, а папка открылась бы на компьютере, а не у человека в руках.
_LOCAL_ONLY = re.compile(r"/api/projects/.+/montage/(?:desk|desk/close|reveal)")
_DECODE_ROUNDS = 4


def validate_init_data(raw: str, bot_token: str, owner_id: int, *, now=None, max_age=86400) -> dict:
    if not isinstance(raw, str) or not raw:
        raise ValueError("missing Telegram initData")
    if not isinstance(bot_token, str) or not bot_token:
        raise ValueError("missing bot token")
    fields = dict(parse_qsl(raw, keep_blank_values=True, strict_parsing=True))
    supplied_hash = fields.pop("hash", None)
    if not supplied_hash:
        raise ValueError("missing Telegram initData signature")
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(expected, supplied_hash):
        raise ValueError("invalid Telegram initData signature")
    try:
        auth_date = int(fields.get("auth_date", ""))
    except ValueError:
        raise ValueError("invalid Telegram auth_date") from None
    current = int(time.time() if now is None else now)
    if auth_date > current + 60 or current - auth_date > max_age:
        raise ValueError("stale Telegram initData")
    try:
        user = json.loads(fields.get("user", ""))
    except json.JSONDecodeError:
        raise ValueError("invalid Telegram user data") from None
    if not isinstance(user, dict) or user.get("id") != owner_id:
        raise ValueError("Telegram owner mismatch")
    return user


class MiniAppGateway:
    """Authenticate Telegram requests and delegate to loopback Studio."""

    def __init__(self, inner, bot_token: str, owner_id: int):
        self.inner = inner
        self.bot_token = bot_token
        self.owner_id = owner_id
        self.ticket_key = hmac.new(b"AI-Master-asset", bot_token.encode(), hashlib.sha256).digest()

    @staticmethod
    def _is_protected(path: str) -> bool:
        # Authenticate everything except the exact document and known static
        # files. This intentionally treats encoded separators as protected;
        # Studio later decodes paths before routing them.
        #
        # Repair, 2026-09-21: the caller passes the *parsed* path now. It
        # used to pass the raw request target, so the document was only
        # public at a bare "/": the dashboard's own `history.pushState`
        # turns the address into `/?project=<id>`, and reloading the Telegram
        # WebView on that address was answered with a raw 403 JSON body
        # instead of the page -- no dashboard, no diagnostics, no way back.
        return path != "/" and not path.startswith("/static/")

    @staticmethod
    def _forbidden():
        # Repair, 2026-09-21: this used to declare `Content-Length: 31` for a
        # 30-byte body, and `_MiniAppHandler` adds the real length on top of
        # whatever the response already carries -- so every 403 went out with
        # two conflicting Content-Length headers. RFC 9112 §6.3 calls that
        # invalid framing a recipient MUST reject, which through the
        # cloudflared tunnel turns the Mini App's "not authorized" answer
        # into a tunnel error instead of the JSON the dashboard can report.
        # The length is left to the one layer that knows the body.
        return Response(
            403,
            {"Content-Type": "application/json"},
            b'{"error":{"code":"forbidden"}}',
        )

    def _asset_ticket(self, asset_id: str, expires: int) -> str:
        message = f"{asset_id}:{expires}".encode()
        return hmac.new(self.ticket_key, message, hashlib.sha256).hexdigest()

    def _valid_asset_ticket(self, asset_id: str, query: str) -> bool:
        values = dict(parse_qsl(query, keep_blank_values=True))
        try:
            expires = int(values.get("e", "0"))
        except ValueError:
            return False
        if expires < int(time.time()):
            return False
        try:
            # compare_digest refuses non-ASCII str; a ticket like `t=%D0%B6`
            # must simply be invalid, not an exception on an anonymous request.
            return secrets.compare_digest(
                values.get("t", "").encode("utf-8", "surrogatepass"),
                self._asset_ticket(asset_id, expires).encode(),
            )
        except (TypeError, ValueError):
            return False

    def _rewrite_asset_urls(self, response):
        if not response.headers.get("Content-Type", "").startswith("application/json"):
            return response
        try:
            value = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return response
        expires = int(time.time()) + 300

        def rewrite(item):
            if isinstance(item, dict):
                return {key: rewrite(value) for key, value in item.items()}
            if isinstance(item, list):
                return [rewrite(value) for value in item]
            if isinstance(item, str) and item.startswith("/assets/") and "?" not in item:
                asset_id = item.removeprefix("/assets/")
                return f"{item}?e={expires}&t={self._asset_ticket(asset_id, expires)}"
            return item

        body = json.dumps(rewrite(value), ensure_ascii=False, separators=(",", ":")).encode()
        headers = dict(response.headers)
        headers["Content-Length"] = str(len(body))
        return Response(response.status, headers, body)

    @staticmethod
    def _local_only(path: str) -> bool:
        """Путь стола или папки — в том виде, в каком его увидит дашборд
        (`http_app._path` раскодирует процентные последовательности), и ещё
        строже: раскодированный до конца (`%252F`), без двойных и конечных «/»,
        без «.» и «..». Не раскодируется — тоже «нельзя»: дашборд его всё равно
        не примет."""

        text = path
        for _ in range(_DECODE_ROUNDS):
            try:
                decoded = unquote(text, errors="strict")
            except (UnicodeDecodeError, ValueError):
                return True
            if decoded == text:
                break
            text = decoded
        else:
            return True
        flat = posixpath.normpath(re.sub(r"/+", "/", text))
        return any(_LOCAL_ONLY.fullmatch(form) for form in (text, flat))

    def handle(self, method, path, headers, body):
        normalized = {key.casefold(): value for key, value in headers}
        parsed = urlsplit(path)
        # И путь, который уйдёт дашборду, и цель запроса как есть: «//api/…»
        # urlsplit считает адресом хоста — такую цель тоже не пускаем.
        if any(self._local_only(form) for form in (parsed.path, path.partition("?")[0])):
            return self._forbidden()  # до проверки входа и без обращения к дашборду
        asset_path = parsed.path.startswith("/assets/")
        asset_id = parsed.path.removeprefix("/assets/") if asset_path else ""
        ticket_ok = asset_path and "/" not in asset_id and self._valid_asset_ticket(asset_id, parsed.query)
        if self._is_protected(parsed.path) and not ticket_ok:
            authorization = normalized.get("authorization", "")
            if not authorization.startswith("tma "):
                return self._forbidden()
            try:
                validate_init_data(authorization[4:], self.bot_token, self.owner_id)
            except ValueError:
                return self._forbidden()
        forwarded = [("Host", self.inner.authority)]
        if "content-type" in normalized:
            forwarded.append(("Content-Type", normalized["content-type"]))
        if method.upper() == "POST":
            forwarded.extend(
                [
                    ("Origin", self.inner.origin),
                    ("X-CSRF-Token", normalized.get("x-csrf-token", "")),
                ]
            )
        if "range" in normalized:
            forwarded.append(("Range", normalized["range"]))
        response = self.inner.handle(method, parsed.path, forwarded, body)
        if method.upper() == "GET" and parsed.path.startswith("/api/"):
            response = self._rewrite_asset_urls(response)
        return response


@dataclass(slots=True)
class RunningMiniApp:
    base_url: str
    _server: LoopbackThreadingHTTPServer
    _thread: threading.Thread

    def close(self):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _MiniAppHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _dispatch(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 2 * 1024 * 1024:
                raise ValueError
            body = self.rfile.read(length) if length else b""
            response = self.server.gateway.handle(
                self.command, self.path, list(self.headers.items()), body
            )
        except Exception:
            # Fail closed with a real HTTP answer. The request body may be
            # unread (oversized or malformed Content-Length), so the
            # keep-alive connection must not be reused: leftover bytes would
            # be parsed as the next request on a socket the tunnel shares.
            response = MiniAppGateway._forbidden()
            self.close_connection = True
        # Одна настоящая длина и поток файла кусками — http_write (там же
        # объяснено, почему Content-Length из ответа не повторяется).
        write_response(self, response)

    do_GET = _dispatch
    do_POST = _dispatch
    do_HEAD = _dispatch

    def log_message(self, format, *args):
        return


def serve_mini_app(inner, bot_token: str, owner_id: int, *, host="127.0.0.1", port=0):
    if host != "127.0.0.1":
        raise ValueError("Mini App gateway may bind only to 127.0.0.1")
    server = LoopbackThreadingHTTPServer((host, port), _MiniAppHandler)
    server.gateway = MiniAppGateway(inner, bot_token, owner_id)
    assigned = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, name=f"aimaster-mini-app-{assigned}", daemon=True)
    thread.start()
    return RunningMiniApp(f"http://127.0.0.1:{assigned}", server, thread)

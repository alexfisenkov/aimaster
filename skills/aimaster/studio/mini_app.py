"""Telegram Mini App authentication adapter for the existing Studio app."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl

from .http_app import Response


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

    @staticmethod
    def _is_protected(path: str) -> bool:
        # Authenticate everything except the exact document and known static
        # files. This intentionally treats encoded separators as protected;
        # Studio later decodes paths before routing them.
        return path != "/" and not path.startswith("/static/")

    @staticmethod
    def _forbidden():
        return Response(
            403,
            {"Content-Type": "application/json", "Content-Length": "31"},
            b'{"error":{"code":"forbidden"}}',
        )

    def handle(self, method, path, headers, body):
        normalized = {key.casefold(): value for key, value in headers}
        if self._is_protected(path):
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
        return self.inner.handle(method, path, forwarded, body)


@dataclass(slots=True)
class RunningMiniApp:
    base_url: str
    _server: ThreadingHTTPServer
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
        except ValueError:
            response = MiniAppGateway._forbidden()
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

    def log_message(self, format, *args):
        return


def serve_mini_app(inner, bot_token: str, owner_id: int, *, host="127.0.0.1", port=0):
    if host != "127.0.0.1":
        raise ValueError("Mini App gateway may bind only to 127.0.0.1")
    server = ThreadingHTTPServer((host, port), _MiniAppHandler)
    server.gateway = MiniAppGateway(inner, bot_token, owner_id)
    assigned = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, name=f"aimaster-mini-app-{assigned}", daemon=True)
    thread.start()
    return RunningMiniApp(f"http://127.0.0.1:{assigned}", server, thread)

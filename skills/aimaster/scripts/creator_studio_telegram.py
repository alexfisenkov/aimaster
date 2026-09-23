#!/usr/bin/env python3
"""Local setup and launch entrypoint for the Studio Telegram transport.

Importing this module and rendering ``--help`` are deliberately offline.  The
Bot API is only constructed by the existing polling entrypoint after ``run``
loads a locally stored credential.
"""

from __future__ import annotations

import argparse
import getpass
import html
import os
import queue
import re
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler
from pathlib import Path


_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from creator_studio_bot import TelegramApiError, TelegramBotApi, build_ssl_context  # noqa: E402
from studio.platform_compat import (  # noqa: E402
    IS_MACOS,
    IS_WINDOWS,
    ensure_utf8_stdio,
    is_private,
    make_private,
    open_nofollow,
    user_data_dir,
)
from studio.loopback_http import LoopbackThreadingHTTPServer  # noqa: E402
from studio.telegram_bot import TelegramBotState, TelegramBotError  # noqa: E402
from studio.workspace import PRIVATE_DIR_NAME, resolve_workspace_paths  # noqa: E402


_TOKEN_PATTERN = re.compile(r"^[0-9]{6,20}:[A-Za-z0-9_-]{20,}$")
_KEYCHAIN_SERVICE = "ai-master-studio-telegram"
_KEYCHAIN_ACCOUNT = "bot-token"
_TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
# A quick tunnel is published before its hostname resolves everywhere, so the
# URL is probed until it answers instead of being advertised immediately.  The
# first probe waits on purpose: a query sent before the name has spread gets
# an NXDOMAIN that the local resolver then caches for minutes.
# Measured on the owner's network: the edge answered 404 for 53 s after the
# URL appeared, so the budget is ~65 s.  It costs nothing now that the check
# runs off the polling thread.
_TUNNEL_PROBE_DELAY = 5.0
_TUNNEL_PROBE_ATTEMPTS = 24
_TUNNEL_PROBE_INTERVAL = 2.5
# cloudflared can die at any moment (network change, its own watchdog).  The
# restart is retried on a widening delay so a machine without the executable,
# or without network, does not spawn an attempt on every polling iteration.
_TUNNEL_BACKOFF_SECONDS = (5.0, 15.0, 45.0, 120.0, 300.0)
# Owners who already run a named Cloudflare tunnel (or any other permanent
# HTTPS front) point it at a fixed loopback port and pass the public address
# here.  Neither value is a secret, so both are plain environment variables.
MINI_APP_URL_VARIABLE = "AIMASTER_MINI_APP_PUBLIC_URL"
MINI_APP_PORT_VARIABLE = "AIMASTER_MINI_APP_PORT"


def _default_fallback_path() -> Path:
    """Keep the fallback outside project state when setup has no workspace.

    macOS keeps ``~/Library/Application Support/AI Мастерская`` exactly as
    before; Windows uses ``%LOCALAPPDATA%\\AI Мастерская`` and Linux the XDG
    data directory.  A Linux install that already stored its token under the
    old macOS-style path keeps using it.
    """

    path = user_data_dir() / "telegram-bot-token"
    if not IS_MACOS and not IS_WINDOWS and not path.exists():
        legacy = Path.home() / "Library" / "Application Support" / "AI Мастерская" / "telegram-bot-token"
        if legacy.exists():
            return legacy
    return path


def validate_bot_token(token: str) -> str:
    """Accept only a non-whitespace BotFather token without echoing it."""

    if not isinstance(token, str) or not _TOKEN_PATTERN.fullmatch(token):
        raise ValueError("invalid Telegram bot token")
    return token


def render_setup_html(message="", pairing_code=None) -> str:
    result = ""
    if pairing_code:
        result = (
            f'<p class="ok">{html.escape(message or "Готово")}</p>'
            f'<p>Отправьте боту: <code>/start {html.escape(pairing_code)}</code></p>'
            "<p>После этого окно можно закрыть.</p>"
        )
    elif message:
        result = f"<p>{html.escape(message)}</p>"
    form = "" if pairing_code else (
        '<form method="post" action="/setup">'
        '<label>Токен BotFather<input name="token" type="password" required autocomplete="off"></label>'
        '<button type="submit">Подключить Telegram</button></form>'
    )
    return """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Мастерская — Telegram</title><style>
body{font:16px -apple-system,BlinkMacSystemFont,sans-serif;max-width:520px;margin:12vh auto;padding:24px;color:#16191d;background:#f5f6f7}
main{background:white;border:1px solid #dfe3e8;border-radius:18px;padding:28px;box-shadow:0 8px 30px #0000000d}h1{font-size:24px}
label{display:grid;gap:8px}input{font:inherit;padding:12px;border:1px solid #bbc3cc;border-radius:10px}button{margin-top:18px;padding:12px 16px;border:0;border-radius:10px;background:#101418;color:white;font:inherit}.ok{color:#087443}
</style><main><h1>AI Мастерская · Telegram</h1><p>Токен обрабатывается только на этом компьютере.</p>""" + result + form + "</main>"


def run_setup_ui(*, token_store=None, pairing_store=None, open_browser=True):
    token_store = token_store or LocalSecretStore(_default_fallback_path())
    pairing_store = pairing_store or PairingCodeStore(
        _default_fallback_path().with_name("telegram-pairing-code")
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = render_setup_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4096:
                    raise ValueError
                raw = self.rfile.read(length).decode("utf-8")
                submitted = urllib.parse.parse_qs(raw).get("token", [""])[0]
                token_store.store(submitted)
                code = pairing_store.store_new()
                body = render_setup_html("Telegram подключён локально.", pairing_code=code).encode("utf-8")
                self.server.setup_complete = True
            except Exception:
                body = render_setup_html("Не удалось сохранить токен. Проверьте его и повторите.").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    server = LoopbackThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.setup_complete = False
    url = f"http://127.0.0.1:{server.server_address[1]}"
    if open_browser:
        webbrowser.open(url)
    try:
        while not server.setup_complete:
            server.handle_request()
    finally:
        server.server_close()
    return url


def _default_cloudflared_config_path() -> Path:
    return _default_fallback_path().with_name("cloudflared-empty-config.yml")


def empty_cloudflared_config(path=None) -> Path:
    """Create the empty config file the quick tunnel must be started with.

    ``cloudflared tunnel --url`` reads ``~/.cloudflared/config.yml`` when no
    config is given.  An owner who already runs a named tunnel has ingress
    rules there, and their catch-all (``service: http_status:404``) answers
    every request to the quick tunnel's own hostname: the edge returns an
    empty 404 and nothing ever reaches this Mini App gateway.  An empty file
    of our own keeps those rules out without touching the owner's config.
    """

    target = Path(path) if path is not None else _default_cloudflared_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = open_nofollow(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(descriptor)
    return target


def cloudflared_command(local_url: str, *, config_path=None) -> list[str]:
    if not isinstance(local_url, str) or not local_url.startswith("http://127.0.0.1:"):
        raise ValueError("cloudflared target must be a loopback HTTP URL")
    executable = shutil.which("cloudflared")
    if not executable:
        raise RuntimeError("cloudflared is not installed")
    # QUIC (the cloudflared default) travels over UDP and is dropped or rate
    # limited on many home networks, where the tunnel then dies minutes after
    # it started.  HTTP/2 uses the same TCP path the dashboard already needs.
    return [
        executable,
        "tunnel",
        "--config",
        str(empty_cloudflared_config(config_path)),
        "--url",
        local_url,
        "--no-autoupdate",
        "--protocol",
        "http2",
    ]


def _read_until_url(stream, lines):
    """Hand cloudflared's first lines over until the one carrying the URL.

    A thread instead of ``select`` on the pipe: Windows can only ``select``
    sockets.  The thread stops right after the URL line, so the supervisor's
    own drain is then the only reader of the pipe.
    """

    try:
        for line in stream:
            lines.put(line)
            if _TUNNEL_URL.search(line):
                return
    except (OSError, ValueError):
        pass
    lines.put(None)


def start_cloudflared(local_url: str, *, popen=subprocess.Popen, timeout=12, config_path=None):
    process = popen(
        cloudflared_command(local_url, config_path=config_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lines = queue.Queue()
    reader = threading.Thread(
        target=_read_until_url, args=(process.stdout, lines),
        name="aimaster-tunnel-start", daemon=True,
    )
    reader.start()
    deadline = time.monotonic() + timeout
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=min(0.25, remaining))
        except queue.Empty:
            continue
        if line is None:
            break
        match = _TUNNEL_URL.search(line)
        if match:
            # The caller must keep reading this pipe: cloudflared logs for as
            # long as it runs and blocks on a full pipe buffer if nobody does.
            reader.join()
            return process, match.group(0)
    process.terminate()
    raise RuntimeError("cloudflared did not provide an HTTPS URL")


def resolve_public_mini_app_url(environ=None):
    """Return the owner's permanent Mini App address, or ``None``.

    Telegram opens this address itself, so it must be a plain HTTPS origin:
    a query or fragment would be lost behind the ``#mini-app`` the menu
    appends, and credentials in the URL would travel to Telegram.
    """

    environment = os.environ if environ is None else environ
    value = (environment.get(MINI_APP_URL_VARIABLE) or "").strip()
    if not value:
        return None
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"{MINI_APP_URL_VARIABLE} must be an https:// address")
    if parts.query or parts.fragment:
        raise ValueError(f"{MINI_APP_URL_VARIABLE} must carry no query and no fragment")
    if parts.username or parts.password:
        raise ValueError(f"{MINI_APP_URL_VARIABLE} must carry no user name or password")
    return value.rstrip("/")


def resolve_mini_app_port(environ=None) -> int:
    """Return the fixed loopback port for the gateway, or 0 for any free one."""

    environment = os.environ if environ is None else environ
    value = (environment.get(MINI_APP_PORT_VARIABLE) or "").strip()
    if not value:
        return 0
    try:
        port = int(value)
    except ValueError:
        raise ValueError(f"{MINI_APP_PORT_VARIABLE} must be a number") from None
    if not 1024 <= port <= 65535:
        raise ValueError(f"{MINI_APP_PORT_VARIABLE} must be between 1024 and 65535")
    return port


TUNNEL_READY = "ready"
TUNNEL_UNRESOLVED = "unresolved"
TUNNEL_UNREACHABLE = "unreachable"
TUNNEL_UNCONFIRMED = "unconfirmed"
# This machine's Python cannot verify TLS at all (python.org builds ship
# without root certificates until `Install Certificates.command` is run).
# Nothing about the tunnel can be learned from that, so it is published at once.
TUNNEL_UNVERIFIABLE = "unverifiable"
# How many freshly started tunnels may fail their check before one is
# published anyway.  Restarting forever would leave the owner with no button
# at all, which is the very failure this supervision exists to end.
_TUNNEL_UNCONFIRMED_LIMIT = 3


def tunnel_warning(verification) -> str:
    """The line the owner sees when a published URL was not confirmed."""

    if verification == TUNNEL_UNRESOLVED:
        return (
            "Имя туннеля ещё не разошлось по DNS; кнопка появится, "
            "проверьте через минуту."
        )
    if verification == TUNNEL_UNVERIFIABLE:
        return (
            "Python на этом компьютере не может проверить TLS-сертификаты "
            "(нет корневых сертификатов), поэтому туннель не проверен отсюда. "
            "Публикую адрес как есть; проверьте кнопку в Telegram. Для Python "
            "с python.org запустите «Install Certificates.command»."
        )
    return (
        "Туннель поднят, но проверить его с этого компьютера не удалось. "
        "Публикую адрес как есть; если кнопка не открывается, проверьте сеть."
    )


_TUNNEL_EDGE_HOST = "trycloudflare.com"
_HOSTNAME_PATTERN = re.compile(r"^[A-Za-z0-9.-]+$")


def probe_tunnel_url(
    url: str,
    *,
    timeout=8,
    edge_host=_TUNNEL_EDGE_HOST,
    resolver=socket.getaddrinfo,
    connector=socket.create_connection,
    context_factory=build_ssl_context,
) -> str:
    """Ask the tunnel for its root without resolving the tunnel's own name.

    A quick tunnel's hostname appears in DNS seconds after the URL is
    printed.  Asking earlier earns an NXDOMAIN that the local resolver then
    repeats from cache for minutes -- poisoning not only this probe but also
    the Telegram client on the same Mac.  So the probe never looks the name
    up: it resolves the always-present ``trycloudflare.com``, opens TLS to
    that edge with the tunnel's name as SNI and asks for ``/`` with a
    matching ``Host`` header, exactly as ``curl --resolve`` would.  A
    permanent address on someone's own domain has stable DNS and is
    resolved normally.

    ``ready`` is any 2xx/3xx.  A 404 (the edge has the tunnel's name but no
    route to it yet) and 5xx are ``unreachable`` and worth another attempt.
    """

    parts = urllib.parse.urlsplit(url)
    try:
        hostname = parts.hostname
        port = parts.port or 443
    except ValueError:
        # A malformed address must never reach a socket or a request header.
        return TUNNEL_UNREACHABLE
    if not hostname or not _HOSTNAME_PATTERN.fullmatch(hostname):
        return TUNNEL_UNREACHABLE
    target = edge_host if hostname.endswith("." + edge_host) else hostname
    try:
        candidates = resolver(target, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return TUNNEL_UNRESOLVED
    except OSError:
        return TUNNEL_UNREACHABLE
    address = next((item[4] for item in candidates), None)
    if address is None:
        return TUNNEL_UNRESOLVED
    payload = (
        f"GET / HTTP/1.1\r\nHost: {hostname}\r\n"
        "User-Agent: aimaster-tunnel-probe\r\nAccept: */*\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    try:
        context = context_factory()
        with connector(tuple(address[:2]), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=hostname) as secure:
                secure.settimeout(timeout)
                secure.sendall(payload)
                head = b""
                while b"\r\n" not in head and len(head) < 512:
                    chunk = secure.recv(256)
                    if not chunk:
                        break
                    head += chunk
    except ssl.SSLCertVerificationError:
        return TUNNEL_UNVERIFIABLE
    except (OSError, ssl.SSLError, ValueError):
        return TUNNEL_UNREACHABLE
    fields = head.split(b"\r\n", 1)[0].split()
    if len(fields) < 2 or not fields[0].upper().startswith(b"HTTP/"):
        return TUNNEL_UNREACHABLE
    try:
        status = int(fields[1])
    except ValueError:
        return TUNNEL_UNREACHABLE
    return TUNNEL_READY if 200 <= status < 400 else TUNNEL_UNREACHABLE


class TunnelSupervisor:
    """Keep one Cloudflare Quick Tunnel alive in front of the Mini App.

    The transport used to start cloudflared once and forget it, so a child
    that died left the bot advertising a hostname nothing served.  All of the
    slow work -- starting cloudflared, waiting for the name to spread,
    probing it, backing off, watching the child -- happens on this object's
    own thread.  ``ensure`` only reads the decided state, because it is
    called from the polling loop: a second spent here is a second the owner's
    commands go unanswered.
    """

    def __init__(
        self,
        local_url,
        *,
        starter=start_cloudflared,
        probe=probe_tunnel_url,
        sleep=None,
        probe_delay=_TUNNEL_PROBE_DELAY,
        probe_attempts=_TUNNEL_PROBE_ATTEMPTS,
        probe_interval=_TUNNEL_PROBE_INTERVAL,
        backoff=_TUNNEL_BACKOFF_SECONDS,
        unconfirmed_limit=_TUNNEL_UNCONFIRMED_LIMIT,
        poll_interval=1.0,
    ):
        self.local_url = local_url
        self.process = None
        self.url = None
        # ``ready`` when the dashboard answered through the tunnel; the other
        # values say why the published URL could not be confirmed here.
        # ``None`` means "still deciding" and nothing may be published yet.
        self.verification = None
        self._starter = starter
        self._probe = probe
        self._sleep = sleep
        self._probe_delay = probe_delay
        self._probe_attempts = probe_attempts
        self._probe_interval = probe_interval
        self._backoff = tuple(backoff)
        self._unconfirmed_limit = unconfirmed_limit
        self._poll_interval = poll_interval
        self._lock = threading.RLock()
        self._stopping = threading.Event()
        self._worker = None
        self._reader = None
        self._failures = 0
        self._unconfirmed = 0

    @property
    def verified(self):
        """True only when the dashboard really answered through the tunnel."""

        return self.verification == TUNNEL_READY

    def ensure(self):
        """Return the decided public URL.  Never sleeps, never waits on I/O."""

        self._start_worker()
        with self._lock:
            return self.url if self.verification is not None else None

    def stop(self):
        """Stop supervising, terminate the tunnel and join both threads."""

        self._stopping.set()
        worker = self._worker
        self._discard()
        if worker is not None:
            worker.join(timeout=10)
        self._worker = None

    # -- the supervising thread ---------------------------------------------

    def _start_worker(self):
        if self._stopping.is_set():
            return
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._supervise, name="aimaster-tunnel", daemon=True
            )
            self._worker.start()

    def _supervise(self):
        while not self._stopping.is_set():
            if self._start() is None:
                self._failures += 1
                index = min(self._failures, len(self._backoff)) - 1
                if self._pause(self._backoff[index]):
                    return
                continue
            self._failures = 0
            self._watch()

    def _watch(self):
        """Hold the tunnel until it dies or the transport stops."""

        while not self._stopping.is_set():
            if not self._alive():
                self._discard()
                return
            if self._stopping.wait(self._poll_interval):
                return

    def _pause(self, seconds):
        """Wait, but wake at once when the transport is stopping."""

        if self._sleep is not None:
            self._sleep(seconds)
            return self._stopping.is_set()
        return self._stopping.wait(seconds)

    def _start(self):
        with self._lock:
            self.verification = None
        try:
            process, url = self._starter(self.local_url)
        except (OSError, RuntimeError, ValueError):
            return None
        reader = threading.Thread(target=self._drain, args=(process,), daemon=True)
        reader.start()
        with self._lock:
            self.process = process
            self.url = url
            self._reader = reader
        verification = self._verify(url)
        if verification is None:
            self._discard()
            return None
        with self._lock:
            if self.url != url:
                # The tunnel was discarded while the probe was running.
                return None
            self.verification = verification
        return url

    def _verify(self, url):
        """Decide how the new name may be used, or ``None`` to start over.

        The first probe is deliberately late, because a quick tunnel needs
        seconds to reach the edge.  A name that answers nothing is retried
        and then restarted -- but only a few times: after that the URL is
        published unconfirmed, since an unconfirmed button beats no button.
        """

        if self._pause(self._probe_delay):
            return None
        verdicts = []
        for attempt in range(self._probe_attempts):
            if self._stopping.is_set() or not self._alive():
                return None
            verdict = self._probe(url)
            if verdict == TUNNEL_READY:
                self._unconfirmed = 0
                return TUNNEL_READY
            if verdict == TUNNEL_UNVERIFIABLE:
                # Repeating the probe cannot change a missing certificate
                # store, and restarting would punish a healthy tunnel.
                return TUNNEL_UNVERIFIABLE
            verdicts.append(verdict)
            if attempt + 1 < self._probe_attempts:
                if self._pause(self._probe_interval):
                    return None
        if verdicts and all(item == TUNNEL_UNRESOLVED for item in verdicts):
            return TUNNEL_UNRESOLVED
        self._unconfirmed += 1
        if self._unconfirmed >= self._unconfirmed_limit and self._alive():
            return TUNNEL_UNCONFIRMED
        return None

    def _alive(self):
        with self._lock:
            process = self.process
        return process is not None and process.poll() is None

    @staticmethod
    def _drain(process):
        """Consume cloudflared's log so a full pipe never blocks the child."""

        stream = process.stdout
        if stream is None:
            return
        try:
            for _ in stream:
                pass
        except (OSError, ValueError):
            return

    def _discard(self):
        # The handles are taken under the lock and waited on outside it, so
        # a slow terminate can never delay the polling loop's ``ensure``.
        with self._lock:
            process, self.process = self.process, None
            reader, self._reader = self._reader, None
            self.url = None
            self.verification = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except (OSError, ValueError):
                    pass
        if reader is not None:
            reader.join(timeout=5)
        if process is not None and process.stdout is not None:
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass


_BINARY = getattr(os, "O_BINARY", 0)


class FileSecretStore:
    """Owner-only local fallback: mode 0600 on POSIX, a user-only ACL on Windows."""

    def __init__(self, path):
        self.path = Path(path)

    def store(self, value: str):
        value = validate_bot_token(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        make_private(self.path.parent, directory=True)
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(value)
                handle.write("\n")
        finally:
            # fdopen closes on normal and exceptional writes.  The explicit
            # permission repair also protects an existing file with old mode.
            make_private(self.path)

    def load(self) -> str:
        try:
            private = is_private(self.path)
        except FileNotFoundError:
            raise RuntimeError("Telegram token is not configured") from None
        except OSError:
            if not self.path.exists():
                raise RuntimeError("Telegram token is not configured") from None
            raise RuntimeError("Telegram token fallback file cannot be read") from None
        if not private:
            raise RuntimeError("Telegram token fallback file must have mode 0600 (owner-only access)")
        try:
            value = self.path.read_text(encoding="utf-8").rstrip("\n")
        except OSError:
            raise RuntimeError("Telegram token fallback file cannot be read") from None
        return validate_bot_token(value)


class KeychainSecretStore:
    """macOS Keychain store using ``security`` without placing the token in argv."""

    def __init__(self, command=None):
        self.command = command or shutil.which("security")
        if not self.command:
            raise RuntimeError("macOS Keychain command is unavailable")

    def store(self, value: str):
        value = validate_bot_token(value)
        try:
            result = subprocess.run(
                [
                    self.command,
                    "add-generic-password",
                    "-U",
                    "-a",
                    _KEYCHAIN_ACCOUNT,
                    "-s",
                    _KEYCHAIN_SERVICE,
                    "-w",
                ],
                input=f"{value}\n",
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("macOS Keychain timed out while storing the Telegram token") from None
        if result.returncode != 0:
            raise RuntimeError("macOS Keychain could not store the Telegram token")

    def load(self) -> str:
        try:
            result = subprocess.run(
                [
                    self.command,
                    "find-generic-password",
                    "-a",
                    _KEYCHAIN_ACCOUNT,
                    "-s",
                    _KEYCHAIN_SERVICE,
                    "-w",
                ],
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("macOS Keychain timed out while loading the Telegram token") from None
        if result.returncode != 0:
            raise RuntimeError("Telegram token is not configured in macOS Keychain")
        return validate_bot_token(result.stdout.rstrip("\n"))


class DpapiSecretStore:
    """Windows: the token encrypted with DPAPI for the current user only.

    Only this Windows account on this computer can decrypt the file; the
    owner-only ACL on it is a second, best-effort layer.
    """

    _ENTROPY = b"aimaster-telegram-bot-token"

    def __init__(self, path=None):
        if not IS_WINDOWS:
            raise RuntimeError("Windows DPAPI is unavailable")
        self.path = Path(path) if path is not None else (
            _default_fallback_path().with_name("telegram-bot-token.dpapi")
        )

    def store(self, value: str):
        from studio import _windows_security

        value = validate_bot_token(value)
        try:
            sealed = _windows_security.protect(value.encode("utf-8"), self._ENTROPY)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(sealed)
        except OSError:
            raise RuntimeError("Windows DPAPI could not store the Telegram token") from None
        try:
            make_private(self.path)
        except OSError:
            pass

    def load(self) -> str:
        from studio import _windows_security

        try:
            sealed = self.path.read_bytes()
        except FileNotFoundError:
            raise RuntimeError("Telegram token is not configured") from None
        except OSError:
            raise RuntimeError("Telegram token file cannot be read") from None
        try:
            value = _windows_security.unprotect(sealed, self._ENTROPY).decode("utf-8")
        except (OSError, UnicodeError):
            raise RuntimeError("Windows DPAPI could not decrypt the Telegram token") from None
        return validate_bot_token(value)


def _platform_secret_store():
    """macOS Keychain, Windows DPAPI; Linux raises and the file store is used."""

    if IS_WINDOWS:
        return DpapiSecretStore()
    return KeychainSecretStore()


class LocalSecretStore:
    """Prefer the OS secret store, then the private file fallback if unavailable."""

    def __init__(self, fallback_path, *, keychain_factory=_platform_secret_store):
        self.fallback = FileSecretStore(fallback_path)
        try:
            self.keychain = keychain_factory()
        except RuntimeError:
            self.keychain = None

    def store(self, token: str):
        if self.keychain is not None:
            try:
                self.keychain.store(token)
                return
            except RuntimeError:
                pass
        self.fallback.store(token)

    def load(self) -> str:
        if self.keychain is not None:
            try:
                return self.keychain.load()
            except RuntimeError:
                pass
        return self.fallback.load()


class PairingCodeStore(FileSecretStore):
    """Mode-0600 one-time pairing code, separate from the bot token."""

    def store_new(self) -> str:
        code = secrets.token_urlsafe(18)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _BINARY, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(code + "\n")
        finally:
            make_private(self.path)
        return code


def _workspace_state(workspace):
    workspace_path, _, _, private_root = resolve_workspace_paths(workspace)
    return workspace_path, private_root, TelegramBotState(private_root / "telegram_bot.sqlite3")


def build_parser():
    parser = argparse.ArgumentParser(description="Set up or run Studio Telegram transport")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("setup")
    subcommands.add_parser("setup-ui")
    run = subcommands.add_parser("run")
    run.add_argument("--workspace", required=True, type=Path)
    return parser


def main(argv=None, *, token_prompt=getpass.getpass, runner=None):
    ensure_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        if args.command == "setup":
            LocalSecretStore(_default_fallback_path()).store(
                token_prompt("BotFather token (hidden): ")
            )
            pairing = PairingCodeStore(_default_fallback_path().with_name("telegram-pairing-code")).store_new()
            print(f"Telegram token saved locally. Send /start {pairing} to the bot to pair the owner.")
            return 0
        if args.command == "setup-ui":
            run_setup_ui()
            return 0
        workspace, _, state = _workspace_state(args.workspace)
        secret_store = LocalSecretStore(_default_fallback_path())
        owner_id = state.paired_owner()
        stored_value = secret_store.load()
        pairing_path = _default_fallback_path().with_name("telegram-pairing-code")
        pairing_code = pairing_path.read_text(encoding="utf-8").strip() if owner_id is None else None
        try:
            permanent_url = resolve_public_mini_app_url()
            mini_app_port = resolve_mini_app_port()
        except ValueError as error:
            # These settings name variables, never credentials, so the
            # reason can be shown in full.
            print(f"Mini App settings are invalid: {error}", file=sys.stderr)
            return 2
        if runner is None:
            from creator_studio_bot import main as runner
        from studio.agent_bridge import process_inbox_once
        from studio.mini_app import serve_mini_app
        from studio.server import serve

        studio = serve(workspace)
        mini_app = None
        tunnel = None
        published = None

        def publish(controller, paired_owner, public_url):
            api = TelegramBotApi(stored_value)
            api.set_chat_menu_button(public_url)
            controller.set_mini_app_url(public_url + "#mini-app")
            from studio.telegram_bot import navigation_markup
            api.send_message(
                paired_owner,
                controller.navigation_text(),
                navigation_markup(controller.store.list_projects(), mini_app_url=controller.mini_app_url),
            )

        def after_iteration(controller):
            nonlocal mini_app, tunnel, published
            process_inbox_once(controller.state)
            paired_owner = controller.state.paired_owner()
            if paired_owner is None:
                return
            if mini_app is None:
                mini_app = serve_mini_app(
                    studio.application, stored_value, paired_owner, port=mini_app_port
                )
                # The loopback Mini App address is the only handle the owner
                # has when the public tunnel is unavailable; it carries no
                # credential.
                print(
                    f"Mini App (локально, для проверки шлюза; дашборд открывается из Telegram): "
                    f"{mini_app.base_url}/#mini-app",
                    flush=True,
                )
            if permanent_url is not None:
                # The owner runs a permanent front (a named tunnel on his own
                # domain).  Nothing here starts or supervises it, so the
                # address is published once and never withdrawn.
                if published is None:
                    if probe_tunnel_url(permanent_url) != TUNNEL_READY:
                        print(
                            f"Постоянный адрес Mini App не ответил с этого компьютера: "
                            f"{permanent_url}. Публикую как есть — проверьте свой туннель "
                            f"и что он ведёт на {mini_app.base_url}.",
                            flush=True,
                        )
                    try:
                        publish(controller, paired_owner, permanent_url)
                        published = permanent_url
                    except (OSError, RuntimeError, TelegramApiError):
                        controller.set_mini_app_url(None)
                        published = None
                return
            if tunnel is None:
                tunnel = TunnelSupervisor(mini_app.base_url)
            try:
                public_url = tunnel.ensure()
            except (OSError, RuntimeError, ValueError):
                # Supervision is best effort: the bot keeps answering over
                # long polling even when no tunnel can be raised at all.
                public_url = None
            if public_url is None:
                # Nothing public is reachable: withdraw the URL so the bot
                # stops drawing a Mini App button onto a dead hostname.
                if published is not None:
                    published = None
                    controller.set_mini_app_url(None)
                    try:
                        TelegramBotApi(stored_value).reset_chat_menu_button()
                    except (OSError, RuntimeError, TelegramApiError):
                        # The inline buttons are already withdrawn; a menu
                        # left over is not worth stopping the transport for.
                        pass
                return
            if public_url == published:
                return
            try:
                publish(controller, paired_owner, public_url)
                published = public_url
                if not tunnel.verified:
                    # The button is already in Telegram; the owner only needs
                    # to know why it may not open right away.
                    print(tunnel_warning(tunnel.verification), flush=True)
            except (OSError, RuntimeError, TelegramApiError):
                # Publishing is retried on the next iteration; polling must
                # not stop and no half-published URL may stay advertised.
                controller.set_mini_app_url(None)
                published = None

        try:
            return runner(
                ["--workspace", str(workspace)],
                credential=stored_value,
                owner_id=owner_id,
                allow_pairing=owner_id is None,
                after_iteration=after_iteration,
                pairing_code=pairing_code,
            )
        finally:
            if tunnel is not None:
                tunnel.stop()
            if mini_app is not None:
                mini_app.close()
            studio.close()
    except (OSError, RuntimeError, TelegramBotError, ValueError) as error:
        # Credential-bearing exceptions are intentionally not interpolated.
        print("Telegram transport setup or launch failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

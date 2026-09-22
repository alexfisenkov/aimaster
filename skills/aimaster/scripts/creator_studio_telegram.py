#!/usr/bin/env python3
"""Local setup and launch entrypoint for the macOS Studio Telegram transport.

Importing this module and rendering ``--help`` are deliberately offline.  The
Bot API is only constructed by the existing polling entrypoint after ``run``
loads a locally stored credential.
"""

from __future__ import annotations

import argparse
import getpass
import html
import os
import re
import secrets
import shutil
import select
import socket
import ssl
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from creator_studio_bot import TelegramApiError, TelegramBotApi  # noqa: E402
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
_TUNNEL_PROBE_DELAY = 5.0
_TUNNEL_PROBE_ATTEMPTS = 12
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
    """Keep the fallback outside project state when setup has no workspace."""

    return Path.home() / "Library" / "Application Support" / "AI Мастерская" / "telegram-bot-token"


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

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
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
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
        0o600,
    )
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


def start_cloudflared(local_url: str, *, popen=subprocess.Popen, timeout=12, config_path=None):
    process = popen(
        cloudflared_command(local_url, config_path=config_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], 0.25)
        if not ready:
            if process.poll() is not None:
                break
            continue
        line = process.stdout.readline()
        if not line:
            break
        lines.append(line)
        match = _TUNNEL_URL.search(line)
        if match:
            # The caller must keep reading this pipe: cloudflared logs for as
            # long as it runs and blocks on a full pipe buffer if nobody does.
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


def probe_tunnel_url(url: str, *, timeout=8) -> str:
    """Ask the public tunnel URL for its root and classify the answer.

    ``ready`` means the Mini App answered through the tunnel.  ``unresolved``
    means the name is not in DNS yet — which is not proof of a dead tunnel:
    a fresh quick tunnel needs seconds to spread, and a resolver that
    answered NXDOMAIN once keeps repeating it from cache for minutes while
    Telegram's own resolver already sees the name.  Anything else
    (Cloudflare's 4xx/5xx tunnel pages, refused connections) is
    ``unreachable``: the name exists but nothing serves the dashboard.
    """

    outgoing = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(outgoing, timeout=timeout) as response:
            response.read(1024)
            status = getattr(response, "status", 200)
        return TUNNEL_READY if 200 <= status < 400 else TUNNEL_UNREACHABLE
    except urllib.error.HTTPError as error:
        error.close()
        return TUNNEL_UNREACHABLE
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", None)
        if isinstance(reason, socket.gaierror):
            return TUNNEL_UNRESOLVED
        if isinstance(reason, ssl.SSLCertVerificationError):
            return TUNNEL_UNVERIFIABLE
        return TUNNEL_UNREACHABLE
    except ssl.SSLCertVerificationError:
        return TUNNEL_UNVERIFIABLE
    except socket.gaierror:
        return TUNNEL_UNRESOLVED
    except Exception:
        # A probe failure is an ordinary "not ready yet", never a transport
        # error: the polling loop must survive it.
        return TUNNEL_UNREACHABLE


class TunnelSupervisor:
    """Keep one Cloudflare Quick Tunnel alive in front of the Mini App.

    The transport used to start cloudflared once and forget it.  When the
    child died the bot kept offering buttons pointing at a hostname that no
    longer resolved.  This object is asked on every polling iteration whether
    a verified public URL exists: it restarts the dead child, re-probes the
    new name and reports ``None`` for as long as there is nothing to
    advertise.
    """

    def __init__(
        self,
        local_url,
        *,
        starter=start_cloudflared,
        probe=probe_tunnel_url,
        clock=time.monotonic,
        sleep=time.sleep,
        probe_delay=_TUNNEL_PROBE_DELAY,
        probe_attempts=_TUNNEL_PROBE_ATTEMPTS,
        probe_interval=_TUNNEL_PROBE_INTERVAL,
        backoff=_TUNNEL_BACKOFF_SECONDS,
        unconfirmed_limit=_TUNNEL_UNCONFIRMED_LIMIT,
    ):
        self.local_url = local_url
        self.process = None
        self.url = None
        # ``ready`` when the dashboard answered through the tunnel; the other
        # values say why the published URL could not be confirmed here.
        self.verification = None
        self._starter = starter
        self._probe = probe
        self._clock = clock
        self._sleep = sleep
        self._probe_delay = probe_delay
        self._probe_attempts = probe_attempts
        self._probe_interval = probe_interval
        self._backoff = tuple(backoff)
        self._unconfirmed_limit = unconfirmed_limit
        self._reader = None
        self._failures = 0
        self._unconfirmed = 0
        self._next_attempt = None

    @property
    def verified(self):
        """True only when the dashboard really answered through the tunnel."""

        return self.verification == TUNNEL_READY

    def ensure(self):
        """Return a verified public URL, restarting the tunnel if it died."""

        if self.process is not None and self.process.poll() is not None:
            self._discard()
        if self.process is not None:
            return self.url
        if self._next_attempt is not None and self._clock() < self._next_attempt:
            return None
        if self._start() is None:
            self._failures += 1
            index = min(self._failures, len(self._backoff)) - 1
            self._next_attempt = self._clock() + self._backoff[index]
            return None
        self._failures = 0
        self._next_attempt = None
        return self.url

    def stop(self):
        """Terminate the tunnel and join its reader on transport shutdown."""

        self._discard()

    def _start(self):
        self.verification = None
        try:
            process, url = self._starter(self.local_url)
        except (OSError, RuntimeError, ValueError):
            return None
        self.process = process
        self.url = url
        self._reader = threading.Thread(target=self._drain, args=(process,), daemon=True)
        self._reader.start()
        if not self._verify(url):
            self._discard()
            return None
        return url

    def _verify(self, url):
        """Wait for the new name to answer; report whether it may be used.

        The first probe is deliberately late: asking before the name has
        spread earns an NXDOMAIN that the local resolver caches for minutes,
        which would make a healthy tunnel look dead.  When every attempt
        failed only on name resolution, the tunnel is still handed over --
        Telegram resolves the name with its own resolver, and refusing would
        leave the owner with no button at all.  For the same reason a tunnel
        that keeps failing its check is published after a few restarts: an
        unconfirmed button beats no button.
        """

        self._sleep(self._probe_delay)
        verdicts = []
        for attempt in range(self._probe_attempts):
            if self.process is None or self.process.poll() is not None:
                return False
            verdict = self._probe(url)
            if verdict == TUNNEL_READY:
                self.verification = TUNNEL_READY
                self._unconfirmed = 0
                return True
            if verdict == TUNNEL_UNVERIFIABLE:
                # Repeating the probe cannot change a missing certificate
                # store, and restarting the tunnel would punish a healthy one.
                self.verification = TUNNEL_UNVERIFIABLE
                return True
            verdicts.append(verdict)
            if attempt + 1 < self._probe_attempts:
                self._sleep(self._probe_interval)
        if verdicts and all(item == TUNNEL_UNRESOLVED for item in verdicts):
            self.verification = TUNNEL_UNRESOLVED
            return True
        self._unconfirmed += 1
        if self._unconfirmed >= self._unconfirmed_limit and self._alive():
            self.verification = TUNNEL_UNCONFIRMED
            return True
        return False

    def _alive(self):
        return self.process is not None and self.process.poll() is None

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


class FileSecretStore:
    """Mode-0600 local fallback for test environments without macOS Keychain."""

    def __init__(self, path):
        self.path = Path(path)

    def store(self, value: str):
        value = validate_bot_token(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(value)
                handle.write("\n")
        finally:
            # fdopen closes on normal and exceptional writes.  The explicit
            # permission repair also protects an existing file with old mode.
            os.chmod(self.path, 0o600)

    def load(self) -> str:
        try:
            mode = stat.S_IMODE(self.path.stat().st_mode)
        except FileNotFoundError:
            raise RuntimeError("Telegram token is not configured") from None
        if mode != 0o600:
            raise RuntimeError("Telegram token fallback file must have mode 0600")
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


class LocalSecretStore:
    """Prefer Keychain, then use the private workspace fallback if unavailable."""

    def __init__(self, fallback_path, *, keychain_factory=KeychainSecretStore):
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
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(code + "\n")
        finally:
            os.chmod(self.path, 0o600)
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

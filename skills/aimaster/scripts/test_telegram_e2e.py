#!/usr/bin/env python3
"""Local end-to-end run of the Telegram transport against a mock Bot API.

The transport is started exactly as an owner starts it
(``creator_studio_telegram.py run --workspace …``) as a separate process, so
the assertions below observe the real long-polling loop, the real Bot API
client and the real Mini App gateway -- not a controller called directly.

Nothing leaves this machine.  The Bot API origin is overridden to an IPv4
loopback mock (``AIMASTER_TELEGRAM_API_ORIGIN``), the token is synthetic, and
the process runs with ``HOME`` pointed at a temporary directory and with an
empty ``PATH`` so neither the macOS Keychain nor ``cloudflared`` nor Codex can
be reached.  No paid action and no provider call is exercised.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import contextlib
import io
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from creator_studio_bot import (  # noqa: E402
    API_ORIGIN_VARIABLE,
    TelegramApiError,
    build_ssl_context,
    resolve_api_origin,
)
from studio.platform_compat import user_data_dir  # noqa: E402
from studio.telegram_bot import TelegramBotState  # noqa: E402
from studio.workspace import resolve_workspace_paths  # noqa: E402


OWNER_ID = 501
SYNTHETIC_TOKEN = "123456789:" + "A" * 36
PROJECT_ID = "e2e-demo"
PROJECT_TITLE = "Демо E2E"
DEADLINE_SECONDS = 25.0
ARTIFACT_VARIABLE = "AIMASTER_E2E_ARTIFACT_DIR"


class _MockBotApiHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler contract
        prefix = f"/bot{self.server.token}/"
        if not self.path.startswith(prefix):
            self._reply(404, {"ok": False, "description": "unknown bot"})
            return
        method = self.path[len(prefix):]
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            self._reply(400, {"ok": False, "description": "bad payload"})
            return
        self.server.record(method, payload)
        if method == "getUpdates":
            self._reply(200, {"ok": True, "result": self.server.take_updates(payload)})
            return
        if method in {"sendMessage", "editMessageText"}:
            self._reply(200, {"ok": True, "result": {"message_id": self.server.next_message_id()}})
            return
        if method in {"answerCallbackQuery", "setChatMenuButton"}:
            self._reply(200, {"ok": True, "result": True})
            return
        self._reply(200, {"ok": False, "description": f"unsupported method {method}"})

    def _reply(self, status, document):
        body = json.dumps(document, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


class MockBotApi(ThreadingHTTPServer):
    """Loopback stand-in for api.telegram.org that records every call."""

    daemon_threads = True

    def __init__(self, token, log_path):
        super().__init__(("127.0.0.1", 0), _MockBotApiHandler)
        self.token = token
        self.calls = []
        self._pending = []
        self._message_id = 1000
        self._lock = threading.Lock()
        self._log = open(log_path, "a", encoding="utf-8")
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server_address[1]}"

    def record(self, method, payload):
        entry = {"at": time.time(), "direction": "in", "method": method, "payload": payload}
        with self._lock:
            self.calls.append(entry)
            self._log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._log.flush()

    def note(self, event, detail):
        entry = {"at": time.time(), "direction": "note", "event": event, "detail": detail}
        with self._lock:
            self._log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._log.flush()

    def queue_updates(self, updates):
        with self._lock:
            self._pending.extend(updates)

    def next_message_id(self):
        with self._lock:
            self._message_id += 1
            return self._message_id

    def take_updates(self, payload):
        """Hand out one update at a time, honouring the polling cursor."""

        offset = payload.get("offset")
        offset = offset if isinstance(offset, int) and not isinstance(offset, bool) else 0
        with self._lock:
            self._pending = [item for item in self._pending if item["update_id"] >= offset]
            batch = self._pending[:1]
        if not batch:
            # A real Bot API long-polls; sleeping keeps the loop honest
            # without turning an idle test into a busy wait.
            time.sleep(0.1)
            return []
        return batch

    def sent_texts(self):
        with self._lock:
            return [
                entry["payload"].get("text", "")
                for entry in self.calls
                if entry["method"] == "sendMessage"
            ]

    def methods(self):
        with self._lock:
            return [entry["method"] for entry in self.calls]

    def close(self):
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=5)
        with self._lock:
            self._log.close()


def message_update(update_id, text):
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "from": {"id": OWNER_ID, "is_bot": False, "first_name": "Owner"},
            "chat": {"id": OWNER_ID, "type": "private"},
            "date": int(time.time()),
            "text": text,
        },
    }


def callback_update(update_id, data):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"query-{update_id}",
            "from": {"id": OWNER_ID, "is_bot": False, "first_name": "Owner"},
            "message": {
                "message_id": update_id,
                "chat": {"id": OWNER_ID, "type": "private"},
                "date": int(time.time()),
            },
            "data": data,
        },
    }


class TlsTrustTests(unittest.TestCase):
    """A python.org Python has an empty trust store; the client must still verify."""

    def _empty_store(self):
        import ssl
        from unittest import mock

        return mock.patch.object(
            ssl.SSLContext, "cert_store_stats", return_value={"x509_ca": 0, "x509": 0, "crl": 0}
        )

    def test_certifi_bundle_is_loaded_when_the_default_store_is_empty(self):
        import ssl
        from unittest import mock

        with self._empty_store(), mock.patch.object(
            ssl.SSLContext, "load_verify_locations"
        ) as load:
            context = build_ssl_context(certifi_path="/bundle/cacert.pem", system_roots=lambda: "")
        load.assert_called_once_with(cafile="/bundle/cacert.pem")
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_system_roots_are_the_fallback_without_certifi(self):
        import ssl
        from unittest import mock

        with self._empty_store(), mock.patch.object(
            ssl.SSLContext, "load_verify_locations"
        ) as load:
            build_ssl_context(certifi_path="", system_roots=lambda: "-----BEGIN CERTIFICATE-----\n")
        load.assert_called_once_with(cadata="-----BEGIN CERTIFICATE-----\n")

    def test_verification_is_never_disabled(self):
        import ssl

        context = build_ssl_context(certifi_path="", system_roots=lambda: "")
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)


class TransportResilienceTests(unittest.TestCase):
    """One failed Bot API call must not stop the transport or loop forever."""

    def _controller(self, replies):
        class Reply:
            def __init__(self):
                self.chat_id, self.text, self.reply_markup = 501, "section", {"k": 1}
                self.update_id, self.callback_query_id = 7, None

        class Controller:
            def __init__(self):
                self.delivered = []
                self._pending = [Reply() for _ in range(replies)]

            def pending_replies(self):
                return list(self._pending)

            def mark_delivered(self, update_id):
                self.delivered.append(update_id)
                self._pending = []

            def next_offset(self):
                return 0

            def handle_update(self, update):
                return []

        return Controller()

    def test_rejected_reply_is_replaced_and_marked_delivered(self):
        from creator_studio_bot import _deliver_pending

        sent = []

        class Api:
            def send_message(self, chat_id, text, reply_markup=None):
                sent.append(text)
                if text == "section":
                    raise TelegramApiError("Telegram rejected sendMessage: HTTP 400: too long", status=400, retryable=False)

        controller = self._controller(1)
        with contextlib.redirect_stderr(io.StringIO()):
            _deliver_pending(controller, Api())
        self.assertEqual(controller.delivered, [7])
        self.assertIn("отклонил сообщение (400)", sent[-1])

    def test_transient_failure_propagates_and_main_keeps_polling(self):
        from creator_studio_bot import main as bot_main

        calls = []

        class Api:
            def __init__(self, token):
                pass

            def get_updates(self, offset, timeout):
                calls.append("getUpdates")
                if len(calls) == 1:
                    raise TelegramApiError("Telegram request failed (getUpdates: TimeoutError)")
                return []

        slept = []
        with tempfile.TemporaryDirectory() as workspace, contextlib.redirect_stderr(io.StringIO()) as err:
            code = bot_main(
                ["--workspace", workspace], api_factory=Api, iterations=3,
                credential="123456:" + "a" * 32, owner_id=501, sleep=slept.append,
            )
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["getUpdates"] * 3)
        self.assertEqual(slept, [2.0])
        self.assertIn("TimeoutError", err.getvalue())
        self.assertNotIn("aaaa", err.getvalue())

    def test_http_error_carries_status_and_description_but_no_token(self):
        import urllib.error
        from creator_studio_bot import TelegramBotApi

        body = io.BytesIO(b'{"ok":false,"description":"Bad Request: message is too long"}')
        error = urllib.error.HTTPError("https://api.telegram.org/botSECRET/sendMessage", 400, "Bad Request", {}, body)

        def opener(request_, timeout):
            raise error

        api = TelegramBotApi("123456:" + "a" * 32, opener=opener)
        with self.assertRaises(TelegramApiError) as caught:
            api.send_message(501, "x")
        self.assertEqual(caught.exception.status, 400)
        self.assertFalse(caught.exception.retryable)
        self.assertIn("message is too long", str(caught.exception))
        self.assertNotIn("SECRET", str(caught.exception))


class ApiOriginOverrideTests(unittest.TestCase):
    """The override exists for local tests only and cannot leave this machine."""

    def test_default_origin_is_unchanged(self):
        self.assertEqual(resolve_api_origin({}), "https://api.telegram.org")
        self.assertEqual(
            resolve_api_origin({API_ORIGIN_VARIABLE: ""}), "https://api.telegram.org"
        )

    def test_loopback_override_is_accepted(self):
        self.assertEqual(
            resolve_api_origin({API_ORIGIN_VARIABLE: "http://127.0.0.1:8765"}),
            "http://127.0.0.1:8765",
        )

    def test_non_loopback_override_is_refused(self):
        for value in (
            "https://api.evil.example",
            "http://127.0.0.1:8765/path",
            "http://localhost:8765",
            "http://127.0.0.2:8765",
            "http://127.0.0.1",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TelegramApiError, "loopback"):
                    resolve_api_origin({API_ORIGIN_VARIABLE: value})


class TelegramTransportEndToEndTests(unittest.TestCase):
    """One live transport process drives the whole Telegram callback path."""

    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory(prefix="aimaster-e2e-")
        root = Path(cls._temporary.name)
        artifacts = os.environ.get(ARTIFACT_VARIABLE)
        cls.artifacts = Path(artifacts) if artifacts else root / "artifacts"
        cls.artifacts.mkdir(parents=True, exist_ok=True)
        cls.workspace = root / "workspace"
        cls.workspace.mkdir()
        cls.home = root / "home"
        cls.empty_path = root / "empty-bin"
        cls.empty_path.mkdir()

        cls._create_project()
        cls._store_synthetic_token()
        cls._pair_owner()

        cls.raw_log = cls.artifacts / "mock-bot-api.jsonl"
        cls.transport_log = cls.artifacts / "transport-stdout.log"
        cls.api = MockBotApi(SYNTHETIC_TOKEN, cls.raw_log)
        cls.api.note("workspace", str(cls.workspace))
        cls.output = []
        cls.mini_app_url = None
        cls.process = None
        try:
            cls._start_transport()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        process = getattr(cls, "process", None)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        reader = getattr(cls, "_reader", None)
        if reader is not None:
            reader.join(timeout=5)
        if process is not None and process.stdout is not None:
            process.stdout.close()
        api = getattr(cls, "api", None)
        if api is not None:
            api.close()
        temporary = getattr(cls, "_temporary", None)
        if temporary is not None:
            temporary.cleanup()

    # -- fixture construction ------------------------------------------------

    @classmethod
    def _create_project(cls):
        completed = subprocess.run(
            [
                sys.executable,
                str(_SCRIPTS / "creator_studio.py"),
                "project",
                "create",
                str(cls.workspace),
                PROJECT_ID,
                "--title",
                PROJECT_TITLE,
                "--type",
                "photo",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=60,
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"synthetic project creation failed: {completed.stdout}{completed.stderr}"
            )

    @classmethod
    def _store_synthetic_token(cls):
        from creator_studio_telegram import FileSecretStore

        # Wherever the transport itself will look under this synthetic home:
        # Application Support on macOS, %LOCALAPPDATA% on Windows, XDG on Linux.
        token_path = user_data_dir(
            home=cls.home, environ=cls._transport_environment()
        ) / "telegram-bot-token"
        FileSecretStore(token_path).store(SYNTHETIC_TOKEN)
        cls.token_path = token_path

    @classmethod
    def _pair_owner(cls):
        _, _, _, private_root = resolve_workspace_paths(cls.workspace)
        TelegramBotState(private_root / "telegram_bot.sqlite3").pair_owner(OWNER_ID)

    @classmethod
    def _transport_environment(cls):
        environment = {
            "HOME": str(cls.home),
            "PATH": str(cls.empty_path),
            "LANG": "en_US.UTF-8",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(_SKILL_ROOT),
        }
        api = getattr(cls, "api", None)
        if api is not None:
            environment[API_ORIGIN_VARIABLE] = api.origin
        if os.name == "nt":
            # Windows finds the profile through USERPROFILE, not HOME, and
            # Python itself needs the system root to start.
            environment.update(
                USERPROFILE=str(cls.home),
                LOCALAPPDATA=str(cls.home / "AppData" / "Local"),
                APPDATA=str(cls.home / "AppData" / "Roaming"),
            )
            for name in ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP"):
                if name in os.environ:
                    environment[name] = os.environ[name]
        return environment

    @classmethod
    def _start_transport(cls):
        environment = cls._transport_environment()
        cls.api.note("api_origin", cls.api.origin)
        cls.process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(_SCRIPTS / "creator_studio_telegram.py"),
                "run",
                "--workspace",
                str(cls.workspace),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )

        def pump():
            handle = cls.transport_log.open("a", encoding="utf-8")
            try:
                for line in cls.process.stdout:
                    cls.output.append(line.rstrip("\n"))
                    handle.write(line)
                    handle.flush()
            finally:
                handle.close()

        cls._reader = threading.Thread(target=pump, daemon=True)
        cls._reader.start()

    # -- helpers -------------------------------------------------------------

    @classmethod
    def _wait(cls, predicate, description):
        deadline = time.monotonic() + DEADLINE_SECONDS
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                raise AssertionError(
                    f"transport exited with {cls.process.returncode} while waiting for "
                    f"{description}\n" + "\n".join(cls.output)
                )
            value = predicate()
            if value:
                cls.api.note("observed", description)
                return value
            time.sleep(0.05)
        raise AssertionError(
            f"timed out waiting for {description}\n"
            + "\n".join(cls.output)
            + "\nsent: "
            + json.dumps(cls.api.sent_texts(), ensure_ascii=False)
        )

    @classmethod
    def _wait_for_text(cls, fragment, description):
        return cls._wait(
            lambda: [text for text in cls.api.sent_texts() if fragment in text],
            description,
        )

    # -- the ordered scenario ------------------------------------------------

    def test_01_transport_starts_and_polls_the_bot_api(self):
        self._wait(lambda: "getUpdates" in self.api.methods(), "the first getUpdates call")
        self.assertIsNone(self.process.poll())

    def test_02_project_callback_selects_the_project(self):
        self.api.queue_updates([callback_update(1000, f"project:{PROJECT_ID}")])
        matched = self._wait_for_text(PROJECT_TITLE, "the selected project card")

        self.assertIn("выбран", matched[0])
        self._wait(
            lambda: "answerCallbackQuery" in self.api.methods(),
            "the callback acknowledgement",
        )
        _, _, _, private_root = resolve_workspace_paths(self.workspace)
        selection = TelegramBotState(private_root / "telegram_bot.sqlite3").selection(OWNER_ID)
        self.assertEqual(selection["project_id"], PROJECT_ID)

    def test_03_malformed_and_legacy_callbacks_keep_polling_alive(self):
        before = len(self.api.sent_texts())
        self.api.queue_updates(
            [
                callback_update(1001, f"project:{PROJECT_ID}:unknown"),
                callback_update(1002, "garbage"),
                callback_update(1003, "project:"),
                callback_update(1004, "project:no-such-project"),
                callback_update(1005, "menu:projects"),
            ]
        )
        self._wait(
            lambda: len([text for text in self.api.sent_texts()[before:] if "устарела" in text]) >= 4,
            "four stale-button refusals",
        )
        self._wait_for_text("Проекты:", "the project list after the refusals")
        self.assertIsNone(self.process.poll())

    def test_04_next_update_after_the_errors_is_processed(self):
        self.api.queue_updates([message_update(1006, "/help")])
        self._wait_for_text("Команды:", "the /help reply after the malformed callbacks")
        self.api.queue_updates([callback_update(1007, f"project:{PROJECT_ID}:scenario")])
        # The project index line also contains the word "Сценарий", so the
        # section card is matched by its own full heading, not by that word.
        self._wait_for_text(
            f"«{PROJECT_TITLE}» · Сценарий", "the project scenario section card"
        )
        self.assertIsNone(self.process.poll())
        self.assertGreaterEqual(self.api.methods().count("answerCallbackQuery"), 7)

    def test_05_mini_app_gateway_is_still_answering(self):
        prefix = "Mini App (локально"
        line = self._wait(
            lambda: next((item for item in self.output if item.startswith(prefix)), None),
            "the local Mini App address",
        )
        base_url = line.rsplit(": ", 1)[1].strip().removesuffix("/#mini-app")
        self.assertTrue(base_url.startswith("http://127.0.0.1:"), base_url)
        type(self).mini_app_url = base_url

        with urllib.request.urlopen(base_url + "/", timeout=10) as document:
            status = document.status
            document.read()
        self.assertEqual(status, 200)
        self.api.note("mini_app_root", {"url": base_url + "/", "status": status})

        with self.assertRaises(urllib.error.HTTPError) as refused:
            with urllib.request.urlopen(base_url + "/api/projects", timeout=10):
                pass
        self.assertEqual(refused.exception.code, 403)
        refused.exception.close()
        self.api.note("mini_app_api", {"url": base_url + "/api/projects", "status": 403})
        self.assertIsNone(self.process.poll())

    def test_06_transport_never_reached_a_non_loopback_host(self):
        self.assertTrue(self.token_path.exists())
        joined = "\n".join(self.output)
        self.assertNotIn(SYNTHETIC_TOKEN, joined)
        self.assertNotIn("api.telegram.org", joined)
        self.assertIsNone(self.process.poll())


if __name__ == "__main__":
    unittest.main()

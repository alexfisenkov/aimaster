#!/usr/bin/env python3
"""Offline Telegram Mini App authentication and gateway tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from studio.http_app import Response  # noqa: E402
from studio.mini_app import MiniAppGateway, serve_mini_app, validate_init_data  # noqa: E402


class _StubInner:
    """Minimal stand-in for `StudioApplication` as the gateway uses it."""

    origin = "http://127.0.0.1:8765"
    authority = "127.0.0.1:8765"
    csrf_token = "csrf"

    def __init__(self, body=b"{}", content_type="application/json"):
        self.body = body
        self.content_type = content_type
        self.calls = []

    def handle(self, method, path, headers, body):
        self.calls.append((method, path, headers, body))
        return Response(200, {"Content-Type": self.content_type}, self.body)


def init_data(token: str, user_id: int, auth_date: int) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "AA-test",
        "user": json.dumps({"id": user_id, "first_name": "Alex"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(values)


class MiniAppAuthTests(unittest.TestCase):
    def test_valid_init_data_returns_owner(self):
        token = "123456:" + "a" * 32
        raw = init_data(token, 501, int(time.time()))
        self.assertEqual(validate_init_data(raw, token, 501)["id"], 501)

    def test_tampered_or_stale_data_is_rejected(self):
        token = "123456:" + "a" * 32
        raw = init_data(token, 501, int(time.time()) - 90000)
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_init_data(raw, token, 501)
        with self.assertRaisesRegex(ValueError, "signature"):
            validate_init_data(raw.replace("501", "502"), token, 501)


class MiniAppGatewayTests(unittest.TestCase):
    def test_api_requires_valid_telegram_authorization(self):
        token = "123456:" + "a" * 32

        class Inner:
            origin = "http://127.0.0.1:8765"
            authority = "127.0.0.1:8765"
            csrf_token = "csrf"

            def __init__(self):
                self.calls = []

            def handle(self, method, path, headers, body):
                self.calls.append((method, path, headers, body))
                return Response(200, {"Content-Type": "application/json"}, b"{}")

        inner = Inner()
        gateway = MiniAppGateway(inner, token, 501)
        denied = gateway.handle("GET", "/api/projects", [("Host", "public")], b"")
        self.assertEqual(denied.status, 403)
        authorized = gateway.handle(
            "GET",
            "/api/projects",
            [("Host", "public"), ("Authorization", "tma " + init_data(token, 501, int(time.time())))],
            b"",
        )
        self.assertEqual(authorized.status, 200)
        self.assertEqual(inner.calls[0][1], "/api/projects")

    def test_encoded_api_separator_is_still_authenticated(self):
        token = "123456:" + "a" * 32

        class Inner:
            origin = "http://127.0.0.1:8765"
            authority = "127.0.0.1:8765"
            csrf_token = "csrf"

            def handle(self, method, path, headers, body):
                return Response(200, {"Content-Type": "application/json"}, b"{}")

        gateway = MiniAppGateway(Inner(), token, 501)
        denied = gateway.handle("GET", "/api%2fprojects", [("Host", "public")], b"")
        self.assertEqual(denied.status, 403)

    def test_snapshot_asset_urls_receive_short_lived_signed_tickets(self):
        token = "123456:" + "a" * 32

        class Inner:
            origin = "http://127.0.0.1:8765"
            authority = "127.0.0.1:8765"
            csrf_token = "csrf"

            def handle(self, method, path, headers, body):
                return Response(
                    200,
                    {"Content-Type": "application/json"},
                    b'{"asset_url":"/assets/asset-1"}',
                )

        gateway = MiniAppGateway(Inner(), token, 501)
        response = gateway.handle(
            "GET",
            "/api/projects/demo/snapshot",
            [("Authorization", "tma " + init_data(token, 501, int(time.time())))],
            b"",
        )
        self.assertIn(b"?e=", response.body)
        self.assertIn(b"&t=", response.body)


class MiniAppDocumentTests(unittest.TestCase):
    """The page itself must stay reachable; only the API is authenticated."""

    def setUp(self):
        self.token = "123456:" + "a" * 32
        self.inner = _StubInner(b"<!doctype html>", "text/html; charset=utf-8")
        self.gateway = MiniAppGateway(self.inner, self.token, 501)

    def test_document_with_query_is_served_without_authorization(self):
        # `app.js` pushes `?project=<id>` into the address bar, so reloading
        # the Telegram WebView asks for exactly this URL. Answering it with
        # 403 leaves the owner with a raw error body instead of the page.
        response = self.gateway.handle("GET", "/?project=demo", [("Host", "public")], b"")
        self.assertEqual(response.status, 200)
        self.assertEqual(self.inner.calls[0][1], "/")

    def test_static_asset_with_cache_buster_is_served(self):
        response = self.gateway.handle("GET", "/static/app.js?v=2", [("Host", "public")], b"")
        self.assertEqual(response.status, 200)

    def test_query_does_not_open_the_api(self):
        for target in ("/api/projects?x=1", "/api/session?", "/api%2fprojects?x=1"):
            with self.subTest(target=target):
                denied = self.gateway.handle("GET", target, [("Host", "public")], b"")
                self.assertEqual(denied.status, 403)

    def test_non_ascii_asset_ticket_is_denied_not_crashed(self):
        # `secrets.compare_digest` raises TypeError on non-ASCII str; an
        # anonymous request must get 403, not a dropped connection.
        target = "/assets/x?e=9999999999&t=%D0%B6"
        denied = self.gateway.handle("GET", target, [("Host", "public")], b"")
        self.assertEqual(denied.status, 403)
        self.assertEqual(self.inner.calls, [])


class MiniAppFramingTests(unittest.TestCase):
    """Responses must carry exactly one, correct Content-Length.

    A 403 used to declare `Content-Length: 31` for a 30-byte body while the
    handler added the real length as well: two conflicting framing headers,
    which RFC 9112 §6.3 requires a recipient to reject -- and the Mini App
    is reached through a tunnel that is exactly such a recipient.
    """

    def test_forbidden_body_length_is_not_misdeclared(self):
        response = MiniAppGateway._forbidden()
        declared = response.headers.get("Content-Length")
        if declared is not None:
            self.assertEqual(int(declared), len(response.body))

    def test_live_gateway_sends_one_content_length(self):
        token = "123456:" + "a" * 32
        inner = _StubInner(b'{"asset_url":"/assets/asset-1"}')
        running = serve_mini_app(inner, token, 501)
        try:
            port = int(running.base_url.rsplit(":", 1)[1])
            for target, expected in (
                (b"/api/projects", b"403"),
                (b"/", b"200"),
            ):
                with self.subTest(target=target):
                    head, body = self._request(port, target)
                    lengths = [
                        line for line in head.splitlines()
                        if line.lower().startswith(b"content-length")
                    ]
                    self.assertIn(expected, head.splitlines()[0])
                    self.assertEqual(len(lengths), 1, head)
                    self.assertEqual(int(lengths[0].split(b":")[1]), len(body))
        finally:
            running.close()

    @staticmethod
    def _request(port, target):
        connection = socket.create_connection(("127.0.0.1", port), timeout=5)
        try:
            connection.sendall(
                b"GET " + target + b" HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            )
            raw = b""
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                raw += chunk
        finally:
            connection.close()
        head, _, body = raw.partition(b"\r\n\r\n")
        return head, body


# `studio/static/mini-app.js` is a classic browser script, so it is exercised
# the only way it can be without a browser: executed in a node `vm` context
# whose `location`/`document`/`Telegram`/`fetch` are stubs. The harness below
# is written to a temporary file and prints what the page would end up with --
# whether `fetch` was wrapped, which notice (if any) was shown, and the
# Authorization header attached to a same-origin call.
_BROWSER_HARNESS = """
import fs from "node:fs";
import vm from "node:vm";

const [, , scriptPath, rawConfig] = process.argv;
const config = JSON.parse(rawConfig);
const notices = [];
const calls = [];
const telegram =
  config.initData === null ? undefined : { WebApp: { initData: config.initData, ready() {} } };
const originalFetch = (input, init) => {
  calls.push({
    url: String(input),
    authorization: init && init.headers && init.headers.get ? init.headers.get("Authorization") : null,
  });
  return Promise.resolve({ ok: true });
};
const sandbox = {
  location: {
    hash: config.hash,
    href: "http://127.0.0.1:8799/" + config.hash,
    origin: "http://127.0.0.1:8799",
  },
  document: {
    createElement: () => ({ style: { cssText: "" }, textContent: "" }),
    body: { prepend: (node) => notices.push(node.textContent) },
  },
  Telegram: telegram,
  fetch: originalFetch,
  Headers,
  URL,
  URLSearchParams,
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(scriptPath, "utf8"), sandbox, { filename: scriptPath });
const patched = sandbox.fetch !== originalFetch;
if (patched) {
  sandbox.fetch("/api/projects");
  sandbox.fetch("https://telegram.org/js/telegram-web-app.js");
}
console.log(JSON.stringify({ patched, notices, calls }));
"""


class MiniAppBrowserAdapterTests(unittest.TestCase):
    """`mini-app.js`: which launch actually turns the adapter on."""

    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("node is not installed")
        cls._workdir = tempfile.TemporaryDirectory()
        cls.harness = Path(cls._workdir.name) / "mini-app-harness.mjs"
        cls.harness.write_text(_BROWSER_HARNESS, encoding="utf-8")
        cls.script = ROOT / "studio" / "static" / "mini-app.js"

    @classmethod
    def tearDownClass(cls):
        cls._workdir.cleanup()

    def run_adapter(self, hash_value, init_data):
        completed = subprocess.run(
            [
                "node",
                "--no-warnings",
                str(self.harness),
                str(self.script),
                json.dumps({"hash": hash_value, "initData": init_data}),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return json.loads(completed.stdout)

    def test_real_telegram_launch_attaches_init_data(self):
        # Telegram appends its own launch parameters to the fragment
        # (telegram.org's SDK does it in `urlAppendHashParams`), so a bare
        # `#mini-app` never reaches the page -- the adapter has to recognize
        # `#mini-app?tgWebAppData=...` or it stays off inside Telegram.
        result = self.run_adapter(
            "#mini-app?tgWebAppData=abc&tgWebAppVersion=7.0", "auth_date=1&hash=abc"
        )
        self.assertTrue(result["patched"])
        self.assertEqual(result["notices"], [])
        self.assertEqual(result["calls"][0]["authorization"], "tma auth_date=1&hash=abc")

    def test_launch_parameters_alone_attach_init_data(self):
        result = self.run_adapter("#tgWebAppData=abc", "auth_date=1&hash=abc")
        self.assertTrue(result["patched"])

    def test_launch_parameters_alone_switch_mode_on_even_without_init_data(self):
        # The fragment signal on its own: SDK present, initData empty. The
        # adapter must recognise a Telegram launch and show its notice, not
        # stay silent as if this were the ordinary local dashboard.
        result = self.run_adapter("#tgWebAppData=abc", "")
        self.assertFalse(result["patched"])
        self.assertIn("не получила данные Telegram", result["notices"][0])

    def test_restored_init_data_without_fragment_attaches_init_data(self):
        # After an in-WebView reload the SDK restores its launch parameters
        # from sessionStorage, and the fragment can be gone entirely.
        result = self.run_adapter("", "auth_date=1&hash=abc")
        self.assertTrue(result["patched"])

    def test_cross_origin_requests_never_carry_init_data(self):
        result = self.run_adapter("#mini-app?tgWebAppData=abc", "auth_date=1&hash=abc")
        self.assertIsNone(result["calls"][1]["authorization"])

    def test_missing_sdk_shows_a_notice_instead_of_a_blank_page(self):
        result = self.run_adapter("#mini-app", None)
        self.assertFalse(result["patched"])
        self.assertIn("Telegram SDK", result["notices"][0])

    def test_empty_init_data_shows_a_notice(self):
        result = self.run_adapter("#mini-app", "")
        self.assertFalse(result["patched"])
        self.assertIn("не получила данные Telegram", result["notices"][0])

    def test_plain_local_dashboard_is_left_alone(self):
        result = self.run_adapter("", "")
        self.assertFalse(result["patched"])
        self.assertEqual(result["notices"], [])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Offline Telegram Mini App authentication and gateway tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
import urllib.parse
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from studio.http_app import Response  # noqa: E402
from studio.mini_app import MiniAppGateway, validate_init_data  # noqa: E402


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
        raw = init_data("123456:abcdefghijklmnopqrstuvwxyz", 501, int(time.time()))
        self.assertEqual(validate_init_data(raw, "123456:abcdefghijklmnopqrstuvwxyz", 501)["id"], 501)

    def test_tampered_or_stale_data_is_rejected(self):
        token = "123456:abcdefghijklmnopqrstuvwxyz"
        raw = init_data(token, 501, int(time.time()) - 90000)
        with self.assertRaisesRegex(ValueError, "stale"):
            validate_init_data(raw, token, 501)
        with self.assertRaisesRegex(ValueError, "signature"):
            validate_init_data(raw.replace("501", "502"), token, 501)


class MiniAppGatewayTests(unittest.TestCase):
    def test_api_requires_valid_telegram_authorization(self):
        token = "123456:abcdefghijklmnopqrstuvwxyz"

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


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""/assets/<id> потоком: весь файл, Range, одна длина (и у HEAD — запись
ответа); через шлюз Mini App — тоже; AssetIndex.resolve (чтение целиком) при
отдаче не зовётся. HEAD на /assets/ дашборд, как и раньше, не принимает (405)."""

from __future__ import annotations

import http.client
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import isolate_hyperframes_dir, seed_workspace, tiny_mp4, video_state  # noqa: E402
from studio.assets import AssetIndex  # noqa: E402
from studio.http_app import Response  # noqa: E402
from studio.http_write import write_response  # noqa: E402
from studio.mini_app import serve_mini_app  # noqa: E402
from studio.server import serve  # noqa: E402

TOKEN = "123456:" + "a" * 32


def request(port, target, headers=None, *, method="GET"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, target, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.getheaders(), response.read()
    finally:
        connection.close()


def values(headers, name):
    return [value for key, value in headers if key.lower() == name.lower()]


class _Handler:
    def __init__(self, command="GET"):
        self.command, self.sent, self.wfile = command, [], io.BytesIO()

    def send_response(self, status):
        self.sent.append(("status", status))

    def send_header(self, name, value):
        self.sent.append((name, value))

    def end_headers(self):
        self.sent.append(("end", None))


class _Stream:
    length = 6

    def __init__(self):
        self.closed = False

    def chunks(self):
        yield b"abc"
        yield b"def"

    def close(self):
        self.closed = True


class WriteResponseTests(unittest.TestCase):
    def test_bytes_body_gets_one_true_length(self):
        handler = _Handler()
        write_response(handler, Response(200, {"Content-Type": "text/plain", "Content-Length": "999"}, b"hello"))
        self.assertEqual(values(handler.sent, "Content-Length"), ["5"])
        self.assertEqual(handler.wfile.getvalue(), b"hello")

    def test_stream_goes_in_chunks_and_is_closed(self):
        handler, stream = _Handler(), _Stream()
        write_response(handler, Response(206, {}, b"", stream=stream))
        self.assertEqual((handler.wfile.getvalue(), stream.closed), (b"abcdef", True))
        self.assertEqual(values(handler.sent, "Content-Length"), ["6"])

    def test_head_sends_no_body_and_still_closes_the_stream(self):
        handler, stream = _Handler("HEAD"), _Stream()
        write_response(handler, Response(200, {}, b"", stream=stream))
        self.assertEqual((handler.wfile.getvalue(), stream.closed), (b"", True))


class StreamedAssetTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        isolate_hyperframes_dir(self, base)
        self.data = tiny_mp4(bytes(range(256)) * 8_000)
        seed = seed_workspace(base, {"a.mp4": self.data}, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"])]))
        self.file, self.asset = seed.media / "a.mp4", seed.ids["a.mp4"]
        self.running = serve(seed.workspace)
        self.addCleanup(self.running.close)
        self.port = int(self.running.base_url.rsplit(":", 1)[1])

    def get(self, target, headers=None, **kwargs):
        return request(self.port, target, headers, **kwargs)

    def test_whole_file_is_sent_with_its_length(self):
        status, headers, body = self.get(f"/assets/{self.asset}")
        self.assertEqual((status, body), (200, self.data))
        self.assertEqual(values(headers, "Content-Length"), [str(len(self.data))])
        self.assertEqual(values(headers, "Accept-Ranges"), ["bytes"])
        self.assertEqual(values(headers, "Content-Type"), ["video/mp4"])

    def test_range_is_sent_as_206(self):
        status, headers, body = self.get(f"/assets/{self.asset}", {"Range": "bytes=10-19"})
        self.assertEqual((status, body), (206, self.data[10:20]))
        self.assertEqual(values(headers, "Content-Range"), [f"bytes 10-19/{len(self.data)}"])

    def test_suffix_range_gives_the_tail(self):
        status, _headers, body = self.get(f"/assets/{self.asset}", {"Range": "bytes=-5"})
        self.assertEqual((status, body), (206, self.data[-5:]))

    def test_range_past_the_end_is_416(self):
        status, headers, body = self.get(f"/assets/{self.asset}", {"Range": f"bytes={len(self.data)}-"})
        self.assertEqual((status, body), (416, b""))
        self.assertEqual(values(headers, "Content-Range"), [f"bytes */{len(self.data)}"])

    def test_asset_is_not_read_whole_by_resolve(self):
        with mock.patch.object(AssetIndex, "resolve", side_effect=AssertionError("resolve читает целиком")):
            status, _headers, body = self.get(f"/assets/{self.asset}", {"Range": "bytes=0-99"})
        self.assertEqual((status, body), (206, self.data[:100]))

    def test_changed_file_is_not_served(self):
        self.get(f"/assets/{self.asset}")
        changed = bytearray(self.data)
        changed[-1] ^= 0xFF
        self.file.write_bytes(bytes(changed))
        info = self.file.stat()
        os.utime(self.file, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
        status, _headers, body = self.get(f"/assets/{self.asset}")
        # Как и прежде у resolve: AssetValidationError — ValueError, handle отвечает 400.
        self.assertEqual(status, 400)
        self.assertNotEqual(body, bytes(changed))

    def test_mini_app_gateway_streams_with_a_ticket(self):
        mini = serve_mini_app(self.running.application, TOKEN, 501)
        self.addCleanup(mini.close)
        port = int(mini.base_url.rsplit(":", 1)[1])
        expires = int(time.time()) + 300
        ticket = mini._server.gateway._asset_ticket(self.asset, expires)
        target = f"/assets/{self.asset}?e={expires}&t={ticket}"
        status, headers, body = request(port, target)
        self.assertEqual((status, body), (200, self.data))
        self.assertEqual(values(headers, "Content-Length"), [str(len(self.data))])
        status, _headers, body = request(port, target, {"Range": "bytes=0-3"})
        self.assertEqual((status, body), (206, self.data[:4]))


if __name__ == "__main__":
    unittest.main()

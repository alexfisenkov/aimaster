#!/usr/bin/env python3
"""round 4/5, пункт 3: скачивание с общим сроком (install_montage_download)."""

from __future__ import annotations

import http.client
import io
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install_montage_download as dl  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Response(io.BytesIO):
    """Ответ сервера: `read1` отдаёт кусками по `piece` байт и двигает часы на `step` с."""

    def __init__(self, data: bytes, *, clock=None, step=0.0, piece=None):
        super().__init__(data)
        self.clock, self.step, self.piece, self.sizes = clock, step, piece, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read1(self, size=-1):
        self.sizes.append(size)
        if self.clock is not None:
            self.clock.now += self.step
        return super().read1(self.piece or size)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dest = Path(temp.name) / "AI Мастерская" / "архив.zip"
        self.dest.parent.mkdir()
        self.seen = []

    def opener(self, response):
        def open_(request, timeout=None, context=None):
            self.seen.append((request.full_url, timeout))
            return response
        return open_

    def test_whole_file_lands_on_disk_in_bounded_chunks(self):
        data = b"z" * (dl.CHUNK * 2 + 5)
        response = Response(data)
        reason = dl.download("https://example.test/a.zip", self.dest, deadline=660,
                             opener=self.opener(response))
        self.assertEqual(reason, "")
        self.assertEqual(self.dest.read_bytes(), data)
        self.assertTrue(all(size == dl.CHUNK for size in response.sizes))
        self.assertEqual(self.seen, [("https://example.test/a.zip", dl.READ_TIMEOUT)])

    def test_slow_drip_is_cut_at_the_deadline_not_at_the_socket_timeout(self):
        clock = Clock()
        response = Response(b"x" * 1000, clock=clock, step=25, piece=1)
        reason = dl.download("https://example.test/a.zip", self.dest, deadline=100,
                             opener=self.opener(response), clock=clock)
        self.assertEqual(reason, "не скачался за 100 с")
        self.assertEqual(len(response.sizes), 4)  # 0, 25, 50, 75 с — на 100 с остановка
        self.assertEqual(self.seen[0][1], dl.READ_TIMEOUT)

    def test_short_deadline_also_caps_the_socket_timeout(self):
        dl.download("https://example.test/a.zip", self.dest, deadline=20,
                    opener=self.opener(Response(b"ok")))
        self.assertEqual(self.seen[0][1], 20)

    def test_network_failures_are_reasons_not_exceptions(self):
        failures = (urllib.error.URLError("нет сети"), http.client.IncompleteRead(b""),
                    TimeoutError("timed out"), ConnectionResetError(54, "reset"))
        for error in failures:
            with self.subTest(error=type(error).__name__):
                def open_(request, timeout=None, context=None, error=error):
                    raise error
                reason = dl.download("https://example.test/a.zip", self.dest, deadline=60, opener=open_)
                self.assertTrue(reason.startswith("не скачался:"), reason)


if __name__ == "__main__":
    unittest.main()

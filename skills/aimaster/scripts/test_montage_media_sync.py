#!/usr/bin/env python3
"""Медиа в current/assets: жёсткая ссылка, иначе копия; ссылки композиции не выходят наружу."""

from __future__ import annotations

import errno
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage import MontageError, media_sync  # noqa: E402


class SyncTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.source = self.base / "media" / "клип сцены 1.MP4"
        self.source.parent.mkdir()
        self.source.write_bytes(b"video-bytes")
        self.assets = self.base / "montage" / "current" / "assets"

    def test_hard_link_when_possible_then_exists(self):
        synced = media_sync.sync_media([("asset-1", self.source)], self.assets)
        target = self.assets / "asset-1.mp4"
        self.assertEqual(synced["asset-1"]["src"], "assets/asset-1.mp4")
        self.assertIn(synced["asset-1"]["method"], ("link", "copy"))
        if synced["asset-1"]["method"] == "link":
            self.assertTrue(os.path.samefile(self.source, target))
        again = media_sync.sync_media([("asset-1", self.source)], self.assets)
        self.assertEqual(again["asset-1"]["method"], "exists")

    def test_copy_when_link_is_impossible(self):
        with mock.patch.object(media_sync.os, "link", side_effect=OSError(errno.EXDEV, "cross-device")):
            method = media_sync.link_or_copy(self.source, self.assets / "asset-1.mp4")
        self.assertEqual(method, "copy")
        self.assertEqual((self.assets / "asset-1.mp4").read_bytes(), b"video-bytes")
        self.assertFalse(os.path.samefile(self.source, self.assets / "asset-1.mp4"))
        self.assertEqual(list(self.assets.glob(".*.part")), [])

    def test_other_file_with_same_name_is_refused(self):
        self.assets.mkdir(parents=True)
        (self.assets / "asset-1.mp4").write_bytes(b"something else entirely")
        with self.assertRaises(MontageError):
            media_sync.link_or_copy(self.source, self.assets / "asset-1.mp4")


class ReferenceTests(unittest.TestCase):
    HTML = """<html><head>
      <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter">
      <script src="//cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
      <style>@import "https://x.example/a.css"; .a { background: url(file:///etc/x.png); }
             .b { background: url('assets/ok.png'); }</style></head>
      <body><video src="assets/a.mp4"></video><audio src="../media/v.wav"></audio>
      <img src="/abs/x.png"><img src="data:image/png;base64,AA"><a href="#top">.</a>
      <div style="background:url(https://y.example/b.png)"></div></body></html>"""

    def test_external_references(self):
        self.assertEqual(media_sync.external_references(self.HTML), [
            "https://fonts.googleapis.com/css2?family=Inter",
            "//cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js",
            "https://x.example/a.css", "file:///etc/x.png", "https://y.example/b.png"])

    def test_missing_and_escaping_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            current = Path(temp)
            (current / "assets").mkdir()
            (current / "assets" / "a.mp4").write_bytes(b"x")
            (current / "assets" / "ok.png").write_bytes(b"x")
            self.assertEqual(media_sync.missing_sources(self.HTML, current),
                             ["../media/v.wav", "/abs/x.png"])
            problems = media_sync.check_composition(self.HTML, current)
        self.assertIn("внешняя ссылка: https://x.example/a.css", problems)
        self.assertIn("файла нет в папке монтажа: ../media/v.wav", problems)


if __name__ == "__main__":
    unittest.main()

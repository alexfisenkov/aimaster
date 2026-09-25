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

    def test_stat_failure_on_existing_target_is_a_montage_error(self):
        # Fix round 1/5: гонка/права при os.path.samefile или .stat() на уже
        # существующем target не должны утечь голым OSError.
        self.assets.mkdir(parents=True)
        (self.assets / "asset-1.mp4").write_bytes(b"video-bytes")
        with mock.patch.object(media_sync.os.path, "samefile",
                               side_effect=OSError(errno.EACCES, "denied")):
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
      <img src="assets/missing.png">
      <div style="background:url(https://y.example/b.png)"></div></body></html>"""

    def test_external_references(self):
        self.assertEqual(media_sync.external_references(self.HTML), [
            "https://fonts.googleapis.com/css2?family=Inter",
            "//cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js",
            "https://x.example/a.css", "file:///etc/x.png", "https://y.example/b.png"])

    def test_missing_and_escaping_sources(self):
        # Fix round 1/5: экранирование ("../…", "/abs/…") и отсутствие файла —
        # разные находки, разный текст (было: обе в missing_sources под одним
        # «файла нет»).
        with tempfile.TemporaryDirectory() as temp:
            current = Path(temp)
            (current / "assets").mkdir()
            (current / "assets" / "a.mp4").write_bytes(b"x")
            (current / "assets" / "ok.png").write_bytes(b"x")
            self.assertEqual(media_sync.escaping_sources(self.HTML), ["../media/v.wav", "/abs/x.png"])
            self.assertEqual(media_sync.missing_sources(self.HTML, current), ["assets/missing.png"])
            problems = media_sync.check_composition(self.HTML, current)
        self.assertIn("внешняя ссылка: https://x.example/a.css", problems)
        self.assertIn("ссылка вне папки монтажа: ../media/v.wav", problems)
        self.assertIn("ссылка вне папки монтажа: /abs/x.png", problems)
        self.assertIn("файла нет в папке монтажа: assets/missing.png", problems)
        self.assertNotIn("файла нет в папке монтажа: ../media/v.wav", problems)

    def test_escaping_forms_are_caught_on_every_host(self):
        # Разбор чисто лексический (не спрашивает файловую систему хоста),
        # поэтому Windows-формы проверяются и на macOS/Linux CI тоже.
        html = ('<video src="C:/x.mp4"></video><video src="C:\\x.mp4"></video>'
                '<video src="D:a.mp4"></video><video src="..\\media\\v.wav"></video>'
                '<video src="\\abs\\x.mp4"></video><video src="assets/ok.mp4"></video>')
        self.assertEqual(media_sync.escaping_sources(html), [
            "C:/x.mp4", "C:\\x.mp4", "D:a.mp4", "..\\media\\v.wav", "\\abs\\x.mp4"])
        with tempfile.TemporaryDirectory() as temp:
            current = Path(temp)
            (current / "assets").mkdir()
            (current / "assets" / "ok.mp4").write_bytes(b"x")
            self.assertEqual(media_sync.missing_sources(html, current), [])


if __name__ == "__main__":
    unittest.main()

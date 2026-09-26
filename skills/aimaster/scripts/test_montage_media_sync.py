#!/usr/bin/env python3
"""Медиа в current/assets: жёсткая ссылка, иначе копия.

Fix round 2/5: проверка ссылок композиции (external/missing/escaping)
переехала в test_montage_composition_refs.py вместе с composition_refs.py —
здесь только про то, как файл попадает на диск."""

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

    def test_copy_does_not_depend_on_a_fixed_temp_name(self):
        (self.assets / ".asset-1.mp4.part").mkdir(parents=True)  # старое фиксированное имя занято
        with mock.patch.object(media_sync.os, "link", side_effect=OSError(errno.EXDEV, "cross-device")):
            self.assertEqual(media_sync.link_or_copy(self.source, self.assets / "asset-1.mp4"), "copy")
        self.assertEqual((self.assets / "asset-1.mp4").read_bytes(), b"video-bytes")
        self.assertEqual(sorted(p.name for p in self.assets.iterdir()), [".asset-1.mp4.part", "asset-1.mp4"])

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


if __name__ == "__main__":
    unittest.main()

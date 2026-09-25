#!/usr/bin/env python3
"""Шрифт монтажа: файлы в навыке совпадают с манифестом, @font-face только локальный."""

from __future__ import annotations

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

from studio.montage import MontageError, typeface  # noqa: E402


class TypefaceTests(unittest.TestCase):
    def test_bundle_matches_the_manifest_and_carries_the_license(self):
        manifest = typeface.load_manifest()
        self.assertEqual(typeface.verify_bundle(manifest), [])
        self.assertEqual((manifest["family"], manifest["license"]), (typeface.FONT_FAMILY, "OFL-1.1"))
        license_text = (typeface.FONT_DIR / manifest["license_file"]).read_text(encoding="utf-8")
        self.assertIn("SIL Open Font License, Version 1.1", license_text)
        self.assertLess(sum(item["bytes"] for item in manifest["files"]), 100 * 1024)

    def test_css_declares_only_local_files_with_cyrillic(self):
        css = typeface.font_face_css()
        self.assertEqual(css.count("@font-face"), 4)
        self.assertNotIn("http", css)
        self.assertIn('url("assets/fonts/inter-cyrillic-700-normal.woff2")', css)
        self.assertIn("U+0400-045F", css)
        self.assertEqual(typeface.FONT_STACK, '"AM Inter", sans-serif')

    def test_sync_copies_once_and_repairs_a_damaged_copy(self):
        # Fix round 1/5: sync_fonts теперь несёт и OFL.txt рядом со шрифтами
        # (условие 2 лицензии) — 4 шрифта + лицензия = 5, было 4.
        with tempfile.TemporaryDirectory() as temp:
            assets = Path(temp) / "assets"
            self.assertEqual(len(typeface.sync_fonts(assets)), 5)
            self.assertEqual(typeface.sync_fonts(assets), [])
            self.assertTrue((assets / "fonts" / "OFL.txt").is_file())
            self.assertIn("SIL Open Font License, Version 1.1",
                          (assets / "fonts" / "OFL.txt").read_text(encoding="utf-8"))
            damaged = assets / "fonts" / "inter-latin-400-normal.woff2"
            damaged.write_bytes(b"broken")
            self.assertEqual(typeface.sync_fonts(assets), ["inter-latin-400-normal.woff2"])
            self.assertEqual(damaged.read_bytes(),
                             (typeface.FONT_DIR / "inter-latin-400-normal.woff2").read_bytes())

    def test_verify_bundle_also_checks_the_license(self):
        manifest = dict(typeface.load_manifest())
        manifest["license_sha256"] = "0" * 64
        self.assertEqual(typeface.verify_bundle(manifest), ["OFL.txt"])

    def test_sync_refuses_a_broken_bundle_before_copying_anything(self):
        manifest = dict(typeface.load_manifest())
        manifest["files"] = [dict(manifest["files"][0])]
        manifest["files"][0]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temp:
            assets = Path(temp) / "assets"
            with self.assertRaises(MontageError) as caught:
                typeface.sync_fonts(assets, manifest)
            self.assertIn("пакет навыка повреждён, переустановите", str(caught.exception))
            self.assertFalse((assets / "fonts").exists())

    def test_sync_wraps_filesystem_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            assets = Path(temp) / "assets"
            with mock.patch.object(typeface.shutil, "copyfile", side_effect=OSError("disk full")):
                with self.assertRaises(MontageError):
                    typeface.sync_fonts(assets)


if __name__ == "__main__":
    unittest.main()

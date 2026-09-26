#!/usr/bin/env python3
"""Шрифт монтажа: файлы в навыке совпадают с манифестом, @font-face только локальный."""

from __future__ import annotations

import os
import shutil
import stat
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

from studio.montage import MontageError, index_io, media_sync, typeface  # noqa: E402


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

    def test_sync_does_not_depend_on_a_fixed_temp_name(self):
        with tempfile.TemporaryDirectory() as temp:
            fonts = Path(temp) / "assets" / "fonts"
            (fonts / ".inter-latin-400-normal.woff2.part").mkdir(parents=True)
            self.assertEqual(len(typeface.sync_fonts(Path(temp) / "assets")), 5)
            self.assertEqual(sorted(p.name for p in fonts.iterdir() if p.name.endswith(".part")),
                             [".inter-latin-400-normal.woff2.part"])

    def test_read_only_package_files_do_not_make_read_only_copies(self):
        # установка навыка «только для чтения»: копия шрифта не наследует права
        # файла пакета, иначе на Windows повторная синхронизация не заменит её
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp) / "пакет"
            shutil.copytree(typeface.FONT_DIR, package)
            for item in package.iterdir():
                os.chmod(item, 0o444)
            assets = Path(temp) / "assets"
            try:
                with mock.patch.object(typeface, "FONT_DIR", package):
                    self.assertEqual(len(typeface.sync_fonts(assets)), 5)
                    font = assets / "fonts" / "inter-latin-400-normal.woff2"
                    self.assertTrue(os.access(font, os.W_OK))
                    if os.name != "nt":
                        self.assertEqual(stat.S_IMODE(font.stat().st_mode), index_io.new_file_mode())
                    font.write_bytes(b"broken")
                    os.chmod(font, 0o444)  # повреждённая копия прежней версии — «только чтение»
                    self.assertEqual(typeface.sync_fonts(assets), [font.name])
                    self.assertTrue(os.access(font, os.W_OK))
                    self.assertEqual(font.read_bytes(), (package / font.name).read_bytes())
            finally:
                for item in package.iterdir():
                    os.chmod(item, 0o644)

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
            # копия идёт через media_sync.copy_via_temp (mkstemp + copyfile + замена)
            with mock.patch.object(media_sync.shutil, "copyfile", side_effect=OSError("disk full")):
                with self.assertRaises(MontageError):
                    typeface.sync_fonts(assets)
            self.assertEqual(list((assets / "fonts").glob(".*.part")), [])  # временный файл убран

    def test_verify_bundle_wraps_a_read_failure(self):
        # Fix round 2/5, item 4: OSError на чтении файла бандла (не «его
        # нет», а именно сбой чтения) — MontageError, как обещает докстрока.
        with mock.patch.object(Path, "read_bytes", side_effect=OSError("denied")):
            with self.assertRaises(MontageError):
                typeface.verify_bundle()

    def test_sync_fonts_wraps_a_verify_read_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            assets = Path(temp) / "assets"
            with mock.patch.object(Path, "read_bytes", side_effect=OSError("denied")):
                with self.assertRaises(MontageError):
                    typeface.sync_fonts(assets)

    def test_load_manifest_wraps_a_missing_or_unreadable_file(self):
        # Fix round 3/5, item 9: fonts.json нет/не читается/битый JSON —
        # MontageError «пакет навыка повреждён», не голый traceback.
        for error in (FileNotFoundError("no such file"), PermissionError("denied")):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(Path, "read_text", side_effect=error):
                    with self.assertRaises(MontageError) as caught:
                        typeface.load_manifest()
                    self.assertIn("пакет навыка повреждён, переустановите", str(caught.exception))

    def test_load_manifest_wraps_invalid_json(self):
        with mock.patch.object(Path, "read_text", return_value="не json {"):
            with self.assertRaises(MontageError) as caught:
                typeface.load_manifest()
            self.assertIn("пакет навыка повреждён, переустановите", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

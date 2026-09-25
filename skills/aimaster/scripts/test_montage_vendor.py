#!/usr/bin/env python3
"""GSAP из установленного движка → current/assets/: закреплённая версия, только локально."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import fake_gsap_prefix  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage import vendor  # noqa: E402
from studio.montage.engine import install_command, load_pin  # noqa: E402

PIN = load_pin()["gsap_version"]


class CopyGsapTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.assets = self.root / "current" / "assets"

    def test_copies_gsap_and_motion_path_plugin_and_returns_local_sources(self):
        prefix = fake_gsap_prefix(self.root)
        sources = vendor.copy_gsap(prefix, self.assets)
        self.assertEqual(sources, ["assets/gsap.min.js", "assets/MotionPathPlugin.min.js"])
        for name in ("gsap", "MotionPathPlugin"):
            self.assertEqual((self.assets / f"{name}.min.js").read_bytes(),
                             (vendor.gsap_dist(prefix) / f"{name}.min.js").read_bytes())
        self.assertEqual(sorted(p.name for p in self.assets.iterdir()),
                         ["MotionPathPlugin.min.js", "gsap.min.js"])

    def test_second_copy_refreshes_a_changed_file_and_leaves_no_temp(self):
        prefix = fake_gsap_prefix(self.root)
        vendor.copy_gsap(prefix, self.assets)
        (vendor.gsap_dist(prefix) / "gsap.min.js").write_text("/* обновлён */", encoding="utf-8")
        vendor.copy_gsap(prefix, self.assets)
        self.assertEqual((self.assets / "gsap.min.js").read_text(encoding="utf-8"), "/* обновлён */")
        self.assertEqual(len(list(self.assets.iterdir())), 2)

    def test_missing_gsap_names_the_install_command_and_writes_nothing(self):
        with self.assertRaises(MontageError) as caught:
            vendor.copy_gsap(self.root / "пусто", self.assets)
        message = str(caught.exception)
        self.assertIn(f"GSAP {PIN}", message)
        self.assertIn(install_command(), message)
        self.assertFalse(self.assets.exists())

    def test_wrong_version_is_named(self):
        prefix = fake_gsap_prefix(self.root, version="3.14.1")
        with self.assertRaises(MontageError) as caught:
            vendor.copy_gsap(prefix, self.assets)
        self.assertIn("3.14.1", str(caught.exception))
        self.assertIn(install_command(), str(caught.exception))
        self.assertFalse(self.assets.exists())

    def test_missing_dist_file_is_named(self):
        prefix = fake_gsap_prefix(self.root, files=("gsap",))
        with self.assertRaises(MontageError) as caught:
            vendor.copy_gsap(prefix, self.assets)
        self.assertIn("MotionPathPlugin.min.js", str(caught.exception))
        self.assertIn(install_command(), str(caught.exception))
        self.assertFalse(self.assets.exists())


if __name__ == "__main__":
    unittest.main()

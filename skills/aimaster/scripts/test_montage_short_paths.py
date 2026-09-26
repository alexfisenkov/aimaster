#!/usr/bin/env python3
"""Вывод чужих программ в отказе человеку — без абсолютных путей: метки вместо папок, «~» вместо HOME."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage.short_paths import short_paths  # noqa: E402


class ShortPathsTests(unittest.TestCase):
    def test_known_folders_become_labels_longest_first(self):
        ws = Path("/Volumes/Диск/рабочая папка")
        text = f"open {ws}/projects/p/montage/current/index.html; cache {ws}/tools/hf/cache"
        shown = short_paths(text, {ws: "<рабочая папка>", ws / "tools" / "hf": "<движок>"})
        self.assertEqual(shown, "open <рабочая папка>/projects/p/montage/current/index.html; "
                                "cache <движок>/cache")

    def test_home_becomes_tilde_and_windows_separators_are_handled(self):
        home = Path.home()
        self.assertEqual(short_paths(f"{home}/Library/x"), "~/Library/x")
        self.assertEqual(short_paths(r"C:\Users\a\ws\clip.mp4", {Path(r"C:\Users\a\ws"): "<рабочая папка>"})
                         .replace("\\", "/"), "<рабочая папка>/clip.mp4")

    def test_root_like_values_are_never_replaced(self):
        self.assertEqual(short_paths("a/b", {Path("/"): "X"}), "a/b")


if __name__ == "__main__":
    unittest.main()

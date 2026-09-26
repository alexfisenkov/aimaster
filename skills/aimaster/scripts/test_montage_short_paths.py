#!/usr/bin/env python3
"""Вывод чужих программ в отказе человеку — без абсолютных путей: метки вместо папок, «~» вместо HOME."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

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

    def test_mixed_separators_are_the_same_path(self):
        self.assertEqual(short_paths(r"D:\a\ws/projects\p/x", {Path("D:/a/ws"): "<рабочая папка>"}),
                         r"<рабочая папка>/projects\p/x")

    def test_root_like_values_are_never_replaced(self):
        self.assertEqual(short_paths("a/b", {Path("/"): "X"}), "a/b")
        for root in ("D:\\", "D:/", "D:"):
            self.assertEqual(short_paths(r"D:\clip.mp4 D:/x", {root: "X"}), r"D:\clip.mp4 D:/x", root)

    def test_only_whole_path_components_are_replaced(self):
        with mock.patch.object(Path, "home", return_value=Path("/Users/al")):
            self.assertEqual(short_paths("open /Users/alex/f.mp4"), "open /Users/alex/f.mp4")
            self.assertEqual(short_paths("open /Users/al/f.mp4"), "open ~/f.mp4")
        with mock.patch.object(Path, "home", return_value=Path("/app")):
            self.assertEqual(short_paths("fetch https://cdn.example/app/x.js"),
                             "fetch https://cdn.example/app/x.js")
            self.assertEqual(short_paths('cache "/app/.cache"'), 'cache "~/.cache"')
        ws = {Path("/Users/alex/proj"): "<рабочая папка>"}
        self.assertEqual(short_paths("/Users/alex/proj-old/a.mp4", ws), "/Users/alex/proj-old/a.mp4")
        self.assertEqual(short_paths("/Users/alex/proj.bak/a.mp4", ws), "/Users/alex/proj.bak/a.mp4")
        self.assertEqual(short_paths("in /Users/alex/proj.", ws), "in <рабочая папка>.")
        self.assertEqual(short_paths("(/Users/alex/proj)", ws), "(<рабочая папка>)")

    def test_url_schemes_keep_their_slashes(self):
        with mock.patch.object(Path, "home", return_value=Path("/app")):
            for url in ("http://app:3000/x", "file:///app/x", "see file:///app/x.js:12:3", "x:/app/y"):
                self.assertEqual(short_paths(url), url)
            self.assertEqual(short_paths("open /app/x and //app/y"), "open ~/x and ~/y")
        with mock.patch.object(Path, "home", return_value=Path(r"C:\Users\al")):
            self.assertEqual(short_paths("file:///C:/Users/al/x"), "file:///C:/Users/al/x")

    def test_paths_before_closing_punctuation_are_shortened(self):
        ws = {Path("/Users/alex/proj"): "<рабочая папка>"}
        for tail in (">", "}", "!", "?", "...", ".)", ".]", '."'):
            with self.subTest(tail=tail):
                self.assertEqual(short_paths(f"<in /Users/alex/proj{tail}", ws), f"<in <рабочая папка>{tail}")
        self.assertEqual(short_paths("{/Users/alex/proj}", ws), "{<рабочая папка>}")
        self.assertEqual(short_paths("/Users/alex/proj.v2/x", ws), "/Users/alex/proj.v2/x")


if __name__ == "__main__":
    unittest.main()

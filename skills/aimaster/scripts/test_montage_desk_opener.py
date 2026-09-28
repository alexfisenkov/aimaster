#!/usr/bin/env python3
"""Страница-переходник монтажного стола: ставит оба ключа отказа от аналитики
Studio и уходит в Studio того же адреса; лежит в current/.hyperframes/."""

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

from studio.montage.desk_opener import (  # noqa: E402
    OPENER_HTML, OPENER_RELATIVE, TELEMETRY_KEYS, ensure_opener, opener_file, opener_url)
from studio.montage.link_guard import check_montage_folder  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402

PAGE = "/api/projects/current/preview/.hyperframes/aimaster-desk-open.html"


class OpenerPageTests(unittest.TestCase):
    def test_page_sets_both_keys_before_it_goes_to_studio(self):
        self.assertEqual(TELEMETRY_KEYS, ("hyperframes-studio:telemetryDisabled",
                                          "hf-studio-telemetry-opt-out"))
        for key in TELEMETRY_KEYS:
            self.assertIn(f'"{key}"', OPENER_HTML)
        self.assertLess(OPENER_HTML.index("localStorage.setItem"),
                        OPENER_HTML.index("location.replace"))

    def test_page_goes_nowhere_but_its_own_origin(self):
        self.assertNotRegex(OPENER_HTML, r"https?://")
        self.assertIn('location.replace("/#project/"', OPENER_HTML)

    def test_page_declares_its_charset(self):
        # Studio отдаёт .html как «text/html» без charset — русский текст иначе ломается
        self.assertIn('<meta charset="utf-8">', OPENER_HTML)


class EnsureOpenerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.paths = montage_paths(Path(temp.name).resolve() / "папка с пробелом" / "p")
        self.paths.current.mkdir(parents=True)

    def test_page_goes_into_the_hidden_service_folder_of_the_montage(self):
        ensure_opener(self.paths)
        self.assertEqual(opener_file(self.paths), self.paths.current / ".hyperframes" / "aimaster-desk-open.html")
        self.assertEqual(opener_file(self.paths).read_text(encoding="utf-8"), OPENER_HTML)
        self.assertEqual(OPENER_RELATIVE, ".hyperframes/aimaster-desk-open.html")

    def test_same_page_is_not_written_again(self):
        ensure_opener(self.paths)
        with mock.patch("studio.montage.desk_opener.write_text_atomic") as write:
            ensure_opener(self.paths)
        write.assert_not_called()

    def test_changed_page_is_put_back(self):
        ensure_opener(self.paths)
        opener_file(self.paths).write_text("<p>чужое</p>", encoding="utf-8")
        ensure_opener(self.paths)
        self.assertEqual(opener_file(self.paths).read_text(encoding="utf-8"), OPENER_HTML)

    def test_page_does_not_trip_the_link_guard(self):
        ensure_opener(self.paths)
        check_montage_folder(self.paths.root)  # обычный файл — не ссылка и не ffmpeg


class OpenerUrlTests(unittest.TestCase):
    def test_address_is_on_the_desk_origin(self):
        self.assertEqual(opener_url("http://127.0.0.1:52508/#project/current"),
                         "http://127.0.0.1:52508" + PAGE)

    def test_studio_state_after_the_name_is_ignored(self):
        self.assertEqual(opener_url("http://127.0.0.1:1/#project/current?v=1&t=0&tab=design"),
                         "http://127.0.0.1:1" + PAGE)

    def test_unusual_name_is_encoded(self):
        self.assertEqual(
            opener_url("http://127.0.0.1:1/#project/%D0%BC%D0%BE%D0%BD%D1%82%D0%B0%D0%B6"),
            "http://127.0.0.1:1/api/projects/%D0%BC%D0%BE%D0%BD%D1%82%D0%B0%D0%B6/preview/"
            ".hyperframes/aimaster-desk-open.html")

    def test_no_project_in_the_address_means_no_page(self):
        for url in ("http://127.0.0.1:1/", "http://127.0.0.1:1/#settings",
                    "http://127.0.0.1:1/#project/", "http://127.0.0.1:1/#project/a%2Fb", "#project/x",
                    "http://127.0.0.1:1/#project/.", "http://127.0.0.1:1/#project/..",
                    "http://127.0.0.1:1/#project/%2E%2E", "http://127.0.0.1:1/#project/a%5Cb"):
            with self.subTest(url=url):
                self.assertIsNone(opener_url(url))

    def test_only_a_plain_address_on_this_computer_gets_a_page(self):
        for url in ("https://127.0.0.1:1/#project/current", "http://example.com:1/#project/current",
                    "http://u:p@127.0.0.1:1/#project/current", "file:///#project/current",
                    "http://127.0.0.1/#project/current", "http://127.0.0.1:99999/#project/current"):
            with self.subTest(url=url):
                self.assertIsNone(opener_url(url))


if __name__ == "__main__":
    unittest.main()

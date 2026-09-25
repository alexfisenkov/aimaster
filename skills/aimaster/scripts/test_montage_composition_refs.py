#!/usr/bin/env python3
"""Ссылки композиции не выходят наружу и не уходят за пределы current/.

Fix round 2/5: выделен из test_montage_media_sync.py вместе с
composition_refs.py (module split, ruling item 1)."""

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

from studio.montage import composition_refs  # noqa: E402


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
        self.assertEqual(composition_refs.external_references(self.HTML), [
            "https://fonts.googleapis.com/css2?family=Inter",
            "//cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js",
            "https://x.example/a.css", "file:///etc/x.png", "https://y.example/b.png"])

    def test_missing_and_escaping_sources(self):
        with tempfile.TemporaryDirectory() as temp:
            current = Path(temp)
            (current / "assets").mkdir()
            (current / "assets" / "a.mp4").write_bytes(b"x")
            (current / "assets" / "ok.png").write_bytes(b"x")
            self.assertEqual(composition_refs.escaping_sources(self.HTML),
                             ["../media/v.wav", "/abs/x.png"])
            self.assertEqual(composition_refs.missing_sources(self.HTML, current),
                             ["assets/missing.png"])
            problems = composition_refs.check_composition(self.HTML, current)
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
        self.assertEqual(composition_refs.escaping_sources(html), [
            "C:/x.mp4", "C:\\x.mp4", "D:a.mp4", "..\\media\\v.wav", "\\abs\\x.mp4"])
        with tempfile.TemporaryDirectory() as temp:
            current = Path(temp)
            (current / "assets").mkdir()
            (current / "assets" / "ok.mp4").write_bytes(b"x")
            self.assertEqual(composition_refs.missing_sources(html, current), [])

    def test_percent_encoded_traversal_is_caught(self):
        # Fix round 2/5, item 8: "%2e%2e/" декодируется в ".." до проверки —
        # иначе она прячет подъём, хотя рендерер его раскодирует и подставит.
        html = ('<video src="%2e%2e/media/v.mp4"></video>'
                '<video src="assets%2fok.mp4"></video>')
        self.assertEqual(composition_refs.escaping_sources(html),
                         ["%2e%2e/media/v.mp4"])
        # Сообщение показывает исходную (закодированную) ссылку — не то, во
        # что она раскодировалась, а то, что реально написано в композиции.
        problems = composition_refs.check_composition(html, Path("/nonexistent"))
        self.assertIn("ссылка вне папки монтажа: %2e%2e/media/v.mp4", problems)

    def test_percent_encoded_backslash_traversal_is_caught(self):
        # Fix round 3/5, item 8: раскодировать НАДО раньше нормализации "\\"
        # → "/" — "%5c" не текстовый "\\", им не станет, пока не раскодирован;
        # старый порядок (сначала заменить "\\", потом unquote) эту форму
        # пропускал.
        html = ('<video src="..%5cmedia%5cv.mp4"></video>'
                '<video src="%5cabs%5cx.mp4"></video>')
        self.assertEqual(composition_refs.escaping_sources(html),
                         ["..%5cmedia%5cv.mp4", "%5cabs%5cx.mp4"])

    def test_percent_encoded_space_in_an_existing_file_is_not_missing(self):
        # Fix round 3/5, item 8: missing_sources ищет файл по тому же
        # раскодированному пути, что escaping_sources проверяет — иначе
        # "my%20clip.mp4" ищет файл с буквальным "%20" в имени и не находит
        # реально существующий "my clip.mp4".
        html = '<video src="assets/my%20clip.mp4"></video>'
        with tempfile.TemporaryDirectory() as temp:
            current = Path(temp)
            (current / "assets").mkdir()
            (current / "assets" / "my clip.mp4").write_bytes(b"x")
            self.assertEqual(composition_refs.missing_sources(html, current), [])


    def test_local_gsap_is_allowed_and_cdn_gsap_is_not(self):
        # Задача 10b: черновик несёт GSAP из движка локально (assets/) — это
        # не проблема сборки, пока файл лежит в папке монтажа; тот же GSAP с
        # CDN — внешняя ссылка, как и раньше.
        local = ('<head><script src="assets/gsap.min.js"></script>'
                 '<script src="assets/MotionPathPlugin.min.js"></script></head>'
                 '<body><script>window.__timelines["main"] = gsap.timeline({ paused: true });'
                 '</script></body>')
        with tempfile.TemporaryDirectory() as temp:
            current = Path(temp)
            (current / "assets").mkdir()
            (current / "assets" / "gsap.min.js").write_text("/* gsap */", encoding="utf-8")
            self.assertEqual(composition_refs.check_composition(local, current),
                             ["файла нет в папке монтажа: assets/MotionPathPlugin.min.js"])
            (current / "assets" / "MotionPathPlugin.min.js").write_text("/* mp */", encoding="utf-8")
            self.assertEqual(composition_refs.check_composition(local, current), [])
            cdn = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>'
            self.assertEqual(composition_refs.check_composition(cdn, current),
                             ["внешняя ссылка: https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"])


if __name__ == "__main__":
    unittest.main()

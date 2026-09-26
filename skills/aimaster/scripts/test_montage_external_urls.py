#!/usr/bin/env python3
"""round 4/5, пункт 2: внешние ссылки композиции (studio/montage/external_urls.py).

Каждая форма — в настоящем, валидном HTML/CSS: так, как её написал бы
человек или агент, а не упрощённый заменитель."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import montage_ci_check  # noqa: E402
from studio.montage import composition_refs  # noqa: E402
from studio.montage.external_urls import external_urls  # noqa: E402


class FormsTests(unittest.TestCase):
    def check(self, html: str, expected: list[str]):
        self.assertEqual(external_urls(html), expected)

    def test_src_href_poster_in_every_quoting(self):
        self.check('<img src="https://a.test/1.png"><img src=\'https://a.test/2.png\'>'
                   '<img src=https://a.test/3.png alt="">'
                   '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter">'
                   '<video poster="//a.test/p.jpg" src="assets/v.mp4"></video>',
                   ["https://a.test/1.png", "https://a.test/2.png", "https://a.test/3.png",
                    "https://fonts.googleapis.com/css2?family=Inter", "//a.test/p.jpg"])

    def test_srcset_every_candidate_in_every_quoting(self):
        self.check('<img src="assets/a.png" srcset="assets/a.png 1x, https://a.test/a2.png 2x, '
                   '//a.test/a3.png 3x">'
                   "<img srcset='https://a.test/w480.png 480w, assets/w800.png 800w'>"
                   '<img srcset=https://a.test/bare.png>'
                   '<img srcset=https://a.test/b1.png,https://a.test/b2.png>',
                   ["https://a.test/a2.png", "//a.test/a3.png", "https://a.test/w480.png",
                    "https://a.test/bare.png", "https://a.test/b1.png", "https://a.test/b2.png"])

    def test_css_url_in_every_quoting(self):
        self.check('<div style="background: url(https://a.test/u1.png)"></div>'
                   "<style>.a { background: url('https://a.test/u2.png') no-repeat; }"
                   '.b { background: URL( "//a.test/u3.png" ); }</style>',
                   ["https://a.test/u1.png", "https://a.test/u2.png", "//a.test/u3.png"])

    def test_import_as_string_and_as_url(self):
        self.check('<style>@import "https://a.test/i1.css";\n'
                   "@import 'https://a.test/i2.css' screen;\n"
                   '@import url(https://a.test/i3.css);\n'
                   '@import url("https://a.test/i4.css") layer(base);</style>',
                   ["https://a.test/i1.css", "https://a.test/i2.css", "https://a.test/i3.css",
                    "https://a.test/i4.css"])

    def test_image_set_with_url_functions(self):
        self.check('<style>.a { background-image: image-set(url(https://a.test/s1.png) 1x, '
                   'url("https://a.test/s2.png") 2x); }</style>',
                   ["https://a.test/s1.png", "https://a.test/s2.png"])

    def test_webkit_image_set(self):
        self.check('<style>.a { background-image: -webkit-image-set(url(https://a.test/wk1.png) 1x, '
                   "url('//a.test/wk2.png') 2x); }</style>",
                   ["https://a.test/wk1.png", "//a.test/wk2.png"])

    def test_image_set_with_plain_strings(self):
        self.check('<style>.a { background-image: image-set("https://a.test/str1.png" 1x, '
                   "'https://a.test/str2.avif' type(\"image/avif\"), \"assets/c.png\" 2x); }</style>",
                   ["https://a.test/str1.png", "https://a.test/str2.avif"])

    def test_document_order_is_kept_across_forms(self):
        self.check('<style>@import "https://a.test/first.css";</style>'
                   '<img srcset="https://a.test/second.png 1x">'
                   '<div style="background: image-set(\'https://a.test/third.png\' 1x)"></div>'
                   '<video src="https://a.test/fourth.mp4"></video>',
                   ["https://a.test/first.css", "https://a.test/second.png", "https://a.test/third.png",
                    "https://a.test/fourth.mp4"])


class LocalTests(unittest.TestCase):
    def test_local_paths_and_data_uris_never_match(self):
        html = ('<video src="assets/clip.mp4" poster="./poster.jpg"></video>'
                '<audio src=assets/voice.wav></audio>'
                '<link rel="stylesheet" href="../style.css">'
                '<img src="/abs/from/root.png" srcset="assets/a.png 1x, assets/b.png 2x">'
                '<img src="C:/Users/Александр/Видео/кадр.png">'
                '<img src="data:image/png;base64,AAAA" srcset="data:image/png;base64,AA 1x">'
                '<style>@import "local.css"; @font-face { src: url(assets/fonts/inter.woff2); }'
                '.a { background: url(data:image/svg+xml;utf8,<svg/>); }'
                '.b { background-image: image-set("assets/c.png" 1x, url(assets/d.png) 2x); }</style>')
        self.assertEqual(external_urls(html), [])

    def test_ci_check_uses_the_build_scanner(self):
        # CI проверяет черновик навыка тем же разбором, что и сборка версии
        # (composition_refs → этот external_urls); своего сканера у неё нет.
        # Что сам черновик чист — test_montage_ci_check.py.
        self.assertIs(montage_ci_check.check_composition, composition_refs.check_composition)
        self.assertIs(montage_ci_check.external_references, composition_refs.external_references)
        self.assertIs(composition_refs.external_urls, external_urls)


if __name__ == "__main__":
    unittest.main()

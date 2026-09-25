#!/usr/bin/env python3
"""Раскладка montage/ и точечная правка index.html: остальное — байт в байт."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage import MontageError  # noqa: E402
from studio.montage.html_doc import (  # noqa: E402
    element_attrs, element_span, fmt_number, insert_before_root_end, root_duration, set_attr,
    set_text)
from studio.montage.paths import (  # noqa: E402
    montage_paths, render_output, version_name, version_number)

# Так выглядит композиция после открытия в Studio: data-hf-id, <!DOCTYPE>, <meta …>.
SAMPLE = """<!DOCTYPE html>
<html lang="ru">
  <head>
    <meta charset="UTF-8">
  </head>
  <body>
    <div data-hf-id="hf-qv3y" id="root" data-composition-id="main" data-start="0" data-duration="15" data-width="1080" data-height="1920" data-no-timeline>
      <video data-hf-id="hf-hjwo" id="v-1" class="am-video" src="assets/a.mp4" data-start="0" data-duration="5" data-media-start="0" data-am-layer="video" data-am-scene="s1" playsinline></video>
      <div data-hf-id="hf-d5xw" id="t-1" class="clip am-title" data-start="1" data-duration="2" data-am-layer="titles"><span data-hf-id="hf-p0ft">Барсик &amp; клубок</span></div>
      <audio id="a-voice" src="assets/v.wav" data-start="2" data-duration="6" data-volume="1" data-am-layer="voice"></audio>
    </div>
  </body>
</html>
"""


class ReadTests(unittest.TestCase):
    def test_attributes_text_and_boolean_attrs(self):
        attrs = element_attrs(SAMPLE)
        self.assertEqual((attrs["v-1"]["_tag"], attrs["v-1"]["data-am-scene"]), ("video", "s1"))
        self.assertEqual(attrs["t-1"]["_text"], "Барсик & клубок")
        self.assertEqual(attrs["root"]["data-no-timeline"], "")
        self.assertEqual(root_duration(SAMPLE), 15.0)

    def test_numbers_are_short(self):
        self.assertEqual([fmt_number(v) for v in (1.5, 2, 0.30000001, -0.0, 12.3456)],
                         ["1.5", "2", "0.3", "0", "12.346"])


class PatchTests(unittest.TestCase):
    def test_replace_changes_only_that_value(self):
        changed = set_attr(SAMPLE, "v-1", "data-start", "1")
        self.assertEqual(changed, SAMPLE.replace(
            'src="assets/a.mp4" data-start="0"', 'src="assets/a.mp4" data-start="1"'))

    def test_add_and_remove(self):
        added = set_attr(SAMPLE, "a-voice", "data-fade-out", "0.5")
        self.assertIn('data-am-layer="voice" data-fade-out="0.5"></audio>', added)
        removed = set_attr(SAMPLE, "v-1", "data-media-start", None)
        self.assertIn('data-duration="5" data-am-layer="video"', removed)
        self.assertEqual(set_attr(SAMPLE, "v-1", "data-nothing", None), SAMPLE)

    def test_values_are_escaped(self):
        changed = set_attr(SAMPLE, "t-1", "title", 'a "b" & c')
        self.assertIn('title="a &quot;b&quot; &amp; c"', changed)
        self.assertEqual(element_attrs(changed)["t-1"]["title"], 'a "b" & c')

    def test_title_text(self):
        changed = set_text(SAMPLE, "t-1", "Кот <и> мяч")
        self.assertIn('<span data-hf-id="hf-p0ft">Кот &lt;и&gt; мяч</span>', changed)
        with self.assertRaises(MontageError):
            set_text(SAMPLE, "v-1", "не титр")

    def test_span_and_insert(self):
        begin, end = element_span(SAMPLE, "t-1")
        self.assertTrue(SAMPLE[begin:end].startswith('<div data-hf-id="hf-d5xw" id="t-1"'))
        self.assertTrue(SAMPLE[begin:end].endswith("</span></div>"))
        inserted = insert_before_root_end(SAMPLE, '<div id="t-9"></div>')
        self.assertIn('      <div id="t-9"></div>\n    </div>\n  </body>', inserted)

    def test_missing_element(self):
        with self.assertRaises(MontageError):
            set_attr(SAMPLE, "nope", "data-start", "1")


class PathsTests(unittest.TestCase):
    def test_layout(self):
        paths = montage_paths(Path("/w/projects/p"))
        self.assertEqual(paths.index, Path("/w/projects/p/montage/current/index.html"))
        self.assertEqual(paths.assets, Path("/w/projects/p/montage/current/assets"))
        self.assertEqual(paths.version_dir("v003"), Path("/w/projects/p/montage/versions/v003"))
        self.assertEqual(paths.desk_file, Path("/w/projects/p/montage/.desk.json"))
        self.assertEqual(render_output(Path("/w/media"), "p", "v003"),
                         Path("/w/media/p/montage/v003.mp4"))

    def test_version_names(self):
        self.assertEqual((version_name(12), version_number("v012")), ("v012", 12))
        for bad in ("v1", "003", "v01a"):
            with self.assertRaises(ValueError):
                version_number(bad)


# Fix round 1/5: <script> (montage gsap допишет свой), <style> и комментарии
# не должны читаться как разметка тег-сканером на регэкспах.
WITH_SCRIPT = """<div id="root" data-duration="1">
  <!-- фальшивка <div id="v-1"></div> в комментарии -->
  <style>#fake[id="v-1"] { color: red; }</style>
  <script>const html = '<div id="v-1"></div>';</script>
  <video id="v-1" src="assets/a.mp4" data-start="0"></video>
</div>
"""

NESTED_SPAN = ('<div id="t-1" class="clip am-title"><span>внешний '
               '<span class="hl">внутренний</span> хвост</span></div>')


class FixRoundOneTests(unittest.TestCase):
    def test_comments_style_and_script_are_not_markup(self):
        changed = set_attr(WITH_SCRIPT, "v-1", "data-start", "1")
        self.assertIn('id="v-1" src="assets/a.mp4" data-start="1"', changed)
        self.assertIn("фальшивка <div id=\"v-1\"></div> в комментарии", changed)
        self.assertIn("const html = '<div id=\"v-1\"></div>';", changed)
        begin, end = element_span(WITH_SCRIPT, "v-1")
        self.assertEqual(WITH_SCRIPT[begin:end],
                         '<video id="v-1" src="assets/a.mp4" data-start="0"></video>')

    def test_set_text_replaces_nested_spans_as_one_block(self):
        changed = set_text(NESTED_SPAN, "t-1", "новый текст")
        self.assertEqual(changed, '<div id="t-1" class="clip am-title"><span>новый текст</span></div>')

    def test_set_attr_bare_boolean_insert_and_remove(self):
        base = '<video id="v-1" src="a.mp4"></video>'
        muted = set_attr(base, "v-1", "muted", True)
        self.assertEqual(muted, '<video id="v-1" src="a.mp4" muted></video>')
        unmuted = set_attr(muted, "v-1", "muted", None)
        self.assertEqual(unmuted, base)
        # true → true — не задваивает и не переносит атрибут не туда.
        self.assertEqual(set_attr(muted, "v-1", "muted", True), muted)

    def test_insert_before_root_end_keeps_crlf(self):
        crlf = SAMPLE.replace("\n", "\r\n")
        inserted = insert_before_root_end(crlf, '<div id="t-9"></div>')
        self.assertIn('<div id="t-9"></div>\r\n    </div>\r\n  </body>', inserted)
        self.assertNotIn("</div>\n    </div>", inserted)

    def test_set_attr_false_removes_like_none(self):
        # Fix round 2/5, item 5: value=False должно убирать атрибут, а не
        # писать буквальный текст name="False".
        base = '<video id="v-1" src="a.mp4"></video>'
        muted = set_attr(base, "v-1", "muted", True)
        self.assertEqual(set_attr(muted, "v-1", "muted", False), base)
        self.assertNotIn("False", set_attr(muted, "v-1", "muted", False))
        # Не было атрибута — value=False тоже ничего не вставляет.
        self.assertEqual(set_attr(base, "v-1", "muted", False), base)


# Fix round 2/5, item 2: раньше _excluded_ranges сканировал комментарии и
# <script>/<style> ДВУМЯ независимыми regex — если один тип разметки прятал
# внутри себя обрывок другого, они путали начало/конец друг у друга.
COMMENT_HIDES_UNCLOSED_SCRIPT = (
    '<!-- <script> fake, no closing -->\n'
    '<video id="v-1" src="assets/a.mp4"></video>\n'
    '<script id="s-1">var x = 1;</script>\n'
)
SCRIPT_HIDES_FAKE_COMMENT_START = (
    '<script id="s-1">var x = "<!--";</script>\n'
    '<video id="v-1" src="assets/a.mp4"></video>\n'
    '<!-- real comment -->\n'
)


class FixRoundTwoScanTests(unittest.TestCase):
    def test_comment_hiding_an_unclosed_script_does_not_swallow_the_real_element(self):
        changed = set_attr(COMMENT_HIDES_UNCLOSED_SCRIPT, "v-1", "data-start", "1")
        self.assertIn('<video id="v-1" src="assets/a.mp4" data-start="1"></video>', changed)
        # Настоящий <script> после комментария остался ровно тем, чем был.
        self.assertIn('<script id="s-1">var x = 1;</script>', changed)

    def test_script_hiding_a_fake_comment_start_does_not_swallow_the_real_element(self):
        changed = set_attr(SCRIPT_HIDES_FAKE_COMMENT_START, "v-1", "data-start", "1")
        self.assertIn('<video id="v-1" src="assets/a.mp4" data-start="1"></video>', changed)
        self.assertIn('<!-- real comment -->', changed)


if __name__ == "__main__":
    unittest.main()

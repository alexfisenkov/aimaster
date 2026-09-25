#!/usr/bin/env python3
"""normalize_split_fades: чистит внутренний край разреза — свой и сделанный в Studio."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage.html_doc import element_attrs  # noqa: E402
from studio.montage.split_fades import normalize_split_fades  # noqa: E402

# Как реально выглядит разрез с обеих сторон (проба 0.8.75, задача 14 brief):
# CLI и Studio копируют fade-in/fade-out и класс am-fade-in на ОБЕ половины;
# data-hf-id и порядок — шум, который Studio добавляет и который не должен
# мешать опознать пару.
STUDIO_SPLIT = """<!DOCTYPE html>
<html lang="ru">
  <head><meta charset="UTF-8" /></head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="2" data-hf-id="hf-r00t">
      <video id="v-1" class="am-video am-fade-in" data-start="0" data-duration="1"
             data-am-asset="asset-a" data-media-start="0" data-fade-in="0.4" data-fade-out="0.4"
             data-hf-id="hf-aaa1"></video>
      <video id="v-1-2" class="am-video am-fade-in" data-start="1" data-duration="1"
             data-am-asset="asset-a" data-media-start="1" data-fade-in="0.4" data-fade-out="0.4"
             data-hf-id="hf-aaa2"></video>
    </div>
  </body>
</html>
"""


class SplitFadesTests(unittest.TestCase):
    def test_studio_style_split_clears_the_inner_edge_only(self):
        text, changed = normalize_split_fades(STUDIO_SPLIT)
        self.assertEqual(set(changed), {"v-1", "v-1-2"})
        attrs = element_attrs(text)
        # Левая половина: внутренний конец (data-fade-out) снят, внешнее
        # начало (data-fade-in, оно у неё тоже было скопировано) осталось.
        self.assertNotIn("data-fade-out", attrs["v-1"])
        self.assertEqual(attrs["v-1"]["data-fade-in"], "0.4")
        self.assertEqual(attrs["v-1"]["class"], "am-video am-fade-in")
        # Правая половина: внутреннее начало (data-fade-in + класс) снято,
        # внешний конец (data-fade-out) остался.
        self.assertNotIn("data-fade-in", attrs["v-1-2"])
        self.assertEqual(attrs["v-1-2"]["data-fade-out"], "0.4")
        self.assertEqual(attrs["v-1-2"]["class"], "am-video")

    def test_idempotent(self):
        once, _ = normalize_split_fades(STUDIO_SPLIT)
        twice, changed = normalize_split_fades(once)
        self.assertEqual(once, twice)
        self.assertEqual(changed, [])

    def test_unrelated_clips_are_left_alone(self):
        # v-1-2 переставлен на другой исходник — больше не продолжение v-1.
        text = STUDIO_SPLIT.replace('data-am-asset="asset-a" data-media-start="1"',
                                    'data-am-asset="asset-b" data-media-start="0"')
        _, changed = normalize_split_fades(text)
        self.assertEqual(changed, [])

    def test_title_split_matches_by_text_not_asset(self):
        titles = ('<div id="t-1" class="clip am-title" data-start="0" data-duration="1">'
                  '<span>Привет</span></div>'
                  '<div id="t-1-2" class="clip am-title" data-start="1" data-duration="1">'
                  '<span>Привет</span></div>')
        text = STUDIO_SPLIT.replace("</div>\n  </body>", titles + "</div>\n  </body>")
        _, changed = normalize_split_fades(text)
        # у титров нет fade-атрибутов вовсе — normalize их не трогает, но и не падает
        self.assertNotIn("t-1", changed)
        self.assertNotIn("t-1-2", changed)


if __name__ == "__main__":
    unittest.main()

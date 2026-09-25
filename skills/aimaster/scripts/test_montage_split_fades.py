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

# <audio> в черновике никогда не несёт class вовсе (draft_html._element не
# пишет его для не-видео дорожек) — проверка «класс дописывается, только
# если он там реально был» (round-fix-2/5, item 2) нужна фикстуре без него.
STUDIO_SPLIT_AUDIO = """<!DOCTYPE html>
<html lang="ru">
  <head><meta charset="UTF-8" /></head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="2" data-hf-id="hf-r00t">
      <audio id="a-voice" data-start="0" data-duration="1" data-am-asset="asset-v"
             data-media-start="0" data-fade-in="0.4" data-fade-out="0.4" data-hf-id="hf-vvv1"></audio>
      <audio id="a-voice-2" data-start="1" data-duration="1" data-am-asset="asset-v"
             data-media-start="1" data-fade-in="0.4" data-fade-out="0.4" data-hf-id="hf-vvv2"></audio>
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

    def test_no_empty_class_added_to_elements_without_one(self):
        # Round-fix-2/5, item 2: <audio> никогда не несёт class — раньше
        # normalize дописывал пустой class="", хотя дело было только в
        # data-fade-in/out, к классу отношения не имеющих.
        text, changed = normalize_split_fades(STUDIO_SPLIT_AUDIO)
        self.assertEqual(set(changed), {"a-voice", "a-voice-2"})
        attrs = element_attrs(text)
        self.assertNotIn("data-fade-out", attrs["a-voice"])
        self.assertNotIn("data-fade-in", attrs["a-voice-2"])
        self.assertNotIn("class", attrs["a-voice"])
        self.assertNotIn("class", attrs["a-voice-2"])
        self.assertNotIn('class=""', text)

    def test_title_split_matches_by_text_when_no_asset_marker(self):
        # Round-fix-2/5, item 9: прежняя фикстура не несла data-media-start
        # вовсе — is_split_pair требует и временную, и media-непрерывность,
        # так что пара тогда не подтверждалась вообще ничем: у титров и так
        # нет fade, поэтому «ничего не изменилось» проходило вхолостую и при
        # разбитой контактной проверке. Здесь — честная непрерывность
        # (0..1, затем 1..2 с data-media-start="1") и fade-атрибуты,
        # специально добавленные для теста, чтобы увидеть факт снятия, а не
        # только отсутствие падения.
        titles = ('<div id="t-1" class="clip am-title" data-start="0" data-duration="1" '
                  'data-fade-out="0.3"><span>Привет</span></div>'
                  '<div id="t-1-2" class="clip am-title am-fade-in" data-start="1" '
                  'data-duration="1" data-media-start="1" data-fade-in="0.3">'
                  '<span>Привет</span></div>')
        text = STUDIO_SPLIT.replace("</div>\n  </body>", titles + "</div>\n  </body>")
        result, changed = normalize_split_fades(text)
        self.assertEqual(set(changed) & {"t-1", "t-1-2"}, {"t-1", "t-1-2"})
        attrs = element_attrs(result)
        self.assertNotIn("data-fade-out", attrs["t-1"])
        self.assertNotIn("data-fade-in", attrs["t-1-2"])
        self.assertEqual(attrs["t-1-2"]["class"], "clip am-title")

    def test_data_playback_start_is_accepted_like_model_py(self):
        # Round-fix-3/5, item E: тот же запасной атрибут, что model.py:94
        # (`data-media-start` или, если его нет, `data-playback-start`).
        text = STUDIO_SPLIT.replace("data-media-start", "data-playback-start")
        result, changed = normalize_split_fades(text)
        self.assertEqual(set(changed), {"v-1", "v-1-2"})
        attrs = element_attrs(result)
        self.assertNotIn("data-fade-out", attrs["v-1"])
        self.assertNotIn("data-fade-in", attrs["v-1-2"])

    def test_titles_with_different_text_are_not_matched(self):
        titles = ('<div id="t-1" class="clip am-title" data-start="0" data-duration="1" '
                  'data-fade-out="0.3"><span>Привет</span></div>'
                  '<div id="t-1-2" class="clip am-title" data-start="1" data-duration="1" '
                  'data-media-start="1" data-fade-in="0.3"><span>Другое</span></div>')
        text = STUDIO_SPLIT.replace("</div>\n  </body>", titles + "</div>\n  </body>")
        _, changed = normalize_split_fades(text)
        self.assertEqual(set(changed) & {"t-1", "t-1-2"}, set())


if __name__ == "__main__":
    unittest.main()

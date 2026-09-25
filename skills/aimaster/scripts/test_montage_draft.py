#!/usr/bin/env python3
"""Черновик: эталонная разметка без титров, GSAP и внешних ссылок; свой шрифт; обновление устаревших клипов."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import video_state  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.draft import create_draft, rebuild_draft, refresh_draft, stale_clips  # noqa: E402
from studio.montage.draft_html import title_fragment  # noqa: E402
from studio.montage.html_doc import element_attrs  # noqa: E402
from studio.montage.media_sync import external_references, missing_sources  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402

SCENES = [("s1", "Сад", "Барсик идёт по саду", 2000, "asset-a"),
          ("s2", "Клубок", "Находит клубок", 2000, "asset-b")]
ROOT = ('<div id="root" data-composition-id="main" data-start="0" data-duration="3.5" '
        'data-width="108" data-height="192" data-no-timeline>')
V1 = ('<video id="v-1" class="am-video" src="assets/asset-a.mp4" data-media-start="0" '
      'data-start="0" data-duration="2" data-track-index="0" data-am-layer="video" '
      'data-am-scene="s1" data-am-asset="asset-a" data-has-audio="true" data-volume="0.3" '
      'data-fade-out="0.4" playsinline></video>')
V2 = ('<video id="v-2" class="am-video am-fade-in" src="assets/asset-b.mp4" data-media-start="0" '
      'data-start="2" data-duration="1.5" data-track-index="0" data-am-layer="video" '
      'data-am-scene="s2" data-am-asset="asset-b" muted playsinline></video>')
VOICE = ('<audio id="a-voice" src="assets/asset-v.wav" data-media-start="0" data-start="0" '
         'data-duration="3.5" data-track-index="2" data-am-layer="voice" data-am-asset="asset-v" '
         'data-volume="1"></audio>')


class DraftTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        self.media = base / "media"
        self.media.mkdir()
        self.infos = {"asset-a": MediaInfo(2.0, 108, 192, True, True),
                      "asset-b": MediaInfo(1.5, 108, 192, True, False),
                      "asset-c": MediaInfo(1.0, 108, 192, True, True),
                      "asset-v": MediaInfo(5.0, None, None, False, True)}
        for asset in self.infos:
            suffix = ".wav" if asset == "asset-v" else ".mp4"
            (self.media / f"{asset}{suffix}").write_bytes(asset.encode())
        self.paths = montage_paths(base / "projects" / "p")

    def resolve(self, asset):
        return next(self.media.glob(f"{asset}.*"))

    def probe(self, path):
        return self.infos[Path(path).stem]

    def draft(self, state):
        return create_draft(self.paths, state, self.resolve, probe=self.probe)

    def test_draft_is_the_reference_composition(self):
        result = self.draft(video_state(SCENES, audio={"voice": "asset-v"}))
        text = self.paths.index.read_text(encoding="utf-8")
        self.assertEqual((result.canvas, result.duration, result.clips), (Canvas(108, 192), 3.5, 3))
        for line in (ROOT, V1, V2, VOICE):
            self.assertIn(line, text)
        self.assertNotIn('data-am-layer="titles"', text)
        self.assertNotIn("gsap", text.lower())
        self.assertNotIn("<script", text)
        self.assertIn('font-family: "AM Inter", sans-serif', text)
        self.assertNotIn("font-family: sans-serif", text)
        self.assertIn('src: url("assets/fonts/inter-cyrillic-400-normal.woff2") format("woff2")', text)
        self.assertTrue((self.paths.assets / "fonts" / "inter-cyrillic-700-normal.woff2").is_file())
        self.assertEqual(external_references(text), [])
        self.assertEqual(missing_sources(text, self.paths.current), [])
        config = json.loads((self.paths.current / "hyperframes.json").read_text(encoding="utf-8"))
        self.assertEqual(config, {"media": {"autoProxy": True}})

    def test_title_fragment_uses_the_title_style(self):
        self.assertEqual(title_fragment("t-1", "Кот & «мяч»", 0.2, 1.6),
                         '<div id="t-1" class="clip am-title" data-start="0.2" data-duration="1.6" '
                         'data-track-index="1" data-am-layer="titles"><span>Кот &amp; «мяч»</span></div>')

    def test_second_draft_is_refused(self):
        self.draft(video_state(SCENES))
        with self.assertRaises(MontageError) as caught:
            self.draft(video_state(SCENES))
        self.assertIn("--refresh", str(caught.exception))

    def test_refresh_replaces_only_the_stale_clip(self):
        self.draft(video_state(SCENES))
        before = element_attrs(self.paths.index.read_text(encoding="utf-8"))
        newer = video_state([SCENES[0], ("s2", "Клубок", "Находит клубок", 2000, "asset-c")])
        stale = refresh_draft(self.paths, newer, self.resolve, probe=self.probe)
        self.assertEqual([item["clip"] for item in stale], ["v-2"])
        after = element_attrs(self.paths.index.read_text(encoding="utf-8"))
        self.assertEqual((after["v-2"]["src"], after["v-2"]["data-am-asset"], after["v-2"]["data-duration"]),
                         ("assets/asset-c.mp4", "asset-c", "1"))
        self.assertEqual(after["v-1"], before["v-1"])
        self.assertEqual(stale_clips(self.paths.index.read_text(encoding="utf-8"), newer), [])

    def test_rebuild_keeps_the_old_draft_in_undo(self):
        self.draft(video_state(SCENES))
        original = self.paths.index.read_text(encoding="utf-8")
        self.paths.index.write_text(original + "<!-- правка в столе -->", encoding="utf-8")
        result, backup = rebuild_draft(self.paths, video_state(SCENES), self.resolve, probe=self.probe)
        self.assertEqual(result.clips, 2)
        self.assertEqual(self.paths.index.read_text(encoding="utf-8"), original)
        self.assertEqual(backup.parent, self.paths.undo)
        self.assertTrue(backup.read_text(encoding="utf-8").endswith("<!-- правка в столе -->"))


if __name__ == "__main__":
    unittest.main()

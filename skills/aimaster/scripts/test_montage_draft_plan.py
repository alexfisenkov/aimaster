#!/usr/bin/env python3
"""План черновика: порядок сцен, окна сцен, выбранные результаты, звук, переходы; без титров."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import video_state  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.draft_plan import plan_draft  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402
from studio.projection import validate_state  # noqa: E402

MEDIA = {
    "asset-a": MediaInfo(2.0, 108, 192, True, True),
    "asset-b": MediaInfo(1.5, 108, 192, True, False),
    "asset-o": MediaInfo(3.0, 108, 192, True, True),
    "asset-v": MediaInfo(5.0, None, None, False, True),
    "asset-m": MediaInfo(60.0, None, None, False, True),
}
SCENES = [("s1", "Сад", "Барсик идёт по саду", 2000, "asset-a"),
          ("s2", "Клубок", "Находит клубок", 2000, "asset-b")]


def by_layer(plan, *layers):
    return [clip for clip in plan.clips if clip.layer in layers]


class DraftPlanTests(unittest.TestCase):
    def test_fixture_is_a_valid_project(self):
        validate_state(video_state(SCENES, audio={"voice": "asset-v"}))

    def test_clips_follow_scene_order_and_windows(self):
        plan = plan_draft(video_state(SCENES), MEDIA.__getitem__)
        videos = by_layer(plan, "video")
        self.assertEqual([(c.clip_id, c.scene_id, c.start, c.duration) for c in videos],
                         [("v-1", "s1", 0.0, 2.0), ("v-2", "s2", 2.0, 1.5)])
        self.assertEqual(plan.duration, 3.5)
        self.assertEqual([c.visual_fade for c in videos], [False, True])
        self.assertEqual((videos[0].volume, videos[0].fade_in, videos[0].fade_out), (1.0, 0.0, 0.4))
        self.assertEqual((videos[1].volume, videos[1].has_audio), (None, False))
        self.assertEqual(plan.first_video_asset(), "asset-a")

    def test_draft_has_no_titles(self):
        """Текст сцены — описание кадра, а не реплика: титры добавляет только montage edit."""
        plan = plan_draft(video_state(SCENES, audio={"voice": "asset-v"}), MEDIA.__getitem__)
        self.assertEqual(by_layer(plan, "titles"), [])
        self.assertEqual([c.clip_id for c in plan.clips], ["v-1", "v-2", "a-voice"])

    def test_audio_layers_and_video_under_them(self):
        plan = plan_draft(video_state(SCENES, audio={"voice": "asset-v", "music": "asset-m"}),
                          MEDIA.__getitem__)
        audio = {clip.layer: clip for clip in by_layer(plan, "voice", "music")}
        self.assertEqual((audio["voice"].clip_id, audio["voice"].volume, audio["voice"].duration),
                         ("a-voice", 1.0, 3.5))
        self.assertEqual((audio["music"].volume, audio["music"].fade_out), (0.3, 1.0))
        self.assertEqual(by_layer(plan, "video")[0].volume, 0.3)
        self.assertEqual(plan.media_assets(), ["asset-a", "asset-b", "asset-v", "asset-m"])

    def test_missing_scene_video_is_named(self):
        state = video_state([SCENES[0], ("s2", "Клубок", "Находит клубок", 2000, None)])
        with self.assertRaises(MontageError) as caught:
            plan_draft(state, MEDIA.__getitem__)
        self.assertIn("Клубок", str(caught.exception))

    def test_photo_project_has_no_montage(self):
        state = video_state(SCENES)
        state["project"]["type"] = "photo"
        with self.assertRaises(MontageError) as caught:
            plan_draft(state, MEDIA.__getitem__)
        self.assertIn("фото", str(caught.exception))

    def test_one_shot_is_one_clip_over_the_story(self):
        state = video_state([("s1", "Сад", "Барсик в саду", 2000, None),
                             ("s2", "Клубок", "Клубок", 2000, None)],
                            gen_mode="one_shot", oneshot_asset="asset-o")
        plan = plan_draft(state, MEDIA.__getitem__)
        self.assertEqual([(c.clip_id, c.scene_id, c.start, c.duration) for c in by_layer(plan, "video")],
                         [("v-1", None, 0.0, 3.0)])
        self.assertEqual(by_layer(plan, "titles"), [])


if __name__ == "__main__":
    unittest.main()

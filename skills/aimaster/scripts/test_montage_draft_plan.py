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
from studio.domain import DomainValidationError  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.draft_plan import audio_sources, plan_draft, video_sources  # noqa: E402
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


# Fix round 1/5: _current_asset брал результат по указателю позиции не
# спрашивая decision/retired/hidden — отклонённый, отправленный в архив,
# скрытый или ещё не принятый результат тогда попадал в черновик как обычный.
_REJECTING_STATES = {
    "undecided": lambda result: result.pop("decision", None),
    "rejected": lambda result: result.__setitem__("decision", "rejected"),
    "retired": lambda result: result.__setitem__("retired", True),
    "hidden": lambda result: result.__setitem__("hidden", True),
    "empty_asset_id": lambda result: result.__setitem__("asset_id", ""),
}


class AcceptedOnlyTests(unittest.TestCase):
    def _video_result_for(self, state, scene_id):
        return next(r for r in state["video_results"] if r["scene_id"] == scene_id)

    def _audio_result_for(self, state, layer):
        return next(r for r in state["audio_results"]
                    if r["result_id"] == f"result:audio:{layer}")

    def test_unaccepted_scene_video_is_excluded_and_named(self):
        for name, mutate in _REJECTING_STATES.items():
            with self.subTest(state=name):
                state = video_state(SCENES)
                mutate(self._video_result_for(state, "s2"))
                found = video_sources(state, strict=False)
                self.assertEqual([scene["scene_id"] for scene, _asset in found], ["s1"])
                with self.assertRaises(MontageError) as caught:
                    plan_draft(state, MEDIA.__getitem__)
                self.assertIn("Клубок", str(caught.exception))
                self.assertIn("не принято", str(caught.exception))

    def test_unaccepted_audio_layer_is_silently_excluded(self):
        for name, mutate in _REJECTING_STATES.items():
            with self.subTest(state=name):
                state = video_state(SCENES, audio={"voice": "asset-v"})
                mutate(self._audio_result_for(state, "voice"))
                self.assertEqual(audio_sources(state), {})
                # Звук необязателен — план собирается и без принятого голоса.
                plan = plan_draft(state, MEDIA.__getitem__)
                self.assertEqual(by_layer(plan, "voice"), [])

    def test_unaccepted_one_shot_is_named(self):
        state = video_state([("s1", "Сад", "Барсик в саду", 2000, None),
                             ("s2", "Клубок", "Клубок", 2000, None)],
                            gen_mode="one_shot", oneshot_asset="asset-o")
        state["video_results"][0]["decision"] = "rejected"
        with self.assertRaises(MontageError) as caught:
            plan_draft(state, MEDIA.__getitem__)
        self.assertIn("не принято", str(caught.exception))

    def test_duplicate_link_is_a_montage_error_not_a_domain_error(self):
        state = video_state(SCENES)
        duplicate = dict(self._video_result_for(state, "s2"))
        duplicate["result_id"] = "result:scene:s2:video-dup"
        duplicate["asset_id"] = "asset-c"
        state["video_results"].append(duplicate)
        with self.assertRaises(MontageError):
            video_sources(state, strict=False)
        # А не оригинальным исключением слоя владений — оно течь наружу не должно.
        try:
            video_sources(state, strict=False)
        except DomainValidationError:
            self.fail("duplicate link должен всплывать как MontageError")
        except MontageError:
            pass

    def test_duplicate_link_error_names_the_scene(self):
        # Fix round 2/5, item 6: текст по-русски называет сцену/слой, а не
        # голое исключение domain.
        state = video_state(SCENES)
        duplicate = dict(self._video_result_for(state, "s2"))
        duplicate["result_id"] = "result:scene:s2:video-dup"
        duplicate["asset_id"] = "asset-c"
        state["video_results"].append(duplicate)
        with self.assertRaises(MontageError) as caught:
            video_sources(state, strict=False)
        self.assertIn("сломана ссылка на результат сцены Клубок", str(caught.exception))
        self.assertIn("выберите вариант заново", str(caught.exception))

    def test_duplicate_link_error_names_the_audio_layer(self):
        state = video_state(SCENES, audio={"voice": "asset-v"})
        duplicate = dict(self._audio_result_for(state, "voice"))
        duplicate["result_id"] = "result:audio:voice-dup"
        duplicate["asset_id"] = "asset-v2"
        state["audio_results"].append(duplicate)
        with self.assertRaises(MontageError) as caught:
            audio_sources(state)
        self.assertIn("звукового слоя «voice»", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

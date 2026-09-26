#!/usr/bin/env python3
"""ffprobe → MediaInfo и размер кадра монтажа."""

from __future__ import annotations

import subprocess
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

import montage_testkit  # noqa: E402
from studio.montage import MontageError, probe  # noqa: E402
from studio.montage.canvas import Canvas, canvas_for  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_video_with_sound(self):
        info = probe.parse_probe({"streams": [
            {"codec_type": "video", "width": 1080, "height": 1920}, {"codec_type": "audio"}],
            "format": {"duration": "15.000000"}})
        self.assertEqual(info, MediaInfo(15.0, 1080, 1920, True, True))

    def test_mp3_cover_is_not_a_picture(self):
        info = probe.parse_probe({"streams": [
            {"codec_type": "video", "width": 500, "height": 500, "disposition": {"attached_pic": 1}},
            {"codec_type": "audio"}], "format": {"duration": "3.5"}})
        self.assertEqual(info, MediaInfo(3.5, None, None, False, True))

    def test_bad_duration_is_zero(self):
        self.assertEqual(probe.parse_probe({"format": {"duration": "N/A"}}).duration, 0.0)

    def test_side_data_rotation_swaps_width_and_height(self):
        # Современный способ хранить поворот: displaymatrix. Значение бывает
        # отрицательным (типично -90 у портретной съёмки) — нормализуем %360.
        payload = {"streams": [
            {"codec_type": "video", "width": 1920, "height": 1080,
             "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]}]}
        info = probe.parse_probe(payload)
        self.assertEqual((info.width, info.height), (1080, 1920))

    def test_legacy_rotate_tag_lowercase_mp4_form_swaps(self):
        # Старый способ хранить поворот в mp4 — тег rotate, ровно в нижнем
        # регистре: так его пишет сам mp4/mov.
        payload = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080,
                                "tags": {"rotate": "270"}}]}
        info = probe.parse_probe(payload)
        self.assertEqual((info.width, info.height), (1080, 1920))

    def test_matroska_uppercase_rotate_tag_is_not_honoured(self):
        # ROTATE в верхнем регистре — собственная условность Matroska, а не
        # общий формат; угадывать её не стоит (реальный источник — mp4).
        payload = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080,
                                "tags": {"ROTATE": "270"}}]}
        info = probe.parse_probe(payload)
        self.assertEqual((info.width, info.height), (1920, 1080))

    def test_180_degrees_does_not_swap(self):
        payload = {"streams": [{"codec_type": "video", "width": 1920, "height": 1080,
                                "tags": {"rotate": "180"}}]}
        info = probe.parse_probe(payload)
        self.assertEqual((info.width, info.height), (1920, 1080))


class ProbeTests(unittest.TestCase):
    def test_missing_ffprobe(self):
        with mock.patch.object(probe, "find_ffprobe", return_value=None):
            with self.assertRaises(MontageError) as caught:
                probe.probe_media(Path("x.mp4"))
        self.assertIn("ffprobe", str(caught.exception))

    def test_failure_names_the_file(self):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, b"", b"Invalid data found")
        with self.assertRaises(MontageError) as caught:
            probe.probe_media(Path("клип 1.mp4"), ffprobe="/usr/bin/ffprobe", runner=runner)
        self.assertIn("клип 1.mp4", str(caught.exception))
        self.assertIn("Invalid data", str(caught.exception))

    def test_tool_output_carries_no_absolute_paths(self):
        clip = Path.home() / "Проекты" / "клип 1.mp4"
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, b"", f"{clip}: Invalid data".encode())
        with self.assertRaises(MontageError) as caught:
            probe.probe_media(clip, ffprobe="/usr/bin/ffprobe", runner=runner)
        self.assertIn("<папка файла>/клип 1.mp4: Invalid data", str(caught.exception).replace("\\", "/"))
        self.assertNotIn(str(Path.home()), str(caught.exception))

    def test_timeout_is_reported(self):
        def runner(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        with self.assertRaises(MontageError) as caught:
            probe.probe_media(Path("клип.mp4"), ffprobe="/usr/bin/ffprobe", runner=runner)
        self.assertIn("не запустился", str(caught.exception))

    def test_oserror_is_reported(self):
        def runner(argv, **kwargs):
            raise OSError("нет такого файла")
        with self.assertRaises(MontageError) as caught:
            probe.probe_media(Path("клип.mp4"), ffprobe="/несуществующий/ffprobe", runner=runner)
        self.assertIn("не запустился", str(caught.exception))

    def test_non_json_stdout_is_reported(self):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, "это не json".encode("utf-8"), b"")
        with self.assertRaises(MontageError) as caught:
            probe.probe_media(Path("клип.mp4"), ffprobe="/usr/bin/ffprobe", runner=runner)
        self.assertIn("не JSON", str(caught.exception))

    def test_real_clip_with_cyrillic_path(self):
        montage_testkit.ffmpeg_or_skip()
        with tempfile.TemporaryDirectory() as temp:
            clip = montage_testkit.make_clip(Path(temp) / "папка с пробелом" / "клип 1.mp4", 1.0)
            info = probe.probe_media(clip)
        self.assertAlmostEqual(info.duration, 1.0, delta=0.1)
        self.assertEqual((info.width, info.height, info.has_video, info.has_audio),
                         (108, 192, True, True))

    def test_real_rotated_clip_reports_display_dimensions(self):
        # Клип реально закодирован лёжа боком (192x108) и реально несёт
        # матрицу поворота в mp4 (ffmpeg -display_rotation + -c copy — см.
        # montage_testkit.make_rotated_clip) — probe_media должен вернуть
        # то, что покажет плеер (108x192), а не то, что физически в потоке.
        montage_testkit.ffmpeg_or_skip()
        with tempfile.TemporaryDirectory() as temp:
            clip = montage_testkit.make_rotated_clip(Path(temp) / "поворот.mp4", 1.0,
                                                      size=(192, 108), rotation=90)
            info = probe.probe_media(clip)
        self.assertAlmostEqual(info.duration, 1.0, delta=0.2)
        self.assertEqual((info.width, info.height, info.has_video), (108, 192, True))


class CanvasTests(unittest.TestCase):
    def test_default_when_unknown(self):
        self.assertEqual(canvas_for(None), Canvas(1080, 1920))
        self.assertEqual(canvas_for(MediaInfo(3.0, None, None, False, True)), Canvas(1080, 1920))

    def test_takes_first_video_and_rounds_up_to_even(self):
        self.assertEqual(canvas_for(MediaInfo(3.0, 1280, 720, True, False)), Canvas(1280, 720))
        self.assertEqual(canvas_for(MediaInfo(3.0, 1081, 1919, True, False)), Canvas(1082, 1920))
        self.assertEqual(Canvas(540, 960).to_dict(), {"width": 540, "height": 960})


if __name__ == "__main__":
    unittest.main()

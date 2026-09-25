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

    def test_real_clip_with_cyrillic_path(self):
        montage_testkit.ffmpeg_or_skip()
        with tempfile.TemporaryDirectory() as temp:
            clip = montage_testkit.make_clip(Path(temp) / "папка с пробелом" / "клип 1.mp4", 1.0)
            info = probe.probe_media(clip)
        self.assertAlmostEqual(info.duration, 1.0, delta=0.1)
        self.assertEqual((info.width, info.height, info.has_video, info.has_audio),
                         (108, 192, True, True))


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

#!/usr/bin/env python3
"""Проверка движка для CI: без движка — понятный JSON; черновик навыка с титром готов
к сборке без сети; каждая причина в problems даёт ok: false."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import montage_ci_check  # noqa: E402
import montage_testkit  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.composition_refs import check_composition, external_references  # noqa: E402
from studio.montage.draft_html import TIMELINE_SCRIPT  # noqa: E402
from studio.montage.engine import Engine  # noqa: E402
from studio.montage.engine_cli import EngineResult  # noqa: E402
from studio.montage.html_doc import element_attrs  # noqa: E402
from studio.montage.index_io import read_index  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402


def _touch(path, *_args, **_kwargs) -> Path:
    """Заглушка make_clip/make_tone: логику черновика и отчёта проверяем без
    настоящего ffmpeg — только создаём файл на месте клипа."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(path.name.encode("utf-8"))
    return path


def _probe(path) -> MediaInfo:
    """ffprobe черновика: клипы — как у make_clip (кадр SIZE, со звуком), голос — только звук."""

    seconds = {"clip-1": 2.0, "clip-2": 1.0}.get(Path(path).stem, montage_ci_check.DURATION)
    video = Path(path).suffix == ".mp4"
    width, height = montage_ci_check.SIZE if video else (None, None)
    return MediaInfo(duration=seconds, width=width, height=height, has_video=video, has_audio=True)


def _fake_engine(prefix: Path) -> Engine:
    return Engine(node="node", script=Path("hyperframes.mjs"), prefix=prefix, version="9.9.9",
                  browser=None)


class FakeMediaTestCase(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.prefix = montage_testkit.fake_gsap_prefix(temp.name)
        for name, fake in (("make_clip", _touch), ("make_tone", _touch)):
            patcher = mock.patch.object(montage_testkit, name, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)


class CiCheckTests(FakeMediaTestCase):
    def test_missing_engine_is_json_not_traceback(self):
        buffer = io.StringIO()
        with mock.patch.object(montage_ci_check, "require_engine",
                               side_effect=MontageError("Монтажный движок не готов: не найден Node.js")), \
                redirect_stdout(buffer):
            code = montage_ci_check.main(["--json"])
        report = json.loads(buffer.getvalue())
        self.assertEqual(code, 1)
        self.assertIs(report["ok"], False)
        self.assertIn("не готов", report["problems"][0])

    def test_skill_draft_with_a_title_is_ready_for_an_offline_build(self):
        # Задача 10b: черновик — локальный GSAP из движка и один таймлайн main
        # на паузе, корень без data-no-timeline; титр — как после montage edit
        # title-add; текст только шрифтом «AM Inter»; ни одной внешней ссылки.
        with mock.patch.object(montage_ci_check, "probe_media", side_effect=_probe):
            comp = montage_ci_check.build_draft(self.temp / "проверка монтажа" / "ролик 1", self.prefix)
        text = read_index(comp / "index.html")
        self.assertEqual((external_references(text), check_composition(text, comp)), ([], []))
        root = element_attrs(text)["root"]
        self.assertNotIn("data-no-timeline", root)
        self.assertEqual((root["data-duration"], root["data-width"], root["data-height"]),
                         ("3", "540", "960"))
        self.assertEqual((root["data-am-scenes"], root["data-am-layers"]), ("s1 s2", "voice"))
        head = text[:text.index("</head>")]
        self.assertIn('<script src="assets/gsap.min.js"></script>', head)
        self.assertIn('<script src="assets/MotionPathPlugin.min.js"></script>', head)
        self.assertEqual(text.count('window.__timelines["main"] ='), 1)
        self.assertIn(TIMELINE_SCRIPT.split("\n")[3].strip(), text)
        title = element_attrs(text)["t-1"]
        self.assertEqual((title["class"], title["data-am-layer"]), ("clip am-title", "titles"))
        self.assertIn(f"<span>{montage_ci_check.TITLE}</span>", text)
        self.assertIn('font-family: "AM Inter", sans-serif', text)
        self.assertNotIn("font-family: sans-serif", text)
        for name in ("gsap.min.js", "MotionPathPlugin.min.js", "clip-1.mp4", "clip-2.mp4", "voice.wav",
                     "fonts/inter-cyrillic-700-normal.woff2"):
            self.assertTrue((comp / "assets" / name).is_file(), name)
        self.assertEqual(json.loads((comp / "hyperframes.json").read_text(encoding="utf-8")),
                         {"media": {"autoProxy": True}})



class VideoMd5Tests(unittest.TestCase):
    def test_video_md5_is_the_decoded_picture(self):
        montage_testkit.ffmpeg_or_skip()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "проверка md5"
            red = montage_testkit.make_clip(folder / "кадр 1.mp4", 1.0, color="red")
            again = montage_testkit.make_clip(folder / "кадр 2.mp4", 1.0, color="red", freq=880)
            blue = montage_testkit.make_clip(folder / "кадр 3.mp4", 1.0, color="blue")
            digest = montage_ci_check.video_md5(red)
            self.assertRegex(digest, r"^[0-9a-f]{32}$")
            self.assertEqual(montage_ci_check.video_md5(again), digest)  # другой звук — та же картинка
            self.assertNotEqual(montage_ci_check.video_md5(blue), digest)


class CiCheckReportTests(FakeMediaTestCase):
    """check(): каждая причина `problems` даёт `ok: False`, чистый прогон — `ok: True`."""

    def setUp(self):
        super().setUp()
        for name, value in (("require_engine", lambda: _fake_engine(self.prefix)),
                            ("video_md5", lambda path: "0" * 32)):
            patcher = mock.patch.object(montage_ci_check, name, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _check(self, *, lint=None, probe=None, render_code=0, render_stdout="", render_stderr=""):
        def fake_render(engine, args, *, cwd, timeout):
            self.rendered = read_index(Path(cwd) / "index.html")
            self.render_args = list(args)
            output = Path(args[args.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"stub")
            return EngineResult(render_code, render_stdout, render_stderr)

        final = probe or self._clean_probe()
        with mock.patch.object(montage_ci_check, "run_engine_json",
                               return_value=lint or {"ok": True, "findings": []}), \
                mock.patch.object(montage_ci_check, "run_engine", side_effect=fake_render), \
                mock.patch.object(montage_ci_check, "probe_media",
                                  side_effect=lambda path: final if Path(path).name == "итог ролика.mp4"
                                  else _probe(path)):
            return montage_ci_check.check(False)

    def _clean_probe(self, **overrides) -> MediaInfo:
        fields = {"duration": montage_ci_check.DURATION, "width": montage_ci_check.SIZE[0],
                  "height": montage_ci_check.SIZE[1], "has_video": True, "has_audio": True}
        fields.update(overrides)
        return MediaInfo(**fields)

    def test_clean_run_is_ok(self):
        report = self._check()
        self.assertIs(report["ok"], True)
        self.assertEqual((report["problems"], report["video_md5"]), ([], "0" * 32))
        self.assertIn(montage_ci_check.TITLE, self.rendered)  # рендерится черновик с титром
        # качество — то же, что у сборки версии (engine.json), а не отдельное
        self.assertEqual(self.render_args[self.render_args.index("--quality") + 1],
                         montage_ci_check.load_pin()["render_quality"])

    def test_engine_without_gsap_is_a_json_problem(self):
        self.prefix = Path(self.prefix).parent / "без-gsap"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = montage_ci_check.main(["--json"])
        report = json.loads(buffer.getvalue())
        self.assertEqual((code, report["ok"]), (1, False))
        self.assertIn("GSAP", report["problems"][0])

    def test_network_marker_fails(self):
        report = self._check(render_stdout="…text… from Google Fonts …more…")
        self.assertIs(report["ok"], False)
        self.assertTrue(any(p.startswith("сеть:") for p in report["problems"]), report["problems"])

    def test_font_substitution_is_a_network_marker_too(self):
        # Метки — из verify.network_markers, как у сборки версии: подменённый
        # шрифт без сети дал бы другой ролик, чем с сетью.
        report = self._check(render_stderr="[Compiler] Injected deterministic @font-face rules")
        self.assertIs(report["ok"], False)
        self.assertEqual(report["network_markers"], ["[Compiler] Injected deterministic @font-face rules"])

    def test_wrong_duration_fails(self):
        report = self._check(probe=self._clean_probe(duration=5.0))
        self.assertIs(report["ok"], False)
        self.assertTrue(any("длительность" in p for p in report["problems"]), report["problems"])

    def test_wrong_size_fails(self):
        report = self._check(probe=self._clean_probe(width=1080, height=1920))
        self.assertIs(report["ok"], False)
        self.assertTrue(any("кадр" in p for p in report["problems"]), report["problems"])

    def test_no_audio_fails(self):
        report = self._check(probe=self._clean_probe(has_audio=False))
        self.assertIs(report["ok"], False)
        self.assertTrue(any("нет звука" in p for p in report["problems"]), report["problems"])

    def test_failed_render_fails(self):
        report = self._check(render_code=1, render_stderr="browser crashed")
        self.assertIs(report["ok"], False)
        self.assertTrue(any("кодом 1" in p and "browser crashed" in p for p in report["problems"]))
        self.assertNotIn("video_md5", report)

    def test_lint_error_finding_fails(self):
        report = self._check(lint={"ok": False, "errorCount": 1,
                                   "findings": [{"severity": "error", "code": "X1", "message": "beep"}]})
        self.assertIs(report["ok"], False)
        self.assertEqual([p for p in report["problems"] if p.startswith("lint:")], ["lint: X1: beep"])

    def test_lint_internal_crash_fails(self):
        report = self._check(lint={"ok": False, "error": "boom", "findings": [], "errorCount": 0})
        self.assertIs(report["ok"], False)
        self.assertTrue(any(p.startswith("lint:") and "boom" in p for p in report["problems"]),
                        report["problems"])

    def test_composition_problem_fails(self):
        with mock.patch.object(montage_ci_check, "check_composition",
                               return_value=["внешняя ссылка: https://cdn.example/gsap.js"]):
            report = self._check()
        self.assertIs(report["ok"], False)
        self.assertIn("композиция: внешняя ссылка: https://cdn.example/gsap.js", report["problems"])

    # Все формы внешних ссылок (srcset, image-set, @import, …) — test_montage_external_urls.py.


if __name__ == "__main__":
    unittest.main()

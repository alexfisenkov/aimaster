#!/usr/bin/env python3
"""Проверка движка для CI: без движка — понятный JSON, композиция без внешних ссылок,
с локальным GSAP и таймлайном main, как у черновика (задача 10b)."""

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
from studio.montage.draft_html import TIMELINE_SCRIPT  # noqa: E402
from studio.montage.engine import Engine  # noqa: E402
from studio.montage.engine_cli import EngineResult  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402


class CiCheckTests(unittest.TestCase):
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

    def test_external_urls_are_found(self):
        html = ('<link href="https://fonts.googleapis.com/css2?family=Inter">'
                '<video src="assets/a.mp4"></video>'
                '<div style="background:url(//cdn.example/y.png)"></div>'
                '<img src="data:image/png;base64,AA">')
        self.assertEqual(montage_ci_check.external_urls(html),
                         ["https://fonts.googleapis.com/css2?family=Inter", "//cdn.example/y.png"])

    def test_fixture_is_shaped_like_the_draft(self):
        # Задача 10b: CI рендерит на трёх ОС (и без сети на Linux) то же, что
        # несёт черновик: локальный GSAP из движка и таймлайн main, без
        # data-no-timeline — и ни одной внешней ссылки.
        composition = montage_ci_check.COMPOSITION
        self.assertEqual(montage_ci_check.external_urls(composition), [])
        self.assertNotIn("data-no-timeline", composition)
        self.assertIn('<script src="assets/gsap.min.js"></script>', composition)
        self.assertIn('<script src="assets/MotionPathPlugin.min.js"></script>', composition)
        self.assertIn(TIMELINE_SCRIPT.split("\n")[3].strip(), composition)
        self.assertLess(composition.index('id="root"'), composition.index('window.__timelines["main"]'))

    # Все формы ссылок (srcset, image-set, @import, …) — test_montage_external_urls.py:
    # round 4/5 вынес поиск в studio/montage/external_urls.py, общий с media_sync.


def _touch(path, *_args, **_kwargs) -> Path:
    """Заглушка make_clip/make_tone: юнит-тесты check() проверяют логику
    отчёта, а не настоящий ffmpeg — только создают файл на месте клипа."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def _fake_engine(prefix: Path) -> Engine:
    return Engine(node="node", script=Path("hyperframes.mjs"), prefix=prefix, version="9.9.9",
                  browser=None)


class CiCheckReportTests(unittest.TestCase):
    """check(): каждая причина `problems` даёт `ok: False`, чистый прогон — `ok: True`
    (round 1/5, пункт 5 — раньше это проверял только настоящий движок в CI)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.prefix = montage_testkit.fake_gsap_prefix(temp.name)
        clip_patch = mock.patch.object(montage_testkit, "make_clip", side_effect=_touch)
        tone_patch = mock.patch.object(montage_testkit, "make_tone", side_effect=_touch)
        engine_patch = mock.patch.object(montage_ci_check, "require_engine",
                                         side_effect=lambda: _fake_engine(self.prefix))
        for patcher in (clip_patch, tone_patch, engine_patch):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _check(self, *, lint, probe, render_code=0, render_stdout="", render_stderr=""):
        def fake_render(engine, args, *, cwd, timeout):
            self.rendered_assets = sorted(path.name for path in (Path(cwd) / "assets").iterdir())
            args = list(args)
            output = Path(args[args.index("--output") + 1])
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"stub")
            return EngineResult(render_code, render_stdout, render_stderr)

        with mock.patch.object(montage_ci_check, "run_engine_json", return_value=lint), \
                mock.patch.object(montage_ci_check, "run_engine", side_effect=fake_render), \
                mock.patch.object(montage_ci_check, "probe_media", return_value=probe):
            return montage_ci_check.check(False)

    def _clean_probe(self, **overrides) -> MediaInfo:
        fields = {"duration": montage_ci_check.DURATION, "width": montage_ci_check.SIZE[0],
                  "height": montage_ci_check.SIZE[1], "has_video": True, "has_audio": True}
        fields.update(overrides)
        return MediaInfo(**fields)

    def test_clean_run_is_ok(self):
        report = self._check(lint={"findings": []}, probe=self._clean_probe())
        self.assertIs(report["ok"], True)
        self.assertEqual(report["problems"], [])
        # GSAP движка лежит в assets композиции к моменту рендера.
        self.assertEqual(self.rendered_assets, ["MotionPathPlugin.min.js", "clip-1.mp4", "clip-2.mp4",
                                                "gsap.min.js", "voice.wav"])

    def test_engine_without_gsap_is_a_json_problem(self):
        self.prefix = Path(self.prefix).parent / "без-gsap"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = montage_ci_check.main(["--json"])
        report = json.loads(buffer.getvalue())
        self.assertEqual((code, report["ok"]), (1, False))
        self.assertIn("GSAP", report["problems"][0])

    def test_network_marker_fails(self):
        report = self._check(lint={"findings": []}, probe=self._clean_probe(),
                             render_stdout="…text… from Google Fonts …more…")
        self.assertIs(report["ok"], False)
        self.assertTrue(any(p.startswith("сеть:") for p in report["problems"]), report["problems"])

    def test_wrong_duration_fails(self):
        report = self._check(lint={"findings": []}, probe=self._clean_probe(duration=5.0))
        self.assertIs(report["ok"], False)
        self.assertTrue(any("длительность" in p for p in report["problems"]), report["problems"])

    def test_wrong_size_fails(self):
        report = self._check(lint={"findings": []}, probe=self._clean_probe(width=1080, height=1920))
        self.assertIs(report["ok"], False)
        self.assertTrue(any("кадр" in p for p in report["problems"]), report["problems"])

    def test_no_audio_fails(self):
        report = self._check(lint={"findings": []}, probe=self._clean_probe(has_audio=False))
        self.assertIs(report["ok"], False)
        self.assertIn("в ролике нет звука", report["problems"])

    def test_lint_error_finding_fails(self):
        """round 3/5: обычный неуспешный lint — {"ok": false, "errorCount": N,
        "findings": […]} — не крэш инструмента (нет ключа "error"), ровно
        одна причина от самой находки."""

        report = self._check(lint={"ok": False, "errorCount": 1,
                                   "findings": [{"severity": "error", "code": "X1", "message": "beep"}]},
                             probe=self._clean_probe())
        self.assertIs(report["ok"], False)
        lint_problems = [p for p in report["problems"] if p.startswith("lint:")]
        self.assertEqual(len(lint_problems), 1)
        self.assertIn("X1", lint_problems[0])
        self.assertIn("beep", lint_problems[0])

    def test_lint_internal_crash_fails(self):
        report = self._check(lint={"ok": False, "error": "boom", "findings": [], "errorCount": 0},
                             probe=self._clean_probe())
        self.assertIs(report["ok"], False)
        self.assertTrue(any(p.startswith("lint:") and "boom" in p for p in report["problems"]),
                        report["problems"])


if __name__ == "__main__":
    unittest.main()

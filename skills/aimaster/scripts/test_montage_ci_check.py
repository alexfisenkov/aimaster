#!/usr/bin/env python3
"""Проверка движка для CI: без движка — понятный JSON, композиция без внешних ссылок."""

from __future__ import annotations

import io
import json
import sys
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

    def test_fixture_has_no_external_urls_and_no_gsap(self):
        self.assertEqual(montage_ci_check.external_urls(montage_ci_check.COMPOSITION), [])
        self.assertNotIn("gsap", montage_ci_check.COMPOSITION.lower())
        self.assertIn("data-no-timeline", montage_ci_check.COMPOSITION)

    def test_external_urls_also_catch_poster_srcset_and_bare_import(self):
        html = ('<video poster="https://cdn.example/poster.jpg"></video>'
                '<img srcset="https://cdn.example/x2.png 2x">'
                '<style>@import "https://fonts.googleapis.com/css2?family=Inter";</style>'
                '<img poster="assets/local.jpg" srcset="assets/local2.jpg 1x">')
        self.assertEqual(montage_ci_check.external_urls(html),
                         ["https://cdn.example/poster.jpg", "https://cdn.example/x2.png 2x",
                          "https://fonts.googleapis.com/css2?family=Inter"])


def _touch(path, *_args, **_kwargs) -> Path:
    """Заглушка make_clip/make_tone: юнит-тесты check() проверяют логику
    отчёта, а не настоящий ffmpeg — только создают файл на месте клипа."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


_FAKE_ENGINE = Engine(node="node", script=Path("hyperframes.mjs"), prefix=Path("/fake-prefix"),
                      version="9.9.9", browser=None)


class CiCheckReportTests(unittest.TestCase):
    """check(): каждая причина `problems` даёт `ok: False`, чистый прогон — `ok: True`
    (round 1/5, пункт 5 — раньше это проверял только настоящий движок в CI)."""

    def setUp(self):
        clip_patch = mock.patch.object(montage_testkit, "make_clip", side_effect=_touch)
        tone_patch = mock.patch.object(montage_testkit, "make_tone", side_effect=_touch)
        engine_patch = mock.patch.object(montage_ci_check, "require_engine",
                                         return_value=_FAKE_ENGINE)
        for patcher in (clip_patch, tone_patch, engine_patch):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _check(self, *, lint, probe, render_code=0, render_stdout="", render_stderr=""):
        def fake_render(engine, args, *, cwd, timeout):
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
        report = self._check(lint={"findings": [{"severity": "error", "code": "X1", "message": "beep"}]},
                             probe=self._clean_probe())
        self.assertIs(report["ok"], False)
        self.assertTrue(any(p.startswith("lint:") and "X1" in p and "beep" in p
                            for p in report["problems"]), report["problems"])

    def test_lint_internal_crash_fails(self):
        report = self._check(lint={"ok": False, "error": "boom", "findings": [], "errorCount": 0},
                             probe=self._clean_probe())
        self.assertIs(report["ok"], False)
        self.assertTrue(any(p.startswith("lint:") and "boom" in p for p in report["problems"]),
                        report["problems"])


if __name__ == "__main__":
    unittest.main()

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
from studio.montage import MontageError  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Вход service для экрана «Сборка»: фото без монтажа, стол через
переходник без pid и порта, «Сделать текущей» от имени человека, файл версии."""

from __future__ import annotations

import json
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

from montage_built import BuiltMontage  # noqa: E402
from montage_testkit import isolate_hyperframes_dir  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.service_screen import (  # noqa: E402
    current_output, desk_view, open_desk_for_screen, restore_as_owner, screen_model, screen_status)

STUDIO = "http://127.0.0.1:9/#project/current"
OPENER = "http://127.0.0.1:9/api/projects/current/preview/.hyperframes/aimaster-desk-open.html"
OPEN = {"state": "open", "url": STUDIO, "port": 9, "pid": 5, "started_at": "t"}


class ServiceScreenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name).resolve()
        isolate_hyperframes_dir(self, self.temp)
        self.m = BuiltMontage(self.temp)

    def status(self, desk_state):
        return screen_status(self.m.workspace, "p", locate=self.m.locate, desk_state=desk_state)

    def test_photo_project_has_no_montage(self):
        path = self.m.workspace / "projects" / "p" / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["project"]["type"] = "photo"
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        result = self.status(lambda paths: self.fail("фото-проекту стол не нужен"))
        self.assertEqual(result, {"project_id": "p", "revision": 0, "applicable": False})

    def test_desk_is_asked_only_when_there_is_a_draft(self):
        seen = []
        state = lambda paths: seen.append(paths) or {"state": "closed"}  # noqa: E731
        before = self.status(state)
        self.assertEqual((before["applicable"], before["desk"], seen), (True, {"state": "closed"}, []))
        self.m.draft()
        self.status(state)
        self.assertEqual(seen, [self.m.paths])

    def test_open_desk_is_shown_through_the_opener_without_pid_and_port(self):
        self.m.draft()
        self.assertEqual(self.status(lambda paths: dict(OPEN))["desk"],
                         {"state": "open", "url": OPENER, "telemetry_off": True})

    def test_desk_notes_pass_as_text_and_numbers_do_not(self):
        self.assertEqual(desk_view({"state": "closed", "note": "монтажный стол не отвечает", "pid": 3}),
                         {"state": "closed", "note": "монтажный стол не отвечает"})
        self.assertEqual(desk_view({"state": "busy"}), {"state": "busy"})

    def test_studio_address_without_project_keeps_the_flag_honest(self):
        self.assertEqual(desk_view({"state": "open", "url": "http://127.0.0.1:9/"}),
                         {"state": "open", "url": "http://127.0.0.1:9/", "telemetry_off": False})

    def test_model_uses_the_engine_from_locate(self):
        self.m.draft()
        model = screen_model(self.m.workspace, "p", locate=self.m.locate, runner=self.m.runner)
        self.assertEqual(len(model["layers"]), 6)

    def test_open_desk_for_screen_returns_the_view_and_the_montage_folder(self):
        self.m.draft()
        desk = mock.Mock()
        desk.open.return_value = dict(OPEN)
        view, paths = open_desk_for_screen(self.m.workspace, "p", desk=desk)
        self.assertEqual(view, {"project_id": "p", "state": "open", "url": OPENER, "telemetry_off": True})
        self.assertEqual(paths, self.m.paths)

    def test_restore_from_the_screen_is_written_as_the_person(self):
        self.m.draft_and_build()
        self.assertEqual(restore_as_owner(self.m.workspace, "p", 2, "v001"),
                         {"project_id": "p", "revision": 3, "current_version": "v001"})
        last = self.m.state()["history"][-1]
        self.assertEqual((last["actor"], last["kind"], last["params"]["target_id"]),
                         ("you", "montage-restored", "v001"))

    def test_current_output_is_the_mp4_of_the_current_version(self):
        self.m.draft_and_build()
        target, shown = current_output(self.m.workspace, "p")
        self.assertEqual(target, self.m.seed.media / "p" / "montage" / "v001.mp4")
        self.assertTrue(target.is_file())
        self.assertEqual(shown, "рабочая папка/media/p/montage/v001.mp4")

    def test_nothing_to_reveal_before_the_first_build(self):
        self.m.draft()
        with self.assertRaisesRegex(MontageError, "ещё не собран"):
            current_output(self.m.workspace, "p")

    def test_missing_file_is_named_without_an_absolute_path(self):
        self.m.draft_and_build()
        (self.m.seed.media / "p" / "montage" / "v001.mp4").unlink()
        with self.assertRaises(MontageError) as caught:
            current_output(self.m.workspace, "p")
        self.assertIn("media/p/montage", str(caught.exception))
        self.assertNotIn(str(self.temp), str(caught.exception))


if __name__ == "__main__":
    unittest.main()

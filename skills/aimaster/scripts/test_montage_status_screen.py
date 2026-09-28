#!/usr/bin/env python3
"""Состояние монтажа для экрана «Сборка»: дешёвая часть без движка и без
схемы, схема слоёв — отдельно и только по запросу."""

from __future__ import annotations

import hashlib
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

from montage_built import BuiltMontage  # noqa: E402
from montage_testkit import FakeHyperframes, isolate_hyperframes_dir  # noqa: E402
from studio.montage import MontageError, service  # noqa: E402
from studio.montage.context import open_context  # noqa: E402
from studio.montage.edit import EditRequest  # noqa: E402
from studio.montage.index_io import read_index  # noqa: E402
from studio.montage.status_screen import cheap_status, index_key, model_status  # noqa: E402

LAYERS = ["video", "titles", "voice", "music", "fx", "atmos"]


class _TimelineBroken(FakeHyperframes):
    def json(self, engine, args, *, cwd, timeout, ok_codes=(0,)):
        if list(args) == ["timeline", "--json"]:
            raise MontageError("HyperFrames «timeline --json» завершился с кодом 1: сломано")
        return super().json(engine, args, cwd=cwd, timeout=timeout, ok_codes=ok_codes)


class StatusScreenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name).resolve()
        isolate_hyperframes_dir(self, self.temp)
        self.m = BuiltMontage(self.temp)

    def ctx(self):
        return open_context(self.m.workspace, "p")

    def test_before_the_draft_there_is_nothing_yet(self):
        status = cheap_status(self.ctx(), self.m.engine, "")
        self.assertEqual((status["exists"], status["current_version"], status["canvas"],
                          status["index_key"], status["file"], status["unrendered_changes"]),
                         (False, None, None, None, None, None))
        self.assertEqual(status["engine"], {"state": "installed", "version": "0.8.75", "reason": ""})
        self.assertEqual((status["project_id"], status["revision"]), ("p", 0))

    def test_index_key_follows_the_text_of_index_html(self):
        self.m.draft()
        text = read_index(self.m.paths.index)
        status = cheap_status(self.ctx(), self.m.engine, "")
        self.assertEqual(status["index_key"], hashlib.sha256(text.encode("utf-8")).hexdigest()[:16])
        self.assertEqual(status["index_key"], index_key(text))
        self.assertEqual(status["canvas"], {"width": 108, "height": 192})

    def test_unrendered_flag_comes_only_from_the_model_cache(self):
        self.m.draft()
        self.assertIsNone(cheap_status(self.ctx(), self.m.engine, "")["unrendered_changes"])
        before = len(self.m.runner.calls)
        self.assertIs(model_status(self.ctx(), self.m.engine, runner=self.m.runner)["unrendered_changes"], True)
        self.assertEqual(len(self.m.runner.calls), before + 1)  # один timeline --json
        self.assertIs(cheap_status(self.ctx(), self.m.engine, "")["unrendered_changes"], True)
        self.assertEqual(len(self.m.runner.calls), before + 1)  # дешёвая часть движок не зовёт

    def test_after_a_build_the_file_is_shown_from_above_the_workspace(self):
        built = self.m.draft_and_build()
        status = cheap_status(self.ctx(), self.m.engine, "")
        self.assertEqual((status["current_version"], built["version"]), ("v001", "v001"))
        self.assertEqual(status["file"], {"version": "v001", "shown": "рабочая папка/media/p/montage/v001.mp4"})
        self.assertIs(status["unrendered_changes"], False)  # сборка сама положила модель в кэш
        self.assertNotIn(str(self.temp), json.dumps(status, ensure_ascii=False))

    def test_missing_mp4_is_no_file_but_still_the_version(self):
        self.m.draft_and_build()
        (self.m.seed.media / "p" / "montage" / "v001.mp4").unlink()
        self.assertEqual(cheap_status(self.ctx(), self.m.engine, "")["file"],
                         {"version": "v001", "shown": None})

    def test_without_engine_versions_and_file_are_still_there(self):
        self.m.draft_and_build()
        status = cheap_status(self.ctx(), None, "не найден Node.js")
        self.assertEqual(status["engine"], {"state": "missing", "version": None, "reason": "не найден Node.js"})
        self.assertIsNone(status["unrendered_changes"])
        self.assertEqual(status["file"]["version"], "v001")
        model = model_status(self.ctx(), None)
        self.assertEqual((model["layers"], model["model_hash"], model["stale_clips"], model["model_error"]),
                         ([], None, [], None))

    def test_model_part_has_six_layers_and_follows_edits(self):
        self.m.draft_and_build()
        first = model_status(self.ctx(), self.m.engine, runner=self.m.runner)
        self.assertEqual([layer["layer"] for layer in first["layers"]], LAYERS)
        self.assertIs(first["unrendered_changes"], False)
        service.edit(self.m.workspace, "p", 2, EditRequest(op="trim-start", clip="v-1", seconds=0.5),
                     engine=self.m.engine, runner=self.m.runner)
        second = model_status(self.ctx(), self.m.engine, runner=self.m.runner)
        self.assertNotEqual(second["index_key"], first["index_key"])
        self.assertIs(second["unrendered_changes"], True)

    def test_model_part_before_the_draft_is_empty(self):
        model = model_status(self.ctx(), self.m.engine, runner=self.m.runner)
        self.assertEqual((model["index_key"], model["layers"], model["stale_clips"]), (None, [], []))

    def test_engine_failure_is_text_and_stale_part_stays(self):
        self.m.draft()
        model = model_status(self.ctx(), self.m.engine, runner=_TimelineBroken())
        self.assertIn("timeline --json", model["model_error"])
        self.assertEqual((model["layers"], model["stale_clips"], model["stale_error"]), ([], [], None))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Вход service: полный цикл черновик → сборка → правка → diff → сборка → возврат, без движка — понятный отказ."""

from __future__ import annotations

import os
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

from montage_testkit import (FakeHyperframes, fake_engine, fake_gsap_prefix,  # noqa: E402
                             seed_workspace, tiny_mp4, tiny_wav, video_state)
from studio.authoring_support import open_assets, open_store  # noqa: E402
from studio.montage import MontageError, service, service_versions  # noqa: E402
from studio.montage.edit import EditRequest  # noqa: E402
from studio.montage.engine import PREFIX_ENV  # noqa: E402
from studio.montage.index_io import read_index, write_index  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import MediaInfo  # noqa: E402
from studio.montage.version_staging import build_lock  # noqa: E402
from studio.store import RevisionConflict  # noqa: E402

GSAP_FILES = ("gsap", "MotionPathPlugin", "SplitText")


class _TimelineBroken(FakeHyperframes):
    def json(self, engine, args, *, cwd, timeout, ok_codes=(0,)):
        if list(args) == ["timeline", "--json"]:
            raise MontageError("HyperFrames «timeline --json» завершился с кодом 1: сломано")
        return super().json(engine, args, cwd=cwd, timeout=timeout, ok_codes=ok_codes)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name).resolve()
        # кеш скиллов — в пустой временной папке: реальный HOME тесты не читают
        environ = mock.patch.dict(os.environ, {PREFIX_ENV: str(self.temp / "tools" / "hyperframes")})
        environ.start()
        self.addCleanup(environ.stop)
        files = {"a.mp4": tiny_mp4(b"a"), "b.mp4": tiny_mp4(b"b"), "c.mp4": tiny_mp4(b"c"),
                 "v.wav": tiny_wav()}
        self.seed = seed_workspace(self.temp, files, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"]),
             ("s2", "Клубок", "Находит клубок", 2000, ids["b.mp4"])], audio={"voice": ids["v.wav"]}))
        self.ws = self.seed.workspace
        self.infos = {"a.mp4": MediaInfo(2.0, 108, 192, True, True),
                      "b.mp4": MediaInfo(1.5, 108, 192, True, False),
                      "c.mp4": MediaInfo(1.0, 108, 192, True, True),
                      "v.wav": MediaInfo(5.0, None, None, False, True)}
        self.engine = fake_engine(fake_gsap_prefix(self.temp, files=GSAP_FILES))
        self.runner = FakeHyperframes(render_bytes=tiny_mp4(b"out-1"))
        self.paths = montage_paths(self.ws / "projects" / "p")

    def probe(self, path):
        return self.infos.get(Path(path).name, MediaInfo(3.5, 108, 192, True, True))

    def kw(self, probe=False):
        extra = {"probe": self.probe} if probe else {}
        return {"engine": self.engine, "runner": self.runner, **extra}

    def status(self, runner=None):
        return service.status(self.ws, "p", locate=lambda: (self.engine, ""), runner=runner or self.runner)

    def test_full_cycle(self):
        drafted = service.draft(self.ws, "p", 0, **self.kw(probe=True))
        self.assertEqual((drafted["revision"], drafted["canvas"], drafted["clips"]),
                         (1, {"width": 108, "height": 192}, 3))
        self.assertEqual(drafted["skills"]["status"], "missing")
        status = self.status()
        self.assertEqual((status["exists"], status["unrendered_changes"], status["engine"]["state"],
                          status["engine"]["install"]), (True, True, "installed", None))
        self.assertEqual([layer["layer"] for layer in status["layers"]][:3], ["video", "titles", "voice"])
        self.assertIsNone(status["paths"]["output"])
        first = service.render(self.ws, "p", 1, **self.kw(probe=True))
        self.assertEqual((first["version"], first["revision"], first["project_id"]), ("v001", 2, "p"))
        self.assertIs(self.status()["unrendered_changes"], False)
        service.edit(self.ws, "p", 2, EditRequest(op="trim-start", clip="v-1", seconds=0.5), **self.kw())
        diff = service.diff(self.ws, "p", **self.kw())
        self.assertEqual((diff["base"], diff["changes"], diff["unrendered_changes"]),
                         ("v001", ["клип сцены 1 «Сад»: начало обрезано на 0,5 с"], True))
        self.runner.render_bytes = tiny_mp4(b"out-2")
        second = service.render(self.ws, "p", 2, **self.kw(probe=True))
        self.assertEqual(second["version"], "v002")
        restored = service.restore(self.ws, "p", 3, "v001")
        self.assertEqual((restored["current_version"], restored["revision"]), ("v001", 4))
        status = self.status()
        self.assertEqual((status["current_version"], status["unrendered_changes"]), ("v001", False))
        self.assertTrue(status["paths"]["output"].endswith("v001.mp4"))
        state = open_store(self.ws).load("p")
        self.assertEqual(state["assembly"]["asset_id"], first["asset_id"])
        self.assertEqual([h["kind"] for h in state["history"]],
                         ["montage-drafted", "montage-built", "montage-built", "montage-restored"])

    def test_every_engine_call_carries_json(self):
        # Без --json движок на каждом запуске ходит за обновлениями (engine_cli.argv_for):
        # и lint/timeline, и правки, и сама сборка передают его явно.
        drafted = service.draft(self.ws, "p", 0, **self.kw(probe=True))
        for request in (EditRequest(op="move", clip="v-2", at=2.5),
                        EditRequest(op="trim-start", clip="v-1", seconds=0.5),
                        EditRequest(op="trim-end", clip="v-1", duration=1.0),
                        EditRequest(op="split", clip="a-voice", at=1.0),
                        EditRequest(op="volume", clip="a-voice", value=0.5),
                        EditRequest(op="fade", clip="a-voice", fade_in=0.2),
                        EditRequest(op="title-add", text="Барсик", at=0.2, duration=1.0),
                        EditRequest(op="delete", clip="t-1")):
            service.edit(self.ws, "p", drafted["revision"], request, **self.kw())
        service.diff(self.ws, "p", **self.kw())
        self.infos["v001.mp4"] = MediaInfo(self.status()["duration"], 108, 192, True, True)
        service.render(self.ws, "p", drafted["revision"], **self.kw(probe=True))
        commands = {call[0] if call[0] != "timeline" or len(call) < 3 else call[1] for call in self.runner.calls}
        self.assertTrue({"lint", "render", "move", "trim", "split", "set", "delete"} <= commands, commands)
        self.assertEqual([call for call in self.runner.calls if "--json" not in call], [])

    def test_status_without_engine_still_answers(self):
        status = service.status(self.ws, "p", locate=lambda: (None, "не найден Node.js"))
        self.assertEqual((status["engine"]["state"], status["engine"]["reason"], status["exists"]),
                         ("missing", "не найден Node.js", False))
        self.assertEqual((status["current_version"], status["versions"], status["desk"]),
                         (None, [], {"state": "closed"}))
        self.assertIn("--install-deps", status["engine"]["install"])
        self.assertEqual(status["skills"]["status"], "missing")
        self.assertEqual((status["model_hash"], status["duration"], status["unrendered_changes"],
                          status["layers"]), (None, None, None, []))

    def test_status_answers_even_when_the_engine_cannot_read_the_montage(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        status = self.status(runner=_TimelineBroken())
        self.assertIn("сломано", status["model_error"])
        self.assertEqual((status["exists"], status["layers"], status["model_hash"]), (True, [], None))
        self.assertIsNone(self.status()["model_error"])

    def test_status_answers_with_a_corrupt_snapshot_and_a_broken_scene(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        service.render(self.ws, "p", 1, **self.kw(probe=True))
        (self.paths.version_dir("v001") / "meta.json").write_text("не json", encoding="utf-8")
        status = self.status()
        self.assertEqual((status["current_version"], status["unrendered_changes"]), ("v001", True))
        store = open_store(self.ws)
        store.transact("p", 2, lambda state: state["scenes"][0].pop("scene_id"))
        status = self.status()
        self.assertIn("у сцены нет scene_id", status["stale_error"])
        self.assertEqual((status["stale_clips"], status["exists"]), ([], True))

    def test_draft_without_engine_refuses_and_writes_nothing(self):
        with mock.patch.object(service, "require_engine",
                               side_effect=MontageError("Монтажный движок не готов: не найден Node.js")):
            with self.assertRaises(MontageError):
                service.draft(self.ws, "p", 0, probe=self.probe)
        self.assertFalse((self.ws / "projects" / "p" / "montage").exists())

    def test_draft_whose_state_write_fails_leaves_no_draft(self):
        with mock.patch.object(service, "record_draft", side_effect=RevisionConflict(0, 1)):
            with self.assertRaises(RevisionConflict):
                service.draft(self.ws, "p", 0, **self.kw(probe=True))
        self.assertFalse(self.paths.index.exists())
        service.draft(self.ws, "p", 0, **self.kw(probe=True))  # повтор не упирается в «черновик уже есть»

    def test_failed_state_write_keeps_a_concurrent_edit_of_the_draft(self):
        def studio_edits_then_state_refuses(*args, **kwargs):
            write_index(self.paths.index, "<html>правка из стола</html>")
            raise RevisionConflict(0, 1)
        with mock.patch.object(service, "record_draft", side_effect=studio_edits_then_state_refuses):
            with self.assertRaises(MontageError) as caught:
                service.draft(self.ws, "p", 0, **self.kw(probe=True))
        self.assertIn("тем временем поменяли", str(caught.exception))
        self.assertEqual(read_index(self.paths.index), "<html>правка из стола</html>")

    def test_failed_restore_record_puts_back_only_its_own_write(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        service.render(self.ws, "p", 1, **self.kw(probe=True))
        service.edit(self.ws, "p", 2, EditRequest(op="delete", clip="v-2"), **self.kw())
        edited = read_index(self.paths.index)
        with mock.patch.object(service_versions, "record_restore", side_effect=RevisionConflict(2, 3)):
            with self.assertRaises(RevisionConflict):
                service.restore(self.ws, "p", 2, "v001")
        self.assertEqual(read_index(self.paths.index), edited)  # своя запись снимка отменена

        def studio_edits_then_state_refuses(*args, **kwargs):
            write_index(self.paths.index, "<html>правка из стола</html>")
            raise RevisionConflict(2, 3)
        with mock.patch.object(service_versions, "record_restore", side_effect=studio_edits_then_state_refuses):
            with self.assertRaises(MontageError) as caught:
                service.restore(self.ws, "p", 2, "v001")
        self.assertIn("тем временем поменяли", str(caught.exception))
        self.assertEqual(read_index(self.paths.index), "<html>правка из стола</html>")

    def test_stale_revision_is_refused(self):
        with self.assertRaises(RevisionConflict) as caught:
            service.draft(self.ws, "p", 5, **self.kw(probe=True))
        self.assertEqual(str(caught.exception), "проект изменился — обновите номер ревизии: сейчас 0")
        self.assertEqual((caught.exception.expected_revision, caught.exception.current_revision), (5, 0))

    def test_unknown_draft_mode_is_refused(self):
        with self.assertRaises(MontageError):
            service.draft(self.ws, "p", 0, mode="всё сразу", **self.kw(probe=True))

    def test_refresh_after_a_new_scene_video(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        store = open_store(self.ws)

        def new_video(state):
            for item in state["video_results"]:
                if item["scene_id"] == "s2":
                    item["asset_id"] = self.seed.ids["c.mp4"]
        store.transact("p", 1, new_video)
        stale = self.status()["stale_clips"]
        self.assertEqual([item["clip"] for item in stale], ["v-2"])
        self.assertEqual({key: stale[0][key] for key in ("reason", "cause", "audio_change")},
                         {"reason": None, "cause": None, "audio_change": None})
        refreshed = service.draft(self.ws, "p", 2, mode="refresh", **self.kw(probe=True))
        self.assertEqual([item["clip"] for item in refreshed["refreshed"]], ["v-2"])
        self.assertEqual(refreshed["refreshed"][0]["audio_change"], "добавился звук")
        self.assertEqual(refreshed["not_refreshed"], [])
        self.assertEqual(self.status()["stale_clips"], [])

    def test_refresh_does_not_claim_structural_items(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        store = open_store(self.ws)

        def add_scene(state):
            state["scenes"].append({**state["scenes"][-1], "scene_id": "s3", "order": 3,
                                    "start_ms": 4000, "end_ms": 6000, "links": {}})
        store.transact("p", 1, add_scene)
        refreshed = service.draft(self.ws, "p", 2, mode="refresh", **self.kw(probe=True))
        self.assertEqual(refreshed["refreshed"], [])
        self.assertEqual([(item["cause"], item["reason"]) for item in refreshed["not_refreshed"]],
                         [("scene_added", "нужен --rebuild")])

    def test_rebuild_keeps_the_edited_draft_as_backup(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        service.edit(self.ws, "p", 1, EditRequest(op="delete", clip="v-2"), **self.kw())
        rebuilt = service.draft(self.ws, "p", 1, mode="rebuild", **self.kw(probe=True))
        self.assertEqual(rebuilt["revision"], 2)
        self.assertNotIn('id="v-2"', Path(rebuilt["backup"]).read_text(encoding="utf-8"))
        video = next(layer for layer in self.status()["layers"] if layer["layer"] == "video")
        self.assertEqual([clip["id"] for clip in video["clips"]], ["v-1", "v-2"])

    def test_gsap_is_copied_from_the_engine_folder(self):
        bare = fake_engine(self.temp / "движок без gsap")
        with self.assertRaises(MontageError) as caught:
            service.gsap(self.ws, "p", engine=bare)
        self.assertIn("engine.install в ответе montage status", str(caught.exception))
        with self.assertRaises(MontageError) as caught:
            service.gsap(self.ws, "p", engine=self.engine)
        self.assertIn("черновика ещё нет", str(caught.exception))
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        self.assertEqual(service.gsap(self.ws, "p", engine=self.engine)["copied"], [])  # черновик уже положил
        result = service.gsap(self.ws, "p", plugins=["SplitText"], engine=self.engine)
        self.assertEqual(result["files"], ["assets/gsap.min.js", "assets/MotionPathPlugin.min.js",
                                           "assets/SplitText.min.js"])
        self.assertEqual(result["copied"], ["assets/SplitText.min.js"])
        self.assertEqual(result["script_tags"][0], '<script src="assets/gsap.min.js"></script>')
        self.assertEqual(result["missing_tags"], ['<script src="assets/SplitText.min.js"></script>'])
        self.assertTrue(any('__timelines["main"]' in rule for rule in result["rules"]))
        split = self.paths.current / "assets" / "SplitText.min.js"
        self.assertEqual(split.read_text(encoding="utf-8"), "/* SplitText */\n")
        for bad in ("../evil", "Нет", "Flip"):
            with self.assertRaises(MontageError):
                service.gsap(self.ws, "p", plugins=[bad], engine=self.engine)

    def test_diff_against_a_version_and_a_lost_snapshot(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        with self.assertRaises(MontageError):
            service.diff(self.ws, "p", against="v001", **self.kw())
        with self.assertRaises(MontageError):
            service.diff(self.ws, "p", against="../v001", **self.kw())
        service.render(self.ws, "p", 1, **self.kw(probe=True))
        self.assertEqual(service.diff(self.ws, "p", against="v001", **self.kw())["changes"], [])
        self.paths.version_dir("v001").rename(self.paths.versions / "потерян")
        diff = service.diff(self.ws, "p", **self.kw())
        self.assertIn("не с чем", diff["changes"][0])
        self.assertIs(diff["unrendered_changes"], True)

    def test_restore_unknown_version(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        with self.assertRaises(MontageError):
            service.restore(self.ws, "p", 1, "v009")
        self.assertIsNotNone(open_assets(self.ws))

    def test_restore_waits_for_no_build(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        service.render(self.ws, "p", 1, **self.kw(probe=True))
        with build_lock(self.paths):
            with self.assertRaises(MontageError) as caught:
                service.restore(self.ws, "p", 2, "v001")
        self.assertIn("уже идёт", str(caught.exception))

    def test_desk_goes_through_the_desk_interface(self):
        service.draft(self.ws, "p", 0, **self.kw(probe=True))
        desk = mock.Mock()
        desk.open.return_value = {"state": "open", "url": "http://127.0.0.1:1/", "port": 1, "pid": 2,
                                  "started_at": "t"}
        desk.close.return_value = {"state": "closed"}
        self.assertEqual(service.open_desk(self.ws, "p", desk=desk)["url"], "http://127.0.0.1:1/")
        self.assertEqual(service.close_desk(self.ws, "p", desk=desk), {"project_id": "p", "state": "closed"})
        self.assertEqual(desk.open.call_args.args[0], self.paths)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Сквозной монтаж на настоящем HyperFrames: черновик (скиллы — в рабочую папку) →
v001 → обрезка и кириллический титр → diff → v002 → чужой шрифт отклонён без версии →
GSAP в assets → возврат к v001 → монтажный стол открыт и закрыт.

Движок — тот, что находит engine.locate(); без него тест пропускается, а с
AIMASTER_REQUIRE_ENGINE=1 (CI после установки движка) падает. В общую папку
движка тест не пишет: у него своя папка движка во временной папке (HOME движка,
кэш кадров и шрифтов, копия GSAP), скрипт движка и браузер берутся из общей
только на чтение. Сборки ждут своего конца, стол закрывается в addCleanup —
после теста не остаётся ни одного запущенного им процесса."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import make_clip, make_tone, seed_workspace, video_state  # noqa: E402
from studio.montage import MontageError, engine, service  # noqa: E402
from studio.montage.desk_identity import fetch_config  # noqa: E402
from studio.montage.edit import EditRequest  # noqa: E402
from studio.montage.html_doc import element_attrs, insert_before_root_end  # noqa: E402
from studio.montage.index_io import read_index, write_index  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.probe import probe_media  # noqa: E402
from studio.montage.proc import process_alive  # noqa: E402
from studio.platform_compat import find_program  # noqa: E402

REQUIRE_ENV = "AIMASTER_REQUIRE_ENGINE"
FOREIGN_FONT = ('<div id="t-9" class="clip" data-start="0.2" data-duration="1" data-track-index="1" '
                'data-am-layer="titles" style="font-family: Roboto; color: #fff; font-size: 40px">Барсик</div>')


def _required() -> bool:
    return os.environ.get(REQUIRE_ENV) == "1"


def own_engine(found: engine.Engine, root: Path) -> engine.Engine:
    """Найденный движок со своей папкой: всё, что движок пишет (HOME, кэши), — сюда."""

    prefix = root / "движок"
    shutil.copytree(found.prefix / "node_modules" / "gsap", prefix / "node_modules" / "gsap")
    return engine.Engine(node=found.node, script=found.script, prefix=prefix, version=found.version,
                         browser=found.browser)


def frame_md5(path: Path, at: float) -> str:
    proc = subprocess.run([find_program("ffmpeg"), "-v", "error", "-ss", str(at), "-i", str(path),
                           "-frames:v", "1", "-f", "md5", "-"], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, check=True, timeout=120)
    return proc.stdout.strip()


class RealEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.found, reason = engine.locate()
        missing = (f"монтажный движок не установлен: {reason}" if cls.found is None
                   else "нужны ffmpeg и ffprobe" if not (find_program("ffmpeg") and find_program("ffprobe"))
                   else None)
        if missing:
            if _required():
                raise AssertionError(missing)
            raise unittest.SkipTest(missing)

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="aimaster-e2e-", ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name) / "проверка монтажа"
        self.eng = own_engine(self.found, Path(temp.name))
        self.kw = {"engine": self.eng}

    def _seed(self) -> Path:
        sources = self.base / "исходники"
        files = {
            "a.mp4": make_clip(sources / "a.mp4", 2.0, size=(540, 960), color="red", freq=440).read_bytes(),
            "b.mp4": make_clip(sources / "b.mp4", 1.0, size=(540, 960), color="blue", freq=660).read_bytes(),
            "v.wav": make_tone(sources / "v.wav", 3.0).read_bytes(),
        }
        return seed_workspace(self.base, files, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"]),
             ("s2", "Клубок", "Находит клубок", 1000, ids["b.mp4"])],
            audio={"voice": ids["v.wav"]})).workspace

    def _status(self, ws) -> dict:
        return service.status(ws, "p", locate=lambda: (self.eng, ""))

    def _check_draft(self, ws, drafted, text):
        self.assertEqual((drafted["canvas"], drafted["duration"], drafted["clips"]),
                         ({"width": 540, "height": 960}, 3.0, 3))
        root = element_attrs(text)["root"]
        self.assertNotIn("data-no-timeline", root)
        self.assertEqual((root["data-am-scenes"], root["data-am-layers"]), ("s1 s2", "voice"))
        self.assertEqual(text.count('window.__timelines["main"] ='), 1)
        self.assertIn('<script src="assets/MotionPathPlugin.min.js"></script>', text)
        self.assertNotIn('data-am-layer="titles"', text)
        if drafted["skills"]["status"] == "missing" and not _required():
            return  # движок есть, а кеша скиллов нет — рабочей папке нечего копировать
        self.assertEqual(drafted["skills"]["status"], "installed")
        for parts in ((".claude", "skills"), (".agents", "skills")):
            skill = ws.joinpath(*parts, "hyperframes")
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertTrue((skill / ".aimaster-install.json").is_file())

    def _render(self, ws, revision) -> dict:
        built = service.render(ws, "p", revision, **self.kw)
        info = probe_media(Path(built["path"]))
        self.assertAlmostEqual(info.duration, 3.0, delta=0.1)
        self.assertEqual((info.width, info.height, info.has_audio), (540, 960, True))
        self.assertEqual(built["warnings"], [])
        return built

    def _edit(self, ws, revision):
        service.edit(ws, "p", revision, EditRequest(op="trim-start", clip="v-1", seconds=0.5), **self.kw)
        added = service.edit(ws, "p", revision, EditRequest(op="title-add", text="Ёжик и кот: проверка",
                                                            at=0.5, duration=2.0), **self.kw)
        self.assertEqual(added["receipt"]["new_clip"], "t-1")
        status = self._status(ws)
        video = next(layer for layer in status["layers"] if layer["layer"] == "video")
        self.assertEqual((video["clips"][0]["start"], video["clips"][0]["media_start"]), (0.5, 0.5))
        titles = next(layer for layer in status["layers"] if layer["layer"] == "titles")
        self.assertEqual([clip["text"] for clip in titles["clips"]], ["Ёжик и кот: проверка"])
        self.assertIs(status["unrendered_changes"], True)
        return ["добавлен титр «Ёжик и кот: проверка» с 0:00.5",
                "клип сцены 1 «Сад»: начало обрезано на 0,5 с"]

    def _foreign_font_refused(self, ws, paths, revision):
        write_index(paths.index, insert_before_root_end(read_index(paths.index), FOREIGN_FONT))
        with self.assertRaises(MontageError) as caught:
            service.render(ws, "p", revision, **self.kw)
        message = str(caught.exception)
        self.assertIn("обращалась в сеть или к чужому шрифту", message)
        for folder in (ws, self.eng.prefix):
            self.assertNotIn(str(folder), message)
        self.assertEqual([item["id"] for item in self._status(ws)["versions"]], ["v001", "v002"])
        self.assertFalse((ws / "media" / "p" / "montage" / "v003.mp4").exists())

    def _gsap(self, ws, paths):
        vendored = service.gsap(ws, "p", **self.kw)
        self.assertEqual((vendored["version"], vendored["files"], vendored["copied"], vendored["missing_tags"]),
                         ("3.14.2", ["assets/gsap.min.js", "assets/MotionPathPlugin.min.js"], [], []))
        self.assertGreater((paths.assets / "gsap.min.js").stat().st_size, 10_000)
        plugin = service.gsap(ws, "p", plugins=["SplitText"], **self.kw)
        self.assertEqual((plugin["copied"], plugin["missing_tags"]),
                         (["assets/SplitText.min.js"], ['<script src="assets/SplitText.min.js"></script>']))

    def _desk(self, ws):
        desk = service.open_desk(ws, "p", **self.kw)
        self.addCleanup(service.close_desk, ws, "p")
        self.assertTrue(desk["url"].startswith(f"http://127.0.0.1:{desk['port']}/"))
        config = fetch_config(desk["port"], timeout=10) or {}
        self.assertEqual((config.get("isHyperframes"), config.get("pid")), (True, desk["pid"]))
        self.assertEqual(self._status(ws)["desk"]["state"], "open")
        self.assertEqual(service.close_desk(ws, "p")["state"], "closed")
        deadline = time.monotonic() + 15
        while process_alive(desk["pid"]) and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertFalse(process_alive(desk["pid"]), "монтажный стол пережил montage close")
        self.assertEqual(self._status(ws)["desk"], {"state": "closed"})

    def test_draft_render_edit_diff_restore_desk(self):
        ws = self._seed()
        drafted = service.draft(ws, "p", 0, **self.kw)
        paths = montage_paths(ws.resolve() / "projects" / "p")
        self._check_draft(ws, drafted, read_index(paths.index))
        first = self._render(ws, drafted["revision"])
        self.assertEqual((first["version"], first["changes"]), ("v001", ["черновой монтаж: 3 клипа, 3,0 с"]))
        changes = self._edit(ws, first["revision"])
        self.assertEqual(service.diff(ws, "p", **self.kw)["changes"], changes)
        second = self._render(ws, first["revision"])  # титр кириллицей — своим шрифтом, без сети
        self.assertEqual((second["version"], second["changes"]), ("v002", changes))
        self.assertNotEqual(frame_md5(Path(second["path"]), 1.0), frame_md5(Path(first["path"]), 1.0))
        self._foreign_font_refused(ws, paths, second["revision"])
        self._gsap(ws, paths)
        restored = service.restore(ws, "p", second["revision"], "v001")
        self.assertEqual(restored["current_version"], "v001")
        status = self._status(ws)
        self.assertEqual((status["current_version"], status["unrendered_changes"]), ("v001", False))
        self.assertEqual(Path(status["paths"]["output"]).name, "v001.mp4")
        self._desk(ws)


if __name__ == "__main__":
    unittest.main()

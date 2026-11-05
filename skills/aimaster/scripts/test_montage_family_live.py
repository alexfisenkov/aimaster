"""Actual HyperFrames, pointer editing/save/reopen, export and relocated render."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS.parent))
from montage_testkit import make_clip, make_tone, seed_workspace, video_state
from test_montage_e2e import own_engine
from studio.montage import service
from studio.montage.engine import locate
from studio.montage.engine_cli import EngineRunner
from studio.montage.model import read_model
from studio.montage.paths import montage_paths
from studio.montage.probe import probe_media
from studio.montage.render_run import render_args
from studio.platform_compat import find_program


class FamilyLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.found, reason = locate()
        if not cls.found or not find_program("ffmpeg") or not find_program("ffprobe"):
            if os.environ.get("AIMASTER_REQUIRE_ENGINE") == "1":
                raise AssertionError(reason or "ffmpeg/ffprobe missing")
            raise unittest.SkipTest(reason or "ffmpeg/ffprobe missing")

    def test_style_desk_save_export_and_relocated_render(self):
        with tempfile.TemporaryDirectory(prefix="aimaster-family-engine-") as temporary:
            root = Path(temporary).resolve()
            eng = own_engine(self.found, root)
            files = {"a.mp4": make_clip(root / "a.mp4", 2, size=(108, 192), color="red").read_bytes(),
                     "b.mp4": make_clip(root / "b.mp4", 1, size=(108, 192), color="blue").read_bytes(),
                     "voice.wav": make_tone(root / "voice.wav", 4).read_bytes()}
            ws = seed_workspace(root, files, lambda ids: video_state([
                ("s1", "First", "Cinematic", 2000, ids["a.mp4"]),
                ("s2", "Second", "Product", 1000, ids["b.mp4"])],
                audio={"voice": ids["voice.wav"]})).workspace
            first = service.build(ws, "p", 0, style="cinematic", engine=eng)
            self.assertEqual((first["version"], first["duration"]), ("v001", 3))
            preview = service.preview(ws, "p", style="dynamic", duration=2, engine=eng)
            self.assertAlmostEqual(probe_media(Path(preview["path"])).duration, 2, delta=.1)
            self.assertTrue(service.preview(ws, "p", style="dynamic", duration=2, engine=eng)["reused"])
            desk = service.open_desk(ws, "p", engine=eng)
            try:
                config = root / "browser.json"
                config.write_text(json.dumps({"modules": str(self.found.prefix / "node_modules"),
                    "browser": eng.browser, "profile": str(root / "browser-profile"),
                    "pidFile": str(root / "browser.pid"), "href": desk["opener_url"],
                    "indexPath": str(montage_paths(ws / "projects" / "p").index)}), encoding="utf-8")
                check = subprocess.run([eng.node, str(SCRIPTS / "montage_family_desk.mjs"), str(config)],
                                       capture_output=True, text=True, encoding="utf-8", timeout=180)
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr[-2000:])
                self.assertTrue(all(item["ok"] for item in json.loads(check.stdout.strip())))
            finally:
                service.close_desk(ws, "p")
            second = service.render(ws, "p", first["revision"], by="owner", engine=eng)
            self.assertEqual(second["version"], "v002")
            self.assertAlmostEqual(second["duration"], 3.5, delta=.1)
            self.assertTrue(Path(first["path"]).is_file())
            service.export(ws, "p", destination=root / "delivery")
            moved = root / "relocated delivery"
            (root / "delivery").rename(moved)
            shutil.rmtree(ws)
            service.verify_export(moved / "manifest.json")
            composition = moved / "editable"
            model = read_model(eng, composition)
            self.assertAlmostEqual(model.clip("v-2").start, 2.5)
            output = moved / "rendered-again.mp4"
            result = EngineRunner().run(eng, render_args(eng, output), cwd=composition, timeout=120)
            self.assertEqual(result.code, 0, result.stderr[-2000:])
            self.assertAlmostEqual(probe_media(output).duration, 3.5, delta=.1)


if __name__ == "__main__":
    unittest.main()

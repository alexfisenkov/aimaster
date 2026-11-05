"""Real SVG pixels, Studio pointer save/reopen and relocated overlay rendering."""
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
from montage_testkit import make_clip, seed_workspace, video_state
from test_montage_e2e import own_engine
from studio.montage import service
from studio.montage.engine import locate
from studio.montage.engine_cli import EngineRunner
from studio.montage.model import read_model
from studio.montage.paths import montage_paths
from studio.montage.render_run import render_args
from studio.platform_compat import find_program


def pixel(path, second, x, y):
    result = subprocess.run([find_program("ffmpeg"), "-v", "error", "-ss", str(second), "-i", str(path),
                             "-frames:v", "1", "-vf", f"crop=2:2:{x}:{y},scale=1:1",
                             "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                            capture_output=True, check=True, timeout=30)
    return tuple(result.stdout[:3])


class OverlayLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.found, reason = locate()
        if not cls.found or not find_program("ffmpeg") or not find_program("ffprobe"):
            if os.environ.get("AIMASTER_REQUIRE_ENGINE") == "1":
                raise AssertionError(reason or "ffmpeg/ffprobe missing")
            raise unittest.SkipTest(reason or "ffmpeg/ffprobe missing")

    def test_visible_drawing_geometry_desk_timing_and_portable_render(self):
        with tempfile.TemporaryDirectory(prefix="aimaster-overlay-engine-") as temporary:
            root = Path(temporary).resolve()
            eng = own_engine(self.found, root)
            files = {"a.mp4": make_clip(root / "a.mp4", 2, size=(320, 180), color="red", audio=False).read_bytes(),
                     "b.mp4": make_clip(root / "b.mp4", 1, size=(320, 180), color="blue", audio=False).read_bytes()}
            ws = seed_workspace(root, files, lambda ids: video_state([
                ("s1", "First", "Drawing", 2000, ids["a.mp4"]),
                ("s2", "Second", "End", 1000, ids["b.mp4"])])).workspace
            base = service.build(ws, "p", 0, engine=eng)
            overlay = {"type": "rect", "canvas": {"width": 320, "height": 180},
                       "geometry": {"x": 10, "y": 10, "width": 60, "height": 60},
                       "color": "#00FF00", "stroke_width": 8, "opacity": 1,
                       "draw_on": .4, "scene_id": "s1"}
            service.overlay_add(ws, "p", base["revision"], overlay=overlay, at=0, duration=1.5, engine=eng)
            overlay["geometry"]["x"] = 30
            service.overlay_update(ws, "p", base["revision"], clip="o-1", overlay=overlay, engine=eng)
            paths = montage_paths(ws / "projects" / "p")
            desk = service.open_desk(ws, "p", engine=eng)
            try:
                config = root / "browser.json"
                config.write_text(json.dumps({"modules": str(self.found.prefix / "node_modules"),
                    "browser": eng.browser, "profile": str(root / "browser-profile"),
                    "pidFile": str(root / "browser.pid"), "href": desk["opener_url"],
                    "indexPath": str(paths.index), "overlay": True}), encoding="utf-8")
                check = subprocess.run([eng.node, str(SCRIPTS / "montage_family_desk.mjs"), str(config)],
                                       capture_output=True, text=True, encoding="utf-8", timeout=180)
                self.assertEqual(check.returncode, 0, check.stdout + check.stderr[-2000:])
            finally:
                service.close_desk(ws, "p")
            model = read_model(eng, paths.current)
            self.assertEqual(model.clip("o-1").start, .5)
            self.assertEqual(model.clip("o-1").overlay["geometry"]["x"], 30)
            for kind, geometry, color in (
                    ("ellipse", {"x": 110, "y": 10, "width": 60, "height": 60}, "#0000FF"),
                    ("arrow", {"x1": 210, "y1": 10, "x2": 270, "y2": 70}, "#FFFF00"),
                    ("stroke", {"points": [[20, 120], [60, 150], [100, 120]]}, "#FFFFFF")):
                service.overlay_add(ws, "p", base["revision"], overlay={
                    **overlay, "type": kind, "geometry": geometry, "color": color, "draw_on": 0},
                    at=.5, duration=1.5, engine=eng)
            built = service.render(ws, "p", base["revision"], by="owner", engine=eng)
            before = pixel(built["path"], .4, 30, 40)
            drawing = pixel(built["path"], .55, 30, 40)
            drawn = pixel(built["path"], 1.4, 30, 40)
            self.assertGreater(before[0], 150, before)
            self.assertLess(before[1], 70, before)
            self.assertLess(drawing[1], 70, drawing)
            self.assertGreater(drawn[1], 150, drawn)
            self.assertLess(drawn[0], 100, drawn)
            ellipse = pixel(built["path"], 1.4, 110, 40)
            arrow = pixel(built["path"], 1.4, 240, 40)
            stroke = pixel(built["path"], 1.4, 40, 135)
            self.assertGreater(ellipse[2], 150, ellipse)
            self.assertLess(ellipse[0], 100, ellipse)
            self.assertGreater(min(arrow[:2]), 150, arrow)
            self.assertLess(arrow[2], 100, arrow)
            self.assertGreater(min(stroke), 150, stroke)
            service.export(ws, "p", destination=root / "delivery")
            moved = root / "relocated"
            (root / "delivery").rename(moved)
            shutil.rmtree(ws)
            service.verify_export(moved / "manifest.json")
            exported = read_model(eng, moved / "editable")
            self.assertEqual(exported.clip("o-1").overlay, model.clip("o-1").overlay)
            self.assertEqual(len([clip for clip in exported.clips if clip.overlay]), 4)
            output = moved / "rendered-again.mp4"
            result = EngineRunner().run(eng, render_args(eng, output), cwd=moved / "editable", timeout=120)
            self.assertEqual(result.code, 0, result.stderr[-2000:])
            copied = pixel(output, 1.4, 30, 40)
            self.assertGreater(copied[1], 150, copied)
            self.assertLess(copied[0], 100, copied)


if __name__ == "__main__":
    unittest.main()

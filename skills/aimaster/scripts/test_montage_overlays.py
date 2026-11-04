"""Typed editable drawings, through public montage operations only."""
from __future__ import annotations

import copy
import json
import shutil
import unittest
from pathlib import Path

import test_montage_family as fixtures
from studio.montage import MontageError, service
from studio.montage.edit import EditRequest
from studio.montage.index_io import read_index


def shape(kind="rect"):
    geometry = ({"x": 10, "y": 20, "width": 60, "height": 80} if kind in {"rect", "ellipse"}
                else {"x1": 10, "y1": 20, "x2": 90, "y2": 120} if kind == "arrow"
                else {"points": [[10, 20], [30, 60], [80, 90]]})
    return {"type": kind, "canvas": {"width": 108, "height": 192}, "geometry": geometry,
            "color": "#00FF80", "stroke_width": 4, "opacity": .8, "draw_on": .4,
            "scene_id": "s1"}


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.FamilyMontageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.ws, self.paths = self.fixture.ws, self.fixture.paths
        self.kw = {"engine": self.fixture.engine, "runner": self.fixture.runner}
        self.rev = service.build(self.ws, "p", 0, **self.fixture.kw)["revision"]

    def view(self):
        status = service.status(self.ws, "p", locate=lambda: (self.fixture.engine, ""),
                                runner=self.fixture.runner)
        return next(item["clips"] for item in status["layers"] if item["layer"] == "overlays")

    def test_typed_shapes_geometry_diff_and_portable_round_trip(self):
        self.assertTrue(callable(getattr(service, "overlay_add", None)), "no typed overlay add operation")
        for index, kind in enumerate(("rect", "ellipse", "arrow", "stroke"), 1):
            added = service.overlay_add(self.ws, "p", self.rev, overlay=shape(kind), at=.2,
                                        duration=1.5, **self.kw)
            self.assertEqual(added["receipt"]["new_clip"], f"o-{index}")
        self.assertEqual([clip["overlay"]["type"] for clip in self.view()],
                         ["rect", "ellipse", "arrow", "stroke"])
        first = service.render(self.ws, "p", self.rev, **self.fixture.kw)
        changed = shape("rect")
        changed["geometry"]["x"] = 25
        update = service.overlay_update(self.ws, "p", first["revision"], clip="o-1",
                                        overlay=changed, **self.kw)
        self.assertNotEqual(update["model_hash_before"], update["model_hash"])
        self.assertEqual(self.view()[0]["overlay"]["geometry"]["x"], 25)
        self.assertTrue(any("геометрия" in item for item in service.diff(self.ws, "p", **self.kw)["changes"]))
        second = service.render(self.ws, "p", first["revision"], **self.fixture.kw)
        bundle = self.fixture.root / "drawings"
        service.export(self.ws, "p", destination=bundle, probe=self.fixture.probe)
        shutil.rmtree(self.ws)
        verified = service.verify_export(bundle / "manifest.json")
        self.assertEqual(verified["version"], second["version"])
        text = (bundle / "editable" / "index.html").read_text()
        self.assertIn('<svg', text)
        self.assertIn('id="o-4"', text)
        self.assertFalse((bundle / "subtitles" / "titles.srt").exists())

    def test_invalid_geometry_scene_and_stale_model_refuse_without_file_changes(self):
        original = read_index(self.paths.index)
        invalid = []
        for key, value in (("canvas", {"width": 192, "height": 108}), ("color", "url(https://bad)"),
                           ("stroke_width", float("nan")), ("opacity", 2),
                           ("scene_id", "not-a-project-scene"), ("svg", "<script>bad</script>")):
            candidate = shape()
            candidate[key] = value
            invalid.append(candidate)
        outside = shape()
        outside["geometry"]["x"] = 100
        invalid.append(outside)
        stroke = shape("stroke")
        stroke["geometry"]["points"] = [[0, 0]] * 1025
        invalid.append(stroke)
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(MontageError):
                service.overlay_add(self.ws, "p", self.rev, overlay=candidate, at=.2, duration=1, **self.kw)
            self.assertEqual(read_index(self.paths.index), original)
        with self.assertRaises(MontageError):
            service.overlay_add(self.ws, "p", self.rev, overlay=shape(), at=.2, duration=1,
                                expected_model_hash="stale", **self.kw)
        self.assertEqual(read_index(self.paths.index), original)

    def test_overlay_uses_existing_timing_delete_undo_and_tracks_native_geometry(self):
        service.overlay_add(self.ws, "p", self.rev, overlay=shape("stroke"), at=.2, duration=1.5, **self.kw)
        service.edit(self.ws, "p", self.rev, EditRequest(op="move", clip="o-1", at=.6), **self.kw)
        self.assertEqual(self.view()[0]["start"], .6)
        service.edit(self.ws, "p", self.rev, EditRequest(op="trim-end", clip="o-1", duration=1), **self.kw)
        self.assertEqual(self.view()[0]["duration"], 1)
        before = read_index(self.paths.index)
        service.edit(self.ws, "p", self.rev, EditRequest(op="delete", clip="o-1"), **self.kw)
        self.assertNotIn('id="o-1"', read_index(self.paths.index))
        service.edit(self.ws, "p", self.rev, EditRequest(op="undo"), **self.kw)
        self.assertEqual(read_index(self.paths.index), before)
        built = service.render(self.ws, "p", self.rev, **self.fixture.kw)
        self.paths.index.write_text(before.replace('stroke="#00FF80"', 'stroke="#FF0080"'), encoding="utf-8")
        changed = service.diff(self.ws, "p", **self.kw)
        self.assertTrue(changed["unrendered_changes"])
        self.assertTrue(any("рисунка" in item for item in changed["changes"]))


if __name__ == "__main__":
    unittest.main()

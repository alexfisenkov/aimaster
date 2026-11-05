#!/usr/bin/env python3
"""Studio-only GSAP move must dirty the rendered version without a model migration."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS.parent), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_built import BuiltMontage  # noqa: E402
from studio.montage import service  # noqa: E402
from studio.montage.context import open_context  # noqa: E402
from studio.montage.index_io import read_index, write_index  # noqa: E402
from studio.montage.status_screen import cheap_status  # noqa: E402


class StudioMoveTests(unittest.TestCase):
    def test_normalization_stays_clean_but_saved_x_move_needs_new_render(self):
        with tempfile.TemporaryDirectory() as temp:
            built = BuiltMontage(Path(temp).resolve())
            first = built.draft_and_build()
            self.assertEqual(first["version"], "v001")
            original = read_index(built.paths.index)
            self.assertEqual(original, read_index(built.paths.version_dir("v001") / "index.html"))

            # Studio rewrites ordinary HTML metadata when opening an old version.
            normalized = original.replace("<!doctype html>", "<!DOCTYPE html>")
            normalized = normalized.replace('id="root"', 'data-hf-id="hf-root" id="root"', 1)
            write_index(built.paths.index, normalized)
            self.assertFalse(service.status(built.workspace, "p", locate=built.locate,
                                            runner=built.runner)["unrendered_changes"])
            self.assertEqual(service.diff(built.workspace, "p", engine=built.engine,
                                          runner=built.runner)["changes"], [])

            # Exact form Studio 0.8.75 saved after Layout X 0 -> 12px in the blind sample.
            moved = normalized.replace('var tl = gsap.timeline({ paused: true });',
                                       'gsap.set("#v-1", { x: 12, y: 0 });\n'
                                       '        var tl = gsap.timeline({ paused: true });', 1)
            write_index(built.paths.index, moved)
            current = service.status(built.workspace, "p", locate=built.locate,
                                     runner=built.runner)
            self.assertTrue(current["unrendered_changes"])
            self.assertTrue(cheap_status(open_context(built.workspace, "p"), built.engine, "")
                            ["unrendered_changes"])
            pending = service.diff(built.workspace, "p", engine=built.engine,
                                   runner=built.runner)
            self.assertTrue(pending["unrendered_changes"])
            self.assertTrue(pending["changes"])

            second = built.build(first["revision"])
            self.assertEqual(second["version"], "v002")
            self.assertTrue(second["changes"])
            self.assertEqual(read_index(built.paths.version_dir("v002") / "index.html"), moved)
            self.assertFalse(service.status(built.workspace, "p", locate=built.locate,
                                             runner=built.runner)["unrendered_changes"])
            self.assertFalse(service.diff(built.workspace, "p", engine=built.engine,
                                          runner=built.runner)["unrendered_changes"])

            packet = Path(temp) / "packet"
            service.export(built.workspace, "p", destination=packet, version="v002",
                           probe=built.probe)
            moved_packet = Path(temp) / "moved-packet"
            shutil.move(packet, moved_packet)
            self.assertEqual(service.verify_export(moved_packet / "manifest.json")["version"],
                             "v002")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""state["montage"]: черновик, версия, возврат — вместе с assembly и историей, одной транзакцией."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import seed_workspace, tiny_mp4, tiny_wav, video_state  # noqa: E402
from studio.authoring_support import AuthoringError, open_assets, open_store  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.canvas import Canvas  # noqa: E402
from studio.montage.montage_state import (  # noqa: E402
    check_writable, record_draft, record_restore, record_version)
from studio.montage.versions import VersionMeta  # noqa: E402
from studio.projection import ProjectionError, build_snapshot, validate_state  # noqa: E402


class StateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        files = {"a.mp4": tiny_mp4(b"a"), "v1.mp4": tiny_mp4(b"v1"), "v2.mp4": tiny_mp4(b"v2"),
                 "voice.wav": tiny_wav()}
        self.seed = seed_workspace(Path(temp.name).resolve(), files, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"])], audio={"voice": ids["voice.wav"]}))
        self.store = open_store(self.seed.workspace)
        self.assets = open_assets(self.seed.workspace)

    def meta(self, version, file, based_on=None):
        return VersionMeta(version=version, created_at="2026-09-25T10:00:00+00:00", by="agent",
                           based_on=based_on, summary=f"Сборка {version}", changes=(),
                           asset_id=self.seed.ids[file], model_hash="h")

    def load(self):
        return self.store.load("p")

    def test_draft_records_canvas_and_history(self):
        result = record_draft(self.store, "p", 0, canvas=Canvas(108, 192))
        state = self.load()
        self.assertEqual(result["revision"], 1)
        self.assertEqual(state["montage"], {"current_version": None, "versions": [],
                                            "canvas": {"width": 108, "height": 192}})
        self.assertEqual(state["history"][-1]["kind"], "montage-drafted")

    def test_version_sets_assembly_in_the_same_transaction(self):
        record_draft(self.store, "p", 0, canvas=Canvas(108, 192))
        result = record_version(self.store, self.assets, "p", 1, meta=self.meta("v001", "v1.mp4"))
        state = self.load()
        self.assertEqual(result["revision"], 2)
        self.assertEqual(state["montage"]["current_version"], "v001")
        self.assertEqual(state["montage"]["versions"], [{
            "id": "v001", "asset_id": self.seed.ids["v1.mp4"], "created_at": "2026-09-25T10:00:00+00:00",
            "by": "agent", "based_on": None, "summary": "Сборка v001"}])
        self.assertEqual(state["assembly"], {"status": "ready", "asset_id": self.seed.ids["v1.mp4"],
                                             "summary": "Сборка v001"})
        self.assertEqual((state["history"][-1]["kind"], state["history"][-1]["params"]),
                         ("montage-built", {"target_id": "v001"}))

    def test_restore_points_assembly_back(self):
        record_draft(self.store, "p", 0, canvas=Canvas(108, 192))
        record_version(self.store, self.assets, "p", 1, meta=self.meta("v001", "v1.mp4"))
        record_version(self.store, self.assets, "p", 2, meta=self.meta("v002", "v2.mp4", "v001"))
        record_restore(self.store, self.assets, "p", 3, version_id="v001", actor="you")
        state = self.load()
        self.assertEqual(state["montage"]["current_version"], "v001")
        self.assertEqual(state["assembly"]["asset_id"], self.seed.ids["v1.mp4"])
        self.assertEqual((state["history"][-1]["kind"], state["history"][-1]["actor"]),
                         ("montage-restored", "you"))

    def test_refusals(self):
        record_draft(self.store, "p", 0, canvas=Canvas(108, 192))
        record_version(self.store, self.assets, "p", 1, meta=self.meta("v001", "v1.mp4"))
        with self.assertRaises(MontageError):
            record_restore(self.store, self.assets, "p", 2, version_id="v009")
        with self.assertRaises(MontageError):
            record_version(self.store, self.assets, "p", 2, meta=self.meta("v001", "v2.mp4"))
        with self.assertRaises(MontageError):
            check_writable({"project": {"type": "photo"}, "milestones": {}})

    def test_approved_assembly_is_not_reopened(self):
        def approve(state):
            state["milestones"]["assembly"] = "approved"
        self.store.transact("p", 0, approve)
        with self.assertRaises(AuthoringError):
            record_draft(self.store, "p", 1, canvas=Canvas(108, 192))

    def test_validation_rejects_broken_sections(self):
        base = video_state([("s1", "Сад", "текст", 2000, "asset-a")])
        broken = [
            {"current_version": "v002", "versions": [], "canvas": {"width": 1, "height": 1}},
            {"current_version": None, "versions": [{"id": "001", "asset_id": "a", "created_at": "t",
                                                    "by": "agent", "based_on": None, "summary": ""}],
             "canvas": {"width": 1, "height": 1}},
            {"current_version": None, "versions": [], "canvas": {"width": 0, "height": 1}},
            {"current_version": None, "versions": [], "canvas": {"width": 1, "height": 1}, "x": 1},
        ]
        for section in broken:
            with self.subTest(section=section), self.assertRaises(ProjectionError):
                validate_state({**base, "montage": section})
        photo = {**base, "project": {**base["project"], "type": "photo"},
                 "montage": {"current_version": None, "versions": [], "canvas": {"width": 1, "height": 1}}}
        with self.assertRaises(ProjectionError):
            validate_state(photo)

    def test_snapshot_shows_versions_with_asset_urls(self):
        record_draft(self.store, "p", 0, canvas=Canvas(108, 192))
        record_version(self.store, self.assets, "p", 1, meta=self.meta("v001", "v1.mp4"))
        snapshot = build_snapshot(self.store.list_projects(), self.load(),
                                  asset_url=lambda asset: f"/assets/{asset}")
        montage = snapshot["active_project"]["montage"]
        self.assertEqual(montage["current_version"], "v001")
        self.assertEqual(montage["versions"][0]["asset_url"], f"/assets/{self.seed.ids['v1.mp4']}")
        self.assertEqual(self.store.project_dir("p"), self.seed.workspace.resolve() / "projects" / "p")


if __name__ == "__main__":
    unittest.main()

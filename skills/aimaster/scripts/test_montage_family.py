"""Generated-clips format, personal style and portable export public seams."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from montage_testkit import (FakeHyperframes, fake_engine, fake_gsap_prefix,
                             seed_workspace, tiny_mp4, tiny_wav, video_state)
from studio.authoring_support import open_store
from studio.montage import MontageError, service
from studio.montage.paths import montage_paths
from studio.montage.probe import MediaInfo
from studio.montage.edit import EditRequest


class FamilyMontageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.seed = seed_workspace(self.root, {
            "a.mp4": tiny_mp4(b"selected-a"), "b.mp4": tiny_mp4(b"selected-b"),
            "voice.wav": tiny_wav()}, lambda ids: video_state([
                ("s1", "First", "slow cinematic reveal", 2000, ids["a.mp4"]),
                ("s2", "Second", "product", 2000, ids["b.mp4"])],
                audio={"voice": ids["voice.wav"]}))
        self.ws = self.seed.workspace
        self.paths = montage_paths(self.ws / "projects" / "p")
        self.engine = fake_engine(fake_gsap_prefix(self.root, files=("gsap", "MotionPathPlugin")))
        self.runner = FakeHyperframes(render_bytes=tiny_mp4(b"rendered"))
        self.kw = {"engine": self.engine, "runner": self.runner, "probe": self.probe}

    def probe(self, path):
        duration = 3.5 if Path(path).name not in {"a.mp4", "b.mp4", "voice.wav"} else {
            "a.mp4": 2.0, "b.mp4": 1.5, "voice.wav": 8.0}[Path(path).name]
        return MediaInfo(duration, 108, 192, True, True)

    def test_build_executes_selected_generated_format_and_preserves_base(self):
        self.assertTrue(callable(getattr(service, "build", None)), "missing executable format build")
        result = service.build(self.ws, "p", 0, style="cinematic", **self.kw)
        self.assertEqual((result["version"], result["revision"]), ("v001", 2))
        manifest = result["handoff"]
        self.assertEqual(manifest["format"]["kind"], "generated-clips")
        self.assertEqual(manifest["format"]["method"], "aiediting-format-adaptation")
        self.assertEqual([item["asset_id"] for item in manifest["scenes"]],
                         [self.seed.ids["a.mp4"], self.seed.ids["b.mp4"]])
        self.assertEqual([(item["start"], item["duration"]) for item in manifest["scenes"]],
                         [(0.0, 2.0), (2.0, 1.5)])
        self.assertEqual(manifest["audio"][0]["duration"], 3.5)
        self.assertEqual(manifest["aspect_ratio"], "9:16")
        original = Path(result["path"]).read_bytes()
        composition = (self.paths.version_dir("v001") / "index.html").read_bytes()
        self.runner.render_bytes = tiny_mp4(b"improved")
        second = service.build(self.ws, "p", 2, style="dynamic", improve=True, **self.kw)
        self.assertEqual(second["version"], "v002")
        self.assertEqual(Path(result["path"]).read_bytes(), original)
        self.assertEqual((self.paths.version_dir("v001") / "index.html").read_bytes(), composition)
        self.assertNotEqual(self.paths.index.read_bytes(), composition)
        self.assertTrue(result["improvement_optional"])

    def test_export_is_relocatable_verified_and_uses_rendered_snapshot(self):
        base = service.build(self.ws, "p", 0, **self.kw)
        service.edit(self.ws, "p", 2, EditRequest(op="title-add", text="Created caption", at=.25,
                                                  duration=1), engine=self.engine, runner=self.runner)
        service.render(self.ws, "p", 2, **self.kw)
        (self.paths.current / ".env").write_text("PRIVATE_NOT_FOR_EXPORT", encoding="utf-8")
        self.assertTrue(callable(getattr(service, "export", None)), "missing portable export")
        destination = self.root / "delivery"
        result = service.export(self.ws, "p", destination=destination, probe=self.probe)
        self.assertEqual(result["version"], "v002")
        self.assertTrue((destination / "final.mp4").is_file())
        self.assertTrue((destination / "editable" / "assets" / "fonts" / "OFL.txt").is_file(),
                        "redistributed fonts must retain their license")
        self.assertIn("Created caption", (destination / "subtitles" / "titles.srt").read_text())
        self.assertNotIn(str(self.ws), (destination / "manifest.json").read_text())
        self.assertFalse((destination / "editable" / ".env").exists())
        # Unsaved desk changes never replace the composition for the delivered MP4.
        self.paths.index.write_text("unrendered private edits", encoding="utf-8")
        moved = self.root / "other folder" / "delivery"
        moved.parent.mkdir()
        destination.rename(moved)
        shutil.rmtree(self.ws)
        verified = service.verify_export(moved / "manifest.json")
        self.assertEqual(verified["version"], "v002")
        self.assertIn("Created caption", (moved / "editable" / "index.html").read_text())
        (moved / "final.mp4").write_bytes(b"corrupt")
        with self.assertRaises(MontageError):
            service.verify_export(moved / "manifest.json")

    def test_personal_style_preview_reuses_only_verified_same_selected_media(self):
        result = service.build(self.ws, "p", 0, style="auto", **self.kw)
        self.assertEqual(result["handoff"]["format_ref"], "cinematic")
        saved = service.save_style(self.ws, "p", identity="my-look", label="My look")
        self.assertEqual(saved["ref"], "user:my-look")
        self.assertTrue((self.ws / ".montage-styles" / "my-look.json").is_file())
        self.assertTrue(callable(getattr(service, "preview", None)), "missing own-clips preview")
        before = open_store(self.ws).load("p")
        first = service.preview(self.ws, "p", style="user:my-look", duration=3.5, **self.kw)
        count = sum(call[0] == "render" for call in self.runner.calls)
        again = service.preview(self.ws, "p", style="user:my-look", duration=3.5, **self.kw)
        self.assertTrue(again["reused"])
        self.assertEqual(first["path"], again["path"])
        self.assertEqual(sum(call[0] == "render" for call in self.runner.calls), count)
        self.assertEqual(open_store(self.ws).load("p"), before)
        Path(first["path"]).write_bytes(b"corrupt preview")
        repaired = service.preview(self.ws, "p", style="user:my-look", duration=3.5, **self.kw)
        self.assertFalse(repaired["reused"])
        self.assertEqual(sum(call[0] == "render" for call in self.runner.calls), count + 1)

    def test_explicit_improvement_reopens_approved_base_without_losing_delivery_on_failure(self):
        base = service.build(self.ws, "p", 0, **self.kw)
        store = open_store(self.ws)
        store.transact("p", 2, lambda state: state["milestones"].update(assembly="approved"))
        self.runner.render_bytes = None
        with self.assertRaisesRegex(MontageError, "Сборка не удалась"):
            service.build(self.ws, "p", 3, style="dynamic", improve=True, **self.kw)
        state = store.load("p")
        self.assertEqual(state["milestones"]["assembly"], "ready")
        self.assertEqual(state["assembly"]["asset_id"], base["asset_id"])
        self.assertEqual(state["montage"]["current_version"], "v001")
        self.assertEqual(state["history"][-1]["kind"], "montage-improvement-opened")
        self.assertTrue(Path(base["path"]).is_file())

    def test_stale_selected_result_is_not_handed_to_a_format(self):
        state_path = self.ws / "projects" / "p" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["video_results"][0]["stale"] = True
        state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(MontageError):
            service.handoff(self.ws, "p", probe=self.probe)
        self.assertFalse(self.paths.index.exists())


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Regression tests for mandatory per-scene continuity decisions."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from studio import authoring, domain, runner_context  # noqa: E402
from studio.authoring_continuity import extract_last_frame  # noqa: E402


def video_state() -> dict:
    return {
        "project": {"id": "demo", "type": "video", "mode": "guided"},
        "gen_mode": "per_scene",
        "history": [],
        "references": [],
        "scenes": [
            {"scene_id": "s1", "order": 1, "duration_ms": 3000, "need_first": False, "need_last": False, "video_mode": "references", "links": {"video_result_id": "result:s1:video-v1"}},
            {"scene_id": "s2", "order": 2, "duration_ms": 3000, "need_first": False, "need_last": False, "video_mode": "references", "links": {"reference_ids": []}},
        ],
        "video_results": [{
            "result_id": "result:s1:video",
            "version_id": "result:s1:video-v1",
            "scene_id": "s1",
            "asset_id": "asset-prev",
            "status": "ready",
            "decision": "approved",
        }],
    }


class ContinuityGuardTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe required")
    def test_extracts_last_frame_from_real_video_and_preserves_previous_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "media").mkdir()
            store = authoring.open_store(workspace)
            authoring.create_project(store, "film", "Synthetic", "video", "guided")
            assets = authoring.open_assets(workspace)
            video = assets.allowed_roots[0] / "source.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=2:duration=1",
                            "-c:v", "mpeg4", "-q:v", "2", "-pix_fmt", "yuv420p", str(video)], check=True)
            asset = assets.register(video.relative_to(assets.root), "result")["asset_id"]
            def setup(state):
                sample = video_state()
                state.update(scenes=sample["scenes"], video_results=sample["video_results"], gen_mode="per_scene")
                state["video_results"][0]["asset_id"] = asset
                state["milestones"].update(scenario="approved", image_plan="approved", image_results="approved")
            store.transact("film", 0, setup)
            first = extract_last_frame(store, assets, "film", 1, scene_id="s2")
            self.assertEqual(float(first["timestamp"]), 0.5)
            path, mime = assets.resolve(first["asset_id"])
            self.assertTrue(path.is_file())
            self.assertEqual(mime, "image/png")
            def pixels(file, frame_filter=None):
                command = ["ffmpeg", "-v", "error", "-i", str(file)]
                if frame_filter:
                    command += ["-vf", frame_filter]
                return subprocess.run(command + ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                      capture_output=True, check=True).stdout
            extracted = pixels(path)
            self.assertEqual(extracted, pixels(video, "select=eq(n\\,1)"))
            self.assertNotEqual(extracted, pixels(video, "select=eq(n\\,0)"))
            state = store.load("film")
            domain.require_continuity_choice(state, "s2")
            command = subprocess.run([sys.executable, str(SKILL_ROOT / "scripts" / "creator_studio.py"),
                "scene", "continuity", str(workspace), "film", "--scene", "s2", "--strategy",
                "previous_last_frame", "--expected-revision", "2"], capture_output=True, text=True, check=True)
            second = json.loads(command.stdout)
            self.assertNotEqual(first["version_id"], second["version_id"])
            self.assertEqual(len(store.load("film")["image_results"]), 2)
            assets.resolve(first["asset_id"])
            current = store.load("film")
            current["video_results"][0]["asset_id"] = "asset-changed"
            with self.assertRaisesRegex(domain.DomainValidationError, "no longer matches"):
                domain.require_continuity_choice(current, "s2")
            with self.assertRaises(Exception):
                extract_last_frame(store, assets, "film", 1, scene_id="s2")
            self.assertEqual(store.load("film")["revision"], 3)

    def test_second_scene_requires_a_recorded_choice(self) -> None:
        with self.assertRaisesRegex(domain.DomainValidationError, "continuity choice"):
            domain.require_continuity_choice(video_state(), "s2")

    def test_first_scene_and_one_shot_do_not_require_choice(self) -> None:
        domain.require_continuity_choice(video_state(), "s1")
        state = video_state()
        state["gen_mode"] = "one_shot"
        domain.require_continuity_choice(state, "s2")

    def test_independent_choice_satisfies_guard(self) -> None:
        state = video_state()
        domain.set_continuity_strategy(state, "s2", "independent")
        domain.require_continuity_choice(state, "s2")
        self.assertEqual(state["scenes"][1]["continuity_strategy"], "independent")

    def test_changing_one_source_does_not_invalidate_unrelated_choice(self):
        state = video_state()
        state["scenes"].append({"scene_id": "s3", "order": 3, "duration_ms": 3000,
            "need_first": False, "need_last": False, "video_mode": "references", "links": {}})
        domain.set_continuity_strategy(state, "s2", "previous_video")
        domain.set_continuity_strategy(state, "s3", "independent")
        state["video_results"][0]["asset_id"] = "new-source"
        with self.assertRaisesRegex(domain.DomainValidationError, "no longer matches"):
            domain.require_continuity_choice(state, "s2")
        domain.require_continuity_choice(state, "s3")

    def test_previous_video_uses_selected_previous_result(self) -> None:
        state = video_state()
        domain.set_continuity_strategy(state, "s2", "previous_video")
        domain.require_continuity_choice(state, "s2")
        self.assertEqual(state["scenes"][1]["continuity_source_result_id"], "result:s1:video-v1")
        state["video_results"][0]["decision"] = "rejected"
        with self.assertRaisesRegex(domain.DomainValidationError, "accepted"):
            domain.require_continuity_choice(state, "s2")

    def test_previous_video_switches_mode_and_deduplicates_proven_local_reference(self):
        state = video_state()
        scene = state["scenes"][1]
        scene.update(need_first=True, video_mode="first")
        scene["links"]["reference_ids"] = ["VID_01", "VID_02"]
        state["references"] = [
            {"reference_id": "VID_01", "tag": "VID_01", "role": "video", "usage": "continue", "local": True,
             "scene_id": "s2", "asset_id": "asset-prev", "continuity_source_result_id": "result:s1:video-v1"},
            {"reference_id": "VID_02", "tag": "VID_02", "role": "video", "usage": "reference", "local": True,
             "scene_id": "s2", "asset_id": "asset-other"},
        ]
        domain.set_continuity_strategy(state, "s2", "previous_video")
        self.assertEqual(scene["video_mode"], "references")
        with self.assertRaisesRegex(domain.DomainValidationError, "references mode"):
            domain.set_video_mode(state, "s2", "first")
        spec = next(s for s in domain.position_specs(state) if s.get("kind") == "video" and s.get("scene_id") == "s2")
        item = runner_context._position_context(state, spec)
        self.assertEqual([r["reference_id"] for r in item["references"]], ["VID_02"])
        self.assertEqual(item["semantic_tags"], ["VID_01"])
        self.assertEqual(item["continuity_video"]["reference_id"], "previous:result:s1:video-v1")
        self.assertEqual(len(item["semantic_references"]), 2)
        scene["video_mode"] = "first"
        with self.assertRaisesRegex(domain.DomainValidationError, "references mode"):
            domain.require_continuity_choice(state, "s2")

    def test_previous_last_frame_never_accepts_unrelated_first_frame(self) -> None:
        state = video_state()
        state["scenes"][1]["need_first"] = True
        state["scenes"][1]["video_mode"] = "first"
        state["scenes"][1]["links"]["first_frame_result_id"] = "result:s2:first-v1"
        state["image_results"] = [{
            "result_id": "result:s2:first",
            "version_id": "result:s2:first-v1",
            "scene_id": "s2",
            "asset_id": "asset-first",
            "status": "ready",
            "decision": "approved",
        }]
        with self.assertRaisesRegex(domain.DomainValidationError, "materializing"):
            domain.set_continuity_strategy(state, "s2", "previous_last_frame")
        state["scenes"][1].update(continuity_strategy="previous_last_frame", continuity_previous_scene_id="s1",
                                   continuity_source_result_id="result:s1:video-v1", continuity_source_asset_id="asset-prev", continuity_first_frame_result_id="result:s2:first-v1")
        with self.assertRaisesRegex(domain.DomainValidationError, "provenance"):
            domain.require_continuity_choice(state, "s2")

    def test_unknown_strategy_is_rejected(self) -> None:
        state = copy.deepcopy(video_state())
        with self.assertRaisesRegex(domain.DomainValidationError, "continuity strategy"):
            domain.set_continuity_strategy(state, "s2", "magic")

    def test_keyframe_inputs_do_not_upload_semantic_references(self):
        state = video_state()
        scene = state["scenes"][1]
        scene.update(need_first=True, video_mode="first")
        scene["links"]["reference_ids"] = ["IMG_01"]
        state["references"] = [{"reference_id": "IMG_01", "role": "character", "asset_id": "hero"}]
        spec = next(s for s in domain.position_specs(state) if s.get("kind") == "video" and s.get("scene_id") == "s2")
        item = runner_context._position_context(state, spec)
        self.assertEqual(item["references"], [])
        self.assertEqual(item["semantic_references"][0]["asset_id"], "hero")

    def test_vary_and_regenerate_target_use_the_same_continuity_guard(self) -> None:
        state = video_state()
        state["scenes"][1]["links"]["video_result_id"] = "result:s2:video-v1"
        state["video_results"].append({
            "result_id": "result:s2:video",
            "version_id": "result:s2:video-v1",
            "scene_id": "s2",
            "asset_id": "asset-s2",
            "status": "ready",
        })
        with self.assertRaisesRegex(domain.DomainValidationError, "continuity choice"):
            runner_context.require_existing_video_action_continuity(
                state, "result:s2:video-v1"
            )
        domain.set_continuity_strategy(state, "s2", "independent")
        runner_context.require_existing_video_action_continuity(
            state, "result:s2:video-v1"
        )


if __name__ == "__main__":
    unittest.main()

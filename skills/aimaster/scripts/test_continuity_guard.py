#!/usr/bin/env python3
"""Regression tests for mandatory per-scene continuity decisions."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from studio import domain, runner_context  # noqa: E402


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

    def test_previous_video_requires_scene_local_continue_reference(self) -> None:
        state = video_state()
        state["references"].append({
            "reference_id": "VID_GLOBAL", "role": "video", "usage": "continue", "asset_id": "asset-v1"
        })
        state["scenes"][1]["links"]["reference_ids"] = ["VID_GLOBAL"]
        with self.assertRaisesRegex(domain.DomainValidationError, "usage=continue"):
            domain.set_continuity_strategy(state, "s2", "previous_video")
        state["references"].append({
            "reference_id": "VID_01", "role": "video", "usage": "continue", "asset_id": "asset-v2",
            "local": True, "scene_id": "s2",
        })
        state["scenes"][1]["links"]["reference_ids"] = ["VID_01"]
        domain.set_continuity_strategy(state, "s2", "previous_video")
        domain.require_continuity_choice(state, "s2")
        self.assertEqual(state["references"][1]["continuity_source_result_id"], "result:s1:video-v1")

    def test_previous_last_frame_requires_planned_first_frame(self) -> None:
        state = video_state()
        with self.assertRaisesRegex(domain.DomainValidationError, "planned first frame"):
            domain.set_continuity_strategy(state, "s2", "previous_last_frame")
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
        domain.set_continuity_strategy(state, "s2", "previous_last_frame")
        domain.require_continuity_choice(state, "s2")
        self.assertEqual(state["scenes"][1]["continuity_first_frame_result_id"], "result:s2:first-v1")

    def test_unknown_strategy_is_rejected(self) -> None:
        state = copy.deepcopy(video_state())
        with self.assertRaisesRegex(domain.DomainValidationError, "continuity strategy"):
            domain.set_continuity_strategy(state, "s2", "magic")

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

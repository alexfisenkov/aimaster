#!/usr/bin/env python3
"""Этап звука можно пропустить, если слоёв никто не делал.

Четыре аудио-позиции (`domain_positions.AUDIO_LAYERS`) заводятся у каждого
видеопроекта сразу, поэтому до этой правки нетронутый звук оставлял все
четыре в `status: "none"`, а `stage_readiness` отвечал `unaccepted_positions`
— проект без звука не мог дойти до сборки вообще.

Правило: аудио-позиция обязательна, только если в её группе результатов
есть хоть одна запись. Не «выбрана владельцем», а именно «есть»: вариант
сделан, но решение по нему не принято — это как раз тот случай, который
обязан держать этап.

Состояния собираются здесь же, без файлов и процессов: проверяется чистая
функция готовности, а не CLI.
"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.decision_stages import plan_milestone  # noqa: E402
from studio.decision_support import DecisionError  # noqa: E402
from studio.domain import derive_positions  # noqa: E402
from studio.stage_readiness import stage_readiness  # noqa: E402


VOICE_GROUP = "result:audio:voice"
VOICE_VERSION = "result:audio:voice-v1"


def project_at_audio():
    """Видеопроект, прошедший всё до звука. Звука ещё нет вовсе."""

    return {
        "revision": 1,
        "project": {"id": "p", "title": "Проект", "type": "video",
                    "mode": "guided", "status": "active", "order": 1},
        "milestones": {"scenario": "approved", "image_plan": "approved",
                       "image_results": "approved", "motion": "approved"},
        "script": {"active_version_id": "s1", "versions": [
            {"version_id": "s1", "parent_version_id": None, "text": "текст", "reason": "начало"}]},
        "history": [],
        "gen_mode": "per_scene",
        "scenes": [],
        "stage_decisions": [],
        "references": [],
        "image_prompts": [], "motion_prompts": [], "image_results": [], "video_results": [],
        "applied_action_ids": [],
        "audio_layers": [{"layer": "voice", "links": {}}],
        "audio_prompts": [], "audio_results": [],
    }


def with_voice_result(decision=None):
    """Тот же проект, но у слоя «голос» появился один вариант."""

    state = project_at_audio()
    state["audio_layers"] = [{"layer": "voice", "links": {"audio_result_id": VOICE_VERSION}}]
    result = {"result_id": VOICE_GROUP, "version_id": VOICE_VERSION,
              "parent_version_id": None, "status": "ready"}
    if decision is not None:
        result["decision"] = decision
    state["audio_results"] = [result]
    return state


def audio_positions(state):
    return {position["layer"]: position
            for position in derive_positions(state) if position.get("layer")}


class AudioStageSkippable(unittest.TestCase):
    def test_untouched_sound_can_be_approved(self):
        state = project_at_audio()
        readiness = stage_readiness(state)
        self.assertEqual(readiness["stage"], "audio")
        self.assertIs(readiness["can_approve"], True)
        self.assertIsNone(readiness["reason"])

    def test_untouched_layers_are_not_required(self):
        positions = audio_positions(project_at_audio())
        self.assertEqual(sorted(positions), ["atmos", "fx", "music", "voice"])
        for layer, position in positions.items():
            self.assertIs(position["required"], False, layer)
            self.assertEqual(position["status"], "none", layer)

    def test_a_variant_without_a_decision_still_holds_the_stage(self):
        state = with_voice_result()
        readiness = stage_readiness(state)
        self.assertIs(readiness["can_approve"], False)
        self.assertEqual(readiness["reason"], "unaccepted_positions")
        positions = audio_positions(state)
        self.assertIs(positions["voice"]["required"], True)
        self.assertEqual(positions["voice"]["status"], "ready")
        self.assertIs(positions["music"]["required"], False)

    def test_an_accepted_layer_next_to_three_empty_ones_passes(self):
        state = with_voice_result(decision="approved")
        readiness = stage_readiness(state)
        self.assertIs(readiness["can_approve"], True)
        self.assertIsNone(readiness["reason"])
        self.assertEqual(audio_positions(state)["voice"]["status"], "accepted")

    def test_a_result_that_nobody_linked_still_counts_as_work(self):
        """«Есть результат» — про группу, а не про ссылку владельца."""

        state = project_at_audio()
        state["audio_results"] = [{"result_id": VOICE_GROUP, "version_id": VOICE_VERSION,
                                   "parent_version_id": None, "status": "ready"}]
        positions = audio_positions(state)
        self.assertIs(positions["voice"]["required"], True)
        self.assertEqual(positions["voice"]["status"], "none")
        self.assertEqual(stage_readiness(state)["reason"], "unaccepted_positions")

    def test_other_kinds_stay_required_without_any_result(self):
        """Правка касается только звука: сцены и референсы не ослабли."""

        state = project_at_audio()
        state["milestones"] = {"scenario": "approved", "image_plan": "approved"}
        state["scenes"] = [{"scene_id": "s", "order": 1, "title": "Сцена", "duration_ms": 5000,
                            "start_ms": 0, "end_ms": 5000, "links": {},
                            "script_block": {"active_version_id": "b1", "versions": [
                                {"version_id": "b1", "parent_version_id": None,
                                 "text": "блок", "reason": "начало"}]}}]
        clip = next(position for position in derive_positions(state)
                    if position["position_id"] == "pos:scene:s:video")
        self.assertIs(clip["required"], True)
        self.assertEqual(clip["status"], "none")

    def test_the_stage_decision_uses_the_same_readiness(self):
        """Одобрение стадии не считает готовность по-своему."""

        approved = project_at_audio()
        plan_milestone("audio", True, {})(approved)
        self.assertEqual(approved["milestones"]["audio"], "approved")

        held = with_voice_result()
        with self.assertRaises(DecisionError) as refusal:
            plan_milestone("audio", True, {})(held)
        self.assertEqual(str(refusal.exception), "unaccepted_positions")


if __name__ == "__main__":
    unittest.main()

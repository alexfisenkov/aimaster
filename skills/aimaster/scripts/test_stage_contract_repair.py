"""Stage approval, audio planning and current motion basis at public boundaries."""
import copy
import json
import time
import unittest

from test_library import Base, cli
from studio import domain
from studio.decision_support import DecisionError
from studio.decision_stages import plan_milestone
from studio.domain_positions import position_specs
from studio.runner_context import build_action_context
from studio.server import serve
from studio.stage_readiness import stage_readiness
from validate_reference_bindings import validate_binding, validate_claimed_context


class StageContractTests(Base):
    def reference_plan(self):
        self.project_at_references("p")
        ref = cli("reference", "add", self.ws, "p", "--kind", "character", "--name", "Hero",
                  "--source", "generate", "--expected-revision", self.rev("p"))["reference_id"]
        image = cli("prompt", "add-version", self.ws, "p", "--target", "pos:ref:" + ref,
                    "--text", "Hero portrait", "--reason", "test", "--expected-revision", self.rev("p"))
        motion = cli("prompt", "add-version", self.ws, "p", "--target", "pos:scene:s1:video",
                     "--text", "Camera moves", "--reason", "draft", "--expected-revision", self.rev("p"))
        return ref, image["version_id"], motion["version_id"]

    def test_cli_stage_approves_only_current_image_prompt(self):
        ref, first, motion = self.reference_plan()
        second = cli("prompt", "add-version", self.ws, "p", "--target", "pos:ref:" + ref,
                     "--text", "New hero", "--reason", "refine", "--expected-revision", self.rev("p"))["version_id"]
        cli("stage", "approve", self.ws, "p", "--expected-revision", self.rev("p"))
        state = self.store.load("p")
        prompts = {p["version_id"]: p for p in state["image_prompts"] + state["motion_prompts"]}
        self.assertEqual(prompts[first]["status"], "pending")
        self.assertEqual(prompts[second]["status"], "approved")
        self.assertEqual(prompts[second]["decisions"][-1]["decision"], "approved")
        self.assertEqual(prompts[motion]["status"], "pending")
        self.assertEqual(state["references"][0]["links"]["image_prompt_version_id"], second)

    def test_rejected_and_stale_prompt_block_approval(self):
        _, version, _ = self.reference_plan()
        state = self.store.load("p")
        target = next(p for p in state["image_prompts"] if p["version_id"] == version)
        target["status"] = "rejected"
        self.assertFalse(stage_readiness(state)["can_approve"])
        with self.assertRaises(DecisionError): plan_milestone("image_plan", True, {})(state)
        target["status"] = "pending"
        target["basis"] = {"label": "outdated", "kind": "character"}
        self.assertFalse(stage_readiness(state)["can_approve"])

    def test_cross_stage_and_superseded_prompt_cannot_be_approved(self):
        ref, first, motion = self.reference_plan()
        cli("prompt", "add-version", self.ws, "p", "--target", "pos:ref:" + ref,
            "--text", "Current", "--reason", "refine", "--expected-revision", self.rev("p"))
        for target in (first, motion):
            revision = self.rev("p")
            with self.assertRaises(ValueError):
                cli("decide", self.ws, "p", "approve", "--target", target, "--expected-revision", revision)
            self.assertEqual(self.rev("p"), revision)

    def test_legacy_approved_status_gets_auditable_decision(self):
        _, version, _ = self.reference_plan()
        state = self.store.load("p")
        prompt = next(p for p in state["image_prompts"] if p["version_id"] == version)
        prompt["status"] = "approved"
        plan_milestone("image_plan", True, {"comment": "reviewed"})(state)
        self.assertEqual(prompt["decisions"][-1], {"decision": "approved", "comment": "reviewed"})

    def test_http_card_approval_uses_current_version_then_cli_stage(self):
        _, version, _ = self.reference_plan()
        server = serve(self.ws)
        self.addCleanup(server.close)
        app = server.application
        headers = [("Host", app.authority), ("Origin", app.origin), ("X-CSRF-Token", app.csrf_token), ("Content-Type", "application/json")]
        payload = {"project_id": "p", "action_type": "approve", "target_id": version,
                   "payload": {}, "expected_revision": self.rev("p"), "idempotency_key": "approve-image"}
        response = app.handle("POST", "/api/actions", headers, json.dumps(payload).encode())
        self.assertEqual(response.status, 202)
        action_id = json.loads(response.body)["action_id"]
        for _ in range(100):
            action = app.ledger.get_action(action_id)
            if action.get("status") in {"succeeded", "failed"}: break
            time.sleep(.02)
        self.assertEqual(action.get("status"), "succeeded", action)
        image = next(p for p in self.store.load("p")["image_prompts"] if p["version_id"] == version)
        self.assertEqual(image["status"], "approved")
        payload.update(target_id="image_plan", expected_revision=self.rev("p"), idempotency_key="approve-stage")
        response = app.handle("POST", "/api/actions", headers, json.dumps(payload).encode())
        self.assertEqual(response.status, 202)
        stage_id = json.loads(response.body)["action_id"]
        for _ in range(100):
            stage_action = app.ledger.get_action(stage_id)
            if stage_action.get("status") in {"succeeded", "failed"}: break
            time.sleep(.02)
        self.assertEqual(stage_action.get("status"), "succeeded", stage_action)
        snapshot = app.handle("GET", "/api/projects/p/snapshot", [("Host", app.authority)], b"")
        self.assertEqual(snapshot.status, 200)
        image = next(p for p in self.store.load("p")["image_prompts"] if p["version_id"] == version)
        self.assertEqual(len(image["decisions"]), 1)

    def test_audio_plan_cli_required_and_silent(self):
        self.project_at_references("p")
        cli("project", "set-audio-plan", self.ws, "p", "--layers", "voice", "music", "--expected-revision", self.rev("p"))
        state = self.store.load("p")
        required = {p["layer"] for p in domain.derive_positions(state) if p.get("kind") == "audio" and p["required"]}
        self.assertEqual(required, {"voice", "music"})
        state["milestones"].update(image_plan="approved", image_results="approved", motion="approved")
        self.assertEqual(stage_readiness(state)["reason"], "unaccepted_positions")
        cli("project", "set-audio-plan", self.ws, "p", "--silent", "--expected-revision", self.rev("p"))
        silent = self.store.load("p")
        silent["milestones"].update(image_plan="approved", image_results="approved", motion="approved")
        self.assertTrue(stage_readiness(silent)["can_approve"])

    def test_audio_plan_does_not_silently_discard_existing_take(self):
        self.project_at_references("p")
        def seed(state):
            state["audio_results"] = [{"result_id": "result:audio:music", "version_id": "result:audio:music-v1", "status": "ready"}]
        self.store.transact("p", self.rev("p"), seed)
        revision = self.rev("p")
        with self.assertRaisesRegex(ValueError, "existing"):
            cli("project", "set-audio-plan", self.ws, "p", "--silent", "--expected-revision", revision)
        self.assertEqual(self.rev("p"), revision)
        self.assertEqual(len(self.store.load("p")["audio_results"]), 1)

    def test_motion_approval_records_actual_prompt_decision(self):
        self.project_at_references("p")
        result = cli("prompt", "add-version", self.ws, "p", "--target", "pos:scene:s1:video",
                     "--text", "Move", "--reason", "draft", "--expected-revision", self.rev("p"))
        state = self.store.load("p")
        state["milestones"].update(image_plan="approved", image_results="approved")
        scene = state["scenes"][0]
        video = {"result_id": "result:scene:s1:video", "version_id": "result:scene:s1:video-v1",
                 "scene_id": "s1", "asset_id": "asset-v", "status": "ready", "decision": "approved"}
        state["video_results"] = [video]
        scene["links"]["video_result_id"] = video["version_id"]
        self.assertTrue(stage_readiness(state)["can_approve"])
        plan_milestone("motion", True, {"comment": "checked"})(state)
        prompt = next(p for p in state["motion_prompts"] if p["version_id"] == result["version_id"])
        self.assertEqual(prompt["status"], "approved")
        self.assertEqual(prompt["decisions"][-1], {"decision": "approved", "comment": "checked"})

    def test_motion_approval_checks_frame_acceptance_even_if_prompt_basis_matches(self):
        self.project_at_references("p")
        result = cli("prompt", "add-version", self.ws, "p", "--target", "pos:scene:s1:video",
                     "--text", "Move", "--reason", "draft", "--expected-revision", self.rev("p"))
        state = self.store.load("p")
        state["milestones"].update(image_plan="approved", image_results="approved")
        scene = state["scenes"][0]
        scene.update(need_first=True, video_mode="first")
        scene["links"].update(first_frame_result_id="result:frame:s1:first-v1", video_result_id="result:scene:s1:video-v1")
        frame = {"result_id": "result:frame:s1:first", "version_id": "result:frame:s1:first-v1", "scene_id": "s1", "asset_id": "frame", "status": "ready", "decision": "approved"}
        state["image_results"] = [frame]
        state["video_results"] = [{"result_id": "result:scene:s1:video", "version_id": "result:scene:s1:video-v1", "scene_id": "s1", "asset_id": "video", "status": "ready", "decision": "approved"}]
        spec = next(s for s in position_specs(state) if s.get("kind") == "video")
        prompt = next(p for p in state["motion_prompts"] if p["version_id"] == result["version_id"])
        prompt["basis"] = domain.prompt_basis(state, spec)
        self.assertTrue(stage_readiness(state)["can_approve"])
        frame["decision"] = "rejected"
        self.assertFalse(stage_readiness(state)["can_approve"])

    def test_motion_prompt_stales_after_frame_change_for_all_paid_actions(self):
        self.project_at_references("p")
        result = cli("prompt", "add-version", self.ws, "p", "--target", "pos:scene:s1:video",
                     "--text", "Move", "--reason", "draft", "--expected-revision", self.rev("p"))
        state = self.store.load("p")
        state["milestones"].update(image_plan="approved", image_results="approved")
        spec = next(s for s in position_specs(state) if s.get("kind") == "video")
        prompt = next(p for p in state["motion_prompts"] if p["version_id"] == result["version_id"])
        state["scenes"][0]["links"]["first_frame_result_id"] = "new-frame-v1"
        self.assertTrue(domain.compute_prompt_stale(state, prompt, spec))
        for kind in ("generate", "vary", "regenerate"):
            candidate = dict(state, video_results=[])
            target = spec["position_id"]
            if kind != "generate":
                candidate["video_results"] = [{"result_id": spec["result_group_id"], "version_id": spec["result_group_id"] + "-v1", "scene_id": "s1", "asset_id": "asset-v", "status": "ready"}]
                candidate["scenes"][0]["links"]["video_result_id"] = candidate["video_results"][0]["version_id"]
                target = candidate["video_results"][0]["version_id"]
            with self.assertRaisesRegex(ValueError, "stale"):
                build_action_context(candidate, {"action_type": kind, "target_id": target})

    def test_keyframe_prompt_can_preserve_semantics_but_outgoing_must_resolve_tags(self):
        self.project_at_references("p")
        state = self.store.load("p")
        state["milestones"].update(image_plan="approved", image_results="approved")
        scene = state["scenes"][0]
        scene.update(need_first=True, video_mode="first")
        scene["links"].update(first_frame_result_id="result:frame:s1:first-v1", reference_ids=["IMG_01"],
                              motion_prompt_version_id="prompt:scene:s1:video-v1")
        state["references"] = [{"reference_id": "IMG_01", "tag": "IMG_01", "role": "character", "asset_id": "asset-hero"}]
        state["image_results"] = [{"result_id": "result:frame:s1:first", "version_id": "result:frame:s1:first-v1",
                                  "scene_id": "s1", "asset_id": "asset-frame", "status": "ready", "decision": "approved"}]
        spec = next(s for s in position_specs(state) if s.get("kind") == "video")
        state["motion_prompts"] = [{"prompt_id": "prompt:scene:s1:video", "version_id": "prompt:scene:s1:video-v1",
            "scene_id": "s1", "text": "@IMG_01 идёт вперёд", "status": "pending", "basis": domain.prompt_basis(state, spec)}]
        context = build_action_context(state, {"action_type": "generate", "target_id": spec["position_id"]})
        position = context["positions"][0]
        self.assertEqual(position["references"], [])
        self.assertEqual(position["semantic_references"][0]["reference_id"], "IMG_01")
        self.assertEqual(position["prompt"]["text"], "@IMG_01 идёт вперёд")
        manifest = {"schema_version": 1, "operation_id": "op", "provider": "test", "route": "route", "model": "model",
                    "binding_source": "structured_schema", "observed_at": "2026-11-06T00:00:00Z", "state_revision": state["revision"],
                    "references": [{"canonical": "FRAME_FIRST", "reference_id": "frame:s1:first", "asset_id": "asset-frame",
                                    "role": "first frame", "transport": "structured", "slot": "start_image"}]}
        validate_binding(manifest, "Персонаж в первом кадре идёт вперёд")
        validate_claimed_context(manifest, {"action_id": "op", "context": context})
        with self.assertRaisesRegex(ValueError, "unresolved"):
            validate_binding(manifest, "@IMG_01 идёт вперёд")

    def test_previous_video_manifest_against_real_frozen_context(self):
        self.project_at_references("p")
        state = self.store.load("p")
        state["milestones"].update(image_plan="approved", image_results="approved")
        first = state["scenes"][0]
        first["links"]["video_result_id"] = "result:scene:s1:video-v1"
        second = copy.deepcopy(first)
        second.update(scene_id="s2", order=2, video_mode="references")
        second["links"] = {"motion_prompt_version_id": "prompt:scene:s2:video-v1", "reference_ids": ["VID_01"]}
        state["scenes"].append(second)
        state["video_results"] = [{"result_id": "result:scene:s1:video", "version_id": "result:scene:s1:video-v1",
                                   "scene_id": "s1", "asset_id": "asset-selected", "status": "ready", "decision": "approved"}]
        state["references"] = [{"reference_id": "VID_01", "tag": "VID_01", "role": "video", "usage": "continue",
                                "local": True, "scene_id": "s2", "asset_id": "asset-selected",
                                "continuity_source_result_id": "result:scene:s1:video-v1"}]
        domain.set_continuity_strategy(state, "s2", "previous_video")
        spec = next(s for s in position_specs(state) if s.get("scene_id") == "s2" and s.get("kind") == "video")
        state["motion_prompts"] = [{"prompt_id": "prompt:scene:s2:video", "version_id": "prompt:scene:s2:video-v1",
            "scene_id": "s2", "text": "Continue @VID_01", "status": "pending", "basis": domain.prompt_basis(state, spec)}]
        context = build_action_context(state, {"action_type": "generate", "target_id": spec["position_id"]})
        self.assertEqual(context["positions"][0]["references"], [])
        self.assertEqual(context["positions"][0]["continuity_video"]["aliases"], ["VID_01"])
        manifest = {"schema_version": 1, "operation_id": "op", "provider": "test", "route": "route", "model": "model",
                    "binding_source": "structured_schema", "observed_at": "2026-11-06T00:00:00Z", "state_revision": state["revision"],
                    "references": [{"canonical": "PREVIOUS_VIDEO", "reference_id": "previous:result:scene:s1:video-v1", "asset_id": "asset-selected",
                                    "role": "guidance", "transport": "structured", "slot": "source_video"}]}
        package = {"action_id": "op", "context": context}
        validate_binding(manifest, "Continue")
        validate_claimed_context(manifest, package)
        for entries in ([], [dict(manifest["references"][0], asset_id="wrong")],
                        [dict(manifest["references"][0], reference_id="previous:other")]):
            with self.assertRaisesRegex(ValueError, "claimed context"):
                validate_claimed_context(dict(manifest, references=entries), package)


if __name__ == "__main__":
    unittest.main()

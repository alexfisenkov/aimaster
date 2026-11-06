"""Legacy selected clips and immutable render source approval boundaries."""
import copy
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from montage_testkit import video_state
from studio import domain
from studio.completion import CompletionError, selected_materials
from studio.decision_stages import plan_milestone
from studio.domain_positions import position_specs
from studio.montage.stale import stale_clips
from studio.projection import build_snapshot
from studio.stage_readiness import stage_readiness
from studio.store import ProjectStore
from studio.server import serve
from studio.telegram_bot import TelegramBotController, TelegramBotState


class MontageAcceptanceTruthTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.projects = Path(temporary.name) / "projects"
        self.project = self.projects / "p"
        version = self.project / "montage" / "versions" / "v001"
        version.mkdir(parents=True)
        self.state = video_state([(f"s{i}", f"Scene {i}", "Action", 1000, f"asset-{i}") for i in range(1, 7)])
        for spec in position_specs(self.state):
            if spec["kind"] != "video": continue
            scene = next(s for s in self.state["scenes"] if s["scene_id"] == spec["scene_id"])
            prompt_id = f"prompt:scene:{spec['scene_id']}:video"
            scene["links"]["motion_prompt_version_id"] = prompt_id + "-v1"
            basis = domain.prompt_basis(self.state, spec)
            basis.pop("video_mode", None)  # persisted before additive provenance field
            self.state["motion_prompts"].append({"prompt_id": prompt_id, "version_id": prompt_id + "-v1",
                "scene_id": spec["scene_id"], "text": "Move", "status": "approved", "basis": basis})
        self.state["assembly"] = {"status": "ready", "asset_id": "asset-render"}
        self.state["montage"] = {"current_version": "v001", "versions": [{"id": "v001", "asset_id": "asset-render", "created_at": "2026-01-01T00:00:00Z", "by": "agent", "based_on": None, "summary": ""}]}
        scene_ids = " ".join(f"s{i}" for i in range(1, 7))
        clips = "".join(f'<video id="v{i}" data-am-layer="video" data-am-scene="s{i}" data-am-asset="asset-{i}"></video>' for i in range(1, 7))
        self.html = f'<div id="root" data-am-scenes="{scene_ids}" data-am-gen-mode="per_scene" data-am-layers="">{clips}</div>'
        index = version / "index.html"
        index.write_text(self.html)
        (version / "files.json").write_text(json.dumps([{"path": "index.html", "sha256": hashlib.sha256(index.read_bytes()).hexdigest()}]))
        (version / "meta.json").write_text(json.dumps({"version": "v001", "asset_id": "asset-render"}))
        self.store = ProjectStore(self.projects, [])

    def write_state(self, state):
        (self.project / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def snapshot(self, state):
        return build_snapshot([], state, asset_url=lambda a: "/assets/" + a, project_directory=self.project)

    def test_legacy_prompts_do_not_revoke_accepted_results(self):
        self.assertEqual(stale_clips(self.html, self.state), [])
        self.assertEqual(len([x for x in selected_materials(self.state) if x["kind"] == "video"]), 6)
        snap = self.snapshot(self.state)["active_project"]
        self.assertTrue(snap["stage_readiness"]["can_approve"])
        self.assertTrue(all(p["stale"] for p in snap["motion_prompts"]))
        self.write_state(self.state)
        accepted = self.store.transact("p", 0, plan_milestone("assembly", True, {}))
        self.assertEqual(accepted["milestones"]["assembly"], "approved")

    def test_changed_selected_or_rejected_clip_blocks_snapshot_and_transaction(self):
        for changed in ("rejected", "new-asset"):
            state = copy.deepcopy(self.state)
            if changed == "rejected": state["video_results"][0]["decision"] = "rejected"
            else: state["video_results"][0]["asset_id"] = "asset-new"
            self.assertEqual(stage_readiness(state, project_directory=self.project)["reason"], "stale_assembly")
            self.assertFalse(self.snapshot(state)["active_project"]["stage_readiness"]["can_approve"])
            self.write_state(state)
            with self.assertRaises(CompletionError):
                self.store.transact("p", 0, plan_milestone("assembly", True, {}))
            self.assertNotEqual(self.store.load("p")["milestones"].get("assembly"), "approved")
            self.assertTrue((self.project / "montage" / "versions" / "v001" / "index.html").is_file())

    def test_missing_or_changed_version_evidence_blocks_approval(self):
        (self.project / "montage" / "versions" / "v001" / "index.html").write_text(self.html + "<!-- changed -->")
        self.assertEqual(stage_readiness(self.state, project_directory=self.project)["reason"], "stale_assembly")

    def test_unrelated_historical_media_action_does_not_revoke_render(self):
        state = copy.deepcopy(self.state)
        state["actions"] = [{"target_id": "pos:scene:s2:video", "status": "running"}]
        self.assertTrue(stage_readiness(state, project_directory=self.project)["can_approve"])

    def test_http_snapshot_and_decision_use_same_selected_render_gate(self):
        state = copy.deepcopy(self.state)
        state["video_results"][0]["decision"] = "rejected"
        self.write_state(state)
        server = serve(self.projects.parent)
        self.addCleanup(server.close)
        app = server.application
        headers = [("Host", app.authority), ("Origin", app.origin), ("X-CSRF-Token", app.csrf_token), ("Content-Type", "application/json")]
        response = app.handle("GET", "/api/projects/p/snapshot", [("Host", app.authority)], b"")
        self.assertEqual(response.status, 200)
        ready = json.loads(response.body)["active_project"]["stage_readiness"]
        self.assertEqual(ready["reason"], "stale_assembly")
        request = {"project_id": "p", "action_type": "approve", "target_id": "assembly", "payload": {},
                   "expected_revision": 0, "idempotency_key": "approve-stale-render"}
        result = app.handle("POST", "/api/actions", headers, json.dumps(request).encode())
        self.assertEqual(result.status, 202)
        action_id = json.loads(result.body)["action_id"]
        for _ in range(100):
            action = app.ledger.get_action(action_id)
            if action.get("status") in {"succeeded", "failed"}: break
            time.sleep(.02)
        self.assertEqual(action.get("status"), "failed")
        self.assertNotEqual(self.store.load("p")["milestones"].get("assembly"), "approved")

    def test_telegram_snapshot_keeps_same_montage_gate(self):
        state = copy.deepcopy(self.state)
        state["video_results"][0]["decision"] = "rejected"
        self.write_state(state)
        controller = TelegramBotController(self.projects.parent, 501,
            state=TelegramBotState(self.projects.parent / "telegram.sqlite3"),
            store_factory=lambda: self.store, ledger_factory=lambda: None, questions_factory=lambda: None)
        snapshot = controller._public_snapshot("p")
        self.assertIsNotNone(snapshot)
        self.assertFalse(snapshot["active_project"]["stage_readiness"]["can_approve"])
        self.assertEqual(snapshot["active_project"]["stage_readiness"]["reason"], "stale_assembly")


if __name__ == "__main__":
    unittest.main()

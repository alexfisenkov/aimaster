"""Public controller/host boundaries; no provider calls in this suite."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import authoring
from studio.runner import open_runner
from studio.ledger import ActionRequest


class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = Path(self.tmp.name) / "workspace Ω"
        self.ws.mkdir()
        self.ws = self.ws.resolve()
        self.store = authoring.open_store(self.ws)
        authoring.create_project(self.store, "film", "Synthetic", "photo", "guided")
        self.runner = open_runner(self.ws)

    def operator(self, adapter):
        self.assertIsNotNone(importlib.util.find_spec("studio.operator"), "missing executable operator")
        from studio.operator import Operator
        return Operator(self.ws, agent="codex", adapter=adapter, state_dir=Path(self.tmp.name) / "family")

    def queue(self, key="one"):
        return self.runner.ledger.enqueue("film", ActionRequest("continue-in-chat", "scenario",
            {"text": "Read the current script"}, 0, key))

    def test_canonical_readback_and_exact_action_identity(self):
        action = self.queue()
        def adapter(job, workspace, skill):
            from studio.operator_adapters import state_digest
            return {"action_id": job["action_id"], "project_id": "film", "action_type": "continue-in-chat",
                "target_id": "scenario", "base_revision": 0, "revision": 0, "status": "succeeded",
                "state_sha256": state_digest(self.store.load("film")), "output_ids": [], "reply": "No script yet."}
        with self.operator(adapter) as controller:
            self.assertEqual(controller.step()["status"], "succeeded")
            self.assertIsNone(controller.step())
        self.assertEqual(self.runner.ledger.get_action(action["action_id"])["status"], "succeeded")

    def test_telegram_inbox_uses_same_controller_and_verified_result(self):
        from studio.telegram_bot import TelegramBotState
        state = TelegramBotState(self.ws / ".studio" / "telegram_bot.sqlite3")
        state.begin(12, "fingerprint", 99, {"kind": "reply", "text": "Queued"})
        state.complete(12, "Queued")
        state.enqueue_inbox(update_id=12, chat_id=99, workspace=str(self.ws), project_id="film", text="Read only")
        def adapter(job, workspace, skill):
            from studio.operator_adapters import state_digest
            return {"action_id": job["action_id"], "project_id": "film", "action_type": "continue-in-chat",
                "target_id": "scenario", "base_revision": 0, "revision": 0, "status": "succeeded",
                "state_sha256": state_digest(self.store.load("film")), "output_ids": [], "reply": "No script yet."}
        with self.operator(adapter) as controller:
            result = controller.step()
            self.assertIsNotNone(result, "Telegram inbox never reaches the canonical executor")
            self.assertEqual(result["status"], "succeeded")
        self.assertEqual(state.pending_replies(99)[0].text, "No script yet.")

    def test_spoofed_success_is_unknown_and_never_replayed(self):
        action = self.queue()
        calls = []
        def adapter(*args):
            calls.append(1)
            return {"status":"succeeded", "reply":"done"}
        with self.operator(adapter) as controller:
            self.assertEqual(controller.step()["status"], "outcome_unknown")
            self.assertIsNone(controller.step())
        self.assertEqual(calls, [1])
        duplicate = self.runner.ledger.enqueue("film", ActionRequest("continue-in-chat", "scenario", {}, 0, "new-click"), deduplicate=True)
        self.assertEqual(duplicate["action_id"], action["action_id"])

    def test_exact_scenario_mutation_proves_version_and_revision(self):
        action = self.runner.ledger.enqueue("film", ActionRequest("revise-scenario", "scenario", {}, 0, "revise"))
        def adapter(job, workspace, skill):
            from studio.operator_adapters import state_digest
            changed = authoring.add_script_version(self.store, "film", 0, "New synthetic scenario", "owner requested revision")
            state = self.store.load("film")
            return {**{key:job[key] for key in ("action_id","project_id","action_type","target_id")},
                "base_revision":0,"revision":changed["revision"],"status":"succeeded",
                "state_sha256":state_digest(state),"output_ids":[changed["version_id"]],"reply":"Scenario saved."}
        with self.operator(adapter) as controller:
            self.assertEqual(controller.step()["status"], "succeeded")
        self.assertEqual(self.store.load("film")["script"]["versions"][-1]["text"], "New synthetic scenario")

    def test_single_controller_and_family_lock_precede_claim(self):
        from studio.family_setup import operation_lease, OperationBusy
        action = self.queue()
        with self.operator(lambda *args: self.fail("adapter must not run")) as controller:
            with self.assertRaises(OperationBusy):
                with self.operator(lambda *args: None):
                    pass
            with operation_lease(Path(self.tmp.name) / "family", "updater"):
                with self.assertRaises(OperationBusy):
                    controller.step()
                self.assertEqual(self.runner.ledger.get_action(action["action_id"])["status"], "queued")

    def test_restart_recovers_only_stopped_operator_worker(self):
        action = self.queue()
        with self.operator(lambda *args: None) as controller:
            self.runner.ledger.claim_next(controller.identity)
        other = self.queue("manual")
        self.runner.ledger.claim_next("manual-worker")
        with self.operator(lambda *args: None):
            self.assertEqual(self.runner.ledger.get_action(action["action_id"])["status"], "outcome_unknown")
            self.assertEqual(self.runner.ledger.get_action(other["action_id"])["status"], "running")

    def test_package_change_and_stale_revision_do_not_dispatch(self):
        action = self.queue()
        with self.operator(lambda *args: self.fail("stale job dispatched")) as controller:
            with patch("studio.operator.package_fingerprint", return_value="changed"):
                self.assertIsNone(controller.step())
                from studio.operator import status
                self.assertEqual(status(self.ws)["reason"], "restart_required")
        authoring.add_script_version(self.store, "film", 0, "Concurrent revision", "test")
        with self.operator(lambda *args: self.fail("stale job dispatched")) as controller:
            self.assertEqual(controller.step()["status"], "failed")

    def test_family_pointer_switch_requires_restart_even_when_old_files_stay(self):
        from studio.operator import status
        from studio.family_setup.state import read_state, save_state
        action = self.queue()
        with self.operator(lambda *args: self.fail("old package accepted a new job")) as controller:
            directory = Path(self.tmp.name) / "family"
            data = read_state(directory)
            data["components"]["aimaster"] = {"fingerprint":"new-package", "revision":"new-revision"}
            save_state(directory,data)
            self.assertIsNone(controller.step(), "old physical checkout was reused after family switch")
            self.assertEqual(status(self.ws).get("reason"), "restart_required")
            self.assertEqual(self.runner.ledger.get_action(action["action_id"])["status"],"queued")


class PaidRouteTests(unittest.TestCase):
    def test_exact_route_grant_duplicate_and_canonical_asset_collection(self):
        from test_library import cli, png_bytes
        from studio.server import serve
        from studio.operator import Operator
        from studio.operator_routes import set_route
        from studio.operator_adapters import state_digest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); ws = root / "ws"
            cli("workspace", "init", ws)
            store = authoring.open_store(ws)
            cli("project", "create", ws, "p", "--title", "Photo", "--type", "photo", "--mode", "guided")
            rev = lambda: store.load("p")["revision"]
            cli("script", "add-version", ws, "p", "--text", "Synthetic", "--reason", "start", "--expected-revision", rev())
            scenes = root / "scenes.json"; scenes.write_text(json.dumps([{"scene_id":"s1","title":"Scene","text":"Action"}]))
            cli("scenes", "set", ws, "p", "--file", scenes, "--expected-revision", rev())
            cli("stage", "approve", ws, "p", "--expected-revision", rev())
            target = "pos:scene:s1:image"
            cli("prompt", "add-version", ws, "p", "--target", target, "--text", "Synthetic image", "--reason", "start", "--expected-revision", rev())
            cli("stage", "approve", ws, "p", "--expected-revision", rev())
            selected = set_route(ws, "p", target, rev(), provider="magnific", model="synthetic-test-model", operation="image.generate", parameters={"width":1280})
            server = serve(ws); self.addCleanup(server.close)
            app = server.application
            headers = [("Host",app.authority),("Origin",app.origin),("X-CSRF-Token",app.csrf_token),("Content-Type","application/json")]
            request = {"project_id":"p","action_type":"generate","target_id":target,"expected_revision":rev(),
                "idempotency_key":"one","payload":{"spending":{"confirmed":True,**{key:selected[key] for key in ("route_id","provider","model")}}}}
            calls = []
            def adapter(job, workspace, skill):
                calls.append(job)
                (ws / "media" / "result.png").write_bytes(png_bytes())
                asset = cli("asset", "register", ws, "--path", "media/result.png", "--role", "result")
                result = cli("result", "add-version", ws, "p", "--target", target, "--asset-id", asset["asset_id"], "--expected-revision", rev())
                return {**{key:job[key] for key in ("action_id","project_id","action_type","target_id")},"base_revision":job["revision"],
                    "revision":rev(),"status":"succeeded","state_sha256":state_digest(store.load("p")),"output_ids":[result["version_id"]],"reply":"Collected."}
            with Operator(ws, agent="codex", adapter=adapter, state_dir=root / "family") as controller:
                first = json.loads(app.handle("POST","/api/actions",headers,json.dumps(request).encode()).body)
                self.assertEqual(first["status"], "queued")
                request["idempotency_key"] = "double-click"
                second = json.loads(app.handle("POST","/api/actions",headers,json.dumps(request).encode()).body)
                self.assertEqual(first["action_id"], second["action_id"])
                self.assertEqual(controller.step()["status"], "succeeded")
                self.assertEqual(len(calls),1)
                self.assertEqual(calls[0]["execution_route"]["model"], "synthetic-test-model")
                self.assertEqual(controller.runner.ledger.count_reserved_grants(), 1)
                self.assertEqual(len(store.load("p")["image_results"]), 1)
                routes = app.handle("GET","/api/projects/p/routes",[("Host",app.authority)],b"")
                self.assertNotIn(str(ws), routes.body.decode())
                self.assertNotIn("parameters", routes.body.decode())
                cli("mode", "set", ws, "p", "--mode", "autopilot", "--expected-revision", rev())
                request.update(action_type="vary",target_id=store.load("p")["image_results"][0]["version_id"],
                    payload={},expected_revision=rev(),idempotency_key="auto-next")
                automatic = json.loads(app.handle("POST","/api/actions",headers,json.dumps(request).encode()).body)
                self.assertEqual(automatic["status"],"queued")
                self.assertEqual(controller.step()["status"],"succeeded", "autopilot history revision must be the execution basis")
                cli("mode", "set", ws, "p", "--mode", "guided", "--expected-revision", rev())
                cli("prompt", "add-version", ws, "p", "--target", target, "--text", "Changed prompt basis", "--reason", "new request", "--expected-revision", rev())
                request.update(payload={"spending":{"confirmed":True,**{key:selected[key] for key in ("route_id","provider","model")}}},
                    expected_revision=rev(),idempotency_key="stale-route")
                refused = json.loads(app.handle("POST","/api/actions",headers,json.dumps(request).encode()).body)
                self.assertEqual(refused["status"],"needs_chat_setup")
                self.assertEqual(controller.runner.ledger.count_reserved_grants(), 2)
                self.assertIsNone(controller.step())
                with self.assertRaises(ValueError):
                    set_route(ws,"p",target,rev(),provider="magnific",model="synthetic-test-model",operation="image.generate",parameters={"endpoint":"https://attacker.invalid"})
                fresh = set_route(ws,"p",target,rev(),provider="magnific",model="synthetic-test-model",operation="image.generate",parameters={})
                payload = {"spending":{"confirmed":True,**{key:fresh[key] for key in ("route_id","provider","model")}}}
                latest = store.load("p")["image_results"][-1]["version_id"]
                for key in ("legacy-one","legacy-two"):
                    controller.runner.ledger.enqueue("p",ActionRequest("vary",latest,payload,rev(),key),scoped_grant=True)
                from studio.operator_adapters import AdapterFailure
                attempts = []
                def uncertain(*args):
                    attempts.append(1)
                    raise AdapterFailure()
                controller.adapter = uncertain
                self.assertEqual(controller.step()["status"],"outcome_unknown")
                self.assertEqual(controller.step()["status"],"needs_chat")
                self.assertEqual(attempts,[1],"legacy second paid job must not replay an unknown position")


if __name__ == "__main__":
    unittest.main()

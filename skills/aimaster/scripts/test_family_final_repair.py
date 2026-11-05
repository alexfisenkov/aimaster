"""Final repair regressions through public domain/transport entry points."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

import test_montage_family as montage_fixture
import test_provider_collection as collection_fixture
from studio import authoring
from studio.family_setup import packages
from studio.telegram_bot import TelegramBotController
from studio.montage import service, MontageError
from studio.montage.edit import EditRequest


class CompatibilityRepairTests(unittest.TestCase):
    def test_actual_target_reader_refuses_version_only_malformed_meta(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Path(directory).resolve()
            authoring.create_project(authoring.open_store(ws), "p", "Synthetic", "photo", "guided")
            meta = ws / "projects/p/montage/versions/v001/meta.json"
            meta.parent.mkdir(parents=True); meta.write_text("{}")
            before = {str(p): p.read_bytes() for p in ws.rglob("*") if p.is_file()}
            self.assertFalse(packages.compatibility(Path(__file__).resolve().parents[1], [ws]))
            self.assertEqual(before, {str(p): p.read_bytes() for p in ws.rglob("*") if p.is_file()})

    def test_workspace_preferences_survive_new_origin_and_refuse_unknown_keys(self):
        from studio.server import serve
        with tempfile.TemporaryDirectory() as directory:
            ws = Path(directory).resolve()
            authoring.create_project(authoring.open_store(ws), "p", "Свой текст", "photo", "guided")
            before = authoring.open_store(ws).load("p")
            first = serve(ws)
            app = first.application
            headers = [("Host",app.authority),("Origin",app.origin),("X-CSRF-Token",app.csrf_token),("Content-Type","application/json")]
            value = {"locale":"en","theme":"dark","view":"overview","rail":"docked"}
            try:
                self.assertEqual(app.handle("POST","/api/preferences",headers,json.dumps(value).encode()).status,200)
                self.assertEqual(app.handle("POST","/api/preferences",[("Host",app.authority)],b'{}').status,403)
                for invalid in ({"path":"/tmp/private"},{"theme":"blue"},{"locale":"en","extra":1}):
                    self.assertEqual(app.handle("POST","/api/preferences",headers,json.dumps(invalid).encode()).status,400)
            finally:
                first.close()
            second = serve(ws)
            try:
                response = second.application.handle("GET","/api/preferences",[("Host",second.application.authority)],b"")
                self.assertEqual(json.loads(response.body),value)
            finally:
                second.close()
            self.assertEqual(authoring.open_store(ws).load("p"),before)


class TelegramRepairTests(unittest.TestCase):
    def update(self, identity, text=None, document=None):
        return {"update_id": identity, "message": {"from": {"id": 99},
            "chat": {"id": 99, "type": "private"}, **({"text": text} if text else {}),
            **({"document": document} if document else {})}}

    def test_malformed_archive_is_durable_and_following_update_works(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Path(directory).resolve()
            authoring.create_project(authoring.open_store(ws), "p", "Synthetic", "photo", "guided")
            bot = TelegramBotController(ws, 99)
            calls = []
            bot.attachment_downloader = lambda spec: calls.append(1) or b"PK\x03\x04broken"
            bad = self.update(1, document={"file_id": "broken", "file_unique_id": "broken"})
            reply = bot.handle_update(bad)
            self.assertIn("отклонена", reply[0].text)
            self.assertEqual(bot.state.next_offset(), 2)
            bot.handle_update(bad)
            self.assertEqual(calls, [1])
            following = bot.handle_update(self.update(2, text="/start"))[0]
            self.assertIn("Synthetic", json.dumps(following.reply_markup))
            self.assertEqual(bot.state.next_offset(), 3)

    def test_first_pairing_has_project_navigation_without_tunnel(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Path(directory).resolve()
            authoring.create_project(authoring.open_store(ws), "p", "Synthetic", "photo", "guided")
            bot = TelegramBotController(ws, None, pairing_code="synthetic-pair")
            reply = bot.handle_update(self.update(1, text="/start synthetic-pair"))
            self.assertIn("Synthetic", reply[0].text)
            self.assertIsNotNone(reply[0].reply_markup)
            self.assertNotIn("synthetic-pair", reply[0].text)


class MontageUndoRepairTests(unittest.TestCase):
    setUp = montage_fixture.FamilyMontageTests.setUp
    probe = montage_fixture.FamilyMontageTests.probe
    def test_stale_undo_refuses_without_touching_composition_or_history(self):
        service.build(self.ws, "p", 0, **self.kw)
        service.edit(self.ws, "p", 2, EditRequest(op="title-add", text="Mark", at=0, duration=1),
                     engine=self.engine, runner=self.runner)
        before = {str(p): p.read_bytes() for p in self.paths.root.rglob("*") if p.is_file()}
        with self.assertRaises(MontageError):
            service.edit(self.ws, "p", 2, EditRequest(op="undo"), expected_model_hash="stale-hash",
                         engine=self.engine, runner=self.runner)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.paths.root.rglob("*") if p.is_file()})


class TelegramPaidRepairTests(unittest.TestCase):
    setUp = collection_fixture.CollectionTests.setUp

    def exercise(self, command, grant):
        from studio.operator import Operator
        from studio.operator_adapters import AdapterFailure
        assets = authoring.open_assets(self.ws)
        (self.ws / "media/first.png").write_bytes(self.original.read_bytes())
        asset = assets.register("media/first.png", "result")
        result = authoring.add_result_version(self.store, assets, "p", self.store.load("p")["revision"], target=self.target, asset_id=asset["asset_id"])
        if grant:
            self.runner.ledger.issue_grant("p", command, datetime.now(timezone.utc) + timedelta(minutes=5))
        bot = TelegramBotController(self.ws, 99)
        def incoming(identity, text):
            return {"update_id":identity,"message":{"from":{"id":99},"chat":{"id":99,"type":"private"},"text":text}}
        bot.handle_update(incoming(10, "/open p"))
        calls = []
        def adapter(job, *args):
            calls.append(job)
            raise AdapterFailure()
        update = incoming(11, "/" + command + " " + result["version_id"])
        with Operator(self.ws, agent="codex", adapter=adapter, state_dir=self.state_dir) as controller:
            bot.handle_update(update); bot.handle_update(update)
            completed = controller.step()
            if grant:
                self.assertEqual(len(calls), 1, "authorized Telegram paid command did not reach the selected route")
                self.assertEqual(calls[0]["execution_route"]["route_id"], self.route["route_id"])
                self.assertEqual(completed["status"], "outcome_unknown")
            else:
                self.assertIsNone(completed); self.assertEqual(calls, [])
            self.assertIsNone(controller.step())

    def test_guided_vary_binds_saved_route_and_ordinary_grant(self):
        self.exercise("vary", True)

    def test_guided_regenerate_binds_saved_route_and_ordinary_grant(self):
        self.exercise("regenerate", True)

    def test_guided_command_does_not_create_its_own_grant(self):
        self.exercise("vary", False)


if __name__ == "__main__":
    unittest.main()

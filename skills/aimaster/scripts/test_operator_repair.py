"""Blocking T04 review regressions through canonical/public boundaries."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_library import cli
from studio import authoring
from studio.ledger import ActionRequest
from studio.operator import Operator
from studio.operator_routes import set_route


class ScopedGrantRepairTests(unittest.TestCase):
    @patch("studio.provider_download.preflight", lambda route: True)
    def test_refused_s1_grant_never_authorizes_s2(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); ws = root / "workspace"
            cli("workspace", "init", ws)
            store = authoring.open_store(ws)
            cli("project", "create", ws, "p", "--title", "Synthetic", "--type", "photo", "--mode", "guided")
            revision = lambda: store.load("p")["revision"]
            cli("script", "add-version", ws, "p", "--text", "Two scenes", "--reason", "fixture", "--expected-revision", revision())
            scenes = root / "scenes.json"
            scenes.write_text(json.dumps([{"scene_id":sid,"title":sid,"text":"Synthetic"} for sid in ("s1","s2")]))
            cli("scenes", "set", ws, "p", "--file", scenes, "--expected-revision", revision())
            cli("stage", "approve", ws, "p", "--expected-revision", revision())
            routes = {}
            for sid in ("s1", "s2"):
                target = f"pos:scene:{sid}:image"
                cli("prompt", "add-version", ws, "p", "--target", target, "--text", "Synthetic image", "--reason", "fixture", "--expected-revision", revision())
                routes[sid] = set_route(ws,"p",target,revision(),provider="magnific",model="synthetic",operation="image.generate",parameters={})
            cli("stage", "approve", ws, "p", "--expected-revision", revision())
            calls = []
            def adapter(job, *args):
                calls.append(job["target_id"])
                from studio.operator_adapters import AdapterFailure
                raise AdapterFailure()
            with Operator(ws,agent="codex",adapter=adapter,state_dir=root / "family") as controller:
                ledger = controller.runner.ledger
                def request(sid, key):
                    return ActionRequest("generate",f"pos:scene:{sid}:image",
                        {"spending":{"confirmed":True, **{name:routes[sid][name] for name in ("route_id","provider","model")}}},revision(),key)
                first = ledger.enqueue("p",request("s1","first-click"),scoped_grant=True)
                cli("mode", "set", ws, "p", "--mode", "guided", "--expected-revision", revision())
                self.assertEqual(controller.step()["status"],"failed")
                second = ledger.enqueue("p",request("s2","without-new-permission"))
                self.assertEqual(second["status"],"needs_chat", "s1 scoped grant escaped into the reusable chat pool")
                self.assertIsNone(controller.step())
                self.assertEqual(calls,[])
                self.assertEqual(ledger.get_action(first["action_id"])["grant_id"],first["grant_id"])
                # Ordinary, explicitly chat-issued grants keep their old reuse contract.
                from datetime import datetime, timedelta, timezone
                ordinary = ledger.issue_grant("p","generate",datetime.now(timezone.utc)+timedelta(minutes=5))
                ordinary_first = ledger.enqueue("p",request("s1","ordinary-before-refusal"))
                cli("mode", "set", ws, "p", "--mode", "guided", "--expected-revision", revision())
                self.assertEqual(controller.step()["status"],"failed")
                self.assertIsNone(ledger.get_action(ordinary_first["action_id"])["grant_id"])
                allowed = ledger.enqueue("p",request("s2","ordinary-grant"))
                self.assertEqual(allowed["grant_id"],ordinary)
                self.assertEqual(controller.step()["status"],"outcome_unknown")
                self.assertEqual(calls,["pos:scene:s2:image"])


class TelegramUnavailableRepairTests(unittest.TestCase):
    def test_unavailable_owner_input_has_terminal_identity_and_never_replays_on_recovery(self):
        from studio.telegram_bot import TelegramBotController
        for availability in (
            {"available":False,"status":"offline","agent":None},
            {"available":False,"status":"needs_setup","agent":"claude"},
            {"available":False,"status":"needs_setup","agent":"codex","reason":"restart_required"},
        ):
            with self.subTest(availability=availability), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(); ws = root / "ws"; ws.mkdir()
                authoring.create_project(authoring.open_store(ws),"p","Synthetic","photo","guided")
                bot = TelegramBotController(ws,99)
                def incoming(identity,text):
                    return {"update_id":identity,"message":{"from":{"id":99},"chat":{"id":99,"type":"private"},"text":text}}
                bot.handle_update(incoming(1,"/open p"))
                update = incoming(2,"Сгенерируй следующий вариант после проверки проекта")
                with patch("studio.operator.status",return_value=availability):
                    first = bot.handle_update(update)
                action = bot.ledger.action_by_key("p","telegram:2")
                self.assertIsNotNone(action,"offline request was stranded only in the transport inbox")
                self.assertIn(action["status"],{"needs_chat","needs_chat_setup"})
                self.assertIn(action["action_id"],first[0].text)
                self.assertIn('"project_id": "p"',first[0].text)
                self.assertIn('"revision": 0',first[0].text)
                label = ("перезапуска" if availability.get("reason") == "restart_required" else
                         "настройки" if availability["status"] == "needs_setup" else "выключен")
                self.assertIn(label,first[0].text)
                self.assertIsNone(bot.state.dequeue_inbox())
                self.assertIsNone(action["grant_id"])
                calls = []
                with Operator(ws,agent="codex",adapter=lambda *args:calls.append(1),state_dir=root / "family") as controller:
                    repeated = bot.handle_update(update)
                    self.assertEqual(repeated[0].text,first[0].text)
                    self.assertEqual(bot.ledger.action_by_key("p","telegram:2")["action_id"],action["action_id"])
                    self.assertIsNone(controller.step())
                self.assertEqual(calls,[])


class FamilyFontGatewayTests(unittest.TestCase):
    def test_bundled_woff2_is_served_with_exact_mime_and_same_origin_csp(self):
        from urllib.request import urlopen
        from urllib.error import HTTPError
        from studio.server import serve
        from studio.mini_app import serve_mini_app
        with tempfile.TemporaryDirectory() as directory:
            server = serve(Path(directory))
            mini = serve_mini_app(server.application,"synthetic-token",99)
            try:
                for base in (server.base_url,mini.base_url):
                    with urlopen(base + "/") as shell:
                        policy = shell.headers["Content-Security-Policy"]
                        self.assertIn("font-src 'self'",policy,"local family fonts are blocked by default-src none")
                        self.assertIn("default-src 'none'",policy)
                        self.assertIn("script-src 'self' https://telegram.org",policy)
                    with urlopen(base + "/static/fonts/onest-latin-wght-normal.woff2") as font:
                        self.assertEqual(font.status,200)
                        self.assertEqual(font.headers["Content-Type"],"font/woff2")
                        data = font.read()
                        self.assertEqual(data[:4],b"wOF2")
                        self.assertGreater(len(data),1000)
                    with self.assertRaises(HTTPError) as refused:
                        urlopen(base + "/static/fonts/../../SKILL.md")
                    self.assertEqual(refused.exception.code,404)
                    refused.exception.close()
            finally:
                mini.close(); server.close()


if __name__ == "__main__":
    unittest.main()

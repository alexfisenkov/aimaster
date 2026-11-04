"""Owner HTTP, Telegram attachments and public Mini App transport boundaries."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import time
import io
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio import authoring
from studio.server import serve


class HttpOperatorTests(unittest.TestCase):
    def test_montage_family_routes_keep_owner_and_typed_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Path(directory).resolve()
            authoring.create_project(authoring.open_store(ws), "film", "Synthetic", "photo", "guided")
            server = serve(ws)
            self.addCleanup(server.close)
            app = server.application
            class Screen:
                def family(self, part, project_id, request):
                    return {"op":part, "project_id":project_id, "received":request}
            app.montage = Screen()
            base = [("Host", app.authority)]
            self.assertEqual(app.handle("GET", "/api/projects/film/montage/styles", base, b"").status, 200,
                             "family montage endpoints are not mounted")
            headers = base + [("Origin", app.origin), ("X-CSRF-Token", app.csrf_token), ("Content-Type", "application/json")]
            body = json.dumps({"expected_revision":0, "expected_model_hash":"a"*16,
                              "edit":{"op":"overlay-add", "at":0,"duration":1,"overlay":{"type":"rect"}}}).encode()
            self.assertEqual(app.handle("POST", "/api/projects/film/montage/edit", base, body).status, 403)
            result = app.handle("POST", "/api/projects/film/montage/edit", headers, body)
            self.assertEqual(result.status, 200)
            self.assertEqual(json.loads(result.body)["received"]["edit"]["op"], "overlay-add")
    def test_real_server_offline_actions_are_observable_not_permanently_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            ws = Path(directory).resolve()
            authoring.create_project(authoring.open_store(ws), "film", "Synthetic", "photo", "guided")
            server = serve(ws)
            self.addCleanup(server.close)
            app = server.application
            headers = [("Host", app.authority)]
            response = app.handle("GET", "/api/operator", headers, b"")
            self.assertEqual(response.status, 200, "operator liveness endpoint is missing")
            self.assertFalse(json.loads(response.body)["available"])
            library = app.handle("GET", "/api/library", headers, b"")
            self.assertEqual(library.status, 200)
            headers += [("Origin", app.origin), ("X-CSRF-Token", app.csrf_token), ("Content-Type", "application/json")]
            body = json.dumps({"project_id":"film", "action_type":"continue-in-chat", "target_id":"scenario",
                "payload":{}, "expected_revision":0, "idempotency_key":"offline"}).encode()
            accepted = app.handle("POST", "/api/actions", headers, body)
            self.assertEqual(accepted.status, 202)
            result = json.loads(accepted.body)
            self.assertEqual(result["status"], "needs_chat")
            self.assertIn(result["action_id"], result["copy_request"])


class TelegramAttachmentTests(unittest.TestCase):
    def test_default_transport_does_not_follow_credential_bearing_redirects(self):
        from creator_studio_bot import default_opener
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from urllib.error import HTTPError
        import threading
        paths = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                paths.append(self.path)
                self.send_response(302 if self.path == "/first" else 200)
                if self.path == "/first":
                    self.send_header("Location", "/redirected")
                self.send_header("Content-Length", "0")
                self.end_headers()
            def log_message(self, *args):
                pass
        server = HTTPServer(("127.0.0.1",0),Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            with self.assertRaises(HTTPError) as refused:
                default_opener()(f"http://127.0.0.1:{server.server_port}/first",timeout=3)
            refused.exception.close()
            self.assertEqual(paths,["/first"])
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_public_health_requires_exact_html_before_publishing(self):
        from creator_studio_telegram import probe_tunnel_url, TUNNEL_UNREACHABLE, TUNNEL_READY
        from test_telegram_tunnel import FakeEdgeSocket
        def probe(body):
            edge = FakeEdgeSocket(body)
            return probe_tunnel_url("https://studio.example.com",
                resolver=lambda *args, **kwargs: [(2,1,6,"",("127.0.0.1",443))],
                connector=lambda *args, **kwargs: edge, context_factory=lambda: edge)
        self.assertEqual(probe(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\nnot our app"), TUNNEL_UNREACHABLE)
        self.assertEqual(probe(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<script src="/static/mini-app.js"></script>'), TUNNEL_READY)
    @patch("studio.operator.status", lambda workspace: {"available": True, "status": "ready"})
    def test_photo_download_is_owner_scoped_and_replay_safe(self):
        from studio.telegram_bot import TelegramBotController
        from test_library import png_bytes
        with tempfile.TemporaryDirectory() as directory:
            ws = Path(directory).resolve()
            authoring.create_project(authoring.open_store(ws), "film", "Synthetic", "photo", "guided")
            controller = TelegramBotController(ws, 99)
            calls = []
            controller.attachment_downloader = lambda spec: calls.append(spec["file_id"]) or png_bytes()
            def update(identity, sender=99, **message):
                return {"update_id":identity,"message":{"from":{"id":sender},"chat":{"id":sender,"type":"private"},**message}}
            controller.handle_update(update(1, text="/open film"))
            photo = {"photo":[{"file_id":"file-one","file_unique_id":"unique","file_size":100}],"caption":"Use as reference"}
            controller.handle_update(update(2, sender=98, **photo))
            self.assertEqual(calls, [])
            controller.handle_update(update(3, **photo))
            controller.handle_update(update(3, **photo))
            self.assertEqual(calls, ["file-one"], "photo ignored instead of bounded download and intake")
            item = controller.state.dequeue_inbox()
            self.assertEqual(item["project_id"], "film")
            attachments = json.loads(item["attachments_json"])
            self.assertEqual(attachments[0]["source"], "telegram")
            self.assertTrue((ws / attachments[0]["path"]).is_file())

    @patch("studio.operator.status", lambda workspace: {"available": True, "status": "ready"})
    def test_unselected_document_is_retained_separately_and_voice_has_text_fallback(self):
        from studio.telegram_bot import TelegramBotController
        from test_library import wav_bytes
        with tempfile.TemporaryDirectory() as directory:
            ws = Path(directory).resolve()
            authoring.create_project(authoring.open_store(ws), "p", "Synthetic", "photo", "guided")
            controller = TelegramBotController(ws, 99)
            controller.attachment_downloader = lambda spec: wav_bytes() if spec["kind"] == "voice" else b"User instruction document"
            def send(identity, **message):
                return controller.handle_update({"update_id":identity,"message":{"from":{"id":99},"chat":{"id":99,"type":"private"},**message}})
            send(1, document={"file_id":"doc","file_unique_id":"doc","file_name":"../../evil.sh"})
            self.assertIsNone(controller.state.dequeue_inbox())
            self.assertEqual(len(controller.state.pending_uploads()), 1)
            send(2, text="/open p")
            send(3, text="Use the pending document for the scenario")
            item = controller.state.dequeue_inbox()
            self.assertEqual(item["project_id"], "p")
            self.assertEqual(len(json.loads(item["attachments_json"])), 1)
            self.assertEqual(controller.state.pending_uploads(), [])
            reply = send(4, voice={"file_id":"voice","file_unique_id":"voice"})
            self.assertIn("текстом", reply[0].text)
            voice = controller.state.dequeue_inbox()
            self.assertEqual(json.loads(voice["attachments_json"])[0]["transcription"], "unavailable")


class HttpMontageDeliveryTests(unittest.TestCase):
    def test_build_preview_typed_overlay_and_signed_portable_export(self):
        from montage_testkit import FakeHyperframes, fake_engine, fake_gsap_prefix, seed_workspace, tiny_mp4, video_state
        from studio.montage.probe import MediaInfo
        from studio.mini_app import MiniAppGateway
        from test_mini_app import init_data
        from studio.montage import service
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            seed = seed_workspace(root,{"a.mp4":tiny_mp4(b"a")},lambda ids:video_state([("s1","Scene","slow cinematic",2000,ids["a.mp4"])]))
            engine = fake_engine(fake_gsap_prefix(root, files=("gsap","MotionPathPlugin")))
            runner = FakeHyperframes(render_bytes=tiny_mp4(b"rendered"))
            probe = lambda path: MediaInfo(2,108,192,True,False)
            server = serve(seed.workspace); self.addCleanup(server.close)
            app = server.application
            app.montage.engines = lambda:(engine,None)
            app.montage.runner = runner
            app.montage.family_probe = probe
            app.montage.family_state_dir = root / "family"
            token = "123456:" + "a" * 32
            gateway = MiniAppGateway(app,token,99)
            headers = [("Authorization","tma "+init_data(token,99,int(time.time()))),("Content-Type","application/json"),("X-CSRF-Token",app.csrf_token)]
            def post(part, body):
                response = gateway.handle("POST","/api/projects/p/montage/"+part,headers,json.dumps(body).encode())
                self.assertEqual(response.status,200,response.body.decode())
                self.assertNotIn(str(seed.workspace),response.body.decode())
                return json.loads(response.body)
            built = post("build",{"expected_revision":0,"style":"cinematic","improve":False})
            self.assertEqual(built["version"],"v001")
            preview = post("preview",{"style":"dynamic","duration":2})
            self.assertIn("?e=",preview["url"])
            overlay = {"type":"rect","canvas":{"width":108,"height":192},"geometry":{"x":10,"y":20,"width":30,"height":40},"color":"#00FF00","stroke_width":2,"opacity":1}
            # Actual canvas comes from the rendered model rather than viewport pixels.
            from studio.montage.paths import montage_paths
            from studio.montage.model import read_model, model_hash
            model = read_model(engine,montage_paths(seed.workspace / "projects" / "p").current,runner=runner)
            post("edit",{"expected_revision":built["revision"],"expected_model_hash":model_hash(model),"edit":{"op":"overlay-add","at":0,"duration":1,"overlay":overlay}})
            exported = post("export",{"version":"v001"})
            download = gateway.handle("GET",exported["url"],[],b"")
            self.assertEqual(download.status,200)
            data = b"".join(download.stream.chunks()); download.stream.close()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertIn("manifest.json",archive.namelist())
                self.assertIn("final.mp4",archive.namelist())
            self.assertEqual(gateway.handle("GET",exported["url"].split("?")[0],[],b"").status,403)


if __name__ == "__main__":
    unittest.main()

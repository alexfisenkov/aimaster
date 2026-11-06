"""Export fallback accepts only a matching downloaded representation."""
import io
import json
import unittest
import zipfile
import tempfile
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_library  # Adds the skill root to the import path.
from studio.provider_export import verify_export, _zip_bytes

ID = "creation123"
JOB = "a3283332-f93a-4001-9cc3-23ecbee7c9fd"
URL = "https://pikaso.cdnpk.net/private/video.mp4?token=example"
CREATION = {"content": [{"type": "text", "text": f'''identifier: {ID}
tool: video-generator
status: completed
url: "{URL}"
metadata:
  mediaCollection[1]:
    - type: video
      url: "{URL}"
'''}]}
STATUS = {"content": [{"type": "text", "text": f'''status: finished
data:
  total_files: 1
  processed_files: 1
  download_url: "https://pikaso.cdnpk.net/tmp/bulk-downloads/{JOB}/x.zip?token=example"
'''}]}
META = {"identifier": ID, "width": 864, "height": 496, "codecName": "h264",
        "pixFmt": "yuv420p", "durationSeconds": 4.0}
PROBE = {"streams": [{"codec_name": "h264", "width": 864, "height": 496, "pix_fmt": "yuv420p"}],
         "format": {"duration": "4.0"}}


def archive(data=b"video"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as result:
        result.writestr("video.mp4", data)
    return buffer.getvalue()


class ExportTests(unittest.TestCase):
    def verify(self, creation=CREATION, status=STATUS, meta=META, direct=b"video"):
        with patch("studio.provider_export._zip_bytes", return_value=archive()), \
             patch("studio.provider_export.fetch_original", return_value=direct), \
             patch("studio.provider_export.find_program", return_value="ffprobe-test"), \
             patch("studio.provider_export.subprocess.run", return_value=SimpleNamespace(stdout=json.dumps(PROBE).encode())):
            return verify_export(ID, creation, status, JOB, meta)

    def test_matches_exact_provider_representation(self):
        data, proof = self.verify()
        self.assertEqual(data, b"video")
        self.assertEqual(proof["kind"], "provider_export")

    def test_rejects_other_bytes_or_original_available(self):
        with self.assertRaises(ValueError):
            self.verify(direct=b"different")
        bad = {"content": [{"type": "text", "text": CREATION["content"][0]["text"] + '\ndownloadUrl: "https://example.invalid/master"\n'}]}
        with self.assertRaises(ValueError):
            self.verify(creation=bad)

    def test_rejects_different_creation_and_metadata(self):
        with self.assertRaises(ValueError):
            self.verify(meta={**META, "identifier": "another"})
        for value in (None, "NaN", "inf", 0):
            with self.subTest(duration=value), self.assertRaisesRegex(ValueError, "metadata_mismatch"):
                self.verify(meta={**META, "durationSeconds": value})

    def test_refuses_non_provider_zip_and_ambiguous_video(self):
        with self.assertRaises(ValueError):
            _zip_bytes("https://example.invalid/tmp/bulk-downloads/" + JOB + "/x.zip?token=x", JOB)
        bad = {"content": [{"type": "text", "text": CREATION["content"][0]["text"] +
            f'    - type: video\n      url: "{URL}"\n'}]}
        with self.assertRaises(ValueError):
            self.verify(creation=bad)


class ExportRecoveryTests(unittest.TestCase):
    def test_conflict_preview_and_explicit_choice(self):
        from studio import authoring
        from studio.ledger import ActionRequest
        from studio.operator_routes import set_route
        from studio.runner import open_runner
        from studio.provider_export import collect_provider_export
        from studio.provider_collection import recovered_preview, resolve_conflict
        from test_library import cli, mp4_bytes
        for choice in ("keep", "adopt"):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); ws = root / "ws"
                cli("workspace", "init", ws)
                cli("project", "create", ws, "p", "--title", "Test", "--type", "video", "--mode", "guided")
                store = authoring.open_store(ws)
                rev = lambda: store.load("p")["revision"]
                cli("script", "add-version", ws, "p", "--text", "Test", "--reason", "test", "--expected-revision", rev())
                scenes = root / "scenes.json"
                scenes.write_text(json.dumps([{"scene_id": "s1", "title": "One", "text": "Action", "duration_ms": 4000}]))
                cli("scenes", "set", ws, "p", "--file", scenes, "--expected-revision", rev())
                cli("stage", "approve", ws, "p", "--expected-revision", rev())
                target = "pos:scene:s1:video"
                cli("prompt", "add-version", ws, "p", "--target", target, "--text", "A boat", "--reason", "test", "--expected-revision", rev())
                cli("stage", "approve", ws, "p", "--expected-revision", rev())
                cli("stage", "approve", ws, "p", "--expected-revision", rev())
                assets = authoring.open_assets(ws)
                (ws / "media" / "seed.mp4").write_bytes(mp4_bytes())
                seed = assets.register("media/seed.mp4", "result")
                version = authoring.add_result_version(store, assets, "p", rev(), target=target, asset_id=seed["asset_id"])["version_id"]
                route = set_route(ws, "p", target, rev(), provider="magnific", model="synthetic", operation="video_generate", parameters={})
                runner = open_runner(ws)
                payload = {"spending": {"confirmed": True, **{k: route[k] for k in ("route_id", "provider", "model")}}}
                action = runner.ledger.enqueue("p", ActionRequest("vary", version, payload, rev(), "once"), scoped_grant=True)
                runner.claim("worker")
                with patch("studio.provider_download.preflight", return_value=True):
                    prepared = runner.prepare_paid(ws, action["action_id"], "worker")
                ack = {k: prepared["execution_route"][k] for k in ("provider", "model", "operation", "prompt_sha256", "basis_sha256")}
                ack.update(creation_id=ID, observation="acknowledged")
                runner.record_provider_ack(ws, action["action_id"], ack)
                store.transact("p", rev(), lambda state: state["project"].update(title="Changed"))
                data = mp4_bytes()
                proof = {"kind": "provider_export", "creation_id": ID, "zip_job_id": JOB,
                         "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
                         "width": 864, "height": 496, "duration": 4.0, "codec": "h264", "pix_fmt": "yuv420p"}
                with patch("studio.provider_export.verify_export", return_value=(data, proof)), \
                     patch("studio.authoring.open_assets", side_effect=RuntimeError("interrupted")):
                    with self.assertRaises(RuntimeError):
                        collect_provider_export(ws, runner, action["action_id"], CREATION, STATUS, JOB, META)
                with patch("studio.provider_export.verify_export", side_effect=AssertionError("no repeat GET")):
                    result = collect_provider_export(ws, runner, action["action_id"], CREATION, STATUS, JOB, META)
                self.assertEqual(result["collection"], "conflict")
                self.assertEqual(recovered_preview(ws, runner, action["action_id"])["representation"], "provider_export")
                resolution = resolve_conflict(ws, runner, action["action_id"], choice, rev(), state_dir=root / "family")
                self.assertEqual(resolution["collection"], "resolved_" + choice)
                results = store.load("p")["video_results"]
                self.assertEqual(len(results), 2 if choice == "adopt" else 1)
                if choice == "adopt":
                    self.assertIn("оригинал не подтверждён", results[-1]["caption"])


if __name__ == "__main__":
    unittest.main()

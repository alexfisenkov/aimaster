"""Public CLI/HTTP integration on an isolated synthetic workspace."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from test_library import png_bytes


SCRIPTS = Path(__file__).resolve().parent
STUDIO = SCRIPTS / "creator_studio.py"
GUIDES = SCRIPTS / "guide_registry.py"
OPERATOR = SCRIPTS / "creator_studio_operator.py"


class FamilyAcceptance(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.ws = Path(temporary.name) / "space with spaces"

    def run_json(self, script, *args, success=True):
        result = subprocess.run([sys.executable, str(script), *map(str, args)],
                                capture_output=True, text=True, timeout=25)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return result, json.loads(result.stdout) if result.returncode == 0 else None

    def test_exact_project_dashboard_and_explicit_materials_choice(self):
        self.run_json(STUDIO, "workspace", "init", self.ws)
        _, created = self.run_json(STUDIO, "project", "create", self.ws, "small-film",
                                   "--title", "Synthetic film", "--type", "video", "--mode", "autopilot")
        self.assertEqual(created["revision"], 0)
        _, choice = self.run_json(STUDIO, "project", "set-assembly-mode", self.ws, "small-film",
                                  "--mode", "materials", "--expected-revision", 0)
        self.assertEqual(choice["revision"], 1)
        failed, _ = self.run_json(STUDIO, "project", "set-assembly-mode", self.ws, "small-film",
                                  "--mode", "montage", "--expected-revision", 0, success=False)
        self.assertNotEqual(failed.returncode, 0)

        server = subprocess.Popen([sys.executable, str(STUDIO), "serve", str(self.ws), "--port", "0"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def stop_server():
            if server.poll() is None:
                server.terminate()
                server.wait(timeout=10)
            server.stdout.close()
            server.stderr.close()
        self.addCleanup(stop_server)
        first_line = []
        reader = threading.Thread(target=lambda: first_line.append(server.stdout.readline()), daemon=True)
        reader.start()
        reader.join(timeout=10)
        self.assertFalse(reader.is_alive(), "dashboard did not report a URL within 10 seconds")
        self.assertTrue(first_line and first_line[0], "dashboard exited before reporting a URL")
        address = json.loads(first_line[0])["base_url"]
        with urllib.request.urlopen(address + "/api/projects/small-film/snapshot", timeout=10) as response:
            payload = json.load(response)
        self.assertIn("small-film", json.dumps(payload))
        self.assertIn("materials", json.dumps(payload))
        with urllib.request.urlopen(address + "/api/operator", timeout=10) as response:
            operator = json.load(response)
        self.assertFalse(operator["available"])

    def test_builtin_guide_scope_and_user_library_survive_copy(self):
        self.run_json(STUDIO, "workspace", "init", self.ws)
        _, listed = self.run_json(GUIDES, "--workspace", self.ws, "list", "--include-builtin")
        self.assertTrue(any(entry["ref"].startswith("builtin:") for entry in listed["entries"]))
        _, wrong = self.run_json(GUIDES, "--workspace", self.ws, "match", "--include-builtin",
                                 "--kind", "prompt", "--modality", "video", "--task", "generate",
                                 "--provider", "magnific", "--model", "imagen-nano-banana-2-1",
                                 "--version", "2.1")
        self.assertEqual(wrong["matches"], [])

        sample = self.ws / "media" / "prop.png"
        sample.write_bytes(png_bytes())
        _, added = self.run_json(STUDIO, "library", "add", self.ws, "--kind", "product",
                                 "--label", "Synthetic prop", "--file", sample,
                                 "--notes", "Test-only object", "--tag", "ceramic")
        _, found = self.run_json(STUDIO, "library", "match", self.ws, "--text", "ceramic prop")
        self.assertIn(added["library_id"], [item["library_id"] for item in found["matches"]])
        _, entries = self.run_json(STUDIO, "library", "list", self.ws)
        self.assertEqual(entries["entries"][0]["notes"], "Test-only object")


if __name__ == "__main__":
    unittest.main()

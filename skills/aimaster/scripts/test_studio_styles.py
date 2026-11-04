"""The shipped dashboard stylesheet is generated and cannot silently drift."""
from __future__ import annotations

import tempfile
import unittest
from html.parser import HTMLParser
import json
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from build_studio_styles import SOURCE_PATHS, build_artifacts, check_artifacts

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.family_setup.packages import digest_tree


class StudioStylesTests(unittest.TestCase):
    def test_autocrlf_checkout_keeps_guide_and_bundle_bytes(self):
        root = Path(__file__).resolve().parents[3]
        paths = [".gitattributes", "skills/aimaster/guides/catalog.json",
                 "skills/aimaster/guides/authored/gemini-images.md",
                 "skills/aimaster/studio/family_setup/packages.py",
                 "skills/aimaster/studio/static/styles/studio-bundle.css",
                 "skills/aimaster/studio/static/styles/studio-bundle.manifest.json",
                 "skills/aimaster/studio/static/fonts/onest-latin-wght-normal.woff2",
                 "skills/aimaster/studio/montage/fonts/OFL.txt"]
        paths += ["skills/aimaster/studio/static/" + name for name in SOURCE_PATHS]
        with tempfile.TemporaryDirectory() as tmp:
            fixture, checkout = Path(tmp) / "fixture", Path(tmp) / "checkout"
            for name in paths:
                target = fixture / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / name, target)
            commands = [(["git", "init", "-q"], fixture),
                        (["git", "config", "user.name", "Fixture"], fixture),
                        (["git", "config", "user.email", "fixture@example.invalid"], fixture),
                        (["git", "add", "."], fixture),
                        (["git", "commit", "-qm", "fixture"], fixture),
                        (["git", "-c", "core.autocrlf=true", "clone", "-q", "--no-hardlinks", str(fixture), str(checkout)], Path(tmp))]
            for command, cwd in commands:
                result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode, 0, f"{command}: {result.stderr[-300:]}")
            for name in paths:
                self.assertEqual((checkout / name).read_bytes(), (fixture / name).read_bytes(), name)
            catalog = json.loads((checkout / "skills/aimaster/guides/catalog.json").read_text(encoding="utf-8"))
            guide = checkout / "skills/aimaster/guides" / catalog["entries"][0]["path"]
            self.assertEqual(hashlib.sha256(guide.read_bytes()).hexdigest(), catalog["entries"][0]["sha256"])
            self.assertEqual(digest_tree(fixture / "skills/aimaster"), digest_tree(checkout / "skills/aimaster"))
            self.assertTrue(check_artifacts(checkout / "skills/aimaster/studio/static"))

    def test_document_requests_one_shipped_stylesheet(self):
        static = Path(__file__).resolve().parents[1] / "studio" / "static"
        class Styles(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links = []
            def handle_starttag(self, tag, attrs):
                values = dict(attrs)
                if tag == "link" and values.get("rel") == "stylesheet":
                    self.links.append(values["href"])
        parsed = Styles()
        parsed.feed((static / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(parsed.links, ["/static/styles/studio-bundle.css"])

    def test_bundle_uses_original_order_and_keeps_font_url(self):
        static = Path(__file__).resolve().parents[1] / "studio" / "static"
        bundle, manifest = build_artifacts(static)
        self.assertEqual(len(manifest["sources"]), 19)
        self.assertEqual(manifest["sources"][0]["path"], "styles/tokens.css")
        self.assertEqual(manifest["sources"][-1]["path"], "styles/v2/family.css")
        self.assertIn(b"url('/static/fonts/onest-cyrillic-wght-normal.woff2')", bundle)
        self.assertTrue(check_artifacts(static))

    def test_stale_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            static = Path(tmp)
            for index, path in enumerate(SOURCE_PATHS):
                source = static / path
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_text(f".p{index} {{ order: {index}; }}\n", encoding="utf-8")
            bundle, manifest = build_artifacts(static)
            (static / "styles/studio-bundle.css").write_bytes(bundle)
            (static / "styles/studio-bundle.manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.assertTrue(check_artifacts(static))
            (static / SOURCE_PATHS[4]).write_text(".changed { color: black; }\n", encoding="utf-8")
            self.assertFalse(check_artifacts(static))
            (static / SOURCE_PATHS[4]).write_text(".changed { background: url('../x.png'); }\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "URL needs rebasing"):
                build_artifacts(static)

    def test_crlf_checkout_does_not_mark_same_styles_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            static = Path(tmp)
            for index, path in enumerate(SOURCE_PATHS):
                source = static / path
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(f".p{index} {{ color: black; }}\r\n".encode())
            bundle, manifest = build_artifacts(static)
            (static / "styles/studio-bundle.css").write_bytes(bundle.replace(b"\n", b"\r\n"))
            (static / "styles/studio-bundle.manifest.json").write_bytes(
                (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode().replace(b"\n", b"\r\n"))
            self.assertEqual(manifest["canonical_eol"], "LF")
            self.assertTrue(check_artifacts(static))


if __name__ == "__main__":
    unittest.main()

"""Public guide bundle contracts: integrity, scope, and standalone content."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parent.parent / "guides"
sys.path.insert(0, str(ROOT.parent))
from studio.guide_catalog import match  # noqa: E402


class GuideBundleTest(unittest.TestCase):
    def test_catalog_covers_authored_families_with_full_sources(self):
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        entries = catalog["entries"]
        required = {
            "gemini-images", "marketplace-cards", "midjourney", "seedance-2",
            "kling-3", "veo", "grok-aurora", "suno", "elevenlabs",
            "ugc-scenarios", "expert-scenarios", "cinemaster", "image-quality",
            "youtube-metadata", "seedream-5-pro", "higgsfield", "magnific",
            "gpt-image", "syntx-director-v5",
        }
        self.assertTrue(required <= {entry["id"] for entry in entries})
        self.assertEqual(len(entries), len({entry["id"] for entry in entries}))
        for entry in entries:
            with self.subTest(entry=entry["id"]):
                path = ROOT / entry["path"]
                self.assertTrue(path.is_file())
                data = path.read_bytes()
                self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
                self.assertGreater(len(data), 900)
                provenance = entry["provenance"]
                self.assertIn("reviewed_at", provenance)
                self.assertIn("changes", provenance)
                self.assertIn("original_sha256", provenance)

    def test_public_bundle_has_no_private_absolute_paths(self):
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotRegex(text, r"/Users/AlexFisenkov(?:_1)?/")
                self.assertNotRegex(text, r"(?i)(?:api[_ -]?key|token|password)\s*[:=]\s*['\"][A-Za-z0-9_-]{20,}")

    def test_supplements_are_separate_and_dated(self):
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        ids = {entry["id"] for entry in catalog["entries"]}
        for required in ("seedance-2-5", "kling-4", "grok-imagine", "suno-v6", "elevenlabs-current"):
            self.assertIn(required, ids)
        for entry in catalog["entries"]:
            if entry["id"] in {"seedance-2-5", "kling-4", "grok-imagine", "suno-v6", "elevenlabs-current", "seedream-5-pro", "higgsfield", "magnific", "gpt-image"}:
                self.assertTrue(entry["provenance"]["official_urls"])

    def test_director_keeps_unique_full_modules_without_confirmed_third_party_sections(self):
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        entries = {entry["id"]: entry for entry in catalog["entries"]}
        minimum_bytes = {
            "syntx-director-v5-01": 90000,
            "syntx-director-v5-04": 70000,
            "syntx-director-v5-05": 230000,
            "syntx-director-v5-06": 450000,
            "syntx-director-v5-07": 100000,
            "syntx-director-v5-08": 150000,
            "personal-lt-style": 25000,
        }
        for guide_id, minimum in minimum_bytes.items():
            with self.subTest(guide_id=guide_id):
                data = (ROOT / entries[guide_id]["path"]).read_bytes()
                self.assertGreater(len(data), minimum)
        all_text = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.rglob("*.md"))
        self.assertNotIn("Made with love and Ruby on Rails. DEV Community", all_text)
        self.assertNotIn("Source:** `ИНСТРУКЦИЯ - Вася", all_text)
        self.assertNotIn("liza.tkachyk", all_text)

    def test_model_methods_match_verified_aggregator_routes_only_at_exact_scope(self):
        cases = (
            ("prompt", "image", "generate", "magnific", "nano-banana", "imagen-nano-banana-2-1", "2.1", "nano-banana-2-1-magnific"),
            ("prompt", "video", "generate", "magnific", "seedance", "pro-2.5", "2.5", "seedance-2-5-magnific"),
            ("prompt", "image", "generate", "syntx", "banana", "banana-2.1", "2.1", "nano-banana-2-1-syntx"),
            ("prompt", "video", "generate", "syntx", "seedance", "seedance-2.5", "2.5", "seedance-2-5-syntx"),
            ("prompt", "video", "generate", "higgsfield", "seedance", None, "2.5", "seedance-2-5-higgsfield"),
        )
        with tempfile.TemporaryDirectory() as workspace:
            for kind, modality, task, provider, family, model, version, expected in cases:
                scope = dict(kind=kind, modality=modality, task=task, provider=provider,
                             model_family=family, model=model, version=version)
                with self.subTest(route=expected):
                    matches = match(workspace, SimpleNamespace(**scope))["matches"]
                    self.assertIn(expected, {entry["id"] for entry in matches})
                    for wrong in (dict(version="unknown"), dict(modality="audio"), dict(task="unrelated")):
                        invalid = dict(scope, **wrong)
                        matches = match(workspace, SimpleNamespace(**invalid))["matches"]
                        self.assertNotIn(expected, {entry["id"] for entry in matches})
                    if model is not None:
                        invalid = dict(scope, model="wrong-model")
                        matches = match(workspace, SimpleNamespace(**invalid))["matches"]
                        self.assertNotIn(expected, {entry["id"] for entry in matches})

    def test_face_style_has_full_safe_method(self):
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        entry = next(item for item in catalog["entries"] if item["id"] == "visual-reference-style")
        self.assertEqual(entry["kind"], "scenario")
        self.assertIn("image", entry["modalities"])
        text = (ROOT / entry["path"]).read_text(encoding="utf-8")
        self.assertGreater(len(text), 5500)
        for term in ("согласие", "референс", "консистентност", "не вывод"):
            self.assertIn(term, text.lower())


if __name__ == "__main__":
    unittest.main()

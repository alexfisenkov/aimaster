#!/usr/bin/env python3
"""Regression tests for provider-native reference binding preflight."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate_reference_bindings.py")


class ReferenceBindingCliTests(unittest.TestCase):
    def run_validator(self, manifest: dict, prompt: str, context: dict | None = None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = root / "binding.json"
            prompt_path = root / "prompt.txt"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            prompt_path.write_text(prompt, encoding="utf-8")
            command = [sys.executable, str(SCRIPT), str(manifest_path), str(prompt_path)]
            if context is not None:
                context_path = root / "context.json"
                context_path.write_text(json.dumps(context), encoding="utf-8")
                command.extend(["--context", str(context_path)])
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )

    @staticmethod
    def manifest(*references: dict, binding_source: str = "plain_text") -> dict:
        normalized = []
        for index, reference in enumerate(references, start=1):
            item = dict(reference)
            item.setdefault("reference_id", f"REF_{index:02d}")
            item.setdefault("asset_id", f"asset-{index:02d}")
            normalized.append(item)
        return {
            "schema_version": 1,
            "operation_id": "op-test-1",
            "provider": "provider-under-test",
            "route": "route-under-test",
            "model": "model-under-test",
            "binding_source": binding_source,
            "observed_at": "2026-09-21T00:00:00Z",
            "state_revision": 7,
            "references": normalized,
        }

    def test_fails_when_any_required_inline_tag_is_missing(self) -> None:
        result = self.run_validator(
            self.manifest(
                {"canonical": "@IMG_01", "native": "@char1", "role": "Alexander", "transport": "inline"},
                {"canonical": "@IMG_02", "native": "@img1", "role": "cafe", "transport": "inline"},
            ),
            "Show @char1 in the cafe.",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("@img1", result.stderr)

    def test_passes_only_when_all_inline_tags_are_exactly_present(self) -> None:
        result = self.run_validator(
            self.manifest(
                {"canonical": "@IMG_01", "native": "@char1", "role": "Alexander", "transport": "inline"},
                {"canonical": "@IMG_02", "native": "@img1", "role": "cafe", "transport": "inline"},
            ),
            "@char1 (Alexander) enters @img1 (the cafe).",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["inline_references"], 2)

    def test_does_not_accept_a_longer_lookalike_tag(self) -> None:
        result = self.run_validator(
            self.manifest(
                {"canonical": "@IMG_01", "native": "@img1", "role": "cafe", "transport": "inline"},
            ),
            "Use @img10 as the cafe.",
        )
        self.assertEqual(result.returncode, 2)

    def test_structured_reference_uses_slot_instead_of_prompt_tag(self) -> None:
        result = self.run_validator(
            self.manifest(
                {"canonical": "@VID_01", "slot": "video_reference[0]", "role": "continue", "transport": "structured"},
                binding_source="structured_schema",
            ),
            "Continue the previous scene.",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["structured_references"], 1)

    def test_structured_reference_rejects_canonical_tag_in_native_prompt(self) -> None:
        result = self.run_validator(
            self.manifest(
                {"canonical": "@VID_01", "slot": "video_reference[0]", "role": "continue", "transport": "structured"},
                binding_source="structured_schema",
            ),
            "Continue from @VID_01.",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unresolved canonical", result.stderr)

    def test_rejects_duplicate_native_inline_tags(self) -> None:
        result = self.run_validator(
            self.manifest(
                {"canonical": "@IMG_01", "native": "@img1", "role": "person", "transport": "inline"},
                {"canonical": "@IMG_02", "native": "@img1", "role": "place", "transport": "inline"},
            ),
            "@img1",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate native", result.stderr)

    def test_rejects_unresolved_canonical_tag(self) -> None:
        result = self.run_validator(
            self.manifest(
                {"canonical": "@IMG_01", "native": "@img1", "role": "cafe", "transport": "inline"},
            ),
            "Use @IMG_01 together with @img1.",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unresolved canonical", result.stderr)

    def test_rich_mention_requires_observed_chip(self) -> None:
        result = self.run_validator(
            self.manifest(
                {
                    "canonical": "@IMG_01",
                    "native": "@char1",
                    "role": "Alexander",
                    "transport": "inline",
                    "chip_verified": False,
                },
                binding_source="rich_ui",
            ),
            "Keep @char1 as Alexander.",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("chip", result.stderr)

    def test_generation_without_references_is_valid(self) -> None:
        result = self.run_validator(self.manifest(), "A clean establishing shot.")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["references"], 0)

    def test_unlisted_canonical_tag_is_rejected_even_with_empty_manifest(self) -> None:
        result = self.run_validator(self.manifest(), "Use @IMG_01 as the person.")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unresolved canonical", result.stderr)

    def test_missing_operation_provenance_is_rejected(self) -> None:
        manifest = self.manifest()
        del manifest["provider"]
        result = self.run_validator(manifest, "A clean establishing shot.")
        self.assertEqual(result.returncode, 2)
        self.assertIn("provider", result.stderr)

    def test_claimed_context_must_match_every_reference_and_asset(self) -> None:
        manifest = self.manifest(
            {"canonical": "@IMG_01", "native": "@img1", "role": "person", "transport": "inline"},
        )
        context = {
            "action_id": "op-test-1",
            "context": {
                "state_revision": 7,
                "positions": [{
                    "scene_id": "s2",
                    "references": [
                        {"reference_id": "REF_01", "tag": "IMG_01", "asset_id": "asset-01"},
                        {"reference_id": "REF_02", "tag": "IMG_02", "asset_id": "asset-02"},
                    ],
                    "frames": [],
                }],
            },
        }
        result = self.run_validator(manifest, "Use @img1.", context)
        self.assertEqual(result.returncode, 2)
        self.assertIn("claimed context", result.stderr)

    def test_claimed_context_passes_with_exact_reference_set(self) -> None:
        manifest = self.manifest(
            {"canonical": "@IMG_01", "native": "@img1", "role": "person", "transport": "inline"},
        )
        context = {
            "action_id": "op-test-1",
            "untrusted_input": {"context": {
                "state_revision": 7,
                "positions": [{
                    "references": [
                        {"reference_id": "REF_01", "tag": "IMG_01", "asset_id": "asset-01"},
                    ],
                    "frames": [],
                }],
            }},
        }
        result = self.run_validator(manifest, "Use @img1.", context)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

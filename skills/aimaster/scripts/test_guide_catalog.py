"""Public CLI contracts for builtin/user guide selection; fixtures are synthetic."""
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import guide_registry


class GuideCatalogTests(unittest.TestCase):
    def test_namespaces_exact_scope_and_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            instructions = root / "instructions"
            instructions.mkdir()
            builtin = root / "builtin"
            builtin.mkdir()
            text = "Synthetic guide / инструкция\n"
            (instructions / "guide.md").write_bytes(text.encode("utf-8"))
            (builtin / "guide.md").write_bytes(text.encode("utf-8"))
            entry = dict(id="same", title="Same title", path="guide.md",
                         sha256=hashlib.sha256(text.encode()).hexdigest(), kind="prompt",
                         modalities=["image"], tasks=["generate"], providers=["test"],
                         model_families=["family"], models=["model"], versions=["1"],
                         family_all_versions=False, model_agnostic=False)
            (instructions / "guides.json").write_text(json.dumps(dict(
                schema_version=1, revision=1, entries=[entry])), encoding="utf-8")
            catalog = builtin / "catalog.json"
            catalog.write_text(json.dumps(dict(schema_version=1, bundle_version="test",
                entries=[dict(entry, provenance={"author_source_title": "Synthetic"})])), encoding="utf-8")
            def run(*args):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = guide_registry.main(["--workspace", str(root), *args])
                return code, json.loads(output.getvalue())
            flags = ["--include-builtin", "--builtin-catalog", str(catalog)]
            code, result = run("list", *flags)
            self.assertEqual(code, 0, result)
            self.assertEqual({e["ref"] for e in result["entries"]}, {"builtin:same", "user:same"})
            self.assertNotIn("namespace", run("list")[1]["entries"][0])
            scope = ["--kind", "prompt", "--modality", "image", "--task", "generate",
                     "--provider", "test", "--model-family", "family", "--model", "model", "--version", "1"]
            self.assertEqual(len(run("match", *scope, *flags)[1]["matches"]), 2)
            self.assertEqual(run("match", *scope[:-1], "unknown", *flags)[1]["matches"], [])
            motion_scope = ["video" if value == "image" else value for value in scope]
            self.assertEqual(run("match", *motion_scope, *flags)[1]["matches"], [])
            (builtin / "guide.md").write_text("tampered", encoding="utf-8")
            (instructions / "guide.md").unlink()
            result = run("match", *scope, *flags)[1]
            self.assertEqual(result["matches"], [])
            self.assertEqual({e["ref"] for e in result["stale"]}, {"builtin:same", "user:same"})

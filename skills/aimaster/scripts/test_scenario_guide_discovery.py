"""Public guide CLI contracts for provider-independent scenarios."""
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import guide_registry


class ScenarioGuideDiscoveryTests(unittest.TestCase):
    def run_cli(self, workspace, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = guide_registry.main(["--workspace", str(workspace), *args])
        return code, json.loads(output.getvalue())

    def test_builtin_scenario_discovery_without_provider_keeps_exact_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            def builtin(task, *, provider=None, kind="scenario"):
                args = ["match", "--include-builtin", "--kind", kind,
                        "--modality", "scenario", "--task", task]
                if provider is not None:
                    args.extend(["--provider", provider])
                return self.run_cli(workspace, *args)

            code, result = builtin("ugc-script")
            self.assertEqual(code, 0, result)
            self.assertEqual({item["id"] for item in result["matches"]}, {"ugc-scenarios", "ugc-gpts"})
            code, result = builtin("expert-script")
            self.assertEqual(code, 0, result)
            self.assertEqual({item["id"] for item in result["matches"]}, {"expert-scenarios", "expert-gpts"})
            self.assertEqual({item["id"] for item in builtin("ugc-script", provider="syntx")[1]["matches"]},
                             {"ugc-scenarios", "ugc-gpts", "syntx-director-v5-05"})
            self.assertEqual({item["id"] for item in builtin("ugc-script", provider="higgsfield")[1]["matches"]},
                             {"ugc-scenarios", "ugc-gpts"})
            self.assertEqual(builtin("ugc-script", kind="prompt")[1]["matches"], [])
            self.assertEqual(builtin("ugc")[1]["matches"], [])

    def test_user_generic_scenario_is_discoverable_without_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            instructions = workspace / "instructions"
            instructions.mkdir()
            guide = instructions / "guide.md"
            text = "Synthetic provider-independent scenario guide.\n"
            guide.write_text(text, encoding="utf-8")
            code, registered = self.run_cli(workspace, "register", "--id", "generic-scenario",
                "--title", "Generic scenario", "--path", "guide.md", "--kind", "scenario",
                "--modality", "scenario", "--task", "ugc-script", "--provider", "*", "--model-agnostic")
            self.assertEqual(code, 0, registered)
            code, result = self.run_cli(workspace, "match", "--kind", "scenario", "--modality", "scenario",
                                        "--task", "ugc-script")
            self.assertEqual(code, 0, result)
            self.assertEqual([entry["id"] for entry in result["matches"]], ["generic-scenario"])


if __name__ == "__main__":
    unittest.main()

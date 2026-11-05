"""Private host packages are the same executable in setup and the operator."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import authoring
from studio.family_setup import providers
from studio.operator import Operator, status
from studio.operator_adapters import state_digest
from studio.ledger import ActionRequest
from studio.runner import open_runner


class PrivateHostTests(unittest.TestCase):
    def test_private_host_executes_free_job_for_both_hosts_without_path_install(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is not installed on this test runner")
        for agent, package in (("codex", "@openai/codex"), ("claude", "@anthropic-ai/claude-code")):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(); ws = root / "workspace Ω"; ws.mkdir()
                store = authoring.open_store(ws)
                authoring.create_project(store, "p", "Synthetic", "photo", "guided")
                runner = open_runner(ws)
                action = runner.ledger.enqueue("p", ActionRequest("continue-in-chat", "scenario", {}, 0, "free"))
                family = root / "family"; package_root = family / "tools" / agent / "node_modules" / package
                package_root.mkdir(parents=True)
                (package_root / "package.json").write_text(json.dumps({"name":package,"bin":{agent:"cli.js"}}))
                result = {key:action[key] for key in ("action_id","project_id","action_type","target_id")}
                result.update(base_revision=0, revision=0, status="succeeded", output_ids=[], reply="Read only.", state_sha256=state_digest(store.load("p")))
                output = ("\n".join(json.dumps(e) for e in ({"type":"item.completed","item":{"type":"agent_message","text":json.dumps(result)}},{"type":"turn.completed"}))
                          if agent == "codex" else json.dumps({"subtype":"success","structured_output":result}))
                (package_root / "cli.js").write_text("process.stdin.resume(); process.stdin.on('end',()=>process.stdout.write(" + json.dumps(output) + "));")
                with patch.object(providers, "program", side_effect=lambda name: node if name == "node" else None), \
                        patch("shutil.which", return_value=None):
                    deps = providers.dependencies(family, root, [agent], False)
                    self.assertEqual(deps["hosts"][agent], [node, str(package_root / "cli.js")])
                    with Operator(ws, agent=agent, state_dir=family) as controller:
                        self.assertTrue(status(ws)["available"], "private installation was ignored by the executor")
                        self.assertEqual(controller.step()["status"], "succeeded")
                    (package_root / "cli.js").unlink()
                    with Operator(ws, agent=agent, state_dir=family):
                        self.assertFalse(status(ws)["available"])


if __name__ == "__main__":
    unittest.main()

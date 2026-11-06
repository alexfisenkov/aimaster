"""The assembly-browser fixture must reach assembly through the public CLI."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smoke_clean_machine import clean_env
from smoke_kit import cli
from smoke_montage import MONTAGE_PROJECT, project_ready_for_assembly
from studio import authoring, domain
from studio.domain_positions import current_member, position_specs


class MontageSmokeContractTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_real_two_scene_fixture_records_choice_and_current_motion_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home, workspace = root / "home", root / "workspace"
            home.mkdir()
            env = clean_env(home)
            cli(env, "workspace", "init", workspace)
            revision = project_ready_for_assembly(env, workspace)
            state = authoring.open_store(workspace).load(MONTAGE_PROJECT)
            self.assertEqual(state["revision"], revision)
            self.assertEqual(domain.derive_view_stage(state)["current_stage"], "assembly")
            second = next(scene for scene in state["scenes"] if scene["scene_id"] == "s2")
            self.assertEqual(second["continuity_strategy"], "independent")
            spec = next(s for s in position_specs(state) if s.get("scene_id") == "s2" and s.get("kind") == "video")
            prompt = current_member(state, spec, "prompt")
            self.assertFalse(domain.compute_prompt_stale(state, prompt, spec))
            self.assertEqual(prompt["status"], "approved")


if __name__ == "__main__":
    unittest.main()

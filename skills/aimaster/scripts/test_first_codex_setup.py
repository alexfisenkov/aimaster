"""Fresh-install Codex registration stays inside synthetic roots."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio.family_setup import packages, providers
from studio.family_setup.service import setup


class FirstCodexSetupTests(unittest.TestCase):
    def test_exact_readback_after_nonzero_or_timeout_is_configured_but_not_authenticated(self):
        for exit_code in (1, 124):
            with self.subTest(exit_code=exit_code), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                path = home / ".codex/config.toml"

                def fake_codex(argv, *, env, **kwargs):
                    path.write_text('[mcp_servers.magnific]\nurl = "https://mcp.magnific.com"\n')
                    return exit_code, "", "private provider detail must not escape"

                result = providers.register_connector(home, home / "test-state", "codex", "magnific",
                    {"url": "https://mcp.magnific.com"}, ["fake-codex"], runner=fake_codex)
                self.assertTrue(result["configured"], result)
                self.assertEqual(result["status"], "auth_pending")
                self.assertEqual(result["registration_warning"], "registration_command_nonzero")
                self.assertEqual(result["registration_exit_code"], exit_code)
                self.assertFalse(result["authenticated"])
                self.assertFalse(result["available"])
                self.assertNotIn("private provider detail", str(result))

    def test_nonzero_with_wrong_or_missing_entry_remains_failed(self):
        fixtures = (
            '[mcp_servers.magnific]\nurl = "https://wrong.example/mcp"\n',
            None,
        )
        for config_text in fixtures:
            with self.subTest(config_text=config_text), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                path = home / ".codex/config.toml"

                def fake_codex(argv, *, env, **kwargs):
                    if config_text is not None:
                        path.write_text(config_text)
                    return 1, "", ""

                result = providers.register_connector(home, home / "test-state", "codex", "magnific",
                    {"url": "https://mcp.magnific.com"}, ["fake-codex"], runner=fake_codex)
                self.assertFalse(result["configured"], result)
                self.assertFalse(result["authenticated"])
                self.assertFalse(result["available"])
                self.assertEqual(result["status"], "registration_failed")

    def test_setup_creates_missing_codex_home_and_reads_back_preserving_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home, state_dir = root / "test-home", root / "test-state"
            home.mkdir()
            state_dir.mkdir()
            env = dict(os.environ, AIMASTER_CONFIG_HOME=str(state_dir))
            config = home / ".codex/config.toml"
            # The config file is absent, as on a clean install; its directory
            # must be prepared before the normal Codex CLI registration.
            deps = {"hosts": {"codex": ["fake-codex"]}, "programs": {}, "steps": []}

            def fake_codex(argv, *, env, **kwargs):
                codex_home = Path(env["CODEX_HOME"])
                if not codex_home.is_dir():
                    return 1, "", "failed to load configuration: CODEX_HOME does not exist"
                self.assertEqual(argv, ["fake-codex", "mcp", "add", "magnific", "--url",
                                        "https://mcp.magnific.com"])
                config.write_text('[mcp_servers.magnific]\nurl = "https://mcp.magnific.com"\n')
                return 0, "", ""

            receipt = {"package": str(root / "unused-package"), "fingerprint": "f" * 64,
                       "targets": [], "origin_status": "local"}

            def install_package(*args, publish=None, **kwargs):
                publish(receipt)
                return receipt

            with mock.patch.dict(os.environ, env, clear=False), \
                    mock.patch.object(providers, "dependencies", return_value=deps), \
                    mock.patch.object(packages, "source_identity", return_value={"origin_status": "local"}), \
                    mock.patch.object(packages, "install_package", side_effect=install_package), \
                    mock.patch.object(providers, "program", return_value="fake-codex"):
                result = setup(Path(__file__).resolve().parents[1], home=home, state_dir=state_dir,
                               agents=("codex",), selected=("magnific",), aiediting=False,
                               runner=fake_codex)

            self.assertTrue(result["providers"]["magnific"]["codex"]["configured"], result)
            self.assertTrue(result["ok"], result)
            parsed = providers.read_config(home, "codex")[1]
            self.assertEqual(parsed["mcp_servers"]["magnific"]["url"], "https://mcp.magnific.com")
            self.assertEqual(config.parent, home / ".codex")

    def test_existing_codex_config_entry_survives_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            config = home / ".codex/config.toml"
            config.parent.mkdir()
            config.write_text('[mcp_servers.keep_me]\nurl = "https://example.invalid/mcp"\n')

            def fake_codex(argv, *, env, **kwargs):
                config.write_text(config.read_text() +
                                  '\n[mcp_servers.magnific]\nurl = "https://mcp.magnific.com"\n')
                return 0, "", ""

            result = providers.register_connector(home, home / "test-state", "codex", "magnific",
                {"url": "https://mcp.magnific.com"}, ["fake-codex"], runner=fake_codex)
            parsed = providers.read_config(home, "codex")[1]
            self.assertTrue(result["configured"], result)
            self.assertEqual(parsed["mcp_servers"]["keep_me"]["url"], "https://example.invalid/mcp")
            self.assertEqual(parsed["mcp_servers"]["magnific"]["url"], "https://mcp.magnific.com")


if __name__ == "__main__":
    unittest.main()

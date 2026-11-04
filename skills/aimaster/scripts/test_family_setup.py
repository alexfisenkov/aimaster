"""Family setup contracts, always inside a synthetic home."""
import io
import json
import sys
import tempfile
import subprocess
import hashlib
import shutil
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install
import family_setup
from studio.family_setup import providers, packages
from studio.family_setup.service import setup


class StandaloneTests(unittest.TestCase):
    def test_human_output_names_the_actual_blocker(self):
        output = io.StringIO()
        report = {"ok": False, "status": "partial", "providers": {"magnific": {"codex": {
            "status": "needs_host", "next_step": "Install Codex CLI, then retry setup --install-deps."}}}}
        with mock.patch.object(family_setup, "setup", return_value=report), redirect_stdout(output):
            code = family_setup.main(["setup", "--locale", "en"])
        self.assertEqual(code, 1)
        self.assertIn("magnific/codex: needs_host", output.getvalue())
        self.assertIn("Install Codex CLI", output.getvalue())

    def test_bootstrap_can_replace_the_standalone_folder_it_is_running_from(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            skill = home / ".agents/skills/aimaster"
            shutil.copytree(Path(__file__).parent.parent, skill,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            other = home / ".claude/skills/aimaster"
            other.parent.mkdir(parents=True)
            try:
                other.symlink_to(skill, target_is_directory=True)
            except OSError:
                pass  # Native Windows without symlink rights still tests the copy bootstrap.
            env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PATH=str(home / "empty-bin"))
            result = subprocess.run([sys.executable, str(skill / "scripts/family_setup.py"), "setup",
                                     "--home", str(home), "--provider", "magnific", "--no-aiediting", "--json"],
                                    env=env, cwd=home, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertTrue(result.stdout.startswith("{"), result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "partial")
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertTrue((home / ".claude/skills/aimaster/SKILL.md").is_file())

    def test_install_accepts_skill_folder_without_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "npx навык с пробелами"
            (skill / "scripts").mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: aimaster\n---\n")
            (skill / "VERSION").write_text("2099.01.01\n")
            output = io.StringIO()
            with mock.patch.object(install, "check_deps", return_value=[]), \
                    mock.patch.object(install, "_montage_report", return_value={"ok": True}), \
                    redirect_stdout(output):
                code = install.main(["--repo", str(skill), "--home", str(root / "home"),
                                     "--skip-self-check", "--json"])
            self.assertEqual(code, 0, output.getvalue())
            self.assertTrue((root / "home/.agents/skills/aimaster/SKILL.md").is_file())
            self.assertTrue((root / "home/.claude/skills/aimaster/SKILL.md").is_file())

    def test_family_catalog_is_standalone_and_has_all_four_providers(self):
        script = Path(__file__).parent / "family_setup.py"
        with tempfile.TemporaryDirectory() as temporary:
            completed = subprocess.run([sys.executable, str(script), "catalog", "--json",
                                        "--home", temporary], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        providers = json.loads(completed.stdout)["providers"]
        self.assertEqual(set(providers), {"syntx", "higgsfield", "magnific", "fal"})
        self.assertEqual(providers["fal"]["endpoint"], "https://mcp.fal.ai/mcp-relay")
        self.assertFalse(providers["magnific"]["server_rollback"])

    def test_setup_executes_install_and_records_opt_in_without_any_host(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            output = io.StringIO()
            with mock.patch("studio.family_setup.providers.program", return_value=None), redirect_stdout(output):
                code = family_setup.main(["setup", "--home", str(home), "--provider", "magnific",
                                          "--no-aiediting", "--auto-update", "on", "--json"])
            self.assertEqual(code, 1, output.getvalue())  # partial: host is absent
            report = json.loads(output.getvalue())
            self.assertTrue((home / ".agents/skills/aimaster/SKILL.md").is_file())
            self.assertTrue((home / ".claude/skills/aimaster/SKILL.md").is_file())
            state = json.loads((home / ".config/aimaster/family.json").read_text())
            self.assertTrue(state["auto_update"]["enabled"])
            self.assertEqual(report["providers"]["magnific"]["codex"]["status"], "needs_host")


class ConnectorTests(unittest.TestCase):
    def test_install_deps_upgrades_an_unsupported_node_using_available_manager(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            executables = {"git": "/fake/git", "node": "/fake/old-node", "ffmpeg": "/fake/ffmpeg", "ffprobe": "/fake/ffprobe", "brew": "/fake/brew"}
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                if argv == ["/fake/brew", "install", "node"]:
                    executables["node"] = "/fake/new-node"
                if argv[-1] == "--version":
                    return 0, "v18.0.0" if argv[0] == "/fake/old-node" else "v24.0.0", ""
                return 0, "", ""
            with mock.patch.object(providers, "program", side_effect=executables.get), \
                    mock.patch.object(providers.sys, "platform", "darwin"), \
                    mock.patch("install_montage_node.npm_cli_js", return_value=home / "npm-cli.js"):
                result = providers.dependencies(home / "state", home, (), True, runner=runner)
            self.assertIn(["/fake/brew", "install", "node"], calls)
            self.assertEqual(result["programs"]["node"], "/fake/new-node")

    def test_npx_receipt_does_not_authorize_overwriting_modified_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            skill = home / ".agents/skills/aimaster"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_bytes(b"---\nname: aimaster\n---\n")
            blob = (skill / "SKILL.md").read_bytes()
            sha = hashlib.sha1(b"blob " + str(len(blob)).encode() + b"\0" + blob).hexdigest()
            upstream = {"tree": [{"path": "SKILL.md", "type": "blob", "sha": sha}], "truncated": False}
            (home / ".agents/.skill-lock.json").write_text(json.dumps({"version": 3, "skills": {"aimaster": {
                "source": "alexfisenkov/aimaster", "sourceType": "github", "skillFolderHash": "a" * 40}}}))
            with mock.patch.object(packages.shutil, "which", return_value=None), \
                    mock.patch.object(packages, "download", return_value=json.dumps(upstream).encode()):
                clean = packages.source_identity(skill, "aimaster", home)
                self.assertEqual(clean["origin_status"], "skills_cli")
                (skill / "personal-notes.md").write_text("synthetic personal additions")
                dirty = packages.source_identity(skill, "aimaster", home)
            self.assertEqual(dirty["origin_status"], "dirty_source")

    def test_full_setup_executes_all_four_provider_registrations_and_aiediting(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            directory = home / "state"
            syntx = directory / "syntx"
            (home / ".codex").mkdir()
            (home / ".codex/config.toml").write_text('model = "untouched"\n')
            (home / ".claude.json").write_text('{"theme":"untouched"}\n')
            deps = {"programs": {"git": "/fake/git", "node": "/fake/node", "ffmpeg": "/fake/ffmpeg", "ffprobe": "/fake/ffprobe"},
                    "npm": "/fake/npm-cli.js", "hosts": {"codex": ["fake-codex"], "claude": ["fake-claude"]}, "steps": []}
            calls = []
            def runner(argv, **kwargs):
                calls.append(argv)
                if "clone" in argv:
                    syntx.mkdir(parents=True)
                elif "get-url" in argv:
                    return 0, "https://github.com/alexfisenkov/syntx-mcp.git", ""
                elif "--porcelain" in argv:
                    return 0, "", ""
                elif "rev-parse" in argv:
                    return 0, "a" * 40, ""
                elif "build" in argv:
                    for relative in ("dist/src/transports/stdio-owner.js", "scripts/update-mcp.mjs", "scripts/print-media-mcp-config.mjs"):
                        target = syntx / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text("// synthetic fixture")
                elif len(argv) > 1 and argv[1].endswith("print-media-mcp-config.mjs"):
                    entry = {"command": "/fake/node", "args": [str(syntx / "dist/src/transports/stdio-owner.js")],
                             "env": {"SYNTX_OWNER_MEDIA_PROFILE": "all-supported", "SYNTX_SELF_UPDATE": "1", "SYNTX_LOCAL_IMAGE_ROOTS": "[]",
                                     "SYNTX_MEDIA_FFPROBE_PATH": "<absolute path>", "SYNTX_MEDIA_FFMPEG_PATH": "<absolute path>",
                                     "SYNTX_OWNER_TOPAZ_ASTRA_UPLOAD_DESTINATION": "<uploaded|hidden>"}}
                    return 0, json.dumps({"mcpServers": {"syntx": entry}}), ""
                elif argv[0] == "fake-codex":
                    name = argv[3]
                    path = providers.config_path(home, "codex")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    previous = path.read_text() if path.exists() else 'model = "untouched"\n'
                    if "--url" in argv:
                        block = f'\n[mcp_servers.{name}]\nurl = {json.dumps(argv[-1])}\n'
                    else:
                        split = argv.index("--")
                        env = {}
                        for i, value in enumerate(argv):
                            if value == "--env":
                                key, setting = argv[i + 1].split("=", 1)
                                env[key] = setting
                        block = f'\n[mcp_servers.{name}]\ncommand = {json.dumps(argv[split+1])}\nargs = {json.dumps(argv[split+2:])}\n'
                        block += f'[mcp_servers.{name}.env]\n' + ''.join(f'{k} = {json.dumps(v)}\n' for k, v in env.items())
                    path.write_text(previous + block)
                elif argv[0] == "fake-claude":
                    path = providers.config_path(home, "claude")
                    value = json.loads(path.read_text()) if path.exists() else {"theme": "untouched"}
                    if "add-json" in argv:
                        name, entry = argv[-2], json.loads(argv[-1])
                    else:
                        name, entry = argv[-2], {"type": "http", "url": argv[-1]}
                    value.setdefault("mcpServers", {})[name] = entry
                    path.write_text(json.dumps(value))
                return 0, "", ""
            def fetch(name, target):
                self.assertEqual(name, "aiediting")
                target.mkdir()
                (target / "SKILL.md").write_text('---\nname: aiediting\n---\n')
                return {"origin": "https://github.com/alexfisenkov/AIEditing.git", "revision": "b" * 40,
                        "fingerprint": packages.digest_tree(target)}
            with mock.patch.object(providers, "dependencies", return_value=deps), \
                    mock.patch.object(packages, "fetch_package", side_effect=fetch):
                result = setup(Path(__file__).parent.parent, home=home, state_dir=directory,
                               syntx_destination="hidden", runner=runner)
                count = len([c for c in calls if c[0].startswith("fake-")])
                again = setup(Path(__file__).parent.parent, home=home, state_dir=directory,
                              syntx_destination="hidden", runner=runner)
            self.assertTrue(result["ok"], result)
            self.assertTrue(again["ok"], again)
            self.assertEqual(count, 8)
            self.assertEqual(len([c for c in calls if c[0].startswith("fake-")]), count)
            self.assertEqual(set(result["providers"]), {"syntx", "higgsfield", "magnific", "fal"})
            for hosts in result["providers"].values():
                self.assertTrue(all(h["configured"] and not h["available"] and not h["authenticated"] for h in hosts.values()))
            self.assertTrue((home / ".agents/skills/aiediting/SKILL.md").is_file())
            self.assertEqual(providers.read_config(home, "codex")[1]["model"], "untouched")
            self.assertEqual(providers.read_config(home, "claude")[1]["theme"], "untouched")

    def test_repeat_setup_can_add_the_other_host_without_clobbering_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            with mock.patch.object(providers, "program", return_value=None):
                setup(Path(__file__).parent.parent, home=home, agents=("codex",), selected=("fal",), aiediting=False)
                before = packages.digest_tree(home / ".agents/skills/aimaster")
                setup(Path(__file__).parent.parent, home=home, agents=("codex", "claude"), selected=("fal",), aiediting=False)
            self.assertTrue((home / ".claude/skills/aimaster/SKILL.md").is_file())
            self.assertEqual(packages.digest_tree(home / ".agents/skills/aimaster"), before)

    def test_discovery_requires_real_probe_and_rechecks_changed_schema(self):
        from studio.family_setup.state import read_state, save_state
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            state = read_state(directory)
            state["connectors"] = {"magnific": {"expected": {"url": "https://mcp.magnific.com"}}}
            save_state(directory, state)
            record = getattr(providers, "record_discovery", None)
            self.assertTrue(callable(record), "a host-session discovery bridge is required")
            tools = [{"name": "balance", "inputSchema": {"type": "object", "properties": {}}}]
            result = record(directory, "magnific", "codex", "chat-1", tools,
                            authenticated=True, probe_succeeded=False)
            self.assertFalse(result["available"])
            result = record(directory, "magnific", "codex", "chat-2", tools,
                            authenticated=True, probe_succeeded=True)
            self.assertTrue(result["available"])
            changed = [{"name": "balance", "inputSchema": {"type": "object", "required": ["workspace"]}}]
            result = record(directory, "magnific", "codex", "chat-3", changed,
                            authenticated=True, probe_succeeded=True)
            self.assertEqual(result["status"], "schema_change_requires_review")
            self.assertFalse(result["available"])
            raw = (directory / "family.json").read_text()
            self.assertNotIn('"inputSchema"', raw)

    def test_corrupt_cli_write_restores_exact_config_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = home / ".codex/config.toml"
            path.parent.mkdir()
            before = b'# owner comment\nmodel = "synthetic-model"\n'
            path.write_bytes(before)
            def runner(argv, **kwargs):
                path.write_bytes(b"not valid TOML [")
                return 0, "", ""
            result = providers.register_connector(home, home / "state", "codex", "magnific",
                {"url": "https://mcp.magnific.com"}, ["fake-host"], runner=runner)
            self.assertEqual(result["status"], "registration_failed")
            self.assertEqual(path.read_bytes(), before)

    def test_registration_readback_repeat_and_conflict_for_both_hosts(self):
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                path = providers.config_path(home, agent)
                path.parent.mkdir(parents=True, exist_ok=True)
                before = b'# personal settings\nmodel = "keep-me"\n' if agent == "codex" else b'{"theme":"keep-me"}\n'
                path.write_bytes(before)
                calls = []
                def runner(argv, **kwargs):
                    calls.append(argv)
                    self.assertEqual(kwargs["env"]["HOME"], str(home))
                    if agent == "codex":
                        path.write_bytes(before + b'\n[mcp_servers.magnific]\nurl = "https://mcp.magnific.com"\n')
                    else:
                        path.write_text(json.dumps({"theme": "keep-me", "mcpServers": {"magnific": {"type": "http", "url": "https://mcp.magnific.com"}}}))
                    return 0, "", ""
                expected = {"url": "https://mcp.magnific.com"}
                result = providers.register_connector(home, home / "state", agent, "magnific", expected, ["fake-host"], runner=runner)
                self.assertTrue(result["configured"])
                self.assertFalse(result["authenticated"])
                self.assertFalse(result["available"])
                again = providers.register_connector(home, home / "state", agent, "magnific", expected, ["fake-host"], runner=runner)
                self.assertEqual(again["status"], "auth_pending")
                self.assertEqual(len(calls), 1)
                snapshot = path.read_bytes()
                conflict = providers.register_connector(home, home / "state", agent, "magnific", {"url": "https://mcp.fal.ai/mcp-relay"}, ["fake-host"], runner=runner)
                self.assertEqual(conflict["status"], "config_conflict")
                self.assertEqual(path.read_bytes(), snapshot)


if __name__ == "__main__":
    unittest.main()

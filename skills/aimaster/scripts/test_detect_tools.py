#!/usr/bin/env python3
"""Tests for detect_tools.py on a synthetic HOME full of fake secrets."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import detect_tools  # noqa: E402

SECRETS = [
    "sk-SECRET-env-0001",
    "Bearer SECRET-header-0002",
    "--api-key=SECRET-arg-0003",
    "SECRET-query-0004",
    "SECRET-codex-0005",
    "SECRET-gemini-0006",
    "SECRET-cursor-0007",
    "SECRET-plugin-0008",
    "SECRET-project-0009",
    "SECRET-parent-0010",
    "/Users/someone/secret-path-0011/server.js",
]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_home(root: Path) -> tuple[Path, Path]:
    home = root / "home"
    work = root / "work" / "clients" / "reel"
    work.mkdir(parents=True)
    write(home / ".claude.json", json.dumps({
        "mcpServers": {
            "higgsfield": {"type": "http", "url": "https://mcp.higgsfield.ai/mcp?token=" + SECRETS[3],
                           "headers": {"Authorization": SECRETS[1]}},
            "image-tools": {"command": "npx", "args": ["-y", "@fal-ai/mcp-server", SECRETS[2], SECRETS[10]],
                            "env": {"FAL_KEY": SECRETS[0]}},
            "openai-docs": {"type": "http", "url": "https://developers.openai.com/mcp"},
        },
        "projects": {
            str(work.parent): {"mcpServers": {"proj-kling": {
                "command": "node", "args": ["kling-mcp"], "env": {"KLING_TOKEN": SECRETS[8]}}}},
            "/unrelated/folder": {"mcpServers": {"runway": {"command": "x"}}},
        },
    }))
    write(root / "work" / ".mcp.json", json.dumps({"mcpServers": {
        "syntx": {"type": "sse", "url": "https://api.syntx.ai/sse", "headers": {"X-Key": SECRETS[9]}}}}))
    write(home / ".codex" / "config.toml",
          '[mcp_servers.replicate]\ncommand = "npx"\nargs = ["replicate-mcp"]\n'
          '[mcp_servers.replicate.env]\nREPLICATE_API_TOKEN = "' + SECRETS[4] + '"\n'
          '[mcp_servers.luma]\nurl = "https://mcp.lumalabs.ai/v1"\n')
    write(home / ".gemini" / "settings.json", json.dumps({"mcpServers": {
        "voice": {"httpUrl": "https://api.elevenlabs.io/mcp", "headers": {"xi-api-key": SECRETS[5]}}}}))
    write(home / ".cursor" / "mcp.json", "{ this is not json " + SECRETS[6])
    plugins = home / ".claude" / "plugins"
    install = plugins / "cache" / "market" / "magnific-kit" / "1.0.0"
    write(install / ".mcp.json", json.dumps({"mcpServers": {
        "magnific": {"type": "http", "url": "https://mcp.magnific.com/", "headers": {"k": SECRETS[7]}}}}))
    write(plugins / "cache" / "market" / "stale" / "0.1" / ".mcp.json",
          json.dumps({"mcpServers": {"pika": {"command": "pika"}}}))
    write(plugins / ".trash" / "old" / ".mcp.json", json.dumps({"mcpServers": {"runway": {"command": "x"}}}))
    write(plugins / "installed_plugins.json", json.dumps({"version": 2, "plugins": {
        "magnific-kit@market": [{"scope": "user", "installPath": str(install)}]}}))
    write(home / ".config" / "aimaster" / "preferences.json", json.dumps({
        "schema_version": 1, "preferred_provider_id": "magnific",
        "providers": [{"id": "magnific", "name": "Magnific", "transport": "mcp",
                       "declared_capabilities": ["image_generation"], "declared_by": "user"}]}))
    return home, work


class DetectToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home, self.work = build_home(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *extra: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = detect_tools.main(["--home", str(self.home), "--cwd", str(self.work), *extra])
        return code, out.getvalue()

    def test_no_secret_reaches_any_output(self):
        for extra in ((), ("--json",)):
            code, text = self.run_cli(*extra)
            self.assertEqual(code, 0)
            for secret in SECRETS:
                self.assertNotIn(secret, text)
            for fragment in ("SECRET", "token=", "Bearer", "@fal-ai/mcp-server", "secret-path"):
                self.assertNotIn(fragment, text)

    def test_environments_servers_and_types(self):
        _, text = self.run_cli("--json")
        report = json.loads(text)
        envs = report["environments"]
        claude = {s["name"]: s for s in envs["claude_code"]["servers"]}
        self.assertEqual(claude["higgsfield"]["type"], "http")
        self.assertEqual(claude["higgsfield"]["host"], "mcp.higgsfield.ai")
        self.assertEqual(claude["image-tools"]["type"], "stdio")
        self.assertIn("proj-kling", claude)          # project entry of a parent folder
        self.assertEqual(claude["syntx"]["type"], "sse")  # parent .mcp.json
        self.assertIn("plugin:magnific-kit:magnific", claude)
        self.assertNotIn("runway", claude)            # unrelated project and trash
        self.assertNotIn("plugin:stale:pika", claude)  # cached, not installed
        self.assertNotIn("providers", claude["openai-docs"])
        self.assertEqual({s["name"] for s in envs["codex"]["servers"]}, {"replicate", "luma"})
        self.assertEqual(envs["gemini"]["servers"][0]["type"], "http")
        self.assertEqual(envs["cursor"]["servers"], [])
        self.assertTrue(envs["cursor"]["errors"])

    def test_provider_summary(self):
        _, text = self.run_cli("--json")
        providers = json.loads(text)["providers"]
        for pid in ("higgsfield", "fal", "kling", "syntx", "magnific", "replicate", "luma", "elevenlabs"):
            self.assertIn(pid, providers, pid)
        self.assertNotIn("openai", providers)
        self.assertNotIn("runway", providers)
        how = {h["server"]: h["matched_by"] for h in providers["fal"]}
        self.assertEqual(how["image-tools"], "package")

    def test_preferences_are_listed_without_extra_fields(self):
        _, text = self.run_cli("--json")
        prefs = json.loads(text)["aimaster_preferences"]
        self.assertEqual(prefs["status"], "ok")
        self.assertEqual(prefs["preferred_provider_id"], "magnific")
        self.assertEqual(prefs["providers"][0]["name"], "Magnific")

    def test_empty_home_is_not_an_error(self):
        empty = Path(self.tmp.name) / "empty"
        empty.mkdir()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = detect_tools.main(["--home", str(empty), "--cwd", str(empty), "--json"])
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report["providers"], {})
        self.assertEqual(report["aimaster_preferences"]["status"], "absent")


if __name__ == "__main__":
    unittest.main()

"""Public update CLI and transactional boundaries on disposable homes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import shutil
import io
import zipfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio.family_setup import updates, operation_lease, OperationBusy, register_workspace
from studio.family_setup import packages, providers
from studio.family_setup.snapshots import snapshot_workspace, restore_workspace
from studio.family_setup.state import save_state, read_state, write_json


class PolicyTests(unittest.TestCase):
    def test_compatibility_calls_the_target_full_project_validator(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "target runtime"
            (package / "studio").mkdir(parents=True)
            (package / "studio/__init__.py").write_text("")
            (package / "studio/library.py").write_text("def read_index(path): return {}\n")
            (package / "studio/domain.py").write_text("def derive_view_stage(state): return {}\ndef derive_project_status(view): return 'done'\n")
            (package / "studio/projection.py").write_text("def validate_state(state):\n raise ValueError('unsupported future assembly')\n")
            workspace = root / "workspace"
            (workspace / "projects/one").mkdir(parents=True)
            write_json(workspace / "projects/one/state.json", {"assembly": {"kind": "materials"}})
            self.assertFalse(packages.compatibility(package, [workspace]))

    def test_download_extracts_only_skill_and_ignores_other_agent_symlinks(self):
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("repo/skills/aiediting/SKILL.md", "---\nname: aiediting\n---\n")
            link = zipfile.ZipInfo("repo/.claude/skills/aiediting")
            link.external_attr = 0o120777 << 16
            archive.writestr(link, "../../skills/aiediting")
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(packages, "download", side_effect=[
                json.dumps({"sha": "a" * 40}).encode(), payload.getvalue()]):
            receipt = packages.fetch_package("aiediting", Path(temporary) / "skill")
            self.assertEqual(receipt["revision"], "a" * 40)
            self.assertTrue((Path(temporary) / "skill/SKILL.md").is_file())
            self.assertFalse((Path(temporary) / ".claude").exists())

    def test_new_session_does_nothing_without_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("family_update.py")),
                                     "session-start", "--state-dir", temporary, "--session-id", "test-chat", "--json"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "disabled")
            self.assertFalse((Path(temporary) / "packages").exists())


class TransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.home, self.directory = self.root / "home", self.root / "state"
        self.source = self.root / "old package"
        shutil.copytree(Path(__file__).resolve().parent.parent, self.source,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.identity = {"origin_status": "verified", "origin": "https://github.com/alexfisenkov/aimaster.git", "revision": "a" * 40}
        self.current = packages.install_package(self.source, "aimaster", self.directory, self.home,
                                                ("codex", "claude"), identity=self.identity)
        state = read_state(self.directory)
        state.update(home=str(self.home), agents=["codex", "claude"], components={"aimaster": self.current},
                     auto_update={"enabled": True, "confirmed_at": "synthetic"})
        save_state(self.directory, state)

    def fetch(self, name, destination):
        shutil.copytree(self.source, destination)
        (destination / "VERSION").write_text("2099.02.02\n")
        return {"origin": self.identity["origin"], "revision": "b" * 40,
                "fingerprint": packages.digest_tree(destination), "archive_sha256": "0" * 64}

    def test_busy_lock_and_same_session_do_not_fetch(self):
        fetch = mock.Mock(side_effect=self.fetch)
        with operation_lease(self.directory, "active-generation", ttl=0):
            result = updates.session_start("chat-1", state_dir=self.directory, fetcher=fetch)
        self.assertEqual(result["status"], "deferred_busy")
        fetch.assert_not_called()
        self.assertIsNone(read_state(self.directory)["last_session"])
        result = updates.session_start("chat-1", state_dir=self.directory, fetcher=fetch)
        self.assertEqual(result["components"]["aimaster"]["status"], "updated")
        self.assertTrue(result["restart_required"])
        self.assertEqual(updates.session_start("chat-1", state_dir=self.directory, fetcher=fetch)["status"], "already_checked")
        self.assertEqual(fetch.call_count, 1)

    def test_package_rollback_preserves_workspace_and_personal_editing_skill(self):
        user = self.home / ".agents/skills/монтаж-личный/profile.json"
        user.parent.mkdir(parents=True)
        user.write_bytes(b'{"owner-style":true}\n')
        workspace = self.root / "workspace"
        workspace.mkdir()
        (workspace / "private.txt").write_bytes(b"synthetic project bytes")
        register_workspace(workspace, state_dir=self.directory)
        before = packages.digest_tree(workspace), user.read_bytes()
        result = updates.session_start("chat-update", state_dir=self.directory, fetcher=self.fetch)
        self.assertEqual(result["components"]["aimaster"]["status"], "updated")
        result = updates.rollback("aimaster", state_dir=self.directory)
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(packages.digest_tree(Path(self.current["targets"][0]).resolve()), self.current["fingerprint"])
        self.assertEqual((packages.digest_tree(workspace), user.read_bytes()), before)

    def test_compatible_snapshot_restores_only_into_a_separate_copy(self):
        workspace = self.root / "original workspace"
        workspace.mkdir()
        (workspace / "private.txt").write_bytes(b"synthetic original media")
        register_workspace(workspace, state_dir=self.directory)
        saved = self.root / "snapshot"
        snapshot_workspace(workspace, saved, state_dir=self.directory)
        (workspace / "private.txt").write_bytes(b"newer material must remain")
        destination = self.root / "compatible copy"
        result = restore_workspace(saved, destination, state_dir=self.directory)
        self.assertEqual(result["status"], "compatible_workspace_copy")
        self.assertEqual((workspace / "private.txt").read_bytes(), b"newer material must remain")
        self.assertEqual((destination / "private.txt").read_bytes(), b"synthetic original media")
        with self.assertRaises(ValueError):
            restore_workspace(saved, workspace, state_dir=self.directory)
        with self.assertRaises(ValueError):
            restore_workspace(saved, workspace / "nested copy", state_dir=self.directory)

    def test_offline_corrupt_and_dirty_keep_last_good(self):
        for kind in ("offline", "corrupt", "dirty"):
            def fetch(name, destination):
                if kind == "offline":
                    raise OSError("offline")
                identity = self.fetch(name, destination)
                identity["fingerprint"] = "0" * 64
                return identity
            if kind == "dirty":
                (Path(self.current["targets"][0]) / "local-note.txt").write_text("owner change")
            before = packages.digest_tree(Path(self.current["targets"][0]).resolve())
            result = updates.session_start(kind, state_dir=self.directory, fetcher=fetch)
            self.assertEqual(result["components"]["aimaster"]["status"], "kept_current")
            self.assertEqual(packages.digest_tree(Path(self.current["targets"][0]).resolve()), before)

    def test_real_library_reader_blocks_incompatible_rollback_without_downgrade(self):
        # Old runtime's closed allowlist rejects the newly saved metadata fields.
        old = Path(self.current["package"])
        path = old / "studio/library.py"
        path.write_text(path.read_text().replace('"voice_of", "source", "notes", "tags", "updated_at"', '"voice_of", "source"'))
        # Point both installed copies at this initial old version before updating.
        import install
        for target in self.current["targets"]:
            if not Path(target).is_symlink() and not getattr(__import__('os').path, 'isjunction', lambda p: False)(target):
                shutil.copy2(path, Path(target) / "studio/library.py")
        self.current["fingerprint"] = packages.digest_tree(old)
        state = read_state(self.directory)
        state["components"]["aimaster"] = self.current
        save_state(self.directory, state)
        workspace = self.root / "workspace"
        (workspace / "library").mkdir(parents=True)
        register_workspace(workspace, state_dir=self.directory)
        result = updates.session_start("new-runtime", state_dir=self.directory, fetcher=self.fetch)
        self.assertEqual(result["components"]["aimaster"]["status"], "updated")
        index = {"schema_version": 1, "revision": 1, "entries": [{"library_id": "character-one",
            "kind": "character", "label": "Synthetic", "aliases": [], "added_at": "2026-11-05", "notes": "Keep this",
            "files": [{"path": "characters/a.png", "sha256": "0" * 64, "media": "image"}]}]}
        write_json(workspace / "library/index.json", index)
        before = (workspace / "library/index.json").read_bytes()
        selected = read_state(self.directory)["components"]["aimaster"]["fingerprint"]
        result = updates.rollback("aimaster", state_dir=self.directory)
        self.assertEqual(result["status"], "compatibility_blocked")
        self.assertEqual((workspace / "library/index.json").read_bytes(), before)
        self.assertEqual(read_state(self.directory)["components"]["aimaster"]["fingerprint"], selected)

    def test_native_syntx_rollback_protocol_reads_back_pointer(self):
        state = read_state(self.directory)
        root = self.root / "syntx"
        root.mkdir()
        (root / "dist/src/transports").mkdir(parents=True)
        (root / "dist/src/transports/stdio-owner.js").write_text("// synthetic runtime")
        state["components"]["syntx"] = {"installed": True, "package": str(root), "node": "/fake/node"}
        save_state(self.directory, state)
        calls = []
        def runner(argv, **kwargs):
            calls.append(argv)
            if "get-url" in argv:
                return 0, "https://github.com/alexfisenkov/syntx-mcp.git", ""
            if "--porcelain" in argv:
                return 0, "", ""
            if "rev-parse" in argv:
                return 0, "a" * 40, ""
            write_json(self.home / ".syntx-mcp-updates/pointer.json", {"current": "a" * 40, "previous": "b" * 40, "current_path": str(root)})
            return 0, json.dumps({"status": "ROLLBACK_STAGED", "current_sha": "a" * 40,
                "latest_sha": None, "rollback_sha": "b" * 40, "restart_required": True}), ""
        with mock.patch.object(providers, "program", return_value="/fake/git"):
            result = updates.rollback("syntx", state_dir=self.directory, runner=runner)
        self.assertEqual(result["status"], "ROLLBACK_STAGED")
        self.assertTrue(result["restart_required"])
        self.assertTrue(any(call[-1] == "rollback" for call in calls))

    def test_syntx_pointer_alone_does_not_prove_a_selected_version_exists(self):
        state = read_state(self.directory)
        state["components"]["syntx"] = {"installed": True, "package": str(self.root / "syntx"), "node": "/fake/node"}
        def runner(argv, **kwargs):
            if "get-url" in argv:
                return 0, "https://github.com/alexfisenkov/syntx-mcp.git", ""
            if "--porcelain" in argv:
                return 0, "", ""
            write_json(self.home / ".syntx-mcp-updates/pointer.json", {"current": "b" * 40, "previous": "a" * 40})
            return 0, json.dumps({"status": "STAGED", "current_sha": "b" * 40,
                "latest_sha": "b" * 40, "rollback_sha": "a" * 40, "restart_required": True}), ""
        with mock.patch.object(providers, "program", return_value="/fake/git"):
            result = updates.native_syntx(state, self.directory, "apply", runner=runner)
        self.assertEqual(result["status"], "native_readback_failed")

    def test_hosted_manifest_rollback_is_local_not_a_server_version_rollback(self):
        state = read_state(self.directory)
        state["connectors"] = {"magnific": {"expected": {"url": "https://mcp.magnific.com"}, "manifest_version": "previous"}}
        path = providers.config_path(self.home, "codex")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[mcp_servers.magnific]\nurl = "https://mcp.magnific.com"\n')
        state["agents"] = ["codex"]
        updates.refresh_connectors(state, self.directory)
        save_state(self.directory, state)
        before = path.read_bytes()
        result = updates.rollback("magnific", state_dir=self.directory)
        self.assertEqual(result["status"], "local_manifest_rolled_back")
        self.assertFalse(result["server_rollback"])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(read_state(self.directory)["connectors"]["magnific"]["manifest_version"], "previous")


if __name__ == "__main__":
    unittest.main()

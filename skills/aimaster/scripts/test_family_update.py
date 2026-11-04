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
import html
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio.family_setup import updates, operation_lease, OperationBusy, register_workspace
from studio.family_setup import packages, providers
from studio.family_setup.snapshots import snapshot_workspace, restore_workspace
from studio.family_setup.state import save_state, read_state, write_json


class PolicyTests(unittest.TestCase):
    def test_restore_rejects_an_external_manifest_link_before_reading_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            workspace = root / "workspace"
            workspace.mkdir()
            snapshot = root / "snapshot"
            snapshot_workspace(workspace, snapshot, state_dir=root / "family")
            manifest = snapshot / "manifest.json"
            outside = root / "outside.json"
            outside.write_bytes(manifest.read_bytes())
            manifest.unlink()
            try:
                manifest.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable on this runner")
            original_read = Path.read_text
            def reject_external_read(path, *args, **kwargs):
                if path == manifest:
                    raise AssertionError("external manifest was dereferenced")
                return original_read(path, *args, **kwargs)
            with mock.patch.object(Path, "read_text", reject_external_read):
                with self.assertRaisesRegex(ValueError, "unsafe_snapshot"):
                    restore_workspace(snapshot, root / "restored", state_dir=root / "family")

    def test_snapshot_and_restore_reject_links_even_under_digest_exclusions(self):
        for name in (".git", ".aimaster-install.json", ".DS_Store", "__pycache__", "cached.pyc"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                outside = root / "outside"
                outside.mkdir()
                (outside / "private.txt").write_bytes(b"must never enter a workspace copy")
                workspace = root / "workspace"
                workspace.mkdir()
                link = workspace / name
                try:
                    link.symlink_to(outside, target_is_directory=True)
                except OSError:
                    self.skipTest("directory symlinks unavailable on this runner")
                with self.assertRaises(ValueError):
                    snapshot_workspace(workspace, root / "snapshot", state_dir=root / "family")
                self.assertFalse((root / "snapshot/manifest.json").exists())
                link.unlink()
                snapshot_workspace(workspace, root / "valid snapshot", state_dir=root / "family")
                injected = root / "valid snapshot/workspace" / name
                injected.symlink_to(outside, target_is_directory=True)
                # A runtime isn't needed: the snapshot must be rejected before
                # any target reader or copy can inspect the outside directory.
                with self.assertRaisesRegex(ValueError, "symlink|unsafe|invalid_snapshot"):
                    restore_workspace(root / "valid snapshot", root / "restore", state_dir=root / "family")
                self.assertFalse((root / "restore").exists())

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
        self.identity = {"origin_status": "verified", "origin": "https://github.com/alexfisenkov/aimaster.git", "revision": "a" * 40,
                         "archive_sha256": "0" * 64, "provenance": "official_archive"}
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

    def test_receipt_write_failure_restores_the_previous_active_package(self):
        original_write = packages.write_json
        def fail_receipt(path, value):
            if Path(path).parent.name == "receipts":
                raise OSError("synthetic receipt write failure")
            return original_write(path, value)
        with mock.patch.object(packages, "write_json", side_effect=fail_receipt):
            result = updates.session_start("receipt-failure", state_dir=self.directory, fetcher=self.fetch)
        self.assertEqual(result["components"]["aimaster"]["status"], "kept_current")
        self.assertEqual(read_state(self.directory)["components"]["aimaster"]["fingerprint"], self.current["fingerprint"])
        for target in self.current["targets"]:
            self.assertEqual(packages.digest_tree(Path(target).resolve()), self.current["fingerprint"])

    def test_family_write_failure_does_not_publish_new_targets_as_kept_current(self):
        original_save = updates.save_state
        def fail_new_state(directory, state):
            if state["components"]["aimaster"]["fingerprint"] != self.current["fingerprint"]:
                raise OSError("synthetic family state write failure")
            return original_save(directory, state)
        with mock.patch.object(updates, "save_state", side_effect=fail_new_state):
            result = updates.session_start("state-failure", state_dir=self.directory, fetcher=self.fetch)
        self.assertEqual(result["components"]["aimaster"]["status"], "kept_current")
        self.assertEqual(read_state(self.directory)["components"]["aimaster"]["fingerprint"], self.current["fingerprint"])
        for target in self.current["targets"]:
            self.assertEqual(packages.digest_tree(Path(target).resolve()), self.current["fingerprint"])

    def test_failure_after_family_file_was_written_compensates_disk_state_too(self):
        original_save = updates.save_state
        def write_then_fail(directory, state):
            original_save(directory, state)
            if state["components"]["aimaster"]["fingerprint"] != self.current["fingerprint"]:
                raise OSError("synthetic error after atomic state replacement")
        with mock.patch.object(updates, "save_state", side_effect=write_then_fail):
            result = updates.session_start("after-state-write", state_dir=self.directory, fetcher=self.fetch)
        self.assertEqual(result["components"]["aimaster"]["status"], "kept_current")
        self.assertEqual(read_state(self.directory)["components"]["aimaster"]["fingerprint"], self.current["fingerprint"])
        for target in self.current["targets"]:
            self.assertEqual(packages.digest_tree(Path(target).resolve()), self.current["fingerprint"])

    def test_old_receipt_without_official_proof_is_reverified_before_any_update(self):
        state = read_state(self.directory)
        state["components"]["aimaster"].pop("archive_sha256")
        state["components"]["aimaster"].pop("provenance")
        save_state(self.directory, state)
        fetcher = mock.Mock()
        with mock.patch.object(packages, "download", side_effect=OSError("unpublished local commit")):
            result = updates.session_start("legacy-unverified", state_dir=self.directory, fetcher=fetcher)
        self.assertEqual(result["components"]["aimaster"]["status"], "kept_current")
        fetcher.assert_not_called()
        self.assertEqual(read_state(self.directory)["components"]["aimaster"]["fingerprint"], self.current["fingerprint"])

    def test_rollback_state_write_failure_retains_current_and_rollback_receipts(self):
        updates.session_start("before-rollback", state_dir=self.directory, fetcher=self.fetch)
        before = read_state(self.directory)
        with mock.patch.object(updates, "save_state", side_effect=OSError("synthetic state failure")):
            with self.assertRaises(OSError):
                updates.rollback("aimaster", state_dir=self.directory)
        self.assertEqual(read_state(self.directory), before)
        for target in self.current["targets"]:
            self.assertEqual(packages.digest_tree(Path(target).resolve()), before["components"]["aimaster"]["fingerprint"])
        self.assertTrue(Path(before["rollback"]["aimaster"]["package"]).is_dir())

    def test_summary_write_failure_reports_the_committed_new_version(self):
        original_save = updates.save_state
        def fail_summary(directory, state):
            if state.get("last_session") == "summary-failure":
                raise OSError("synthetic summary write failure")
            return original_save(directory, state)
        with mock.patch.object(updates, "save_state", side_effect=fail_summary):
            result = updates.session_start("summary-failure", state_dir=self.directory, fetcher=self.fetch)
        self.assertEqual(result["status"], "report_write_failed")
        self.assertEqual(result["components"]["aimaster"]["status"], "updated")
        persisted = read_state(self.directory)
        self.assertNotEqual(persisted["components"]["aimaster"]["fingerprint"], self.current["fingerprint"])
        for target in self.current["targets"]:
            self.assertEqual(packages.digest_tree(Path(target).resolve()), persisted["components"]["aimaster"]["fingerprint"])
        self.assertEqual(persisted["rollback"]["aimaster"]["fingerprint"], self.current["fingerprint"])

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

    def test_overlay_model_sidecars_block_rollback_in_current_versions_and_cache(self):
        from montage_testkit import video_state
        old = Path(self.current["package"])
        model_path = old / "studio/montage/model.py"
        text = model_path.read_text()
        legacy = text.replace("    overlay: dict | None = None\n", "").replace("    visual_hash: str | None = None\n", "")
        self.assertNotEqual(legacy, text)
        model_path.write_text(legacy)
        for target in self.current["targets"]:
            if not Path(target).is_symlink() and not getattr(__import__('os').path, 'isjunction', lambda p: False)(target):
                shutil.copy2(model_path, Path(target) / "studio/montage/model.py")
        self.current["fingerprint"] = packages.digest_tree(old)
        state = read_state(self.directory)
        state["components"]["aimaster"] = self.current
        save_state(self.directory, state)
        workspace = self.root / "overlay workspace"
        (workspace / "projects/p").mkdir(parents=True)
        write_json(workspace / "projects/p/state.json", video_state([("s1", "Scene", "Text", 1000, None)]))
        register_workspace(workspace, state_dir=self.directory)
        self.assertTrue(packages.compatibility(old, [workspace]))
        updated = updates.session_start("overlay-runtime", state_dir=self.directory, fetcher=self.fetch)
        self.assertEqual(updated["components"]["aimaster"]["status"], "updated")
        selected = read_state(self.directory)["components"]["aimaster"]
        model = {"duration": 1.0, "clips": [{"id": "o-1", "layer": "overlays", "kind": "svg", "start": 0.0,
            "duration": 1.0, "overlay": {"type": "rect", "color": "#00FF80"}, "visual_hash": "a" * 16}]}
        for relative in ("current/model.json", "versions/v001/model.json", ".cache/model-synthetic.json",
                         "current/index.html", "versions/v001/index.html"):
            with self.subTest(sidecar=relative):
                path = workspace / "projects/p/montage" / relative
                if relative.endswith(".html"):
                    shape = {"type": "rect", "canvas": {"width": 108, "height": 192},
                        "geometry": {"x": 10, "y": 20, "width": 60, "height": 80}, "color": "#00FF80",
                        "stroke_width": 4, "opacity": .8, "draw_on": .4, "scene_id": "s1"}
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('<svg id="o-1" data-am-layer="overlays" data-am-overlay="' +
                                    html.escape(json.dumps(shape), quote=True) + '"></svg>')
                else:
                    write_json(path, {"model": model} if ".cache/" in relative else model)
                before = path.read_bytes()
                self.assertTrue(packages.compatibility(Path(selected["package"]), [workspace]))
                result = updates.rollback("aimaster", state_dir=self.directory)
                self.assertEqual(result["status"], "compatibility_blocked")
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(read_state(self.directory)["components"]["aimaster"]["fingerprint"], selected["fingerprint"])
                path.unlink()

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

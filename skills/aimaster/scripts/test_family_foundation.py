"""Family foundation public CLI and portable workspace contracts."""
import json
import shutil
import unittest
from unittest.mock import patch

from test_library import Base, cli, png_bytes, wav_bytes, mp4_bytes
from studio.library import LibraryError, read_index
from studio.library_projects import materialize
from studio.stage_readiness import stage_readiness
from studio.projection import build_snapshot
from studio import authoring
from studio.store import ProjectStore


class LibraryIdentityTests(Base):
    def test_project_library_identity_and_voice_binding_survive_missing_library(self):
        portrait = cli("library", "add", self.ws, "--kind", "character", "--label", "Actor",
                       "--file", self.file("actor.png", png_bytes()))
        identity = portrait["library_id"]
        voice = cli("library", "add", self.ws, "--kind", "voice", "--label", "Actor voice",
                    "--file", self.file("actor.wav", wav_bytes()), "--voice-of", identity)
        self.project_at_references("reuse")
        linked = cli("reference", "add", self.ws, "reuse", "--from-library", identity,
                     "--expected-revision", self.rev("reuse"))
        ref_id = linked["reference_id"]
        reference = self.store.load("reuse")["references"][0]
        self.assertEqual(reference.get("library_id"), identity)
        cli("reference", "edit", self.ws, "reuse", "--reference", ref_id,
            "--field", "voice_enabled", "--value", "true", "--expected-revision", self.rev("reuse"))
        cli("reference", "attach", self.ws, "reuse", "--reference", ref_id,
            "--from-library", voice["library_id"], "--expected-revision", self.rev("reuse"))
        reference = self.store.load("reuse")["references"][0]
        self.assertEqual(reference["library_id"], identity)
        self.assertEqual(reference["voice"]["library_id"], voice["library_id"])
        shutil.rmtree(self.ws / "library")
        snapshot = build_snapshot(self.store.list_projects(), self.store.load("reuse"), asset_url=lambda x: "/assets/" + x)
        self.assertEqual(snapshot["active_project"]["references"][0]["library_id"], identity)
        self.assertTrue(authoring.open_assets(self.ws).resolve(reference["asset_id"])[0].is_file())

    def test_two_distinct_names_are_not_a_name_collision(self):
        for number, label in enumerate(("Alice", "Bob")):
            cli("library", "add", self.ws, "--kind", "character", "--label", label,
                "--file", self.file(label + ".png", png_bytes(number)))
        result = cli("library", "match", self.ws, "--text", "Alice meets Bob")
        self.assertEqual(result["count"], 2)
        self.assertFalse(result["ambiguous"])

    def test_notes_edit_attach_revision_and_cross_project_reuse(self):
        ids = []
        for offset, kind in enumerate(("character", "product", "location", "style")):
            added = cli("library", "add", self.ws, "--kind", kind, "--label", "Shared name",
                        "--file", self.file(kind + ".png", png_bytes(10 + offset)),
                        "--notes", "Synthetic subject", "--tag", kind)
            identity = added["library_id"]
            ids.append(identity)
            revision = read_index(self.ws / "library")["revision"]
            before = (self.ws / "library" / "index.json").read_bytes()
            edited = cli("library", "edit", self.ws, identity, "--notes", "Blue workshop prop",
                         "--alias", kind + " alias", "--tag", "blue", "--expected-revision", revision)
            self.assertEqual(edited["revision"], revision + 1)
            self.assertEqual((self.ws / "library" / ".history" / f"index-r{revision}.json").read_bytes(), before)
            with self.assertRaisesRegex(LibraryError, "revision"):
                cli("library", "edit", self.ws, identity, "--notes", "stale", "--expected-revision", revision)
            cli("library", "attach", self.ws, identity, "--file",
                self.file(kind + "-second.png", png_bytes(30 + offset)), "--expected-revision", revision + 1)
            self.assertEqual(len(cli("library", "list", self.ws, "--kind", kind)["entries"][0]["files"]), 2)
            for file_index, pid in enumerate((kind + "-first", kind + "-next")):
                self.project_at_references(pid)
                attached = cli("reference", "add", self.ws, pid, "--from-library", identity,
                               "--library-file-index", file_index,
                               "--expected-revision", self.rev(pid))
                self.assertEqual(attached["library_id"], identity)
                self.assertEqual(self.store.load(pid)["references"][0]["library_id"], identity)
            second = materialize(self.ws, identity, file_index=1)
            self.assertEqual(second["entry"]["library_id"], identity)
        cli("library", "add", self.ws, "--kind", "voice", "--label", "Shared voice",
            "--file", self.file("voice.wav", wav_bytes()), "--voice-of", ids[0])
        matched = cli("library", "match", self.ws, "--text", "blue")
        self.assertEqual({item["library_id"] for item in matched["matches"] if item["kind"] != "voice"}, set(ids))
        self.assertTrue(all(item["reasons"] for item in matched["matches"]))
        # Two characters sharing a name stay separate and require a choice.
        cli("library", "add", self.ws, "--kind", "character", "--label", "Shared name",
            "--file", self.file("other-person.png", png_bytes(90)))
        self.assertTrue(cli("library", "match", self.ws, "--text", "Shared name")["ambiguous"])
        copied = self.root / "relocated"
        shutil.copytree(self.ws, copied)
        self.assertEqual(cli("library", "list", copied), cli("library", "list", self.ws))
        self.assertEqual(materialize(copied, ids[0])["entry"]["notes"], "Blue workshop prop")


class AssemblyChoiceTests(Base):
    def test_new_choice_and_legacy_read_are_distinct_and_revisioned(self):
        cli("project", "create", self.ws, "new", "--title", "New", "--type", "video", "--mode", "autopilot")
        self.assertIn("assembly_mode", self.store.load("new")["project"])
        self.assertIsNone(self.store.load("new")["project"]["assembly_mode"])
        cli("script", "add-version", self.ws, "new", "--text", "Synthetic", "--reason", "start", "--expected-revision", self.rev("new"))
        scenes = self.file("scenes.json", json.dumps([{"scene_id": "s1", "title": "Scene", "text": "Action", "duration_ms": 2000}]).encode())
        cli("scenes", "set", self.ws, "new", "--file", scenes, "--expected-revision", self.rev("new"))
        self.assertEqual(stage_readiness(self.store.load("new"))["reason"], "assembly_choice_required")
        revision = self.rev("new")
        cli("project", "set-assembly-mode", self.ws, "new", "--mode", "materials", "--expected-revision", revision)
        self.assertTrue(stage_readiness(self.store.load("new"))["can_approve"])
        with self.assertRaisesRegex(Exception, "revision"):
            cli("project", "set-assembly-mode", self.ws, "new", "--mode", "montage", "--expected-revision", revision)
        current = self.store.load("new")
        self.assertEqual(current["history"][-1]["kind"], "assembly-mode-set")
        legacy = dict(current, project={k: v for k, v in current["project"].items() if k != "assembly_mode"})
        self.assertTrue(stage_readiness(legacy)["can_approve"])
        self.assertEqual(build_snapshot([], legacy, asset_url=lambda x: "/asset/" + x)["active_project"]["assembly_mode"], "montage")
        legacy_ws = self.root / "legacy"
        cli("workspace", "init", legacy_ws)
        legacy_project = legacy_ws / "projects" / "new"
        legacy_project.mkdir()
        original = legacy_project / "state.json"
        original.write_text(json.dumps(legacy))
        original_bytes = original.read_bytes()
        private_file = legacy_ws / "instructions" / "personal.txt"
        private_file.write_bytes(b"Synthetic personal instructions\n")
        clone = self.root / "continued-copy"
        shutil.copytree(legacy_ws, clone)
        cli("project", "set-assembly-mode", clone, "new", "--mode", "materials", "--expected-revision", current["revision"])
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual((clone / "instructions" / "personal.txt").read_bytes(), private_file.read_bytes())
        cli("project", "create", self.ws, "photo", "--title", "Photo", "--type", "photo", "--mode", "guided")
        self.assertEqual(self.store.load("photo")["project"]["assembly_mode"], "materials")

    def test_guide_choice_persists_exact_scope_and_refuses_stale_hash(self):
        import hashlib
        cli("project", "create", self.ws, "guided", "--title", "Guided", "--type", "photo", "--mode", "guided")
        text = "Synthetic guide"
        (self.ws / "instructions" / "synthetic.md").write_text(text)
        digest = hashlib.sha256(text.encode()).hexdigest()
        entry = dict(id="synthetic", title="Synthetic", path="synthetic.md", sha256=digest,
                     kind="prompt", modalities=["image"], tasks=["generate"], providers=["test"],
                     model_families=["family"], models=["model"], versions=["1"],
                     family_all_versions=False, model_agnostic=False)
        (self.ws / "instructions" / "guides.json").write_text(json.dumps(dict(schema_version=1, revision=1, entries=[entry])))
        choice = dict(stage="image_plan", kind="prompt", modality="image", task="generate",
                      provider="test", model_family="family", model="model", version="1",
                      source="user", ref="user:synthetic", sha256=digest)
        choice_file = self.file("choice.json", json.dumps(choice).encode())
        cli("project", "set-guide-choice", self.ws, "guided", "--file", choice_file, "--expected-revision", 0)
        self.assertEqual(self.store.load("guided")["project"]["guide_choices"], [choice])
        self.assertEqual(self.store.load("guided")["history"][-1]["kind"], "guide-choice-set")
        (self.ws / "instructions" / "synthetic.md").write_text("Changed guide")
        before = (self.store.project_dir("guided") / "state.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "stale|exact"):
            cli("project", "set-guide-choice", self.ws, "guided", "--file", choice_file, "--expected-revision", 1)
        self.assertEqual((self.store.project_dir("guided") / "state.json").read_bytes(), before)
        choice.update(source="none", ref=None, sha256=None)
        choice_file.write_text(json.dumps(choice))
        cli("project", "set-guide-choice", self.ws, "guided", "--file", choice_file, "--expected-revision", 1)
        self.assertEqual(self.store.load("guided")["project"]["guide_choices"], [choice])


class MaterialsCompletionTests(Base):
    def at_assembly(self, kind, *, choose_older=False):
        pid = kind
        cli("project", "create", self.ws, pid, "--title", kind, "--type", kind, "--mode", "guided")
        cli("project", "set-assembly-mode", self.ws, pid, "--mode", "materials", "--expected-revision", self.rev(pid))
        cli("script", "add-version", self.ws, pid, "--text", "Synthetic", "--reason", "start", "--expected-revision", self.rev(pid))
        scene = {"scene_id": "s1", "title": "Scene", "text": "Action"}
        if kind == "video":
            scene["duration_ms"] = 2000
        scenes = self.file(kind + ".json", json.dumps([scene]).encode())
        cli("scenes", "set", self.ws, pid, "--file", scenes, "--expected-revision", self.rev(pid))
        cli("stage", "approve", self.ws, pid, "--expected-revision", self.rev(pid))
        target = "pos:scene:s1:" + ("image" if kind == "photo" else "video")
        cli("prompt", "add-version", self.ws, pid, "--target", target, "--text", "Synthetic prompt", "--reason", "start", "--expected-revision", self.rev(pid))
        cli("stage", "approve", self.ws, pid, "--expected-revision", self.rev(pid))
        if kind == "video":
            cli("stage", "approve", self.ws, pid, "--expected-revision", self.rev(pid))
        filename, contents = ("selected.png", png_bytes()) if kind == "photo" else ("selected.mp4", mp4_bytes())
        (self.ws / "media" / filename).write_bytes(contents)
        asset = cli("asset", "register", self.ws, "--path", "media/" + filename, "--role", "result")
        if choose_older:
            chosen = cli("result", "add-version", self.ws, pid, "--target", target, "--asset-id", asset["asset_id"], "--expected-revision", self.rev(pid))
        for number in (1, 2):
            alternative_name = str(number) + filename
            alternative = png_bytes(number) if kind == "photo" else contents[:-1] + bytes([number])
            (self.ws / "media" / alternative_name).write_bytes(alternative)
            other = cli("asset", "register", self.ws, "--path", "media/" + alternative_name, "--role", "result")
            version = cli("result", "add-version", self.ws, pid, "--target", target,
                          "--asset-id", other["asset_id"], "--expected-revision", self.rev(pid))
            if number == 1:
                cli("decide", self.ws, pid, "reject", "--target", version["version_id"], "--expected-revision", self.rev(pid))
        if not choose_older:
            chosen = cli("result", "add-version", self.ws, pid, "--target", target, "--asset-id", asset["asset_id"], "--expected-revision", self.rev(pid))
        cli("decide", self.ws, pid, "approve", "--target", chosen["version_id"], "--expected-revision", self.rev(pid))
        link_key = "image_result_id" if kind == "photo" else "video_result_id"
        self.assertEqual(self.store.load(pid)["scenes"][0]["links"][link_key], chosen["version_id"])
        cli("stage", "approve", self.ws, pid, "--expected-revision", self.rev(pid))
        if kind == "video":
            cli("stage", "approve", self.ws, pid, "--expected-revision", self.rev(pid))
        return pid, asset["asset_id"], contents

    def test_accepting_older_result_selects_it_for_materials(self):
        for kind in ("photo", "video"):
            pid, asset_id, _ = self.at_assembly(kind, choose_older=True)
            result = cli("assembly", "materials", self.ws, pid, "--expected-revision", self.rev(pid))
            self.assertEqual(result["asset_ids"], [asset_id])

    def test_interrupted_prepare_reconciles_existing_verified_packet(self):
        pid, asset_id, _ = self.at_assembly("photo")
        revision = self.rev(pid)
        before = (self.store.project_dir(pid) / "state.json").read_bytes()
        with patch.object(ProjectStore, "_atomic_replace", side_effect=OSError("synthetic interruption")):
            with self.assertRaises(OSError):
                cli("assembly", "materials", self.ws, pid, "--expected-revision", revision)
        self.assertEqual((self.store.project_dir(pid) / "state.json").read_bytes(), before)
        result = cli("assembly", "materials", self.ws, pid, "--expected-revision", revision)
        self.assertEqual(result["asset_ids"], [asset_id])
        self.assertEqual(len(list((self.store.project_dir(pid) / "materials").glob("r*"))), 1)

    def test_real_materials_manifest_done_reopen_and_relocated_verification(self):
        for kind in ("photo", "video"):
            pid, asset_id, contents = self.at_assembly(kind)
            with self.assertRaisesRegex(Exception, "missing_final_material"):
                cli("stage", "approve", self.ws, pid, "--expected-revision", self.rev(pid))
            prepared = cli("assembly", "materials", self.ws, pid, "--expected-revision", self.rev(pid))
            state = self.store.load(pid)
            assembly = state["assembly"]
            self.assertEqual(assembly["kind"], "materials")
            self.assertEqual(assembly["asset_ids"], [asset_id])
            self.assertNotIn("asset_id", assembly)
            manifest_path = self.store.project_dir(pid) / assembly["manifest"]["path"]
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest["assets"][0]["asset_id"], asset_id)
            output_file = manifest_path.parent / manifest["assets"][0]["path"]
            self.assertEqual(output_file.read_bytes(), contents)
            self.assertNotIn(str(self.ws), manifest_path.read_text())
            output_file.write_bytes(b"broken")
            before = self.rev(pid)
            with self.assertRaisesRegex(Exception, "checksum"):
                cli("stage", "approve", self.ws, pid, "--expected-revision", before)
            self.assertEqual(self.rev(pid), before)
            output_file.write_bytes(contents)
            cli("stage", "approve", self.ws, pid, "--expected-revision", self.rev(pid))
            self.assertEqual(self.store.load(pid)["project"]["status"], "done")
            previous_history = self.store.load(pid)["history"]
            if kind == "video":
                cli("project", "set-assembly-mode", self.ws, pid, "--mode", "montage", "--expected-revision", self.rev(pid))
                self.assertEqual(self.store.load(pid)["project"]["status"], "review")
                self.assertFalse(stage_readiness(self.store.load(pid))["can_approve"])
            cli("scenario", "reopen", self.ws, pid, "--expected-revision", self.rev(pid), "--comment", "New pass")
            self.assertEqual(self.store.load(pid)["history"][:len(previous_history)], previous_history)
            self.assertTrue(manifest_path.is_file())
            moved = self.root / (kind + "-portable")
            shutil.copytree(manifest_path.parent, moved)
            from studio.completion import verify_manifest
            self.assertEqual(verify_manifest(moved / "manifest.json")["assets"][0]["asset_id"], asset_id)

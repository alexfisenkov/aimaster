"""Public regressions for the three blocking T01 point-review findings."""
import hashlib
import io
import json
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, get_ident
from unittest.mock import patch

import guide_registry
from test_library import Base, cli, png_bytes, wav_bytes
from studio.authoring_support import AuthoringError
from studio import library
from studio.guide_catalog import resolve_choice


class FoundationReviewTests(Base):
    def test_library_list_snapshot_and_stale_edit_with_concurrent_writer(self):
        identity = cli("library", "add", self.ws, "--kind", "character", "--label", "Actor",
                       "--notes", "before", "--file", self.file("actor.png", png_bytes()))["library_id"]
        initial_revision = cli("library", "list", self.ws)["revision"]
        index_path = (self.ws / "library" / "index.json").resolve()
        original_read = Path.read_text
        reader_id = get_ident()
        snapshot_read, written = Event(), Event()

        def concurrent_edit():
            if not snapshot_read.wait(3):
                raise AssertionError("library listing did not read its index")
            try:
                return library.edit(self.ws, identity, notes="concurrent", expected_revision=initial_revision)
            finally:
                written.set()

        def read_with_interleaving(path, *args, **kwargs):
            contents = original_read(path, *args, **kwargs)
            if path == index_path and get_ident() == reader_id and not snapshot_read.is_set():
                # A real public writer lands after this complete atomic file read.
                snapshot_read.set()
                # A reader holding the library lock may legitimately finish first.
                written.wait(1)
            return contents

        with ThreadPoolExecutor(max_workers=1) as executor:
            writer = executor.submit(concurrent_edit)
            with patch.object(Path, "read_text", read_with_interleaving):
                listing = cli("library", "list", self.ws)
            update = writer.result(timeout=3)
        self.assertEqual(update["revision"], initial_revision + 1)
        self.assertIn((listing["revision"], listing["entries"][0]["notes"]),
                      {(initial_revision, "before"), (initial_revision + 1, "concurrent")})
        before_refusal = index_path.read_bytes()
        with self.assertRaisesRegex(library.LibraryError, "revision"):
            cli("library", "edit", self.ws, identity, "--notes", "stale overwrite",
                "--expected-revision", initial_revision)
        self.assertEqual(index_path.read_bytes(), before_refusal)

    def test_identity_replacement_refuses_incompatible_attached_voice_atomically(self):
        alice = cli("library", "add", self.ws, "--kind", "character", "--label", "Alice",
                    "--file", self.file("alice.png", png_bytes(20)))["library_id"]
        bob = cli("library", "add", self.ws, "--kind", "character", "--label", "Bob",
                  "--file", self.file("bob.png", png_bytes(30)))["library_id"]
        voice = cli("library", "add", self.ws, "--kind", "voice", "--label", "Alice voice",
                    "--file", self.file("alice.wav", wav_bytes()), "--voice-of", alice)["library_id"]
        self.project_at_references("cast")
        reference = cli("reference", "add", self.ws, "cast", "--from-library", alice,
                        "--expected-revision", self.rev("cast"))["reference_id"]
        cli("reference", "edit", self.ws, "cast", "--reference", reference,
            "--field", "voice_enabled", "--value", "true", "--expected-revision", self.rev("cast"))
        cli("reference", "attach", self.ws, "cast", "--reference", reference,
            "--from-library", voice, "--expected-revision", self.rev("cast"))
        state_file = self.store.project_dir("cast") / "state.json"
        before = state_file.read_bytes()
        with self.assertRaisesRegex(AuthoringError, "voice.*identity"):
            cli("reference", "attach", self.ws, "cast", "--reference", reference,
                "--from-library", bob, "--expected-revision", self.rev("cast"))
        self.assertEqual(state_file.read_bytes(), before)
        # A different portrait of the same selected identity remains valid.
        revision = cli("library", "list", self.ws)["revision"]
        cli("library", "attach", self.ws, alice, "--file", self.file("alice-two.png", png_bytes(21)),
            "--expected-revision", revision)
        cli("reference", "attach", self.ws, "cast", "--reference", reference,
            "--from-library", alice, "--library-file-index", 1, "--expected-revision", self.rev("cast"))
        current = self.store.load("cast")["references"][0]
        self.assertEqual(current["library_id"], alice)
        self.assertEqual(current["voice"]["library_id"], voice)

    def test_model_agnostic_scenario_choice_accepts_null_model_scope(self):
        source = self.ws / "instructions" / "scenario.md"
        source.write_text("Synthetic scenario method\n", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            status = guide_registry.main([
                "--workspace", str(self.ws), "register", "--id", "scenario-method",
                "--title", "Scenario method", "--path", "scenario.md", "--kind", "scenario",
                "--modality", "scenario", "--task", "outline", "--model-agnostic"])
        self.assertEqual(status, 0)
        catalog = self.file("catalog.json", json.dumps({"schema_version": 1, "bundle_version": "test", "entries": []}).encode())
        cli("project", "create", self.ws, "scenario", "--title", "Scenario", "--type", "photo", "--mode", "guided")
        choice = dict(stage="scenario", kind="scenario", modality="scenario", task="outline",
                      provider=None, model_family=None, model=None, version=None,
                      source="user", ref="user:scenario-method", sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        choice_file = self.file("choice.json", json.dumps(choice).encode())
        cli("project", "set-guide-choice", self.ws, "scenario", "--file", choice_file,
            "--builtin-catalog", catalog, "--expected-revision", 0)
        self.assertEqual(self.store.load("scenario")["project"]["guide_choices"], [choice])
        self.assertEqual(resolve_choice(self.ws, choice, catalog_path=catalog)["ref"], "user:scenario-method")
        state_file = self.store.project_dir("scenario") / "state.json"
        before = state_file.read_bytes()
        for invalid in (dict(choice, task="rewrite"), dict(choice, sha256="0" * 64),
                        dict(choice, provider="wrong-provider")):
            choice_file.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exact"):
                cli("project", "set-guide-choice", self.ws, "scenario", "--file", choice_file,
                    "--builtin-catalog", catalog, "--expected-revision", 1)
            self.assertEqual(state_file.read_bytes(), before)

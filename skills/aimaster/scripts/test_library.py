#!/usr/bin/env python3
"""Библиотека рабочей папки и `workspace init` (спецификация 2026-09-23 §3, §5).

Всё собирается командами `creator_studio.py` в этом же интерпретаторе на
синтетических файлах во временной папке. Ничего не уходит с машины.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import creator_studio  # noqa: E402
import montage_testkit  # noqa: E402
from studio import authoring  # noqa: E402
from studio.library import LibraryError, library_file, library_root, read_index  # noqa: E402


def can_symlink() -> bool:
    """Windows creates symlinks only with Developer Mode or elevation."""

    if not hasattr(os, "symlink"):
        return False
    with tempfile.TemporaryDirectory() as directory:
        try:
            os.symlink(directory, Path(directory) / "probe", target_is_directory=True)
        except (OSError, NotImplementedError):
            return False
    return True


CAN_SYMLINK = can_symlink()
from studio.library_match import stems  # noqa: E402


def cli(*argv):
    args = creator_studio.build_parser().parse_args([str(item) for item in argv])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        args.handler(args)
    return json.loads(buffer.getvalue())


def png_bytes(red=200):
    rows = b"".join(b"\x00" + bytes([red, 120, 60] * 8) for _ in range(8))

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def mp4_bytes():
    def box(kind, payload):
        return struct.pack(">I", 8 + len(payload)) + kind + payload

    return box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41") + box(b"mdat", b"\x00" * 16)


def wav_bytes():
    samples = b"\x00\x00" * 8000
    fmt = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, 8000, 16000, 2, 16)
    body = b"WAVE" + fmt + b"data" + struct.pack("<I", len(samples)) + samples
    return b"RIFF" + struct.pack("<I", len(body)) + body


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ws = self.root / "ws"
        montage_testkit.isolate_hyperframes_dir(self, self.root)
        cli("workspace", "init", self.ws)
        self.store = authoring.open_store(self.ws)

    def file(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def rev(self, pid):
        return self.store.load(pid)["revision"]

    def project_at_references(self, pid, mode="guided"):
        cli("project", "create", self.ws, pid, "--title", pid, "--type", "video", "--mode", mode)
        cli("script", "add-version", self.ws, pid, "--text", "Два героя в кафе.", "--reason", "v1",
            "--expected-revision", self.rev(pid))
        scenes = self.root / f"{pid}-scenes.json"
        scenes.write_text(json.dumps([{"scene_id": "s1", "title": "Кафе", "text": "Разговор.",
                                       "duration_ms": 4000}], ensure_ascii=False), encoding="utf-8")
        cli("scenes", "set", self.ws, pid, "--file", scenes, "--expected-revision", self.rev(pid))
        cli("stage", "approve", self.ws, pid, "--expected-revision", self.rev(pid))

    def media_reference(self, pid, name, data, *, kind="character", label, scene=None):
        path = self.ws / "media" / name
        path.write_bytes(data)
        asset = cli("asset", "register", self.ws, "--path", f"media/{name}", "--role", kind)
        extra = ["--scene", scene] if scene else []
        return cli("reference", "add", self.ws, pid, "--kind", kind, "--name", label,
                   "--asset-id", asset["asset_id"], *extra, "--expected-revision", self.rev(pid))


class WorkspaceInitTests(Base):
    def test_init_is_idempotent_and_keeps_readme(self):
        for folder in ("projects", "media", "instructions", ".studio", "library/characters",
                       "library/voices", "library/locations", "library/products", "library/styles",
                       "library/other"):
            self.assertTrue((self.ws / folder).is_dir(), folder)
        self.assertEqual(read_index(self.ws / "library")["entries"], [])
        (self.ws / "README.md").write_text("мой текст", encoding="utf-8")
        again = cli("workspace", "init", self.ws)
        self.assertEqual(again["created"], [])
        self.assertTrue(again["already_initialized"])
        self.assertEqual((self.ws / "README.md").read_text(encoding="utf-8"), "мой текст")

    def test_init_fills_only_missing_parts(self):
        (self.ws / "library" / "voices").rmdir()
        result = cli("workspace", "init", self.ws)
        self.assertEqual(result["created"], ["library/voices/"])


class LibraryAddTests(Base):
    def test_add_copies_file_and_refuses_duplicates(self):
        photo = self.file("alex.png", png_bytes())
        first = cli("library", "add", self.ws, "--kind", "character", "--label", "Александр",
                    "--alias", "Саша", "--file", photo)
        self.assertTrue(first["created"])
        stored = first["entry"]["files"][0]
        self.assertTrue(stored["path"].startswith("characters/"))
        self.assertTrue((self.ws / "library" / stored["path"]).is_file())
        copy = self.file("same-bytes.png", png_bytes())
        second = cli("library", "add", self.ws, "--kind", "character", "--label", "Alex", "--file", copy)
        self.assertFalse(second["created"])
        self.assertEqual(second["library_id"], first["library_id"])
        listing = cli("library", "list", self.ws)
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["entries"][0]["aliases"], ["Саша", "Alex"])
        self.assertEqual(cli("library", "list", self.ws, "--kind", "voice")["count"], 0)

    def test_voice_needs_audio_and_a_character_owner(self):
        character = cli("library", "add", self.ws, "--kind", "character", "--label", "Артём",
                        "--file", self.file("a.png", png_bytes(10)))
        voice = cli("library", "add", self.ws, "--kind", "voice", "--label", "Артём",
                    "--voice-of", character["library_id"], "--file", self.file("a.wav", wav_bytes()))
        self.assertEqual(voice["entry"]["voice_of"], character["library_id"])
        with self.assertRaises(LibraryError):
            cli("library", "add", self.ws, "--kind", "voice", "--label", "x",
                "--file", self.file("b.png", png_bytes(20)))
        with self.assertRaises(LibraryError):
            cli("library", "add", self.ws, "--kind", "voice", "--label", "x", "--voice-of", "nope",
                "--file", self.file("c.wav", wav_bytes() + b"\x00\x00"))


class LibraryPathTests(Base):
    def test_index_path_outside_library_is_rejected(self):
        index = self.ws / "library" / "index.json"
        index.write_text(json.dumps({"entries": [{
            "library_id": "x", "kind": "other", "label": "x", "aliases": [], "added_at": "t",
            "files": [{"path": "../projects/secret.png", "sha256": "0", "media": "image"}]}]}),
            encoding="utf-8")
        with self.assertRaises(LibraryError):
            cli("library", "list", self.ws)

    def test_relative_traversal_and_foreign_roots_are_rejected(self):
        library = library_root(self.ws)
        for relative in ("../README.md", "/etc/passwd", "C:/Windows/win.ini", "C:x.png",
                         "other\\..\\..\\x.png", "..\\README.md"):
            with self.subTest(relative=relative), self.assertRaises(LibraryError):
                library_file(library, relative)

    @unittest.skipUnless(CAN_SYMLINK, "this account cannot create symlinks")
    def test_symlink_escapes_are_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.png").write_bytes(png_bytes())
        library = library_root(self.ws)
        os.symlink(outside / "secret.png", library / "other" / "link.png")
        with self.assertRaises(LibraryError):
            library_file(library, "other/link.png")
        with self.assertRaises(LibraryError):
            library_file(library, "../README.md")
        (library / "styles").rmdir()
        os.symlink(outside, library / "styles", target_is_directory=True)
        with self.assertRaises(LibraryError):
            cli("library", "add", self.ws, "--kind", "style", "--label", "s",
                "--file", self.file("s.png", png_bytes(33)))

    @unittest.skipUnless(CAN_SYMLINK, "this account cannot create symlinks")
    def test_library_symlink_to_outside_is_rejected(self):
        other = self.root / "other-ws"
        cli("workspace", "init", other)
        (other / "library").rename(self.root / "moved")
        os.symlink(self.root / "moved", other / "library", target_is_directory=True)
        with self.assertRaises(LibraryError):
            cli("library", "list", other)


class LibraryImportMatchTests(Base):
    def setUp(self):
        super().setUp()
        self.project_at_references("one")
        self.project_at_references("two")
        self.alex = png_bytes(1)
        self.artem = png_bytes(2)
        self.media_reference("one", "alex.png", self.alex, label="Александр — основной персонаж")
        self.media_reference("two", "alex-copy.png", self.alex, label="Alex — rider")
        self.media_reference("two", "alex-again.png", self.alex, label="Александр — референс")
        self.media_reference("one", "artem.png", self.artem, label="Артём — второй персонаж")
        self.media_reference("two", "local.png", png_bytes(3), label="Локальный", scene="s1")
        (self.ws / "media" / "clip.mp4").write_bytes(mp4_bytes())
        clip = cli("asset", "register", self.ws, "--path", "media/clip.mp4", "--role", "video_reference")
        self.clip = cli("reference", "add", self.ws, "two", "--kind", "video", "--name", "Продолжение",
                        "--asset-id", clip["asset_id"], "--usage", "continue", "--scene", "s1",
                        "--expected-revision", self.rev("two"))["reference_id"]
        artem = self.store.load("one")["references"][-1]["reference_id"]
        cli("reference", "edit", self.ws, "one", "--reference", artem, "--field", "voice_enabled",
            "--value", "true", "--expected-revision", self.rev("one"))
        (self.ws / "media" / "artem.wav").write_bytes(wav_bytes())
        voice_asset = cli("asset", "register", self.ws, "--path", "media/artem.wav", "--role", "voice")
        cli("reference", "attach", self.ws, "one", "--reference", artem,
            "--asset-id", voice_asset["asset_id"], "--expected-revision", self.rev("one"))

    def test_import_takes_local_images_and_skips_project_clips(self):
        result = cli("library", "import", self.ws, "--from-projects")
        self.assertEqual(len(result["created"]), 4)
        self.assertEqual([(i["reference_id"], i["reason"]) for i in result["skipped"]],
                         [(self.clip, "project_clip")])
        self.assertIn("Локальный", [e["label"] for e in cli("library", "list", self.ws)["entries"]])
        entries = {entry["label"]: entry
                   for entry in cli("library", "list", self.ws, "--kind", "character")["entries"]}
        self.assertEqual(entries["Александр"]["aliases"],
                         ["Alex", "Александр — основной персонаж", "Alex — rider", "Александр — референс"])
        self.assertEqual(entries["Артём"]["kind"], "character")
        voices = cli("library", "list", self.ws, "--kind", "voice")["entries"]
        self.assertEqual(voices[0]["voice_of"], entries["Артём"]["library_id"])
        again = cli("library", "import", self.ws, "--from-projects")
        self.assertEqual(again["created"], [])
        self.assertEqual(again["entries"], 4)

    def test_match_ignores_case_and_endings(self):
        cli("library", "import", self.ws, "--from-projects")
        found = cli("library", "match", self.ws, "--text", "ролик с Артёмом и АЛЕКСАНДРОМ в кафе")
        kinds = sorted((m["kind"], m["label"]) for m in found["matches"])
        self.assertEqual(kinds, [("character", "Александр"), ("character", "Артём"), ("voice", "Артём")])
        self.assertEqual(cli("library", "match", self.ws, "--text", "артист в кафе")["count"], 0)
        self.assertEqual(stems("артем"), frozenset({"артем", "арте"}))

    def test_reference_add_from_library_in_new_project(self):
        cli("library", "import", self.ws, "--from-projects")
        artem = next(e for e in cli("library", "list", self.ws, "--kind", "character")["entries"]
                     if e["label"] == "Артём")
        voice = cli("library", "list", self.ws, "--kind", "voice")["entries"][0]
        self.project_at_references("three", mode="autopilot")
        added = cli("reference", "add", self.ws, "three", "--from-library", artem["library_id"],
                    "--expected-revision", self.rev("three"))
        self.assertEqual(added["kind"], "character")
        reference = self.store.load("three")["references"][-1]
        self.assertEqual(reference["label"], "Артём")
        self.assertEqual(reference["source"], "upload")
        self.assertEqual(reference["asset_id"], added["asset_id"])
        self.assertTrue(any((self.ws / "media" / "library" / "characters").iterdir()))
        cli("reference", "edit", self.ws, "three", "--reference", added["reference_id"],
            "--field", "voice_enabled", "--value", "true", "--expected-revision", self.rev("three"))
        attached = cli("reference", "attach", self.ws, "three", "--reference", added["reference_id"],
                       "--from-library", voice["library_id"], "--expected-revision", self.rev("three"))
        self.assertEqual(self.store.load("three")["references"][-1]["voice"]["asset_id"], attached["asset_id"])
        with self.assertRaises(ValueError):
            cli("reference", "add", self.ws, "three", "--from-library", voice["library_id"],
                "--expected-revision", self.rev("three"))


class GeneratedReferenceImportTests(Base):
    """Сгенерированный референс даёт выбранный результат, иначе принятый."""

    def setUp(self):
        super().setUp()
        self.project_at_references("gen")
        self.assets = {}
        for name, red in (("cafe-v1", 40), ("cafe-v2", 41), ("pen-v1", 50), ("pen-v2", 51),
                          ("wall-v1", 60), ("hidden-v1", 70)):
            (self.ws / "media" / f"{name}.png").write_bytes(png_bytes(red))
            self.assets[name] = cli("asset", "register", self.ws, "--path", f"media/{name}.png",
                                    "--role", "result")["asset_id"]
        refs = {}
        for label, kind in (("Кафе — паб", "location"), ("Ручка — сувенир", "product"),
                            ("Стена", "style"), ("Скрытое", "other"), ("Пустое", "location")):
            refs[label] = cli("reference", "add", self.ws, "gen", "--kind", kind, "--name", label,
                              "--source", "generate",
                              "--expected-revision", self.rev("gen"))["reference_id"]
        self.refs = refs
        a = self.assets

        def version(ref, n, asset, **extra):
            return {"result_id": f"result:ref:{ref}", "version_id": f"result:ref:{ref}-v{n}",
                    "asset_id": asset, "status": "ready", **extra}

        cafe, pen, wall, hidden = (refs[k] for k in ("Кафе — паб", "Ручка — сувенир", "Стена", "Скрытое"))

        def mutate(state):
            state.setdefault("image_results", []).extend([
                version(cafe, 1, a["cafe-v1"], decision="approved"),
                version(cafe, 2, a["cafe-v2"]),
                version(pen, 1, a["pen-v1"], decision="approved"),
                version(pen, 2, a["pen-v2"], decision="rejected"),
                version(wall, 1, a["wall-v1"], decision="rejected"),
                version(hidden, 1, a["hidden-v1"], decision="approved", hidden=True),
            ])
            for reference in state["references"]:
                if reference["reference_id"] == cafe:
                    reference.setdefault("links", {})["image_result_id"] = f"result:ref:{cafe}-v2"
                if reference["reference_id"] == pen:
                    reference.setdefault("links", {})["image_result_id"] = f"result:ref:{pen}-v2"

        self.store.transact("gen", self.rev("gen"), mutate)

    def test_selected_then_approved_and_skips(self):
        result = cli("library", "import", self.ws, "--from-projects")
        self.assertEqual(len(result["created"]), 2)
        reasons = {item["reference_id"]: item["reason"] for item in result["skipped"]}
        for label in ("Стена", "Скрытое", "Пустое"):
            self.assertEqual(reasons[self.refs[label]], "no_selected_result", label)
        entries = {e["label"]: e for e in cli("library", "list", self.ws)["entries"]}
        self.assertEqual(entries["Кафе — паб"]["kind"], "location")
        self.assertEqual(entries["Ручка — сувенир"]["kind"], "product")
        cafe_v2 = (self.ws / "media" / "cafe-v2.png").read_bytes()
        pen_v1 = (self.ws / "media" / "pen-v1.png").read_bytes()
        self.assertEqual(entries["Кафе — паб"]["files"][0]["sha256"], hashlib.sha256(cafe_v2).hexdigest())
        self.assertEqual(entries["Ручка — сувенир"]["files"][0]["sha256"], hashlib.sha256(pen_v1).hexdigest())
        self.assertEqual(cli("library", "import", self.ws, "--from-projects")["created"], [])


class ImportLabelRuleTests(Base):
    def setUp(self):
        super().setUp()
        self.project_at_references("p")
        self.media_reference("p", "look.png", png_bytes(90), kind="style",
                             label="AI Мастерская — dark boho riding look")
        self.media_reference("p", "hero.png", png_bytes(91), label="Артём — второй персонаж")

    def labels(self):
        return {e["kind"]: (e["label"], e["aliases"]) for e in cli("library", "list", self.ws)["entries"]}

    def test_only_people_are_shortened_and_full_caption_is_an_alias(self):
        cli("library", "import", self.ws, "--from-projects")
        labels = self.labels()
        self.assertEqual(labels["style"], ("AI Мастерская — dark boho riding look", []))
        self.assertEqual(labels["character"], ("Артём", ["Артём — второй персонаж"]))

    def test_reimport_relabels_derived_entries_but_not_manual_ones(self):
        cli("library", "import", self.ws, "--from-projects")
        index_path = self.ws / "library" / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for entry in index["entries"]:
            if entry["kind"] == "style":
                entry["label"], entry["aliases"] = "AI Мастерская", []
        index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        manual = cli("library", "add", self.ws, "--kind", "location", "--label", "Моё место — как есть",
                     "--file", self.file("place.png", png_bytes(92)))
        (self.ws / "media" / "place.png").write_bytes(png_bytes(92))
        asset = cli("asset", "register", self.ws, "--path", "media/place.png", "--role", "location")
        cli("reference", "add", self.ws, "p", "--kind", "location", "--name", "Другое имя",
            "--asset-id", asset["asset_id"], "--expected-revision", self.rev("p"))
        result = cli("library", "import", self.ws, "--from-projects")
        style_id = next(e["library_id"] for e in index["entries"] if e["kind"] == "style")
        self.assertEqual(result["relabeled"], [style_id])
        labels = self.labels()
        self.assertEqual(labels["style"][0], "AI Мастерская — dark boho riding look")
        self.assertEqual(labels["location"][0], "Моё место — как есть")
        self.assertIn(manual["library_id"], result["already_in_library"])


if __name__ == "__main__":
    unittest.main()

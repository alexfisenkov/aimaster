#!/usr/bin/env python3
"""Референс вида «Прочее» (`kind=other`).

Спецификация перестройки дашборда §5: к четырём основным видам добавлен
пятый — «загрузить что угодно» без категории. Он ведёт себя ровно как
`product`: не попадает автоматически во все сцены (это делает только
`style`) и не может иметь голоса.

Проект собирается теми же командами `creator_studio.py`, какими его пишет
агент, только без запуска процесса: разбор аргументов и обработчик
вызываются в этом же интерпретаторе. Ничего не уходит с машины.
"""

from __future__ import annotations

import io
import json
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
from studio import authoring  # noqa: E402
from studio.assets import REFERENCE_ROLES  # noqa: E402
from studio.domain import DomainValidationError, add_reference, default_reference_prompt  # noqa: E402
from studio.projection import build_snapshot  # noqa: E402
from studio.telegram_prompts import _REFERENCE_KINDS  # noqa: E402


def cli(*argv):
    args = creator_studio.build_parser().parse_args([str(item) for item in argv])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        args.handler(args)
    return buffer.getvalue()


def revision(workspace, project_id):
    return authoring.open_store(Path(workspace)).load(project_id)["revision"]


def png_bytes(width=8, height=8):
    rows = b"".join(b"\x00" + bytes([200, 120, 60] * width) for _ in range(height))

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class ReferenceKindOtherTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.workspace = self.root / "ws"
        (self.workspace / "media").mkdir(parents=True)
        self.pid = "proba"
        cli("project", "create", self.workspace, self.pid, "--title", "Проба", "--type", "video")
        cli("script", "add-version", self.workspace, self.pid, "--text",
            "Один герой достаёт со стола листовку и показывает её в камеру.",
            "--reason", "первая версия", "--expected-revision", revision(self.workspace, self.pid))
        scenes = self.root / "scenes.json"
        scenes.write_text(json.dumps([
            {"scene_id": "s1", "title": "Стол", "text": "Герой берёт листовку.", "duration_ms": 4000},
            {"scene_id": "s2", "title": "Камера", "text": "Герой показывает листовку.", "duration_ms": 3000},
        ], ensure_ascii=False), encoding="utf-8")
        cli("scenes", "set", self.workspace, self.pid, "--file", scenes,
            "--expected-revision", revision(self.workspace, self.pid))
        cli("stage", "approve", self.workspace, self.pid,
            "--expected-revision", revision(self.workspace, self.pid))

    def snapshot(self):
        store = authoring.open_store(self.workspace)
        state = store.load(self.pid)
        state["questions"] = []
        state["actions"] = []
        return build_snapshot(store.list_projects(), state, asset_url=lambda aid: f"/assets/{aid}")

    def reference(self, snapshot, reference_id):
        matches = [item for item in snapshot["active_project"]["references"]
                   if item["reference_id"] == reference_id]
        self.assertEqual(len(matches), 1, reference_id)
        return matches[0]

    # -- CLI, домен, проекция -------------------------------------------

    def test_cli_accepts_other_and_projection_reports_it(self):
        printed = cli("reference", "add", self.workspace, self.pid, "--kind", "other",
                      "--name", "Листовка мастерской", "--source", "generate",
                      "--expected-revision", revision(self.workspace, self.pid))
        tag = json.loads(printed)["reference_id"]
        reference = self.reference(self.snapshot(), tag)
        self.assertEqual(reference["kind"], "other")
        self.assertEqual(reference["label"], "Листовка мастерской")
        self.assertEqual(reference["source"], "generate")
        self.assertIs(reference["local"], False)

    def test_other_is_not_added_to_every_scene_the_way_style_is(self):
        other = json.loads(cli("reference", "add", self.workspace, self.pid, "--kind", "other",
                               "--name", "Листовка", "--source", "generate",
                               "--expected-revision", revision(self.workspace, self.pid)))["reference_id"]
        style = json.loads(cli("reference", "add", self.workspace, self.pid, "--kind", "style",
                               "--name", "Общий стиль", "--source", "generate",
                               "--expected-revision", revision(self.workspace, self.pid)))["reference_id"]
        for scene in self.snapshot()["active_project"]["scenes"]:
            linked = scene["links"].get("reference_ids", [])
            self.assertIn(style, linked, scene["scene_id"])
            self.assertNotIn(other, linked, scene["scene_id"])

    def test_other_can_be_local_to_one_scene(self):
        tag = json.loads(cli("reference", "add", self.workspace, self.pid, "--kind", "other",
                             "--name", "Только для стола", "--source", "generate",
                             "--scene", "s1",
                             "--expected-revision", revision(self.workspace, self.pid)))["reference_id"]
        reference = self.reference(self.snapshot(), tag)
        self.assertIs(reference["local"], True)
        self.assertEqual(reference["scene_id"], "s1")

    def test_generated_other_gets_its_own_default_prompt(self):
        tag = json.loads(cli("reference", "add", self.workspace, self.pid, "--kind", "other",
                             "--name", "Листовка", "--source", "generate",
                             "--expected-revision", revision(self.workspace, self.pid)))["reference_id"]
        project = self.snapshot()["active_project"]
        version_id = self.reference({"active_project": project}, tag)["links"]["image_prompt_version_id"]
        prompts = [item for item in project["image_prompts"] if item["version_id"] == version_id]
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["text"], default_reference_prompt("other"))
        self.assertTrue(prompts[0]["text"].strip())

    def test_uploaded_other_accepts_an_asset_registered_with_the_same_role(self):
        media = self.workspace / "media"
        media.mkdir(parents=True, exist_ok=True)
        (media / "flyer.png").write_bytes(png_bytes())
        asset_id = json.loads(cli("asset", "register", self.workspace,
                                  "--path", "media/flyer.png", "--role", "other"))["asset_id"]
        tag = json.loads(cli("reference", "add", self.workspace, self.pid, "--kind", "other",
                             "--name", "Листовка из файла", "--asset-id", asset_id,
                             "--expected-revision", revision(self.workspace, self.pid)))["reference_id"]
        reference = self.reference(self.snapshot(), tag)
        self.assertIs(reference["has_asset"], True)
        self.assertEqual(reference["source"], "upload")
        self.assertIn("other", REFERENCE_ROLES)

    def test_other_has_no_voice(self):
        tag = json.loads(cli("reference", "add", self.workspace, self.pid, "--kind", "other",
                             "--name", "Листовка", "--source", "generate",
                             "--expected-revision", revision(self.workspace, self.pid)))["reference_id"]
        self.assertIs(self.reference(self.snapshot(), tag)["voice"]["enabled"], False)
        with self.assertRaises(Exception):
            cli("reference", "edit", self.workspace, self.pid, "--reference", tag,
                "--field", "voice_enabled", "--value", "true",
                "--expected-revision", revision(self.workspace, self.pid))

    def test_unknown_kind_is_still_refused(self):
        state = authoring.open_store(self.workspace).load(self.pid)
        with self.assertRaises(DomainValidationError):
            add_reference(state, kind="whatever", name="Нечто", source="upload")

    def test_telegram_dictionary_names_the_new_kind_in_russian(self):
        self.assertEqual(_REFERENCE_KINDS["other"], "прочее")


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Версии: v001, v002…; снимок публикуется целиком; не перезаписываются; возврат с резервной копией.

Резервация версии — по round-fix-3/5: один build_lock на весь `montage
build`, не резервации с проверкой возраста (test_montage_version_staging.py
несёт остальные тесты этой части — build_lock/settle_orphans/stage_version)."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage import MontageError  # noqa: E402
from studio.montage.model import Clip, Model  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.version_staging import discard_staging, publish_version, stage_version  # noqa: E402
from studio.montage.versions import (  # noqa: E402
    VersionMeta, has_unrendered_changes, list_versions, next_version_id, read_meta,
    read_version_model, restore_files)
import studio.montage.versions as versions_module  # noqa: E402

MODEL = Model(1.0, (Clip(id="v-1", layer="video", kind="video", start=0.0, duration=1.0),))


def meta(version, based_on=None, model_hash="h1"):
    return VersionMeta(version=version, created_at="2026-09-25T10:00:00+00:00", by="agent",
                       based_on=based_on, summary="Черновой монтаж",
                       changes=("черновой монтаж: 1 клип, 1,0 с",), asset_id="asset-x",
                       model_hash=model_hash)


class VersionsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.paths = montage_paths(Path(temp.name).resolve() / "p")
        self.paths.current.mkdir(parents=True)
        self.paths.index.write_text("<html>v1</html>", encoding="utf-8")

    def publish(self, version, **kwargs):
        staging = stage_version(self.paths, meta(version, **kwargs), MODEL)
        return publish_version(self.paths, staging, version)

    def test_first_version_is_published_whole(self):
        self.assertEqual(next_version_id(self.paths, recorded_ids=[]), "v001")
        staging = stage_version(self.paths, meta("v001"), MODEL)
        self.assertFalse(self.paths.version_dir("v001").exists())
        final = publish_version(self.paths, staging, "v001")
        self.assertEqual((final / "index.html").read_text(encoding="utf-8"), "<html>v1</html>")
        self.assertEqual(json.loads((final / "meta.json").read_text(encoding="utf-8"))["version"], "v001")
        self.assertEqual(read_version_model(self.paths, "v001"), MODEL)
        self.assertEqual(list_versions(self.paths), [meta("v001")])
        self.assertEqual(next_version_id(self.paths, recorded_ids=[]), "v002")

    def test_versions_are_never_overwritten(self):
        self.publish("v001")
        with self.assertRaises(MontageError) as caught:
            stage_version(self.paths, meta("v001"), MODEL)
        self.assertIn("не перезаписываются", str(caught.exception))

    def test_discarded_staging_leaves_no_version(self):
        discard_staging(stage_version(self.paths, meta("v001"), MODEL))
        self.assertEqual(list_versions(self.paths), [])
        self.assertEqual(list(self.paths.versions.iterdir()), [])

    def test_list_ignores_staging_and_foreign_folders(self):
        self.publish("v001")
        (self.paths.versions / ".v002.staging").mkdir()
        (self.paths.versions / "notes").mkdir()
        self.assertEqual([m.version for m in list_versions(self.paths)], ["v001"])
        with self.assertRaises(MontageError):
            read_meta(self.paths, "v009")

    def test_restore_copies_the_snapshot_and_keeps_a_backup(self):
        self.publish("v001")
        self.paths.index.write_text("<html>v2 edited</html>", encoding="utf-8")
        backup = restore_files(self.paths, "v001")
        self.assertEqual(self.paths.index.read_text(encoding="utf-8"), "<html>v1</html>")
        self.assertEqual(backup.read_text(encoding="utf-8"), "<html>v2 edited</html>")
        self.assertEqual(backup.parent, self.paths.undo)
        with self.assertRaises(MontageError):
            restore_files(self.paths, "v007")

    def test_restore_failure_does_not_leak_raw_os_error_text(self):
        # Round-fix-3/5, item F: OSError.__str__ часто по-английски и
        # локале-зависимый — не в тексте отказа, только в цепочке (from error).
        self.publish("v001")
        with mock.patch.object(versions_module, "replace_file",
                               side_effect=OSError("boom-english-text")):
            with self.assertRaises(MontageError) as caught:
                restore_files(self.paths, "v001")
        self.assertNotIn("boom-english-text", str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, OSError)

    def test_unrendered_changes(self):
        self.assertFalse(has_unrendered_changes("h1", meta("v001", model_hash="h1")))
        self.assertTrue(has_unrendered_changes("h2", meta("v001", model_hash="h1")))
        self.assertTrue(has_unrendered_changes("h1", None))

    def test_next_version_id_requires_recorded_ids_and_accounts_for_them(self):
        # Round-fix-3/5, item B: recorded_ids — обязательный именованный
        # аргумент; staging здесь больше не участвует вовсе (счёт по одному
        # только диску и state) — settle_orphans разбирает staging раньше,
        # чем эта функция вообще может быть вызвана в реальном потоке.
        self.publish("v001")
        self.publish("v002")
        self.assertEqual(next_version_id(self.paths, recorded_ids=["v003"]), "v004")
        with self.assertRaises(TypeError):
            next_version_id(self.paths)  # без recorded_ids — TypeError, не тихое умолчание

    def test_restore_does_not_collide_on_a_fixed_temp_name(self):
        # Round-fix-1/5, item 11: временное имя — mkstemp, не фиксированное
        # ".index.restore.tmp"; два восстановления подряд не должны спотыкаться
        # друг о друга или оставлять after себя фиксированное имя.
        self.publish("v001")
        restore_files(self.paths, "v001")
        restore_files(self.paths, "v001")
        self.assertFalse((self.paths.current / ".index.restore.tmp").exists())
        self.assertEqual(self.paths.index.read_text(encoding="utf-8"), "<html>v1</html>")

    def test_restore_from_two_threads_at_once_does_not_collide(self):
        # Round-fix-2/5, item 9: прежний тест только проверял, что имя не
        # фиксировано — здесь настоящая гонка, несколько потоков одновременно.
        self.publish("v001")
        errors = []

        def go():
            try:
                restore_files(self.paths, "v001")
            except Exception as error:  # тест обязан явно увидеть любую ошибку потока
                errors.append(error)

        threads = [threading.Thread(target=go) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.paths.index.read_text(encoding="utf-8"), "<html>v1</html>")


if __name__ == "__main__":
    unittest.main()

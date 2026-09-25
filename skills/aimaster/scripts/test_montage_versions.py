#!/usr/bin/env python3
"""Версии: v001, v002…; снимок публикуется целиком; не перезаписываются; возврат с резервной копией."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage import MontageError  # noqa: E402
from studio.montage.model import Clip, Model  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.version_staging import _reserve  # noqa: E402
from studio.montage.versions import (  # noqa: E402
    VersionMeta, discard_staging, has_unrendered_changes, list_versions, next_version_id,
    publish_version, read_meta, read_version_model, recover_published_from_staging,
    reserve_version, restore_files, stage_version)

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
        self.assertEqual(next_version_id(self.paths), "v001")
        staging = stage_version(self.paths, meta("v001"), MODEL)
        self.assertFalse(self.paths.version_dir("v001").exists())
        final = publish_version(self.paths, staging, "v001")
        self.assertEqual((final / "index.html").read_text(encoding="utf-8"), "<html>v1</html>")
        self.assertEqual(json.loads((final / "meta.json").read_text(encoding="utf-8"))["version"], "v001")
        self.assertEqual(read_version_model(self.paths, "v001"), MODEL)
        self.assertEqual(list_versions(self.paths), [meta("v001")])
        self.assertEqual(next_version_id(self.paths), "v002")

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

    def test_unrendered_changes(self):
        self.assertFalse(has_unrendered_changes("h1", meta("v001", model_hash="h1")))
        self.assertTrue(has_unrendered_changes("h2", meta("v001", model_hash="h1")))
        self.assertTrue(has_unrendered_changes("h1", None))

    def test_parallel_build_of_the_same_version_is_refused(self):
        # Round-fix-1/5, item 2а: check-then-act («есть? снести, создать»)
        # давал окно гонки — теперь резервация одним mkdir.
        stage_version(self.paths, meta("v002"), MODEL)  # никто не опубликовал — «сборка ещё идёт»
        with self.assertRaises(MontageError) as caught:
            stage_version(self.paths, meta("v002"), MODEL)
        self.assertIn("уже идёт", str(caught.exception))

    def test_stale_staging_is_swept_and_replaced(self):
        staging = stage_version(self.paths, meta("v002"), MODEL)
        old = time.time() - 3700
        os.utime(staging, (old, old))
        fresh = stage_version(self.paths, meta("v002"), MODEL)
        self.assertTrue(fresh.is_dir())
        self.assertTrue((fresh / "meta.json").is_file())

    def test_next_version_id_accounts_for_state_and_staging(self):
        # Round-fix-1/5, item 2б: диск может отстать от state (снимок ещё не
        # опубликован, но state уже знает о версии) — счётчик не должен застревать.
        self.publish("v001")
        self.publish("v002")
        self.assertEqual(next_version_id(self.paths, recorded_ids=["v003"]), "v004")
        (self.paths.versions / ".v005.staging").mkdir()
        self.assertEqual(next_version_id(self.paths), "v006")

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

    def test_reserve_version_picks_and_holds_the_next_number(self):
        # Round-fix-2/5, item 4: next_version_id и резервация — одним вызовом,
        # чтобы между выбором номера и резервацией не влез параллельный вызов.
        first = reserve_version(self.paths)
        self.assertEqual(first, "v001")
        self.assertTrue((self.paths.versions / ".v001.staging").is_dir())
        # v001 ещё не опубликована, но уже занята нашей же резервацией —
        # следующий вызов должен получить следующий номер, не тот же.
        self.assertEqual(reserve_version(self.paths), "v002")

    def test_reserve_version_accounts_for_recorded_ids(self):
        self.assertEqual(reserve_version(self.paths, recorded_ids=["v001", "v002"]), "v003")

    def test_reserve_collision_on_the_same_number_is_refused(self):
        # _reserve — общий примитив reserve_version/stage_version; гонку на
        # ОДНОМ и том же номере (как если бы next_version_id прочли
        # одновременно, до появления .vNNN.staging) проверяем напрямую.
        _reserve(self.paths, "v001")
        with self.assertRaises(MontageError) as caught:
            _reserve(self.paths, "v001")
        self.assertIn("уже идёт", str(caught.exception))

    def test_stage_version_releases_reservation_on_failure(self):
        # Round-fix-2/5, item 4: сбой копирования/записи снимка не должен
        # оставлять резервацию висеть до истечения часа.
        broken = montage_paths(self.paths.root.parent / "сломанный")
        broken.versions.mkdir(parents=True)  # current/index.html нарочно не создаём
        with self.assertRaises(OSError):
            stage_version(broken, meta("v001"), MODEL)
        self.assertEqual(list(broken.versions.iterdir()), [])

    def test_recover_publishes_a_complete_orphaned_staging(self):
        # Round-fix-2/5, item 4: сборка успела дописать снимок целиком, но
        # процесс оборвался до publish_version — задача 15 зовёт это вместо
        # пересборки.
        staging = stage_version(self.paths, meta("v001"), MODEL)
        final = recover_published_from_staging(self.paths, "v001")
        self.assertEqual(final, self.paths.version_dir("v001"))
        self.assertTrue((final / "meta.json").is_file())
        self.assertFalse(staging.exists())

    def test_recover_ignores_incomplete_or_already_published(self):
        self.assertIsNone(recover_published_from_staging(self.paths, "v009"))
        staging = stage_version(self.paths, meta("v002"), MODEL)
        (staging / "model.json").unlink()  # неполный снимок — не публикуем
        self.assertIsNone(recover_published_from_staging(self.paths, "v002"))
        self.publish("v003")
        self.assertIsNone(recover_published_from_staging(self.paths, "v003"))  # уже опубликована


if __name__ == "__main__":
    unittest.main()

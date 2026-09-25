#!/usr/bin/env python3
"""build_lock: один замок на сборку; settle_orphans разбирает staging под ним; stage_version снимает."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage import MontageError, version_staging  # noqa: E402
from studio.montage.model import Clip, Model  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402
from studio.montage.version_staging import (  # noqa: E402
    build_lock, publish_version, settle_orphans, stage_version)
from studio.montage.versions import VersionMeta, next_version_id  # noqa: E402
from studio.platform_compat import IS_WINDOWS, LockBusyError  # noqa: E402

MODEL = Model(1.0, (Clip(id="v-1", layer="video", kind="video", start=0.0, duration=1.0),))

_BUILD_LOCK_HOLDER = """
import sys, time
sys.path.insert(0, sys.argv[1])
from studio.montage.paths import montage_paths
from studio.montage.version_staging import build_lock
with build_lock(montage_paths(sys.argv[2])):
    print("locked", flush=True)
    time.sleep(float(sys.argv[3]))
"""


def _start_holder(project_dir, seconds):
    return subprocess.Popen(
        [sys.executable, "-c", _BUILD_LOCK_HOLDER, str(_SKILL_ROOT), str(project_dir), str(seconds)],
        stdout=subprocess.PIPE, encoding="utf-8", errors="replace")


def _stop_holder(holder):
    """Всегда в finally: упавшая проверка не должна оставить держателя замка жить час."""

    if holder.poll() is None:
        holder.kill()
    holder.wait(timeout=30)
    holder.stdout.close()


def meta(version, based_on=None, model_hash="h1"):
    return VersionMeta(version=version, created_at="2026-09-25T10:00:00+00:00", by="agent",
                       based_on=based_on, summary="Черновой монтаж",
                       changes=("черновой монтаж: 1 клип, 1,0 с",), asset_id="asset-x",
                       model_hash=model_hash)


class VersionStagingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project_dir = Path(temp.name).resolve() / "p"
        self.paths = montage_paths(self.project_dir)
        self.paths.current.mkdir(parents=True)
        self.paths.index.write_text("<html>v1</html>", encoding="utf-8")

    def test_full_build_flow_without_reservations(self):
        # Round-fix-3/5, item B: поток без резерваций — settle_orphans,
        # next_version_id, stage_version, publish_version, всё под одним
        # build_lock; ни одна функция не резервирует номер заранее.
        with build_lock(self.paths):
            self.assertEqual(settle_orphans(self.paths, recorded_ids=[]), [])
            version_id = next_version_id(self.paths, recorded_ids=[])
            self.assertEqual(version_id, "v001")
            staging = stage_version(self.paths, meta(version_id), MODEL)
            # ... здесь в реальном потоке идёт montage_state.record_version ...
            final = publish_version(self.paths, staging, version_id)
        self.assertTrue(final.is_dir())
        self.assertEqual(next_version_id(self.paths, recorded_ids=[]), "v002")

    def test_second_build_lock_in_the_same_process_is_refused(self):
        with build_lock(self.paths):
            with self.assertRaises(MontageError) as caught:
                with build_lock(self.paths):
                    pass
        self.assertIn("уже идёт", str(caught.exception))

    def test_build_lock_across_processes_is_refused(self):
        holder = _start_holder(self.project_dir, 3600)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "locked")
            with self.assertRaises(MontageError) as caught:
                with build_lock(self.paths):
                    pass
            self.assertIn("уже идёт", str(caught.exception))
        finally:
            _stop_holder(holder)

    def test_build_lock_is_released_when_the_holder_process_is_killed(self):
        # «Гвардия ОС», не наша: замок умирает вместе с процессом, который
        # его держал — краш сборки не должен требовать ручной зачистки замка.
        holder = _start_holder(self.project_dir, 3600)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "locked")
            with self.assertRaises(MontageError):
                with build_lock(self.paths):
                    pass
        finally:
            _stop_holder(holder)
        # Windows снимает байтовый замок убитого процесса не мгновенно — недолго повторяем.
        deadline = time.monotonic() + (10 if IS_WINDOWS else 0)
        while True:
            try:
                with build_lock(self.paths):
                    break
            except MontageError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)

    def test_errors_from_the_build_itself_pass_through_unchanged(self):
        for error in (LockBusyError("чужой замок внутри сборки"), ValueError("сбой сборки")):
            with self.assertRaises(type(error)) as caught:
                with build_lock(self.paths):
                    raise error
            self.assertIs(caught.exception, error)
        with build_lock(self.paths):  # замок отпущен и после ошибки
            pass

    def test_lock_that_cannot_be_opened_is_a_russian_refusal(self):
        blocker = self.project_dir.parent / "файл-вместо-папки"
        blocker.write_text("x", encoding="utf-8")
        with self.assertRaises(MontageError) as caught:
            with build_lock(montage_paths(blocker)):
                pass
        self.assertIn("замок сборки", str(caught.exception))

    def test_filesystem_without_locks_is_a_russian_refusal(self):
        unsupported = OSError(95, "Operation not supported")
        with mock.patch.object(version_staging, "file_lock", side_effect=unsupported):
            with self.assertRaises(MontageError) as caught:
                with build_lock(self.paths):
                    pass
        self.assertIn("не поддерживает блокировки", str(caught.exception))

    def test_settle_orphans_recovers_a_complete_recorded_staging(self):
        staging = stage_version(self.paths, meta("v001"), MODEL)
        recovered = settle_orphans(self.paths, recorded_ids=["v001"])
        self.assertEqual(recovered, ["v001"])
        self.assertFalse(staging.exists())
        self.assertTrue(self.paths.version_dir("v001").is_dir())

    def test_settle_orphans_discards_unrecorded_staging(self):
        staging = stage_version(self.paths, meta("v001"), MODEL)
        recovered = settle_orphans(self.paths, recorded_ids=[])  # state не знает о v001
        self.assertEqual(recovered, [])
        self.assertFalse(staging.exists())
        self.assertFalse(self.paths.version_dir("v001").exists())

    def test_settle_orphans_discards_corrupt_staging(self):
        staging = stage_version(self.paths, meta("v001"), MODEL)
        (staging / "meta.json").write_text("не json", encoding="utf-8")
        recovered = settle_orphans(self.paths, recorded_ids=["v001"])
        self.assertEqual(recovered, [])
        self.assertFalse(staging.exists())
        self.assertFalse(self.paths.version_dir("v001").exists())

    def test_settle_orphans_discards_incomplete_staging(self):
        staging = stage_version(self.paths, meta("v001"), MODEL)
        (staging / "model.json").unlink()
        recovered = settle_orphans(self.paths, recorded_ids=["v001"])
        self.assertEqual(recovered, [])
        self.assertFalse(staging.exists())

    def test_settle_orphans_ignores_published_versions_and_foreign_folders(self):
        staging = stage_version(self.paths, meta("v001"), MODEL)
        publish_version(self.paths, staging, "v001")
        (self.paths.versions / "notes").mkdir()
        self.assertEqual(settle_orphans(self.paths, recorded_ids=["v001"]), [])
        self.assertTrue(self.paths.version_dir("v001").is_dir())
        self.assertTrue((self.paths.versions / "notes").is_dir())

    def test_settle_orphans_discards_a_second_snapshot_of_a_published_version(self):
        publish_version(self.paths, stage_version(self.paths, meta("v001"), MODEL), "v001")
        stray = self.paths.versions / ".v001.staging"  # полный второй снимок той же версии
        shutil.copytree(self.paths.version_dir("v001"), stray)
        (stray / "index.html").write_text("<html>другое</html>", encoding="utf-8")
        self.assertEqual(settle_orphans(self.paths, recorded_ids=["v001"]), [])
        self.assertFalse(stray.exists())
        self.assertEqual((self.paths.version_dir("v001") / "index.html").read_text(encoding="utf-8"),
                         "<html>v1</html>")

    def test_settle_orphans_keeps_a_snapshot_it_could_not_publish(self):
        staging = stage_version(self.paths, meta("v001"), MODEL)
        with mock.patch.object(version_staging.os, "rename", side_effect=PermissionError(13, "busy")):
            self.assertEqual(settle_orphans(self.paths, recorded_ids=["v001"]), [])
        self.assertTrue(staging.is_dir())
        self.assertEqual(settle_orphans(self.paths, recorded_ids=["v001"]), ["v001"])

    def test_stage_version_snapshots_the_given_text_byte_for_byte(self):
        staging = stage_version(self.paths, meta("v001"), MODEL, index_text="<html>\r\nсобрано</html>")
        with (staging / "index.html").open(encoding="utf-8", newline="") as handle:
            self.assertEqual(handle.read(), "<html>\r\nсобрано</html>")

    def test_stage_version_refuses_a_stray_collision(self):
        (self.paths.versions / ".v001.staging").mkdir(parents=True)
        with self.assertRaises(MontageError) as caught:
            stage_version(self.paths, meta("v001"), MODEL)
        self.assertIn("уже собирается", str(caught.exception))

    def test_stage_version_releases_its_folder_on_failure(self):
        broken = montage_paths(self.project_dir.parent / "сломанный")
        broken.versions.mkdir(parents=True)  # current/index.html нарочно не создаём
        with self.assertRaises(MontageError) as caught:
            stage_version(broken, meta("v001"), MODEL)
        self.assertIn("v001", str(caught.exception))
        self.assertEqual(list(broken.versions.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Общая уборка временных папок (studio/montage/temp_sweep.py): только точный вид
tempfile.mkdtemp, только старше часа, по ссылкам не ходит, наружу не бросает."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

_SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from studio.montage import temp_sweep  # noqa: E402

PREFIX = ".aimaster-tmp-download-"
POSIX_PERMS = unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                              "права доступа POSIX: на Windows и под root действуют иначе")


def make_old(path: Path, seconds: float = 7200) -> Path:
    moment = time.time() - seconds
    os.utime(path, (moment, moment))
    return path


class SweepTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.parent = self.base / "кеш"
        self.parent.mkdir()

    def mkdtemp(self) -> Path:
        path = Path(tempfile.mkdtemp(prefix=PREFIX, dir=str(self.parent)))
        (path / "leftover.txt").write_text("мусор", encoding="utf-8")
        return path

    def sweep(self, **kwargs) -> None:
        temp_sweep.sweep_stale(self.parent, PREFIX, **kwargs)

    def test_old_real_mkdtemp_dir_is_removed_fresh_one_kept(self):
        # настоящий mkdtemp этого Python — страховка от смены вида имени в будущих версиях
        old, fresh = make_old(self.mkdtemp()), self.mkdtemp()
        self.sweep()
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_min_age_is_respected(self):
        path = make_old(self.mkdtemp(), seconds=60)
        self.sweep()
        self.assertTrue(path.exists())
        self.sweep(min_age=30)
        self.assertFalse(path.exists())

    def test_only_the_exact_mkdtemp_shape_matches(self):
        names = [PREFIX + "notes", PREFIX + "abcdefghi", PREFIX + "abcdefg", PREFIX + "ABCDEFGH",
                 PREFIX + "abcd-fgh", "x" + PREFIX + "abcdefgh", ".aimaster-tmp-abcdefgh"]
        if os.name != "nt":
            names.append(PREFIX + "abcdefgh\n")  # `^…$` пропустил бы перевод строки в конце
        for name in names:
            (self.parent / name).mkdir()
        self.sweep(min_age=0)
        self.assertEqual(sorted(path.name for path in self.parent.iterdir()), sorted(names))

    def test_matching_file_is_kept(self):
        target = self.parent / (PREFIX + "abcdefgh")
        target.write_text("не папка", encoding="utf-8")
        self.sweep(min_age=0)
        self.assertTrue(target.is_file())

    def test_symlink_with_matching_name_is_not_followed(self):
        outside = self.base / "чужое"
        outside.mkdir()
        (outside / "ценное.txt").write_text("не трогать", encoding="utf-8")
        link = self.parent / (PREFIX + "abcdefgh")
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("символические ссылки недоступны")
        self.sweep(min_age=0)
        self.assertTrue(os.path.lexists(link))
        self.assertTrue((outside / "ценное.txt").is_file())

    def test_windows_reparse_point_is_skipped(self):
        """Junction на Windows lstat отдаёт как папку — отличает её только
        st_reparse_tag; подмена переносима на любую ОС."""

        self.mkdtemp()
        folder = dict(st_mode=stat.S_IFDIR | 0o755, st_mtime=0)
        # IO_REPARSE_TAG_MOUNT_POINT; в модуле stat он есть только на Windows
        junction = types.SimpleNamespace(st_reparse_tag=0xA0000003, **folder)
        for fake, removed in ((junction, False), (types.SimpleNamespace(**folder), True)):
            with self.subTest(removed=removed), \
                    mock.patch.object(type(self.parent), "lstat", return_value=fake), \
                    mock.patch.object(temp_sweep.shutil, "rmtree") as rmtree:
                self.sweep()
                self.assertEqual(rmtree.called, removed)

    def test_stat_error_on_one_entry_does_not_stop_the_others(self):
        blocked, other = make_old(self.mkdtemp()), make_old(self.mkdtemp())
        real_lstat = type(blocked).lstat

        def lstat(path, *args, **kwargs):
            if path == blocked:
                raise PermissionError(13, "Permission denied", str(path))
            return real_lstat(path, *args, **kwargs)

        with mock.patch.object(type(blocked), "lstat", autospec=True, side_effect=lstat):
            self.sweep()
        self.assertTrue(blocked.exists())
        self.assertFalse(other.exists())

    def test_missing_or_file_parent_is_a_no_op(self):
        temp_sweep.sweep_stale(self.parent / "нет такой", PREFIX)
        not_a_dir = self.parent / "файл"
        not_a_dir.write_text("x", encoding="utf-8")
        temp_sweep.sweep_stale(not_a_dir, PREFIX)

    @POSIX_PERMS
    def test_unlistable_parent_is_a_no_op(self):
        stale = make_old(self.mkdtemp())
        self.parent.chmod(0o300)  # поиск без чтения: iterdir() падает
        try:
            self.sweep()
        finally:
            self.parent.chmod(0o700)
        self.assertTrue(stale.exists())

    @POSIX_PERMS
    def test_unsearchable_parent_is_a_no_op(self):
        """Разбор 4/5, находка 2: чтение без поиска — iterdir() работает, а
        stat каждой записи нет; на Python 3.11/3.12 is_symlink()/is_dir()
        прежней уборки бросали PermissionError."""

        stale = make_old(self.mkdtemp())
        self.parent.chmod(0o600)
        try:
            self.sweep()
        finally:
            self.parent.chmod(0o700)
        self.assertTrue(stale.exists())


if __name__ == "__main__":
    unittest.main()

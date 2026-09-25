#!/usr/bin/env python3
"""home_guard.py напрямую, не через sync_workspace_skills: сравнение путей
само по себе, включая версионно-зависимые исключения от циклов симлинков."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage import home_guard  # noqa: E402


class SameDirTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()

    def test_identical_existing_dirs_match(self):
        a = self.base / "a"
        a.mkdir()
        self.assertTrue(home_guard.same_dir(a, a))

    def test_different_existing_dirs_do_not_match(self):
        a, b = self.base / "a", self.base / "b"
        a.mkdir()
        b.mkdir()
        self.assertFalse(home_guard.same_dir(a, b))

    def test_nonexistent_paths_fall_back_to_resolve_and_compare(self):
        a = self.base / "нет" / "такого"
        self.assertTrue(home_guard.same_dir(a, a))
        self.assertFalse(home_guard.same_dir(a, self.base / "другой" / "путь"))

    def test_runtime_error_from_resolve_is_treated_as_not_matching(self):
        """Разбор 3/5, находка 3: Path.resolve() на цикле символических
        ссылок бросает RuntimeError на Python 3.11/3.12 (не OSError) —
        same_dir не должен падать, только сказать «не совпало». Подмена
        вместо реального цикла: поведение самого цикла отличается между
        версиями Python (на сборке, где писался тест, os.path.samefile сам
        перехватывает цикл как OSError раньше, чем дело доходит до
        resolve() — см. batch-2-report.md, разбор 3/5)."""

        a, b = self.base / "a", self.base / "b"
        with mock.patch("os.path.samefile", side_effect=OSError("не то")), \
                mock.patch.object(Path, "resolve", side_effect=RuntimeError("Symlink loop from …")):
            self.assertFalse(home_guard.same_dir(a, b))

    def test_oserror_from_resolve_is_also_treated_as_not_matching(self):
        a, b = self.base / "a", self.base / "b"
        with mock.patch("os.path.samefile", side_effect=OSError("не то")), \
                mock.patch.object(Path, "resolve", side_effect=OSError("ELOOP")):
            self.assertFalse(home_guard.same_dir(a, b))


class WouldWriteIntoHomeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()

    def test_no_home_is_not_home(self):
        with mock.patch("pathlib.Path.home", side_effect=RuntimeError("нет HOME")):
            self.assertFalse(home_guard.would_write_into_home(self.base / "любая папка"))

    def test_workspace_itself_is_home(self):
        with mock.patch("pathlib.Path.home", return_value=self.base):
            self.assertTrue(home_guard.would_write_into_home(self.base))

    def test_unrelated_workspace_is_not_home(self):
        ws = self.base / "рабочая папка"
        ws.mkdir()
        with mock.patch("pathlib.Path.home", return_value=self.base / "домашняя"):
            self.assertFalse(home_guard.would_write_into_home(ws))


if __name__ == "__main__":
    unittest.main()

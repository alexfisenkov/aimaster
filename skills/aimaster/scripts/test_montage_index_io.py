#!/usr/bin/env python3
"""Чтение/запись index.html (и прочих текстовых файлов монтажа) на диске.

Fix round 3/5, item 2: выделен из test_montage_html_doc.py вместе с
index_io.py (module split) — заодно чинит критическую находку (`newline=`
у Path.read_text появился только в 3.13, читаем через Path.open) и добавляет
уникальное временное имя (mkstemp) плюс защиту от того, что ошибка чистки
подменит исходную."""

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

from studio.montage import MontageError  # noqa: E402
from studio.montage.index_io import read_index, write_index  # noqa: E402

CRLF_SAMPLE = '<!DOCTYPE html>\r\n<html>\r\n  <body>текст</body>\r\n</html>\r\n'


class IndexIoTests(unittest.TestCase):
    def test_write_then_read_round_trips_crlf(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "index.html"
            write_index(path, CRLF_SAMPLE)
            self.assertEqual(path.read_bytes(), CRLF_SAMPLE.encode("utf-8"))
            self.assertEqual(read_index(path), CRLF_SAMPLE)

    def test_read_missing_file_is_a_montage_error(self):
        with self.assertRaises(MontageError):
            read_index(Path("/nonexistent/index.html"))

    def test_write_leaves_no_temp_file_and_replaces_target(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "index.html"
            path.write_text("старое", encoding="utf-8")
            write_index(path, "новое")
            self.assertEqual(read_index(path), "новое")
            leftovers = [p for p in Path(temp).iterdir() if p != path]
            self.assertEqual(leftovers, [])

    def test_write_failure_is_a_montage_error_and_cleanup_does_not_mask_it(self):
        # Fix round 3/5, item 2: если и запись, и попытка убрать временный
        # файл после неё падают, наружу должна выйти MontageError про
        # ИСХОДНУЮ ошибку записи, а не про сбой чистки.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "index.html"
            with mock.patch("studio.montage.index_io.replace_file",
                            side_effect=OSError("исходный сбой записи")):
                with mock.patch.object(Path, "unlink", side_effect=OSError("сбой чистки")):
                    with self.assertRaises(MontageError) as caught:
                        write_index(path, "текст")
            self.assertIn("исходный сбой записи", str(caught.exception))
            self.assertNotIn("сбой чистки", str(caught.exception))

    def test_write_uses_a_unique_temp_name(self):
        # mkstemp — не голое ".name.tmp": проверяем, что реально вызывается.
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "index.html"
            import studio.montage.index_io as index_io_module
            with mock.patch.object(index_io_module.tempfile, "mkstemp",
                                   wraps=index_io_module.tempfile.mkstemp) as spy:
                write_index(path, "текст")
            spy.assert_called_once()
            self.assertEqual(spy.call_args.kwargs.get("dir"), path.parent)


if __name__ == "__main__":
    unittest.main()

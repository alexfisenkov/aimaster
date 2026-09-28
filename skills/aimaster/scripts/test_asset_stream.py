#!/usr/bin/env python3
"""Отдача зарегистрированного файла потоком: размер — по записи, sha256 —
кусками и раз на отпечаток файла; целиком файл в память не читается."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import tiny_mp4  # noqa: E402
from studio import asset_stream  # noqa: E402
from studio.asset_stream import CHUNK_BYTES, FileBody, VerifiedFiles, open_asset  # noqa: E402
from studio.assets import AssetIndex, AssetNotFound, AssetValidationError  # noqa: E402
from studio.workspace import MAX_ASSET_BYTES, MONTAGE_MAX_BYTES  # noqa: E402


class AssetStreamTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        media = root / "media"
        (media / "p" / "montage").mkdir(parents=True)
        self.data = tiny_mp4(bytes(range(256)) * 12_000)  # ~3 МБ — несколько кусков по 1 МиБ
        self.file = media / "p" / "montage" / "v001.mp4"
        self.file.write_bytes(self.data)
        self.index = AssetIndex(root, (media,), MAX_ASSET_BYTES, montage_max_bytes=MONTAGE_MAX_BYTES,
                                db_path=root / ".studio" / "assets.sqlite3")
        self.asset = self.index.register("media/p/montage/v001.mp4", "result")["asset_id"]
        self.verified = VerifiedFiles()

    def open(self):
        opened = open_asset(self.index, self.asset, self.verified)
        self.addCleanup(opened.handle.close)
        return opened

    def bump_mtime(self):
        info = self.file.stat()
        os.utime(self.file, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))

    def test_index_answers_without_reading_the_file(self):
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("файл целиком")):
            row = self.index.stored(self.asset)
            located = self.index.locate(row["relative_path"])
        self.assertEqual(set(row), {"relative_path", "mime_type", "size_bytes", "digest"})
        self.assertEqual((row["relative_path"], row["size_bytes"], located),
                         ("media/p/montage/v001.mp4", len(self.data), self.file))

    def test_registered_file_opens_with_its_type_and_size(self):
        opened = self.open()
        self.assertEqual((opened.mime_type, opened.size, opened.relative_path),
                         ("video/mp4", len(self.data), "media/p/montage/v001.mp4"))

    def test_body_gives_the_range_in_chunks(self):
        body = FileBody(self.open().handle, 5, 20)
        chunks = list(body.chunks(size=7))
        self.assertEqual(([len(chunk) for chunk in chunks], body.length), ([7, 7, 6], 20))
        self.assertEqual(b"".join(chunks), self.data[5:25])

    def test_whole_file_goes_in_chunks_of_a_mebibyte(self):
        opened = self.open()
        chunks = list(FileBody(opened.handle, 0, opened.size).chunks())
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(max(map(len, chunks)), CHUNK_BYTES)
        self.assertEqual(b"".join(chunks), self.data)

    def test_file_is_hashed_once_while_it_stays_the_same(self):
        with mock.patch.object(asset_stream, "_digest", wraps=asset_stream._digest) as digest:
            self.open()
            self.open()
        self.assertEqual(digest.call_count, 1)

    def test_same_size_other_bytes_are_refused(self):
        self.open()
        changed = bytearray(self.data)
        changed[-1] ^= 0xFF
        self.file.write_bytes(bytes(changed))
        self.bump_mtime()
        with self.assertRaises(AssetValidationError):
            open_asset(self.index, self.asset, self.verified)

    def test_identical_rewrite_is_checked_again_and_opens(self):
        self.open()
        self.file.write_bytes(self.data)
        self.bump_mtime()
        with mock.patch.object(asset_stream, "_digest", wraps=asset_stream._digest) as digest:
            self.open()
        self.assertEqual(digest.call_count, 1)

    @unittest.skipIf(os.name == "nt", "на Windows st_ctime — время создания, запись его не меняет")
    def test_rewrite_with_the_old_mtime_put_back_is_still_checked(self):
        self.open()
        before = self.file.stat()
        changed = bytearray(self.data)
        changed[-1] ^= 0xFF
        time.sleep(0.01)  # время изменения inode — позже прежнего
        self.file.write_bytes(bytes(changed))
        os.utime(self.file, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertEqual((self.file.stat().st_mtime_ns, self.file.stat().st_size),
                         (before.st_mtime_ns, before.st_size))
        with self.assertRaises(AssetValidationError):
            open_asset(self.index, self.asset, self.verified)

    def test_first_view_is_hashed_once_for_parallel_requests(self):
        real, calls, opened, errors = asset_stream._digest, [], [], []

        def slow(handle):
            calls.append(1)
            time.sleep(0.2)
            return real(handle)

        def request():
            try:
                opened.append(open_asset(self.index, self.asset, self.verified))
            except Exception as error:  # noqa: BLE001 — любой сбой потока — провал теста
                errors.append(error)

        with mock.patch.object(asset_stream, "_digest", side_effect=slow):
            threads = [threading.Thread(target=request) for _ in range(3)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        for item in opened:
            item.handle.close()
        self.assertEqual((len(calls), len(opened), errors), (1, 3, []))

    def test_shorter_file_is_refused_without_hashing(self):
        self.file.write_bytes(self.data[:-10])
        with mock.patch.object(asset_stream, "_digest") as digest:
            with self.assertRaises(AssetValidationError):
                open_asset(self.index, self.asset, self.verified)
        digest.assert_not_called()

    def test_file_is_never_read_whole(self):
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("файл целиком")):
            opened = self.open()
            self.assertEqual(b"".join(FileBody(opened.handle, 0, opened.size).chunks()), self.data)

    def test_file_that_shrinks_while_it_is_sent_breaks_the_body(self):
        opened = self.open()
        with open(self.file, "r+b") as handle:
            handle.truncate(10)
        with self.assertRaises(OSError):
            list(FileBody(opened.handle, 0, opened.size).chunks())

    def test_unknown_asset_is_not_found(self):
        with self.assertRaises(AssetNotFound):
            open_asset(self.index, "asset-нет", self.verified)

    def test_memory_of_checked_files_is_bounded(self):
        verified = VerifiedFiles(limit=2)
        for name in "abc":
            verified.remember(name, (1, 2, 3, 4, 5))
        self.assertEqual([verified.known(name, (1, 2, 3, 4, 5)) for name in "abc"], [False, True, True])
        self.assertFalse(verified.known("c", (1, 2, 3, 4, 6)))


if __name__ == "__main__":
    unittest.main()

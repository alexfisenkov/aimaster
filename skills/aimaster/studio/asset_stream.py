"""Отдача зарегистрированного файла потоком — без чтения целиком в память.

`AssetIndex.resolve` читает файл целиком и считает sha256 на каждом вызове; для
собранного ролика (до 2 ГиБ) и частых Range-запросов плеера это непосильно.
Здесь файл открывается один раз на запрос; размер сверяется с записью, а
sha256 считается кусками по 1 МиБ — только когда отпечаток файла (устройство,
inode, размер, время изменения содержимого и время изменения inode) этим
процессом ещё не сверен. Сверенный файл отдаётся с того же открытого
дескриптора: подменить его можно только записью в тот же inode. Запись меняет
mtime, но mtime можно вернуть назад (utime) — а время изменения inode
(st_ctime на POSIX) вернуть нельзя, оно меняется и от самой записи, и от
utime. На Windows st_ctime — время создания файла: там отпечаток держится на
mtime и размере. Первый просмотр ролика шлёт сразу несколько Range-запросов —
sha256 считает один из них, остальные ждут его (`VerifiedFiles.hashing`)."""

from __future__ import annotations

import hashlib
import os
import stat
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import BinaryIO, Iterator

from .assets import AssetIndex, AssetValidationError
from .keyed_locks import KeyedLocks

CHUNK_BYTES = 1024 * 1024
REMEMBER = 256


def fingerprint(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


class VerifiedFiles:
    """asset_id → отпечаток файла, чей sha256 уже совпал с записью; помнит
    `limit` последних, общий для потоков сервера."""

    def __init__(self, limit: int = REMEMBER):
        self._seen: OrderedDict[str, tuple] = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()
        self._hashing = KeyedLocks()

    def hashing(self, asset_id: str):
        """Один sha256 файла ассета за раз: остальные потоки ждут и потом
        видят его в `known` — ролик не читается целиком несколько раз подряд."""

        return self._hashing.hold(asset_id)

    def known(self, asset_id: str, mark: tuple) -> bool:
        with self._lock:
            return self._seen.get(asset_id) == mark

    def remember(self, asset_id: str, mark: tuple) -> None:
        with self._lock:
            self._seen[asset_id] = mark
            self._seen.move_to_end(asset_id)
            while len(self._seen) > self._limit:
                self._seen.popitem(last=False)


class FileBody:
    """Кусок [start, start + length) открытого файла — тело ответа сервера."""

    def __init__(self, handle: BinaryIO, start: int, length: int):
        self._handle, self.start, self.length = handle, start, length

    def chunks(self, size: int = CHUNK_BYTES) -> Iterator[bytes]:
        self._handle.seek(self.start)
        left = self.length
        while left > 0:
            chunk = self._handle.read(min(size, left))
            if not chunk:
                raise OSError("asset file shrank while it was sent")
            left -= len(chunk)
            yield chunk

    def close(self) -> None:
        self._handle.close()


@dataclass(frozen=True)
class OpenedAsset:
    handle: BinaryIO
    mime_type: str
    size: int
    relative_path: str


def _digest(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
        digest.update(chunk)
    return digest.hexdigest()


def open_asset(index: AssetIndex, asset_id: str, verified: VerifiedFiles) -> OpenedAsset:
    """Открытый файл ассета, сверенный с записью. Не тот — AssetValidationError
    (сервер отвечает так же, как при отказе `resolve`), нет записи — AssetNotFound."""

    row = index.stored(asset_id)
    path = index.locate(row["relative_path"])
    try:
        handle = open(path, "rb")
    except OSError as error:
        raise AssetValidationError("asset file cannot be read") from error
    try:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != row["size_bytes"]:
            raise AssetValidationError("registered asset has changed")
        mark = fingerprint(info)
        if not verified.known(asset_id, mark):
            with verified.hashing(asset_id):
                if not verified.known(asset_id, mark):  # пока ждали, мог сверить другой поток
                    if _digest(handle) != row["digest"]:
                        raise AssetValidationError("registered asset has changed")
                    verified.remember(asset_id, mark)
        return OpenedAsset(handle, row["mime_type"], info.st_size, row["relative_path"])
    except BaseException:
        handle.close()
        raise

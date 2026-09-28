"""Значок вкладки дашборда (`GET /favicon.ico`): браузер спрашивает его на каждой
загрузке страницы, и без него в консоли каждый раз ошибка 404. Картинка
рисуется здесь же, стандартной библиотекой: PNG 32×32 — тёмный скруглённый
квадрат цвета главной кнопки (`--v2-primary`) с белым «▶». Современные
браузеры принимают PNG и по адресу `/favicon.ico`."""

from __future__ import annotations

import struct
import zlib
from functools import lru_cache

SIZE = 32
_RADIUS = 7
_BACK = (0x11, 0x13, 0x15, 0xFF)
_MARK = (0xFF, 0xFF, 0xFF, 0xFF)
_CLEAR = (0, 0, 0, 0)


def _inside_square(x: int, y: int) -> bool:
    """Скруглённый квадрат: углы — четверти круга радиусом `_RADIUS`."""

    cx = min(max(x, _RADIUS), SIZE - 1 - _RADIUS)
    cy = min(max(y, _RADIUS), SIZE - 1 - _RADIUS)
    return (x - cx) ** 2 + (y - cy) ** 2 <= _RADIUS ** 2


def _inside_play(x: int, y: int) -> bool:
    """«▶»: треугольник с левой стороной x=12, вершиной в (22, 16), высотой 14."""

    if x < 12 or x > 22:
        return False
    half = 7 * (22 - x) / 10
    return abs(y + 0.5 - 16) <= half


def _pixel(x: int, y: int) -> tuple[int, int, int, int]:
    if not _inside_square(x, y):
        return _CLEAR
    return _MARK if _inside_play(x, y) else _BACK


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


@lru_cache(maxsize=1)
def favicon_png() -> bytes:
    rows = b"".join(b"\x00" + b"".join(bytes(_pixel(x, y)) for x in range(SIZE)) for y in range(SIZE))
    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)  # 8 бит, RGBA
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(rows, 9)) + _chunk(b"IEND", b""))

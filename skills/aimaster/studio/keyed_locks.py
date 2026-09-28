"""Одна работа за раз на ключ (проект, ассет) — без вечно растущего словаря.

Нужен там, где дорогую работу (схема монтажа — до 120 с движка, sha256
ролика — секунды чтения) могут одновременно попросить несколько потоков
сервера: первый делает, остальные ждут и берут готовое (кэш), а не делают то
же самое ещё раз. Замок словаря держится только над словарём; запись ключа
удаляется, когда его больше никто не ждёт — ключи из адреса запроса не копятся."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Hashable, Iterator


class KeyedLocks:
    def __init__(self):
        self._guard = threading.Lock()
        self._entries: dict[Hashable, list] = {}  # ключ → [замок, сколько потоков его держат или ждут]

    @contextmanager
    def hold(self, key: Hashable) -> Iterator[None]:
        with self._guard:
            entry = self._entries.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        try:
            with entry[0]:
                yield
        finally:
            with self._guard:
                entry[1] -= 1
                if entry[1] == 0 and self._entries.get(key) is entry:
                    del self._entries[key]

    def __len__(self) -> int:
        with self._guard:
            return len(self._entries)

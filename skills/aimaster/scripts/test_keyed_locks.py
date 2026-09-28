#!/usr/bin/env python3
"""Одна работа за раз на ключ; разные ключи друг друга не ждут; записи
ключей не копятся."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.keyed_locks import KeyedLocks  # noqa: E402


class KeyedLocksTests(unittest.TestCase):
    def run_two(self, locks, first, second):
        inside, peak, count = threading.Lock(), [0], [0]

        def work(key):
            with locks.hold(key):
                with inside:
                    count[0] += 1
                    peak[0] = max(peak[0], count[0])
                time.sleep(0.1)
                with inside:
                    count[0] -= 1

        threads = [threading.Thread(target=work, args=(key,)) for key in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return peak[0]

    def test_same_key_one_at_a_time(self):
        self.assertEqual(self.run_two(KeyedLocks(), "p", "p"), 1)

    def test_other_keys_do_not_wait(self):
        self.assertEqual(self.run_two(KeyedLocks(), "p", "q"), 2)

    def test_entries_do_not_pile_up(self):
        locks = KeyedLocks()
        for key in ("a", "b", "c"):
            with locks.hold(key):
                self.assertEqual(len(locks), 1)
        self.assertEqual(len(locks), 0)

    def test_failure_inside_releases_the_key(self):
        locks = KeyedLocks()
        with self.assertRaises(ValueError):
            with locks.hold("p"):
                raise ValueError("сбой")
        self.assertEqual(len(locks), 0)
        with locks.hold("p"):
            pass


if __name__ == "__main__":
    unittest.main()

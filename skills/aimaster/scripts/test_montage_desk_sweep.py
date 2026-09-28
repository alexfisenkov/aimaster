#!/usr/bin/env python3
"""Реестр столов, запущенных процессом дашборда: под замком (запросы идут
из разных потоков), уборка — завершившиеся забыть, осиротевшие остановить."""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage import MontageError, desk_children  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402


class _Child:
    def __init__(self, pid, code=None):
        self.pid, self.code, self.waited = pid, code, False

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        self.waited = True
        return self.code


class DeskSweepTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        registry = mock.patch.dict(desk_children._children, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        self.killed = []

    def project(self, name):
        paths = montage_paths(self.base / name)
        paths.root.mkdir(parents=True)
        return paths

    def kill(self, child):
        self.killed.append(child.pid)
        child.code = -15

    def test_exited_children_are_forgotten_and_reaped_without_kill(self):
        child = _Child(11, code=0)
        desk_children.remember(self.project("a"), child, "t")
        self.assertEqual(desk_children.sweep(kill=self.kill), [])
        self.assertEqual((self.killed, desk_children._children, child.waited), ([], {}, True))

    def test_live_child_of_a_vanished_montage_folder_is_stopped(self):
        paths = self.project("b")
        desk_children.remember(paths, _Child(12), "t")
        shutil.rmtree(paths.root)
        self.assertEqual(desk_children.sweep(kill=self.kill), [12])
        self.assertEqual((self.killed, desk_children._children), ([12], {}))

    def test_renamed_project_counts_as_vanished(self):
        paths = self.project("c")
        desk_children.remember(paths, _Child(13), "t")
        (self.base / "c").rename(self.base / "c-переименован")
        self.assertEqual(desk_children.sweep(kill=self.kill), [13])

    def test_live_child_with_its_folder_stays(self):
        desk_children.remember(self.project("d"), _Child(14), "t")
        self.assertEqual(desk_children.sweep(kill=self.kill), [])
        self.assertEqual(len(desk_children._children), 1)

    def test_all_live_stops_every_own_desk(self):
        desk_children.remember(self.project("e"), _Child(15), "t")
        desk_children.remember(self.project("f"), _Child(16, code=1), "t")
        self.assertEqual(desk_children.sweep(kill=self.kill, all_live=True), [15])
        self.assertEqual(desk_children._children, {})

    def test_two_sweeps_at_once_stop_a_desk_only_once(self):
        paths = self.project("h")
        desk_children.remember(paths, _Child(17), "t")
        shutil.rmtree(paths.root)
        inner = []

        def slow_kill(child):  # процесс ещё не вышел, а вторая уборка уже идёт
            self.killed.append(child.pid)
            if len(self.killed) == 1:
                inner.append(desk_children.sweep(kill=slow_kill))

        self.assertEqual(desk_children.sweep(kill=slow_kill), [17])
        self.assertEqual((self.killed, inner, desk_children._children), ([17], [[]], {}))

    def test_desk_that_did_not_stop_stays_for_the_next_sweep(self):
        paths = self.project("i")
        child = _Child(18)
        desk_children.remember(paths, child, "t")
        shutil.rmtree(paths.root)

        def refuse(_child):
            raise MontageError("не удалось остановить монтажный стол (процесс 18)")

        self.assertEqual(desk_children.sweep(kill=refuse), [])
        self.assertEqual((child.waited, len(desk_children._children)), (False, 1))
        self.assertEqual(desk_children.sweep(kill=self.kill), [18])
        self.assertEqual(desk_children._children, {})

    def test_unexpected_failure_of_kill_keeps_the_desk_too(self):
        paths = self.project("j")
        child = _Child(19)
        desk_children.remember(paths, child, "t")
        shutil.rmtree(paths.root)

        def broken(_child):
            raise RuntimeError("сбой посреди остановки")

        with self.assertRaises(RuntimeError):
            desk_children.sweep(kill=broken)
        self.assertEqual(len(desk_children._children), 1)
        self.assertEqual(desk_children.sweep(kill=self.kill), [19])

    def test_registry_survives_parallel_use(self):
        projects = [self.project(f"g{index}") for index in range(4)]
        errors = []

        def work(offset):
            try:
                for step in range(200):
                    paths = projects[(offset + step) % 4]
                    pid = 1000 + offset * 1000 + step
                    desk_children.remember(paths, _Child(pid), "t")
                    desk_children.own(paths, {"pid": pid, "process_started": "t"})
                    desk_children.sweep(kill=self.kill)
                    desk_children.forget(paths, pid)
            except Exception as error:  # noqa: BLE001 — любой сбой потока — провал теста
                errors.append(error)

        threads = [threading.Thread(target=work, args=(offset,)) for offset in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((errors, self.killed, desk_children._children), ([], [], {}))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Хранитель столов дашборда: час без опроса экрана и без правок — стол
останавливается; занятый стол ждёт следующей уборки; выход сервера
останавливает все свои столы."""

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

from studio.desk_keeper import DeskKeeper  # noqa: E402
from studio.montage import MontageError, desk_children  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class DeskKeeperTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.paths = self.project("p")
        registry = mock.patch.dict(desk_children._children, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        self.clock, self.closed = FakeClock(), []
        self.keeper = DeskKeeper(close_desk=self.closed.append, kill=self.no_kill, clock=self.clock,
                                 idle=3600, sweep_every=0.01)

    def project(self, name):
        paths = montage_paths(self.base / name)
        paths.current.mkdir(parents=True)
        paths.index.write_text("<html></html>", encoding="utf-8")
        return paths

    def no_kill(self, child):
        self.fail("живой свой процесс с папкой на месте так не останавливают")

    def test_desk_without_signs_of_life_stops_after_an_hour(self):
        self.keeper.opened("p", self.paths)
        self.clock.now += 3599
        self.assertEqual(self.keeper.sweep(), [])
        self.clock.now += 1
        self.assertEqual(self.keeper.sweep(), ["p"])
        self.assertEqual((self.closed, self.keeper.watched()), ([self.paths], []))

    def test_screen_poll_keeps_the_desk(self):
        self.keeper.opened("p", self.paths)
        self.clock.now += 3000
        self.keeper.touch("p")
        self.clock.now += 3000
        self.assertEqual(self.keeper.sweep(), [])
        self.clock.now += 600
        self.assertEqual(self.keeper.sweep(), ["p"])

    def test_edit_on_the_desk_keeps_it(self):
        self.keeper.opened("p", self.paths)
        self.clock.now += 3000
        self.paths.index.write_text("<html><body>правка</body></html>", encoding="utf-8")
        info = self.paths.index.stat()
        os.utime(self.paths.index, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
        self.assertEqual(self.keeper.sweep(), [])
        self.clock.now += 3599
        self.assertEqual(self.keeper.sweep(), [])
        self.clock.now += 1
        self.assertEqual(self.keeper.sweep(), ["p"])

    def test_touch_of_a_desk_nobody_opened_changes_nothing(self):
        self.keeper.touch("чужой")
        self.assertEqual(self.keeper.watched(), [])

    def test_sweep_skips_a_desk_touched_between_judging_it_idle_and_stopping_it(self):
        # sweep() решает «простаивает» без замка стола (os.stat вне _guard —
        # см. докстринг файла), а закрывает уже под ним, взяв его у
        # DeskKeeper.lock. Гонка: ровно в этот промежуток экран мог как раз
        # опросить стол — touch() обновит ту же запись _Watched. Патчим
        # `lock`, чтобы воспроизвести это детерминированно: тронуть запись
        # ровно в момент, когда _stop_desk идёт за замком.
        self.keeper.opened("p", self.paths)
        self.clock.now += 3600
        real_lock = self.keeper.lock

        def lock_and_touch(project_id):
            if project_id == "p":
                self.keeper.touch("p")
            return real_lock(project_id)

        with mock.patch.object(self.keeper, "lock", side_effect=lock_and_touch):
            self.assertEqual(self.keeper.sweep(), [])
        self.assertEqual(self.closed, [])
        self.assertEqual(self.keeper.watched(), ["p"])

    def test_busy_desk_waits_for_the_next_sweep(self):
        self.keeper.opened("p", self.paths)
        self.clock.now += 3600
        lock = self.keeper.lock("p")
        lock.acquire()
        try:
            self.assertEqual(self.keeper.sweep(), [])
        finally:
            lock.release()
        self.assertEqual(self.closed, [])
        self.assertEqual(self.keeper.sweep(), ["p"])

    def test_refused_close_does_not_stop_the_sweep(self):
        def refuse(paths):
            raise MontageError("не удалось остановить монтажный стол")
        keeper = DeskKeeper(close_desk=refuse, kill=self.no_kill, clock=self.clock, idle=10)
        keeper.opened("p", self.paths)
        keeper.opened("q", self.project("q"))
        self.clock.now += 10
        self.assertEqual(sorted(keeper.sweep()), ["p", "q"])
        self.assertEqual(keeper.watched(), [])

    def test_unexpected_close_failure_does_not_stop_the_sweep_either(self):
        def broken(paths):
            raise OSError("диск отвалился")
        keeper = DeskKeeper(close_desk=broken, kill=self.no_kill, clock=self.clock, idle=10)
        keeper.opened("p", self.paths)
        keeper.opened("q", self.project("q"))
        self.clock.now += 10
        self.assertEqual(sorted(keeper.sweep()), ["p", "q"])

    def test_sweep_tidies_the_registry_of_own_processes(self):
        with mock.patch.object(desk_children, "sweep", return_value=[]) as sweep:
            self.keeper.sweep()
        sweep.assert_called_once_with(kill=self.no_kill)

    def test_stop_closes_every_dashboard_desk_and_ends_the_thread(self):
        self.keeper.start()
        self.assertTrue(self.keeper.running())
        self.keeper.opened("p", self.paths)
        with mock.patch.object(desk_children, "sweep", return_value=[]) as sweep:
            self.keeper.stop()
        self.assertEqual((self.closed, self.keeper.running()), ([self.paths], False))
        self.assertEqual(sweep.call_args_list[-1], mock.call(kill=self.no_kill, all_live=True))

    def test_stop_waits_for_a_desk_that_is_being_opened(self):
        lock, opening = self.keeper.lock("p"), threading.Event()

        def open_slowly():
            with lock:
                opening.set()
                time.sleep(0.3)
                self.keeper.opened("p", self.paths)

        thread = threading.Thread(target=open_slowly)
        thread.start()
        opening.wait(5)
        with mock.patch.object(desk_children, "sweep", return_value=[]):
            self.keeper.stop()
        stopped_with = list(self.closed)  # до join: выход дождался открытия, а не разминулся с ним
        thread.join()
        self.assertEqual((stopped_with, self.keeper.watched()), ([self.paths], []))

    def test_desk_opened_after_the_exit_is_closed_at_once(self):
        with mock.patch.object(desk_children, "sweep", return_value=[]):
            self.keeper.stop()
        self.keeper.opened("p", self.paths)
        self.assertEqual((self.closed, self.keeper.watched()), ([self.paths], []))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""MontageScreen: движок ищется не чаще раза в минуту, опрос не ждёт занятый
стол, схема читается одним потоком, стол дашборда — под присмотром хранителя."""

from __future__ import annotations

import shutil
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

from montage_built import BuiltMontage  # noqa: E402
from montage_testkit import FakeHyperframes, isolate_hyperframes_dir, tiny_mp4  # noqa: E402
from studio.desk_keeper import DeskKeeper  # noqa: E402
from studio.montage import MontageError, desk_children  # noqa: E402
from studio.montage_screen import EngineLookup, MontageScreen  # noqa: E402

STUDIO = "http://127.0.0.1:9/#project/current"
OPENER = "http://127.0.0.1:9/api/projects/current/preview/.hyperframes/aimaster-desk-open.html"


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeDesk:
    def __init__(self, log, answer=None, during_status=None):
        self.log, self.answer = log, answer or {"state": "closed"}
        self.during_status = during_status

    def open(self, paths):
        self.log.append("open")
        return {"state": "open", "url": STUDIO, "port": 9, "pid": 5, "started_at": "t"}

    def close(self, paths):
        self.log.append("close")
        return {"state": "closed"}

    def status(self, paths):
        self.log.append("status")
        if self.during_status is not None:
            self.during_status()
        return dict(self.answer)


class SlowTimeline(FakeHyperframes):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.timelines = 0

    def json(self, engine, args, *, cwd, timeout, ok_codes=(0,)):
        if list(args) == ["timeline", "--json"]:
            self.timelines += 1
            time.sleep(0.3)
        return super().json(engine, args, cwd=cwd, timeout=timeout, ok_codes=ok_codes)


class EngineLookupTests(unittest.TestCase):
    def test_installed_engine_is_looked_up_once_a_minute(self):
        clock, calls = FakeClock(), []
        lookup = EngineLookup(lambda: calls.append(1) or ("движок", ""), clock=clock)
        self.assertEqual(lookup(), ("движок", ""))
        clock.now += 59
        lookup()
        self.assertEqual(len(calls), 1)
        clock.now += 2
        lookup()
        self.assertEqual(len(calls), 2)

    def test_missing_engine_is_rechecked_every_fifteen_seconds(self):
        clock, calls = FakeClock(), []
        lookup = EngineLookup(lambda: calls.append(1) or (None, "не найден Node.js"), clock=clock)
        lookup()
        clock.now += 14
        lookup()
        self.assertEqual(len(calls), 1)
        clock.now += 2
        self.assertEqual(lookup(), (None, "не найден Node.js"))
        self.assertEqual(len(calls), 2)

    def test_others_keep_the_last_answer_while_one_looks_again(self):
        clock, release, started = FakeClock(), threading.Event(), threading.Event()
        answers = iter([("старый", ""), ("новый", "")])

        def locate():
            value = next(answers)
            if value[0] == "новый":
                started.set()
                release.wait(5)
            return value

        lookup = EngineLookup(locate, clock=clock)
        lookup()
        clock.now += 61
        worker = threading.Thread(target=lookup)
        worker.start()
        started.wait(5)
        began = time.monotonic()
        self.assertEqual(lookup(), ("старый", ""))  # node --version другого потока не ждём
        self.assertLess(time.monotonic() - began, 1)
        release.set()
        worker.join()
        self.assertEqual(lookup(), ("новый", ""))

    def test_failed_lookup_is_tried_again_next_time(self):
        clock, calls = FakeClock(), []

        def locate():
            calls.append(1)
            if len(calls) == 1:
                raise OSError("сбой")
            return "движок", ""

        lookup = EngineLookup(locate, clock=clock)
        with self.assertRaises(OSError):
            lookup()
        self.assertEqual((lookup(), len(calls)), (("движок", ""), 2))


class MontageScreenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name).resolve()
        isolate_hyperframes_dir(self, self.temp)
        registry = mock.patch.dict(desk_children._children, clear=True)
        registry.start()
        self.addCleanup(registry.stop)
        self.m = BuiltMontage(self.temp)
        self.m.draft_and_build()  # v001, ревизия 2
        self.log, self.revealed = [], []
        self.keeper = DeskKeeper(close_desk=lambda paths: None)

    def screen(self, **overrides):
        options = {"keeper": self.keeper, "engines": self.m.locate,
                   "desk_factory": lambda engine: FakeDesk(self.log),
                   "reveal": self.revealed.append, "reveal_ready": True, "runner": self.m.runner}
        options.update(overrides)
        return MontageScreen(self.m.workspace, **options)

    def test_status_asks_the_desk_and_says_whether_folders_can_be_shown(self):
        status = self.screen().status("p")
        self.assertEqual((status["desk"], status["reveal"], self.log), ({"state": "closed"}, True, ["status"]))

    def test_busy_desk_does_not_hold_the_status(self):
        lock = self.keeper.lock("p")
        lock.acquire()
        try:
            started = time.monotonic()
            status = self.screen().status("p")
        finally:
            lock.release()
        self.assertEqual((status["desk"], self.log), ({"state": "busy"}, []))
        self.assertLess(time.monotonic() - started, 2)

    def test_desk_is_asked_without_holding_the_project_lock(self):
        held = []
        desk = FakeDesk(self.log, during_status=lambda: held.append(self.keeper.lock("p").locked()))
        self.screen(desk_factory=lambda engine: desk).status("p")
        self.assertEqual(held, [False])

    def test_status_polls_keep_a_dashboard_desk_alive(self):
        clock, closed = FakeClock(), []
        keeper = DeskKeeper(close_desk=closed.append, clock=clock, idle=100)
        screen = self.screen(keeper=keeper)
        screen.open_desk("p")
        clock.now += 90
        screen.status("p")
        clock.now += 90
        self.assertEqual(keeper.sweep(), [])
        clock.now += 20
        self.assertEqual((keeper.sweep(), closed), (["p"], [self.m.paths]))

    def test_open_desk_without_engine_is_refused_in_words(self):
        screen = self.screen(engines=lambda: (None, "не найден Node.js"))
        with self.assertRaisesRegex(MontageError, "не установлен: не найден Node.js"):
            screen.open_desk("p")
        self.assertEqual((self.log, self.keeper.watched()), ([], []))

    def test_open_and_close_are_watched_by_the_keeper(self):
        screen = self.screen()
        self.assertEqual(screen.open_desk("p")["url"], OPENER)
        self.assertEqual(self.keeper.watched(), ["p"])
        self.assertEqual(screen.close_desk("p"), {"project_id": "p", "state": "closed"})
        self.assertEqual((self.keeper.watched(), self.log), ([], ["open", "close"]))

    def test_one_model_read_at_a_time(self):
        runner = SlowTimeline(render_bytes=tiny_mp4(b"out-1"))
        shutil.rmtree(self.m.paths.cache, ignore_errors=True)  # кэша нет — схему читает движок
        screen = self.screen(runner=runner)
        results = []
        threads = [threading.Thread(target=lambda: results.append(screen.model("p"))) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((runner.timelines, len(results)), (1, 2))
        self.assertEqual(results[0]["model_hash"], results[1]["model_hash"])

    def test_restore_and_reveal(self):
        screen = self.screen()
        self.assertEqual(screen.restore("p", "v001", 2)["current_version"], "v001")
        self.assertEqual(screen.reveal("p"), {"project_id": "p", "shown": "рабочая папка/media/p/montage/v001.mp4"})
        self.assertEqual(self.revealed, [self.m.seed.media / "p" / "montage" / "v001.mp4"])

    def test_reveal_holds_no_project_lock(self):
        held = []
        screen = self.screen(reveal=lambda target: held.append(self.keeper.lock("p").locked()))
        screen.reveal("p")
        self.assertEqual(held, [False])

    def test_reveal_needs_a_way_to_open_folders(self):
        with self.assertRaisesRegex(MontageError, "нечем открыть папку"):
            self.screen(reveal_ready=False).reveal("p")
        self.assertEqual(self.revealed, [])


if __name__ == "__main__":
    unittest.main()

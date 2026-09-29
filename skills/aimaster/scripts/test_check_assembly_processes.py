#!/usr/bin/env python3
"""Проверка экрана «Сборка»: учёт процессов (не тронуть того, кого прогон не
запускал), ответ узла браузерных фаз по строке на фазу, выход дашборда со
столом (обязателен на всех системах) и порядок уборки в конце прогона."""

from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS.parent), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from assembly_check import stop  # noqa: E402
from assembly_check.browser import answers  # noqa: E402
from assembly_check.processes import Processes  # noqa: E402
from assembly_check.report import Report  # noqa: E402


class FakeOs:
    """Номер → время запуска; кто «жив», кого убили, кому послали сигнал."""

    def __init__(self, stamps, children=None, leaders=None, deaf=()):
        self.stamps, self.tree = dict(stamps), children or {}
        self.leaders = set(stamps) if leaders is None else set(leaders)
        self.deaf = set(deaf)  # не слышат SIGTERM
        self.killed, self.signalled = [], []

    def started(self, pid):
        return self.stamps.get(pid)

    def alive(self, pid):
        return pid in self.stamps

    def kill(self, handle):  # kill_tree: POSIX достаёт только лидеров группы
        self.killed.append(handle.pid)
        if handle.pid in self.leaders:
            self.stamps.pop(handle.pid, None)

    def send(self, pid, sig):
        self.signalled.append((pid, sig.name))
        if not (sig.name == "SIGTERM" and pid in self.deaf):
            self.stamps.pop(pid, None)

    def children(self, pid):
        found = []
        for child in self.tree.get(pid, []):
            found += [child] + self.children(child)
        return found

    def ledger(self, windows=False):
        return Processes(started=self.started, alive=self.alive, kill=self.kill, children=self.children,
                         send=self.send, windows=windows, sleep=lambda seconds: None)


class ProcessesTests(unittest.TestCase):
    def test_left_and_stop_only_touch_the_same_process(self):
        fake = FakeOs({10: "t10", 20: "t20"})
        ledger = fake.ledger()
        ledger.add(10, "дашборд")
        ledger.add(20, "стол")
        ledger.add(30, "уже вышел")  # время запуска не прочиталось — не записан
        self.assertEqual(sorted(ledger.known), [10, 20])
        fake.stamps[20] = "чужой"  # номер 20 достался чужому процессу
        self.assertEqual(ledger.left(), ["дашборд (pid 10)"])
        self.assertEqual(ledger.stop_left(), (["дашборд (pid 10)"], []))
        self.assertEqual((fake.killed, fake.signalled), ([10], []))

    def test_reused_pid_with_children_records_and_kills_nothing(self):
        fake = FakeOs({10: "браузер"})
        ledger = fake.ledger()
        ledger.add(10, "браузер фаз", with_children=True)
        fake.stamps = {10: "чужой", 11: "ребёнок чужого"}  # браузер ушёл, номер 10 — у чужого
        fake.tree = {10: [11]}
        ledger.add(10, "браузер фаз", with_children=True)  # тот же номер из файла номеров
        self.assertEqual(ledger.known, {10: ("браузер фаз", "браузер")})
        self.assertEqual((ledger.left(), ledger.stop_left()), ([], ([], [])))
        self.assertEqual((fake.killed, fake.signalled), ([], []))

    def test_desk_is_recorded_only_with_the_start_time_from_its_record(self):
        fake = FakeOs({7: "запуск стола"}, children={7: [8]})
        fake.stamps[8] = "ребёнок"
        ledger = fake.ledger()
        ledger.add(7, "стол", with_children=True, expected="другое время")
        self.assertEqual(ledger.known, {})
        ledger.add(7, "стол", with_children=True, expected="запуск стола")
        self.assertEqual(sorted(ledger.known), [7, 8])

    def test_children_are_recorded_while_the_parent_is_the_same(self):
        fake = FakeOs({1: "a", 2: "b", 3: "c"}, children={1: [2], 2: [3]})
        ledger = fake.ledger()
        ledger.add(1, "браузер", with_children=True)
        self.assertEqual(sorted(ledger.known), [1, 2, 3])
        self.assertEqual(ledger.known[3][0], "браузер → потомок")

    @unittest.skipIf(sys.platform == "win32", "прямые сигналы — только macOS и Linux")
    def test_non_leader_left_alone_by_kill_tree_gets_a_direct_signal(self):
        fake = FakeOs({5: "лидер", 6: "сирота", 7: "глухой"}, leaders={5}, deaf={7})
        ledger = fake.ledger()
        for pid, label in ((5, "узел"), (6, "рендерер"), (7, "упрямый")):
            ledger.add(pid, label)
        stopping, still = ledger.stop_left()
        self.assertEqual((len(stopping), still), (3, []))
        self.assertEqual(fake.killed, [5, 6, 7])
        # 6 ушёл от SIGTERM — SIGKILL ему уже не шлют; 7 не услышал — получил SIGKILL
        self.assertEqual(fake.signalled, [(6, "SIGTERM"), (7, "SIGTERM"), (7, "SIGKILL")])

    def test_windows_relies_on_taskkill_and_reports_the_survivor(self):
        fake = FakeOs({6: "упрямый"}, leaders=set())
        ledger = fake.ledger(windows=True)
        ledger.add(6, "стол")
        self.assertEqual(ledger.stop_left(), (["стол (pid 6)"], ["стол (pid 6)"]))
        self.assertEqual(fake.signalled, [])

    def test_wait_gone_gives_dying_processes_a_moment(self):
        fake = FakeOs({9: "уходит"})
        ledger = fake.ledger()
        ledger.add(9, "стол")
        ledger.sleep = lambda seconds: fake.stamps.pop(9, None)
        self.assertEqual(ledger.wait_gone(1.0), [])


class NodeAnswerTests(unittest.TestCase):
    def test_a_line_per_phase_and_a_missing_phase_is_a_failure(self):
        out = ('шум\n{"phase": "desktop", "checks": [{"id": "desktop.a", "ok": true}], "shots": ["1.png"],'
               ' "data": {"x": 1}}\n{"phase": "чужая", "checks": []}\n')
        result = answers(out, ["desktop", "desk"], 1, "Error: браузер упал")
        self.assertEqual([check["id"] for check in result["checks"]], ["desktop.a", "desk.no_result"])
        self.assertIn("браузер упал", result["checks"][1]["detail"])
        self.assertEqual((result["shots"], result["data"]), (["1.png"], {"desktop": {"x": 1}}))

    def test_optional_check_from_the_node_stays_optional(self):
        out = '{"phase": "phone", "checks": [{"id": "phone.shot.full", "ok": false, "required": false}]}\n'
        report = Report()
        report.add("phone.no_hscroll", True)
        report.merge(answers(out, ["phone"], 0, ""))
        self.assertTrue(report.ok)


def fake_run(events, *, desk=None, port_closes=True, keep=False, left=()):
    board = SimpleNamespace(name="exit", running=lambda: True,
                            stop=lambda: events.append("board.stop") or 0)
    processes = mock.Mock(known={})
    processes.add.side_effect = lambda pid, label, **kw: events.append(f"add {pid}")
    processes.wait_gone.side_effect = lambda timeout: events.append("wait_gone") or list(left)
    processes.stop_left.side_effect = lambda: events.append("stop_left") or (list(left), [])
    temp = Path(tempfile.mkdtemp(prefix="aimaster-screencheck-test-"))
    run = SimpleNamespace(report=Report(), processes=processes, dashboards=[board], workspace=temp / "ws",
                          root=temp, work=temp / "журналы", shots=temp / "снимки", env={},
                          args=SimpleNamespace(shots=None, keep=keep))
    return run, board


class FinishTests(unittest.TestCase):
    def test_desk_is_registered_before_dashboards_stop_and_leftovers_fail(self):
        events = []
        run, _board = fake_run(events, left=["стол (pid 7)"])
        desk = {"pid": 7, "port": 9, "process_started": "t"}
        with mock.patch.object(stop, "read_desk", return_value=desk):
            stop.finish(run)
        self.assertEqual(events, ["add 7", "board.stop", "wait_gone", "stop_left"])
        check = {c.id: c for c in run.report.checks}
        self.assertFalse(check["processes.none_left"].ok)
        self.assertIn("пришлось остановить: стол (pid 7)", check["processes.none_left"].detail)
        self.assertTrue(check["run.temp_removed"].ok)
        self.assertFalse(run.root.exists())

    def test_temp_folder_that_stays_is_a_failure(self):
        run, _board = fake_run([])
        with mock.patch.object(stop, "read_desk", return_value=None), \
                mock.patch.object(stop, "remove_tree", return_value=False):
            stop.finish(run)
        check = {c.id: c for c in run.report.checks}["run.temp_removed"]
        self.assertEqual((check.ok, check.required), (False, True))
        stop.shutil.rmtree(run.root, ignore_errors=True)


class DeskGoneTests(unittest.TestCase):
    def test_required_on_every_system_and_cleanup_is_only_informational(self):
        run = SimpleNamespace(report=Report(), env={}, workspace=Path("ws"))
        with mock.patch.object(stop, "port_refused", side_effect=[False, True]), \
                mock.patch.object(stop, "cli", return_value={"state": "closed"}) as close:
            stop.desk_gone(run, 9)
        checks = {c.id: c for c in run.report.checks}
        gone, cleanup = checks["exit.desk_stopped_with_dashboard"], checks["exit.desk_closed_by_agent"]
        self.assertEqual((gone.ok, gone.required), (False, True))
        self.assertEqual((cleanup.ok, cleanup.required), (True, False))
        self.assertEqual(close.call_args.args[1:3], ("montage", "close"))
        self.assertFalse(run.report.ok)
        # Windows больше не исключение: стол дашборда уходит с ним (задание Windows)
        source = inspect.getsource(stop.desk_gone)
        self.assertNotIn("os.name", source)
        self.assertNotIn("required=not", source)

    def test_desk_gone_with_the_dashboard_passes_without_cleanup(self):
        with mock.patch.object(stop, "port_refused", return_value=True), \
                mock.patch.object(stop, "cli") as close:
            run = SimpleNamespace(report=Report(), env={}, workspace=Path("ws"))
            stop.desk_gone(run, 9)
        close.assert_not_called()
        self.assertEqual([(c.id, c.ok) for c in run.report.checks], [("exit.desk_stopped_with_dashboard", True)])


if __name__ == "__main__":
    unittest.main()

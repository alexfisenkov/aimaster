#!/usr/bin/env python3
"""Столы дашборда умирают вместе с ним и на Windows (studio/montage/desk_job.py):
стол, запущенный дашбордом, сразу после запуска входит в задание Windows с
KILL_ON_JOB_CLOSE; стол команды агента (`montage open`) — нет. На Windows —
настоящий проход: процесс «как дашборд» открывает стол через MontageScreen,
его убивают TerminateProcess — стол и его ребёнок уходят следом."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_montage_desk import FAKE_PREVIEW, _Draft  # noqa: E402
from montage_built import BuiltMontage  # noqa: E402
from montage_testkit import fake_engine, isolate_hyperframes_dir  # noqa: E402
from studio.montage import service, win_processes  # noqa: E402
from studio.montage.desk import StudioDesk  # noqa: E402
from studio.montage.desk_job import DeskJob, dashboard_desk_factory  # noqa: E402
from studio.montage.proc import PidHandle, process_alive  # noqa: E402
from studio.montage.proc_tree import kill_tree  # noqa: E402
from studio.server import serve  # noqa: E402


class FakeApi:
    def __init__(self, fail_create=False, fail_assign=False):
        self.jobs, self.assigned = 0, []
        self.fail_create, self.fail_assign = fail_create, fail_assign

    def kill_on_close_job(self):
        if self.fail_create:
            raise OSError("политика запрещает задания")
        self.jobs += 1
        return f"job-{self.jobs}"

    def assign(self, job, pid):
        if self.fail_assign:
            raise OSError("нет доступа")
        self.assigned.append((job, pid))


class DeskJobTests(unittest.TestCase):
    def test_off_windows_nothing_is_touched(self):
        api = FakeApi()
        self.assertFalse(DeskJob(windows=False, api=api).adopt(mock.Mock(pid=7)))
        self.assertEqual((api.jobs, api.assigned), (0, []))

    def test_one_job_per_dashboard_for_every_desk(self):
        api = FakeApi()
        job = DeskJob(windows=True, api=api, warn=self.fail)
        self.assertTrue(job.adopt(mock.Mock(pid=7)))
        self.assertTrue(job.adopt(mock.Mock(pid=8)))
        self.assertEqual((api.jobs, api.assigned), (1, [("job-1", 7), ("job-1", 8)]))

    def test_failure_is_not_fatal_is_retried_and_is_said_once_per_desk(self):
        api, said = FakeApi(fail_create=True), []
        job = DeskJob(windows=True, api=api, warn=said.append)
        self.assertFalse(job.adopt(mock.Mock(pid=7)))
        api.fail_create = False
        self.assertTrue(job.adopt(mock.Mock(pid=8)))
        api.fail_assign = True
        self.assertFalse(job.adopt(mock.Mock(pid=9)))
        self.assertEqual(api.assigned, [("job-1", 8)])
        self.assertEqual(len(said), 2)
        self.assertIn("монтажный стол (процесс 7) открыт без задания Windows (политика запрещает задания)",
                      said[0])
        self.assertIn("montage close", said[1])


class LaunchWiringTests(_Draft):
    def popen_ready(self, argv, **kwargs):
        port = int(argv[argv.index("--port") + 1])
        kwargs["stdout"].write((json.dumps({"ok": True, "result": {
            "port": port, "ready": True, "host": "127.0.0.1",
            "studioUrl": f"http://127.0.0.1:{port}/#project/current"}}) + "\n").encode())
        self.order.append("popen")
        return mock.Mock(pid=4242, poll=mock.Mock(return_value=None))

    def desk(self, **kwargs):
        self.order = []
        return StudioDesk(fake_engine(self.base / "engine"), popen=self.popen_ready,
                          sleep=lambda seconds: None, alive=lambda pid: True,
                          config=lambda port: None, kill=lambda pid: None,
                          started=lambda pid: self.order.append("started") or "запуск", **kwargs)

    def test_dashboard_desk_joins_the_job_right_after_launch(self):
        joined = []
        studio = self.desk(adopt=lambda process: self.order.append("adopt") or joined.append(process.pid))
        self.assertEqual(studio.open(self.paths)["state"], "open")
        self.assertEqual((joined, self.order[:3]), ([4242], ["popen", "adopt", "started"]))

    def test_desk_opens_even_if_the_job_refused(self):
        self.assertEqual(self.desk(adopt=lambda process: False).open(self.paths)["state"], "open")

    def test_factory_of_the_dashboard_adopts_and_the_cli_does_not(self):
        job = DeskJob(windows=False)
        self.assertEqual(dashboard_desk_factory(job)(None).adopt, job.adopt)
        self.assertIsNone(StudioDesk(None).adopt)

    def test_server_gives_its_screen_the_dashboard_factory(self):
        workspace = self.base / "рабочая"
        (workspace / "projects").mkdir(parents=True)
        running = serve(workspace)
        try:
            desk = running.application.montage.desk_factory(None)
            self.assertIsNotNone(desk.adopt)
            self.assertEqual(desk.adopt.__func__, DeskJob.adopt)
        finally:
            running.close()


class CliDeskTests(unittest.TestCase):
    def test_montage_open_from_chat_makes_a_desk_without_the_job(self):
        with tempfile.TemporaryDirectory() as temp:
            isolate_hyperframes_dir(self, temp)
            built = BuiltMontage(Path(temp))
            built.draft_and_build()
            with mock.patch.object(service, "StudioDesk") as cli_desk:
                cli_desk.return_value.open.return_value = {"state": "open"}
                service.open_desk(built.workspace, "p", engine=built.engine)
            cli_desk.assert_called_once_with(built.engine)  # без adopt: CLI выходит, стол остаётся


class WinApiShapeTests(unittest.TestCase):
    def test_job_asks_to_kill_on_close_and_process_handle_is_closed(self):
        seen = {}
        lib = mock.Mock()
        lib.CreateJobObjectW.return_value = 11
        lib.SetInformationJobObject.side_effect = lambda job, klass, ref, size: seen.update(
            job=job, klass=klass, flags=ref._obj.BasicLimitInformation.LimitFlags) or True
        lib.OpenProcess.return_value = 22
        lib.AssignProcessToJobObject.return_value = True
        job = win_processes.kill_on_close_job(lib)
        win_processes.assign(job, 4242, lib)
        self.assertEqual((job, seen["klass"], seen["flags"]), (11, 9, 0x2000))
        lib.OpenProcess.assert_called_once_with(0x0100 | 0x0001, False, 4242)
        lib.AssignProcessToJobObject.assert_called_once_with(11, 22)
        lib.CloseHandle.assert_called_once_with(22)

    def test_snapshot_pairs_and_the_snapshot_is_closed(self):
        entries = iter([(10, 1), (20, 10)])
        lib = mock.Mock()
        lib.CreateToolhelp32Snapshot.return_value = 5

        def fill(snapshot, ref):
            try:
                ref._obj.th32ProcessID, ref._obj.th32ParentProcessID = next(entries)
            except StopIteration:
                return False
            return True
        lib.Process32FirstW.side_effect = fill
        lib.Process32NextW.side_effect = fill
        self.assertEqual(win_processes.process_pairs(lib), [(10, 1), (20, 10)])
        lib.CloseHandle.assert_called_once_with(5)


GRANDCHILD = r'''
import os, subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
with open(os.environ["AIMASTER_TEST_GRANDCHILD"], "w", encoding="ascii") as out:
    out.write(str(child.pid))
'''

PARENT = r'''
import json, sys, time
from pathlib import Path
sys.path[:0] = [sys.argv[3], sys.argv[4]]
from montage_built import BuiltMontage
from studio.desk_keeper import DeskKeeper
from studio.montage.desk import StudioDesk
from studio.montage.desk_job import dashboard_desk_factory
from studio.montage.engine import Engine
from studio.montage_screen import MontageScreen
base, script = Path(sys.argv[1]), Path(sys.argv[2])
built = BuiltMontage(base)
built.draft_and_build()
engine = Engine(node=sys.executable, script=script, prefix=base / "engine", version="0.8.75", browser=None)
keeper = DeskKeeper(close_desk=lambda paths: StudioDesk(None).close(paths))
factory = StudioDesk if sys.argv[5] == "без задания" else dashboard_desk_factory()
screen = MontageScreen(built.workspace, keeper=keeper, engines=lambda: (engine, ""), desk_factory=factory)
print(json.dumps({"state": screen.open_desk("p")["state"],
                  "desk": str(built.paths.desk_file)}), flush=True)
time.sleep(600)
'''


@unittest.skipUnless(os.name == "nt", "задание Windows (Job Object) — только на Windows")
class DashboardKilledTests(unittest.TestCase):
    """Процесс «как дашборд» открывает стол через MontageScreen и убивается
    TerminateProcess. Со столами дашборда (задание) стол и его ребёнок уходят;
    контроль — тот же стол без задания переживает родителя: убивает именно задание."""

    def kill_parent(self, mode: str) -> tuple[list[int], list[int]]:
        """Номера стола и его ребёнка; живые через 10 с после смерти родителя."""

        temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve() / "папка дашборда"
        base.mkdir()
        script = base / "fake_preview.py"
        script.write_text(GRANDCHILD + FAKE_PREVIEW, encoding="utf-8")
        (base / "parent.py").write_text(PARENT, encoding="utf-8")
        env = {**os.environ, "AIMASTER_TEST_GRANDCHILD": str(base / "внук.pid"),
               "AIMASTER_HYPERFRAMES_DIR": str(base / "нет-движка")}
        parent = subprocess.Popen([sys.executable, str(base / "parent.py"), str(base), str(script),
                                   str(_SKILL_ROOT), str(_SCRIPTS), mode], env=env, stdout=subprocess.PIPE,
                                  stdin=subprocess.DEVNULL)
        pids: list[int] = []
        self.addCleanup(lambda: [kill_tree(PidHandle(pid)) for pid in pids if process_alive(pid)])
        try:
            line = json.loads(parent.stdout.readline() or b"{}")
            self.assertEqual(line.get("state"), "open")
            pids += [json.loads(Path(line["desk"]).read_text(encoding="utf-8"))["pid"],
                     int((base / "внук.pid").read_text(encoding="ascii"))]
            self.assertTrue(all(process_alive(pid) for pid in pids))
            parent.kill()  # TerminateProcess: ни finally, ни хранителя столов
            parent.wait(timeout=30)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and any(process_alive(pid) for pid in pids):
                time.sleep(0.2)
            return pids, [pid for pid in pids if process_alive(pid)]
        finally:
            if parent.poll() is None:
                parent.kill()
            parent.stdout.close()

    def test_desk_of_a_killed_dashboard_goes_with_it(self):
        _pids, alive = self.kill_parent("с заданием")
        self.assertEqual(alive, [])

    def test_control_desk_without_the_job_outlives_the_killed_parent(self):
        pids, alive = self.kill_parent("без задания")
        self.assertEqual(alive, pids)  # уборка — в addCleanup


if __name__ == "__main__":
    unittest.main()

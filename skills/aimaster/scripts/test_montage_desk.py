#!/usr/bin/env python3
"""Монтажный стол: один процесс preview на проект, адрес из его JSON, остановка
только доказанно своего процесса (ответ Studio, свой Popen, время запуска)."""

from __future__ import annotations

import json
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

from montage_testkit import fake_engine  # noqa: E402
from studio.montage import MontageError, desk, proc, proc_tree  # noqa: E402
from studio.montage.desk import StudioDesk, studio_origin  # noqa: E402
from studio.montage.desk_identity import fetch_config  # noqa: E402
from studio.montage.engine import Engine  # noqa: E402
from studio.montage.locks import held_lock  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402

# Как `preview --foreground --json` 0.8.75: строка готовности и /__hyperframes_config.
FAKE_PREVIEW = r'''
import json, os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
port = int(sys.argv[sys.argv.index("--port") + 1])

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"isHyperframes": True, "pid": os.getpid(), "projectName": "current",
                           "projectDir": os.getcwd()}).encode()
        self.send_response(200 if self.path == "/__hyperframes_config" else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
print(json.dumps({"schemaVersion": 1, "operation": "start", "ok": True, "result": {
    "state": "started", "host": "127.0.0.1", "port": port, "pid": os.getpid(),
    "studioUrl": f"http://127.0.0.1:{port}/#project/current", "ready": True}}), flush=True)
server.serve_forever()
'''


class _Draft(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve() / "папка с пробелом"
        self.paths = montage_paths(self.base / "p")
        self.paths.current.mkdir(parents=True)
        self.paths.index.write_text("<html></html>", encoding="utf-8")
        self.killed = []
        children = mock.patch.dict(desk._children, clear=True)  # реестр своих Popen — у каждого теста свой
        children.start()
        self.addCleanup(children.stop)


class DeskUnitTests(_Draft):
    def popen_ready(self, argv, host="127.0.0.1", **kwargs):
        self.argv, self.cwd, self.env = argv, kwargs["cwd"], kwargs["env"]
        port = int(argv[argv.index("--port") + 1])
        line = {"ok": True, "result": {"port": port, "ready": True, "host": host, "pid": 4242,
                                       "studioUrl": f"http://127.0.0.1:{port}/#project/current"}}
        kwargs["stdout"].write((json.dumps(line) + "\n").encode())
        self.child = mock.Mock(pid=4242, poll=mock.Mock(return_value=None))
        return self.child

    def ours(self, port):
        return {"isHyperframes": True, "pid": 4242, "projectDir": str(self.paths.current)}

    def desk(self, popen=None, *, alive=True, config=None, started="запуск-1", clock=time.monotonic):
        return StudioDesk(fake_engine(self.base / "engine"), popen=popen or self.popen_ready,
                          clock=clock, sleep=lambda seconds: None, alive=lambda pid: alive,
                          config=config or self.ours, started=lambda pid: started,
                          kill=self.killed.append)

    def opened_elsewhere(self):
        """Стол открыт другим вызовом CLI: своего Popen у этого процесса нет."""

        self.desk().open(self.paths)
        desk._children.clear()

    def test_open_writes_the_record_and_reuses_it(self):
        first = self.desk().open(self.paths)
        self.assertEqual(first["state"], "open")
        self.assertTrue(first["url"].startswith("http://127.0.0.1:"))
        self.assertEqual(self.argv[2:7], ["preview", ".", "--foreground", "--json", "--no-open"])
        self.assertEqual(Path(self.cwd), self.paths.current)
        self.assertEqual(self.env["PWD"], str(self.paths.current))  # иначе Studio: #project/<чужая папка>
        self.assertEqual(self.env["HYPERFRAMES_PREVIEW_HOST"], "127.0.0.1")
        record = json.loads(self.paths.desk_file.read_text(encoding="utf-8"))
        self.assertEqual((record["pid"], record["process_started"]), (4242, "запуск-1"))
        second = self.desk(lambda *a, **k: self.fail("второй процесс не нужен")).open(self.paths)
        self.assertEqual((second["url"], second["pid"]), (first["url"], 4242))
        self.assertEqual(set(second), {"state", "url", "port", "pid", "started_at"})

    def test_answering_desk_opened_elsewhere_is_recognised_by_studio_itself(self):
        self.opened_elsewhere()
        self.assertEqual(self.desk().status(self.paths)["state"], "open")
        self.assertEqual(self.desk().close(self.paths), {"state": "closed"})
        self.assertEqual(self.killed, [4242])

    def test_dead_process_means_closed_and_forgotten(self):
        self.opened_elsewhere()
        silent = self.desk(alive=False, config=lambda port: None)
        self.assertEqual(silent.status(self.paths), {"state": "closed"})
        self.assertFalse(self.paths.desk_file.exists())

    def test_close_kills_and_forgets(self):
        self.desk().open(self.paths)
        self.assertEqual(self.desk().close(self.paths), {"state": "closed"})
        self.assertEqual(self.killed, [4242])
        self.assertFalse(self.paths.desk_file.exists())
        self.assertNotIn(4242, desk._children)

    def assert_forgotten_not_killed(self, studio):
        status = studio.status(self.paths)
        self.assertEqual(status["state"], "closed")
        self.assertIn("ничего не остановлено", status["forgotten"])
        self.assertFalse(self.paths.desk_file.exists())
        self.opened_elsewhere()
        self.killed.clear()
        self.assertIn("ничего не остановлено", studio.close(self.paths)["forgotten"])
        self.assertEqual(self.killed, [])

    def test_another_server_on_the_port_is_forgotten_not_killed(self):
        self.opened_elsewhere()
        self.assert_forgotten_not_killed(self.desk(config=lambda port: {
            "isHyperframes": True, "pid": 999, "projectDir": str(self.paths.current)}))

    def test_another_project_on_the_port_is_forgotten_not_killed(self):
        self.opened_elsewhere()
        self.assert_forgotten_not_killed(self.desk(config=lambda port: {
            "isHyperframes": True, "pid": 4242, "projectDir": str(self.base / "другой")}))

    def test_silent_process_started_at_another_time_is_forgotten_not_killed(self):
        self.opened_elsewhere()  # тот же pid достался чужому процессу
        self.assert_forgotten_not_killed(self.desk(config=lambda port: None, started="запуск-2"))

    def test_start_time_that_cannot_be_read_is_not_ours(self):
        self.opened_elsewhere()  # Windows: нет доступа к процессу — не наш
        self.assert_forgotten_not_killed(self.desk(config=lambda port: None, started=None))

    def test_silent_desk_with_the_recorded_start_time_is_ours_and_stopped(self):
        self.opened_elsewhere()
        silent = self.desk(config=lambda port: None)
        self.assertIn("не отвечает", silent.status(self.paths)["note"])
        self.assertTrue(self.paths.desk_file.exists())  # запись — чтобы open/close его остановили
        reopened = silent.open(self.paths)
        self.assertEqual((self.killed, reopened["state"]), ([4242], "open"))

    def test_desk_started_in_this_process_is_proven_by_its_popen(self):
        self.desk().open(self.paths)
        silent = self.desk(config=lambda port: None, started=None)  # время запуска не прочитать
        self.assertIn("не отвечает", silent.status(self.paths)["note"])
        self.assertEqual(silent.close(self.paths), {"state": "closed"})
        self.assertEqual(self.killed, [4242])

    def test_own_popen_that_exited_means_gone_even_if_the_pid_is_taken_again(self):
        self.desk().open(self.paths)
        self.child.poll.return_value = 0
        self.assertEqual(self.desk().close(self.paths), {"state": "closed"})
        self.assertEqual(self.killed, [])

    def test_start_timeout_kills_and_explains(self):
        ticks = iter([0, 0, 0, 100, 100, 100])
        silent = lambda argv, **kwargs: mock.Mock(pid=77, poll=mock.Mock(return_value=None))  # noqa: E731
        with self.assertRaises(MontageError) as caught:
            self.desk(silent, alive=False, clock=lambda: next(ticks)).open(self.paths)
        self.assertIn("не запустился", str(caught.exception))
        self.assertEqual(self.killed, [77])
        self.assertFalse(self.paths.desk_file.exists())
        self.assertNotIn(77, desk._children)

    def test_studio_listening_beyond_loopback_is_refused(self):
        # engine_env не пускает чужой HYPERFRAMES_PREVIEW_HOST; строка готовности — вторая проверка
        with self.assertRaises(MontageError) as caught:
            self.desk(lambda argv, **kw: self.popen_ready(argv, host="0.0.0.0", **kw)).open(self.paths)
        self.assertIn("127.0.0.1", str(caught.exception))
        self.assertEqual(self.killed, [4242])
        self.assertFalse(self.paths.desk_file.exists())

    def test_one_desk_per_project_even_when_opened_twice_at_once(self):
        ticks = iter(range(0, 1000, 3))
        busy = self.desk(clock=lambda: next(ticks))
        with held_lock(self.paths.root / ".desk.lock", busy="занято"):
            for action in (busy.open, busy.close):
                with self.assertRaises(MontageError) as caught:
                    action(self.paths)
                self.assertIn("повторите", str(caught.exception))
        self.assertEqual(self.killed, [])

    def test_broken_record_means_closed(self):
        self.paths.desk_file.write_text('{"pid": "x"}', encoding="utf-8")
        self.assertEqual(self.desk().status(self.paths), {"state": "closed"})
        self.assertEqual(self.desk().close(self.paths), {"state": "closed"})
        self.assertEqual(self.killed, [])

    def test_no_draft_no_desk(self):
        self.paths.index.unlink()
        with self.assertRaises(MontageError):
            self.desk().open(self.paths)

    def test_no_engine_is_a_clear_refusal(self):
        with self.assertRaises(MontageError) as caught:
            StudioDesk(None, alive=lambda pid: False).open(self.paths)
        self.assertIn("движок", str(caught.exception))

    def test_studio_origin_for_the_telemetry_opener(self):
        self.assertEqual(studio_origin("http://127.0.0.1:4593/#project/current"), "http://127.0.0.1:4593")
        self.assertEqual(desk.TELEMETRY_STORAGE_KEY, "hyperframes-studio:telemetryDisabled")

    def test_windows_stop_uses_taskkill_by_full_path(self):
        calls = []
        with mock.patch.object(proc_tree, "IS_WINDOWS", True), \
                mock.patch.object(proc_tree.subprocess, "run",
                                  side_effect=lambda argv, **kwargs: calls.append((argv, kwargs))):
            desk.stop_process(4242)
        argv, kwargs = calls[0]
        self.assertTrue(argv[0].lower().endswith("system32\\taskkill.exe")
                        or argv[0].lower().endswith("system32/taskkill.exe"))
        self.assertEqual(sorted(argv[1:]), sorted(["/T", "/F", "/PID", "4242"]))
        self.assertNotIn("shell", kwargs)


class _FakeKernel32:
    """Подмена kernel32 для веток Windows — на любой ОС."""

    def __init__(self, handle=7, created=(5, 1), exit_code=proc.STILL_ACTIVE):
        self.handle, self.created, self.exit_code, self.closed = handle, created, exit_code, []

    def OpenProcess(self, access, inherit, pid):  # noqa: N802 — имя функции WinAPI
        return self.handle

    def GetProcessTimes(self, handle, creation, *rest):  # noqa: N802
        creation._obj.low, creation._obj.high = self.created
        return 1

    def GetExitCodeProcess(self, handle, code):  # noqa: N802
        code._obj.value = self.exit_code
        return 1

    def CloseHandle(self, handle):  # noqa: N802
        self.closed.append(handle)


class ProcessStartTests(unittest.TestCase):
    def test_linux_stat_field_22_even_with_parentheses_in_the_name(self):
        stat = "4242 (node (a) b) S 1 " + " ".join(str(n) for n in range(5, 30))
        self.assertEqual(proc._linux_started(stat), "linux:22")
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "4242").mkdir()
            (Path(temp) / "4242" / "stat").write_text(stat, encoding="ascii")
            self.assertEqual(proc._posix_started(4242, proc_root=Path(temp)), "linux:22")

    def test_without_proc_the_start_time_comes_from_ps(self):
        def run(argv, **kwargs):
            self.assertEqual((argv[0], kwargs["env"]["LC_ALL"]), ("/bin/ps", "C"))
            return subprocess.CompletedProcess(argv, 0, "Sat Sep 26 03:41:14 2026   \n", "")
        missing = Path(tempfile.gettempdir()) / "нет-такого-proc"
        self.assertEqual(proc._posix_started(4242, run=run, proc_root=missing),
                         "ps:Sat Sep 26 03:41:14 2026")
        gone = lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, "", "")  # noqa: E731
        self.assertIsNone(proc._posix_started(4242, run=gone, proc_root=missing))

    def test_windows_creation_time_and_access_denied(self):
        kernel32 = _FakeKernel32()
        self.assertEqual(proc._windows_started(4242, kernel32), f"win:{(1 << 32) | 5}")
        self.assertEqual(kernel32.closed, [7])
        self.assertIsNone(proc._windows_started(4242, _FakeKernel32(handle=0)))  # нет доступа — не наш
        self.assertTrue(proc._windows_alive(4242, _FakeKernel32()))
        self.assertFalse(proc._windows_alive(4242, _FakeKernel32(exit_code=1)))
        self.assertFalse(proc._windows_alive(4242, _FakeKernel32(handle=0)))

    def test_real_process_start_time_is_stable_and_personal(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            first = proc.process_started(child.pid)
            self.assertIsNotNone(first)
            self.assertEqual(proc.process_started(child.pid), first)
        finally:
            child.kill()
            child.wait(timeout=30)
        self.assertIsNone(proc.process_started(-1))


class DeskRealProcessTests(_Draft):
    def test_detached_preview_is_identified_and_stopped(self):
        script = self.base / "fake_preview.py"
        script.write_text(FAKE_PREVIEW, encoding="utf-8")
        engine = Engine(node=sys.executable, script=script, prefix=self.base / "engine",
                        version="0.8.75", browser=None)
        studio = StudioDesk(engine)
        opened = studio.open(self.paths)
        try:
            self.assertEqual(fetch_config(opened["port"])["pid"], opened["pid"])
            with mock.patch.dict(desk._children, clear=True):  # как из другого вызова CLI
                self.assertEqual(StudioDesk(None).status(self.paths)["state"], "open")
                silent = StudioDesk(None, config=lambda port: None)  # молчит — по времени запуска
                self.assertIn("не отвечает", silent.status(self.paths)["note"])
        finally:
            studio.close(self.paths)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and proc.process_alive(opened["pid"]):
            time.sleep(0.1)
        self.assertFalse(proc.process_alive(opened["pid"]))
        self.assertEqual(studio.status(self.paths), {"state": "closed"})


if __name__ == "__main__":
    unittest.main()

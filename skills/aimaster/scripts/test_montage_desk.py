#!/usr/bin/env python3
"""Монтажный стол: один процесс preview на проект, адрес из его JSON, остановка с детьми."""

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

from montage_testkit import fake_engine  # noqa: E402
from studio.montage import MontageError, desk, proc, proc_tree  # noqa: E402
from studio.montage.desk import StudioDesk, port_answers, studio_origin  # noqa: E402
from studio.montage.engine import Engine  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402

FAKE_PREVIEW = r'''
import json, socket, sys
port = int(sys.argv[sys.argv.index("--port") + 1])
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", port))
server.listen(5)
print(json.dumps({"schemaVersion": 1, "operation": "start", "ok": True, "result": {
    "state": "started", "port": port, "studioUrl": f"http://127.0.0.1:{port}/#project/current",
    "ready": True}}), flush=True)
while True:
    connection, _ = server.accept()
    connection.close()
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


class DeskUnitTests(_Draft):
    def popen_ready(self, argv, url_host="127.0.0.1", **kwargs):
        self.argv, self.cwd, self.env = argv, kwargs["cwd"], kwargs["env"]
        port = int(argv[argv.index("--port") + 1])
        line = {"ok": True, "result": {"port": port, "ready": True,
                                       "studioUrl": f"http://{url_host}:{port}/#project/current"}}
        kwargs["stdout"].write((json.dumps(line) + "\n").encode())
        return mock.Mock(pid=4242, poll=mock.Mock(return_value=None))

    def desk(self, popen, alive=True, clock=time.monotonic, answers=None):
        return StudioDesk(fake_engine(self.base / "engine"), popen=popen, clock=clock,
                          sleep=lambda seconds: None, alive=lambda pid: alive,
                          answers=answers or (lambda port: alive), kill=self.killed.append)

    def test_open_writes_the_record_and_reuses_it(self):
        first = self.desk(self.popen_ready).open(self.paths)
        self.assertEqual(first["state"], "open")
        self.assertTrue(first["url"].startswith("http://127.0.0.1:"))
        self.assertEqual(self.argv[2:7], ["preview", ".", "--foreground", "--json", "--no-open"])
        self.assertEqual(Path(self.cwd), self.paths.current)
        self.assertEqual(self.env["PWD"], str(self.paths.current))  # иначе Studio: #project/<чужая папка>
        self.assertEqual(json.loads(self.paths.desk_file.read_text(encoding="utf-8"))["pid"], 4242)
        second = self.desk(lambda *a, **k: self.fail("второй процесс не нужен")).open(self.paths)
        self.assertEqual((second["url"], second["pid"]), (first["url"], 4242))
        self.assertEqual(set(second), {"state", "url", "port", "pid", "started_at"})

    def test_dead_process_means_closed_and_forgotten(self):
        self.desk(self.popen_ready).open(self.paths)
        self.assertEqual(self.desk(self.popen_ready, alive=False).status(self.paths), {"state": "closed"})
        self.assertFalse(self.paths.desk_file.exists())

    def test_close_kills_and_forgets(self):
        self.desk(self.popen_ready).open(self.paths)
        self.assertEqual(self.desk(self.popen_ready).close(self.paths), {"state": "closed"})
        self.assertEqual(self.killed, [4242])
        self.assertFalse(self.paths.desk_file.exists())

    def test_hung_desk_is_stopped_before_a_new_one_starts(self):
        self.desk(self.popen_ready).open(self.paths)
        silent = self.desk(self.popen_ready, alive=True, answers=lambda port: False)
        self.assertEqual(silent.status(self.paths), {"state": "closed"})
        self.assertTrue(self.paths.desk_file.exists())  # запись нужна, чтобы потом его остановить
        reopened = silent.open(self.paths)
        self.assertEqual((self.killed, reopened["state"]), ([4242], "open"))

    def test_start_timeout_kills_and_explains(self):
        ticks = iter([0, 0, 100, 100, 100])
        silent = lambda argv, **kwargs: mock.Mock(pid=77, poll=mock.Mock(return_value=None))  # noqa: E731
        with self.assertRaises(MontageError) as caught:
            self.desk(silent, alive=False, clock=lambda: next(ticks)).open(self.paths)
        self.assertIn("не запустился", str(caught.exception))
        self.assertEqual(self.killed, [77])
        self.assertFalse(self.paths.desk_file.exists())

    def test_studio_outside_loopback_is_refused(self):
        with self.assertRaises(MontageError) as caught:
            self.desk(lambda argv, **kw: self.popen_ready(argv, url_host="192.168.1.5", **kw)
                      ).open(self.paths)
        self.assertIn("127.0.0.1", str(caught.exception))
        self.assertEqual(self.killed, [4242])
        self.assertFalse(self.paths.desk_file.exists())

    def test_broken_record_means_closed(self):
        self.paths.desk_file.write_text('{"pid": "x"}', encoding="utf-8")
        self.assertEqual(self.desk(self.popen_ready).status(self.paths), {"state": "closed"})
        self.assertEqual(self.desk(self.popen_ready).close(self.paths), {"state": "closed"})
        self.assertEqual(self.killed, [])

    def test_no_draft_no_desk(self):
        self.paths.index.unlink()
        with self.assertRaises(MontageError):
            self.desk(self.popen_ready).open(self.paths)

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


@unittest.skipIf(os.name == "nt", "сессии процессов — только POSIX")
class OwnSessionTests(unittest.TestCase):
    def test_reused_pid_of_a_foreign_process_is_not_the_desk(self):
        own = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                               start_new_session=True)
        foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.assertTrue(proc.own_session_alive(own.pid))
            self.assertFalse(proc.own_session_alive(foreign.pid))
        finally:
            for child in (own, foreign):
                child.kill()
                child.wait(timeout=30)
        self.assertFalse(proc.process_alive(own.pid))
        self.assertFalse(proc.own_session_alive(own.pid))


class DeskRealProcessTests(_Draft):
    def test_detached_preview_is_found_and_stopped(self):
        script = self.base / "fake_preview.py"
        script.write_text(FAKE_PREVIEW, encoding="utf-8")
        engine = Engine(node=sys.executable, script=script, prefix=self.base / "engine",
                        version="0.8.75", browser=None)
        studio = StudioDesk(engine)
        opened = studio.open(self.paths)
        try:
            self.assertEqual(studio.status(self.paths)["state"], "open")
            self.assertTrue(port_answers(opened["port"]))
        finally:
            studio.close(self.paths)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and proc.process_alive(opened["pid"]):
            time.sleep(0.1)
        self.assertFalse(proc.process_alive(opened["pid"]))
        self.assertEqual(studio.status(self.paths), {"state": "closed"})


if __name__ == "__main__":
    unittest.main()

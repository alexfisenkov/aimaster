#!/usr/bin/env python3
"""Монтажный стол: один процесс preview на проект, адрес из его JSON, остановка
только доказанно своего процесса (ответ Studio, свой Popen, время запуска)."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
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

from montage_testkit import fake_engine  # noqa: E402
from studio.montage import MontageError, desk, desk_children, desk_identity, proc, proc_tree  # noqa: E402
from studio.montage.desk import StudioDesk, studio_origin  # noqa: E402
from studio.montage.desk_identity import fetch_config  # noqa: E402
from studio.montage.desk_record import read_record  # noqa: E402
from studio.montage.engine import Engine  # noqa: E402
from studio.montage.locks import held_lock  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402

# Как `preview --foreground --json` 0.8.75: строка готовности и /__hyperframes_config.
FAKE_PREVIEW = r'''
import json, os, socketserver, sys
from http.server import BaseHTTPRequestHandler
port = int(sys.argv[sys.argv.index("--port") + 1])

# Не http.server.HTTPServer: его server_bind зовёт socket.getfqdn(), а на
# раннерах macOS обратный DNS висит дольше тайм-аута запуска стола.
class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

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

server = Server(("127.0.0.1", port), Handler)
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
        children = mock.patch.dict(desk_children._children, clear=True)  # реестр своих Popen — у каждого теста свой
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
        desk_children._children.clear()

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
        self.assertEqual(desk_children._children, {})

    def test_close_stops_our_desk_even_with_a_link_planted_at_its_lock(self):
        self.desk().open(self.paths)
        elsewhere = self.base / "создал бы замок"
        lock = self.paths.root / ".desk.lock"
        lock.unlink(missing_ok=True)
        try:
            os.symlink(elsewhere, lock)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"симлинк здесь не создать: {error}")
        self.assertEqual(self.desk().close(self.paths), {"state": "closed"})
        self.assertEqual(self.killed, [4242])
        self.assertFalse(os.path.islink(lock))
        self.assertFalse(os.path.lexists(elsewhere))

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
        self.assertEqual(desk_children._children, {})  # завершившийся Popen выброшен

    def test_one_process_with_desks_of_two_projects_never_crosses_them(self):
        # дашборд плана Б: стол проекта A жив (pid 4242, «запуск-1»). У проекта B —
        # своя запись (montage_root — папка B) от прежнего стола с тем же pid и тем же
        # временем запуска (часы ps — секундные), а время запуска ОС сейчас не
        # прочитать. Popen стола A — доказательство только для A: ключ — (папка, pid).
        self.desk().open(self.paths)
        other = montage_paths(self.base / "другой проект")
        other.current.mkdir(parents=True)
        other.desk_file.write_text(json.dumps({"pid": 4242, "port": 1, "url": "http://127.0.0.1:1/",
                                               "process_started": "запуск-1",
                                               "montage_root": desk_children.root_key(other)}),
                                   encoding="utf-8")
        self.assertEqual(desk_children.own(self.paths, read_record(self.paths)), desk_children.RUNNING)
        self.assertIsNone(desk_children.own(other, read_record(other)))
        studio_b = self.desk(config=lambda port: None, started=None)
        self.assertIn("ничего не остановлено", studio_b.close(other)["forgotten"])
        self.assertEqual(self.killed, [])
        self.assertEqual(self.desk().status(self.paths)["state"], "open")  # стол A цел

    def test_own_popen_with_another_start_time_proves_nothing(self):
        self.desk().open(self.paths)
        record = json.loads(self.paths.desk_file.read_text(encoding="utf-8"))
        self.paths.desk_file.write_text(json.dumps({**record, "process_started": "чужой"}), encoding="utf-8")
        self.assert_forgotten_not_killed(self.desk(config=lambda port: None, started="чужой-2"))

    def test_status_does_not_forget_a_record_a_concurrent_open_just_wrote(self):
        self.opened_elsewhere()
        fresh = {"pid": 5151, "port": 2, "url": "http://127.0.0.1:2/", "process_started": "новый"}

        def open_elsewhere_meanwhile(port):
            self.paths.desk_file.write_text(json.dumps(fresh), encoding="utf-8")
            return None
        self.assertEqual(self.desk(alive=False, config=open_elsewhere_meanwhile).status(self.paths),
                         {"state": "closed"})
        self.assertEqual(read_record(self.paths)["pid"], 5151)

    def test_status_leaves_the_record_while_open_or_close_holds_the_lock(self):
        self.opened_elsewhere()
        with held_lock(self.paths.root / ".desk.lock", busy="занято"):
            self.desk(alive=False, config=lambda port: None).status(self.paths)
        self.assertTrue(self.paths.desk_file.exists())

    def test_project_without_montage_is_left_untouched(self):
        bare = montage_paths(self.base / "без монтажа")
        self.assertEqual(self.desk().close(bare), {"state": "closed"})
        self.assertEqual(self.desk().status(bare), {"state": "closed"})
        self.assertFalse(bare.root.exists())

    def test_open_over_a_foreign_record_says_it_forgot_it(self):
        self.opened_elsewhere()
        reopened = self.desk(config=lambda port: None, started="другой запуск").open(self.paths)
        self.assertEqual(reopened["state"], "open")
        self.assertIn("ничего не остановлено", reopened["forgotten"])
        self.assertEqual(self.killed, [])

    def test_crafted_answers_and_records_are_not_ours_and_never_a_traceback(self):
        self.opened_elsewhere()
        record = read_record(self.paths)
        weird = {"isHyperframes": True, "pid": 4242, "projectDir": "/tmp/a\x00b"}
        self.assertEqual(desk_identity.verdict(record, self.paths, config=lambda port: weird,
                                               alive=lambda pid: True, started=lambda pid: None,
                                               own=None), desk_identity.FOREIGN)
        for bad in ({"pid": 4242, "port": 70000, "url": "u"}, {"pid": 2 ** 40, "port": 1, "url": "u"},
                    {"pid": True, "port": 1, "url": "u"}):
            self.paths.desk_file.write_text(json.dumps(bad), encoding="utf-8")
            self.assertIsNone(read_record(self.paths), bad)
            self.assertEqual(self.desk().status(self.paths), {"state": "closed"})
        self.paths.desk_file.write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
        self.assertIsNone(read_record(self.paths))
        self.assertFalse(proc.process_alive(2 ** 40))
        self.assertIsNone(proc.process_started(2 ** 40))

    def test_started_that_fails_right_after_launch_stops_the_process(self):
        def broken(pid):
            raise KeyboardInterrupt  # Ctrl+C между запуском и записью
        studio = StudioDesk(fake_engine(self.base / "engine"), popen=self.popen_ready,
                            sleep=lambda seconds: None, started=broken, kill=self.killed.append)
        with self.assertRaises(KeyboardInterrupt):
            studio.open(self.paths)
        self.assertEqual(self.killed, [4242])
        self.assertEqual(desk_children._children, {})
        self.assertFalse(self.paths.desk_file.exists())

    def test_a_copied_project_folder_does_not_stop_the_original_desk(self):
        self.desk().open(self.paths)  # стол оригинала жив, запись с его временем запуска
        copy = montage_paths(self.base / "p-копия")
        shutil.copytree(self.paths.root, copy.root)
        silent = self.desk(config=lambda port: None)  # тот же pid, то же время запуска
        self.assertIn("ничего не остановлено", silent.close(copy)["forgotten"])
        self.assertEqual(self.killed, [])
        self.assertEqual(self.desk().status(self.paths)["state"], "open")

    def test_foreign_status_says_forgotten_only_when_it_forgot(self):
        self.opened_elsewhere()
        foreign = self.desk(config=lambda port: None, started="другой запуск")
        with held_lock(self.paths.root / ".desk.lock", busy="занято"):
            later = foreign.status(self.paths)["forgotten"]
        self.assertIn("будет забыта", later)
        self.assertTrue(self.paths.desk_file.exists())
        self.assertIn("запись забыта", foreign.status(self.paths)["forgotten"])
        self.assertFalse(self.paths.desk_file.exists())

    def test_foreign_status_says_a_record_rewritten_meanwhile_is_already_replaced(self):
        self.opened_elsewhere()
        fresh = {"pid": 5151, "port": 2, "url": "http://127.0.0.1:2/", "process_started": "новый"}

        def open_elsewhere_meanwhile(port):
            self.paths.desk_file.write_text(json.dumps(fresh), encoding="utf-8")
            return None
        status = self.desk(config=open_elsewhere_meanwhile, started="другой запуск").status(self.paths)
        self.assertIn("запись уже заменена новой", status["forgotten"])
        self.assertNotIn("забыта", status["forgotten"])
        self.assertEqual(read_record(self.paths)["pid"], 5151)

    def test_a_record_that_cannot_be_removed_is_reported_not_claimed_forgotten(self):
        self.opened_elsewhere()
        refuse = mock.patch.object(Path, "unlink", side_effect=PermissionError("занят"))
        foreign = self.desk(config=lambda port: None, started="другой запуск")
        with refuse:
            status = foreign.status(self.paths)["forgotten"]
            closed = foreign.close(self.paths)
        self.assertIn("забыть не удалось", status)
        self.assertIn("забыть не удалось", closed["forgotten"])
        self.assertEqual(self.killed, [])
        self.desk().close(self.paths)  # своя запись удалилась — стол закрыт, записи нет
        self.opened_elsewhere()
        with refuse:
            mine = self.desk().close(self.paths)
        self.assertEqual((mine["state"], self.killed[-1]), ("closed", 4242))
        self.assertIn("удалить не удалось", mine["note"])
        self.assertTrue(self.paths.desk_file.exists())

    def test_open_over_a_foreign_record_it_could_not_remove_says_it_replaced_it(self):
        self.opened_elsewhere()
        foreign = self.desk(config=lambda port: None, started="другой запуск")
        real_unlink = Path.unlink

        def refuse_desk_file(path, *args, **kwargs):
            if path.name == ".desk.json":
                raise PermissionError("занят")
            return real_unlink(path, *args, **kwargs)
        with mock.patch.object(Path, "unlink", refuse_desk_file):
            reopened = foreign.open(self.paths)
        self.assertEqual(reopened["state"], "open")
        self.assertIn("запись уже заменена новой", reopened["forgotten"])
        self.assertEqual(read_record(self.paths)["process_started"], "другой запуск")

    def test_start_timeout_kills_and_explains(self):
        ticks = iter([0, 0, 0, 100, 100, 100])
        silent = lambda argv, **kwargs: mock.Mock(pid=77, poll=mock.Mock(return_value=None))  # noqa: E731
        with self.assertRaises(MontageError) as caught:
            self.desk(silent, alive=False, clock=lambda: next(ticks)).open(self.paths)
        self.assertIn("не запустился", str(caught.exception))
        self.assertEqual(self.killed, [77])
        self.assertFalse(self.paths.desk_file.exists())
        self.assertEqual(desk_children._children, {})

    def test_start_failure_tail_carries_no_absolute_paths(self):
        def crashing(argv, **kwargs):
            kwargs["stdout"].write(f"Error: cannot read {self.paths.current}/index.html\n".encode())
            return mock.Mock(pid=78, poll=mock.Mock(return_value=1))
        with self.assertRaises(MontageError) as caught:
            self.desk(crashing, alive=False).open(self.paths)
        self.assertIn("montage/current/index.html", str(caught.exception).replace("\\", "/"))
        self.assertNotIn(str(self.base), str(caught.exception))

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


class _RawServer:
    """127.0.0.1: на каждое подключение отдаёт `payload` — сразу или по `chunk` байт с паузой."""

    def __init__(self, payload: bytes, *, chunk=None, delay=0.0):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.stopped = threading.Event()
        self.requests: list[bytes] = []
        threading.Thread(target=self._serve, args=(payload, chunk or len(payload), delay),
                         daemon=True).start()

    def _serve(self, payload, step, delay):
        while not self.stopped.is_set():
            try:
                connection, _ = self.sock.accept()
            except OSError:
                continue
            with connection:
                try:
                    self.requests.append(connection.recv(4096))
                    for index in range(0, len(payload), step):
                        if self.stopped.is_set():
                            break
                        connection.sendall(payload[index:index + step])
                        time.sleep(delay)
                except OSError:
                    pass

    def close(self):
        self.stopped.set()
        self.sock.close()


class FetchConfigTests(unittest.TestCase):
    def serve(self, payload, **kwargs):
        server = _RawServer(payload, **kwargs)
        self.addCleanup(server.close)
        return server.port

    def test_a_json_object_with_status_200_is_the_answer(self):
        port = self.serve(b'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{"pid": 7}')
        self.assertEqual(fetch_config(port), {"pid": 7})

    def test_other_statuses_and_shapes_are_not_answers(self):
        for payload in (b"HTTP/1.0 404 Not Found\r\n\r\n{}", b"HTTP/1.0 200 OK\r\n\r\n[1]",
                        b"HTTP/1.0 200 OK\r\n\r\n" + b"[" * 30000 + b"]" * 30000,  # RecursionError
                        b"HTTP/1.0 200 OK\r\n\r\n" + b" " * 70000, b"garbage"):
            with self.subTest(payload=payload[:40]):
                self.assertIsNone(fetch_config(self.serve(payload)))

    def test_one_deadline_for_the_whole_answer(self):
        body = b'HTTP/1.0 200 OK\r\n\r\n{"pid": 7, "pad": "' + b"x" * 200 + b'"}'
        port = self.serve(body, chunk=1, delay=0.05)  # целиком — больше 10 с
        started = time.monotonic()
        self.assertIsNone(fetch_config(port, timeout=0.5))
        self.assertLess(time.monotonic() - started, 3.0)

    def test_bad_ports_are_not_answers(self):
        for port in (70000, -1, "x", None):
            self.assertIsNone(fetch_config(port))

    def test_the_answer_is_capped_at_64_kib(self):
        def padded(total: int) -> bytes:
            head = b'HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n{"pid": 7, "pad": "'
            return head + b"x" * (total - len(head) - 2) + b'"}'
        limit = 64 * 1024
        self.assertEqual(len(padded(limit)), limit)
        self.assertEqual(fetch_config(self.serve(padded(limit)))["pid"], 7)  # ровно предел — ответ
        for total in (limit + 1, 4 * limit):  # верный JSON-объект, но длиннее предела
            with self.subTest(total=total):
                answer = fetch_config(self.serve(padded(total)))
                self.assertTrue(answer is None, f"принят ответ в {total} байт")

    def test_host_names_the_port(self):
        server = _RawServer(b'HTTP/1.0 200 OK\r\n\r\n{"pid": 7}')
        self.addCleanup(server.close)
        self.assertEqual(fetch_config(server.port), {"pid": 7})
        self.assertIn(f"\r\nHost: 127.0.0.1:{server.port}\r\n".encode(), server.requests[0])


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
        self.assertTrue(proc._windows_alive(4242, _FakeKernel32(), last_error=lambda: 0))
        self.assertFalse(proc._windows_alive(4242, _FakeKernel32(exit_code=1), last_error=lambda: 0))
        # нет доступа — процесс есть (жив), но время запуска не прочитать: итог — FOREIGN с запиской
        self.assertTrue(proc._windows_alive(4242, _FakeKernel32(handle=0), last_error=lambda: 5))
        self.assertFalse(proc._windows_alive(4242, _FakeKernel32(handle=0), last_error=lambda: 87))

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
            with mock.patch.dict(desk_children._children, clear=True):  # как из другого вызова CLI
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

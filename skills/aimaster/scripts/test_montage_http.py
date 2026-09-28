#!/usr/bin/env python3
"""Эндпоинты экрана «Сборка»: запись только с Origin и CSRF дашборда, отказы
монтажа — текстом, «Сделать текущей» — от имени человека, выход сервера
останавливает столы дашборда."""

from __future__ import annotations

import json
import os
import select
import signal
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_built import BuiltMontage  # noqa: E402
from montage_testkit import isolate_hyperframes_dir  # noqa: E402
from studio.desk_keeper import DeskKeeper  # noqa: E402
from studio.montage import desk_children  # noqa: E402
from studio.montage.engine import PREFIX_ENV  # noqa: E402
from studio.montage_screen import MontageScreen  # noqa: E402
from studio.server import serve  # noqa: E402

STUDIO = "http://127.0.0.1:9/#project/current"
OPENER = "http://127.0.0.1:9/api/projects/current/preview/.hyperframes/aimaster-desk-open.html"
RESTORE = "/api/projects/p/montage/restore"


def _readline_with_timeout(stream, timeout):
    """`stream.readline()`, но не дольше `timeout` с: без этого сорванный
    старт дочернего дашборда (занятый порт, сломанное окружение) вешал бы
    тест до общего таймаута прогона вместо понятного провала здесь.
    POSIX-only (`select` на трубе процесса) — класс ниже и так пропускает
    Windows: там SIGTERM не перехватить."""

    ready, _, _ = select.select([stream], [], [], timeout)
    if not ready:
        raise AssertionError(f"дашборд не написал строку запуска за {timeout} с")
    return stream.readline()


class FakeDesk:
    def __init__(self, log):
        self.log = log

    def open(self, paths):
        self.log.append("open")
        return {"state": "open", "url": STUDIO, "port": 9, "pid": 5, "started_at": "t"}

    def close(self, paths):
        self.log.append("close")
        return {"state": "closed"}

    def status(self, paths):
        return {"state": "closed"}


class MontageHttpTests(unittest.TestCase):
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
        self.running = serve(self.m.workspace)
        self.addCleanup(self.running.close)
        self.app = self.running.application
        self.desk_log, self.revealed = [], []
        self.keeper = DeskKeeper(close_desk=lambda paths: None)
        self.app.montage = MontageScreen(
            self.m.workspace, keeper=self.keeper, engines=self.m.locate,
            desk_factory=lambda engine: FakeDesk(self.desk_log), reveal=self.revealed.append,
            reveal_ready=True, runner=self.m.runner)

    def call(self, method, path, body=None, *, origin=True, token=True, raw=None):
        headers = [("Host", self.app.authority)]
        payload = b""
        if body is not None or raw is not None:
            payload = raw if raw is not None else json.dumps(body).encode("utf-8")
            headers.append(("Content-Type", "application/json"))
        if method == "POST" and origin is not False:
            headers.append(("Origin", self.app.origin if origin is True else origin))
        if method == "POST" and token is not False:
            headers.append(("X-CSRF-Token", self.app.csrf_token if token is True else token))
        response = self.app.handle(method, path, headers, payload)
        return response.status, json.loads(response.body.decode("utf-8"))

    def edit_state(self, change):
        path = self.m.workspace / "projects" / "p" / "state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        change(state)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def test_status_has_no_absolute_paths_and_no_install_command(self):
        status, body = self.call("GET", "/api/projects/p/montage")
        self.assertEqual(status, 200)
        self.assertNotIn(str(self.temp), json.dumps(body, ensure_ascii=False))
        self.assertEqual(set(body["engine"]), {"state", "version", "reason"})
        self.assertEqual(body["file"], {"version": "v001", "shown": "рабочая папка/media/p/montage/v001.mp4"})
        self.assertEqual((body["desk"], body["reveal"], body["current_version"]), ({"state": "closed"}, True, "v001"))

    def test_model_part(self):
        status, body = self.call("GET", "/api/projects/p/montage/model")
        self.assertEqual((status, len(body["layers"]), body["unrendered_changes"]), (200, 6, False))

    def test_writes_need_the_dashboard_origin_and_csrf(self):
        for origin, token in ((False, True), ("http://evil.test", True), (True, False), (True, "wrong-token")):
            with self.subTest(origin=origin, token=token):
                status, body = self.call("POST", RESTORE, {"version": "v001", "expected_revision": 2},
                                         origin=origin, token=token)
                self.assertEqual((status, body["error"]["code"]), (403, "forbidden"))
        for part in ("desk", "desk/close", "reveal"):
            with self.subTest(part=part):
                self.assertEqual(self.call("POST", f"/api/projects/p/montage/{part}", {}, token=False)[0], 403)
        self.assertEqual((self.m.state()["revision"], self.desk_log, self.revealed), (2, [], []))

    def test_restore_is_written_as_the_person(self):
        status, body = self.call("POST", RESTORE, {"version": "v001", "expected_revision": 2})
        self.assertEqual((status, body), (200, {"project_id": "p", "revision": 3, "current_version": "v001"}))
        last = self.m.state()["history"][-1]
        self.assertEqual((last["actor"], last["kind"]), ("you", "montage-restored"))

    def test_stale_revision_is_a_conflict(self):
        status, body = self.call("POST", RESTORE, {"version": "v001", "expected_revision": 1})
        self.assertEqual((status, body["error"]["code"], body["error"]["current_revision"]),
                         (409, "revision_conflict", 2))

    def test_montage_refusal_comes_back_as_text(self):
        status, body = self.call("POST", RESTORE, {"version": "v009", "expected_revision": 2})
        self.assertEqual((status, body["error"]["code"]), (422, "montage_refused"))
        self.assertIn("нет версии v009", body["error"]["message"])

    def test_unknown_project_is_refused_in_words_without_paths(self):
        status, body = self.call("GET", "/api/projects/nobody/montage")
        self.assertEqual((status, body["error"]["code"]), (422, "montage_refused"))
        self.assertIn("нет проекта «nobody»", body["error"]["message"])
        self.assertNotIn(str(self.temp), body["error"]["message"])

    def test_approved_assembly_refuses_in_words(self):
        self.edit_state(lambda state: state["milestones"].__setitem__("assembly", "approved"))
        status, body = self.call("POST", RESTORE, {"version": "v001", "expected_revision": 2})
        self.assertEqual((status, body["error"]["code"]), (422, "montage_refused"))
        self.assertIn("уже одобрен", body["error"]["message"])

    def test_malformed_restore_is_a_bad_request(self):
        for payload in ({"version": "1", "expected_revision": 2}, {"version": "v001", "expected_revision": True},
                        {"version": "v001"}, {"version": "v001", "expected_revision": 2, "x": 1}):
            with self.subTest(payload=payload):
                self.assertEqual(self.call("POST", RESTORE, payload)[0], 400)

    def test_desk_and_reveal_take_only_an_empty_object(self):
        for part in ("desk", "desk/close", "reveal"):
            for kwargs in ({"body": {"path": "/etc/passwd"}}, {"body": []}, {"raw": b""}, {"raw": b"{} {}"}):
                with self.subTest(part=part, kwargs=kwargs):
                    self.assertEqual(self.call("POST", f"/api/projects/p/montage/{part}", **kwargs)[0], 400)
        self.assertEqual((self.desk_log, self.revealed), ([], []))

    def test_desk_opens_through_the_opener_page_and_closes(self):
        status, body = self.call("POST", "/api/projects/p/montage/desk", {})
        self.assertEqual((status, body), (200, {"project_id": "p", "state": "open", "url": OPENER,
                                                "telemetry_off": True}))
        self.assertEqual(self.keeper.watched(), ["p"])
        status, body = self.call("POST", "/api/projects/p/montage/desk/close", {})
        self.assertEqual((status, body["state"]), (200, "closed"))
        self.assertEqual((self.keeper.watched(), self.desk_log), ([], ["open", "close"]))

    def test_reveal_shows_the_current_file(self):
        status, body = self.call("POST", "/api/projects/p/montage/reveal", {})
        self.assertEqual((status, body), (200, {"project_id": "p", "shown": "рабочая папка/media/p/montage/v001.mp4"}))
        self.assertEqual(self.revealed, [self.m.seed.media / "p" / "montage" / "v001.mp4"])

    def test_photo_project_has_no_montage_screen(self):
        self.edit_state(lambda state: state["project"].__setitem__("type", "photo"))
        status, body = self.call("GET", "/api/projects/p/montage")
        self.assertEqual((status, body["applicable"]), (200, False))

    def test_unknown_part_and_missing_screen_are_404(self):
        self.assertEqual(self.call("GET", "/api/projects/p/montage/other")[0], 404)
        self.assertEqual(self.call("GET", "/api/projects/p/montage/desk")[0], 404)
        self.assertEqual(self.call("POST", "/api/projects/p/montage/model", {})[0], 404)
        self.app.montage = None
        self.assertEqual(self.call("GET", "/api/projects/p/montage")[0], 404)

    def test_server_close_stops_the_desks_of_the_dashboard(self):
        real_stop = DeskKeeper.stop
        with mock.patch.object(DeskKeeper, "stop", autospec=True, side_effect=real_stop) as stop:
            self.running.close()
        stop.assert_called_once()


class FaviconTests(unittest.TestCase):
    """Значок вкладки: без него браузер на каждой загрузке пишет в консоль 404."""

    def test_favicon_is_a_small_png_the_page_may_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            m = BuiltMontage(Path(temp).resolve())
            running = serve(m.workspace)
            try:
                app = running.application
                response = app.handle("GET", "/favicon.ico", [("Host", app.authority)], b"")
            finally:
                running.close()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Content-Type"], "image/png")
        self.assertEqual(response.headers["Cache-Control"], "max-age=86400")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        body = response.body
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(struct.unpack(">II", body[16:24]), (32, 32))
        pixels = zlib.decompress(body[body.index(b"IDAT") + 4:body.index(b"IEND") - 8])
        row = 1 + 32 * 4
        center = pixels[16 * row + 1 + 16 * 4:16 * row + 1 + 17 * 4]
        corner = pixels[1:5]
        self.assertEqual((center, corner), (b"\xff\xff\xff\xff", b"\x00\x00\x00\x00"))
        self.assertLess(len(body), 1024)


@unittest.skipIf(os.name == "nt", "на Windows SIGTERM не перехватить: TerminateProcess")
class ServeStopsOnTermTests(unittest.TestCase):
    """Дашборд, остановленный SIGTERM (агент, launchd, `kill`), закрывается так
    же, как по Ctrl+C: `RunningServer.close()` — и столы, открытые им, тоже."""

    def test_sigterm_closes_the_dashboard_like_ctrl_c(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "рабочая папка"
            (workspace / "projects").mkdir(parents=True)
            env = {**os.environ, PREFIX_ENV: str(Path(temp) / "нет-движка")}
            proc = subprocess.Popen([sys.executable, str(_SCRIPTS / "creator_studio.py"), "serve",
                                     str(workspace)], stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, env=env)
            try:
                self.assertIn(b"base_url", _readline_with_timeout(proc.stdout, 30))
                proc.send_signal(signal.SIGTERM)
                self.assertEqual(proc.wait(timeout=30), 0)  # без обработчика было бы -15
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.stdout.close()


@unittest.skipIf(os.name == "nt", "select() на трубе не работает на Windows — только на сокетах")
class ReadlineWithTimeoutTests(unittest.TestCase):
    """`_readline_with_timeout` — то, чем выше заменена голая `readline()`."""

    def test_returns_the_line_once_it_is_written(self):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b'{"base_url": "http://127.0.0.1:9"}\n')
            with os.fdopen(read_fd, "rb") as stream:
                self.assertEqual(_readline_with_timeout(stream, 1.0), b'{"base_url": "http://127.0.0.1:9"}\n')
        finally:
            os.close(write_fd)

    def test_times_out_instead_of_hanging_forever(self):
        read_fd, write_fd = os.pipe()  # никто не пишет — голая readline() повисла бы навсегда
        try:
            with os.fdopen(read_fd, "rb") as stream:
                with self.assertRaisesRegex(AssertionError, "не написал строку запуска за 0.2 с"):
                    _readline_with_timeout(stream, 0.2)
        finally:
            os.close(write_fd)


if __name__ == "__main__":
    unittest.main()

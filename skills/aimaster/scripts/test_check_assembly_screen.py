#!/usr/bin/env python3
"""Проверка экрана «Сборка» без браузера: разбор аргументов, отчёт и коды
выхода, путь «движка нет», учёт процессов (чужой процесс с тем же номером не
трогается), своя папка движка (проходит проверки `engine.locate()`, общая —
не меняется, ссылка на её пакеты снимается без захода внутрь), разбор ответа
браузерных фаз, порт стола и разбор модулей *.mjs проверки."""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
for _path in (str(_SCRIPTS.parent), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import check_assembly_screen  # noqa: E402
from assembly_check import run as run_module  # noqa: E402
from assembly_check.browser import _answer  # noqa: E402
from assembly_check.dashboard import port_refused  # noqa: E402
from assembly_check.engine_copy import (fingerprint, is_dir_link, make_own_engine,  # noqa: E402
                                        release)
from assembly_check.processes import Processes  # noqa: E402
from assembly_check.report import FAILED, NO_ENGINE, PASSED, Report, exit_code  # noqa: E402
from studio.montage import engine  # noqa: E402
from studio.montage.prefix_layout import (gsap_problem, hyperframes_problem,  # noqa: E402
                                          recorded_browser, write_record)


class ArgumentsTests(unittest.TestCase):
    def test_defaults(self):
        args = check_assembly_screen.build_parser().parse_args([])
        self.assertEqual((args.json, args.reveal, args.shots, args.keep, args.require_engine),
                         (False, False, None, False, False))

    def test_all_flags(self):
        args = check_assembly_screen.build_parser().parse_args(
            ["--json", "--reveal", "--shots", "снимки", "--keep", "--require-engine"])
        self.assertEqual((args.json, args.reveal, args.shots, args.keep, args.require_engine),
                         (True, True, Path("снимки"), True, True))

    def test_unknown_flag_is_refused(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), \
                mock.patch("sys.stderr", io.StringIO()):
            check_assembly_screen.build_parser().parse_args(["--phone"])


class ReportTests(unittest.TestCase):
    def test_empty_report_is_not_a_pass(self):
        self.assertFalse(Report().ok)
        self.assertEqual(exit_code(Report(), require_engine=False), FAILED)

    def test_browser_answer_is_merged_as_required_checks(self):
        report = Report()
        report.add("cli.v001", True, "v001")
        report.merge({"checks": [{"id": "desktop.preview", "ok": True, "detail": "9:16"},
                                 {"id": "desktop.console", "ok": False, "detail": "ошибка"}],
                      "shots": ["a.png"]})
        self.assertEqual([check.id for check in report.checks], ["cli.v001", "desktop.preview", "desktop.console"])
        self.assertEqual(report.shots, ["a.png"])
        self.assertFalse(report.ok)
        self.assertEqual([check.id for check in report.failed()], ["desktop.console"])
        self.assertEqual(exit_code(report, require_engine=True), FAILED)

    def test_ok_only_as_literal_true(self):
        report = Report()
        report.merge({"checks": [{"id": "x", "ok": "false"}]})  # строка — не «да»
        self.assertFalse(report.ok)

    def test_optional_failure_is_shown_but_does_not_fail(self):
        report = Report()
        report.add("exit.no_processes", True)
        report.add("exit.desk_stopped_with_dashboard", False, "порт открыт", required=False)
        self.assertTrue(report.ok)
        self.assertEqual(exit_code(report, require_engine=True), PASSED)
        self.assertIn("· exit.desk_stopped_with_dashboard (не обязательно на этой системе)", report.text())
        self.assertIs(report.as_dict()["checks"][1]["required"], False)

    def test_text_and_json_shapes(self):
        report = Report()
        report.add("a", True, "да")
        report.seconds["этап"] = 2.0
        report.kept = "/tmp/папка"
        self.assertTrue(report.text().splitlines()[-2].startswith("ЭКРАН «СБОРКА» ПРОВЕРЕН"))
        data = report.as_dict()
        self.assertEqual((data["ok"], data["checks"][0]["id"], data["kept"]), (True, "a", "/tmp/папка"))
        self.assertNotIn("engine_missing", data)


class EngineMissingTests(unittest.TestCase):
    def _main(self, argv):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(run_module.engine, "locate",
                                                     return_value=(None, "не найден Node.js")), \
                mock.patch.object(run_module, "Run") as fake_run:
            code = check_assembly_screen.main(argv)
        fake_run.assert_not_called()  # без движка ни папок, ни процессов
        return code, out.getvalue()

    def test_missing_engine_is_a_skip_with_the_install_command(self):
        code, out = self._main([])
        self.assertEqual(code, NO_ENGINE)
        self.assertIn("Монтажный движок не установлен (не найден Node.js)", out)
        self.assertIn(engine.install_command(), out)

    def test_require_engine_turns_it_into_a_failure(self):
        code, out = self._main(["--require-engine", "--json"])
        self.assertEqual(code, FAILED)
        data = json.loads(out)
        self.assertEqual((data["ok"], data["checks"]), (False, []))
        self.assertIn("install.py", data["engine_missing"])

    def test_main_passes_the_report_code_through(self):
        def passing(args, report):
            report.add("всё", True)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(check_assembly_screen.main(["--json"], run=passing), PASSED)


class FakeOs:
    """Номер → время запуска; «живые» и «убитые» — как у настоящих процессов."""

    def __init__(self, stamps, children=None):
        self.stamps, self.tree, self.killed = dict(stamps), children or {}, []

    def started(self, pid):
        return self.stamps.get(pid)

    def alive(self, pid):
        return pid in self.stamps

    def kill(self, handle):
        self.killed.append(handle.pid)
        self.stamps.pop(handle.pid, None)

    def children(self, pid):
        """Все потомки, как `proc_tree._descendants`."""
        found = []
        for child in self.tree.get(pid, []):
            found += [child] + self.children(child)
        return found

    def ledger(self):
        return Processes(started=self.started, alive=self.alive, kill=self.kill, children=self.children)


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
        self.assertEqual(ledger.stop_left(), ["дашборд (pid 10)"])
        self.assertEqual(fake.killed, [10])
        self.assertEqual(ledger.left(), [])

    def test_desk_is_recorded_only_with_the_start_time_from_its_record(self):
        fake = FakeOs({7: "запуск стола"})
        ledger = fake.ledger()
        ledger.add(7, "стол", expected="другое время")
        self.assertEqual(ledger.known, {})
        ledger.add(7, "стол", expected="запуск стола")
        self.assertEqual(ledger.known, {7: ("стол", "запуск стола")})

    @unittest.skipIf(os.name == "nt", "потомков читает ps — только macOS и Linux")
    def test_children_are_recorded_while_the_parent_is_alive(self):
        fake = FakeOs({1: "a", 2: "b", 3: "c"}, children={1: [2], 2: [3]})
        ledger = fake.ledger()
        ledger.add(1, "браузер", with_children=True)
        self.assertEqual(sorted(ledger.known), [1, 2, 3])
        self.assertEqual(ledger.known[3][0], "браузер → потомок")


class OwnEngineTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="aimaster-screencheck-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.pin = engine.load_pin()
        shared = self.root / "общая папка" / "tools" / "hyperframes"
        package = shared / "node_modules" / "hyperframes"
        (package / "bin").mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"version": self.pin["version"]}), encoding="utf-8")
        (package / "bin" / "hyperframes.mjs").write_text("// движок", encoding="utf-8")
        gsap = shared / "node_modules" / "gsap"
        (gsap / "dist").mkdir(parents=True)
        (gsap / "package.json").write_text(json.dumps({"version": self.pin["gsap_version"]}), encoding="utf-8")
        for name in ("gsap", "MotionPathPlugin"):
            (gsap / "dist" / f"{name}.min.js").write_text("//", encoding="utf-8")
        browser = shared / "home" / ".cache" / "chrome" / "linux-1" / "chrome-headless-shell"
        browser.mkdir(parents=True)
        (browser / "chrome-headless-shell").write_bytes(b"\x7fELF")
        (browser / "icudtl.dat").write_bytes(b"data")
        write_record(shared, {"browser": str(browser / "chrome-headless-shell"), "version": self.pin["version"]})
        self.found = engine.Engine(node="node", script=package / "bin" / "hyperframes.mjs", prefix=shared,
                                   version=self.pin["version"], browser=str(browser / "chrome-headless-shell"))

    def test_own_prefix_passes_the_engine_checks_and_shared_stays_untouched(self):
        before = fingerprint(self.found)
        own = make_own_engine(self.found, self.root / "проверка" / "движок")
        self.assertEqual(hyperframes_problem(own.prefix, self.pin["version"]), "")
        self.assertEqual(gsap_problem(own.prefix, self.pin["gsap_version"]), "")
        self.assertEqual(recorded_browser(own.prefix, version=self.pin["version"]), own.browser)
        self.assertTrue(Path(own.browser).is_file())
        self.assertTrue((Path(own.browser).parent / "icudtl.dat").is_file())
        self.assertTrue(is_dir_link(own.prefix / "node_modules"))
        self.assertEqual(own.modules, self.found.prefix / "node_modules")
        self.assertEqual(fingerprint(self.found), before)

    def test_release_drops_the_link_without_entering_it(self):
        own = make_own_engine(self.found, self.root / "проверка" / "движок")
        release(self.root / "проверка" / "движок")
        self.assertFalse(os.path.lexists(own.prefix / "node_modules"))
        shutil.rmtree(self.root / "проверка")
        self.assertTrue((self.found.prefix / "node_modules" / "hyperframes" / "package.json").is_file())
        release(self.root / "не было")  # своей папки не завели — нечего снимать


class BrowserAnswerTests(unittest.TestCase):
    def test_last_json_line_wins(self):
        out = 'шум\n{"checks": [{"id": "a", "ok": true}], "shots": []}\n'
        self.assertEqual(_answer(out, 0, "")["checks"][0]["id"], "a")

    def test_no_answer_is_a_crash_with_stderr(self):
        answer = _answer("не JSON", 1, "Error: нет браузера")
        self.assertEqual((answer["checks"][0]["id"], answer["checks"][0]["ok"]), ("browser.crash", False))
        self.assertIn("нет браузера", answer["checks"][0]["detail"])


class PortTests(unittest.TestCase):
    def test_listening_port_is_not_refused_and_closed_is(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        try:
            self.assertFalse(port_refused(port))
        finally:
            server.close()
        self.assertTrue(port_refused(port, wait=2))


@unittest.skipIf(shutil.which("node") is None, "нет Node.js")
class ModulesParseTests(unittest.TestCase):
    def test_browser_phase_modules_parse_as_es_modules(self):
        # scripts/ целиком: вход check_assembly_screen.mjs и фазы в assembly_check/
        proc = subprocess.run(["node", "--experimental-vm-modules", "--no-warnings",
                               str(_SCRIPTS / "check_static_modules.mjs"), str(_SCRIPTS)],
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(" 0 failed", proc.stdout)


if __name__ == "__main__":
    unittest.main()

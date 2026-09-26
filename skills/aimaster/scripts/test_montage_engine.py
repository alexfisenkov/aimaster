#!/usr/bin/env python3
"""Движок HyperFrames: закреплённая версия, где стоит, готов ли (Node 22+, пакет, браузер)."""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio import platform_compat  # noqa: E402
from studio.montage import MontageError, engine  # noqa: E402


def node_says(version: str):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, (version + "\n").encode(), b"")
    return run


class _Prefix(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.prefix = self.base / "tools" / "hyperframes"
        self.env = {engine.PREFIX_ENV: str(self.prefix), "PATH": ""}

    def install_package(self, version="0.8.75"):
        package = self.prefix / "node_modules" / "hyperframes"
        (package / "bin").mkdir(parents=True)
        (package / "bin" / "hyperframes.mjs").write_text("// заглушка\n", encoding="utf-8")
        (package / "package.json").write_text(
            json.dumps({"name": "hyperframes", "version": version}), encoding="utf-8")

    def install_gsap(self, version="3.14.2", files=("gsap", "MotionPathPlugin")):
        package = self.prefix / "node_modules" / "gsap"
        (package / "dist").mkdir(parents=True, exist_ok=True)
        (package / "package.json").write_text(json.dumps({"name": "gsap", "version": version}),
                                              encoding="utf-8")
        for name in files:
            (package / "dist" / f"{name}.min.js").write_text("/* gsap */\n", encoding="utf-8")

    def install_browser(self):
        browser = self.prefix / "home" / ".cache" / "hyperframes" / "chrome" / "chrome-headless-shell"
        browser.parent.mkdir(parents=True)
        browser.write_text("", encoding="utf-8")
        engine.write_record(self.prefix, {"browser": str(browser), "version": "0.8.75"})
        return browser

    def locate(self, version="v22.3.0"):
        with mock.patch.object(engine, "find_node", return_value="/usr/local/bin/node"):
            return engine.locate(environ=self.env, run=node_says(version))


class PinTests(unittest.TestCase):
    def test_pin_is_hyperframes_0875_with_ten_core_skills(self):
        pin = engine.load_pin()
        self.assertEqual((pin["package"], pin["version"], pin["node_min_major"], pin["gsap_version"]),
                         ("hyperframes", "0.8.75", 22, "3.14.2"))
        skills = pin["skills"]
        self.assertEqual(skills["tag"], "v0.8.75")
        self.assertEqual(skills["commit"], "a95cb96a5dd3c1f7b31266a4b470590c86ad231f")
        self.assertEqual(len(skills["bundles"]), 10)
        self.assertNotIn("figma", skills["bundles"])
        self.assertEqual(skills["bundles"]["hyperframes"], {"hash": "e4788caea448bc93", "files": 26})


class PrefixTests(unittest.TestCase):
    def test_default_prefix_is_user_data_tools(self):
        with tempfile.TemporaryDirectory() as home:
            expected = platform_compat.user_data_dir(home=Path(home), environ={}) / "tools" / "hyperframes"
            self.assertEqual(engine.tools_prefix(home=Path(home), environ={}), expected)

    def test_override_must_be_absolute(self):
        # Слабая проверка "не равно относительному пути" была бы верна и для
        # любого другого абсолютного пути — здесь именно дефолтная папка.
        with tempfile.TemporaryDirectory() as home:
            expected = platform_compat.user_data_dir(home=Path(home), environ={}) / "tools" / "hyperframes"
            self.assertEqual(
                engine.tools_prefix(home=Path(home),
                                    environ={engine.PREFIX_ENV: "relative/dir"}),
                expected)
        absolute = Path(tempfile.gettempdir()).resolve() / "hf"
        self.assertEqual(engine.tools_prefix(environ={engine.PREFIX_ENV: str(absolute)}), absolute)


class LocateTests(_Prefix):
    def test_no_node(self):
        with mock.patch.object(engine, "find_node", return_value=None):
            found, reason = engine.locate(environ=self.env)
        self.assertIsNone(found)
        self.assertIn("Node.js", reason)

    def test_old_node_is_refused(self):
        found, reason = self.locate("v20.11.1")
        self.assertIsNone(found)
        self.assertIn("22", reason)

    def test_missing_package(self):
        found, reason = self.locate()
        self.assertIsNone(found)
        self.assertIn("не установлен", reason)

    def test_other_version_is_refused(self):
        self.install_package("0.8.74")
        found, reason = self.locate()
        self.assertIsNone(found)
        self.assertIn("0.8.74", reason)

    def test_browser_record_is_required(self):
        self.install_package()
        found, reason = self.locate()
        self.assertIsNone(found)
        self.assertIn("браузер", reason)

    def test_malformed_browser_record_is_missing_not_a_crash(self):
        # aimaster-engine.json мог оказаться повреждён руками или сторонним
        # процессом: "browser" не строка. locate() обязан отказать по
        # понятной причине, а не упасть с TypeError внутри Path(browser).
        self.install_package()
        engine.write_record(self.prefix, {"browser": 12345, "version": "0.8.75"})
        found, reason = self.locate()
        self.assertIsNone(found)
        self.assertIn("браузер", reason)

    def test_browser_outside_engine_home_is_not_accepted(self):
        """round 3/5, Minor 7: запись `browser` вне `<prefix>/home` (осевший
        системный браузер из записи прошлых версий установщика, ручная
        правка файла) не должна тихо сходить за «готовый движок» —
        `engine.locate()` и install_montage_browser.check_browser()/
        browser_install() зовут одну и ту же проверку (recorded_browser)."""

        self.install_package()
        outside = self.base / "не-в-home" / "chrome.exe"
        outside.parent.mkdir(parents=True)
        outside.write_text("", encoding="utf-8")
        engine.write_record(self.prefix, {"browser": str(outside), "version": "0.8.75"})
        found, reason = self.locate()
        self.assertIsNone(found)
        self.assertIn("браузер", reason)

    def test_gsap_of_the_pin_is_part_of_the_engine(self):
        # Черновик без GSAP закреплённой версии не собирается (vendor.py), значит
        # и движок без него не «установлен»: status даёт команду установки, а не
        # «installed» с отказом черновика потом.
        self.install_package()
        self.install_browser()
        for setup, wanted in ((lambda: None, "GSAP 3.14.2 для черновика не установлен"),
                              (lambda: self.install_gsap(files=("gsap",)), "MotionPathPlugin.min.js"),
                              (lambda: self.install_gsap("3.13.0"), "стоит 3.13.0")):
            setup()
            found, reason = self.locate()
            self.assertIsNone(found)
            self.assertIn(wanted, reason)
        with mock.patch.object(engine, "find_node", return_value="/usr/local/bin/node"), \
                mock.patch.object(engine, "node_major", return_value=22):
            status = engine.engine_view(*engine.locate(environ=self.env))
            with self.assertRaises(MontageError) as caught:
                engine.require_engine(environ=self.env)
        self.assertEqual(status["state"], "missing")
        self.assertIn("стоит 3.13.0", status["reason"])
        self.assertIn(engine.install_command(), str(caught.exception))

    def test_entry_script_is_part_of_the_package(self):
        self.install_package()
        self.install_browser()
        self.install_gsap()
        engine.entry_script(self.prefix).unlink()
        found, reason = self.locate()
        self.assertIsNone(found)
        self.assertEqual(reason, "HyperFrames не установлен в папке движка")
        self.assertNotIn(str(self.base), reason)

    def test_ready_engine(self):
        self.install_package()
        browser = self.install_browser()
        self.install_gsap()
        found, reason = self.locate("v24.1.0")
        self.assertEqual(reason, "")
        self.assertEqual(found.version, "0.8.75")
        self.assertEqual(found.browser, str(browser))
        self.assertEqual(found.script,
                         self.prefix / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs")

    def test_view_and_require_name_the_exact_install_command(self):
        view = engine.engine_view(*engine.locate(environ=self.env))
        self.assertEqual((view["state"], view["wanted"]), ("missing", "0.8.75"))
        self.assertEqual(view["install"], engine.install_command())
        self.assertEqual(view["install_argv"], engine.install_argv())
        with mock.patch.object(engine, "find_node", return_value=None):
            with self.assertRaises(MontageError) as caught:
                engine.require_engine(environ=self.env)
        self.assertIn(engine.install_command(), str(caught.exception))

    def test_view_of_a_ready_engine_has_no_install_command(self):
        ready = engine.Engine(node="node", script=Path("x"), prefix=self.prefix, version="0.8.75",
                              browser=None)
        view = engine.engine_view(ready, "")
        self.assertEqual((view["state"], view["version"], view["install"], view["install_argv"]),
                         ("installed", "0.8.75", None, None))

    def test_install_command_is_this_python_and_this_install_py(self):
        command = engine.install_command()
        for part in (sys.executable, str(_SCRIPTS / "install.py")):
            self.assertIn(part.replace("\\", "/") if os.name == "nt" else part, command)
        self.assertTrue(command.endswith("--install-deps"))
        with mock.patch.object(engine, "IS_WINDOWS", True):
            self.assertTrue(engine.install_command().endswith("--install-deps"))

    def test_install_argv_is_the_plain_argument_list(self):
        self.assertEqual(engine.install_argv(),
                         [sys.executable, str(_SCRIPTS / "install.py"), "--install-deps"])

    def test_package_versions(self):
        self.install_package()
        gsap = self.prefix / "node_modules" / "gsap"
        gsap.mkdir(parents=True)
        (gsap / "package.json").write_text('{"version": "3.14.2"}', encoding="utf-8")
        self.assertEqual((engine.package_version(self.prefix, "gsap"), engine.installed_version(self.prefix)),
                         ("3.14.2", "0.8.75"))
        self.assertIsNone(engine.package_version(self.prefix, "nope"))


class WindowsCommandLineTests(unittest.TestCase):
    """Строка команды на Windows: одна на Git Bash (оболочка Claude Code) и
    PowerShell (Codex). Пути с «/», кавычки — только у слова, где они нужны."""

    PYTHON = r"C:\Program Files\Python312\python.exe"
    SCRIPT = r"C:\Users\Алекс Ф\AI Мастерская\aimaster\scripts\install.py"

    def command(self, python=PYTHON, script=SCRIPT) -> str:
        with mock.patch.object(engine.sys, "executable", python), \
                mock.patch.object(engine, "INSTALL_PY", Path(script)), \
                mock.patch.object(engine, "IS_WINDOWS", True):
            return engine.install_command()

    def test_paths_with_spaces_are_double_quoted_with_forward_slashes(self):
        command = self.command()
        self.assertEqual(command, '"C:/Program Files/Python312/python.exe" '
                                  '"C:/Users/Алекс Ф/AI Мастерская/aimaster/scripts/install.py" '
                                  "--install-deps")

    def test_git_bash_reads_the_same_three_arguments(self):
        # shlex (POSIX) разбирает так же, как bash: кавычки сняты, «/» на месте.
        self.assertEqual(shlex.split(self.command()),
                         [self.PYTHON.replace("\\", "/"), self.SCRIPT.replace("\\", "/"),
                          "--install-deps"])

    def test_no_background_operator_and_no_backslashes(self):
        # «& "…"» PowerShell понимает, а bash падает на разборе строки;
        # «\» bash съел бы как экранирование. Оператор вызова для PowerShell
        # добавляет агент (references/montage.md).
        command = self.command()
        self.assertFalse(command.startswith("&"))
        self.assertNotIn("\\", command)

    def test_nothing_to_quote_stays_bare_for_both_shells(self):
        command = self.command(r"C:\Python312\python.exe", r"D:\a\aimaster\scripts\install.py")
        self.assertEqual(command, "C:/Python312/python.exe D:/a/aimaster/scripts/install.py --install-deps")

    def test_dollar_and_backtick_are_single_quoted(self):
        # В двойных кавычках «$x» и «`» подставляют и bash, и PowerShell.
        command = self.command(script=r"C:\Users\$dev\install.py")
        self.assertIn("'C:/Users/$dev/install.py'", command)
        self.assertEqual(shlex.split(command)[1], "C:/Users/$dev/install.py")

    def test_brackets_and_apostrophe_are_quoted(self):
        command = self.command(r"C:\Program Files (x86)\Python\python.exe",
                               r"C:\Users\O'Brien\install.py")
        self.assertTrue(command.startswith('"C:/Program Files (x86)/Python/python.exe" '
                                           '"C:/Users/O\'Brien/install.py"'))

    def test_posix_keeps_shlex_quoting(self):
        with mock.patch.object(engine.sys, "executable", "/opt/my python/bin/python3"), \
                mock.patch.object(engine, "IS_WINDOWS", False):
            command = engine.install_command()
        self.assertTrue(command.startswith("'/opt/my python/bin/python3' "))


@unittest.skipUnless(os.name == "nt", "настоящие Git Bash и PowerShell есть только на Windows")
class WindowsShellsRunTheCommandTests(unittest.TestCase):
    """Строку команды выполняют настоящие Git Bash и PowerShell: программа и
    скрипт — в папках с пробелом и кириллицей, как у «AI Мастерская»."""

    def setUp(self):
        import venv
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve() / "папка с пробелом"
        venv.create(base / "venv", with_pip=False)
        self.python = base / "venv" / "Scripts" / "python.exe"
        self.script = base / "AI Мастерская" / "install.py"
        self.script.parent.mkdir(parents=True)
        self.script.write_text("import json, os, sys\n"
                               "with open(os.environ['AIMASTER_ARGV_OUT'], 'w', encoding='utf-8') as f:\n"
                               "    json.dump(sys.argv, f)\n", encoding="utf-8")
        self.out = base / "argv.json"
        self.line = engine.command_line([str(self.python), str(self.script), "--install-deps"],
                                        windows=True)

    def assert_ran(self, argv) -> None:
        env = {**os.environ, "AIMASTER_ARGV_OUT": str(self.out)}
        proc = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace"))
        seen = json.loads(self.out.read_text(encoding="utf-8"))
        self.out.unlink()
        self.assertEqual(os.path.normcase(os.path.abspath(seen[0])), os.path.normcase(str(self.script)))
        self.assertEqual(seen[1:], ["--install-deps"])

    def test_git_bash(self):
        bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if not bash.is_file():
            self.skipTest("Git Bash не установлен")
        self.assert_ran([str(bash), "-c", self.line])

    def test_powershell_with_call_operator_before_a_quoted_program(self):
        line = f"& {self.line}" if self.line.startswith(("\"", "'")) else self.line
        encoded = base64.b64encode(line.encode("utf-16-le")).decode("ascii")
        self.assert_ran(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded])


class FindNodeTests(unittest.TestCase):
    def test_node_major_parses_version(self):
        self.assertEqual(engine.node_major("node", run=node_says("v22.3.0")), 22)
        self.assertIsNone(engine.node_major("node", run=node_says("garbage")))

    def test_windows_takes_exe_not_cmd_and_ignores_relative_path(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            (base / "npmdir").mkdir()
            (base / "npmdir" / "node.cmd").write_text("", encoding="utf-8")
            program_files = base / "Program Files"
            (program_files / "nodejs").mkdir(parents=True)
            exe = program_files / "nodejs" / "node.exe"
            exe.write_text("", encoding="utf-8")
            # "relative" должен реально существовать и содержать node.exe —
            # иначе тест "проходит" даже если фильтр относительных путей в
            # find_program сломан: несуществующий файл найтись и так не мог.
            (base / "relative").mkdir()
            (base / "relative" / "node.exe").write_text("", encoding="utf-8")
            env = {"PATH": os.pathsep.join(["relative", str(base / "npmdir")]),
                   "ProgramFiles": str(program_files)}
            previous_cwd = os.getcwd()
            os.chdir(base)
            try:
                with mock.patch.object(platform_compat, "IS_WINDOWS", True), \
                        mock.patch.object(engine, "IS_WINDOWS", True):
                    self.assertEqual(engine.find_node(environ=env), str(exe))
            finally:
                os.chdir(previous_cwd)

    def test_posix_needs_executable_bit(self):
        if os.name == "nt":
            self.skipTest("бит исполнения есть только на POSIX")
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp).resolve()
            node = folder / "node"
            node.write_text("#!/bin/sh\n", encoding="utf-8")
            self.assertIsNone(platform_compat.find_program("node", environ={"PATH": str(folder)}))
            node.chmod(0o755)
            self.assertEqual(platform_compat.find_program("node", environ={"PATH": str(folder)}),
                             str(node))


if __name__ == "__main__":
    unittest.main()

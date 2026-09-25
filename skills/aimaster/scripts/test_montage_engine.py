#!/usr/bin/env python3
"""Движок HyperFrames: закреплённая версия, где стоит, готов ли (Node 22+, пакет, браузер)."""

from __future__ import annotations

import json
import os
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

    def test_ready_engine(self):
        self.install_package()
        browser = self.install_browser()
        found, reason = self.locate("v24.1.0")
        self.assertEqual(reason, "")
        self.assertEqual(found.version, "0.8.75")
        self.assertEqual(found.browser, str(browser))
        self.assertEqual(found.script,
                         self.prefix / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs")

    def test_status_and_require_name_the_exact_install_command(self):
        status = engine.engine_status(environ=self.env)
        self.assertEqual((status["state"], status["wanted"]), ("missing", "0.8.75"))
        self.assertEqual(status["install"], engine.install_command())
        with mock.patch.object(engine, "find_node", return_value=None):
            with self.assertRaises(MontageError) as caught:
                engine.require_engine(environ=self.env)
        self.assertIn(engine.install_command(), str(caught.exception))

    def test_install_command_is_this_python_and_this_install_py(self):
        command = engine.install_command()
        self.assertIn(sys.executable, command)
        self.assertIn(str(_SCRIPTS / "install.py"), command)
        self.assertTrue(command.endswith("--install-deps"))
        with mock.patch.object(engine, "IS_WINDOWS", True):
            self.assertTrue(engine.install_command().endswith("--install-deps"))

    def test_package_versions(self):
        self.install_package()
        gsap = self.prefix / "node_modules" / "gsap"
        gsap.mkdir(parents=True)
        (gsap / "package.json").write_text('{"version": "3.14.2"}', encoding="utf-8")
        self.assertEqual((engine.package_version(self.prefix, "gsap"), engine.installed_version(self.prefix)),
                         ("3.14.2", "0.8.75"))
        self.assertIsNone(engine.package_version(self.prefix, "nope"))


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

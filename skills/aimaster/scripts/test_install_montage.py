#!/usr/bin/env python3
"""Установка монтажа: Node 22+, HyperFrames через node + npm-cli.js, браузер в HOME движка."""

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

import install  # noqa: E402
import install_montage  # noqa: E402
import install_montage_engine  # noqa: E402
import install_montage_node  # noqa: E402
from studio.montage import engine  # noqa: E402

PIN = engine.load_pin()


def temp_base(test) -> Path:
    temp = tempfile.TemporaryDirectory()
    test.addCleanup(temp.cleanup)
    return Path(temp.name).resolve()


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


class NodeCheckTests(unittest.TestCase):
    def patch_node(self, paths, major):
        sequence = iter(paths)
        return (mock.patch.object(engine, "find_node", side_effect=lambda **kw: next(sequence)),
                mock.patch.object(engine, "node_major", return_value=major))

    def test_found_when_new_enough(self):
        find, major = self.patch_node(["/usr/local/bin/node"], 22)
        with find, major:
            item = install_montage_node.node_check("macos", install_missing=False)
        self.assertEqual((item["status"], item["version"]), ("found", 22))

    def test_old_node_is_missing_with_command(self):
        find, major = self.patch_node(["/usr/local/bin/node"], 20)
        with find, major, mock.patch.object(install, "_run") as run:
            item = install_montage_node.node_check("macos", install_missing=False)
        run.assert_not_called()
        self.assertEqual((item["status"], item["install_cmd"]), ("missing", "brew install node"))
        self.assertIn("20", item["message"])

    def test_windows_installs_lts_with_winget_flags(self):
        find, major = self.patch_node([None, "C:/Program Files/nodejs/node.exe"], 24)
        with find, major, mock.patch.object(install, "_find_program", return_value="C:/winget.exe"), \
                mock.patch.object(install, "_run", return_value=(0, "", "")) as run:
            item = install_montage_node.node_check("windows", install_missing=True)
        self.assertEqual(item["status"], "installed")
        argv = run.call_args.args[0]
        self.assertEqual(argv[:5], ["C:/winget.exe", "install", "-e", "--id", "OpenJS.NodeJS.LTS"])
        self.assertIn("--disable-interactivity", argv)

    def test_linux_prints_instruction_and_never_runs(self):
        find, major = self.patch_node([None], None)
        with find, major, mock.patch.object(install, "_run") as run:
            item = install_montage_node.node_check("linux", install_missing=True)
        run.assert_not_called()
        self.assertEqual(item["status"], "missing")
        self.assertIn("nodejs.org", item["message"])


class NpmCliTests(unittest.TestCase):
    def test_windows_layout(self):
        base = temp_base(self)
        node = touch(base / "nodejs" / "node.exe")
        npm = touch(base / "nodejs" / "node_modules" / "npm" / "bin" / "npm-cli.js")
        self.assertEqual(install_montage_node.npm_cli_js(str(node)), npm)

    def test_tarball_nvm_and_setup_node_layout(self):
        base = temp_base(self)
        node = touch(base / "node-v22" / "bin" / "node")
        npm = touch(base / "node-v22" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js")
        self.assertEqual(install_montage_node.npm_cli_js(str(node)), npm)

    def test_homebrew_layout(self):
        base = temp_base(self)
        cellar = touch(base / "Cellar" / "node" / "26.7.0" / "bin" / "node")
        npm = touch(base / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js")
        (base / "bin").mkdir()
        try:
            os.symlink(cellar, base / "bin" / "node")
        except (OSError, NotImplementedError):
            self.skipTest("символические ссылки недоступны")
        self.assertEqual(install_montage_node.npm_cli_js(str(base / "bin" / "node")), npm)

    def test_missing_npm(self):
        base = temp_base(self)
        self.assertIsNone(install_montage_node.npm_cli_js(str(touch(base / "bin" / "node"))))


class EngineInstallTests(unittest.TestCase):
    def setUp(self):
        self.base = temp_base(self)
        self.prefix = self.base / "tools" / "hyperframes"
        self.node = touch(self.base / "node" / "bin" / "node")
        self.npm = touch(self.base / "node" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js")
        self.calls = []

    def fake_npm(self, version="0.8.75", code=0, gsap="3.14.2"):
        def run(argv, cwd=None, timeout=None, env=None):
            self.calls.append({"argv": argv, "cwd": cwd, "timeout": timeout, "env": env})
            if code != 0:
                return code, "", "npm ERR! network"
            package = self.prefix / "node_modules" / "hyperframes"
            touch(package / "bin" / "hyperframes.mjs")
            (package / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
            if gsap:
                touch(self.prefix / "node_modules" / "gsap" / "dist" / "gsap.min.js")
                (self.prefix / "node_modules" / "gsap" / "package.json").write_text(
                    json.dumps({"version": gsap}), encoding="utf-8")
            return 0, "added 70 packages", ""
        return run

    def test_runs_npm_cli_js_with_node_and_pinned_package(self):
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=False,
                                              run=self.fake_npm())
        self.assertEqual(item["status"], "installed")
        call = self.calls[0]
        argv = call["argv"]
        self.assertEqual(argv[:3], [str(self.node), str(self.npm), "install"])
        self.assertEqual(argv[argv.index("--prefix") + 1], str(self.prefix))
        self.assertIn("hyperframes@0.8.75", argv)
        self.assertIn("gsap@3.14.2", argv)
        self.assertFalse(any("npx" in str(part) for part in argv))
        self.assertEqual(call["timeout"], PIN["timeouts"]["npm_install"])
        self.assertTrue(call["env"]["PATH"].startswith(str(self.node.parent)))

    def test_pinned_version_is_found_without_npm(self):
        self.fake_npm()([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=False,
                                              run=self.fake_npm())
        self.assertEqual(item["status"], "found")
        self.assertEqual(self.calls, [])

    def test_other_version_waits_for_update(self):
        self.fake_npm("0.8.74")([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=False,
                                              run=self.fake_npm())
        self.assertEqual(item["status"], "found")
        self.assertIn("--update", item["message"])
        self.assertEqual(self.calls, [])
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=True,
                                              run=self.fake_npm())
        self.assertEqual(item["status"], "installed")

    def test_missing_gsap_is_installed_without_update_flag(self):
        self.fake_npm(gsap=None)([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=False,
                                                     run=self.fake_npm())
        self.assertEqual(item["status"], "installed")
        self.assertEqual(len(self.calls), 1)

    def test_npm_failure_and_timeout(self):
        failed = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=False,
                                                run=self.fake_npm(code=1))
        self.assertEqual(failed["status"], "failed")
        self.assertIn("npm ERR", failed["message"])
        slow = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, update=False,
                                              run=lambda *a, **k: (install.TIMEOUT_CODE, "", ""))
        self.assertEqual(slow["status"], "timeout")


class BrowserInstallTests(unittest.TestCase):
    def setUp(self):
        self.base = temp_base(self)
        self.prefix = self.base / "tools" / "hyperframes"
        self.browser = self.prefix / "home" / ".cache" / "hyperframes" / "chrome" / "chrome-headless-shell"
        self.calls = []

    def runner(self, path_line):
        def run(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[2:4] == ["browser", "path"]:
                return subprocess.CompletedProcess(argv, 0, (path_line + "\n").encode(), b"")
            touch(self.browser)
            return subprocess.CompletedProcess(argv, 0, b"Ready to render.", b"")
        return run

    def test_downloads_into_engine_home_and_records_the_path(self):
        item = install_montage_engine.browser_install("/usr/bin/node", self.prefix, PIN,
                                               runner=self.runner(str(self.browser)))
        self.assertEqual(item["status"], "installed")
        self.assertEqual(engine.read_record(self.prefix)["browser"], str(self.browser))
        argv, kwargs = self.calls[0]
        self.assertEqual(argv[2:4], ["browser", "ensure"])
        self.assertEqual(kwargs["env"]["HOME"], str(self.prefix / "home"))

    def test_system_chrome_is_not_accepted(self):
        outside = touch(self.base / "Google Chrome")
        item = install_montage_engine.browser_install("/usr/bin/node", self.prefix, PIN,
                                               runner=self.runner(str(outside)))
        self.assertEqual(item["status"], "failed")
        self.assertNotIn("browser", engine.read_record(self.prefix))

    def test_recorded_browser_is_found_without_download(self):
        touch(self.browser)
        engine.write_record(self.prefix, {"browser": str(self.browser), "version": PIN["version"]})
        item = install_montage_engine.browser_install("/usr/bin/node", self.prefix, PIN,
                                               runner=self.runner("x"))
        self.assertEqual(item["status"], "found")
        self.assertEqual(self.calls, [])


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.base = temp_base(self)
        patcher = mock.patch.dict(os.environ, {engine.PREFIX_ENV: str(self.base / "hf")})
        patcher.start()
        self.addCleanup(patcher.stop)
        skills_patch = mock.patch.object(install_montage.install_montage_skills, "skills_report",
                                         return_value={"status": "found", "message": ""})
        self.skills = skills_patch.start()
        self.addCleanup(skills_patch.stop)

    def test_skills_follow_the_act_flag(self):
        with mock.patch.object(engine, "find_node", return_value=None):
            report = install_montage.montage_report("linux", install_missing=True, update=False,
                                                    install_node=False, home=self.base)
        self.assertEqual(report["skills"]["status"], "found")
        self.assertEqual(self.skills.call_args.kwargs, {"act": True, "home": self.base})

    def test_check_only_installs_nothing(self):
        with mock.patch.object(engine, "find_node", return_value="/usr/bin/node"), \
                mock.patch.object(engine, "node_major", return_value=22), \
                mock.patch.object(install, "_run", side_effect=AssertionError("ничего не ставим")), \
                mock.patch.object(install_montage_engine, "run_engine",
                                  side_effect=AssertionError("ничего не качаем")):
            report = install_montage.montage_report("macos", install_missing=False, update=False,
                                                    install_node=False, home=self.base)
        self.assertEqual([report[key]["status"] for key in ("node", "hyperframes", "browser")],
                         ["found", "missing", "missing"])
        self.assertIs(report["ok"], False)
        self.assertEqual(report["prefix"], str(self.base / "hf"))

    def test_no_node_skips_the_engine(self):
        with mock.patch.object(engine, "find_node", return_value=None):
            report = install_montage.montage_report("linux", install_missing=True, update=False,
                                                    install_node=True, home=self.base)
        self.assertEqual(report["hyperframes"]["status"], "missing")
        self.assertIn("Node.js", report["hyperframes"]["message"])

    def test_text_lines(self):
        lines = install_montage.render_montage_lines(
            {"ok": False, "node": {"status": "missing", "message": "Node.js не найден"}})
        self.assertEqual(lines[0], "Монтаж (HyperFrames): не готов")
        self.assertIn("  Node.js 22+ — нет", lines)
        self.assertIn("      Node.js не найден", lines)


if __name__ == "__main__":
    unittest.main()

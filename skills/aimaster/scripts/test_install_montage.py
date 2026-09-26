#!/usr/bin/env python3
"""Установка монтажа: Node 22+, HyperFrames через node + npm-cli.js, браузер в HOME движка."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install  # noqa: E402
import install_montage  # noqa: E402
import install_montage_browser  # noqa: E402
import install_montage_browser_win  # noqa: E402
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

    def test_unparsable_version_does_not_say_none(self):
        find, major = self.patch_node(["/usr/local/bin/node"], None)
        with find, major, mock.patch.object(install, "_run") as run:
            item = install_montage_node.node_check("macos", install_missing=False)
        run.assert_not_called()
        self.assertEqual(item["status"], "missing")
        self.assertIn("версию не удалось определить", item["message"])
        self.assertNotIn("None", item["message"])

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
        """Разбор 1/5 → 2/5, находка C: сообщение само называет команду —
        render_montage_lines печатает только message, «командой выше» без
        самой команды рядом ничего не говорит пользователю."""

        find, major = self.patch_node([None], None)
        with find, major, mock.patch.object(install, "_run") as run:
            item = install_montage_node.node_check("linux", install_missing=True)
        run.assert_not_called()
        self.assertEqual(item["status"], "missing")
        self.assertIn("nodejs.org", item["message"])
        # разбор 3/5, находка 5: одной nodejs недостаточно — на Debian/Ubuntu
        # npm часто отдельный пакет, ставим сразу оба.
        self.assertIn("sudo apt install nodejs npm", item["message"])
        # то, что реально увидит пользователь в тексте — тот же message
        lines = install_montage.render_montage_lines({"ok": False, "node": item})
        self.assertIn("      " + item["message"], lines)


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

    def test_shim_manager_is_resolved_via_process_exec_path(self):
        """asdf/Volta/Scoop ставят перед Node не симлинк, а скрипт-шим —
        os.path.realpath его не раскрывает; npm-cli.js ищем по пути, который
        называет сам `node -p process.execPath`."""

        base = temp_base(self)
        shim = touch(base / "shims" / "node")
        real_node = touch(base / "versions" / "22.1.0" / "bin" / "node")
        npm = touch(base / "versions" / "22.1.0" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js")

        def fake_run(argv, **kwargs):
            self.assertEqual(argv[:2], [str(shim), "-p"])
            return subprocess.CompletedProcess(argv, 0, (str(real_node) + "\n").encode(), b"")

        self.assertEqual(install_montage_node.npm_cli_js(str(shim), run=fake_run), npm)

    def test_shim_resolution_failure_falls_back_to_the_given_path(self):
        base = temp_base(self)
        node = touch(base / "nodejs" / "node.exe")
        npm = touch(base / "nodejs" / "node_modules" / "npm" / "bin" / "npm-cli.js")

        def broken_run(argv, **kwargs):
            raise OSError("не удалось запустить node")

        self.assertEqual(install_montage_node.npm_cli_js(str(node), run=broken_run), npm)


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
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                              install_missing=True, update=False, run=self.fake_npm())
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
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                              install_missing=True, update=False, run=self.fake_npm())
        self.assertEqual(item["status"], "found")
        self.assertEqual(self.calls, [])

    def test_neither_flag_only_reports_the_present_wrong_version(self):
        self.fake_npm("0.8.74")([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                              install_missing=False, update=False, run=self.fake_npm())
        self.assertEqual(item["status"], "found")
        self.assertIn("--install-deps", item["message"])
        self.assertEqual(self.calls, [])

    def test_neither_flag_names_the_gsap_mismatch_not_a_fake_version_diff(self):
        """Разбор 1/5 → 2/5, находка G: HyperFrames уже той версии, что
        нужно — «стоит 0.8.75, нужна 0.8.75» ничего не объясняет, дело в GSAP."""

        self.fake_npm(gsap=None)([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                              install_missing=False, update=False, run=self.fake_npm())
        self.assertEqual(item["status"], "found")
        self.assertIn("GSAP", item["message"])
        self.assertNotIn(f"стоит {PIN['version']}, нужна {PIN['version']}", item["message"])

    def test_neither_flag_names_the_gsap_version_mismatch_not_missing(self):
        """Разбор 3/5, находка 5: GSAP стоит, но не той версии — не «нет GSAP»."""

        self.fake_npm(gsap="3.14.1")([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                              install_missing=False, update=False, run=self.fake_npm())
        self.assertEqual(item["status"], "found")
        self.assertIn("3.14.1", item["message"])
        self.assertIn(PIN["gsap_version"], item["message"])
        self.assertNotIn("нет GSAP", item["message"])

    def test_install_deps_alone_reinstalls_present_wrong_version_to_pin(self):
        """Разбор 1/5, находка 3: --install-deps один тоже чинит версию —
        документированная команда действительно чинит расхождение."""

        self.fake_npm("0.8.74")([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                              install_missing=True, update=False, run=self.fake_npm())
        self.assertEqual(item["status"], "installed")
        argv = self.calls[0]["argv"]
        self.assertIn(f"hyperframes@{PIN['version']}", argv)
        self.assertEqual(item["version"], PIN["version"])

    def test_update_alone_also_repairs_a_present_wrong_version(self):
        self.fake_npm("0.8.74")([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                              install_missing=False, update=True, run=self.fake_npm())
        self.assertEqual(item["status"], "installed")

    def test_update_alone_never_installs_from_nothing(self):
        """Разбор 1/5, находка 2: --update один на чистой машине ничего не ставит."""

        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                              install_missing=False, update=True, run=self.fake_npm())
        self.assertEqual(item["status"], "missing")
        self.assertIn("--install-deps", item["message"])
        self.assertEqual(self.calls, [])

    def test_missing_gsap_is_installed_with_install_deps(self):
        self.fake_npm(gsap=None)([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                              install_missing=True, update=False, run=self.fake_npm())
        self.assertEqual(item["status"], "installed")
        self.assertEqual(len(self.calls), 1)

    def test_missing_gsap_is_repaired_by_update_alone_when_hyperframes_is_present(self):
        self.fake_npm(gsap=None)([], None, None, None)
        self.calls.clear()
        item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                              install_missing=False, update=True, run=self.fake_npm())
        self.assertEqual(item["status"], "installed")

    def test_npm_failure_and_timeout(self):
        failed = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                                install_missing=True, update=False,
                                                run=self.fake_npm(code=1))
        self.assertEqual(failed["status"], "failed")
        self.assertIn("npm ERR", failed["message"])
        slow = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                              install_missing=True, update=False,
                                              run=lambda *a, **k: (install.TIMEOUT_CODE, "", ""))
        self.assertEqual(slow["status"], "timeout")

    def test_default_runner_kills_the_whole_process_tree_on_timeout(self):
        """Разбор 1/5, находка 5: по умолчанию npm запускается через
        движковый tree-killing runner, а не голый subprocess.run."""

        with mock.patch.object(install_montage_engine, "default_runner",
                                side_effect=subprocess.TimeoutExpired(["node"], 1)) as runner:
            item = install_montage_engine.engine_install(str(self.node), self.prefix, PIN, kind="macos",
                                                  install_missing=True, update=False)
        runner.assert_called_once()
        self.assertEqual(item["status"], "timeout")

    def test_npm_missing_message_is_platform_specific(self):
        """Разбор 1/5 → 2/5, находка C: дистрибутивный nodejs без npm — надо
        поставить npm отдельно (sudo apt install npm), не «переустановите
        Node.js» (переустановка apt-пакета npm может не принести)."""

        with mock.patch.object(install_montage_engine, "npm_cli_js", return_value=None):
            linux = install_montage_engine.engine_install(str(self.node), self.prefix, PIN,
                                                  kind="linux", install_missing=True, update=False)
            macos = install_montage_engine.engine_install(str(self.node), self.prefix, PIN,
                                                  kind="macos", install_missing=True, update=False)
        self.assertEqual(linux["status"], "failed")
        self.assertIn("sudo apt install npm", linux["message"])
        self.assertEqual(macos["status"], "failed")
        self.assertIn("brew reinstall node", macos["message"])


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

    def call(self, *args, **kwargs):
        """browser_install печатает «Качаю компонент…» в stderr, когда
        реально доходит до скачивания — перехватываем, чтобы тестовый вывод
        оставался чистым (разбор 1/5 → 2/5, находка I)."""

        with redirect_stderr(io.StringIO()):
            return install_montage_browser.browser_install(*args, **kwargs)

    def test_old_names_still_work_from_the_engine_module(self):
        """Разбор 4/5, находка 3: браузер переехал в install_montage_browser.py,
        прежние имена install_montage_engine.* (интерфейс плана) — те же функции."""

        self.assertIs(install_montage_engine.browser_install, install_montage_browser.browser_install)
        self.assertIs(install_montage_engine.check_browser, install_montage_browser.check_browser)

    def test_downloads_into_engine_home_and_records_the_path(self):
        item = self.call("/usr/bin/node", self.prefix, PIN,
                         install_missing=True, update=False,
                         runner=self.runner(str(self.browser)))
        self.assertEqual(item["status"], "installed")
        self.assertEqual(engine.read_record(self.prefix)["browser"], str(self.browser))
        argv, kwargs = self.calls[0]
        self.assertEqual(argv[2:4], ["browser", "ensure"])
        self.assertEqual(kwargs["env"]["HOME"], str(self.prefix / "home"))
        # --json в каждом запуске движка: без него он ходит за обновлениями (engine_cli.argv_for)
        self.assertEqual([call[0][-1] for call in self.calls], ["--json"] * len(self.calls))

    # --- HYPERFRAMES_BROWSER_PATH: не поддерживается (round 4/5) ---

    def install_engine_files(self):
        """Минимальный движок в префиксе — чтобы engine.locate() дошёл до браузера."""

        touch(engine.entry_script(self.prefix))
        manifest = self.prefix / "node_modules" / "hyperframes" / "package.json"
        manifest.write_text(json.dumps({"version": PIN["version"]}), encoding="utf-8")
        gsap = self.prefix / "node_modules" / "gsap"
        for name in ("gsap", "MotionPathPlugin"):  # GSAP черновика — часть движка (engine.locate)
            touch(gsap / "dist" / f"{name}.min.js")
        (gsap / "package.json").write_text(json.dumps({"version": PIN["gsap_version"]}), encoding="utf-8")

    def locate(self):
        env = {engine.PREFIX_ENV: str(self.prefix), "PATH": ""}
        with mock.patch.object(engine, "find_node", return_value="/usr/bin/node"), \
                mock.patch.object(engine, "node_major", return_value=PIN["node_min_major"]):
            return engine.locate(environ=env)

    def test_browser_path_variable_changes_nothing_and_install_agrees_with_locate(self):
        """round 4/5: запись установщика — единственный источник правды.
        Переменная указывает на реальный файл, но ни check_browser, ни
        browser_install её не читают, в запуски `ensure`/`path` она не
        уходит, а итог установки совпадает с engine.locate() до и после."""

        self.install_engine_files()
        user_choice = touch(self.base / "свой браузер" / "chrome-headless-shell.exe")
        with mock.patch.dict(os.environ, {"HYPERFRAMES_BROWSER_PATH": str(user_choice)}), \
                mock.patch.object(install_montage_browser, "IS_WINDOWS", False):
            self.assertEqual(install_montage_browser.check_browser(self.prefix, PIN)["status"], "missing")
            found, reason = self.locate()
            self.assertIsNone(found)
            self.assertIn("не скачан браузер", reason)

            item = self.call("/usr/bin/node", self.prefix, PIN, install_missing=True, update=False,
                             runner=self.runner(str(self.browser)))
            self.assertEqual(item["status"], "installed")
            self.assertEqual(item["path"], str(self.browser))
            for _argv, kwargs in self.calls:
                self.assertNotIn("HYPERFRAMES_BROWSER_PATH", kwargs["env"])

            self.assertEqual(install_montage_browser.check_browser(self.prefix, PIN),
                             {"status": "found", "message": "", "path": str(self.browser)})
            found, reason = self.locate()
            self.assertEqual(reason, "")
            self.assertEqual(found.browser, str(self.browser))

    def test_record_for_another_version_is_missing_for_both_check_and_locate(self):
        """round 4/5: check_browser и engine.locate() зовут одну проверку —
        браузер, записанный для другой версии HyperFrames, не готов ни там, ни там."""

        self.install_engine_files()
        touch(self.browser)
        engine.write_record(self.prefix, {"browser": str(self.browser), "version": "0.8.70"})
        self.assertEqual(install_montage_browser.check_browser(self.prefix, PIN)["status"], "missing")
        found, _reason = self.locate()
        self.assertIsNone(found)

    def test_hyperframes_hint_is_replaced_by_our_command_on_every_platform(self):
        hint = install_montage_browser._MISLEADING_HINT

        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[2:4] == ["browser", "path"]:
                return subprocess.CompletedProcess(argv, 1, b"", b"")
            return subprocess.CompletedProcess(argv, 1, b"", ("Chrome cannot start. " + hint).encode())

        for windows in (False, True):
            with self.subTest(windows=windows), \
                    mock.patch.object(install_montage_browser, "IS_WINDOWS", windows), \
                    mock.patch.object(install_montage_browser_win, "preseed",
                                      return_value=install_montage_browser_win.PreseedResult(True)):
                item = self.call("/usr/bin/node", self.prefix, PIN,
                                 install_missing=True, update=False, runner=runner)
                self.assertEqual(item["status"], "failed")
                self.assertNotIn("HYPERFRAMES_BROWSER_PATH", item["message"])
                self.assertIn("install.py --install-deps", item["message"])

    def test_stale_recorded_browser_outside_home_is_not_found(self):
        """round 3/5, Minor 7: устаревшая запись (от прошлого override или
        ручной правки) вне папки движка не должна тихо сойти за «готовый
        браузер» — ни в browser_install, ни в check_browser."""

        outside = touch(self.base / "снаружи" / "chrome-headless-shell.exe")
        engine.write_record(self.prefix, {"browser": str(outside), "version": PIN["version"]})
        item = self.call("/usr/bin/node", self.prefix, PIN,
                         install_missing=False, update=False,
                         runner=self.runner("не должно понадобиться"))
        self.assertEqual(item["status"], "missing")
        self.assertEqual(self.calls, [])
        self.assertEqual(install_montage_browser.check_browser(self.prefix, PIN)["status"], "missing")

    # --- Windows: install_montage_browser_win.preseed перед ensure ---

    def test_windows_calls_preseed_with_the_download_deadline_before_ensure(self):
        """round 4/5: бюджет timeouts.browser общий — preseed получает срок
        скачивания download_deadline(B), `ensure` — остаток, не больше B."""

        order = []

        def fake_preseed(prefix, *, deadline):
            order.append(("preseed", deadline))
            return install_montage_browser_win.PreseedResult(True)

        def runner(argv, **kwargs):
            order.append(("ensure" if argv[2:4] == ["browser", "ensure"] else "path", kwargs["timeout"]))
            self.calls.append((argv, kwargs))
            if argv[2:4] == ["browser", "path"]:
                return subprocess.CompletedProcess(argv, 0, (str(self.browser) + "\n").encode(), b"")
            touch(self.browser)
            return subprocess.CompletedProcess(argv, 0, b"Ready to render.", b"")

        with mock.patch.object(install_montage_browser, "IS_WINDOWS", True), \
                mock.patch.object(install_montage_browser_win, "preseed", side_effect=fake_preseed):
            item = self.call("/usr/bin/node", self.prefix, PIN,
                             install_missing=True, update=False, runner=runner)
        budget = PIN["timeouts"]["browser"]
        self.assertEqual(item["status"], "installed")
        self.assertEqual(order[0], ("preseed", install_montage_browser_win.download_deadline(budget)))
        self.assertEqual(order[1][0], "ensure")
        self.assertLessEqual(order[1][1], budget)
        self.assertGreater(order[1][1], budget - 5)  # preseed-заглушка мгновенная — остаток почти весь B

    def test_posix_never_calls_preseed(self):
        with mock.patch.object(install_montage_browser, "IS_WINDOWS", False), \
                mock.patch.object(install_montage_browser_win, "preseed") as preseed_mock:
            self.call("/usr/bin/node", self.prefix, PIN,
                     install_missing=True, update=False, runner=self.runner(str(self.browser)))
        preseed_mock.assert_not_called()
        self.assertEqual(self.calls[0][1]["timeout"], PIN["timeouts"]["browser"])

    def test_windows_ensure_timeout_keeps_the_preseed_reason(self):
        """round 4/5, пункт 5: `ensure` не уложился — причина отказа своего
        скачивателя всё равно видна человеку (раньше терялась на этой ветке)."""

        def runner(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        with mock.patch.object(install_montage_browser, "IS_WINDOWS", True), \
                mock.patch.object(install_montage_browser_win, "preseed",
                                  return_value=install_montage_browser_win.PreseedResult(
                                      False, "chrome-headless-shell напрямую не скачался за 660 с")):
            item = self.call("/usr/bin/node", self.prefix, PIN,
                             install_missing=True, update=False, runner=runner)
        self.assertEqual(item["status"], "timeout")
        self.assertIn("не скачался за 660 с", item["message"])

    def test_windows_preseed_failure_reason_appears_in_the_final_failure_message(self):
        outside = touch(self.base / "Google Chrome")  # ensure/path в итоге всё равно откажет
        with mock.patch.object(install_montage_browser, "IS_WINDOWS", True), \
                mock.patch.object(install_montage_browser_win, "preseed",
                                  return_value=install_montage_browser_win.PreseedResult(False, "сеть недоступна")):
            item = self.call("/usr/bin/node", self.prefix, PIN,
                             install_missing=True, update=False, runner=self.runner(str(outside)))
        self.assertEqual(item["status"], "failed")
        self.assertIn("сеть недоступна", item["message"])

    # --- сообщения об отказе ---

    def test_system_chrome_is_not_accepted(self):
        """`browser path` может отдать путь вне папки движка (например
        системный Chrome, а не то, что только что скачал `ensure`) —
        сообщение должно называть причину, а не молча показать хвост `ensure`."""

        outside = touch(self.base / "Google Chrome")
        item = self.call("/usr/bin/node", self.prefix, PIN,
                         install_missing=True, update=False,
                         runner=self.runner(str(outside)))
        self.assertEqual(item["status"], "failed")
        self.assertIn("путь вне папки движка", item["message"])
        self.assertIn(str(outside), item["message"])
        self.assertNotIn("browser", engine.read_record(self.prefix))

    def test_failure_names_a_nonzero_path_exit_code(self):
        """`browser path` может завершиться с ненулевым кодом — сообщение
        должно назвать именно это, а не молча показать успешный хвост `ensure`."""

        def runner(argv, **kwargs):
            self.calls.append((argv, kwargs))
            if argv[2:4] == ["browser", "path"]:
                return subprocess.CompletedProcess(argv, 1, b"", b"boom")
            touch(self.browser)
            return subprocess.CompletedProcess(argv, 0, b"Ready to render.", b"")

        item = self.call("/usr/bin/node", self.prefix, PIN,
                         install_missing=True, update=False, runner=runner)
        self.assertEqual(item["status"], "failed")
        self.assertIn("path вышел с кодом 1", item["message"])
        self.assertIn("boom", item["message"])

    def test_failure_names_a_missing_file_on_disk(self):
        """`browser path` печатает путь внутри папки движка, но файла там
        нет (причина конкретной CI-находки не важна для этого теста — важно,
        что сообщение называет именно эту причину, а не хвост `ensure`)."""

        missing = self.browser.parent / "нет-такого-файла.exe"
        item = self.call("/usr/bin/node", self.prefix, PIN,
                         install_missing=True, update=False,
                         runner=self.runner(str(missing)))
        self.assertEqual(item["status"], "failed")
        self.assertIn("файла нет на диске", item["message"])
        self.assertIn(str(missing), item["message"])

    def test_no_retry_on_a_missing_file_single_ensure_attempt(self):
        """round 3/5: retry-опрос и второй `ensure` (round 1/5, построены на
        опровергнутых гипотезах — антивирус, незавершённая распаковка) убраны
        — один `ensure`, файла нет → сразу «failed», без пауз."""

        never = self.browser.parent / "так-и-не-скачался.exe"
        item = self.call("/usr/bin/node", self.prefix, PIN,
                         install_missing=True, update=False,
                         runner=self.runner(str(never)))
        self.assertEqual(item["status"], "failed")
        ensure_calls = [argv for argv, _kwargs in self.calls if argv[2:4] == ["browser", "ensure"]]
        self.assertEqual(len(ensure_calls), 1)

    def test_recorded_browser_is_found_without_download(self):
        touch(self.browser)
        engine.write_record(self.prefix, {"browser": str(self.browser), "version": PIN["version"]})
        item = self.call("/usr/bin/node", self.prefix, PIN,
                         install_missing=True, update=False,
                         runner=self.runner("x"))
        self.assertEqual(item["status"], "found")
        self.assertEqual(self.calls, [])

    def test_update_alone_never_downloads_from_nothing(self):
        item = self.call("/usr/bin/node", self.prefix, PIN,
                         install_missing=False, update=True,
                         runner=self.runner(str(self.browser)))
        self.assertEqual(item["status"], "missing")
        self.assertIn("--install-deps", item["message"])
        self.assertEqual(self.calls, [])

    def test_update_alone_repairs_a_stale_recorded_browser(self):
        touch(self.browser)
        engine.write_record(self.prefix, {"browser": str(self.browser), "version": "0.8.70"})
        item = self.call("/usr/bin/node", self.prefix, PIN,
                         install_missing=False, update=True,
                         runner=self.runner(str(self.browser)))
        self.assertEqual(item["status"], "installed")
        self.assertEqual(self.calls[0][0][2:4], ["browser", "ensure"])

    def test_neither_flag_only_reports_a_stale_recorded_browser(self):
        touch(self.browser)
        engine.write_record(self.prefix, {"browser": str(self.browser), "version": "0.8.70"})
        item = self.call("/usr/bin/node", self.prefix, PIN,
                         install_missing=False, update=False,
                         runner=self.runner(str(self.browser)))
        self.assertEqual(item["status"], "found")
        self.assertIn("--install-deps", item["message"])
        self.assertEqual(self.calls, [])


class CheckPackageTests(unittest.TestCase):
    """Разбор 1/5, находка 6: отсутствующий GSAP — missing, не found."""

    def setUp(self):
        self.base = temp_base(self)
        self.prefix = self.base / "tools" / "hyperframes"
        package = self.prefix / "node_modules" / "hyperframes"
        touch(package / "bin" / "hyperframes.mjs")
        (package / "package.json").write_text(json.dumps({"version": PIN["version"]}), encoding="utf-8")

    def test_missing_gsap_is_missing_not_found(self):
        item = install_montage_engine.check_package(self.prefix, PIN)
        self.assertEqual(item["status"], "missing")
        self.assertIn("GSAP", item["message"])

    def test_matching_gsap_is_found(self):
        touch(self.prefix / "node_modules" / "gsap" / "dist" / "gsap.min.js")
        (self.prefix / "node_modules" / "gsap" / "package.json").write_text(
            json.dumps({"version": PIN["gsap_version"]}), encoding="utf-8")
        item = install_montage_engine.check_package(self.prefix, PIN)
        self.assertEqual(item["status"], "found")

    def test_gsap_at_wrong_version_says_the_version_not_that_it_is_missing(self):
        """Разбор 3/5, находка 5: GSAP стоит, но не той версии — сообщение
        должно назвать расхождение версий, а не соврать «нет GSAP»."""

        touch(self.prefix / "node_modules" / "gsap" / "dist" / "gsap.min.js")
        (self.prefix / "node_modules" / "gsap" / "package.json").write_text(
            json.dumps({"version": "3.14.1"}), encoding="utf-8")
        item = install_montage_engine.check_package(self.prefix, PIN)
        self.assertEqual(item["status"], "missing")
        self.assertIn("3.14.1", item["message"])
        self.assertIn(PIN["gsap_version"], item["message"])
        self.assertNotIn("нет GSAP", item["message"])


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

    def test_skills_receive_install_missing_and_update(self):
        with mock.patch.object(engine, "find_node", return_value=None):
            report = install_montage.montage_report("linux", install_missing=True, update=False,
                                                    install_node=False, home=self.base)
        self.assertEqual(report["skills"]["status"], "found")
        self.assertEqual(self.skills.call_args.kwargs,
                         {"install_missing": True, "update": False, "home": self.base})

    def test_check_only_installs_nothing(self):
        with mock.patch.object(engine, "find_node", return_value="/usr/bin/node"), \
                mock.patch.object(engine, "node_major", return_value=22), \
                mock.patch.object(install, "_run", side_effect=AssertionError("ничего не ставим")), \
                mock.patch.object(install_montage_browser, "run_engine",
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

    def test_gsap_only_mismatch_does_not_block_the_browser_with_a_hyperframes_message(self):
        """Разбор 3/5, находка 5: HyperFrames уже на закреплённой версии,
        расхождение только в GSAP — статус hyperframes при этом "missing"
        (см. CheckPackageTests), но браузеру не нужно ждать HyperFrames,
        он уже есть; строка про браузер не должна врать про HyperFrames."""

        prefix = self.base / "hf"
        package = prefix / "node_modules" / "hyperframes"
        touch(package / "bin" / "hyperframes.mjs")
        (package / "package.json").write_text(json.dumps({"version": PIN["version"]}), encoding="utf-8")
        # GSAP не поставлен вовсе
        with mock.patch.object(engine, "find_node", return_value="/usr/bin/node"), \
                mock.patch.object(engine, "node_major", return_value=22):
            report = install_montage.montage_report("macos", install_missing=False, update=False,
                                                    install_node=False, home=self.base)
        self.assertEqual(report["hyperframes"]["status"], "missing")
        self.assertIn("GSAP", report["hyperframes"]["message"])
        self.assertNotIn("сначала нужен HyperFrames", report["browser"]["message"])

    def test_node_not_ready_never_starts_the_browser_download(self):
        """Разбор 4/5, находка 1: Node.js нет или он старый, HyperFrames
        закреплённой версии уже на диске, браузер не скачан, флаг действия
        есть. Раньше browser_install(None, …) печатал «Качаю…» и падал
        TypeError в Popen; install.py прятал это в английскую ошибку, и
        next_steps терял настоящий затор — Node.js."""

        package = self.base / "hf" / "node_modules" / "hyperframes"
        touch(package / "bin" / "hyperframes.mjs")
        (package / "package.json").write_text(json.dumps({"version": PIN["version"]}), encoding="utf-8")
        nodes = (("нет Node.js", None, None), ("Node.js 20", "/usr/bin/node", 20))
        flags = ((True, False), (False, True))  # --install-deps; --update один
        for label, found, major in nodes:
            for install_deps, update in flags:
                stderr = io.StringIO()
                with self.subTest(label, install_deps=install_deps, update=update), \
                        mock.patch.object(engine, "find_node", return_value=found), \
                        mock.patch.object(engine, "node_major", return_value=major), \
                        mock.patch.object(install_montage_browser, "run_engine",
                                          side_effect=AssertionError("без Node браузер не качаем")), \
                        redirect_stderr(stderr):
                    # через настоящий предохранитель install.py, не в обход него
                    report = install._montage_report("linux", install_deps, update, self.base)
                    self.assertNotIn("error", report)
                    self.assertEqual(report["browser"]["status"], "missing")
                    self.assertEqual(report["browser"]["message"],
                                     f"сначала нужен Node.js {PIN['node_min_major']}+")
                    self.assertNotIn("Качаю", stderr.getvalue())
                    step = install._montage_next_step(report)
                    self.assertEqual(step, "Монтаж не готов: " + report["node"]["message"])
                    self.assertIn(install_montage_node.NODE_INSTALL["linux"], step)

    def test_update_alone_does_not_install_a_fresh_engine(self):
        """Разбор 1/5, находка 2, на уровне отчёта целиком."""

        with mock.patch.object(engine, "find_node", return_value="/usr/bin/node"), \
                mock.patch.object(engine, "node_major", return_value=22):
            report = install_montage.montage_report("macos", install_missing=False, update=True,
                                                    install_node=False, home=self.base)
        self.assertEqual(report["hyperframes"]["status"], "missing")
        self.assertIn("--install-deps", report["hyperframes"]["message"])

    def test_text_lines(self):
        lines = install_montage.render_montage_lines(
            {"ok": False, "node": {"status": "missing", "message": "Node.js не найден"}})
        self.assertEqual(lines[0], "Монтаж (HyperFrames): не готов")
        self.assertIn("  Node.js 22+ — нет", lines)
        self.assertIn("      Node.js не найден", lines)

    def test_text_lines_show_the_crash_guard_error(self):
        lines = install_montage.render_montage_lines({"ok": False, "error": "неожиданный сбой"})
        self.assertIn("  неожиданный сбой", lines)

    def test_text_lines_show_install_cmd_when_not_in_the_message(self):
        """Разбор 1/5 → 2/5, находка C: render_montage_lines раньше вообще
        не печатал install_cmd — теперь показывает его, если сообщение сам
        не назвал команду."""

        lines = install_montage.render_montage_lines({"ok": False, "node": {
            "status": "missing", "message": "не найден", "install_cmd": "brew install node"}})
        self.assertIn("      поставить: brew install node", lines)

    def test_text_lines_do_not_duplicate_an_already_embedded_install_cmd(self):
        # настоящий ответ node_check на Linux с --install-deps, не строка от руки
        # (разбор 4/5, находка 4): команда уже внутри message
        with mock.patch.object(engine, "find_node", return_value=None):
            node = install_montage_node.node_check("linux", True)
        command = install_montage_node.NODE_INSTALL["linux"]
        self.assertEqual(node["install_cmd"], command)
        lines = install_montage.render_montage_lines({"ok": False, "node": node})
        self.assertEqual(sum(1 for line in lines if command in line), 1)


class UpdateHelpTextTests(unittest.TestCase):
    """Разбор 2/5, находка F: у install_montage.py нет --install-deps —
    справка не должна советовать его запускать, а вправе объяснить, что его
    здесь нет (упоминание ради отрицания — не то же самое, что совет)."""

    def test_update_help_explains_absence_instead_of_suggesting_the_flag(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer), self.assertRaises(SystemExit):
            install_montage.main(["--help"])
        text = buffer.getvalue()
        self.assertIn("здесь нет", text)
        self.assertNotIn("запустите", text)
        self.assertNotIn("поставить: --install-deps", text)


if __name__ == "__main__":
    unittest.main()

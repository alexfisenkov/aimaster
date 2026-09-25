#!/usr/bin/env python3
"""Запуск HyperFrames: node + JS-вход, без оболочки, свои переменные и HOME."""

from __future__ import annotations

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

from studio.montage import MontageError, engine, engine_cli  # noqa: E402


class FakeRun:
    def __init__(self, code=0, stdout=b"", stderr=b"", timeout=False):
        self.code, self.stdout, self.stderr, self.timeout = code, stdout, stderr, timeout
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.timeout:
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        return subprocess.CompletedProcess(argv, self.code, self.stdout, self.stderr)


def make_engine(base: Path, browser=True) -> engine.Engine:
    return engine.Engine(node="/opt/node/bin/node",
                         script=base / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs",
                         prefix=base, version="0.8.75",
                         browser=str(base / "chrome") if browser else None)


class EnvTests(unittest.TestCase):
    def test_env_has_quiet_flags_private_home_and_browser(self):
        base = Path("/tmp/hf")
        # IS_WINDOWS пришпилен к False: без этого тест на Windows CI видит
        # свой же хост (True) и падает на assertNotIn("USERPROFILE", env),
        # хотя test_windows_also_moves_userprofile ниже отдельно проверяет
        # именно этот случай через явный mock.
        with mock.patch.object(engine_cli, "IS_WINDOWS", False):
            env = engine_cli.engine_env(make_engine(base), {"PATH": "/usr/bin", "HOME": "/Users/me"})
        for key in ("HYPERFRAMES_NO_UPDATE_CHECK", "HYPERFRAMES_NO_AUTO_INSTALL",
                    "HYPERFRAMES_NO_TELEMETRY", "HYPERFRAMES_SKIP_SKILLS"):
            self.assertEqual(env[key], "1")
        self.assertEqual(env["HOME"], str(base / "home"))
        self.assertEqual(env["HYPERFRAMES_BROWSER_PATH"], str(base / "chrome"))
        self.assertEqual(env["HYPERFRAMES_EXTRACT_CACHE_DIR"], str(base / "cache" / "frames"))
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertNotIn("USERPROFILE", env)

    def test_windows_also_moves_userprofile(self):
        with mock.patch.object(engine_cli, "IS_WINDOWS", True):
            env = engine_cli.engine_env(make_engine(Path("/tmp/hf"), browser=False), {})
        self.assertEqual(env["USERPROFILE"], env["HOME"])
        self.assertNotIn("HYPERFRAMES_BROWSER_PATH", env)


class RunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.engine = make_engine(self.base)

    def test_argv_is_node_plus_script_without_shell(self):
        run = FakeRun(stdout=b'{"ok": true}')
        payload = engine_cli.run_engine_json(self.engine, ["timeline", "--json"],
                                             cwd=self.base, timeout=5, runner=run)
        argv, kwargs = run.calls[0]
        self.assertEqual(argv, [self.engine.node, str(self.engine.script), "timeline", "--json"])
        self.assertNotIn("shell", kwargs)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["cwd"], str(self.base))
        self.assertEqual(payload, {"ok": True})
        self.assertTrue((self.base / "home").is_dir())

    def test_refusal_json_on_stderr_becomes_message(self):
        run = FakeRun(code=2, stderr=b'{"ok": false, "reason": "#s1 would overlap #s2 at 1-6",'
                                     b' "fix": "pass --overwrite or move the named neighbour"}')
        with self.assertRaises(MontageError) as caught:
            engine_cli.run_engine_json(self.engine, ["timeline", "trim"], cwd=self.base,
                                       timeout=5, runner=run)
        self.assertIn("would overlap", str(caught.exception))
        self.assertIn("--overwrite", str(caught.exception))

    def test_timeout_is_a_clear_message(self):
        with self.assertRaises(MontageError) as caught:
            engine_cli.run_engine_json(self.engine, ["lint", "."], cwd=self.base, timeout=5,
                                       runner=FakeRun(timeout=True))
        self.assertIn("не ответил", str(caught.exception))

    def test_lint_exit_one_is_allowed_when_asked(self):
        run = FakeRun(code=1, stdout=b'{"ok": false, "findings": []}')
        payload = engine_cli.run_engine_json(self.engine, ["lint", ".", "--json"], cwd=self.base,
                                             timeout=5, ok_codes=(0, 1), runner=run)
        self.assertIs(payload["ok"], False)

    def test_non_json_output_is_refused(self):
        with self.assertRaises(MontageError):
            engine_cli.run_engine_json(self.engine, ["timeline", "--json"], cwd=self.base,
                                       timeout=5, runner=FakeRun(stdout=b"hello"))

    def test_runner_object_delegates_to_module_functions(self):
        with mock.patch.object(engine_cli, "run_engine_json", return_value={"x": 1}) as fake:
            self.assertEqual(engine_cli.EngineRunner().json(self.engine, ["a"], cwd=self.base,
                                                            timeout=1), {"x": 1})
        fake.assert_called_once()


class PopenTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.engine = make_engine(self.base)
        self.calls = []

    def popen(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return mock.Mock(pid=4242)

    def test_posix_detaches_with_new_session(self):
        log = self.base / "logs" / "desk.log"
        with mock.patch.object(engine_cli, "IS_WINDOWS", False):
            engine_cli.popen_engine(self.engine, ["preview", "."], cwd=self.base, log_path=log,
                                    popen=self.popen)
        argv, kwargs = self.calls[0]
        self.assertEqual(argv[:2], [self.engine.node, str(self.engine.script)])
        self.assertIs(kwargs["start_new_session"], True)
        self.assertNotIn("creationflags", kwargs)
        self.assertTrue(log.exists())

    def test_windows_hides_console_and_starts_a_new_group(self):
        with mock.patch.object(engine_cli, "IS_WINDOWS", True):
            engine_cli.popen_engine(self.engine, ["preview", "."], cwd=self.base,
                                    log_path=self.base / "desk.log", popen=self.popen)
        _, kwargs = self.calls[0]
        self.assertTrue(kwargs["creationflags"] & engine_cli.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(kwargs["creationflags"] & engine_cli.CREATE_NO_WINDOW)
        self.assertNotIn("start_new_session", kwargs)


if __name__ == "__main__":
    unittest.main()

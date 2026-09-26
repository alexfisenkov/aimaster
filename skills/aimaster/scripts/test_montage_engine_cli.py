#!/usr/bin/env python3
"""Запуск HyperFrames: node + JS-вход, без оболочки, свои переменные и HOME."""

from __future__ import annotations

import json
import os
import shutil
import signal
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

from studio.montage import MontageError, engine, engine_cli, proc_tree  # noqa: E402


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

    def test_inherited_browser_variable_never_reaches_the_engine(self):
        """round 4/5: браузер — только из записи установщика. Чужой
        HYPERFRAMES_BROWSER_PATH из окружения человека не наследуется: без
        записи его нет вовсе, с записью — перебит путём из записи."""

        inherited = {"HYPERFRAMES_BROWSER_PATH": "/Applications/Google Chrome"}
        base = Path("/tmp/hf")
        with mock.patch.object(engine_cli, "IS_WINDOWS", False):
            without = engine_cli.engine_env(make_engine(base, browser=False), inherited)
            with_record = engine_cli.engine_env(make_engine(base), inherited)
        self.assertNotIn("HYPERFRAMES_BROWSER_PATH", without)
        self.assertEqual(with_record["HYPERFRAMES_BROWSER_PATH"], str(base / "chrome"))

    def test_preview_always_listens_on_loopback(self):
        # `preview` 0.8.75 слушает HYPERFRAMES_PREVIEW_HOST: чужое 0.0.0.0 из окружения
        # человека выставило бы монтажный стол в сеть — движок его не наследует.
        env = engine_cli.engine_env(make_engine(Path("/tmp/hf")), {"HYPERFRAMES_PREVIEW_HOST": "0.0.0.0"})
        self.assertEqual(env["HYPERFRAMES_PREVIEW_HOST"], "127.0.0.1")
        self.assertEqual(engine_cli.engine_env(make_engine(Path("/tmp/hf")), {})["HYPERFRAMES_PREVIEW_HOST"],
                         "127.0.0.1")

    def test_ffmpeg_and_ffprobe_are_the_ones_montage_finds(self):
        # HyperFrames без HYPERFRAMES_FFMPEG_PATH/FFPROBE_PATH ищет сам — и доходит до
        # папки запуска (current/: на Windows раньше PATH, и current/.hyperframes/bin)
        inherited = {"PATH": "/usr/bin", "HYPERFRAMES_FFMPEG_PATH": "/чужой/ffmpeg",
                     "HYPERFRAMES_FFPROBE_PATH": "/чужой/ffprobe"}
        seen = []

        def find(name, *, environ):
            seen.append((name, environ.get("PATH")))
            return f"/opt/ff/bin/{name}"
        env = engine_cli.engine_env(make_engine(Path("/tmp/hf")), inherited, find=find)
        self.assertEqual((env["HYPERFRAMES_FFMPEG_PATH"], env["HYPERFRAMES_FFPROBE_PATH"]),
                         ("/opt/ff/bin/ffmpeg", "/opt/ff/bin/ffprobe"))
        self.assertEqual(seen, [("ffmpeg", "/usr/bin"), ("ffprobe", "/usr/bin")])
        missing = engine_cli.engine_env(make_engine(Path("/tmp/hf")), inherited,
                                        find=lambda name, *, environ: None)
        self.assertNotIn("HYPERFRAMES_FFMPEG_PATH", missing)  # не нашли — пусть движок откажет сам
        self.assertNotIn("HYPERFRAMES_FFPROBE_PATH", missing)

    def test_ffmpeg_paths_come_from_absolute_path_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp).resolve() / "ff bin"
            folder.mkdir()
            suffix = ".exe" if os.name == "nt" else ""
            for name in ("ffmpeg", "ffprobe"):
                (folder / f"{name}{suffix}").write_bytes(b"")
                os.chmod(folder / f"{name}{suffix}", 0o755)
            env = engine_cli.engine_env(make_engine(Path("/tmp/hf")), {"PATH": f".{os.pathsep}{folder}"})
            self.assertEqual(Path(env["HYPERFRAMES_FFMPEG_PATH"]), folder / f"ffmpeg{suffix}")
            self.assertEqual(Path(env["HYPERFRAMES_FFPROBE_PATH"]), folder / f"ffprobe{suffix}")

    def test_windows_leaves_localappdata_and_appdata_alone(self):
        """round 3/5: пробная гипотеза (LOCALAPPDATA/APPDATA переносить вместе
        с HOME) не подтвердилась прямым CI-прогоном — H2 (системный Chrome
        виснет на --version независимо от этих переменных) уже объяснял
        зависание, а не рассинхрон известных папок. Убрано (было в
        19d08a3), возвращено к исходному поведению: только HOME/USERPROFILE
        переезжают в песочницу движка, LOCALAPPDATA/APPDATA наследуются как
        есть — их и не трогаем."""

        base = Path("/tmp/hf")
        real_env = {"LOCALAPPDATA": r"C:\Users\real\AppData\Local",
                   "APPDATA": r"C:\Users\real\AppData\Roaming"}
        with mock.patch.object(engine_cli, "IS_WINDOWS", True):
            env = engine_cli.engine_env(make_engine(base, browser=False), real_env)
        self.assertEqual(env["LOCALAPPDATA"], r"C:\Users\real\AppData\Local")
        self.assertEqual(env["APPDATA"], r"C:\Users\real\AppData\Roaming")


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

    def test_every_command_carries_json(self):
        # HyperFrames 0.8.75 без --json на каждом запуске проверяет обновления
        # (registry.npmjs.org, git ls-remote github.com) — флаг добавляется
        # сам, если вызвавший его забыл, и не дублируется.
        for args, tail in ((["render", ".", "--quiet"], ["render", ".", "--quiet", "--json"]),
                           (["browser", "path"], ["browser", "path", "--json"]),
                           (["lint", ".", "--json"], ["lint", ".", "--json"])):
            self.assertEqual(engine_cli.argv_for(self.engine, args),
                             [self.engine.node, str(self.engine.script), *tail])
        run = FakeRun(stdout=b"")
        engine_cli.run_engine(self.engine, ["render", "."], cwd=self.base, timeout=5, runner=run)
        self.assertEqual(run.calls[0][0][-1], "--json")

    def test_pwd_follows_the_working_folder_not_the_caller(self):
        # HyperFrames 0.8.75 `preview .` называет проект по basename($PWD):
        # унаследованный PWD вызывающего дал бы Studio адрес чужой папки.
        run = FakeRun(stdout=b'{"ok": true}')
        with mock.patch.dict(os.environ, {"PWD": "/где-то/ещё"}):
            engine_cli.run_engine_json(self.engine, ["lint", ".", "--json"], cwd=self.base,
                                       timeout=5, runner=run)
            popen = mock.Mock()
            engine_cli.popen_engine(self.engine, ["preview", "."], cwd=self.base,
                                    log_path=self.base / "logs" / "desk.log", popen=popen)
        self.assertEqual(run.calls[0][1]["env"]["PWD"], str(self.base))
        self.assertEqual(popen.call_args.kwargs["env"]["PWD"], str(self.base))

    def test_raw_failure_text_carries_no_absolute_paths(self):
        run = FakeRun(code=1, stderr=f"cannot read {self.base}/index.html under {self.base}/node_modules"
                      .encode())
        with self.assertRaises(MontageError) as caught:
            engine_cli.run_engine_json(self.engine, ["lint", "."], cwd=self.base / "current", timeout=5,
                                       runner=run)
        self.assertNotIn(str(self.base), str(caught.exception))
        self.assertIn("<движок>/index.html", str(caught.exception).replace("\\", "/"))

    def test_refusal_json_on_stderr_becomes_message(self):
        run = FakeRun(code=2, stderr=b'{"ok": false, "reason": "#s1 would overlap #s2 at 1-6",'
                                     b' "fix": "pass --overwrite or move the named neighbour"}')
        with self.assertRaises(MontageError) as caught:
            engine_cli.run_engine_json(self.engine, ["timeline", "trim"], cwd=self.base,
                                       timeout=5, runner=run)
        self.assertIn("would overlap", str(caught.exception))
        self.assertIn("--overwrite", str(caught.exception))
        self.assertTrue(str(caught.exception).startswith(
            "HyperFrames отказал выполнить «timeline trim» — причина словами движка, по-английски: "))

    def test_node_that_does_not_start_is_russian_without_its_path(self):
        def missing(argv, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", argv[0])
        result = engine_cli.run_engine(self.engine, ["lint"], cwd=self.base, timeout=5, runner=missing)
        self.assertEqual(result.code, 127)
        self.assertIn("не удалось запустить Node.js движка", result.stderr)
        self.assertNotIn(self.engine.node, result.stderr)
        self.assertNotIn("No such file", result.stderr)

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

    def test_runner_object_run_also_delegates(self):
        sentinel = engine_cli.EngineResult(0, "ok", "", False)
        with mock.patch.object(engine_cli, "run_engine", return_value=sentinel) as fake:
            self.assertIs(engine_cli.EngineRunner().run(self.engine, ["a"], cwd=self.base,
                                                         timeout=1), sentinel)
        fake.assert_called_once()

    def test_json_payload_ignores_trailing_text_after_the_object(self):
        # raw_decode вместо loads: строка после закрывающей скобки (лишний
        # лог, перевод строки) не должна ронять разбор.
        run = FakeRun(stdout='{"ok": true}\nещё одна строка лога в конце\n'.encode("utf-8"))
        payload = engine_cli.run_engine_json(self.engine, ["timeline", "--json"],
                                             cwd=self.base, timeout=5, runner=run)
        self.assertEqual(payload, {"ok": True})


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
        # popen_engine строит свои флаги через proc_tree.group_kwargs() —
        # именно там теперь ветвление POSIX/Windows, не в engine_cli.
        log = self.base / "logs" / "desk.log"
        with mock.patch.object(proc_tree, "IS_WINDOWS", False):
            engine_cli.popen_engine(self.engine, ["preview", "."], cwd=self.base, log_path=log,
                                    popen=self.popen)
        argv, kwargs = self.calls[0]
        self.assertEqual(argv, [self.engine.node, str(self.engine.script), "preview", ".", "--json"])
        self.assertIs(kwargs["start_new_session"], True)
        self.assertNotIn("creationflags", kwargs)
        self.assertTrue(log.exists())

    def test_windows_hides_console_and_starts_a_new_group(self):
        with mock.patch.object(proc_tree, "IS_WINDOWS", True):
            engine_cli.popen_engine(self.engine, ["preview", "."], cwd=self.base,
                                    log_path=self.base / "desk.log", popen=self.popen)
        _, kwargs = self.calls[0]
        self.assertTrue(kwargs["creationflags"] & engine_cli.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(kwargs["creationflags"] & engine_cli.CREATE_NO_WINDOW)
        self.assertNotIn("start_new_session", kwargs)

    def test_oserror_becomes_montage_error(self):
        def failing_popen(argv, **kwargs):
            raise OSError("node не найден")
        with self.assertRaises(MontageError) as caught:
            engine_cli.popen_engine(self.engine, ["preview", "."], cwd=self.base,
                                    log_path=self.base / "desk.log", popen=failing_popen)
        self.assertIn("не удалось запустить", str(caught.exception))


class FakePopen:
    """Имитирует subprocess.Popen: первый communicate() — таймаут, и, как у
    настоящего Popen, TimeoutExpired уже несёт то, что процесс успел
    накопить (проверено эмпирически — см. отчёт); второй communicate()
    (только для ветки Windows в default_runner) отдаёт то же самое."""

    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.pid = 777
        self.returncode = None
        self.waited = False
        self._calls = 0

    def communicate(self, timeout=None):
        self._calls += 1
        if self._calls == 1:
            raise subprocess.TimeoutExpired(self.argv, timeout, output=b"partial-out",
                                            stderr=b"partial-err")
        self.returncode = -9
        return b"partial-out", b"partial-err"

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.waited = True
        self.returncode = -9
        return self.returncode


class RaisingPopen:
    """communicate() бросает не TimeoutExpired, а что угодно другое — так
    выглядит Ctrl+C (KeyboardInterrupt) во время ожидания HyperFrames."""

    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.pid = 888
        self.returncode = None
        self.waited = False

    def communicate(self, timeout=None):
        raise KeyboardInterrupt

    def wait(self, timeout=None):
        self.waited = True
        self.returncode = -15
        return self.returncode


class ImmediatePopen:
    """Завершается сразу — для проверки штатного (без таймаута) пути."""

    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.pid = 555
        self.returncode = 0

    def communicate(self, timeout=None):
        return b'{"ok": true}', b""


class DefaultRunnerTests(unittest.TestCase):
    """default_runner — то, что run_engine/run_engine_json используют по
    умолчанию вместо голого subprocess.run. Сама механика убийства дерева
    (killpg/kill/taskkill, обход потомков) теперь в studio.montage.proc_tree
    и проверена отдельно в test_montage_proc_tree.py; здесь проверяется
    именно оркестровка default_runner: он зовёт kill_tree, по-разному
    дренирует пайпы на POSIX/Windows и не глотает BaseException."""

    def test_success_path_returns_completed_process(self):
        result = engine_cli.default_runner(
            ["node", "x"], cwd="/tmp", env={}, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, popen=ImmediatePopen)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'{"ok": true}')

    def test_posix_timeout_calls_kill_tree_and_does_not_read_pipes_twice(self):
        created = []

        def make(argv, **kwargs):
            instance = FakePopen(argv, **kwargs)
            created.append(instance)
            return instance

        with mock.patch.object(engine_cli, "IS_WINDOWS", False), \
                mock.patch.object(engine_cli, "kill_tree") as fake_kill:
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                engine_cli.default_runner(
                    ["node", "x"], cwd="/tmp", env={}, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1, popen=make)
        fake_kill.assert_called_once_with(created[0])
        # второй communicate() без таймаута на POSIX небезопасен (см. docstring
        # default_runner) — партийные данные берём из первого TimeoutExpired
        self.assertEqual(created[0]._calls, 1)
        self.assertTrue(created[0].waited)
        self.assertEqual(caught.exception.output, b"partial-out")
        self.assertEqual(caught.exception.stderr, b"partial-err")

    def test_windows_timeout_calls_kill_tree_then_drains_a_second_communicate(self):
        created = []

        def make(argv, **kwargs):
            instance = FakePopen(argv, **kwargs)
            created.append(instance)
            return instance

        with mock.patch.object(engine_cli, "IS_WINDOWS", True), \
                mock.patch.object(engine_cli, "kill_tree") as fake_kill:
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                engine_cli.default_runner(
                    ["node", "x"], cwd="/tmp", env={}, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1, popen=make)
        fake_kill.assert_called_once_with(created[0])
        self.assertEqual(created[0]._calls, 2)  # taskkill /T /F синхронный — дочитать безопасно
        self.assertEqual(caught.exception.output, b"partial-out")
        self.assertEqual(caught.exception.stderr, b"partial-err")

    def test_base_exception_kills_the_tree_and_reraises(self):
        created = []

        def make(argv, **kwargs):
            instance = RaisingPopen(argv, **kwargs)
            created.append(instance)
            return instance

        with mock.patch.object(engine_cli, "kill_tree") as fake_kill:
            with self.assertRaises(KeyboardInterrupt):
                engine_cli.default_runner(
                    ["node", "x"], cwd="/tmp", env={}, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, popen=make)
        fake_kill.assert_called_once_with(created[0])
        self.assertTrue(created[0].waited)

    def test_run_engine_reports_partial_output_and_the_timeout_reason(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(base, ignore_errors=True))
        fake_engine = make_engine(base)
        runner = lambda argv, **kwargs: engine_cli.default_runner(argv, popen=FakePopen, **kwargs)  # noqa: E731
        with mock.patch.object(engine_cli, "IS_WINDOWS", False), \
                mock.patch.object(engine_cli, "kill_tree"):
            result = engine_cli.run_engine(fake_engine, ["render"], cwd=base, timeout=1,
                                           runner=runner)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.stdout, "partial-out")
        # частичный вывод сохранён, и причина по-прежнему в сообщении
        self.assertIn("partial-err", result.stderr)
        self.assertIn("не завершился за 1 с", result.stderr)


_FAKE_NODE = """
import json
import os
import subprocess
import sys
import time

pid_file = sys.argv[1]
# start_new_session=True — как puppeteer/Chrome на POSIX с puppeteer-core
# ^25 (detached=true по умолчанию не на Windows): внук сидит в СВОЕЙ,
# отдельной от node, группе процессов.
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                         start_new_session=True)
with open(pid_file, "w", encoding="utf-8") as handle:
    json.dump({"node": os.getpid(), "child": child.pid}, handle)
    handle.flush()
    os.fsync(handle.fileno())
time.sleep(20)
"""


class RealTimeoutKillsTreeTests(unittest.TestCase):
    """Настоящий узел процессов через полный run_engine (не только
    proc_tree.kill_tree изолированно, как в test_montage_proc_tree.py):
    node (тут — python-заглушка) сам порождает ребёнка в СВОЕЙ сессии — как
    HyperFrames порождает Chrome. По таймауту должны погибнуть оба."""

    def _wait_for_pid_file(self, pid_file: Path, timeout=10.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pid_file.exists():
                try:
                    return json.loads(pid_file.read_text(encoding="utf-8"))
                except ValueError:
                    pass
            time.sleep(0.05)
        raise AssertionError(f"{pid_file} не появился за {timeout:g} с")

    def test_posix_timeout_kills_node_and_its_detached_child(self):
        # hasattr, а не os.name == "nt": именно эти два имени использует
        # proc_tree.kill_tree на POSIX-ветке, и это ровно то, чего не будет
        # на Windows — проверено прогоном сюиты с искусственно вырезанными
        # os.killpg/signal.SIGKILL (см. отчёт).
        if not (hasattr(os, "killpg") and hasattr(signal, "SIGKILL")):
            self.skipTest("процессная группа POSIX — на Windows своя ветка, см. DefaultRunnerTests")
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            script = base / "fake_node.py"
            script.write_text(_FAKE_NODE, encoding="utf-8")
            pid_file = base / "pids.json"
            fake_engine = engine.Engine(node=sys.executable, script=script, prefix=base,
                                        version="0.8.75", browser=None)
            result = engine_cli.run_engine(fake_engine, [str(pid_file)], cwd=base, timeout=2)
            self.assertTrue(result.timed_out)
            pids = self._wait_for_pid_file(pid_file)
            deadline = time.monotonic() + 5
            alive = dict(pids)
            while alive and time.monotonic() < deadline:
                for label, pid in list(alive.items()):
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        del alive[label]
                if alive:
                    time.sleep(0.05)
            self.assertEqual(alive, {}, f"эти процессы всё ещё живы: {alive}")


if __name__ == "__main__":
    unittest.main()

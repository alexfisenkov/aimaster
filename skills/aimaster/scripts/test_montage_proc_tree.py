#!/usr/bin/env python3
"""Обход дерева потомков node и остановка всего узла — POSIX и Windows.

На POSIX смешиваем настоящие процессы (там, где важно доказать, что реально
работает killpg/kill) и подмену os.killpg/os.kill (там, где важен только
порядок вызовов — SIGTERM всем, пауза, SIGKILL уцелевшим). Тесты, которые
трогают os.killpg или signal.SIGKILL напрямую, пропускаются там, где этих
атрибутов нет (Windows) — иначе mock.patch.object падает с AttributeError
раньше, чем успевает подменить."""

from __future__ import annotations

import os
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

from studio.montage import proc_tree  # noqa: E402

_POSIX_SIGNALS = hasattr(os, "killpg") and hasattr(signal, "SIGKILL")


class GroupKwargsTests(unittest.TestCase):
    def test_windows_uses_creationflags(self):
        with mock.patch.object(proc_tree, "IS_WINDOWS", True):
            kwargs = proc_tree.group_kwargs()
        self.assertEqual(kwargs, {"creationflags":
                                  proc_tree.CREATE_NEW_PROCESS_GROUP | proc_tree.CREATE_NO_WINDOW})

    def test_posix_uses_start_new_session(self):
        with mock.patch.object(proc_tree, "IS_WINDOWS", False):
            kwargs = proc_tree.group_kwargs()
        self.assertEqual(kwargs, {"start_new_session": True})


class DescendantsTests(unittest.TestCase):
    def test_parses_ps_output_into_a_transitive_child_list(self):
        # 100 — наш "node"; 200/201 — прямые дети; 300 — внук через 200;
        # 999 — посторонний процесс с тем же ppid=1, что и node, не потомок.
        ps_output = "1 0\n100 1\n200 100\n201 100\n300 200\n999 1\n"

        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, ps_output, "")

        found = proc_tree._descendants(100, run=fake_run)
        self.assertEqual(set(found), {200, 201, 300})
        self.assertNotIn(999, found)
        self.assertNotIn(100, found)

    def test_ps_failure_returns_empty_list_not_a_crash(self):
        def failing_run(argv, **kwargs):
            raise OSError("ps не найден")
        self.assertEqual(proc_tree._descendants(100, run=failing_run), [])

    def test_garbage_lines_are_skipped(self):
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, "junk line\n100 1\n200 100\n", "")
        self.assertEqual(proc_tree._descendants(100, run=fake_run), [200])


@unittest.skipUnless(_POSIX_SIGNALS, "проверка сигналов POSIX (killpg/SIGKILL)")
class KillTreePosixSequencingTests(unittest.TestCase):
    """Порядок важен: сперва SIGTERM всем (дать шанс на штатное закрытие,
    как это обычно делает Ctrl+C), затем — если кто-то пережил паузу —
    SIGKILL. Процесс здесь подставной: poll() сразу говорит "уже мёртв",
    чтобы тест не ждал реальную паузу GRACE_SECONDS."""

    def test_sigterm_first_then_grace_then_sigkill_survivors(self):
        calls = []
        fake_proc = mock.Mock(pid=100)
        fake_proc.poll.return_value = 0
        with mock.patch.object(proc_tree, "IS_WINDOWS", False), \
                mock.patch.object(proc_tree, "_descendants", return_value=[201, 202]), \
                mock.patch.object(proc_tree, "process_started", return_value="ps:1"), \
                mock.patch.object(proc_tree.os, "killpg",
                                  side_effect=lambda pid, sig: calls.append(("group", pid, sig))), \
                mock.patch.object(proc_tree.os, "kill",
                                  side_effect=lambda pid, sig: calls.append(("pid", pid, sig))):
            proc_tree.kill_tree(fake_proc)
        term = [c for c in calls if c[2] == signal.SIGTERM]
        kill = [c for c in calls if c[2] == signal.SIGKILL]
        self.assertEqual(term, [("group", 100, signal.SIGTERM), ("pid", 201, signal.SIGTERM),
                                ("pid", 202, signal.SIGTERM)])
        self.assertEqual(kill, [("group", 100, signal.SIGKILL), ("pid", 201, signal.SIGKILL),
                                ("pid", 202, signal.SIGKILL)])
        # SIGTERM целиком раньше любого SIGKILL — не вперемешку
        self.assertLess(calls.index(term[-1]), calls.index(kill[0]))

    def test_a_reused_pid_never_gets_sigkill(self):
        """За паузу потомок 202 завершился, а ОС отдала его номер чужому
        процессу (другое время запуска); 203 исчез ещё до SIGTERM."""

        calls = []
        started = {201: iter(["t201", "t201"]), 202: iter(["t202", "чужой"]), 203: iter([None])}
        fake_proc = mock.Mock(pid=100)
        fake_proc.poll.return_value = 0
        with mock.patch.object(proc_tree, "IS_WINDOWS", False), \
                mock.patch.object(proc_tree, "_descendants", return_value=[201, 202, 203]), \
                mock.patch.object(proc_tree, "process_started", side_effect=lambda pid: next(started[pid])), \
                mock.patch.object(proc_tree.os, "killpg"), \
                mock.patch.object(proc_tree.os, "kill",
                                  side_effect=lambda pid, sig: calls.append((pid, sig))):
            proc_tree.kill_tree(fake_proc)
        self.assertEqual(calls, [(201, signal.SIGTERM), (202, signal.SIGTERM), (201, signal.SIGKILL)])

    def test_foreign_process_that_refuses_signals_does_not_stop_the_kill(self):
        fake_proc = mock.Mock(pid=100)
        fake_proc.poll.return_value = 0
        with mock.patch.object(proc_tree, "IS_WINDOWS", False), \
                mock.patch.object(proc_tree, "_descendants", return_value=[201]), \
                mock.patch.object(proc_tree, "process_started", return_value="t"), \
                mock.patch.object(proc_tree.os, "killpg", side_effect=PermissionError), \
                mock.patch.object(proc_tree.os, "kill", side_effect=PermissionError) as kill:
            proc_tree.kill_tree(fake_proc)
        self.assertEqual(kill.call_count, 2)  # SIGTERM и SIGKILL — оба дошли до вызова

    def test_already_dead_pid_does_not_raise(self):
        fake_proc = mock.Mock(pid=100)
        fake_proc.poll.return_value = 0
        with mock.patch.object(proc_tree, "IS_WINDOWS", False), \
                mock.patch.object(proc_tree, "_descendants", return_value=[]), \
                mock.patch.object(proc_tree.os, "killpg", side_effect=ProcessLookupError), \
                mock.patch.object(proc_tree.os, "kill", side_effect=ProcessLookupError):
            proc_tree.kill_tree(fake_proc)  # не должно бросить исключение

    def test_waits_up_to_grace_period_for_node_to_exit_on_its_own(self):
        fake_proc = mock.Mock(pid=100)
        # первые два опроса — ещё жив, третий — уже нет
        fake_proc.poll.side_effect = [None, None, 0]
        with mock.patch.object(proc_tree, "IS_WINDOWS", False), \
                mock.patch.object(proc_tree, "_descendants", return_value=[]), \
                mock.patch.object(proc_tree.os, "killpg"), \
                mock.patch.object(proc_tree.os, "kill"), \
                mock.patch.object(proc_tree.time, "sleep") as fake_sleep:
            proc_tree.kill_tree(fake_proc)
        self.assertGreaterEqual(fake_sleep.call_count, 2)


class KillTreeWindowsTests(unittest.TestCase):
    def test_uses_taskkill_tree_force_with_system32_path_no_window_and_timeout(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        fake_proc = mock.Mock(pid=4242)
        with mock.patch.object(proc_tree, "IS_WINDOWS", True), \
                mock.patch.object(subprocess, "run", fake_run):
            proc_tree.kill_tree(fake_proc)
        argv, kwargs = calls[0]
        self.assertEqual(argv[0], proc_tree._taskkill_path())
        self.assertEqual(argv[1:], ["/T", "/F", "/PID", "4242"])
        self.assertEqual(kwargs["creationflags"], proc_tree.CREATE_NO_WINDOW)
        self.assertEqual(kwargs["timeout"], proc_tree.TASKKILL_TIMEOUT)

    def test_taskkill_failure_does_not_raise(self):
        def failing_run(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, proc_tree.TASKKILL_TIMEOUT)

        fake_proc = mock.Mock(pid=1)
        with mock.patch.object(proc_tree, "IS_WINDOWS", True), \
                mock.patch.object(subprocess, "run", failing_run):
            proc_tree.kill_tree(fake_proc)  # не должно бросить исключение


@unittest.skipUnless(_POSIX_SIGNALS, "проверка сигналов POSIX (killpg/SIGKILL)")
class RealDetachedGrandchildTests(unittest.TestCase):
    """Доказательство самой находки: puppeteer/Chrome на POSIX запускает
    себя лидером СВОЕЙ сессии (start_new_session=True), а не остаётся в
    группе node. killpg по группе node его не достаёт — нужен обход дерева
    потомков. Старый код (killpg(node_pgid) в одиночку) это доказуемо не
    ловит; kill_tree — ловит."""

    _SCRIPT = """
import json, os, subprocess, sys, time
pid_file = sys.argv[1]
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
                         start_new_session=True)
with open(pid_file, "w", encoding="utf-8") as handle:
    json.dump({"node": os.getpid(), "child": child.pid}, handle)
    handle.flush()
    os.fsync(handle.fileno())
time.sleep(20)
"""

    def _spawn(self, base: Path) -> tuple[subprocess.Popen, Path]:
        script = base / "fake_node.py"
        script.write_text(self._SCRIPT, encoding="utf-8")
        pid_file = base / "pids.json"
        proc = subprocess.Popen([sys.executable, str(script), str(pid_file)],
                                start_new_session=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return proc, pid_file

    def _wait_for_pid_file(self, pid_file: Path, timeout=10.0) -> dict:
        import json
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pid_file.exists():
                try:
                    return json.loads(pid_file.read_text(encoding="utf-8"))
                except ValueError:
                    pass
            time.sleep(0.05)
        raise AssertionError(f"{pid_file} не появился за {timeout:g} с")

    def _assert_all_dead(self, pids: dict, timeout=5.0) -> None:
        deadline = time.monotonic() + timeout
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

    def test_old_killpg_only_leaves_the_detached_grandchild_alive(self):
        # Контрольный замер: воспроизводим ИМЕННО ту находку, которую чинит
        # kill_tree, — чтобы падение теста здесь означало, что ffmpeg/ОС
        # изменили поведение, а не что тест бесполезен.
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            proc, pid_file = self._spawn(base)
            try:
                proc.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                proc.stdout.close()
                proc.stderr.close()
            pids = self._wait_for_pid_file(pid_file)
            time.sleep(0.3)
            child_alive = True
            try:
                os.kill(pids["child"], 0)
            except ProcessLookupError:
                child_alive = False
            finally:
                for pid in pids.values():
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            self.assertTrue(child_alive, "контрольный замер сломался: старый способ "
                                        "неожиданно убил внука — находка более не воспроизводима")

    def test_kill_tree_kills_node_and_its_detached_grandchild(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            proc, pid_file = self._spawn(base)
            try:
                proc.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                proc_tree.kill_tree(proc)
                proc.wait()
                proc.stdout.close()
                proc.stderr.close()
            pids = self._wait_for_pid_file(pid_file)
            self._assert_all_dead(pids)


if __name__ == "__main__":
    unittest.main()

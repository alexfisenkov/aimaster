#!/usr/bin/env python3
"""«Показать в папке»: полный путь к программе, без оболочки; Проводнику —
готовая строка с /select, и код 1 — не ошибка."""

from __future__ import annotations

import subprocess
import sys
import time
import unittest
from pathlib import Path, PurePosixPath, PureWindowsPath

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from studio.montage import MontageError  # noqa: E402
from studio.reveal import MAC_OPEN, reveal_available, reveal_command, reveal_file  # noqa: E402

MAC_FILE = PurePosixPath("/Users/А Б/рабочая папка/media/p/montage/v001.mp4")
WIN_FILE = PureWindowsPath(r"C:\Users\А Б\рабочая папка\media\p\montage\v001.mp4")
LINUX_FILE = PurePosixPath("/home/а б/рабочая папка/media/p/montage/v001.mp4")


def xdg(name, environ):
    return "/usr/bin/xdg-open" if name == "xdg-open" else None


class RevealCommandTests(unittest.TestCase):
    def test_finder_selects_the_file(self):
        self.assertEqual(reveal_command(MAC_FILE, system="mac", environ={}, is_file=lambda path: path == MAC_OPEN),
                         ["/usr/bin/open", "-R", str(MAC_FILE)])

    def test_explorer_gets_one_command_line_with_select(self):
        command = reveal_command(WIN_FILE, system="windows", environ={"SystemRoot": r"C:\Windows"},
                                 is_file=lambda path: True)
        self.assertEqual(command, '"C:\\Windows\\explorer.exe" /select,'
                                  '"C:\\Users\\А Б\\рабочая папка\\media\\p\\montage\\v001.mp4"')

    def test_windir_is_used_when_system_root_is_missing(self):
        command = reveal_command(WIN_FILE, system="windows", environ={"windir": r"D:\Win"}, is_file=lambda path: True)
        self.assertTrue(command.startswith('"D:\\Win\\explorer.exe" /select,"'))

    def test_system_root_is_found_in_any_letter_case(self):
        for name in ("SYSTEMROOT", "systemroot", "WINDIR"):
            with self.subTest(name=name):
                command = reveal_command(WIN_FILE, system="windows", environ={name: r"E:\Win"},
                                         is_file=lambda path: True)
                self.assertTrue(command.startswith('"E:\\Win\\explorer.exe" /select,"'))

    def test_explorer_needs_an_absolute_system_root(self):
        for environ in ({}, {"SystemRoot": "Windows"}):
            with self.subTest(environ=environ):
                self.assertIsNone(reveal_command(WIN_FILE, system="windows", environ=environ,
                                                 is_file=lambda path: True))

    def test_linux_opens_the_folder_with_xdg_open_from_path(self):
        self.assertEqual(reveal_command(LINUX_FILE, system="linux", environ={"PATH": "/usr/bin"}, find=xdg),
                         ["/usr/bin/xdg-open", "/home/а б/рабочая папка/media/p/montage"])

    def test_no_program_means_no_command(self):
        self.assertIsNone(reveal_command(MAC_FILE, system="mac", environ={}, is_file=lambda path: False))
        self.assertIsNone(reveal_command(LINUX_FILE, system="linux", environ={}, find=lambda name, environ: None))

    def test_available_follows_the_command(self):
        self.assertTrue(reveal_available(system="mac", environ={}, is_file=lambda path: True))
        self.assertFalse(reveal_available(system="linux", environ={}, find=lambda name, environ: None))


class RevealFileTests(unittest.TestCase):
    def runner(self, returncode=0, error=None):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            if error is not None:
                raise error
            return subprocess.CompletedProcess(command, returncode)
        return calls, run

    def test_argv_list_without_shell_and_with_a_timeout(self):
        calls, run = self.runner()
        reveal_file(MAC_FILE, system="mac", environ={}, run=run, is_file=lambda path: True)
        command, kwargs = calls[0]
        self.assertEqual(command, ["/usr/bin/open", "-R", str(MAC_FILE)])
        self.assertNotIn("shell", kwargs)
        self.assertEqual((kwargs["timeout"], kwargs["stdin"], kwargs["check"]), (15, subprocess.DEVNULL, False))

    def test_explorer_code_one_is_success(self):
        calls, run = self.runner(returncode=1)
        reveal_file(WIN_FILE, system="windows", environ={"SystemRoot": r"C:\Windows"}, run=run,
                    is_file=lambda path: True)
        self.assertIsInstance(calls[0][0], str)

    def test_finder_failure_is_a_refusal(self):
        _calls, run = self.runner(returncode=1)
        with self.assertRaisesRegex(MontageError, "не удалось открыть папку"):
            reveal_file(MAC_FILE, system="mac", environ={}, run=run, is_file=lambda path: True)

    def test_timeout_is_a_refusal(self):
        _calls, run = self.runner(error=subprocess.TimeoutExpired(cmd="open", timeout=15))
        with self.assertRaisesRegex(MontageError, "не удалось открыть папку"):
            reveal_file(MAC_FILE, system="mac", environ={}, run=run, is_file=lambda path: True)

    def detached(self, *, code=0, running=False, error=None):
        calls = []

        class Process:
            def __init__(self):
                self.waits = []

            def wait(self, timeout=None):
                self.waits.append(timeout)
                if running and timeout is not None:
                    raise subprocess.TimeoutExpired(cmd="xdg-open", timeout=timeout)
                return code

        def popen(command, **kwargs):
            calls.append((command, kwargs))
            if error is not None:
                raise error
            calls.append(Process())
            return calls[-1]
        return calls, popen

    def reveal_linux(self, popen):
        reveal_file(LINUX_FILE, system="linux", environ={"PATH": "/usr/bin"}, find=xdg, popen=popen,
                    run=lambda *args, **kwargs: self.fail("xdg-open не ждут через run"), wait=0.01)

    def test_xdg_open_runs_in_its_own_session_without_shell(self):
        calls, popen = self.detached()
        self.reveal_linux(popen)
        command, kwargs = calls[0]
        self.assertEqual(command, ["/usr/bin/xdg-open", "/home/а б/рабочая папка/media/p/montage"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual((kwargs["start_new_session"], kwargs["stdin"]), (True, subprocess.DEVNULL))

    def test_file_manager_still_open_is_success(self):
        calls, popen = self.detached(running=True)
        self.reveal_linux(popen)  # не ждёт закрытия окна и не убивает его
        process = calls[1]
        for _ in range(100):
            if None in process.waits:
                break
            time.sleep(0.01)
        self.assertEqual(process.waits, [0.01, None])  # фоновый поток приберёт процесс

    def test_xdg_open_failure_is_a_refusal(self):
        for kwargs in ({"code": 4}, {"error": OSError("нет")}):
            with self.subTest(**{key: str(value) for key, value in kwargs.items()}):
                _calls, popen = self.detached(**kwargs)
                with self.assertRaisesRegex(MontageError, "не удалось открыть папку"):
                    self.reveal_linux(popen)

    def test_missing_program_is_named(self):
        _calls, run = self.runner()
        with self.assertRaisesRegex(MontageError, "xdg-open"):
            reveal_file(LINUX_FILE, system="linux", environ={}, run=run, find=lambda name, environ: None)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""The OS layer behaves the same on macOS, Linux and Windows.

Every test here runs on all three; where the mechanism differs (flock or
msvcrt, mode bits or an ACL) the observable contract is what is checked.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from studio import platform_compat as compat  # noqa: E402

_HOLD_SECONDS = 1.0
_LOCK_HOLDER = """
import sys, time
sys.path.insert(0, sys.argv[1])
from studio.platform_compat import file_lock
with open(sys.argv[2], "a+b") as handle, file_lock(handle):
    print("locked", flush=True)
    time.sleep(float(sys.argv[3]))
"""


def _child_env(**extra):
    environment = dict(os.environ)
    environment.update(extra)
    return environment


class FileLockTests(unittest.TestCase):
    def test_second_process_waits_until_the_first_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / ".state.lock"
            holder = subprocess.Popen(
                [sys.executable, "-c", _LOCK_HOLDER, str(_SKILL_ROOT), str(lock_path), str(_HOLD_SECONDS)],
                stdout=subprocess.PIPE, encoding="utf-8", errors="replace",
            )
            try:
                self.assertEqual(holder.stdout.readline().strip(), "locked")
                started = time.monotonic()
                with open(lock_path, "a+b") as handle, compat.file_lock(handle):
                    waited = time.monotonic() - started
                self.assertGreater(waited, _HOLD_SECONDS / 2)
            finally:
                holder.stdout.close()
                holder.wait(timeout=30)
            self.assertEqual(holder.returncode, 0)

    def test_lock_is_released_so_it_can_be_taken_again(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / ".lock"
            for _ in range(3):
                descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
                with os.fdopen(descriptor, "a+b") as handle, compat.file_lock(handle.fileno()):
                    pass


class PrivacyTests(unittest.TestCase):
    def test_make_private_restricts_a_file_and_a_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "private"
            folder.mkdir()
            secret = folder / "token"
            secret.write_text("x\n", encoding="utf-8")
            compat.make_private(folder, directory=True)
            compat.make_private(secret)
            self.assertTrue(compat.is_private(folder, directory=True))
            self.assertTrue(compat.is_private(secret))
            self.assertTrue(compat.ensure_private(secret))
            self.assertEqual(secret.read_text(encoding="utf-8"), "x\n")

    @unittest.skipIf(os.name == "nt", "mode bits are POSIX-only")
    def test_world_readable_file_is_not_private_on_posix(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "token"
            secret.write_text("x", encoding="utf-8")
            os.chmod(secret, 0o644)
            self.assertFalse(compat.is_private(secret))
            compat.make_private(secret)
            self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "nt", "Windows ACL check")
    def test_file_granted_to_everyone_is_not_private_on_windows(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "token"
            secret.write_text("x", encoding="utf-8")
            subprocess.run(["icacls", str(secret), "/grant", "*S-1-1-0:(R)"],
                           capture_output=True, check=True)
            self.assertFalse(compat.is_private(secret))
            compat.make_private(secret)
            self.assertTrue(compat.is_private(secret))


class FilesystemTests(unittest.TestCase):
    def test_replace_and_directory_fsync(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            target.write_text("old", encoding="utf-8")
            source = Path(directory) / "state.json.tmp"
            source.write_text("new", encoding="utf-8")
            compat.replace_file(source, target)
            compat.fsync_directory(directory)
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertFalse(source.exists())

    def test_open_nofollow_creates_a_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yml"
            os.close(compat.open_nofollow(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC))
            self.assertTrue(path.is_file())

    def test_open_nofollow_refuses_a_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "real"
            target.write_text("", encoding="utf-8")
            link = Path(directory) / "link"
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("this account cannot create symlinks")
            with self.assertRaises(OSError):
                os.close(compat.open_nofollow(link, os.O_WRONLY | os.O_CREAT | os.O_TRUNC))


class UserDirectoryTests(unittest.TestCase):
    def test_directories_follow_each_platform_convention(self):
        home = Path(tempfile.gettempdir()) / "home"
        data = compat.user_data_dir(home=home, environ={})
        config = compat.user_config_dir(home=home, environ={})
        if sys.platform == "darwin":
            self.assertEqual(data, home / "Library" / "Application Support" / "AI Мастерская")
            self.assertEqual(config, home / ".config" / "aimaster")
        elif os.name == "nt":
            self.assertEqual(data, home / "AppData" / "Local" / "AI Мастерская")
            self.assertEqual(config, home / "AppData" / "Roaming" / "aimaster")
        else:
            self.assertEqual(data, home / ".local" / "share" / "aimaster")
            self.assertEqual(config, home / ".config" / "aimaster")

    def test_environment_overrides_are_honoured_only_when_absolute(self):
        home = Path(tempfile.gettempdir()) / "home"
        base = Path(tempfile.gettempdir()) / "elsewhere"
        variables = {"LOCALAPPDATA": str(base), "APPDATA": str(base),
                     "XDG_DATA_HOME": str(base), "XDG_CONFIG_HOME": str(base)}
        config = compat.user_config_dir(home=home, environ=variables)
        self.assertEqual(config, base / "aimaster")
        relative = compat.user_config_dir(home=home, environ={"XDG_CONFIG_HOME": "rel", "APPDATA": "rel"})
        self.assertTrue(relative.is_relative_to(home))


class Utf8StdioTests(unittest.TestCase):
    def test_cyrillic_prints_on_a_legacy_console_encoding(self):
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from studio.platform_compat import ensure_utf8_stdio;"
            "ensure_utf8_stdio(); print('Готово ✓'); print('Ошибка ✓', file=sys.stderr)"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, str(_SKILL_ROOT)],
            capture_output=True, env=_child_env(PYTHONIOENCODING="cp1251", PYTHONUTF8="0"),
            timeout=60, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout.decode("utf-8").strip(), "Готово ✓")
        self.assertEqual(result.stderr.decode("utf-8").strip(), "Ошибка ✓")

    def test_streams_without_reconfigure_are_left_alone(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            compat.ensure_utf8_stdio()
            print("текст")
        self.assertEqual(out.getvalue(), "текст\n")



class FindProgramTests(unittest.TestCase):
    """find_program должен видеть то же, что install.py: псевдонимы
    WindowsApps (реализованные через reparse points/broken symlinks) и
    ярлыки в WinGet Links, когда программы ещё нет на PATH."""

    def test_broken_link_counts_as_present_on_windows_like_a_winget_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp).resolve()
            alias = folder / "ffmpeg.exe"
            try:
                os.symlink(folder / "nowhere.exe", alias)
            except (OSError, NotImplementedError):
                self.skipTest("this account cannot create symlinks")
            # Сперва убеждаемся, что фикстура действительно воспроизводит
            # ситуацию WindowsApps: isfile видит битую ссылку как отсутствие
            # файла, lexists — как присутствие.
            self.assertFalse(os.path.isfile(alias))
            self.assertTrue(os.path.lexists(alias))
            with mock.patch.object(compat, "IS_WINDOWS", True):
                self.assertEqual(compat.find_program("ffmpeg", environ={"PATH": str(folder)}),
                                 str(alias))

    def test_a_directory_shaped_like_the_name_is_not_a_program(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp).resolve()
            (folder / "ffmpeg.exe").mkdir()
            with mock.patch.object(compat, "IS_WINDOWS", True):
                self.assertIsNone(compat.find_program("ffmpeg", environ={"PATH": str(folder)}))

    def test_winget_links_fallback_when_not_on_path(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            links = base / "Microsoft" / "WinGet" / "Links"
            links.mkdir(parents=True)
            target = links / "ffmpeg.exe"
            target.write_text("", encoding="utf-8")
            env = {"PATH": "", "LOCALAPPDATA": str(base)}
            with mock.patch.object(compat, "IS_WINDOWS", True):
                self.assertEqual(compat.find_program("ffmpeg", environ=env), str(target))

    def test_path_match_wins_over_winget_links(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            on_path = base / "bin"
            on_path.mkdir()
            (on_path / "ffmpeg.exe").write_text("", encoding="utf-8")
            links = base / "Microsoft" / "WinGet" / "Links"
            links.mkdir(parents=True)
            (links / "ffmpeg.exe").write_text("", encoding="utf-8")
            env = {"PATH": str(on_path), "LOCALAPPDATA": str(base)}
            with mock.patch.object(compat, "IS_WINDOWS", True):
                self.assertEqual(compat.find_program("ffmpeg", environ=env),
                                 str(on_path / "ffmpeg.exe"))

    def test_winget_links_fallback_only_applies_on_windows(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp).resolve()
            links = base / "Microsoft" / "WinGet" / "Links"
            links.mkdir(parents=True)
            (links / "ffmpeg.exe").write_text("", encoding="utf-8")
            env = {"PATH": "", "LOCALAPPDATA": str(base)}
            with mock.patch.object(compat, "IS_WINDOWS", False):
                self.assertIsNone(compat.find_program("ffmpeg", environ=env))

    def test_missing_localappdata_does_not_crash(self):
        with mock.patch.object(compat, "IS_WINDOWS", True):
            self.assertIsNone(compat.find_program("ffmpeg", environ={"PATH": ""}))


class WindowsPathGuardTests(unittest.TestCase):
    """Backslash and drive tricks never escape the static root, on any OS."""

    def test_static_resolver_refuses_windows_style_escapes(self):
        from studio.http_app import _resolve_static

        self.assertIsNotNone(_resolve_static("index.html"))
        for attempt in ("..\\..\\README.md", "ui\\..\\..\\x", "C:\\Windows\\win.ini",
                        "C:/Windows/win.ini", "C:index.html", "index.html::$DATA",
                        "../index.html", "/etc/passwd", "index.html\x00"):
            with self.subTest(attempt=attempt):
                self.assertIsNone(_resolve_static(attempt))

    def test_http_app_answers_404_to_encoded_windows_traversal(self):
        from studio.http_app import _resolve_static

        from urllib.parse import unquote

        for raw in ("..%5C..%5CREADME.md", "C%3A%5CWindows%5Cwin.ini", "%2E%2E%5Cx"):
            with self.subTest(raw=raw):
                self.assertIsNone(_resolve_static(unquote(raw)))


if __name__ == "__main__":
    unittest.main()

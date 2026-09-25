#!/usr/bin/env python3
"""round 2/5 → 4/5: chrome-headless-shell для Windows напрямую, в обход
штатной распаковки @puppeteer/browsers на не-ASCII пути
(install_montage_browser_win): версия, пути, атомарная распаковка, отказы
сети/архива/диска не бросают исключений, срок скачивания, уборка, протухшая
итоговая папка, параллельная установка, повтор переименования."""

from __future__ import annotations

import http.client
import io
import os
import sys
import tempfile
import time
import unittest
import urllib.error
import zipfile
import zlib
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import install_montage_browser_win as win  # noqa: E402
from studio import platform_compat  # noqa: E402

VERSION = "152.0.7977.30"

# Реальный дефолтный путь движка на Windows: кириллица и пробел
# (studio.platform_compat.user_data_dir) — round 2/5 требует проверить
# именно на таком префиксе, не на упрощённом ASCII.
CYRILLIC_PREFIX_NAME = "AI Мастерская"


def temp_base(test) -> Path:
    temp = tempfile.TemporaryDirectory()
    test.addCleanup(temp.cleanup)
    return Path(temp.name).resolve()


def write_pinned_cli_js(prefix: Path, version: str, *, macos_first=False) -> None:
    cli_js = prefix / "node_modules" / "hyperframes" / "dist" / "cli.js"
    cli_js.parent.mkdir(parents=True, exist_ok=True)
    lines = ['CHROME_VERSION = "%s";' % version,
             'MACOS_12_CHROME_VERSION = "150.0.7871.124";']
    if macos_first:
        lines.reverse()
    cli_js.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fake_zip_bytes(inner_name: str, content: bytes) -> bytes:
    """Собирает .zip с одним файлом внутри — как настоящий
    chrome-headless-shell-win64.zip: верхняя папка
    chrome-headless-shell-win64/, внутри исполняемый файл."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"chrome-headless-shell-win64/{inner_name}", content)
    return buffer.getvalue()


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def leftovers(prefix: Path) -> list[str]:
    parent = win.cache_target(prefix, VERSION).parent
    return [p.name for p in parent.iterdir() if p.name.startswith(win.EXTRACT_TEMP_PREFIX)]


class OpenerFactory:
    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def returning(self, data: bytes):
        captured = []

        def opener(request, timeout=None, context=None):
            captured.append((request, timeout))
            return self._Response(data)
        opener.calls = captured
        return opener

    def raising(self, error: Exception):
        def opener(request, timeout=None, context=None):
            raise error
        return opener


class VersionTests(unittest.TestCase):
    def test_reads_version_from_the_installed_cli_js(self):
        base = temp_base(self)
        write_pinned_cli_js(base, VERSION)
        self.assertEqual(win.pinned_chrome_headless_shell_version(base), VERSION)

    def test_missing_cli_js_is_none_not_a_crash(self):
        base = temp_base(self)
        self.assertIsNone(win.pinned_chrome_headless_shell_version(base))

    def test_cli_js_without_the_pattern_is_none(self):
        base = temp_base(self)
        cli_js = base / "node_modules" / "hyperframes" / "dist" / "cli.js"
        cli_js.parent.mkdir(parents=True, exist_ok=True)
        cli_js.write_text("var SOMETHING_ELSE = 1;\n", encoding="utf-8")
        self.assertIsNone(win.pinned_chrome_headless_shell_version(base))

    def test_ignores_macos_12_variant_even_when_declared_first(self):
        """round 3/5, Minor: «CHROME_VERSION» — подстрока «MACOS_12_CHROME_
        VERSION» — без якоря (?<!\\w) регэксп мог прочитать версию для старых
        macOS 12 вместо основной, если минификация переставит объявления."""

        base = temp_base(self)
        write_pinned_cli_js(base, VERSION, macos_first=True)
        self.assertEqual(win.pinned_chrome_headless_shell_version(base), VERSION)


class PathTests(unittest.TestCase):
    def test_cache_target_matches_at_puppeteer_browsers_layout(self):
        base = Path("/prefix")
        target = win.cache_target(base, VERSION)
        self.assertEqual(target, base / "home" / ".cache" / "hyperframes" / "chrome"
                         / "chrome-headless-shell" / "win64-152.0.7977.30")

    def test_executable_path_matches_relativeExecutablePath_for_win64(self):
        base = Path("/prefix")
        exe = win.executable_path(base, VERSION)
        self.assertEqual(exe, base / "home" / ".cache" / "hyperframes" / "chrome"
                         / "chrome-headless-shell" / "win64-152.0.7977.30"
                         / "chrome-headless-shell-win64" / "chrome-headless-shell.exe")


class PreseedTests(unittest.TestCase):
    """round 2/5 → 3/5: проверка на кириллическом префиксе с пробелом —
    ровно то, что ломает встроенную распаковку @puppeteer/browsers на
    Windows (H1, подтверждено run 36141827389)."""

    def _prefix(self):
        return temp_base(self) / CYRILLIC_PREFIX_NAME / "tools" / "hyperframes"

    def test_no_pinned_version_skips_without_a_network_call(self):
        base = temp_base(self)  # cli.js не создан
        opener = OpenerFactory().raising(AssertionError("сеть не должна была понадобиться"))
        result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("версия", result.reason)

    def test_already_present_is_found_without_a_network_call(self):
        base = self._prefix()
        write_pinned_cli_js(base, VERSION)
        exe = win.executable_path(base, VERSION)
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"stub")
        opener = OpenerFactory().raising(AssertionError("сеть не должна была понадобиться"))
        self.assertTrue(win.preseed(base, opener=opener).ok)

    def test_downloads_and_extracts_into_the_cyrillic_space_prefix(self):
        base = self._prefix()
        write_pinned_cli_js(base, VERSION)
        zip_bytes = fake_zip_bytes("chrome-headless-shell.exe", b"\x00binary-stub")
        opener = OpenerFactory().returning(zip_bytes)

        result = win.preseed(base, opener=opener)
        self.assertTrue(result.ok)

        exe = win.executable_path(base, VERSION)
        self.assertTrue(exe.is_file())
        self.assertEqual(exe.read_bytes(), b"\x00binary-stub")
        # URL собран по формуле @puppeteer/browsers: <base>/<версия>/win64/chrome-headless-shell-win64.zip
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url,
                         f"{win.BASE_URL}/152.0.7977.30/win64/chrome-headless-shell-win64.zip")

    def test_socket_timeout_is_one_read_not_the_whole_deadline(self):
        """round 4/5, пункт 3: таймаут urlopen — предел одного чтения сокета
        (READ_TIMEOUT), а не весь срок: иначе медленная раздача по байту
        держала бы скачивание сколько угодно."""

        for deadline, expected in ((660, win.READ_TIMEOUT), (30, 30)):
            with self.subTest(deadline=deadline):
                base = self._prefix()
                write_pinned_cli_js(base, VERSION)
                opener = OpenerFactory().returning(fake_zip_bytes("chrome-headless-shell.exe", b"x"))
                self.assertTrue(win.preseed(base, opener=opener, deadline=deadline).ok)
                _request, timeout = opener.calls[0]
                self.assertEqual(timeout, expected)

    def test_slow_drip_download_stops_at_the_deadline(self):
        """Сервер отдаёт по байту, каждое чтение укладывается в таймаут сокета,
        но общий срок истёк — отказ «не скачался за N с», без итоговой папки
        и без временных хвостов."""

        base = self._prefix()
        write_pinned_cli_js(base, VERSION)
        clock = FakeClock()
        reads = []

        class Drip(io.RawIOBase):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read1(self, _size=-1):
                reads.append(1)
                clock.now += 10
                # Конец потока через 50 чтений: без проверки срока тест упадёт,
                # а не зависнет, дописывая файл без конца.
                return b"x" if len(reads) <= 50 else b""

        result = win.preseed(base, opener=lambda request, timeout=None, context=None: Drip(),
                             deadline=30, clock=clock)
        self.assertFalse(result.ok)
        self.assertIn("не скачался за 30 с", result.reason)
        self.assertEqual(len(reads), 3)  # 0 → 10 → 20 → 30 с: четвёртого чтения нет
        self.assertFalse(win.cache_target(base, VERSION).exists())
        self.assertEqual(leftovers(base), [])

    def test_second_call_is_idempotent_no_second_download(self):
        base = self._prefix()
        write_pinned_cli_js(base, VERSION)
        zip_bytes = fake_zip_bytes("chrome-headless-shell.exe", b"stub")
        opener = OpenerFactory().returning(zip_bytes)

        self.assertTrue(win.preseed(base, opener=opener).ok)
        self.assertEqual(len(opener.calls), 1)

        opener2 = OpenerFactory().raising(AssertionError("второй прогон не должен качать заново"))
        self.assertTrue(win.preseed(base, opener=opener2).ok)

    def test_success_leaves_no_leftover_temp_dir(self):
        base = self._prefix()
        write_pinned_cli_js(base, VERSION)
        opener = OpenerFactory().returning(fake_zip_bytes("chrome-headless-shell.exe", b"stub"))
        self.assertTrue(win.preseed(base, opener=opener).ok)
        self.assertEqual(leftovers(base), [])

    def test_already_installed_still_sweeps_old_extract_dirs(self):
        """round 4/5, пункт 4: уборка — до раннего выхода «уже стоит», иначе
        временные папки убитых прошлых попыток лежали бы вечно."""

        base = self._prefix()
        write_pinned_cli_js(base, VERSION)
        exe = win.executable_path(base, VERSION)
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"stub")
        old = win.cache_target(base, VERSION).parent / f"{win.EXTRACT_TEMP_PREFIX}abcdefgh"
        (old / "extracted").mkdir(parents=True)
        (old / "chrome-headless-shell-win64.zip").write_bytes(b"half")
        hour_ago = time.time() - 2 * 3600
        os.utime(old, (hour_ago, hour_ago))
        opener = OpenerFactory().raising(AssertionError("сеть не должна была понадобиться"))
        self.assertTrue(win.preseed(base, opener=opener).ok)
        self.assertFalse(old.exists())

    def test_network_failure_returns_false_not_a_crash(self):
        base = self._prefix()
        write_pinned_cli_js(base, VERSION)
        opener = OpenerFactory().raising(urllib.error.URLError("нет сети"))
        result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("не скачался", result.reason)

    def test_incomplete_read_returns_false_not_a_crash(self):
        base = self._prefix()
        write_pinned_cli_js(base, VERSION)
        opener = OpenerFactory().raising(http.client.IncompleteRead(b""))
        result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("не скачался", result.reason)

    def test_corrupt_zip_returns_false_not_a_crash(self):
        base = self._prefix()
        write_pinned_cli_js(base, VERSION)
        opener = OpenerFactory().returning("это не zip-файл".encode("utf-8"))
        result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("повреждён", result.reason)

    def test_zlib_error_during_extraction_returns_false_not_a_crash(self):
        base = self._prefix()
        write_pinned_cli_js(base, VERSION)
        opener = OpenerFactory().returning("стаб-байты-архива".encode("utf-8"))
        with mock.patch("install_montage_browser_win.zipfile.ZipFile",
                        side_effect=zlib.error("bad compressed data")):
            result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("повреждён", result.reason)

    def test_missing_executable_in_zip_leaves_no_partial_final_dir(self):
        """round 3/5, атомарность: архив распаковался, но исполняемого файла
        внутри не оказалось — итоговая папка не должна появиться вовсе
        (HyperFrames доверяет «папка есть» без сверки содержимого)."""

        base = self._prefix()
        write_pinned_cli_js(base, VERSION)
        zip_bytes = fake_zip_bytes("не-тот-файл.txt", b"mimo")
        opener = OpenerFactory().returning(zip_bytes)
        result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("не нашёлся", result.reason)
        self.assertFalse(win.cache_target(base, VERSION).exists())

    def test_mkdir_failure_returns_false_not_a_crash(self):
        base = self._prefix()
        write_pinned_cli_js(base, VERSION)  # создаёт node_modules/… нормально
        (base / "home").write_text("не папка", encoding="utf-8")  # файл там, где нужна папка
        opener = OpenerFactory().raising(AssertionError("сеть не должна была понадобиться"))
        result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("не удалось создать", result.reason)


class FinalDirTests(unittest.TestCase):
    """round 4/5, пункты 6–7: итоговая `win64-<версия>` уже есть, но без .exe;
    параллельная установка; антивирус держит папку при переименовании."""

    def setUp(self):
        self.base = temp_base(self) / CYRILLIC_PREFIX_NAME / "tools" / "hyperframes"
        write_pinned_cli_js(self.base, VERSION)
        self.final_dir = win.cache_target(self.base, VERSION)
        self.exe = win.executable_path(self.base, VERSION)
        self.opener = OpenerFactory().returning(fake_zip_bytes("chrome-headless-shell.exe", b"fresh"))

    def stale(self, *, exe_as_dir=False) -> Path:
        leftover = self.final_dir / "chrome-headless-shell-win64" / "icudtl.dat"
        leftover.parent.mkdir(parents=True)
        leftover.write_bytes(b"half")
        if exe_as_dir:
            (self.exe / "broken").mkdir(parents=True)  # «.exe» есть, но это папка
        return leftover

    def test_nonempty_stale_dir_is_replaced_whole_by_the_fresh_extraction(self):
        for exe_as_dir in (False, True):
            with self.subTest(exe_as_dir=exe_as_dir):
                self.setUp()
                leftover = self.stale(exe_as_dir=exe_as_dir)
                result = win.preseed(self.base, opener=self.opener)
                self.assertTrue(result.ok, result.reason)
                self.assertEqual(self.exe.read_bytes(), b"fresh")
                self.assertFalse(leftover.exists())  # старая папка ушла целиком, не слита
                self.assertEqual(leftovers(self.base), [])

    def test_stale_dir_that_cannot_be_moved_aside_is_a_reason_not_a_crash(self):
        leftover = self.stale()
        real = win.replace_file

        def locked(source, target, **kwargs):
            if Path(source) == self.final_dir:
                raise PermissionError(13, "Отказано в доступе", str(source))
            return real(source, target, **kwargs)

        with mock.patch.object(win, "replace_file", side_effect=locked):
            result = win.preseed(self.base, opener=self.opener)
        self.assertFalse(result.ok)
        self.assertIn("не удалось поставить браузер на место", result.reason)
        self.assertIn("Отказано в доступе", result.reason)
        self.assertTrue(leftover.exists())  # чужое не тронуто
        self.assertFalse(self.exe.exists())
        self.assertEqual(leftovers(self.base), [])

    def test_concurrent_install_that_finished_first_is_kept(self):
        """Пока мы качали и распаковывали, параллельная установка поставила
        готовый браузер — его не трогаем и не считаем отказом."""

        real_extract = win._extract

        def extract_while_someone_else_finishes(zip_path, dest):
            self.exe.parent.mkdir(parents=True, exist_ok=True)
            self.exe.write_bytes(b"theirs")
            return real_extract(zip_path, dest)

        with mock.patch.object(win, "_extract", side_effect=extract_while_someone_else_finishes):
            result = win.preseed(self.base, opener=self.opener)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(self.exe.read_bytes(), b"theirs")
        self.assertEqual(leftovers(self.base), [])

    def test_concurrent_install_that_wins_the_rename_race_is_success(self):
        real = win.replace_file

        def race(source, target, **kwargs):
            if Path(target) == self.final_dir:
                self.exe.parent.mkdir(parents=True, exist_ok=True)
                self.exe.write_bytes(b"theirs")
                raise FileExistsError(17, "уже есть", str(target))
            return real(source, target, **kwargs)

        with mock.patch.object(win, "replace_file", side_effect=race):
            result = win.preseed(self.base, opener=self.opener)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(self.exe.read_bytes(), b"theirs")

    def test_rename_is_retried_while_antivirus_holds_the_folder(self):
        real_replace = os.replace
        attempts = []

        def flaky(source, target):
            attempts.append(source)
            if len(attempts) <= 2:
                raise PermissionError(13, "файл занят другим процессом", str(source))
            return real_replace(source, target)

        with mock.patch.object(platform_compat, "IS_WINDOWS", True), \
                mock.patch.object(platform_compat.time, "sleep") as sleep, \
                mock.patch.object(platform_compat.os, "replace", side_effect=flaky):
            result = win.preseed(self.base, opener=self.opener)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(self.exe.read_bytes(), b"fresh")

    def test_rename_gives_up_after_a_bounded_number_of_attempts(self):
        attempts = []

        def always_locked(source, target):
            attempts.append(source)
            raise PermissionError(13, "файл занят другим процессом", str(source))

        with mock.patch.object(platform_compat, "IS_WINDOWS", True), \
                mock.patch.object(platform_compat.time, "sleep") as sleep, \
                mock.patch.object(platform_compat.os, "replace", side_effect=always_locked):
            result = win.preseed(self.base, opener=self.opener)
        self.assertFalse(result.ok)
        self.assertIn("файл занят другим процессом", result.reason)
        self.assertEqual(len(attempts), win.RENAME_ATTEMPTS)
        self.assertEqual(sleep.call_count, win.RENAME_ATTEMPTS - 1)
        self.assertFalse(self.final_dir.exists())
        self.assertEqual(leftovers(self.base), [])


class BudgetTests(unittest.TestCase):
    """round 4/5, пункт 3: шаг браузера на Windows укладывается в B =
    timeouts.browser (preseed + ensure вместе), пока распаковка ≤ 60 с."""

    def test_download_stops_early_enough_to_leave_ensure_its_share(self):
        budget = 900
        deadline = win.download_deadline(budget)
        worst_download = deadline + win.READ_TIMEOUT
        for extraction in (0, 30, 60):
            with self.subTest(extraction=extraction):
                spent = worst_download + extraction
                total = spent + win.ensure_timeout(budget, spent)
                self.assertEqual(total, budget)
                self.assertGreaterEqual(win.ensure_timeout(budget, spent), win.ENSURE_MIN)

    def test_quick_preseed_leaves_almost_the_whole_budget_to_ensure(self):
        self.assertEqual(win.ensure_timeout(900, 2), 898)

    def test_tiny_budget_still_gives_each_step_a_floor(self):
        self.assertEqual(win.download_deadline(100), win.READ_TIMEOUT)
        self.assertEqual(win.ensure_timeout(100, 90), win.ENSURE_MIN)


if __name__ == "__main__":
    unittest.main()

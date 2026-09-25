#!/usr/bin/env python3
"""round 2/5 → 3/5: chrome-headless-shell для Windows напрямую, в обход
битой распаковки @puppeteer/browsers на не-ASCII пути
(install_montage_browser_win): версия, пути, атомарная распаковка, отказы
сети/архива/диска не бросают исключений."""

from __future__ import annotations

import http.client
import io
import sys
import tempfile
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
        write_pinned_cli_js(base, "152.0.7977.30")
        self.assertEqual(win.pinned_chrome_headless_shell_version(base), "152.0.7977.30")

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
        write_pinned_cli_js(base, "152.0.7977.30", macos_first=True)
        self.assertEqual(win.pinned_chrome_headless_shell_version(base), "152.0.7977.30")


class PathTests(unittest.TestCase):
    def test_cache_target_matches_at_puppeteer_browsers_layout(self):
        base = Path("/prefix")
        target = win.cache_target(base, "152.0.7977.30")
        self.assertEqual(target, base / "home" / ".cache" / "hyperframes" / "chrome"
                         / "chrome-headless-shell" / "win64-152.0.7977.30")

    def test_executable_path_matches_relativeExecutablePath_for_win64(self):
        base = Path("/prefix")
        exe = win.executable_path(base, "152.0.7977.30")
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
        write_pinned_cli_js(base, "152.0.7977.30")
        exe = win.executable_path(base, "152.0.7977.30")
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"stub")
        opener = OpenerFactory().raising(AssertionError("сеть не должна была понадобиться"))
        self.assertTrue(win.preseed(base, opener=opener).ok)

    def test_downloads_and_extracts_into_the_cyrillic_space_prefix(self):
        base = self._prefix()
        write_pinned_cli_js(base, "152.0.7977.30")
        zip_bytes = fake_zip_bytes("chrome-headless-shell.exe", b"\x00binary-stub")
        opener = OpenerFactory().returning(zip_bytes)

        result = win.preseed(base, opener=opener)
        self.assertTrue(result.ok)

        exe = win.executable_path(base, "152.0.7977.30")
        self.assertTrue(exe.is_file())
        self.assertEqual(exe.read_bytes(), b"\x00binary-stub")
        # URL собран по формуле @puppeteer/browsers: <base>/<версия>/win64/chrome-headless-shell-win64.zip
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url,
                         f"{win.BASE_URL}/152.0.7977.30/win64/chrome-headless-shell-win64.zip")

    def test_timeout_is_forwarded_to_the_opener(self):
        base = self._prefix()
        write_pinned_cli_js(base, "152.0.7977.30")
        opener = OpenerFactory().returning(fake_zip_bytes("chrome-headless-shell.exe", b"x"))
        win.preseed(base, opener=opener, timeout=42)
        _request, timeout = opener.calls[0]
        self.assertEqual(timeout, 42)

    def test_second_call_is_idempotent_no_second_download(self):
        base = self._prefix()
        write_pinned_cli_js(base, "152.0.7977.30")
        zip_bytes = fake_zip_bytes("chrome-headless-shell.exe", b"stub")
        opener = OpenerFactory().returning(zip_bytes)

        self.assertTrue(win.preseed(base, opener=opener).ok)
        self.assertEqual(len(opener.calls), 1)

        opener2 = OpenerFactory().raising(AssertionError("второй прогон не должен качать заново"))
        self.assertTrue(win.preseed(base, opener=opener2).ok)

    def test_success_leaves_no_leftover_temp_dir(self):
        base = self._prefix()
        write_pinned_cli_js(base, "152.0.7977.30")
        opener = OpenerFactory().returning(fake_zip_bytes("chrome-headless-shell.exe", b"stub"))
        self.assertTrue(win.preseed(base, opener=opener).ok)
        parent = win.cache_target(base, "152.0.7977.30").parent
        leftovers = [p.name for p in parent.iterdir() if p.name.startswith(win.EXTRACT_TEMP_PREFIX)]
        self.assertEqual(leftovers, [])

    def test_network_failure_returns_false_not_a_crash(self):
        base = self._prefix()
        write_pinned_cli_js(base, "152.0.7977.30")
        opener = OpenerFactory().raising(urllib.error.URLError("нет сети"))
        result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("не скачался", result.reason)

    def test_incomplete_read_returns_false_not_a_crash(self):
        base = self._prefix()
        write_pinned_cli_js(base, "152.0.7977.30")
        opener = OpenerFactory().raising(http.client.IncompleteRead(b""))
        result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("не скачался", result.reason)

    def test_corrupt_zip_returns_false_not_a_crash(self):
        base = self._prefix()
        write_pinned_cli_js(base, "152.0.7977.30")
        opener = OpenerFactory().returning("это не zip-файл".encode("utf-8"))
        result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("повреждён", result.reason)

    def test_zlib_error_during_extraction_returns_false_not_a_crash(self):
        base = self._prefix()
        write_pinned_cli_js(base, "152.0.7977.30")
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
        write_pinned_cli_js(base, "152.0.7977.30")
        zip_bytes = fake_zip_bytes("не-тот-файл.txt", b"mimo")
        opener = OpenerFactory().returning(zip_bytes)
        result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("не нашёлся", result.reason)
        self.assertFalse(win.cache_target(base, "152.0.7977.30").exists())

    def test_mkdir_failure_returns_false_not_a_crash(self):
        base = self._prefix()
        write_pinned_cli_js(base, "152.0.7977.30")  # создаёт node_modules/… нормально
        (base / "home").write_text("не папка", encoding="utf-8")  # файл там, где нужна папка
        opener = OpenerFactory().raising(AssertionError("сеть не должна была понадобиться"))
        result = win.preseed(base, opener=opener)
        self.assertFalse(result.ok)
        self.assertIn("не удалось создать", result.reason)


if __name__ == "__main__":
    unittest.main()

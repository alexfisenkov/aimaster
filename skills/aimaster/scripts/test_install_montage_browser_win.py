#!/usr/bin/env python3
"""round 2/5: chrome-headless-shell для Windows напрямую, в обход битой
распаковки @puppeteer/browsers на не-ASCII пути (install_montage_browser_win)."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path

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


def write_pinned_cli_js(prefix: Path, version: str) -> None:
    cli_js = prefix / "node_modules" / "hyperframes" / "dist" / "cli.js"
    cli_js.parent.mkdir(parents=True, exist_ok=True)
    cli_js.write_text(
        'var CHROME_VERSION, MACOS_12_CHROME_VERSION;\n'
        'CHROME_VERSION = "%s";\n'
        'MACOS_12_CHROME_VERSION = "150.0.7871.124";\n' % version,
        encoding="utf-8")


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
            captured.append(request)
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
    """round 2/5: проверка именно на кириллическом префиксе с пробелом —
    ровно то, что ломает встроенную распаковку @puppeteer/browsers на
    Windows (H1, подтверждено run 36141827389)."""

    def test_no_pinned_version_skips_without_a_network_call(self):
        base = temp_base(self)  # cli.js не создан
        opener = OpenerFactory().raising(AssertionError("сеть не должна была понадобиться"))
        self.assertFalse(win.preseed(base, opener=opener))

    def test_already_present_is_found_without_a_network_call(self):
        base = temp_base(self) / CYRILLIC_PREFIX_NAME / "tools" / "hyperframes"
        write_pinned_cli_js(base, "152.0.7977.30")
        exe = win.executable_path(base, "152.0.7977.30")
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_bytes(b"stub")
        opener = OpenerFactory().raising(AssertionError("сеть не должна была понадобиться"))
        self.assertTrue(win.preseed(base, opener=opener))

    def test_downloads_and_extracts_into_the_cyrillic_space_prefix(self):
        base = temp_base(self) / CYRILLIC_PREFIX_NAME / "tools" / "hyperframes"
        write_pinned_cli_js(base, "152.0.7977.30")
        zip_bytes = fake_zip_bytes("chrome-headless-shell.exe", b"\x00binary-stub")
        factory = OpenerFactory()
        opener = factory.returning(zip_bytes)

        self.assertTrue(win.preseed(base, opener=opener))

        exe = win.executable_path(base, "152.0.7977.30")
        self.assertTrue(exe.is_file())
        self.assertEqual(exe.read_bytes(), b"\x00binary-stub")
        # URL собран по формуле @puppeteer/browsers: <base>/<версия>/win64/chrome-headless-shell-win64.zip
        request = opener.calls[0]
        self.assertEqual(request.full_url,
                         f"{win.BASE_URL}/152.0.7977.30/win64/chrome-headless-shell-win64.zip")

    def test_second_call_is_idempotent_no_second_download(self):
        base = temp_base(self) / CYRILLIC_PREFIX_NAME / "tools" / "hyperframes"
        write_pinned_cli_js(base, "152.0.7977.30")
        zip_bytes = fake_zip_bytes("chrome-headless-shell.exe", b"stub")
        opener = OpenerFactory().returning(zip_bytes)

        self.assertTrue(win.preseed(base, opener=opener))
        self.assertEqual(len(opener.calls), 1)

        opener2 = OpenerFactory().raising(AssertionError("второй прогон не должен качать заново"))
        self.assertTrue(win.preseed(base, opener=opener2))

    def test_network_failure_returns_false_not_a_crash(self):
        base = temp_base(self) / CYRILLIC_PREFIX_NAME / "tools" / "hyperframes"
        write_pinned_cli_js(base, "152.0.7977.30")
        opener = OpenerFactory().raising(urllib.error.URLError("нет сети"))
        self.assertFalse(win.preseed(base, opener=opener))

    def test_corrupt_zip_returns_false_not_a_crash(self):
        base = temp_base(self) / CYRILLIC_PREFIX_NAME / "tools" / "hyperframes"
        write_pinned_cli_js(base, "152.0.7977.30")
        opener = OpenerFactory().returning("это не zip-файл".encode("utf-8"))
        self.assertFalse(win.preseed(base, opener=opener))


if __name__ == "__main__":
    unittest.main()

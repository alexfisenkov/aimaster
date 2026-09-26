#!/usr/bin/env python3
"""Проект, собранный чужими руками: на месте файла монтажа — симлинк на файл вне
проекта. Ни одна запись монтажа не идёт по такой ссылке: не меняет права и
содержимое её цели и не оставляет саму ссылку на месте своего файла."""

from __future__ import annotations

import hashlib
import os
import stat
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

from montage_testkit import FakeHyperframes, fake_engine, fake_gsap_prefix, seed_workspace  # noqa: E402
from studio.authoring_support import open_store  # noqa: E402
from studio.montage import MontageError, engine_cli, index_io, media_sync, replace_target, typeface, vendor  # noqa: E402
from studio.montage.locks import held_lock  # noqa: E402
from studio.montage.model import read_model  # noqa: E402
from test_montage_model import draft_html  # noqa: E402

SECRET = b"PRIVATE KEY"  # 11 байт — как b"video-bytes": «тот же размер» ничего не доказывает


class _Planted(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.outside = self.base / "вне проекта" / "секрет.key"
        self.outside.parent.mkdir()
        self.outside.write_bytes(SECRET)
        os.chmod(self.outside, 0o600)
        self.outside_mode = stat.S_IMODE(os.stat(self.outside).st_mode)
        self.project = self.base / "проект с пробелом"

    def plant(self, link: Path, target: Path | None = None) -> Path:
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(target or self.outside, link)
        except (OSError, NotImplementedError) as error:  # Windows без права на симлинки
            self.skipTest(f"симлинк здесь не создать: {error}")
        return link

    def assert_untouched(self, link: Path, target: Path | None = None, content: bytes = SECRET,
                         mode: int | None = None):
        target = target or self.outside
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode),
                         self.outside_mode if mode is None else mode)
        self.assertFalse(os.path.islink(link), "ссылка осталась на месте файла монтажа")
        self.assertTrue(link.is_file())


class PlantedLinkTests(_Planted):
    def test_fonts_never_chmod_the_target_of_a_planted_link(self):
        assets = self.project / "assets"
        font = self.plant(assets / "fonts" / "inter-latin-400-normal.woff2")
        self.assertIn(font.name, typeface.sync_fonts(assets))
        self.assert_untouched(font)
        self.assertEqual(font.read_bytes(), (typeface.FONT_DIR / font.name).read_bytes())

    def test_fonts_replace_a_planted_link_even_when_its_target_matches(self):
        assets = self.project / "assets"
        package = typeface.FONT_DIR / "OFL.txt"
        before = (package.read_bytes(), stat.S_IMODE(package.stat().st_mode))
        link = self.plant(assets / "fonts" / "OFL.txt", package)
        self.assertIn("OFL.txt", typeface.sync_fonts(assets))
        self.assert_untouched(link, package, before[0], before[1])

    def test_media_replaces_a_planted_link_of_the_same_size(self):
        source = self.base / "media" / "клип.mp4"
        source.parent.mkdir()
        source.write_bytes(b"video-bytes")
        target = self.plant(self.project / "assets" / "asset-1.mp4")
        self.assertIn(media_sync.link_or_copy(source, target), ("link", "copy"))
        self.assert_untouched(target)
        self.assertEqual(target.read_bytes(), b"video-bytes")

    def test_copy_via_temp_in_both_modes(self):
        source = self.base / "шрифт.woff2"
        source.write_bytes(b"font")
        for keep_mode in (True, False):
            with self.subTest(keep_mode=keep_mode):
                target = self.plant(self.project / f"assets-{keep_mode}" / "f.woff2")
                media_sync.copy_via_temp(source, target, keep_mode=keep_mode)
                self.assert_untouched(target)
                self.assertEqual(target.read_bytes(), b"font")

    def test_gsap_replaces_a_planted_link_to_an_identical_file(self):
        prefix = fake_gsap_prefix(self.base / "движок")
        dist = vendor.gsap_dist(prefix) / "gsap.min.js"
        self.outside.write_bytes(dist.read_bytes())  # та же библиотека — вне проекта
        assets = self.project / "current" / "assets"
        link = self.plant(assets / "gsap.min.js")
        vendor.copy_gsap(prefix, assets)
        self.assert_untouched(link, content=dist.read_bytes())

    def test_text_write_does_not_take_the_mode_of_a_planted_link_target(self):
        os.chmod(self.outside, 0o666)  # чужой файл, открытый всем на запись
        self.outside_mode = stat.S_IMODE(os.stat(self.outside).st_mode)
        index = self.plant(self.project / "current" / "index.html")
        index_io.write_text_atomic(index, "<html></html>")
        self.assert_untouched(index)
        self.assertEqual(index.read_text(encoding="utf-8"), "<html></html>")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(index.stat().st_mode), index_io.new_file_mode())

    def test_model_cache_never_writes_through_a_planted_link(self):
        engine, current, cache = fake_engine(self.base), self.project / "current", self.project / ".cache"
        current.mkdir(parents=True)
        (current / "index.html").write_bytes(draft_html().encode("utf-8"))  # без CRLF Windows: имя кэша — по тексту
        key = hashlib.sha256(f"{engine.version}\0{draft_html()}".encode("utf-8")).hexdigest()[:24]
        link = self.plant(cache / f"model-{key}.json")  # имя кэша предсказуемо по index.html
        runner = FakeHyperframes()
        first = read_model(engine, current, cache_dir=cache, runner=runner)
        self.assert_untouched(link)
        self.assertEqual(read_model(engine, current, cache_dir=cache, runner=runner), first)
        self.assertEqual(runner.calls, [["timeline", "--json"]])  # второй раз — из своего кэша

    def test_desk_log_never_truncates_a_planted_link_target(self):
        log = self.plant(self.project / ".logs" / "desk.log")
        engine_cli.popen_engine(fake_engine(self.base / "движок"), ["preview", "."], cwd=self.base,
                                log_path=log, popen=mock.Mock(return_value=mock.Mock(pid=4242)))
        self.assert_untouched(log, content=SECRET)


class LockTests(_Planted):
    def test_montage_lock_never_opens_through_a_planted_link(self):
        elsewhere = self.outside.parent / "создал бы замок"
        lock = self.plant(self.project / "montage" / ".desk.lock", elsewhere)  # висячая ссылка
        with self.assertRaises(MontageError) as caught:
            with held_lock(lock, busy="занято"):
                self.fail("замок взят по ссылке")
        self.assertIn(".desk.lock", str(caught.exception))
        self.assertFalse(os.path.lexists(elsewhere))
        with held_lock(self.project / "montage" / ".build.lock", busy="занято"):
            pass  # обычный замок — как раньше

    def test_state_lock_never_opens_through_a_planted_link(self):
        seed = seed_workspace(self.base, {}, lambda ids: {"revision": 0, "project": {"id": "p"}})
        store = open_store(seed.workspace)
        elsewhere = self.outside.parent / "создал бы замок state"
        link = self.plant(seed.workspace / "projects" / "p" / ".state.lock", elsewhere)
        with self.assertRaises(OSError):
            store.transact("p", 0, lambda state: state.update(note="x"))
        self.assertFalse(os.path.lexists(elsewhere))
        self.assertEqual(store.load("p")["revision"], 0)
        link.unlink()
        self.assertEqual(store.transact("p", 0, lambda state: state.update(note="x"))["revision"], 1)


class ReplaceTargetTests(_Planted):
    def test_read_only_file_is_made_writable_only_on_windows(self):
        target = self.project / "f.bin"
        target.parent.mkdir()
        target.write_bytes(b"old")
        os.chmod(target, 0o444)
        self.addCleanup(os.chmod, target, 0o644)
        with mock.patch.object(replace_target, "IS_WINDOWS", False):
            replace_target.make_replaceable(target)
        self.assertFalse(stat.S_IMODE(target.stat().st_mode) & stat.S_IWRITE)  # POSIX: rename не смотрит
        with mock.patch.object(replace_target, "IS_WINDOWS", True):
            replace_target.make_replaceable(target)
        self.assertTrue(stat.S_IMODE(target.stat().st_mode) & stat.S_IWRITE)
        self.assertEqual(target.read_bytes(), b"old")

    def test_links_go_away_themselves_and_folders_stay(self):
        with mock.patch.object(replace_target, "IS_WINDOWS", True):  # chmod — и на Windows не по ссылке
            dangling = self.plant(self.project / "нет.bin", self.base / "никогда не было")
            replace_target.make_replaceable(dangling)
            self.assertFalse(os.path.lexists(dangling))
            live = self.plant(self.project / "есть.bin")
            os.chmod(self.outside, 0o444)
            self.addCleanup(os.chmod, self.outside, 0o600)
            replace_target.make_replaceable(live)
        self.assertFalse(os.path.lexists(live))
        self.assertEqual(self.outside.read_bytes(), SECRET)
        self.assertFalse(stat.S_IMODE(os.stat(self.outside).st_mode) & stat.S_IWRITE)
        folder = self.project / "папка"
        folder.mkdir()
        replace_target.make_replaceable(folder)
        self.assertTrue(folder.is_dir())
        self.assertIsNone(replace_target.regular_stat(folder))
        self.assertIsNone(replace_target.regular_stat(self.project / "пропал"))


if __name__ == "__main__":
    unittest.main()

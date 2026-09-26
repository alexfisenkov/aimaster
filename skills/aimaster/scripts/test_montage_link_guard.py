#!/usr/bin/env python3
"""Папка монтажа со ссылками наружу (симлинк, junction) или своим ffmpeg —
отказ до любой работы; закрытие стола работает всё равно."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from montage_testkit import seed_workspace, tiny_mp4, video_state  # noqa: E402
from studio.montage import MontageError, link_guard, service  # noqa: E402
from studio.montage.link_guard import check_montage_folder  # noqa: E402
from studio.montage.paths import montage_paths  # noqa: E402

JUNCTION, CLOUD_PLACEHOLDER = 0xA0000003, 0x9000601A


class _FakeEntry:
    """Запись os.scandir с lstat Windows: точка повторной обработки с тегом `tag`."""

    def __init__(self, folder: Path, name: str, tag: int, mode: int):
        self.name, self.path = name, str(folder / name)
        self._info = SimpleNamespace(st_mode=mode, st_reparse_tag=tag)

    def is_symlink(self):
        return False

    def stat(self, follow_symlinks=True):
        return self._info


class GuardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.project = self.base / "проект с пробелом"
        self.root = montage_paths(self.project).root
        (self.root / "current" / "assets").mkdir(parents=True)
        (self.root / "current" / "index.html").write_text("<html></html>", encoding="utf-8")
        (self.root / "versions" / "v001").mkdir(parents=True)
        self.outside = self.base / "вне проекта"
        self.outside.mkdir()
        (self.outside / "секрет.key").write_bytes(b"PRIVATE KEY")

    def link(self, path: Path, target: Path, directory=False) -> None:
        try:
            os.symlink(target, path, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"симлинк здесь не создать: {error}")

    def refused(self, *parts: str) -> str:
        with self.assertRaises(MontageError) as caught:
            check_montage_folder(self.root)
        text = str(caught.exception)
        for part in parts:
            self.assertIn(part, text)
        self.assertNotIn(str(self.base), text)
        return text

    def test_a_clean_folder_and_a_missing_one_pass(self):
        (self.root / "current" / ".hyperframes").mkdir()  # кэш движка без bin — законен
        check_montage_folder(self.root)
        check_montage_folder(self.base / "нет" / "montage")

    def test_file_link_is_refused(self):
        self.link(self.root / "current" / "assets" / "a.mp4", self.outside / "секрет.key")
        self.refused("montage/current/assets/a.mp4", "монтаж не трогаю")

    def test_folder_link_is_refused_and_never_entered(self):
        self.link(self.outside / "внутри", self.outside / "секрет.key")
        self.link(self.root / ".cache", self.outside, directory=True)
        text = self.refused("montage/.cache")
        self.assertNotIn("внутри", text)

    def test_dangling_link_is_refused(self):
        self.link(self.root / ".desk.json", self.base / "никогда не было")
        self.refused("montage/.desk.json")

    def test_montage_itself_as_a_link_is_refused(self):
        moved = self.base / "настоящий монтаж"
        self.root.rename(moved)
        self.link(self.root, moved, directory=True)
        self.refused("папка montage проекта — ссылка")

    def test_at_most_three_links_are_named(self):
        for index in range(5):
            self.link(self.root / "versions" / "v001" / f"l{index}", self.outside / "секрет.key")
        text = self.refused("и ещё 2")
        self.assertEqual(text.count("montage/versions/v001/l"), 3)

    def fake_entries(self, *entries):
        real = os.scandir

        def scandir(path):
            found = list(real(path))
            return found + [entry for entry in entries if Path(entry.path).parent == Path(path)]
        return mock.patch.object(link_guard.os, "scandir", scandir)

    def test_windows_junction_is_a_link_by_its_reparse_tag(self):
        junction = _FakeEntry(self.root / "current", "assets2", JUNCTION, stat.S_IFDIR | 0o755)
        with mock.patch.object(link_guard, "IS_WINDOWS", True), self.fake_entries(junction):
            self.refused("montage/current/assets2")
        real_lstat = os.lstat

        def lstat(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            if Path(path) == self.root:
                return SimpleNamespace(st_mode=info.st_mode, st_reparse_tag=JUNCTION)
            return info
        with mock.patch.object(link_guard, "IS_WINDOWS", True), \
                mock.patch.object(link_guard.os, "lstat", lstat):
            self.refused("папка montage проекта — ссылка")

    def test_cloud_placeholder_is_not_a_link(self):
        placeholder = _FakeEntry(self.root / "current" / "assets", "a.mp4", CLOUD_PLACEHOLDER,
                                 stat.S_IFREG | 0o644)
        with mock.patch.object(link_guard, "IS_WINDOWS", True), self.fake_entries(placeholder):
            check_montage_folder(self.root)

    def test_own_ffmpeg_in_the_launch_folder_is_refused(self):
        for planted in ("ffmpeg.exe", "FFprobe", "ffmpeg.cmd"):
            with self.subTest(planted=planted):
                (self.root / "current" / planted).write_bytes(b"#!")
                self.refused(f"montage/current/{planted}", "ffmpeg")
                (self.root / "current" / planted).unlink()
        (self.root / "current" / ".hyperframes" / "bin").mkdir(parents=True)
        self.refused("montage/current/.hyperframes/bin")

    def test_unreadable_folder_is_a_refusal_not_a_pass(self):
        real = os.scandir

        def scandir(path):
            if Path(path).name == "versions":
                raise PermissionError("нет доступа")
            return real(path)
        with mock.patch.object(link_guard.os, "scandir", scandir):
            self.refused("не удалось проверить папку монтажа montage/versions")


class ServiceGuardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        seed = seed_workspace(base, {"a.mp4": tiny_mp4(b"a")}, lambda ids: video_state(
            [("s1", "Сад", "Барсик", 2000, ids["a.mp4"])]))
        self.ws = seed.workspace
        self.paths = montage_paths(self.ws / "projects" / "p")
        self.paths.current.mkdir(parents=True)
        try:
            os.symlink(base / "где-то", self.paths.current / "index.html")
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"симлинк здесь не создать: {error}")

    def test_every_command_but_close_refuses(self):
        for call in (lambda: service.status(self.ws, "p", locate=lambda: (None, "нет")),
                     lambda: service.open_desk(self.ws, "p", desk=mock.Mock()),
                     lambda: service.gsap(self.ws, "p"),
                     lambda: service.diff(self.ws, "p")):
            with self.assertRaises(MontageError) as caught:
                call()
            self.assertIn("montage/current/index.html", str(caught.exception))

    def test_close_still_stops_our_desk(self):
        desk = mock.Mock()
        desk.close.return_value = {"state": "closed"}
        self.assertEqual(service.close_desk(self.ws, "p", desk=desk), {"project_id": "p", "state": "closed"})
        self.assertEqual(desk.close.call_args.args[0], self.paths)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Скиллы HyperFrames в рабочей папке: копия с пометкой, чужое — conflict, без кеша — статус."""

from __future__ import annotations

import json
import os
import shutil
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

from studio.montage import engine, workspace_skills  # noqa: E402
from studio.workspace_init import init_workspace  # noqa: E402

FILES = {
    "demo/SKILL.md": b"---\nname: demo\n---\r\nhello\r\n",
    "demo/scripts/run.py": b"print(1)\r\n",
    "demo/a.json": b'{"a":1}',
    "other/SKILL.md": b"---\nname: other\n---\n",
}
PIN = {"repo": "heygen-com/hyperframes", "tag": "v9.9.9", "commit": "c" * 40, "tree": "t" * 40,
       "bundles": {"demo": {"hash": "82e2a555abf32641", "files": 3},
                   "other": {"hash": "05d1df8575671f97", "files": 1}}}


class WorkspaceSkillsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        patcher = mock.patch.dict(os.environ, {engine.PREFIX_ENV: str(self.base / "tools" / "hyperframes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cache = self.base / "tools" / "hyperframes-skills" / "v9.9.9"
        for rel, data in FILES.items():
            (self.cache / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.cache / rel).write_bytes(data)
        self.ws = self.base / "рабочая папка"
        self.ws.mkdir()

    def sync(self, **kwargs):
        return workspace_skills.sync_workspace_skills(self.ws, pin=PIN, **kwargs)

    def test_copies_into_both_agent_folders_with_a_marker(self):
        report = self.sync()
        self.assertEqual((report["status"], len(report["items"])), ("installed", 4))
        for parts in ((".claude", "skills"), (".agents", "skills")):
            skill = self.ws.joinpath(*parts, "demo")
            self.assertFalse(skill.is_symlink())
            self.assertEqual((skill / "scripts" / "run.py").read_bytes(), FILES["demo/scripts/run.py"])
            marker = json.loads((skill / ".aimaster-install.json").read_text(encoding="utf-8"))
            self.assertEqual((marker["installed_by"], marker["version"]), ("aimaster", "v9.9.9"))
        self.assertEqual(self.sync()["status"], "found")

    def test_foreign_folder_is_a_conflict_and_untouched(self):
        foreign = self.ws / ".claude" / "skills" / "other"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("чужое", encoding="utf-8")
        report = self.sync()
        self.assertEqual(report["status"], "conflict")
        self.assertIn(str(foreign), report["message"])
        self.assertEqual((foreign / "SKILL.md").read_text(encoding="utf-8"), "чужое")
        self.assertTrue((self.ws / ".claude" / "skills" / "demo" / "SKILL.md").is_file())

    def test_outdated_marked_copy_is_rebuilt(self):
        old = self.ws / ".agents" / "skills" / "demo"
        old.mkdir(parents=True)
        (old / "SKILL.md").write_text("старое", encoding="utf-8")
        (old / ".aimaster-install.json").write_text(
            json.dumps({"installed_by": "aimaster", "version": "v9.9.8"}), encoding="utf-8")
        report = self.sync()
        item = next(i for i in report["items"] if i["path"] == str(old))
        self.assertEqual(item["status"], "installed")
        self.assertEqual((old / "SKILL.md").read_bytes(), FILES["demo/SKILL.md"])
        self.assertEqual(json.loads((old / ".aimaster-install.json").read_text(encoding="utf-8"))["version"],
                         "v9.9.9")

    def test_read_only_check_writes_nothing(self):
        self.assertEqual(self.sync(create=False)["status"], "missing")
        self.assertFalse((self.ws / ".claude").exists())

    def test_empty_cache_is_a_status_not_an_error(self):
        shutil.rmtree(self.cache)
        report = self.sync()
        self.assertEqual(report["status"], "missing")
        self.assertIn("--install-deps", report["message"])
        self.assertFalse((self.ws / ".claude").exists())

    def test_workspace_init_reports_skills_and_never_fails(self):
        result = init_workspace(self.base / "новая папка")
        self.assertIn("projects/", result["created"])
        self.assertEqual(result["hyperframes_skills"]["status"], "missing")
        self.assertIn("--install-deps", result["hyperframes_skills"]["message"])

    def test_stale_copy_temp_dirs_are_swept_before_a_new_copy(self):
        """Разбор 1/5, находка 11: мусор от оборванной прошлой копии убирается."""

        claude_skills = self.ws / ".claude" / "skills"
        stale = claude_skills / ".demo-oldjunk"
        stale.mkdir(parents=True)
        (stale / "leftover.txt").write_text("мусор", encoding="utf-8")
        keep = claude_skills / "not-a-temp-dir"
        keep.mkdir(parents=True)
        self.sync()
        self.assertFalse(stale.exists())
        self.assertTrue(keep.exists())


class HomeGuardTests(unittest.TestCase):
    """Разбор 1/5, находка 4: рабочая папка не может быть домашней."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        patcher = mock.patch.dict(os.environ, {engine.PREFIX_ENV: str(self.base / "tools" / "hyperframes")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cache = self.base / "tools" / "hyperframes-skills" / "v9.9.9"
        for rel, data in FILES.items():
            (self.cache / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.cache / rel).write_bytes(data)
        self.fake_home = self.base / "домашняя папка"
        self.fake_home.mkdir()

    def test_workspace_equal_to_home_is_skipped_not_written(self):
        with mock.patch("pathlib.Path.home", return_value=self.fake_home):
            report = workspace_skills.sync_workspace_skills(self.fake_home, pin=PIN)
        self.assertEqual(report["status"], "skipped_home")
        self.assertEqual(report["items"], [])
        self.assertFalse((self.fake_home / ".claude").exists())
        self.assertFalse((self.fake_home / ".agents").exists())

    def test_workspace_equal_to_home_is_skipped_even_in_read_only_check(self):
        with mock.patch("pathlib.Path.home", return_value=self.fake_home):
            report = workspace_skills.sync_workspace_skills(self.fake_home, pin=PIN, create=False)
        self.assertEqual(report["status"], "skipped_home")

    def test_agent_dir_symlinked_into_home_is_also_skipped(self):
        other_ws = self.base / "другая рабочая папка"
        other_ws.mkdir()
        (self.fake_home / ".claude").mkdir(parents=True)
        try:
            os.symlink(self.fake_home / ".claude", other_ws / ".claude", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("символические ссылки недоступны")
        with mock.patch("pathlib.Path.home", return_value=self.fake_home):
            report = workspace_skills.sync_workspace_skills(other_ws, pin=PIN)
        self.assertEqual(report["status"], "skipped_home")

    def test_ordinary_workspace_is_unaffected_by_the_guard(self):
        ws = self.base / "обычная рабочая папка"
        ws.mkdir()
        with mock.patch("pathlib.Path.home", return_value=self.fake_home):
            report = workspace_skills.sync_workspace_skills(ws, pin=PIN)
        self.assertEqual(report["status"], "installed")


if __name__ == "__main__":
    unittest.main()

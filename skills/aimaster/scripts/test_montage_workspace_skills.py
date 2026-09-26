#!/usr/bin/env python3
"""Скиллы HyperFrames в рабочей папке: копия с пометкой, чужое — conflict, без кеша — статус."""

from __future__ import annotations

import json
import os
import shutil
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
        self.assertIn(".claude/skills/other", report["message"])
        self.assertNotIn(str(self.ws), report["message"])
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
        self.assertIn("engine.install в ответе montage status", report["message"])
        self.assertFalse((self.ws / ".claude").exists())

    def test_workspace_init_reports_skills_and_never_fails(self):
        result = init_workspace(self.base / "новая папка")
        self.assertIn("projects/", result["created"])
        self.assertEqual(result["hyperframes_skills"]["status"], "missing")
        self.assertIn("engine.install в ответе montage status", result["hyperframes_skills"]["message"])

    def test_stale_copy_temp_dirs_are_swept_before_a_new_copy(self):
        """Разбор 1/5, находка 11: мусор от оборванной прошлой копии
        убирается — но только старше часа (разбор 2/5, находка B): свежая
        папка может быть рабочей папкой параллельно идущей установки."""

        claude_skills = self.ws / ".claude" / "skills"
        claude_skills.mkdir(parents=True)
        # имена — настоящий mkdtemp, как у _copy: уборка сверяет его точный вид (разбор 4/5)
        prefix = f"{workspace_skills.TEMP_PREFIX}demo-"
        stale = Path(tempfile.mkdtemp(prefix=prefix, dir=str(claude_skills)))
        (stale / "leftover.txt").write_text("мусор", encoding="utf-8")
        old_time = time.time() - 7200  # два часа назад
        os.utime(stale, (old_time, old_time))
        fresh = Path(tempfile.mkdtemp(prefix=prefix, dir=str(claude_skills)))
        keep = claude_skills / "not-a-temp-dir"
        keep.mkdir(parents=True)
        self.sync()
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(keep.exists())

    def test_lookalike_user_folder_is_never_swept(self):
        """Разбор 2/5, находка B: скилл называется «demo» — своя папка
        пользователя «.demo-backup» не должна совпасть с точным видом
        tempfile.mkdtemp (раньше префиксный glob «.demo-*» её бы смёл)."""

        claude_skills = self.ws / ".claude" / "skills"
        lookalike = claude_skills / ".demo-backup"
        lookalike.mkdir(parents=True)
        old_time = time.time() - 7200
        os.utime(lookalike, (old_time, old_time))
        self.sync()
        self.assertTrue(lookalike.exists())

    @unittest.skipIf(os.name == "nt", "права доступа POSIX — на Windows это не тестируется")
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root игнорирует права доступа")
    def test_unreadable_agent_dir_does_not_crash_the_sweep(self):
        """Разбор 3/5, находка 2: PermissionError на iterdir() при уборке не
        должен ронять всю установку — уборка мусора необязательна."""

        claude_skills = self.ws / ".claude" / "skills"
        claude_skills.mkdir(parents=True)
        claude_skills.chmod(0o300)  # запись+исполнение, без чтения — iterdir() падает
        try:
            report = self.sync()
        finally:
            claude_skills.chmod(0o700)  # иначе временную папку теста будет не удалить
        self.assertIn(report["status"], ("installed", "found", "conflict", "failed"))

    @unittest.skipIf(os.name == "nt", "права доступа POSIX — на Windows это не тестируется")
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root игнорирует права доступа")
    def test_unsearchable_agent_dir_does_not_crash_the_sync(self):
        """Разбор 4/5, находка 2: 0o600 — iterdir() работает, а stat каждой
        записи нет; на Python 3.11/3.12 уборка (is_symlink/is_dir) и
        inspect_copy (is_symlink/exists) бросали PermissionError."""

        claude_skills = self.ws / ".claude" / "skills"
        stale = Path(tempfile.mkdtemp(prefix=f"{workspace_skills.TEMP_PREFIX}demo-",
                                      dir=str(self._mkdir(claude_skills))))
        old_time = time.time() - 7200
        os.utime(stale, (old_time, old_time))
        claude_skills.chmod(0o600)
        try:
            report = self.sync()
        finally:
            claude_skills.chmod(0o700)
        self.assertEqual(report["status"], "failed")
        failed = [item for item in report["items"] if item["path"].startswith(str(claude_skills))]
        self.assertEqual({item["status"] for item in failed}, {"failed"})
        self.assertTrue(stale.exists())  # недоступное не тронуто

    def test_failed_copy_message_is_russian_without_paths(self):
        with mock.patch.object(workspace_skills, "_copy",
                               side_effect=OSError(28, "No space left on device", str(self.ws))):
            report = self.sync()
        self.assertEqual({item["status"] for item in report["items"]}, {"failed"})
        for item in report["items"]:
            self.assertIn("не удалось скопировать скилл", item["message"])
            self.assertNotIn("No space", item["message"])
            self.assertNotIn(str(self.ws), item["message"])

    def test_unstatable_target_is_a_failed_item_not_a_crash(self):
        """То же без chmod — переносимо на любую ОС и версию Python."""

        denied = PermissionError(13, "Permission denied")
        with mock.patch.object(type(self.ws), "is_symlink", side_effect=denied):
            self.assertEqual(workspace_skills.inspect_copy(self.ws / "x", "v9.9.9"), "unreadable")
            report = self.sync()
        self.assertEqual({item["status"] for item in report["items"]}, {"failed"})
        self.assertIn("нет доступа", report["items"][0]["message"])

    @staticmethod
    def _mkdir(path: Path) -> Path:
        path.mkdir(parents=True)
        return path


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

    def test_case_variant_path_is_recognized_via_samefile(self):
        """Разбор 2/5, находка A: на регистронезависимой ФС (обычная APFS)
        Path.resolve() не меняет регистр — строковое сравнение путей это
        упускает, os.path.samefile (по st_dev/st_ino) — нет. Симулируем
        подменой samefile, чтобы тест не зависел от ФС хоста."""

        case_variant = self.base / "ДОМАШНЯЯ ПАПКА"
        real_samefile = os.path.samefile

        def fake_samefile(a, b):
            if {str(a), str(b)} == {str(case_variant), str(self.fake_home)}:
                return True
            return real_samefile(a, b)

        with mock.patch("pathlib.Path.home", return_value=self.fake_home), \
                mock.patch("os.path.samefile", side_effect=fake_samefile):
            report = workspace_skills.sync_workspace_skills(case_variant, pin=PIN)
        self.assertEqual(report["status"], "skipped_home")

    def test_root_level_match_is_caught_before_skills_subfolder_exists(self):
        """Разбор 3/5, находка 3: пока ~/.claude/skills не существует ни с
        той, ни с другой стороны, старое сравнение (только на подпапке
        skills, резолвнутой строкой) это пропускало — теперь сверяется и
        сам корень агента (.claude), где симлинк/регистр уже виден."""

        real_claude = self.fake_home / ".claude"
        real_claude.mkdir(parents=True)  # ~/.claude есть, ~/.claude/skills — нет
        other_ws = self.base / "другая рабочая папка"
        other_ws.mkdir()
        case_variant_claude = other_ws / ".claude"
        case_variant_claude.mkdir()  # «другой регистр» эмулируем через samefile, не реальную ФС
        real_samefile = os.path.samefile

        def fake_samefile(a, b):
            if {str(a), str(b)} == {str(case_variant_claude), str(real_claude)}:
                return True
            return real_samefile(a, b)

        with mock.patch("pathlib.Path.home", return_value=self.fake_home), \
                mock.patch("os.path.samefile", side_effect=fake_samefile):
            report = workspace_skills.sync_workspace_skills(other_ws, pin=PIN)
        self.assertEqual(report["status"], "skipped_home")

    def test_symlink_loop_in_agent_root_does_not_crash(self):
        """Разбор 3/5, находка 3: цикл символических ссылок — на Python
        3.11/3.12 Path.resolve() бросает RuntimeError, не OSError — не
        должен ронять проверку, только сказать «не совпало»."""

        loopy_ws = self.base / "рабочая папка с циклом"
        loopy_ws.mkdir()
        loop_link = loopy_ws / ".claude"
        try:
            os.symlink(loop_link, loop_link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("символические ссылки недоступны")
        (self.fake_home / ".claude").mkdir(parents=True)  # чтобы samefile дошёл до обеих сторон
        with mock.patch("pathlib.Path.home", return_value=self.fake_home):
            # Главное — не упасть с RuntimeError/OSError прямо из проверки
            # гварда; сам цикл симлинков ниже, при попытке скопировать в
            # .claude/skills, честно даёт status="failed" — это не крах.
            report = workspace_skills.sync_workspace_skills(loopy_ws, pin=PIN)
        self.assertIn(report["status"], ("installed", "skipped_home", "failed"))

    def test_no_home_env_is_treated_as_not_home(self):
        """Path.home() может бросить RuntimeError (HOME не определить) —
        тогда просто не можем сказать, что это она, а не падаем."""

        ws = self.base / "рабочая папка без HOME"
        ws.mkdir()
        with mock.patch("pathlib.Path.home", side_effect=RuntimeError("нет HOME")):
            report = workspace_skills.sync_workspace_skills(ws, pin=PIN)
        self.assertEqual(report["status"], "installed")

    def test_home_claude_itself_symlinked_elsewhere_is_still_detected(self):
        """Разбор 2/5, находка A: ~/.claude сам может быть симлинком (типично
        при управлении дотфайлами) — старое сравнение резолвило рабочую
        сторону, но не домашнюю, и пропускало этот случай."""

        dotfiles_claude = self.base / "dotfiles" / "claude"
        dotfiles_claude.mkdir(parents=True)
        try:
            os.symlink(dotfiles_claude, self.fake_home / ".claude", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("символические ссылки недоступны")
        other_ws = self.base / "другая рабочая папка"
        other_ws.mkdir()
        os.symlink(dotfiles_claude, other_ws / ".claude", target_is_directory=True)
        with mock.patch("pathlib.Path.home", return_value=self.fake_home):
            report = workspace_skills.sync_workspace_skills(other_ws, pin=PIN)
        self.assertEqual(report["status"], "skipped_home")


if __name__ == "__main__":
    unittest.main()

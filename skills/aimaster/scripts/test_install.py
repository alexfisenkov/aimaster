#!/usr/bin/env python3
"""Установщик install.py на временном HOME: ссылки, повтор, чужие папки,
форма --json и ветки Windows (junction → symlink → копия) через подмену."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import install  # noqa: E402

_REAL_SYMLINK = os.symlink


def _can_symlink(base: Path) -> bool:
    probe_src, probe = base / "probe-src", base / "probe-link"
    probe_src.mkdir()
    try:
        _REAL_SYMLINK(probe_src, probe, target_is_directory=True)
    except OSError:
        return False
    os.unlink(probe) if os.path.islink(probe) else os.rmdir(probe)
    return True


class _TempInstall:
    """Временные HOME и клон; запуск install.main с --json."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        # без /var → /private/var: пути в отчёте сравниваем как есть
        self.base = Path(temp.name).resolve()
        self.home = self.base / "дом пользователя"
        self.home.mkdir()
        self.repo = self.base / "клон aimaster"
        self.skill = self.repo / "skills" / "aimaster"
        (self.skill / "scripts").mkdir(parents=True)
        (self.skill / "SKILL.md").write_text("---\nname: aimaster\n---\n", encoding="utf-8")
        (self.skill / "VERSION").write_text("2099.01.01\n", encoding="utf-8")
        # зависимости в этих тестах не ищем и не ставим
        patcher = mock.patch.object(install, "check_deps", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        # раздел монтажа проверяется в test_install_montage.py; здесь — заглушка
        montage = mock.patch.object(install, "_montage_report",
                                    return_value={"ok": True, "node": {"status": "found", "message": ""}})
        self.montage = montage.start()
        self.addCleanup(montage.stop)
        self.symlinks = _can_symlink(self.base)

    def run_install(self, *extra):
        argv = ["--repo", str(self.repo), "--home", str(self.home), "--json",
                "--skip-self-check", *extra]
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = install.main(argv)
        return code, json.loads(buffer.getvalue())

    def target(self, agent="claude"):
        parts = {"claude": (".claude", "skills"), "codex": (".agents", "skills")}[agent]
        return self.home.joinpath(*parts) / "aimaster"

    def need_symlinks(self):
        if not self.symlinks:
            self.skipTest("символические ссылки недоступны в этой среде")


class InstallTests(_TempInstall, unittest.TestCase):
    # ---------- общий путь ----------

    def test_json_shape_and_links_created(self):
        self.need_symlinks()
        with mock.patch.object(install, "_is_windows", return_value=False):
            code, report = self.run_install()
        self.assertEqual(code, 0)
        for key in ("ok", "platform", "repo", "skill_dir", "python", "version", "targets",
                    "deps", "self_check", "python_cmd", "next_steps"):
            self.assertIn(key, report)
        self.assertTrue(report["ok"])
        self.assertEqual(report["version"], "2099.01.01")
        self.assertEqual([t["agent"] for t in report["targets"]], ["claude", "codex"])
        for item in report["targets"]:
            self.assertEqual(item["status"], "linked")
            self.assertEqual(item["method"], "symlink")
        for agent in ("claude", "codex"):
            self.assertTrue(os.path.islink(self.target(agent)))
            self.assertEqual(install._norm(self.target(agent)), install._norm(self.skill))

    def test_montage_section_is_reported_and_rendered(self):
        code, report = self.run_install("--install-deps")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["montage"]["ok"], True)
        kind, install_deps, update, home = self.montage.call_args.args
        self.assertEqual((kind, install_deps, update, home), (report["platform"], True, False, self.home))
        text = install.render_text({**report, "montage": {
            "ok": False, "node": {"status": "missing", "message": "Node.js не найден"}}})
        self.assertIn("Монтаж (HyperFrames): не готов", text)
        self.assertIn("Node.js не найден", text)

    def test_repeat_is_idempotent(self):
        self.need_symlinks()
        with mock.patch.object(install, "_is_windows", return_value=False):
            self.run_install()
            code, report = self.run_install()
        self.assertEqual(code, 0)
        self.assertEqual({t["status"] for t in report["targets"]}, {"already"})

    def test_agent_filter(self):
        self.need_symlinks()
        with mock.patch.object(install, "_is_windows", return_value=False):
            code, report = self.run_install("--agent", "claude")
        self.assertEqual(code, 0)
        self.assertEqual([t["agent"] for t in report["targets"]], ["claude"])
        self.assertFalse(self.target("codex").exists())

    def test_foreign_folder_is_never_touched(self):
        foreign = self.target()
        foreign.mkdir(parents=True)
        (foreign / "мой файл.txt").write_text("не трогать", encoding="utf-8")
        for extra in ((), ("--force",), ("--update",)):
            code, report = self.run_install("--agent", "claude", *extra)
            self.assertEqual(code, 1)
            self.assertFalse(report["ok"])
            self.assertEqual(report["targets"][0]["status"], "conflict")
        self.assertEqual((foreign / "мой файл.txt").read_text(encoding="utf-8"), "не трогать")

    def test_link_to_other_aimaster_needs_force(self):
        self.need_symlinks()
        other = self.base / "старый клон" / "skills" / "aimaster"
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text("---\nname: aimaster\n---\n", encoding="utf-8")
        self.target().parent.mkdir(parents=True)
        _REAL_SYMLINK(other, self.target(), target_is_directory=True)
        with mock.patch.object(install, "_is_windows", return_value=False):
            code, report = self.run_install("--agent", "claude")
            self.assertEqual(code, 1)
            self.assertEqual(report["targets"][0]["status"], "conflict")
            self.assertEqual(install._norm(self.target()), install._norm(other))
            code, report = self.run_install("--agent", "claude", "--force")
        self.assertEqual(code, 0)
        self.assertEqual(report["targets"][0]["status"], "refreshed")
        self.assertEqual(install._norm(self.target()), install._norm(self.skill))
        self.assertTrue((other / "SKILL.md").is_file(), "старый клон не должен пострадать")

    def test_link_to_unrelated_folder_is_foreign_even_with_force(self):
        self.need_symlinks()
        unrelated = self.base / "чужое"
        unrelated.mkdir()
        self.target().parent.mkdir(parents=True)
        _REAL_SYMLINK(unrelated, self.target(), target_is_directory=True)
        code, report = self.run_install("--agent", "claude", "--force")
        self.assertEqual(code, 1)
        self.assertEqual(report["targets"][0]["status"], "conflict")

    def test_missing_repo_is_reported(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = install.main(["--repo", str(self.base / "нет такого"), "--json",
                                 "--home", str(self.home)])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(buffer.getvalue())["error"], "repo_not_found")

    def test_old_python_prints_exact_command(self):
        with mock.patch.object(install, "_version_info", return_value=(3, 10, 4)), \
                mock.patch.object(install, "_is_windows", return_value=True):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = install.main(["--json"])
        self.assertEqual(code, 2)
        report = json.loads(buffer.getvalue())
        self.assertEqual(report["error"], "python_too_old")
        self.assertEqual(report["install_cmd"], "winget install -e --id Python.Python.3.12")

    # ---------- Windows ----------

    def fake_winapi(self, succeed, leave_partial=False):
        calls = []

        class FakeWinapi:
            @staticmethod
            def CreateJunction(source, target):
                calls.append((source, target))
                if succeed:
                    _REAL_SYMLINK(source, target, target_is_directory=True)  # как junction
                    return
                if leave_partial:
                    os.mkdir(target)  # CreateJunction успел создать пустую папку
                raise OSError("Отказано в доступе")
        return calls, FakeWinapi

    def test_windows_uses_junction_first_without_a_shell(self):
        self.need_symlinks()
        calls, winapi = self.fake_winapi(succeed=True)
        with mock.patch.object(install, "_is_windows", return_value=True), \
                mock.patch.object(install, "_winapi_module", return_value=winapi), \
                mock.patch.object(install.subprocess, "run") as run:
            code, report = self.run_install("--agent", "claude")
        self.assertEqual(code, 0)
        self.assertEqual(report["platform"], "windows")
        self.assertEqual(report["targets"][0]["method"], "junction")
        self.assertEqual(calls, [(str(self.skill.resolve()), str(self.target()))])
        # ни cmd, ни другой оболочки (запуски python для python_cmd не в счёт)
        for call in run.call_args_list:
            command = call.args[0] if call.args else call.kwargs.get("args")
            text = command if isinstance(command, str) else " ".join(map(str, command))
            self.assertNotIn("mklink", text.lower())
            self.assertNotIn("cmd.exe", text.lower())

    def test_windows_falls_back_to_symlink_and_cleans_the_partial_junction(self):
        self.need_symlinks()
        _, winapi = self.fake_winapi(succeed=False, leave_partial=True)
        with mock.patch.object(install, "_is_windows", return_value=True), \
                mock.patch.object(install, "_winapi_module", return_value=winapi):
            code, report = self.run_install("--agent", "claude")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["targets"][0]["method"], "symlink")
        self.assertTrue(os.path.islink(self.target()))
        self.assertEqual(install._norm(self.target()), install._norm(self.skill))

    def test_windows_falls_back_to_marked_copy_and_update_refreshes_it(self):
        _, winapi = self.fake_winapi(succeed=False)
        with mock.patch.object(install, "_is_windows", return_value=True), \
                mock.patch.object(install, "_winapi_module", return_value=winapi), \
                mock.patch.object(install, "_make_symlink", side_effect=OSError("нет прав")), \
                mock.patch.object(install, "git_update", return_value={"status": "skipped",
                                                                       "message": "не git"}):
            code, report = self.run_install("--agent", "claude")
            self.assertEqual(code, 0)
            item = report["targets"][0]
            self.assertEqual(item["method"], "copy")
            self.assertIn("--update", item["message"])
            self.assertTrue(any("--update" in step for step in report["next_steps"]))
            marker = json.loads((self.target() / install.MARKER).read_text(encoding="utf-8"))
            self.assertEqual(marker["method"], "copy")
            self.assertFalse(os.path.islink(self.target()))
            copied = str(self.target() / "scripts" / "install.py")
            with mock.patch.object(install, "__file__", copied):
                self.assertEqual(install.default_repo(), self.repo.resolve())

            code, report = self.run_install("--agent", "claude")
            self.assertEqual(report["targets"][0]["status"], "already")

            (self.skill / "VERSION").write_text("2099.02.02\n", encoding="utf-8")
            code, report = self.run_install("--agent", "claude", "--update")
        self.assertEqual(code, 0)
        self.assertEqual(report["targets"][0]["status"], "refreshed")
        self.assertEqual((self.target() / "VERSION").read_text(encoding="utf-8").strip(),
                         "2099.02.02")

    def test_windows_python_cmd_prefers_py_launcher(self):
        which = {"py": "C:/Windows/py.exe", "python": "C:/Python312/python.exe"}
        with mock.patch.object(install, "_is_windows", return_value=True), \
                mock.patch.object(install, "_find_program", side_effect=which.get), \
                mock.patch.object(install, "_probe_python", return_value=(3, 12)) as probe:
            self.assertEqual(install.python_cmd(), "py -3")
        # проверяется программа по полному пути, не голое имя
        probe.assert_called_once_with(["C:/Windows/py.exe", "-3"])

    def test_old_py_launcher_is_skipped(self):
        which = {"py": "C:/Windows/py.exe", "python": "C:/Python312/python.exe"}
        versions = {"C:/Windows/py.exe": (3, 10), "C:/Python312/python.exe": (3, 12)}
        with mock.patch.object(install, "_is_windows", return_value=True), \
                mock.patch.object(install, "_find_program", side_effect=which.get), \
                mock.patch.object(install, "_probe_python", side_effect=lambda a: versions[a[0]]):
            self.assertEqual(install.python_cmd(), "python")


    def test_print_python_cmd_installs_nothing(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = install.main(["--print-python-cmd", "--json", "--home", str(self.home)])
        self.assertEqual(code, 0)
        self.assertEqual(set(json.loads(buffer.getvalue())), {"python_cmd"})
        self.assertEqual(list(self.home.iterdir()), [])


class JunctionCommandTests(unittest.TestCase):
    """Запасной путь через cmd.exe (если в _winapi нет CreateJunction)."""

    def test_cmd_metacharacters_are_refused_before_any_process_starts(self):
        for bad in (r"C:\a\R&D\x", r"C:\a\&calc&\x", r"C:\a\100%PATH%", r"C:\a\b^c",
                    r"C:\a\b!c", r"C:\a\b|c", r"C:\a\b<c>"):
            with mock.patch.object(install, "_winapi_module", return_value=None), \
                    mock.patch.object(install, "_run") as run:
                with self.assertRaisesRegex(OSError, "cmd.exe"):
                    install._make_junction(r"C:\clone\skills\aimaster", bad)
                run.assert_not_called()

    def test_safe_path_uses_system_cmd_with_quotes(self):
        with mock.patch.dict(os.environ, {"SystemRoot": r"C:\Windows"}):
            command = install._mklink_command(r"C:\мой клон\skills\aimaster",
                                              r"C:\Users\Анна Иванова\.claude\skills\aimaster")
        self.assertTrue(command.startswith('"' + os.path.join(r"C:\Windows", "System32", "cmd.exe") + '" /d /c mklink /J '))
        self.assertIn('"C:\\Users\\Анна Иванова\\.claude\\skills\\aimaster" "C:\\мой клон\\skills\\aimaster"',
                      command)

    @unittest.skipUnless(os.name == "nt", "junction есть только на Windows")
    def test_real_junction_for_a_path_with_ampersand_and_percent(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "R&D %PATH% клон"
            source.mkdir()
            (source / "SKILL.md").write_text("name: aimaster", encoding="utf-8")
            target = Path(temp) / "R&D навыки" / "aimaster"
            target.parent.mkdir()
            install._make_junction(source, target)
            self.assertTrue(install._is_link_like(target))
            self.assertEqual(install._norm(target), install._norm(source))
            install._remove_link(target)
            self.assertTrue((source / "SKILL.md").is_file())


class ProgramLookupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.cwd_dir = self.base / "папка проекта"
        self.bin_dir = self.base / "Program Files" / "Git" / "cmd"
        self.cwd_dir.mkdir()
        self.bin_dir.mkdir(parents=True)
        previous = os.getcwd()
        os.chdir(self.cwd_dir)
        self.addCleanup(os.chdir, previous)

    def _plant(self, folder, name):
        path = folder / name
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def test_windows_lookup_skips_cwd_and_relative_path_entries(self):
        self._plant(self.cwd_dir, "git.exe")  # подложенный в текущую папку
        real = self._plant(self.bin_dir, "git.exe")
        self._plant(self.bin_dir, "evil.bat")
        path = os.pathsep.join([".", "", "relative\\bin", str(self.bin_dir)])
        with mock.patch.object(install, "_is_windows", return_value=True), \
                mock.patch.dict(os.environ, {"PATH": path}):
            self.assertEqual(install._find_program("git"), str(real))
            self.assertIsNone(install._find_program("evil"), "bat/cmd не запускаем")
            self.assertIsNone(install._find_program("nosuch"))

    def test_posix_lookup_skips_cwd_and_relative_path_entries(self):
        self._plant(self.cwd_dir, "git")
        with mock.patch.object(install, "_is_windows", return_value=False), \
                mock.patch.dict(os.environ, {"PATH": os.pathsep.join([".", ""])}):
            self.assertIsNone(install._find_program("git"))
        real = self._plant(self.bin_dir, "git")
        with mock.patch.object(install, "_is_windows", return_value=False), \
                mock.patch.dict(os.environ, {"PATH": os.pathsep.join([".", str(self.bin_dir)])}):
            found = install._find_program("git")
        if os.name != "nt":
            self.assertEqual(found, str(real))


class ReplaceAndFailureTests(_TempInstall, unittest.TestCase):
    """Замена копии без окна «навыка нет» и JSON вместо трейсбека."""

    def install_copy(self):
        with mock.patch.object(install, "_is_windows", return_value=False), \
                mock.patch.object(install, "_make_symlink", side_effect=OSError("нет прав")):
            code, report = self.run_install("--agent", "claude")
        self.assertEqual(report["targets"][0]["method"], "copy")
        return code, report

    def run_update(self, **patches):
        with mock.patch.object(install, "_is_windows", return_value=False), \
                mock.patch.object(install, "_make_symlink", side_effect=OSError("нет прав")), \
                mock.patch.object(install, "git_update",
                                  return_value={"status": "skipped", "message": "не git"}):
            if patches:
                with mock.patch.multiple(install, **patches):
                    return self.run_install("--agent", "claude", "--update")
            return self.run_install("--agent", "claude", "--update")

    def leftovers(self):
        return [p.name for p in self.target().parent.iterdir() if p.name != "aimaster"]

    def test_update_from_inside_the_copy_moves_cwd_out_and_swaps(self):
        self.install_copy()
        (self.skill / "VERSION").write_text("2099.03.03\n", encoding="utf-8")
        inside = self.target() / "scripts"
        previous = os.getcwd()
        os.chdir(inside)
        self.addCleanup(os.chdir, previous)
        code, report = self.run_update()
        self.assertEqual(code, 0, report)
        self.assertEqual(report["targets"][0]["status"], "refreshed")
        self.assertFalse(install._inside(os.getcwd(), self.target()))
        self.assertTrue((self.target() / install.MARKER).is_file())
        self.assertEqual((self.target() / "VERSION").read_text(encoding="utf-8").strip(),
                         "2099.03.03")
        self.assertEqual(self.leftovers(), [])

    def test_failed_swap_keeps_the_old_copy_and_reports_json(self):
        self.install_copy()
        (self.skill / "VERSION").write_text("2099.04.04\n", encoding="utf-8")
        real_rename = os.rename

        def locked(source, target):
            if Path(source) == self.target():
                raise PermissionError(32, "Процесс не может получить доступ к файлу")
            return real_rename(source, target)

        with mock.patch.object(install.os, "rename", side_effect=locked):
            code, report = self.run_update()
        self.assertEqual(code, 1)
        item = report["targets"][0]
        self.assertEqual(item["status"], "failed")
        self.assertIn("Прежняя версия оставлена", item["message"])
        self.assertTrue((self.target() / install.MARKER).is_file(), "копия осталась своей")
        self.assertEqual((self.target() / "VERSION").read_text(encoding="utf-8").strip(),
                         "2099.01.01")
        self.assertEqual(self.leftovers(), [])

    def test_failed_second_rename_puts_the_old_copy_back(self):
        self.install_copy()
        real_rename = os.rename

        def second_fails(source, target):
            if Path(source).name == "new":
                raise PermissionError(5, "Отказано в доступе")
            return real_rename(source, target)

        with mock.patch.object(install.os, "rename", side_effect=second_fails):
            code, report = self.run_update()
        self.assertEqual(report["targets"][0]["status"], "failed")
        self.assertTrue((self.target() / install.MARKER).is_file())
        self.assertEqual(self.leftovers(), [])

    def test_copy_failure_is_json_not_a_traceback_and_leaves_nothing(self):
        def broken_copy(source, target, version):
            Path(target).mkdir()
            (Path(target) / "половина").write_text("x", encoding="utf-8")
            raise OSError(28, "На диске недостаточно места")

        with mock.patch.object(install, "_is_windows", return_value=False), \
                mock.patch.object(install, "_make_symlink", side_effect=OSError("нет прав")), \
                mock.patch.object(install, "_make_copy", side_effect=broken_copy):
            code, report = self.run_install("--agent", "claude")
        self.assertEqual(code, 1)
        self.assertFalse(report["ok"])
        item = report["targets"][0]
        self.assertEqual(item["status"], "failed")
        self.assertIn("недостаточно места", item["message"])
        self.assertFalse(os.path.lexists(self.target()))


class GitUpdateTests(unittest.TestCase):
    def test_origin_forms_are_normalized(self):
        official = install.normalize_origin(install.OFFICIAL_ORIGIN)
        for url in ("https://github.com/alexfisenkov/aimaster.git",
                    "https://github.com/alexfisenkov/aimaster",
                    "https://github.com/alexfisenkov/aimaster/",
                    "https://github.com/AlexFisenkov/aimaster.git\n",
                    "git@github.com:alexfisenkov/aimaster.git",
                    "git@github.com:alexfisenkov/aimaster",
                    "ssh://git@github.com/alexfisenkov/aimaster.git"):
            self.assertEqual(install.normalize_origin(url), official, url)
        for url in ("https://github.com/someone/aimaster.git",
                    "https://github.com.evil.example/alexfisenkov/aimaster",
                    "git@gitlab.com:alexfisenkov/aimaster.git",
                    "https://github.com/alexfisenkov/aimaster-fork", ""):
            self.assertNotEqual(install.normalize_origin(url), official, url)

    def fake_git(self, origin):
        replies = {
            "rev-parse": (0, "true\n", ""), "get-url": (0, origin + "\n", ""),
            "symbolic-ref": (0, "main\n", ""), "--porcelain": (0, "", ""),
            "pull": (0, "", ""), "fetch": (0, "", ""), "describe": (0, "v2099.01.01\n", ""),
        }
        calls = []

        def run(argv, **kwargs):
            calls.append(list(argv))
            for key, reply in replies.items():
                if key in argv:
                    return reply
            return (1, "", "unexpected")
        return calls, run

    def test_ssh_clone_updates_with_explicit_origin_main_and_full_git_path(self):
        calls, run = self.fake_git("git@github.com:alexfisenkov/aimaster.git")
        with mock.patch.object(install, "_find_program", return_value="C:/Git/cmd/git.exe"), \
                mock.patch.object(install, "_run", side_effect=run):
            result = install.git_update(Path("C:/aimaster"))
        self.assertEqual(result["status"], "updated", result)
        self.assertEqual(result["tag"], "v2099.01.01")
        self.assertTrue(all(call[0] == "C:/Git/cmd/git.exe" for call in calls))
        pull = [call for call in calls if "pull" in call][0]
        self.assertEqual(pull[-4:], ["pull", "--ff-only", "origin", "main"])

    def test_foreign_origin_is_blocked_before_pull(self):
        calls, run = self.fake_git("https://github.com/someone/aimaster.git")
        with mock.patch.object(install, "_find_program", return_value="/usr/bin/git"), \
                mock.patch.object(install, "_run", side_effect=run):
            result = install.git_update(Path("/tmp/aimaster"))
        self.assertEqual(result["status"], "blocked")
        self.assertFalse([call for call in calls if "pull" in call])


class InstallerTimeoutTests(unittest.TestCase):
    def test_timeout_and_uac_failures_become_clear_statuses(self):
        replies = iter([(install.TIMEOUT_CODE, "", "не завершилась"),
                        (0x8A150056 & 0x7FFFFFFF, "", "Установка отменена пользователем"),
                        (0, "", "")])
        with mock.patch.object(install, "_which", return_value=None), \
                mock.patch.object(install, "_find_program", return_value="C:/winget.exe"), \
                mock.patch.object(install, "_run", side_effect=lambda *a, **k: next(replies)):
            report = {d["name"]: d for d in install.check_deps("windows", install=True)}
        self.assertEqual(report["ffmpeg"]["install_status"], "timeout")
        self.assertIs(report["ffmpeg"]["installed"], False)
        self.assertIn("winget install -e --id Gyan.FFmpeg", report["ffmpeg"]["message"])
        self.assertEqual(report["ffprobe"]["install_status"], "timeout")
        self.assertEqual(report["cloudflared"]["install_status"], "failed")
        self.assertIn("UAC", report["cloudflared"]["message"])
        self.assertEqual(report["git"]["install_status"], "installed")

    def test_run_reports_timeout_with_its_own_code(self):
        code, _, err = install._run([sys.executable, "-c", "import time; time.sleep(5)"],
                                    timeout=0.5)
        self.assertEqual(code, install.TIMEOUT_CODE)
        self.assertIn("0.5", err)


class DepsTests(unittest.TestCase):
    def test_missing_deps_are_listed_not_installed(self):
        with mock.patch.object(install, "_which", return_value=None), \
                mock.patch.object(install, "_run") as run:
            report = install.check_deps("windows", install=False)
        run.assert_not_called()
        names = [d["name"] for d in report]
        # Node.js теперь зависимость монтажа: его проверяет install_montage.py
        self.assertEqual(names, ["ffmpeg", "ffprobe", "cloudflared", "git"])
        self.assertTrue(all(not d["found"] and d["installed"] is None for d in report))
        self.assertEqual(report[0]["install_cmd"], "winget install -e --id Gyan.FFmpeg")

    def test_install_deps_runs_winget_once_per_package(self):
        with mock.patch.object(install, "_which", return_value=None), \
                mock.patch.object(install, "_find_program", return_value="C:/winget.exe"), \
                mock.patch.object(install, "_run", return_value=(0, "", "")) as run:
            report = install.check_deps("windows", install=True)
        ids = [call.args[0][4] for call in run.call_args_list]
        self.assertEqual(ids, ["Gyan.FFmpeg", "Cloudflare.cloudflared", "Git.Git"])
        for call in run.call_args_list:
            argv = call.args[0]
            self.assertEqual(argv[0], "C:/winget.exe")
            self.assertIn("--disable-interactivity", argv)
            self.assertEqual(call.kwargs["timeout"], install.INSTALL_TIMEOUT)
        self.assertNotIn("node", [d["name"] for d in report])
        self.assertIn("новый терминал", report[0]["message"])

    def test_linux_never_installs(self):
        with mock.patch.object(install, "_which", return_value=None), \
                mock.patch.object(install, "_run") as run:
            report = install.check_deps("linux", install=True)
        run.assert_not_called()
        self.assertEqual(report[0]["install_cmd"], "sudo apt install ffmpeg")
        self.assertFalse(report[0]["installed"])


class SelfCheckTests(unittest.TestCase):
    def test_self_check_on_real_skill_passes(self):
        checks = install.self_check(_SCRIPTS.parent)
        self.assertEqual([c["name"] for c in checks],
                         ["import studio", "creator_studio.py --help",
                          "detect_tools.py --json", "workspace init"])
        failed = [c for c in checks if not c["ok"]]
        self.assertEqual(failed, [], failed)


if __name__ == "__main__":
    unittest.main()

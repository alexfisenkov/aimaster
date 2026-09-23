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


class InstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
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

    def fake_mklink(self, succeed):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            if argv[:4] == ["cmd", "/c", "mklink", "/J"] and succeed:
                _REAL_SYMLINK(argv[5], argv[4], target_is_directory=True)  # как junction
                return subprocess.CompletedProcess(argv, 0, b"Junction created", b"")
            return subprocess.CompletedProcess(argv, 1, b"", "Отказано в доступе".encode())
        return calls, fake_run

    def test_windows_uses_junction_first(self):
        self.need_symlinks()
        calls, fake_run = self.fake_mklink(succeed=True)
        with mock.patch.object(install, "_is_windows", return_value=True), \
                mock.patch.object(install.subprocess, "run", side_effect=fake_run):
            code, report = self.run_install("--agent", "claude")
        self.assertEqual(code, 0)
        self.assertEqual(report["platform"], "windows")
        self.assertEqual(report["targets"][0]["method"], "junction")
        mklink = [c for c in calls if c[:2] == ["cmd", "/c"]]
        self.assertEqual(mklink, [["cmd", "/c", "mklink", "/J", str(self.target()), str(self.skill.resolve())]])

    def test_windows_falls_back_to_symlink(self):
        self.need_symlinks()
        _, fake_run = self.fake_mklink(succeed=False)
        with mock.patch.object(install, "_is_windows", return_value=True), \
                mock.patch.object(install.subprocess, "run", side_effect=fake_run):
            code, report = self.run_install("--agent", "claude")
        self.assertEqual(code, 0)
        self.assertEqual(report["targets"][0]["method"], "symlink")

    def test_windows_falls_back_to_marked_copy_and_update_refreshes_it(self):
        _, fake_run = self.fake_mklink(succeed=False)
        with mock.patch.object(install, "_is_windows", return_value=True), \
                mock.patch.object(install.subprocess, "run", side_effect=fake_run), \
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
                mock.patch.object(install.shutil, "which", side_effect=which.get), \
                mock.patch.object(install, "_probe_python", return_value=(3, 12)):
            self.assertEqual(install.python_cmd(), "py -3")

    def test_old_py_launcher_is_skipped(self):
        which = {"py": "C:/Windows/py.exe", "python": "C:/Python312/python.exe"}
        versions = {"py": (3, 10), "python": (3, 12)}
        with mock.patch.object(install, "_is_windows", return_value=True), \
                mock.patch.object(install.shutil, "which", side_effect=which.get), \
                mock.patch.object(install, "_probe_python", side_effect=lambda a: versions[a[0]]):
            self.assertEqual(install.python_cmd(), "python")


class DepsTests(unittest.TestCase):
    def test_missing_deps_are_listed_not_installed(self):
        with mock.patch.object(install, "_which", return_value=None), \
                mock.patch.object(install, "_run") as run:
            report = install.check_deps("windows", install=False)
        run.assert_not_called()
        names = [d["name"] for d in report]
        self.assertEqual(names, ["ffmpeg", "ffprobe", "cloudflared", "git", "node"])
        self.assertTrue(all(not d["found"] and d["installed"] is None for d in report))
        self.assertEqual(report[0]["install_cmd"], "winget install -e --id Gyan.FFmpeg")

    def test_install_deps_runs_winget_once_per_package_and_never_node(self):
        with mock.patch.object(install, "_which", return_value=None), \
                mock.patch.object(install.shutil, "which", return_value="C:/winget.exe"), \
                mock.patch.object(install, "_run", return_value=(0, "", "")) as run:
            report = install.check_deps("windows", install=True)
        ids = [call.args[0][4] for call in run.call_args_list]
        self.assertEqual(ids, ["Gyan.FFmpeg", "Cloudflare.cloudflared", "Git.Git"])
        node = report[-1]
        self.assertIsNone(node["installed"])
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

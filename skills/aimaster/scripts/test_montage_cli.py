#!/usr/bin/env python3
"""CLI montage: разбор аргументов, вызов service, один JSON, код 3 без traceback."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import creator_studio  # noqa: E402
import creator_studio_montage  # noqa: E402
from montage_testkit import seed_workspace, tiny_mp4, video_state  # noqa: E402
from studio.montage import MontageError  # noqa: E402
from studio.montage.edit import EditRequest  # noqa: E402
from studio.montage.engine import PREFIX_ENV  # noqa: E402

SUBCOMMANDS = ("draft", "status", "diff", "edit", "render", "restore", "gsap", "open", "close")


def parse(*argv):
    return creator_studio.build_parser().parse_args(list(argv))


def run_main(*argv):
    """creator_studio.main() как из оболочки: (код выхода, stdout, stderr)."""

    out, err = io.StringIO(), io.StringIO()
    code = 0
    with mock.patch.object(sys, "argv", ["creator_studio.py", *argv]), redirect_stdout(out), \
            redirect_stderr(err):
        try:
            creator_studio.main()
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_every_subcommand_parses(self):
        args = parse("montage", "draft", "WS", "p", "--expected-revision", "3", "--refresh", "--json")
        self.assertEqual((args.subcommand, args.expected_revision, args.refresh, args.rebuild),
                         ("draft", 3, True, False))
        args = parse("montage", "edit", "WS", "p", "trim-start", "--clip", "v-1", "--seconds", "0.5",
                     "--expected-revision", "2", "--expected-model-hash", "abc")
        self.assertEqual((args.op, args.clip, args.seconds, args.expected_model_hash),
                         ("trim-start", "v-1", 0.5, "abc"))
        self.assertEqual(parse("montage", "restore", "WS", "p", "v001", "--expected-revision", "4").version,
                         "v001")
        for name in ("status", "diff", "gsap", "open", "close"):
            self.assertEqual(parse("montage", name, "WS", "p").subcommand, name)
        self.assertEqual(parse("montage", "gsap", "WS", "p", "--plugin", "SplitText", "--plugin", "Flip").plugin,
                         ["SplitText", "Flip"])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse("montage", "render", "WS", "p")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse("montage", "draft", "WS", "p", "--expected-revision", "1", "--refresh", "--rebuild")

    def test_every_writing_command_requires_the_revision(self):
        for argv in (("draft",), ("edit", "undo"), ("render",), ("restore", "v001")):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                parse("montage", argv[0], "WS", "p", *argv[1:])

    def run_handler(self, name, *argv):
        buffer = io.StringIO()
        with mock.patch.object(creator_studio_montage.service, name, return_value={"ok": 1}) as call, \
                redirect_stdout(buffer):
            args = parse("montage", *argv)
            args.handler(args)
        return call, json.loads(buffer.getvalue())

    def test_handlers_call_service_and_print_json(self):
        call, printed = self.run_handler("render", "render", "WS", "p", "--expected-revision", "2",
                                         "--by", "owner")
        self.assertEqual(printed, {"ok": 1})
        call.assert_called_once_with(Path("WS"), "p", 2, by="owner", summary=None)
        call, _ = self.run_handler("draft", "draft", "WS", "p", "--expected-revision", "0", "--rebuild")
        call.assert_called_once_with(Path("WS"), "p", 0, mode="rebuild")
        call, _ = self.run_handler("restore", "restore", "WS", "p", "v002", "--expected-revision", "7")
        call.assert_called_once_with(Path("WS"), "p", 7, "v002")
        call, _ = self.run_handler("open_desk", "open", "WS", "p")
        call.assert_called_once_with(Path("WS"), "p")
        call, _ = self.run_handler("close_desk", "close", "WS", "p")
        call.assert_called_once_with(Path("WS"), "p")
        call, _ = self.run_handler("gsap", "gsap", "WS", "p", "--plugin", "SplitText")
        call.assert_called_once_with(Path("WS"), "p", plugins=["SplitText"])
        call, _ = self.run_handler("diff", "diff", "WS", "p", "--against", "v001")
        call.assert_called_once_with(Path("WS"), "p", against="v001")
        call, _ = self.run_handler("status", "status", "WS", "p", "--json")
        call.assert_called_once_with(Path("WS"), "p")

    def test_edit_builds_the_request(self):
        call, _ = self.run_handler("edit", "edit", "WS", "p", "volume", "--clip", "a-voice",
                                   "--value", "0.5", "--expected-revision", "3")
        call.assert_called_once_with(Path("WS"), "p", 3, EditRequest(op="volume", clip="a-voice", value=0.5),
                                     expected_model_hash=None)
        call, _ = self.run_handler("edit", "edit", "WS", "p", "title-add", "--text", "Барсик",
                                   "--at", "0.2", "--duration", "1.5", "--expected-revision", "3")
        call.assert_called_once_with(
            Path("WS"), "p", 3, EditRequest(op="title-add", at=0.2, duration=1.5, text="Барсик"),
            expected_model_hash=None)

    def test_domain_error_exits_3_without_traceback(self):
        with mock.patch.object(creator_studio_montage.service, "status",
                               side_effect=MontageError("Монтажный движок не готов: не найден Node.js")):
            code, out, err = run_main("montage", "status", "WS", "p")
        self.assertEqual((code, out), (3, ""))
        self.assertIn("не готов", err)
        self.assertNotIn("Traceback", err)


class CliWorkspaceTests(unittest.TestCase):
    """Настоящая рабочая папка, без движка: status отвечает одним JSON, отказы — код 3."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name).resolve()
        environ = mock.patch.dict(os.environ, {PREFIX_ENV: str(base / "нет движка" / "hyperframes")})
        environ.start()
        self.addCleanup(environ.stop)
        self.seed = seed_workspace(base, {"a.mp4": tiny_mp4(b"a")}, lambda ids: video_state(
            [("s1", "Сад", "Барсик идёт по саду", 2000, ids["a.mp4"])]))
        self.ws = str(self.seed.workspace)

    def test_status_without_engine_is_one_json_object_with_the_install_command(self):
        code, out, err = run_main("montage", "status", self.ws, "p", "--json")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertEqual(payload["engine"]["state"], "missing")
        self.assertIn("--install-deps", payload["engine"]["install"])

    def test_refusals_exit_3(self):
        for argv, text in ((("draft", "--expected-revision", "0"), "Монтажный движок не готов"),
                           (("draft", "--expected-revision", "5"), "revision"),
                           (("restore", "v001", "--expected-revision", "0"), "нет версии v001"),
                           (("diff",), "черновика ещё нет")):
            with self.subTest(argv=argv):
                code, out, err = run_main("montage", argv[0], self.ws, "p", *argv[1:])
                self.assertEqual((code, out), (3, ""))
                self.assertIn(text, err)
                self.assertNotIn("Traceback", err)

    def test_help_lists_the_nine_subcommands(self):
        proc = subprocess.run([sys.executable, str(_SCRIPTS / "creator_studio.py"), "montage", "--help"],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=60, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = proc.stdout.decode("utf-8")
        for name in SUBCOMMANDS:
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()

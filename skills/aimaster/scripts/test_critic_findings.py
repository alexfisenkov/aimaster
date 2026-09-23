#!/usr/bin/env python3
"""Находки критика кода по движку автопилота (2026-09-23), каждая — тестом.

Все проверки локальные: синтетическая рабочая папка во временном каталоге,
провайдеры не вызываются.
"""

from __future__ import annotations

import io
import json
import sqlite3
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib
from contextlib import closing, redirect_stdout
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import creator_studio  # noqa: E402
import detect_tools  # noqa: E402
from studio import authoring  # noqa: E402
from studio.ledger import ActionLedger  # noqa: E402
from studio.library import LibraryError  # noqa: E402
from studio.runner import open_ledger, open_runner  # noqa: E402


def cli(*argv):
    args = creator_studio.build_parser().parse_args([str(item) for item in argv])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        args.handler(args)
    return json.loads(buffer.getvalue())


def png_bytes(red=200):
    rows = b"".join(b"\x00" + bytes([red, 120, 60] * 8) for _ in range(8))

    def chunk(tag, payload):
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.ws = self.root / "ws"
        cli("workspace", "init", self.ws)
        self.store = authoring.open_store(self.ws)

    def rev(self, pid):
        return self.store.load(pid)["revision"]

    def enqueue(self, pid, key, action="vary", target="scene-1"):
        return cli("action", "enqueue", self.ws, pid, "--type", action, "--target", target,
                   "--expected-revision", self.rev(pid), "--idempotency-key", key)

    def grants(self):
        with closing(sqlite3.connect(self.ws / ".studio" / "actions.sqlite3")) as db:
            return db.execute("SELECT issued_by, reserved_action_id FROM grants").fetchall()


class AutopilotGrantLeakTests(Base):
    """Находка 1: автопилотное разрешение не должно доставаться guided."""

    def test_refused_claim_does_not_hand_autopilot_grant_to_guided(self):
        cli("project", "create", self.ws, "p", "--title", "P", "--type", "photo", "--mode", "autopilot")
        self.assertEqual(self.enqueue("p", "k1")["status"], "queued")
        self.assertIsNone(open_runner(self.ws).claim("w"))  # vary is not allowed at this stage
        cli("mode", "set", self.ws, "p", "--mode", "guided", "--expected-revision", self.rev("p"))
        second = self.enqueue("p", "k2")
        self.assertEqual(second["status"], "needs_chat")
        self.assertIsNone(second["grant_id"])

    def test_switch_to_guided_cancels_queued_autopilot_actions(self):
        cli("project", "create", self.ws, "p", "--title", "P", "--type", "photo", "--mode", "autopilot")
        queued = self.enqueue("p", "k1")
        out = cli("mode", "set", self.ws, "p", "--mode", "guided", "--expected-revision", self.rev("p"))
        self.assertEqual(out["cancelled_actions"], [queued["action_id"]])
        statuses = {a["action_id"]: a["status"] for a in open_ledger(self.ws).latest_actions_by_target("p")}
        self.assertEqual(statuses[queued["action_id"]], "needs_chat")

    def test_claim_refuses_autopilot_grant_after_mode_left_autopilot(self):
        cli("project", "create", self.ws, "p", "--title", "P", "--type", "photo", "--mode", "autopilot")
        self.enqueue("p", "k1")

        def to_guided(state):
            state["project"]["mode"] = "guided"  # a path that skipped the cancel hook

        self.store.transact("p", self.rev("p"), to_guided)
        self.assertIsNone(open_runner(self.ws).claim("w"))
        self.assertEqual([row[0] for row in self.grants()], ["autopilot"])
        self.assertIsNotNone(self.grants()[0][1])  # voided, never back in circulation

    def test_guided_never_reserves_an_autopilot_grant_row(self):
        cli("project", "create", self.ws, "g", "--title", "G", "--type", "photo")
        ledger = open_ledger(self.ws)
        with closing(sqlite3.connect(self.ws / ".studio" / "actions.sqlite3")) as db:
            db.execute("INSERT INTO grants (grant_id, project_id, action_class, expires_at, "
                       "expires_epoch, issued_at, issued_by) VALUES ('grant-x', 'g', 'vary', "
                       "'2999-01-01T00:00:00Z', 32472144000, '2026-01-01T00:00:00Z', 'autopilot')")
            db.commit()
        self.assertIsNone(ledger.grant_issuer("grant-y"))
        self.assertEqual(self.enqueue("g", "k1")["status"], "needs_chat")


class MatchBrandTests(Base):
    """Находка 2: бренд в подписи стиля не должен находить стиль."""

    def test_brand_does_not_match_style_caption(self):
        source = self.root / "look.png"
        source.write_bytes(png_bytes(9))
        cli("library", "add", self.ws, "--kind", "style", "--label",
            "AI Мастерская — dark boho riding look", "--file", source)
        found = cli("library", "match", self.ws, "--text", "ролик для AI Мастерской")
        self.assertEqual(found["count"], 0)
        full = cli("library", "match", self.ws, "--text", "стиль AI Мастерская dark boho riding look")
        self.assertEqual(full["count"], 1)


class EnqueueKeyTests(Base):
    """Находка 3: ключ повтора обязателен, дубль на ту же цель — отказ."""

    def test_key_is_required(self):
        cli("project", "create", self.ws, "p", "--title", "P", "--type", "photo", "--mode", "autopilot")
        with self.assertRaisesRegex(ValueError, "idempotency-key"):
            cli("action", "enqueue", self.ws, "p", "--type", "vary", "--target", "scene-1",
                "--expected-revision", self.rev("p"))

    def test_second_pending_action_on_same_target_is_refused(self):
        cli("project", "create", self.ws, "p", "--title", "P", "--type", "photo", "--mode", "autopilot")
        first = self.enqueue("p", "k1")
        replay = cli("action", "enqueue", self.ws, "p", "--type", "vary", "--target", "scene-1",
                     "--expected-revision", self.rev("p") - 1, "--idempotency-key", "k1")
        self.assertEqual(replay["action_id"], first["action_id"])
        with self.assertRaisesRegex(ValueError, "already"):
            self.enqueue("p", "k2")
        self.assertEqual(len(self.grants()), 1)


class DetectToolsRobustnessTests(unittest.TestCase):
    """Находка 4: плохие конфиги не роняют скрипт и не выдают секрет."""

    def run_main(self, home):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out):
            import contextlib
            with contextlib.redirect_stderr(err):
                code = detect_tools.main(["--home", str(home), "--cwd", str(home), "--json"])
        return code, out.getvalue() + err.getvalue()

    def test_bad_url_deep_json_and_odd_providers(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / ".claude.json").write_text(json.dumps({"mcpServers": {
                "bad": {"url": "http://user:SECRET-userinfo-77@[bad"}}}), encoding="utf-8")
            (home / ".cursor").mkdir()
            (home / ".cursor" / "mcp.json").write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
            prefs = home / ".config" / "aimaster"
            prefs.mkdir(parents=True)
            (prefs / "preferences.json").write_text(json.dumps({"providers": 5}), encoding="utf-8")
            code, text = self.run_main(home)
            self.assertEqual(code, 0)
            self.assertNotIn("SECRET-userinfo-77", text)

    def test_unexpected_crash_prints_only_class_name(self):
        original = detect_tools.collect

        def boom(*args):
            raise RuntimeError("SECRET-in-message-88")

        detect_tools.collect = boom
        try:
            with tempfile.TemporaryDirectory() as temp:
                code, text = self.run_main(Path(temp))
        finally:
            detect_tools.collect = original
        self.assertNotEqual(code, 0)
        self.assertIn("RuntimeError", text)
        self.assertNotIn("SECRET-in-message-88", text)


class LegacyLayoutTests(unittest.TestCase):
    """Находка 5: старая раскладка — проекты прямо в корне."""

    def test_init_does_not_hide_root_projects(self):
        with tempfile.TemporaryDirectory() as temp:
            ws = Path(temp) / "ws"
            (ws / "old-project").mkdir(parents=True)
            (ws / "old-project" / "state.json").write_text("{}", encoding="utf-8")
            result = cli("workspace", "init", ws)
            self.assertFalse((ws / "projects").exists())
            self.assertEqual(result["legacy_projects_in_root"], ["old-project"])


class ImportRobustnessTests(Base):
    def project_with_reference(self, pid, label, red):
        cli("project", "create", self.ws, pid, "--title", pid, "--type", "video")
        cli("script", "add-version", self.ws, pid, "--text", "Сцена.", "--reason", "v1",
            "--expected-revision", self.rev(pid))
        scenes = self.root / f"{pid}.json"
        scenes.write_text(json.dumps([{"scene_id": "s1", "title": "К", "text": "Т", "duration_ms": 3000}]),
                          encoding="utf-8")
        cli("scenes", "set", self.ws, pid, "--file", scenes, "--expected-revision", self.rev(pid))
        cli("stage", "approve", self.ws, pid, "--expected-revision", self.rev(pid))
        (self.ws / "media" / f"{pid}.png").write_bytes(png_bytes(red))
        asset = cli("asset", "register", self.ws, "--path", f"media/{pid}.png", "--role", "character")
        cli("reference", "add", self.ws, pid, "--kind", "character", "--name", label,
            "--asset-id", asset["asset_id"], "--expected-revision", self.rev(pid))

    def test_reimport_keeps_aliases_added_by_hand(self):
        """Находка 6."""
        self.project_with_reference("a", "Артём — герой", 5)
        cli("library", "import", self.ws, "--from-projects")
        cli("library", "add", self.ws, "--kind", "character", "--label", "Тёма",
            "--file", self.ws / "media" / "a.png")
        cli("library", "import", self.ws, "--from-projects")
        entry = cli("library", "list", self.ws)["entries"][0]
        self.assertIn("Тёма", entry["aliases"])

    def test_broken_project_is_skipped_not_fatal(self):
        """Находка 7."""
        self.project_with_reference("a", "Артём", 5)
        broken = self.ws / "projects" / "broken"
        broken.mkdir()
        (broken / "state.json").write_text("{not json", encoding="utf-8")
        result = cli("library", "import", self.ws, "--from-projects")
        self.assertEqual(len(result["created"]), 1)
        self.assertIn("project_unreadable", {item["reason"] for item in result["skipped"]})

    def test_add_failure_is_isolated_per_reference(self):
        """Находка 7: ошибка `add_file` на одной ссылке не роняет остальные."""
        self.project_with_reference("a", "Артём", 5)
        self.project_with_reference("b", "Борис", 6)
        (self.ws / "library" / "characters").rmdir()
        (self.ws / "library" / "characters").write_text("not a folder", encoding="utf-8")
        result = cli("library", "import", self.ws, "--from-projects")
        self.assertEqual(result["created"], [])
        self.assertEqual({item["reason"] for item in result["skipped"]}, {"add_failed"})


class MigrationRaceTests(Base):
    """Находка 10: две миграции одновременно не падают на `duplicate column`."""

    def test_concurrent_alter_is_tolerated(self):
        """A racer that read the old schema must survive the other's ALTER.

        Deterministic: the column already exists, but the schema read is
        forced to report it missing, exactly what the losing racer sees.
        """
        db_path = self.ws / ".studio" / "old.sqlite3"
        with closing(sqlite3.connect(db_path)) as db:
            db.execute("CREATE TABLE grants (grant_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, "
                       "action_class TEXT NOT NULL, expires_at TEXT NOT NULL, "
                       "expires_epoch REAL NOT NULL, issued_at TEXT NOT NULL, "
                       "reserved_action_id TEXT UNIQUE, reserved_at TEXT)")
            db.commit()
        ActionLedger(db_path)  # the winner migrates
        with mock.patch.object(ActionLedger, "_grant_columns", staticmethod(lambda connection: {"grant_id"})):
            ActionLedger(db_path)  # the loser: ALTER -> duplicate column name


class LibraryAddInputTests(Base):
    """Находка 11."""

    def test_same_bytes_under_another_kind_is_an_error(self):
        source = self.root / "x.png"
        source.write_bytes(png_bytes(4))
        cli("library", "add", self.ws, "--kind", "character", "--label", "X", "--file", source)
        with self.assertRaisesRegex(LibraryError, "character"):
            cli("library", "add", self.ws, "--kind", "location", "--label", "X", "--file", source)

    def test_fake_signature_is_refused_at_add(self):
        fake = self.root / "fake.png"
        fake.write_bytes(b"not really a png")
        with self.assertRaises(LibraryError):
            cli("library", "add", self.ws, "--kind", "character", "--label", "F", "--file", fake)


if __name__ == "__main__":
    unittest.main()

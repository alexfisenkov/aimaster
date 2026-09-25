#!/usr/bin/env python3
"""Автопилот сам выдаёт разрешение на платное действие (спецификация
2026-09-23 §2), а режим «с уточнениями» — строго как раньше.

Проект собирается командами `creator_studio.py` в этом же интерпретаторе;
провайдеры не вызываются, действие только ставится в очередь.
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (str(_SKILL_ROOT), str(_SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import creator_studio  # noqa: E402
import montage_testkit  # noqa: E402
from studio import authoring  # noqa: E402
from studio.autopilot import AUTOPILOT_NOTICE, StoreAutopilotPolicy  # noqa: E402
from studio.ledger import ActionLedger, ActionRequest  # noqa: E402
from studio.projection import build_snapshot  # noqa: E402
from studio.runner import open_ledger  # noqa: E402


def cli(*argv):
    args = creator_studio.build_parser().parse_args([str(item) for item in argv])
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        args.handler(args)
    return json.loads(buffer.getvalue())


class AutopilotGrantTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name) / "ws"
        montage_testkit.isolate_hyperframes_dir(self, Path(temp.name))
        cli("workspace", "init", self.workspace)
        self.store = authoring.open_store(self.workspace)

    def create(self, project_id, mode):
        return cli("project", "create", self.workspace, project_id, "--title", "Проба",
                   "--type", "photo", "--mode", mode)

    def revision(self, project_id):
        return self.store.load(project_id)["revision"]

    def enqueue(self, project_id, key="k1", action="vary", target="scene-1"):
        return cli("action", "enqueue", self.workspace, project_id, "--type", action,
                   "--target", target, "--expected-revision", self.revision(project_id),
                   "--idempotency-key", key)

    def history(self, project_id, kind="autopilot-grant"):
        return [e for e in self.store.load(project_id)["history"] if e["kind"] == kind]

    def test_autopilot_queues_paid_action_without_grant(self):
        self.create("auto", "autopilot")
        before = self.revision("auto")
        action = self.enqueue("auto")
        self.assertEqual(action["status"], "queued")
        self.assertIsNotNone(action["grant_id"])
        self.assertEqual(action["issued_by"], "autopilot")
        entries = self.history("auto")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["actor"], "agent")
        self.assertEqual(entries[0]["params"], {"action": "vary", "target_id": "scene-1"})
        self.assertEqual(self.revision("auto"), before + 1)

    def test_guided_without_grant_is_refused_as_before(self):
        self.create("guided", "guided")
        before = self.revision("guided")
        action = self.enqueue("guided")
        self.assertEqual(action["status"], "needs_chat")
        self.assertIsNone(action["grant_id"])
        self.assertEqual(self.history("guided"), [])
        self.assertEqual(self.revision("guided"), before)

    def test_replay_with_same_key_issues_nothing_twice(self):
        self.create("auto", "autopilot")
        first = self.enqueue("auto", key="same")
        replay = cli("action", "enqueue", self.workspace, "auto", "--type", "vary",
                     "--target", "scene-1", "--expected-revision", self.revision("auto") - 1,
                     "--idempotency-key", "same")
        self.assertEqual(first["action_id"], replay["action_id"])
        self.assertEqual(len(self.history("auto")), 1)
        with closing(sqlite3.connect(self.workspace / ".studio" / "actions.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM grants").fetchone()[0], 1)

    def test_chat_grant_is_used_first_in_autopilot(self):
        self.create("auto", "autopilot")
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        cli("grant", self.workspace, "auto", "vary", "--expires-at", expires)
        action = self.enqueue("auto")
        self.assertEqual(action["issued_by"], "chat")
        self.assertEqual(self.history("auto"), [])

    def test_refused_history_write_rolls_back_grant_and_action(self):
        self.create("auto", "autopilot")

        class Refusing(StoreAutopilotPolicy):
            def record_grant(self, *args):
                raise RuntimeError("store refused")

        db_path = self.workspace / ".studio" / "actions.sqlite3"
        ledger = ActionLedger(db_path, revision_resolver=lambda pid: self.revision(pid),
                              autopilot=Refusing(self.store))
        with self.assertRaises(RuntimeError):
            ledger.enqueue("auto", ActionRequest("vary", "scene-1", {}, self.revision("auto"), "k"))
        with closing(sqlite3.connect(db_path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM grants").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM actions").fetchone()[0], 0)

    def test_mode_switched_back_to_guided_refuses_self_grant(self):
        self.create("auto", "autopilot")
        cli("mode", "set", self.workspace, "auto", "--mode", "guided",
            "--expected-revision", self.revision("auto"))
        self.assertEqual(self.enqueue("auto")["status"], "needs_chat")

    def test_history_entry_survives_projection(self):
        self.create("auto", "autopilot")
        self.enqueue("auto")
        state = self.store.load("auto")
        state["questions"], state["actions"] = [], []
        snapshot = build_snapshot(self.store.list_projects(), state, asset_url=lambda a: f"/a/{a}")
        kinds = [entry["kind"] for entry in snapshot["active_project"]["history"]]
        self.assertIn("autopilot-grant", kinds)

    def test_old_ledger_gains_issued_by_column(self):
        self.create("auto", "autopilot")
        db_path = self.workspace / ".studio" / "old.sqlite3"
        with closing(sqlite3.connect(db_path)) as db:
            db.execute("CREATE TABLE grants (grant_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, "
                       "action_class TEXT NOT NULL, expires_at TEXT NOT NULL, expires_epoch REAL NOT NULL, "
                       "issued_at TEXT NOT NULL, reserved_action_id TEXT UNIQUE, reserved_at TEXT)")
        ledger = ActionLedger(db_path, revision_resolver=lambda pid: self.revision(pid),
                              autopilot=StoreAutopilotPolicy(self.store))
        action = ledger.enqueue("auto", ActionRequest("generate", "scene-1", {}, self.revision("auto"), "k"))
        self.assertEqual(ledger.grant_issuer(action["grant_id"]), "autopilot")

    def test_open_ledger_carries_the_policy(self):
        self.assertIsInstance(open_ledger(self.workspace).autopilot, StoreAutopilotPolicy)


class AutopilotNoticeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.workspace = Path(temp.name) / "ws"
        montage_testkit.isolate_hyperframes_dir(self, Path(temp.name))
        cli("workspace", "init", self.workspace)

    def rev(self, pid):
        return authoring.open_store(self.workspace).load(pid)["revision"]

    def test_notice_on_every_switch_to_autopilot(self):
        created = cli("project", "create", self.workspace, "a", "--title", "A", "--type", "photo",
                      "--mode", "autopilot")
        self.assertEqual(created["notice"], AUTOPILOT_NOTICE)
        guided = cli("project", "create", self.workspace, "g", "--title", "G", "--type", "photo")
        self.assertNotIn("notice", guided)
        via_mode = cli("mode", "set", self.workspace, "g", "--mode", "autopilot",
                       "--expected-revision", self.rev("g"))
        self.assertEqual(via_mode["notice"], AUTOPILOT_NOTICE)
        back = cli("project", "set-mode", self.workspace, "g", "--mode", "guided",
                   "--expected-revision", self.rev("g"))
        self.assertNotIn("notice", back)
        again = cli("project", "set-mode", self.workspace, "g", "--mode", "autopilot",
                    "--expected-revision", self.rev("g"))
        self.assertEqual(again["notice"], AUTOPILOT_NOTICE)


if __name__ == "__main__":
    unittest.main()

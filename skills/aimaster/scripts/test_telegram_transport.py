#!/usr/bin/env python3
"""Contract tests for the offline portion of the Studio Telegram transport."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from creator_studio_bot import main as bot_main  # noqa: E402
from creator_studio_telegram import FileSecretStore, build_parser, cloudflared_command, validate_bot_token  # noqa: E402
from studio.telegram_bot import (  # noqa: E402
    TelegramBotController,
    TelegramBotError,
    TelegramBotState,
    project_menu_payloads,
)


class TelegramTransportStateTests(unittest.TestCase):
    """The private transport journal survives restarts without duplicate jobs."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary_directory.name) / "telegram.sqlite3"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_owner_pairing_is_durable_and_cannot_be_replaced(self):
        state = TelegramBotState(self.db_path)

        self.assertEqual(state.pair_owner(501), 501)
        self.assertEqual(TelegramBotState(self.db_path).paired_owner(), 501)
        with self.assertRaisesRegex(TelegramBotError, "already paired"):
            state.pair_owner(777)

    def test_first_private_start_pairs_owner_before_any_project_access(self):
        with tempfile.TemporaryDirectory() as workspace:
            controller = TelegramBotController(workspace, owner_id=None, pairing_code="pair")
            replies = controller.handle_update(
                {
                    "update_id": 90,
                    "message": {
                        "from": {"id": 501},
                        "chat": {"id": 501, "type": "private"},
                        "text": "/start pair",
                    },
                }
            )

            self.assertEqual(controller.owner_id, 501)
            self.assertEqual(controller.state.paired_owner(), 501)
            self.assertEqual(replies[0].text, "Telegram owner paired.")

    def test_pairing_code_blocks_wrong_code(self):
        with tempfile.TemporaryDirectory() as workspace:
            controller = TelegramBotController(workspace, None, pairing_code="only-once")
            replies = controller.handle_update({
                "update_id": 901,
                "message": {
                    "from": {"id": 501},
                    "chat": {"id": 501, "type": "private"},
                    "text": "/start wrong",
                },
            })
            self.assertEqual(replies, [])
            self.assertIsNone(controller.state.paired_owner())

    def test_pairing_code_blocks_the_first_wrong_sender_or_code(self):
        with tempfile.TemporaryDirectory() as workspace:
            controller = TelegramBotController(workspace, None, pairing_code="only-once")
            wrong = controller.handle_update({
                "update_id": 901,
                "message": {"from": {"id": 501}, "chat": {"id": 501, "type": "private"}, "text": "/start wrong"},
            })
            self.assertEqual(wrong, [])
            self.assertIsNone(controller.state.paired_owner())

    def test_dequeue_returns_one_durable_free_form_request(self):
        state = TelegramBotState(self.db_path)

        queued = state.enqueue_inbox(
            update_id=91,
            chat_id=501,
            workspace="/tmp/studio",
            project_id="clip-91",
            text="Сделай короче финал",
        )
        item = TelegramBotState(self.db_path).dequeue_inbox()

        self.assertEqual(queued["idempotency_key"], "telegram:91")
        self.assertEqual(item["update_id"], 91)
        self.assertEqual(item["project_id"], "clip-91")
        self.assertEqual(item["text"], "Сделай короче финал")
        self.assertEqual(item["status"], "processing")

    def test_replayed_update_does_not_create_another_inbox_item(self):
        state = TelegramBotState(self.db_path)
        kwargs = {
            "update_id": 92,
            "chat_id": 501,
            "workspace": "/tmp/studio",
            "project_id": "clip-92",
            "text": "Проверь сценарий",
        }

        first = state.enqueue_inbox(**kwargs)
        second = state.enqueue_inbox(**kwargs)
        item = state.dequeue_inbox()

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(item["id"], first["id"])
        self.assertIsNone(state.dequeue_inbox())


class TelegramTransportSetupTests(unittest.TestCase):
    """Local setup never accepts a token that could be malformed or leaked."""

    def test_token_validation_rejects_whitespace_and_accepts_botfather_shape(self):
        token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"

        self.assertEqual(validate_bot_token(token), token)
        with self.assertRaisesRegex(ValueError, "invalid Telegram bot token"):
            validate_bot_token(token + "\n")

    def test_setup_does_not_require_a_workspace_or_contact_the_network(self):
        args = build_parser().parse_args(["setup"])

        self.assertEqual(args.command, "setup")
        self.assertFalse(hasattr(args, "workspace"))

    def test_file_fallback_is_private_and_round_trips_token(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "telegram-token"
            store = FileSecretStore(token_path)

            store.store("123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")

            self.assertEqual(
                store.load(), "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
            )
            self.assertEqual(stat.S_IMODE(token_path.stat().st_mode), 0o600)

    def test_polling_entrypoint_accepts_secret_without_environment_variable(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = bot_main(
                ["--workspace", str(workspace)],
                token="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
                owner_id=501,
                iterations=0,
            )

        self.assertEqual(result, 0)


class TelegramProjectMenuTests(unittest.TestCase):
    def test_project_menu_payloads_are_callback_safe_and_deterministic(self):
        payloads = project_menu_payloads(
            [
                {"id": "project-z", "title": "Зета"},
                {"id": "project-a", "title": "Альфа"},
            ]
        )

        self.assertEqual(
            payloads,
            [
                {"text": "Альфа", "callback_data": "project:project-a"},
                {"text": "Зета", "callback_data": "project:project-z"},
            ],
        )

    def test_menu_button_requires_https(self):
        from creator_studio_bot import TelegramApiError, TelegramBotApi

        api = object.__new__(TelegramBotApi)
        with self.assertRaisesRegex(TelegramApiError, "HTTPS"):
            api.set_chat_menu_button("http://127.0.0.1:8765")

    def test_cloudflared_command_is_loopback_only(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            cloudflared_command("https://example.com")


class TelegramPairingTests(unittest.TestCase):
    def test_unpaired_controller_accepts_one_private_start_and_persists_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TelegramBotState(Path(directory) / "telegram.sqlite3")
            from studio.telegram_bot import TelegramBotController

            controller = TelegramBotController(
                Path(directory), None, pairing_code="pair", state=state,
                store_factory=lambda: None,
                ledger_factory=lambda: None,
                questions_factory=lambda: None,
            )
            replies = controller.handle_update({
                "update_id": 1,
                "message": {
                    "from": {"id": 501},
                    "chat": {"id": 501, "type": "private"},
                    "text": "/start pair",
                },
            })

            self.assertEqual(state.paired_owner(), 501)
            self.assertEqual(controller.owner_id, 501)
            self.assertIn("paired", replies[0].text.lower())

    def test_unpaired_controller_ignores_non_start_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            state = TelegramBotState(Path(directory) / "telegram.sqlite3")
            from studio.telegram_bot import TelegramBotController

            controller = TelegramBotController(
                Path(directory), None, pairing_code="pair", state=state,
                store_factory=lambda: None,
                ledger_factory=lambda: None,
                questions_factory=lambda: None,
            )
            replies = controller.handle_update({
                "update_id": 2,
                "message": {
                    "from": {"id": 501},
                    "chat": {"id": 501, "type": "private"},
                    "text": "hello",
                },
            })

            self.assertEqual(replies, [])
            self.assertIsNone(state.paired_owner())


if __name__ == "__main__":
    unittest.main()

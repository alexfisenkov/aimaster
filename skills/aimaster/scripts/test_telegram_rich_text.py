#!/usr/bin/env python3
"""Rich messages (Bot API 10.1) are read as text by the Studio Telegram bot."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from studio.telegram_bot import TelegramBotController  # noqa: E402
from studio.telegram_rich import message_text  # noqa: E402


class RichTextTests(unittest.TestCase):
    def test_plain_text_unchanged(self):
        self.assertEqual(message_text({"text": "/help"}), "/help")
        self.assertEqual(message_text({"text": ""}), "")
        self.assertIsNone(message_text({}))
        self.assertIsNone(message_text(None))

    def test_rich_blocks(self):
        rich = {"blocks": [
            {"type": "paragraph", "text": "Привет"},
            {"type": "paragraph", "text": [
                {"type": "mention", "text": "@studio_bot", "username": "studio_bot"}, " "]},
            {"type": "paragraph", "text": [{"type": "bot_command", "text": "/help",
                                            "bot_command": "/help"}]},
            {"type": "table", "cells": [[
                {"text": {"type": "url", "text": "https://e.com/a", "url": "https://e.com/a"},
                 "align": "center", "valign": "top"},
                {"text": {"type": "url", "text": "сайт", "url": "https://e.com/b"}}]]},
            {"type": "list", "items": [
                {"label": "•", "blocks": [{"type": "paragraph", "text": "один"}]},
                {"has_checkbox": True, "is_checked": True,
                 "blocks": [{"type": "paragraph", "text": "два"}]},
                {"has_checkbox": True, "blocks": [{"type": "paragraph", "text": "три"}]}]},
            {"type": "blockquote", "blocks": [{"type": "paragraph", "text": "цитата"}]},
            {"type": "details", "summary": "Детали",
             "blocks": [{"type": "paragraph", "text": "внутри"}]},
            {"type": "future_block", "text": "неизвестный", "url": "https://e.com/z"},
        ], "is_rtl": False}
        self.assertEqual(
            message_text({"rich_message": rich}),
            "Привет\n@studio_bot\n/help\nhttps://e.com/a | сайт (https://e.com/b)\n"
            "• один\n✅ два\n⬜ три\n> цитата\nДетали\nвнутри\nнеизвестный https://e.com/z",
        )

    def test_empty_rich(self):
        self.assertEqual(message_text({"rich_message": {"blocks": []}}), "")

    def test_envelope_uses_rich_text(self):
        update = {"update_id": 5, "message": {
            "from": {"id": 1}, "chat": {"id": 1, "type": "private"},
            "rich_message": {"blocks": [{"type": "paragraph", "text": "/start"}]}}}
        self.assertEqual(TelegramBotController._envelope(update), (5, 1, 1, "private", "/start"))


if __name__ == "__main__":
    unittest.main()

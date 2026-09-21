#!/usr/bin/env python3
"""Local setup and launch entrypoint for the macOS Studio Telegram transport.

Importing this module and rendering ``--help`` are deliberately offline.  The
Bot API is only constructed by the existing polling entrypoint after ``run``
loads a locally stored credential.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path


_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from studio.telegram_bot import TelegramBotState, TelegramBotError  # noqa: E402
from studio.workspace import PRIVATE_DIR_NAME, resolve_workspace_paths  # noqa: E402


_TOKEN_PATTERN = re.compile(r"^[0-9]{6,20}:[A-Za-z0-9_-]{20,}$")
_KEYCHAIN_SERVICE = "ai-master-studio-telegram"
_KEYCHAIN_ACCOUNT = "bot-token"


def _default_fallback_path() -> Path:
    """Keep the fallback outside project state when setup has no workspace."""

    return Path.home() / "Library" / "Application Support" / "AI Мастерская" / "telegram-bot-token"


def validate_bot_token(token: str) -> str:
    """Accept only a non-whitespace BotFather token without echoing it."""

    if not isinstance(token, str) or not _TOKEN_PATTERN.fullmatch(token):
        raise ValueError("invalid Telegram bot token")
    return token


class FileSecretStore:
    """Mode-0600 local fallback for test environments without macOS Keychain."""

    def __init__(self, path):
        self.path = Path(path)

    def store(self, token: str):
        token = validate_bot_token(token)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        descriptor = os.open(
            self.path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(token)
                handle.write("\n")
        finally:
            # fdopen closes on normal and exceptional writes.  The explicit
            # permission repair also protects an existing file with old mode.
            os.chmod(self.path, 0o600)

    def load(self) -> str:
        try:
            mode = stat.S_IMODE(self.path.stat().st_mode)
        except FileNotFoundError:
            raise RuntimeError("Telegram token is not configured") from None
        if mode != 0o600:
            raise RuntimeError("Telegram token fallback file must have mode 0600")
        try:
            token = self.path.read_text(encoding="utf-8").rstrip("\n")
        except OSError:
            raise RuntimeError("Telegram token fallback file cannot be read") from None
        return validate_bot_token(token)


class KeychainSecretStore:
    """macOS Keychain store using ``security`` without placing the token in argv."""

    def __init__(self, command=None):
        self.command = command or shutil.which("security")
        if not self.command:
            raise RuntimeError("macOS Keychain command is unavailable")

    def store(self, token: str):
        token = validate_bot_token(token)
        result = subprocess.run(
            [
                self.command,
                "add-generic-password",
                "-U",
                "-a",
                _KEYCHAIN_ACCOUNT,
                "-s",
                _KEYCHAIN_SERVICE,
                "-w",
            ],
            input=f"{token}\n",
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("macOS Keychain could not store the Telegram token")

    def load(self) -> str:
        result = subprocess.run(
            [
                self.command,
                "find-generic-password",
                "-a",
                _KEYCHAIN_ACCOUNT,
                "-s",
                _KEYCHAIN_SERVICE,
                "-w",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("Telegram token is not configured in macOS Keychain")
        return validate_bot_token(result.stdout.rstrip("\n"))


class LocalSecretStore:
    """Prefer Keychain, then use the private workspace fallback if unavailable."""

    def __init__(self, fallback_path, *, keychain_factory=KeychainSecretStore):
        self.fallback = FileSecretStore(fallback_path)
        try:
            self.keychain = keychain_factory()
        except RuntimeError:
            self.keychain = None

    def store(self, token: str):
        if self.keychain is not None:
            try:
                self.keychain.store(token)
                return
            except RuntimeError:
                pass
        self.fallback.store(token)

    def load(self) -> str:
        if self.keychain is not None:
            try:
                return self.keychain.load()
            except RuntimeError:
                pass
        return self.fallback.load()


def _workspace_state(workspace):
    workspace_path, _, _, private_root = resolve_workspace_paths(workspace)
    return workspace_path, private_root, TelegramBotState(private_root / "telegram_bot.sqlite3")


def build_parser():
    parser = argparse.ArgumentParser(description="Set up or run Studio Telegram transport")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("setup")
    run = subcommands.add_parser("run")
    run.add_argument("--workspace", required=True, type=Path)
    return parser


def main(argv=None, *, token_prompt=getpass.getpass, runner=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "setup":
            LocalSecretStore(_default_fallback_path()).store(
                token_prompt("BotFather token (hidden): ")
            )
            print("Telegram token saved locally. Send /start to the bot to pair the owner.")
            return 0
        workspace, _, state = _workspace_state(args.workspace)
        secret_store = LocalSecretStore(_default_fallback_path())
        owner_id = state.paired_owner()
        token = secret_store.load()
        if runner is None:
            from creator_studio_bot import main as runner
        return runner(
            ["--workspace", str(workspace)],
            token=token,
            owner_id=owner_id,
            allow_pairing=owner_id is None,
        )
    except (OSError, RuntimeError, TelegramBotError, ValueError) as error:
        # Credential-bearing exceptions are intentionally not interpolated.
        print("Telegram transport setup or launch failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

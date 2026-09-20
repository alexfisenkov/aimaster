#!/usr/bin/env python3
"""Silently report a newer official Aimaster release, when one is known."""

from __future__ import annotations

import datetime as _datetime
import http.client
import json
import os
from pathlib import Path
import re
import signal
from typing import Any


_HOST = "api.github.com"
_PATH = "/repos/alexfisenkov/aimaster/releases?per_page=100"
_MAX_RESPONSE_BYTES = 1024 * 1024
_WALL_TIMEOUT_SECONDS = 3.8
_VERSION_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})(?:\.(\d+))?$", re.ASCII)


class _WallTimeout(TimeoutError):
    pass


def _version_key(value: str) -> tuple[int, int, int, int] | None:
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        return None
    year, month, day = (int(part) for part in match.group(1, 2, 3))
    try:
        _datetime.date(year, month, day)
        sequence = int(match.group(4) or "0")
    except ValueError:
        return None
    return year, month, day, sequence


def _read_installed() -> tuple[str, tuple[int, int, int, int]] | None:
    version_path = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        value = version_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    key = _version_key(value)
    return (value, key) if key is not None else None


def _alarm_handler(_signum: int, _frame: Any) -> None:
    raise _WallTimeout


def _fetch_releases() -> Any:
    if os.name != "posix":
        raise OSError("unsupported platform")

    previous_handler = signal.getsignal(signal.SIGALRM)
    connection: http.client.HTTPSConnection | None = None
    try:
        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, _WALL_TIMEOUT_SECONDS)
        connection = http.client.HTTPSConnection(_HOST, timeout=_WALL_TIMEOUT_SECONDS)
        connection.request(
            "GET",
            _PATH,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "aimaster-update-check",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = connection.getresponse()
        if response.status != 200:
            raise OSError("release lookup failed")
        payload = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise ValueError("release response too large")
        return json.loads(payload)
    finally:
        try:
            if connection is not None:
                connection.close()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)


def _latest_release(releases: Any) -> tuple[str, tuple[int, int, int, int]] | None:
    if not isinstance(releases, list):
        return None

    latest: tuple[str, tuple[int, int, int, int]] | None = None
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") is not False:
            continue
        tag = release.get("tag_name")
        if not isinstance(tag, str):
            continue
        key = _version_key(tag)
        if key is not None and (latest is None or key > latest[1]):
            latest = tag, key
    return latest


def _check() -> dict[str, str] | None:
    installed = _read_installed()
    if installed is None:
        return None
    releases = _fetch_releases()
    latest = _latest_release(releases)
    if latest is None or latest[1] <= installed[1]:
        return None
    tag = latest[0]
    return {
        "installed": installed[0],
        "latest": tag,
        "url": f"https://github.com/alexfisenkov/aimaster/releases/tag/{tag}",
    }


def main() -> int:
    try:
        update = _check()
    except Exception:
        return 0
    if update is not None:
        print(json.dumps(update, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

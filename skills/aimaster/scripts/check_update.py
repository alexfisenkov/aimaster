#!/usr/bin/env python3
"""Silently report a newer official Aimaster release, when one is known."""

from __future__ import annotations

import datetime as _datetime
import http.client
import json
from pathlib import Path
import queue
import re
import sys
import threading
from typing import Any

_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from studio.platform_compat import ensure_utf8_stdio  # noqa: E402


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


def _request_releases() -> Any:
    connection = http.client.HTTPSConnection(_HOST, timeout=_WALL_TIMEOUT_SECONDS)
    try:
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
        connection.close()


def _fetch_releases(request=_request_releases, wall_timeout=_WALL_TIMEOUT_SECONDS) -> Any:
    """Run the lookup on a daemon thread and give up after ``wall_timeout``.

    The socket timeout bounds each read, not the whole exchange; the wall
    clock is enforced here instead of with ``SIGALRM``, which Windows lacks.
    A lookup still running at the deadline is abandoned: the thread is a
    daemon and dies with the process.
    """

    outcome: queue.Queue = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            outcome.put((True, request()))
        except BaseException as error:  # noqa: BLE001 - re-raised in the caller
            outcome.put((False, error))

    threading.Thread(target=worker, name="aimaster-update-check", daemon=True).start()
    try:
        succeeded, value = outcome.get(timeout=wall_timeout)
    except queue.Empty:
        raise _WallTimeout from None
    if not succeeded:
        raise value
    return value


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
    ensure_utf8_stdio()
    try:
        update = _check()
    except Exception:
        return 0
    if update is not None:
        print(json.dumps(update, ensure_ascii=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

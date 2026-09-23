#!/usr/bin/env python3
"""The update check keeps its wall-clock limit without SIGALRM (Windows too)."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_update  # noqa: E402


class WallClockTests(unittest.TestCase):
    def test_a_hanging_lookup_is_abandoned_at_the_deadline(self):
        release = threading.Event()
        self.addCleanup(release.set)
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            check_update._fetch_releases(request=lambda: release.wait(30), wall_timeout=0.2)
        self.assertLess(time.monotonic() - started, 5)

    def test_result_and_errors_come_back_from_the_worker(self):
        self.assertEqual(check_update._fetch_releases(request=lambda: [1], wall_timeout=5), [1])

        def failing():
            raise OSError("release lookup failed")

        with self.assertRaisesRegex(OSError, "lookup failed"):
            check_update._fetch_releases(request=failing, wall_timeout=5)

    def test_main_stays_silent_when_the_lookup_fails(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock

        output = io.StringIO()
        with mock.patch.object(check_update, "_fetch_releases", side_effect=TimeoutError), \
                redirect_stdout(output):
            self.assertEqual(check_update.main(), 0)
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()

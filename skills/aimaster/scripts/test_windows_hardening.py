#!/usr/bin/env python3
"""Windows hardening: lock timeout, directory ACL and owner checks, exclusive
port binding.  The decision logic is pure and runs on every OS; the parts
that need the real Windows API are skipped elsewhere."""

from __future__ import annotations

import errno
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS.parent
for _path in (_SKILL_ROOT, _SCRIPTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from studio import _windows_security as winsec  # noqa: E402
from studio import loopback_http  # noqa: E402
from studio import platform_compat as compat  # noqa: E402

USER = "S-1-5-21-1-2-3-1001"
OTHER = "S-1-5-21-1-2-3-1002"
EVERYONE = "S-1-1-0"
ALLOW, DENY = winsec._ACCESS_ALLOWED_ACE_TYPE, winsec._ACCESS_DENIED_ACE_TYPE
OI, CI, IO = winsec._OBJECT_INHERIT_ACE, winsec._CONTAINER_INHERIT_ACE, winsec._INHERIT_ONLY_ACE


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class LockPollingTests(unittest.TestCase):
    def test_busy_lock_is_retried_until_free(self):
        clock, attempts = FakeClock(), []

        def try_lock():
            attempts.append(clock.now)
            if len(attempts) < 3:
                raise OSError(errno.EACCES, "locked")

        compat._acquire_polling(try_lock, timeout=5, clock=clock, sleep=clock.sleep)
        self.assertEqual(len(attempts), 3)

    def test_filesystem_without_locks_fails_at_once(self):
        for code in (errno.EINVAL, errno.EBADF):
            calls = []

            def try_lock():
                calls.append(1)
                raise OSError(code, "no byte-range locks here")

            with self.assertRaises(OSError) as caught:
                compat._acquire_polling(try_lock, timeout=5, sleep=lambda _: None)
            self.assertNotIsInstance(caught.exception, compat.LockTimeoutError)
            self.assertEqual(caught.exception.errno, code)
            self.assertEqual(len(calls), 1, "must not be retried")

    def test_lock_held_forever_times_out_with_a_clear_error(self):
        clock = FakeClock()

        def try_lock():
            raise OSError(getattr(errno, "EDEADLOCK", errno.EDEADLK), "resource deadlock")

        with self.assertRaisesRegex(compat.LockTimeoutError, r"\.state\.lock.*after 2 s"):
            compat._acquire_polling(try_lock, timeout=2, clock=clock, sleep=clock.sleep,
                                    name=".state.lock")
        self.assertGreaterEqual(clock.now, 2)
        self.assertLess(clock.now, 3)

    def test_file_lock_accepts_a_timeout_everywhere(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(Path(directory) / ".lock", "a+b") as handle, \
                    compat.file_lock(handle, timeout=1):
                pass


class DirectoryAclPolicyTests(unittest.TestCase):
    def test_inherit_only_grant_on_a_directory_is_not_private(self):
        entries = [(ALLOW, OI | CI, USER), (ALLOW, OI | CI | IO, EVERYONE)]
        self.assertFalse(winsec.evaluate_private(USER, entries, USER, directory=True))
        # a file never passes its entries on: inherit-only is irrelevant there
        self.assertTrue(winsec.evaluate_private(USER, entries, USER, directory=False))

    def test_inherit_only_without_inheritance_flags_does_not_reach_children(self):
        entries = [(ALLOW, OI | CI, USER), (ALLOW, IO, EVERYONE)]
        self.assertTrue(winsec.evaluate_private(USER, entries, USER, directory=True))

    def test_trusted_inherit_only_entries_are_fine(self):
        entries = [(ALLOW, OI | CI, USER), (ALLOW, OI | CI | IO, "S-1-3-0"),
                   (ALLOW, OI | CI, "S-1-5-18"), (DENY, OI | CI | IO, EVERYONE)]
        self.assertTrue(winsec.evaluate_private(USER, entries, USER, directory=True))

    def test_null_dacl_and_unknown_aces_fail_closed(self):
        self.assertFalse(winsec.evaluate_private(USER, None, USER, directory=True))
        self.assertFalse(winsec.evaluate_private(USER, [(0x5, 0, None)], USER))


class OwnerPolicyTests(unittest.TestCase):
    def test_folder_owned_by_another_account_is_not_private(self):
        entries = [(ALLOW, OI | CI, USER)]
        self.assertFalse(winsec.evaluate_private(OTHER, entries, USER, directory=True))
        self.assertFalse(winsec.evaluate_private(None, entries, USER, directory=True))

    def test_user_system_and_administrators_may_own(self):
        entries = [(ALLOW, 0, USER)]
        for owner in (USER, "S-1-5-18", "S-1-5-32-544"):
            self.assertTrue(winsec.evaluate_private(owner, entries, USER), owner)
        # CREATOR OWNER is a placeholder in an ACE, never a real owner
        self.assertFalse(winsec.evaluate_private("S-1-3-0", entries, USER))

    def test_make_private_takes_ownership_before_changing_the_acl(self):
        calls = []
        owners = iter([OTHER, USER])

        def security(_path):
            return next(owners), [(ALLOW, 0, USER)]

        with mock.patch.object(winsec, "current_user_sid", return_value=USER), \
                mock.patch.object(winsec, "_security", side_effect=security), \
                mock.patch.object(winsec, "_aces", return_value=[(ALLOW, 0, USER)]), \
                mock.patch.object(winsec, "_icacls", side_effect=lambda p, *a: calls.append(a)):
            winsec.make_private(Path("C:/work/.studio"), directory=True)
        self.assertEqual(calls[0], ("/setowner", f"*{USER}"))
        self.assertEqual(calls[1][0], "/inheritance:r")

    def test_foreign_owner_that_cannot_be_replaced_is_a_clear_refusal(self):
        def refuse(_path, *arguments):
            raise OSError("icacls could not restrict access to .studio (exit 5)")

        with mock.patch.object(winsec, "current_user_sid", return_value=USER), \
                mock.patch.object(winsec, "_security", return_value=(OTHER, [])), \
                mock.patch.object(winsec, "_icacls", side_effect=refuse) as icacls:
            with self.assertRaisesRegex(OSError, "another Windows account"):
                winsec.make_private(Path("C:/work/.studio"), directory=True)
        self.assertEqual(icacls.call_count, 1, "no ACL change after a failed /setowner")

    def test_trusted_owner_is_left_alone(self):
        with mock.patch.object(winsec, "current_user_sid", return_value=USER), \
                mock.patch.object(winsec, "_security", return_value=("S-1-5-32-544", [])), \
                mock.patch.object(winsec, "_aces", return_value=[]), \
                mock.patch.object(winsec, "_icacls") as icacls:
            winsec.make_private(Path("C:/work/token"))
        self.assertNotIn("/setowner", [call.args[1] for call in icacls.call_args_list])


@unittest.skipUnless(os.name == "nt", "real Windows ACLs")
class RealWindowsAclTests(unittest.TestCase):
    def test_everyone_inherit_only_on_a_private_folder_is_detected_and_fixed(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / ".studio"
            folder.mkdir()
            compat.make_private(folder, directory=True)
            self.assertTrue(compat.is_private(folder, directory=True))
            subprocess.run(["icacls", str(folder), "/grant", "*S-1-1-0:(OI)(CI)(IO)(R)"],
                           capture_output=True, check=True)
            self.assertFalse(compat.is_private(folder, directory=True))
            self.assertTrue(compat.ensure_private(folder, directory=True))
            created = folder / "state.sqlite3-wal"
            created.write_bytes(b"")
            self.assertTrue(compat.is_private(created))

    def test_owner_of_a_new_folder_is_trusted(self):
        with tempfile.TemporaryDirectory() as directory:
            owner, _ = winsec._security(Path(directory))
            self.assertTrue(winsec.owner_is_trusted(owner, winsec.current_user_sid()), owner)


class ExclusivePortTests(unittest.TestCase):
    def _server_with_fake_socket(self):
        server = loopback_http.LoopbackThreadingHTTPServer(
            ("127.0.0.1", 0), None, bind_and_activate=False)
        server.socket.close()
        fake = mock.Mock()
        fake.getsockname.return_value = ("127.0.0.1", 43210)
        server.socket = fake
        return server, fake

    def test_windows_binds_exclusively_and_never_reuses_the_address(self):
        server, fake = self._server_with_fake_socket()
        with mock.patch.object(loopback_http, "_IS_WINDOWS", True):
            server.server_bind()
        options = [call.args[1] for call in fake.setsockopt.call_args_list]
        self.assertIn(loopback_http._SO_EXCLUSIVEADDRUSE, options)
        self.assertNotIn(socket.SO_REUSEADDR, options)
        self.assertFalse(server.allow_reuse_address)
        self.assertEqual((server.server_name, server.server_port), ("127.0.0.1", 43210))

    def test_posix_behaviour_is_unchanged(self):
        server, fake = self._server_with_fake_socket()
        with mock.patch.object(loopback_http, "_IS_WINDOWS", False):
            server.server_bind()
        options = [call.args[1] for call in fake.setsockopt.call_args_list]
        self.assertIn(socket.SO_REUSEADDR, options)
        self.assertNotIn(loopback_http._SO_EXCLUSIVEADDRUSE, options)

    @unittest.skipUnless(os.name == "nt", "SO_REUSEADDR port stealing is a Windows behaviour")
    def test_another_socket_cannot_take_the_same_port_on_windows(self):
        server = loopback_http.LoopbackThreadingHTTPServer(("127.0.0.1", 0), None)
        try:
            port = server.server_address[1]
            intruder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                intruder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                with self.assertRaises(OSError):
                    intruder.bind(("127.0.0.1", port))
            finally:
                intruder.close()
        finally:
            server.server_close()


class _FakeOsStore:
    """Stands in for DPAPI (or the Keychain) without touching any real secret."""

    def __init__(self, *, replaces_plain_fallback, load_error=None):
        self.replaces_plain_fallback = replaces_plain_fallback
        self.load_error = load_error
        self.value = None

    def store(self, value):
        self.value = value

    def load(self):
        if self.load_error is not None:
            raise self.load_error
        return self.value


class DpapiTokenStoreTests(unittest.TestCase):
    TOKEN = "123456789:" + "D" * 36
    OLD = "987654321:" + "E" * 36

    def setUp(self):
        import creator_studio_telegram as transport

        self.transport = transport
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.plain = Path(temp.name) / "telegram-bot-token"

    def _local(self, os_store):
        return self.transport.LocalSecretStore(self.plain, keychain_factory=lambda: os_store)

    def _plant_plain(self):
        self.transport.FileSecretStore(self.plain).store(self.OLD)
        self.assertTrue(self.plain.exists())

    def test_saving_to_dpapi_deletes_the_old_plaintext_file(self):
        self._plant_plain()
        os_store = _FakeOsStore(replaces_plain_fallback=True)
        self._local(os_store).store(self.TOKEN)
        self.assertEqual(os_store.value, self.TOKEN)
        self.assertFalse(self.plain.exists())

    def test_keychain_store_keeps_the_existing_behaviour(self):
        self._plant_plain()
        self._local(_FakeOsStore(replaces_plain_fallback=False)).store(self.TOKEN)
        self.assertTrue(self.plain.exists())

    def test_undeletable_plaintext_file_is_reported(self):
        self._plant_plain()
        store = self._local(_FakeOsStore(replaces_plain_fallback=True))
        with mock.patch.object(Path, "unlink", side_effect=PermissionError(13, "denied")):
            with self.assertRaisesRegex(RuntimeError, "could not be deleted"):
                store.store(self.TOKEN)

    def test_decrypt_failure_is_not_hidden_by_the_plaintext_fallback(self):
        self._plant_plain()
        broken = _FakeOsStore(
            replaces_plain_fallback=True,
            load_error=self.transport.SecretUnreadableError("DPAPI could not decrypt"),
        )
        with self.assertRaisesRegex(self.transport.SecretUnreadableError, "decrypt"):
            self._local(broken).load()

    def test_missing_dpapi_token_still_falls_back_to_the_file(self):
        self._plant_plain()
        empty = _FakeOsStore(replaces_plain_fallback=True,
                             load_error=RuntimeError("Telegram token is not configured"))
        self.assertEqual(self._local(empty).load(), self.OLD)

    def test_dpapi_store_raises_unreadable_on_a_decrypt_error(self):
        import studio

        sealed = self.plain.with_name("telegram-bot-token.dpapi")
        sealed.write_bytes(b"not a dpapi blob")
        fake = mock.Mock()
        fake.unprotect.side_effect = OSError(13, "The data is invalid")
        with mock.patch.object(self.transport, "IS_WINDOWS", True), \
                mock.patch.object(studio, "_windows_security", fake, create=True):
            with self.assertRaises(self.transport.SecretUnreadableError):
                self.transport.DpapiSecretStore(sealed).load()

    def test_main_names_the_unreadable_token_instead_of_a_generic_failure(self):
        import io
        from contextlib import redirect_stderr

        error = self.transport.SecretUnreadableError("Windows DPAPI could not decrypt")
        failing = mock.Mock()
        failing.return_value.load.side_effect = error
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as workspace, \
                mock.patch.object(self.transport, "LocalSecretStore", failing), \
                redirect_stderr(stderr):
            code = self.transport.main(["run", "--workspace", workspace])
        self.assertEqual(code, 2)
        self.assertIn("could not decrypt", stderr.getvalue())

    @unittest.skipUnless(os.name == "nt", "DPAPI exists only on Windows")
    def test_real_dpapi_setup_removes_the_plaintext_file(self):
        sealed = self.plain.with_name("telegram-bot-token.dpapi")
        self._plant_plain()
        store = self.transport.LocalSecretStore(
            self.plain, keychain_factory=lambda: self.transport.DpapiSecretStore(sealed))
        store.store(self.TOKEN)
        self.assertFalse(self.plain.exists())
        self.assertEqual(store.load(), self.TOKEN)
        sealed.write_bytes(b"garbage")
        with self.assertRaises(self.transport.SecretUnreadableError):
            store.load()


if __name__ == "__main__":
    unittest.main()

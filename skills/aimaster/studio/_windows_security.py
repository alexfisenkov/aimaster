"""Windows-only ACL and DPAPI helpers for ``platform_compat`` (ctypes, stdlib).

Imported lazily and only on Windows; nothing here runs on macOS or Linux.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path

_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x1
_DACL_SECURITY_INFORMATION = 0x4
_TOKEN_QUERY = 0x0008
_TOKEN_USER = 1
_ACCESS_ALLOWED_ACE_TYPE = 0x0
_ACCESS_DENIED_ACE_TYPE = 0x1
_OBJECT_INHERIT_ACE = 0x01
_CONTAINER_INHERIT_ACE = 0x02
_INHERIT_ONLY_ACE = 0x08
_CRYPTPROTECT_UI_FORBIDDEN = 0x1
# SYSTEM, Administrators, CREATOR OWNER, OWNER RIGHTS: the Windows
# equivalent of root, which a 0600 file on POSIX cannot keep out either.
_TRUSTED_SIDS = {"S-1-5-18", "S-1-5-32-544", "S-1-3-0", "S-1-3-4"}
# Who may own a private object besides the current user.  An owner has
# implicit READ_CONTROL and WRITE_DAC, so a folder pre-created by another
# account stays theirs no matter what its DACL says.  An elevated
# administrator's files are owned by the Administrators group by default.
_TRUSTED_OWNERS = {"S-1-5-18", "S-1-5-32-544"}


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _declare(function, restype, *argtypes):
    function.restype = restype
    function.argtypes = list(argtypes)


@lru_cache(maxsize=1)
def _libraries():
    """Load the DLLs once, with full signatures: 64-bit handles must not be
    squeezed through ctypes' default C ``int`` conversion."""

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    pointer, handle, dword, boolean = ctypes.c_void_p, wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
    out_pointer, blob = ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(_Blob)
    _declare(kernel32.GetCurrentProcess, handle)
    _declare(kernel32.CloseHandle, boolean, handle)
    _declare(kernel32.LocalFree, pointer, pointer)
    _declare(advapi32.OpenProcessToken, boolean, handle, dword, ctypes.POINTER(handle))
    _declare(advapi32.GetTokenInformation, boolean, handle, ctypes.c_int, pointer, dword,
             ctypes.POINTER(dword))
    _declare(advapi32.ConvertSidToStringSidW, boolean, pointer, ctypes.POINTER(wintypes.LPWSTR))
    _declare(advapi32.GetNamedSecurityInfoW, dword, wintypes.LPCWSTR, ctypes.c_int, dword,
             out_pointer, pointer, out_pointer, pointer, out_pointer)
    _declare(advapi32.GetAce, boolean, pointer, dword, out_pointer)
    for name in ("CryptProtectData", "CryptUnprotectData"):
        _declare(getattr(crypt32, name), boolean, blob, pointer, blob, pointer, pointer, dword, blob)
    return advapi32, kernel32, crypt32


def _sid_string(sid) -> str:
    advapi32, kernel32, _ = _libraries()
    text = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid), ctypes.byref(text)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return text.value
    finally:
        kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))


@lru_cache(maxsize=1)
def current_user_sid() -> str:
    advapi32, kernel32, _ = _libraries()
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, _TOKEN_USER, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return _sid_string(ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0])
    finally:
        kernel32.CloseHandle(token)


def _security(path: Path):
    """``(owner_sid, entries)``; entries are ``(type, flags, sid)`` of the
    DACL, or None for a NULL DACL."""

    advapi32, kernel32, _ = _libraries()
    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    error = advapi32.GetNamedSecurityInfoW(
        str(path), _SE_FILE_OBJECT, _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
        ctypes.byref(owner), None, ctypes.byref(dacl), None, ctypes.byref(descriptor),
    )
    if error:
        raise ctypes.WinError(error)
    try:
        owner_sid = _sid_string(owner.value) if owner.value else None
        if not dacl.value:
            return owner_sid, None  # a NULL DACL grants everyone everything
        count = ctypes.cast(dacl, ctypes.POINTER(ctypes.c_ushort))[2]  # ACL.AceCount
        entries = []
        for index in range(count):
            ace = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace)):
                raise ctypes.WinError(ctypes.get_last_error())
            header = ctypes.cast(ace, ctypes.POINTER(ctypes.c_ubyte))
            ace_type, ace_flags = header[0], header[1]
            if ace_type in (_ACCESS_ALLOWED_ACE_TYPE, _ACCESS_DENIED_ACE_TYPE):
                sid = _sid_string(ace.value + 8)  # header(4) + mask(4)
            else:
                sid = None  # object/callback ACEs: the caller fails closed
            entries.append((ace_type, ace_flags, sid))
        return owner_sid, entries
    finally:
        kernel32.LocalFree(descriptor)


def _aces(path: Path):
    """``(type, flags, sid)`` for every entry of the DACL; None = no DACL."""

    return _security(path)[1]


def _applies(ace_flags: int, directory: bool) -> bool:
    """Does an allow entry grant access now or to what is created inside?

    An inherit-only entry does not apply to the object itself, but on a
    directory it is copied onto new files (OI) and subfolders (CI) -- the
    SQLite ``-wal``/``-shm`` files of a private folder, for example.
    """

    if not ace_flags & _INHERIT_ONLY_ACE:
        return True
    return directory and bool(ace_flags & (_OBJECT_INHERIT_ACE | _CONTAINER_INHERIT_ACE))


def _allowed_sids(entries, *, directory: bool = False) -> list[str] | None:
    """SIDs of allow entries that matter for the object; None = no DACL."""

    if entries is None:
        return None
    sids = []
    for ace_type, ace_flags, sid in entries:
        if ace_type == _ACCESS_DENIED_ACE_TYPE or not _applies(ace_flags, directory):
            continue
        sids.append(sid if sid is not None else "unsupported-ace")
    return sids


def owner_is_trusted(owner_sid, user_sid: str) -> bool:
    return owner_sid is not None and (owner_sid == user_sid or owner_sid in _TRUSTED_OWNERS)


def evaluate_private(owner_sid, entries, user_sid: str, *, directory: bool = False) -> bool:
    """Pure decision behind ``is_private`` (portable, unit-tested everywhere)."""

    if not owner_is_trusted(owner_sid, user_sid):
        return False
    sids = _allowed_sids(entries, directory=directory)
    if sids is None:
        return False
    allowed = _TRUSTED_SIDS | {user_sid}
    return all(sid in allowed for sid in sids)


def is_private(path: Path, *, directory: bool = False) -> bool:
    owner_sid, entries = _security(path)
    return evaluate_private(owner_sid, entries, current_user_sid(), directory=directory)


def _icacls(path: Path, *arguments: str) -> None:
    # The system copy, not whatever `icacls` comes first on PATH.
    system_copy = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "icacls.exe")
    command = [system_copy if os.path.isfile(system_copy) else "icacls", str(path), *arguments]
    try:
        result = subprocess.run(
            command, capture_output=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise OSError(f"icacls could not restrict access to {path.name}") from error
    if result.returncode != 0:
        raise OSError(f"icacls could not restrict access to {path.name} (exit {result.returncode})")


def _take_ownership(path: Path, owner_sid, user: str) -> None:
    """Make the current user the owner, or refuse with a clear error."""

    if owner_is_trusted(owner_sid, user):
        return
    try:
        _icacls(path, "/setowner", f"*{user}")
    except OSError:
        raise OSError(
            f"{path.name} belongs to another Windows account ({owner_sid}); it cannot be made "
            "private. Delete it (or ask an administrator to) and run the command again"
        ) from None
    if not owner_is_trusted(_security(path)[0], user):
        raise OSError(f"{path.name} still belongs to another Windows account ({owner_sid})")


def make_private(path: Path, *, directory: bool = False) -> None:
    rights = "(OI)(CI)(F)" if directory else "(F)"
    user = current_user_sid()
    _take_ownership(path, _security(path)[0], user)
    # Drop inherited entries and replace the user's own grant ...
    _icacls(path, "/inheritance:r", "/grant:r", f"*{user}:{rights}")
    # ... then every explicit grant to anyone else (an "Everyone: read"
    # added earlier survives `/grant:r`, which only rewrites the named SID).
    # Inherit-only grants count too: on a directory they would reach the
    # files created inside it later.
    foreign = foreign_grants(_aces(path) or [], user)
    if foreign:
        _icacls(path, "/remove:g", *(f"*{sid}" for sid in foreign))


def foreign_grants(entries, user: str) -> list[str]:
    return sorted({
        sid for ace_type, _, sid in entries
        if ace_type == _ACCESS_ALLOWED_ACE_TYPE and sid and sid != user and sid not in _TRUSTED_SIDS
    })


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi(function_name: str, data: bytes, entropy: bytes) -> bytes:
    _, kernel32, crypt32 = _libraries()
    source, _keep_source = _blob(data)
    extra, _keep_extra = _blob(entropy)
    output = _Blob()
    function = getattr(crypt32, function_name)
    if not function(ctypes.byref(source), None, ctypes.byref(extra), None, None,
                    _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def protect(data: bytes, entropy: bytes) -> bytes:
    """Encrypt for the current Windows user only (DPAPI, CurrentUser scope)."""

    return _dpapi("CryptProtectData", data, entropy)


def unprotect(data: bytes, entropy: bytes) -> bytes:
    return _dpapi("CryptUnprotectData", data, entropy)

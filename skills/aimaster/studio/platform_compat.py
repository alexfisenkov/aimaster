"""The one place where Aimaster differs between macOS, Linux and Windows.

Everything here is standard library only.  POSIX behaviour is exactly what
the callers did inline before (``flock``, ``chmod`` 0600/0700, directory
``fsync``, ``O_NOFOLLOW``); Windows gets the closest native equivalent.
The ctypes calls into the Windows security API live in ``_windows_security``
and are imported only on Windows.
"""

from __future__ import annotations

import errno
import os
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path

IS_WINDOWS = os.name == "nt"
IS_MACOS = sys.platform == "darwin"
_LOCK_POLL_SECONDS = 0.05


def _descriptor(target) -> int:
    return target if isinstance(target, int) else target.fileno()


# msvcrt.locking reports "held by another process" as EACCES or EDEADLOCK;
# anything else (a filesystem without byte-range locks: EINVAL, EBADF) will
# never succeed and must not be retried forever.
_LOCK_BUSY_ERRNOS = frozenset(
    {errno.EACCES, getattr(errno, "EDEADLOCK", errno.EDEADLK), errno.EDEADLK}
)
DEFAULT_LOCK_TIMEOUT = 60.0


class LockTimeoutError(TimeoutError):
    """Another process kept the lock for longer than the timeout."""


def _acquire_polling(try_lock, *, timeout, poll=_LOCK_POLL_SECONDS,
                     clock=time.monotonic, sleep=time.sleep, name="the lock file") -> None:
    """Call ``try_lock`` until it succeeds; retry only while the lock is busy."""

    deadline = clock() + timeout
    while True:
        try:
            try_lock()
            return
        except OSError as error:
            if error.errno not in _LOCK_BUSY_ERRNOS:
                raise
            if clock() >= deadline:
                raise LockTimeoutError(
                    f"{name} is still locked by another process after {timeout:g} s; "
                    "close the other Aimaster window or command and try again"
                ) from None
        sleep(poll)


@contextmanager
def file_lock(target, *, timeout: float = DEFAULT_LOCK_TIMEOUT):
    """Hold an exclusive lock on an open file (or descriptor).

    POSIX blocks in ``flock`` exactly as before.  Windows polls
    ``msvcrt.locking`` for at most ``timeout`` seconds and then raises
    ``LockTimeoutError``; a filesystem that cannot lock raises ``OSError``
    at once instead of hanging.
    """

    descriptor = _descriptor(target)
    if IS_WINDOWS:
        import msvcrt

        def lock_byte_zero():
            # msvcrt locks from the current position: always byte 0, which
            # may lie past the end of an empty lock file (Windows allows it).
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)

        label = getattr(target, "name", None)
        label = os.path.basename(label) if isinstance(label, str) else "the lock file"
        _acquire_polling(lock_byte_zero, timeout=timeout, name=label)
        try:
            yield
        finally:
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


def is_private(path, *, directory=False) -> bool:
    """True when only the current user (and the OS itself) can open ``path``.

    POSIX: the mode is exactly 0600 (0700 for a directory).  Windows: every
    allow entry of the DACL names the current user, SYSTEM, Administrators
    or the owner-rights SIDs, and the owner is the current user, SYSTEM or
    Administrators -- checked by SID, so it does not depend on the language
    of the Windows installation.  For a directory, inherit-only entries that
    new files or subfolders would receive count as well.
    """

    if IS_WINDOWS:
        from . import _windows_security

        return _windows_security.is_private(Path(path), directory=directory)
    expected = 0o700 if directory else 0o600
    return stat.S_IMODE(os.stat(path).st_mode) == expected


def make_private(path, *, directory=False) -> None:
    """Restrict ``path`` to the current user; raise ``OSError`` on failure."""

    if IS_WINDOWS:
        from . import _windows_security

        _windows_security.make_private(Path(path), directory=directory)
        return
    os.chmod(path, 0o700 if directory else 0o600)


def ensure_private(path, *, directory=False) -> bool:
    """Make ``path`` private and report whether it now is.

    On Windows the (slow) ``icacls`` call is skipped when the ACL is already
    private, so this is cheap to call on every SQLite connection.
    """

    if IS_WINDOWS and is_private(path, directory=directory):
        return True
    make_private(path, directory=directory)
    return is_private(path, directory=directory)


def fsync_directory(path) -> None:
    """Persist a rename in ``path``.  Windows cannot open a directory: no-op."""

    if IS_WINDOWS:
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def replace_file(source, target, *, attempts=20, delay=0.05) -> None:
    """``os.replace`` that tolerates a reader briefly holding ``target`` on Windows."""

    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if not IS_WINDOWS or attempt + 1 == attempts:
                raise
            time.sleep(delay)


def open_nofollow_flags() -> int:
    """``O_NOFOLLOW`` where the OS has it, else 0 (pair with ``open_nofollow``)."""

    return getattr(os, "O_NOFOLLOW", 0)


def open_nofollow(path, flags, mode=0o600) -> int:
    """``os.open`` that refuses a symlink at ``path`` on every OS."""

    extra = open_nofollow_flags()
    if not extra and Path(path).is_symlink():
        raise OSError(f"refusing to open a symlink: {Path(path).name}")
    return os.open(path, flags | extra | getattr(os, "O_BINARY", 0), mode)


def _home(home=None) -> Path:
    return Path(home) if home is not None else Path.home()


def _env_dir(environ, name, fallback: Path) -> Path:
    value = (environ or {}).get(name)
    return Path(value) if value and Path(value).is_absolute() else fallback


def user_data_dir(*, home=None, environ=None) -> Path:
    """Per-user application data (Telegram token, tunnel config)."""

    home = _home(home)
    environ = os.environ if environ is None else environ
    if IS_MACOS:
        return home / "Library" / "Application Support" / "AI Мастерская"
    if IS_WINDOWS:
        base = _env_dir(environ, "LOCALAPPDATA", home / "AppData" / "Local")
        return base / "AI Мастерская"
    return _env_dir(environ, "XDG_DATA_HOME", home / ".local" / "share") / "aimaster"


def user_config_dir(*, home=None, environ=None) -> Path:
    """Per-user preferences: ``~/.config/aimaster``, ``%APPDATA%\\aimaster``."""

    home = _home(home)
    environ = os.environ if environ is None else environ
    if IS_WINDOWS:
        return _env_dir(environ, "APPDATA", home / "AppData" / "Roaming") / "aimaster"
    return _env_dir(environ, "XDG_CONFIG_HOME", home / ".config") / "aimaster"


def ensure_utf8_stdio() -> None:
    """Print Cyrillic safely on a cp866/cp1251 Windows console."""

    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").replace("-", "").lower()
        reconfigure = getattr(stream, "reconfigure", None)
        if encoding != "utf8" and reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def find_program(name: str, *, environ=None) -> str | None:
    """Полный путь к программе из абсолютных элементов PATH, иначе (на
    Windows) — из WinGet Links, или None.

    Пустой или относительный элемент PATH означал бы текущую папку, где может
    лежать чужой файл. На Windows берём только настоящие .exe/.com: .cmd и
    .bat запускаются через cmd.exe, а оболочку монтаж не использует; кроме
    isfile проверяем ещё lexists — так видны псевдонимы WindowsApps (точки
    повторной обработки, которые winget создаёт для ffmpeg/git/cloudflared и
    которые isfile иногда не распознаёт), но каталог с таким именем — не
    программа. Если ничего не нашлось на PATH, последний шанс — ярлыки в
    %LOCALAPPDATA%\\Microsoft\\WinGet\\Links: туда winget их тоже кладёт, но
    PATH текущего процесса может ещё не знать об этой папке.

    Зеркало этой функции — scripts/install.py: `_find_program`/`_which`.
    Экземпляры не объединены: install.py обязан работать даже под старым
    Python (там нет f-строк и импортов пакета studio), поэтому у него своя,
    независимая копия той же логики.
    """

    environ = os.environ if environ is None else environ
    folders = []
    for entry in environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if entry and os.path.isabs(entry) and entry not in folders:
            folders.append(entry)
    suffixes = ("",) if not IS_WINDOWS or os.path.splitext(name)[1] else (".exe", ".com")
    for folder in folders:
        for suffix in suffixes:
            candidate = os.path.join(folder, name + suffix)
            if not IS_WINDOWS:
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate
                continue
            if (os.path.isfile(candidate) or os.path.lexists(candidate)) \
                    and not os.path.isdir(candidate):
                return candidate
    if not IS_WINDOWS:
        return None
    local_appdata = environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    link = Path(local_appdata) / "Microsoft" / "WinGet" / "Links" / (name + ".exe")
    return str(link) if link.is_file() else None

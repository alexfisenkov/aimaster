"""Private state, atomic receipts and one OS lock shared with creative jobs."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from ..platform_compat import file_lock, LockBusyError, open_text_nofollow

OperationBusy = LockBusyError


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_state_dir(home=None):
    if home is not None:
        return Path(home).expanduser().absolute() / ".config" / "aimaster"
    if os.environ.get("AIMASTER_CONFIG_HOME"):
        return Path(os.environ["AIMASTER_CONFIG_HOME"]).expanduser().absolute()
    root = os.environ.get("APPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME")
    return (Path(root) if root else Path.home() / ".config") / "aimaster"


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("unsafe_state_directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def write_bytes(path, data):
    path = Path(path)
    private_dir(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    write_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def read_state(directory):
    path = Path(directory) / "family.json"
    if not path.exists():
        return {"schema_version": 1, "auto_update": {"enabled": False, "confirmed_at": None},
                "components": {}, "workspaces": [], "last_session": None, "last_check": None}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("components"), dict) \
            or not isinstance(value.get("auto_update"), dict) or type(value["auto_update"].get("enabled")) is not bool \
            or not isinstance(value.get("workspaces", []), list) or not all(isinstance(path, str) for path in value.get("workspaces", [])):
        raise ValueError("invalid_family_state")
    return value


def save_state(directory, value):
    write_json(Path(directory) / "family.json", value)


def register_workspace(workspace, *, state_dir=None):
    directory = private_dir(state_dir or default_state_dir())
    root = str(Path(workspace).expanduser().resolve(strict=True))
    with operation_lease(directory, "workspace-registration"):
        value = read_state(directory)
        value["workspaces"] = list(dict.fromkeys([*value.get("workspaces", []), root]))
        save_state(directory, value)
    return root


@contextmanager
def operation_lease(state_dir=None, owner="operation", ttl=3600):
    """Nonblocking OS lock. TTL is diagnostic, never a license to steal a live lock.

    Hold from before claim through terminal/unknown. A crashed process releases
    the OS lock; its recorded unknown jobs still require explicit reconciliation.
    """
    directory = private_dir(state_dir or default_state_dir())
    with open_text_nofollow(directory / "operation.lock") as handle:
        with file_lock(handle, blocking=False):
            write_json(directory / "operation.json", {"owner": str(owner), "pid": os.getpid(),
                       "started_at": now(), "ttl": ttl, "active": True})
            try:
                yield
            finally:
                try:
                    write_json(directory / "operation.json", {"owner": str(owner), "pid": os.getpid(),
                               "finished_at": now(), "active": False})
                except OSError:
                    # Diagnostic metadata must not replace the committed result
                    # with an exception. The OS lock still releases on this exit.
                    pass

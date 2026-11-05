"""Bounded owner presentation settings; no creative content or install settings."""
import json

from .family_setup.state import write_json
from .platform_compat import file_lock, open_text_nofollow
from .safe_paths import safe_path
from .workspace import resolve_workspace_paths

VALUES = {"locale": {"ru", "en"}, "theme": {"system", "light", "dark"},
          "view": {"stages", "overview"}, "rail": {"collapsed", "docked"}}


def validate(value):
    if not isinstance(value, dict) or not set(value) <= set(VALUES) or any(
            not isinstance(item, str) or item not in VALUES[key] for key, item in value.items()):
        raise ValueError("invalid_workspace_preferences")
    return value


def read(workspace):
    root, _, _, private = resolve_workspace_paths(workspace)
    path = safe_path(root, private / "preferences.json")
    if not path.exists():
        return {}
    if path.stat().st_size > 1024:
        raise ValueError("invalid_workspace_preferences")
    return validate(json.loads(path.read_text(encoding="utf-8")))


def save(workspace, value):
    validate(value)
    root, _, _, private = resolve_workspace_paths(workspace)
    lock = safe_path(root, private / "preferences.lock")
    with open_text_nofollow(lock) as handle, file_lock(handle):
        result = {**read(workspace), **value}
        write_json(safe_path(root, private / "preferences.json"), result)
    return result

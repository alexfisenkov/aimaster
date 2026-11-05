"""One read-only host launcher for setup and execution, including private installs."""
import json
from pathlib import Path

from .family_setup.state import default_state_dir
from .safe_paths import safe_path

PACKAGES = {"codex": "@openai/codex", "claude": "@anthropic-ai/claude-code"}


def resolve(agent, *, state_dir=None, node=None, lookup=None):
    if agent not in PACKAGES:
        return None
    if lookup is None:
        from .family_setup.providers import program
        lookup = program
    found = lookup(agent)
    if found:
        return [str(found)]
    node = node or lookup("node")
    if not node:
        return None
    directory = Path(state_dir or default_state_dir()).absolute()
    package = directory / "tools" / agent / "node_modules" / PACKAGES[agent]
    try:
        metadata = safe_path(directory, package / "package.json")
        if not metadata.is_file() or metadata.stat().st_size > 65536:
            return None
        value = json.loads(metadata.read_text(encoding="utf-8"))
        if value.get("name") != PACKAGES[agent]:
            return None
        entry = value["bin"]
        relative = entry if isinstance(entry, str) else entry.get(agent)
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts or "\\" in relative:
            return None
        executable = safe_path(package, package / relative)
        return [str(node), str(executable)] if executable.is_file() else None
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None

"""Explicit data recovery always creates a separate workspace, never downgrades live data."""
import json
from pathlib import Path
import shutil

from . import packages
from .state import operation_lease, read_state, write_json, now


def snapshot_workspace(workspace, destination, *, state_dir):
    source, destination = Path(workspace).resolve(strict=True), Path(destination).absolute()
    if destination.exists() or destination.is_symlink() or destination.resolve().is_relative_to(source):
        raise ValueError("snapshot_destination_must_be_new_and_outside_workspace")
    with operation_lease(state_dir, "workspace-snapshot"):
        state = read_state(state_dir)
        if any(destination.resolve().is_relative_to(Path(root).resolve()) for root in state.get("workspaces", [])):
            raise ValueError("snapshot_must_be_outside_active_workspaces")
        # digest_tree rejects symlinks; do not dereference external/private files.
        before = packages.digest_tree(source)
        destination.mkdir(parents=True)
        copied = destination / "workspace"
        shutil.copytree(source, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        if packages.digest_tree(copied) != before or packages.digest_tree(source) != before:
            # No manifest means an incomplete snapshot, never a restorable success.
            raise ValueError("workspace_changed_during_snapshot")
        write_json(destination / "manifest.json", {"schema_version": 1, "created_at": now(), "fingerprint": before})
    return {"ok": True, "status": "snapshot_saved", "snapshot": str(destination)}


def restore_workspace(snapshot, destination, *, state_dir, use_rollback=False):
    snapshot, destination = Path(snapshot).resolve(strict=True), Path(destination).absolute()
    source = snapshot / "workspace"
    if destination.exists() or destination.is_symlink() or destination.resolve().is_relative_to(snapshot):
        raise ValueError("restore_destination_must_be_new_and_separate")
    with operation_lease(state_dir, "workspace-copy"):
        state = read_state(state_dir)
        if any(destination.resolve().is_relative_to(Path(root).resolve()) for root in state.get("workspaces", [])):
            raise ValueError("restore_must_be_outside_active_workspaces")
        manifest = json.loads((snapshot / "manifest.json").read_text())
        if manifest.get("schema_version") != 1 or packages.digest_tree(source) != manifest.get("fingerprint"):
            raise ValueError("invalid_snapshot")
        component = state.get("rollback" if use_rollback else "components", {}).get("aimaster")
        if not component or packages.digest_tree(Path(component["package"])) != component["fingerprint"]:
            raise ValueError("missing_or_changed_target_runtime")
        if not packages.compatibility(Path(component["package"]), [source]):
            return {"ok": False, "status": "compatibility_blocked", "data_unchanged": True}
        shutil.copytree(source, destination)
        if packages.digest_tree(destination) != manifest["fingerprint"]:
            raise ValueError("snapshot_copy_failed")
    return {"ok": True, "status": "compatible_workspace_copy", "workspace": str(destination),
            "active_workspace_unchanged": True}

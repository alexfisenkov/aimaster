"""Explicit data recovery always creates a separate workspace, never downgrades live data."""
import json
from pathlib import Path
import shutil
import hashlib
import os
import stat

from . import packages
from .state import operation_lease, read_state, write_json, now


def _unsafe_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) &
        getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def workspace_digest(root):
    """Hash every workspace file, checking links before any package exclusions.

    A snapshot has no package-cache exceptions: `.git`, marker files and pyc
    names can contain private data too. Do not descend into symlinks/junctions.
    """
    root = Path(root)
    if _unsafe_link(root.lstat()) or not root.is_dir():
        raise ValueError("unsafe_workspace_symlink")
    files = []
    def visit(directory):
        with os.scandir(directory) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if _unsafe_link(info):
                    raise ValueError("unsafe_workspace_symlink")
                if stat.S_ISDIR(info.st_mode):
                    visit(Path(entry.path))
                elif stat.S_ISREG(info.st_mode):
                    files.append(Path(entry.path))
                else:
                    raise ValueError("unsafe_workspace_file")
    visit(root)
    digest = hashlib.sha256()
    for path in sorted(files):
        # O_NOFOLLOW additionally rejects a file replaced by a link after scan.
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as handle:
            if _unsafe_link(path.lstat()) or not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("unsafe_workspace_symlink")
            contents = hashlib.sha256()
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                contents.update(chunk)
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(contents.digest())
    return digest.hexdigest()


def snapshot_workspace(workspace, destination, *, state_dir):
    if _unsafe_link(Path(workspace).lstat()):
        raise ValueError("unsafe_workspace_symlink")
    source, destination = Path(workspace).resolve(strict=True), Path(destination).absolute()
    if destination.exists() or destination.is_symlink() or destination.resolve().is_relative_to(source):
        raise ValueError("snapshot_destination_must_be_new_and_outside_workspace")
    with operation_lease(state_dir, "workspace-snapshot"):
        state = read_state(state_dir)
        if any(destination.resolve().is_relative_to(Path(root).resolve()) for root in state.get("workspaces", [])):
            raise ValueError("snapshot_must_be_outside_active_workspaces")
        before = workspace_digest(source)
        destination.mkdir(parents=True, mode=0o700)
        copied = destination / "workspace"
        shutil.copytree(source, copied, symlinks=True)
        if workspace_digest(copied) != before or workspace_digest(source) != before:
            # No manifest means an incomplete snapshot, never a restorable success.
            raise ValueError("workspace_changed_during_snapshot")
        write_json(destination / "manifest.json", {"schema_version": 1, "created_at": now(),
                                                  "digest": "workspace-full-v1", "fingerprint": before})
    return {"ok": True, "status": "snapshot_saved", "snapshot": str(destination)}


def restore_workspace(snapshot, destination, *, state_dir, use_rollback=False):
    if _unsafe_link(Path(snapshot).lstat()):
        raise ValueError("unsafe_snapshot_symlink")
    snapshot, destination = Path(snapshot).resolve(strict=True), Path(destination).absolute()
    source = snapshot / "workspace"
    if destination.exists() or destination.is_symlink() or destination.resolve().is_relative_to(snapshot):
        raise ValueError("restore_destination_must_be_new_and_separate")
    with operation_lease(state_dir, "workspace-copy"):
        state = read_state(state_dir)
        if any(destination.resolve().is_relative_to(Path(root).resolve()) for root in state.get("workspaces", [])):
            raise ValueError("restore_must_be_outside_active_workspaces")
        manifest_path = snapshot / "manifest.json"
        manifest_info = manifest_path.lstat()
        if _unsafe_link(manifest_info) or not stat.S_ISREG(manifest_info.st_mode):
            raise ValueError("unsafe_snapshot_manifest")
        manifest = json.loads(manifest_path.read_text())
        full_digest = workspace_digest(source)  # Reject ALL links before legacy digest exemptions.
        expected = full_digest if manifest.get("digest") == "workspace-full-v1" else packages.digest_tree(source)
        if manifest.get("schema_version") != 1 or expected != manifest.get("fingerprint"):
            raise ValueError("invalid_snapshot")
        component = state.get("rollback" if use_rollback else "components", {}).get("aimaster")
        if not component or packages.digest_tree(Path(component["package"])) != component["fingerprint"]:
            raise ValueError("missing_or_changed_target_runtime")
        if not packages.compatibility(Path(component["package"]), [source]):
            return {"ok": False, "status": "compatibility_blocked", "data_unchanged": True}
        shutil.copytree(source, destination, symlinks=True)
        if workspace_digest(destination) != full_digest:
            raise ValueError("snapshot_copy_failed")
    return {"ok": True, "status": "compatible_workspace_copy", "workspace": str(destination),
            "active_workspace_unchanged": True}

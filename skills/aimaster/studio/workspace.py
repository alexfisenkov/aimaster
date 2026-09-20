"""Canonical on-disk layout for one creator-studio workspace.

Repair, 2026-09-16 (ticket 09, second repair, condition 5). Workspace path
resolution used to live in `runner.py`, and `server.py` imported it from
there (`from .runner import resolve_workspace_paths`) purely to reuse that
one function — pulling in the entire chat/operator-bridge module just for
a path calculation that has nothing to do with chat, providers or the
action ledger. This module owns that layout on its own, with no
dependency on `runner.py`, `ledger.py` or any provider/chat concept:
`server.py`, `runner.py` and the CLI (transitively, through both) now all
read the same paths and filenames from here instead of from each other.
"""

from __future__ import annotations

from pathlib import Path


# Repair, 2026-09-16 (condition 5): named once, here, instead of the same
# literal string appearing separately in `server.serve()` and
# `runner.open_ledger` (and, previously, a third time in `serve()` for the
# event source, which reads the same ledger file).
ACTIONS_DB_NAME = "actions.sqlite3"
QUESTIONS_DB_NAME = "questions.sqlite3"
# Ticket 12: the durable `AssetIndex` sidecar -- lives beside the actions/
# questions stores in `<workspace>/.studio` so `server.serve()` and the
# authoring CLI (`studio/authoring.py`, run as a separate process) open the
# exact same file regardless of which one registers an asset first.
ASSETS_DB_NAME = "assets.sqlite3"

# Ticket 12 repair, condition 11: the private directory's own name, named
# once so `resolve_workspace_paths` below and `AssetIndex`'s own default
# `db_path` fallback (`studio/assets.py`, used only when a caller does not
# pass one explicitly) resolve to the exact same directory instead of each
# spelling `".studio"` out as its own literal.
PRIVATE_DIR_NAME = ".studio"

# Ticket 12: shared by `server.serve()` and `studio/authoring.py` so a CLI
# `asset register` and the running server's own `AssetIndex` enforce the
# identical size ceiling -- one constant, not two copies that could drift.
MAX_ASSET_BYTES = 128 * 1024 * 1024

# Ticket 12 repair, condition 11: the one ceiling for every chat-authored
# free-text field (spec §9, "серверные лимиты по байтам") -- shared by
# `authoring_support.py` (every `--text`/`--reason`/`--caption`/... field)
# and `authoring_scenes.py` (a scene's own `content`), instead of each
# module hand-copying the same `64 * 1024` literal. 64 KiB comfortably
# holds a full scenario or a long prompt while still refusing an unbounded
# paste before it ever reaches `state.json`.
MAX_TEXT_BYTES = 64 * 1024


class WorkspaceError(RuntimeError):
    """A workspace path does not satisfy the on-disk layout contract."""


def resolve_workspace_paths(workspace) -> tuple[Path, Path, Path, Path]:
    """Resolve (workspace, project_root, media_root, private_root).

    The one canonical workspace-layout resolver, shared by `server.serve()`
    and the CLI's `runner.open_ledger`/`runner.open_runner`:
    `<workspace>/projects` holds project state (falling back to
    `workspace` itself when that subdirectory is absent), `<workspace>/media`
    holds registered assets, and `<workspace>/.studio` holds the private
    ledger and question stores — never served, never sanitized for the
    browser.

    Repair, 2026-09-17 (ticket 12 repair, blocking condition 1):
    `media_root` used to fall back to `workspace` itself when `media/` was
    absent, exactly like `project_root` still does above. For an asset
    root that is a security boundary (`AssetIndex`'s only allowed root —
    every path it will ever serve or index), that fallback was the bug:
    the allowed root silently became the *entire* workspace, including
    `projects/nocturne-47/` and every other project's `state.json`. There
    is no safe fallback for a security boundary, so this returns the
    (possibly nonexistent) `<workspace>/media` unconditionally. A caller
    that wants one to exist decides that for itself: `server.serve()`
    creates it (a running server should not refuse to start merely
    because nothing has been registered yet), while the CLI's `asset
    register` (`studio.authoring.open_assets`) does not — `AssetIndex`'s
    own strict `Path.resolve(strict=True)` on this path then refuses with
    `AssetValidationError` (exit code 3), which is exactly the ticket's
    required behavior for a workspace with no `media/` directory.
    """

    workspace = Path(workspace).resolve(strict=True)
    if not workspace.is_dir():
        raise WorkspaceError("workspace must be a directory")
    project_root = workspace / "projects"
    if not project_root.is_dir():
        project_root = workspace
    media_root = workspace / "media"
    private_root = workspace / PRIVATE_DIR_NAME
    return workspace, project_root, media_root, private_root

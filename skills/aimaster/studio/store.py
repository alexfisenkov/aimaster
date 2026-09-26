"""Durable JSON project storage with exclusions and optimistic revisions."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from pathlib import Path

from .platform_compat import file_lock, fsync_directory, open_text_nofollow, replace_file


class StoreError(RuntimeError):
    """Base storage failure."""


class ProjectNotFound(StoreError):
    """A project is absent or intentionally excluded from this store."""


class RevisionConflict(StoreError):
    """The caller attempted to mutate a stale project revision."""

    def __init__(self, expected_revision, current_revision):
        super().__init__(
            f"revision conflict: expected {expected_revision}, current {current_revision}"
        )
        self.expected_revision = expected_revision
        self.current_revision = current_revision


_LOCKS_GUARD = threading.Lock()
_LOCKS = {}


def _thread_lock(path):
    key = str(path)
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _is_within(path, root):
    return path == root or path.is_relative_to(root)


class ProjectStore:
    """Discover and mutate immediate child projects below a safe root."""

    def __init__(self, root: Path, excluded: tuple[Path, ...]):
        self.root = Path(root).resolve(strict=False)
        exclusions = [Path(path).resolve(strict=False) for path in excluded]
        exclusions.append((self.root / "nocturne-47").resolve(strict=False))
        self.excluded = tuple(dict.fromkeys(exclusions))

    def _is_excluded(self, path):
        resolved = path.resolve(strict=False)
        return resolved.name == "nocturne-47" or any(
            _is_within(resolved, excluded) for excluded in self.excluded
        )

    def _project_paths(self):
        if not self.root.is_dir():
            return []
        paths = []
        with os.scandir(self.root) as entries:
            for entry in entries:
                candidate = Path(entry.path)
                try:
                    resolved = candidate.resolve(strict=False)
                except OSError:
                    continue
                if self._is_excluded(candidate) or not _is_within(resolved, self.root):
                    continue
                try:
                    is_directory = candidate.is_dir()
                except OSError:
                    continue
                if is_directory and (resolved / "state.json").is_file():
                    paths.append(resolved)
        return sorted(set(paths), key=lambda path: path.name)

    @staticmethod
    def _read(path):
        try:
            state = json.loads((path / "state.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise StoreError(f"cannot read project state: {path.name}") from error
        if not isinstance(state, dict):
            raise StoreError(f"project state must be an object: {path.name}")
        return state

    def _find(self, project_id):
        if not isinstance(project_id, str) or not project_id or any(
            character in project_id for character in ("/", "\\", "\0")
        ):
            raise ProjectNotFound(str(project_id))
        if project_id == "nocturne-47":
            raise ProjectNotFound(project_id)
        for path in self._project_paths():
            state = self._read(path)
            project = state.get("project")
            if isinstance(project, dict) and project.get("id") == project_id:
                return path
        raise ProjectNotFound(project_id)

    def list_projects(self) -> list[dict]:
        projects = []
        for path in self._project_paths():
            state = self._read(path)
            project = state.get("project")
            if not isinstance(project, dict) or not isinstance(project.get("id"), str):
                raise StoreError(f"project metadata is invalid: {path.name}")
            summary = copy.deepcopy(project)
            from .domain import derive_view_stage, derive_project_status
            view = derive_view_stage(state)
            summary["stage"] = view["current_stage"]
            summary["status"] = derive_project_status(view)
            summary["revision"] = state.get("revision")
            projects.append(summary)
        return sorted(
            projects,
            key=lambda project: (
                project.get("order", 0),
                project.get("title", ""),
                project["id"],
            ),
        )

    def load(self, project_id: str) -> dict:
        return copy.deepcopy(self._read(self._find(project_id)))

    def project_dir(self, project_id: str) -> Path:
        """Папка проекта (там, где state.json) — для файлов рядом с состоянием, например montage/."""

        return self._find(project_id)

    @staticmethod
    def _atomic_replace(path, state):
        serialized = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            replace_file(temporary, path)
            fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _open_lock(project_id, lock_path):
        """The lock file, never through a link planted in its place. The
        OSError text (English, absolute path) stays in the chain only."""

        try:
            return open_text_nofollow(lock_path)
        except OSError as error:
            raise StoreError(
                f"не удалось открыть замок {lock_path.name} проекта «{project_id}»: на его месте "
                "ссылка на другое место или нет доступа — уберите ссылку, и запись пройдёт"
            ) from error

    def transact(self, project_id, expected_revision, mutation) -> dict:
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise ValueError("expected_revision must be a non-negative integer")
        if not callable(mutation):
            raise TypeError("mutation must be callable")
        project_path = self._find(project_id)
        state_path = project_path / "state.json"
        lock_path = project_path / ".state.lock"
        with _thread_lock(project_path):
            with self._open_lock(project_id, lock_path) as lock_handle, file_lock(lock_handle):
                current = self._read(project_path)
                current_revision = current.get("revision")
                if (
                    isinstance(current_revision, bool)
                    or not isinstance(current_revision, int)
                    or current_revision < 0
                ):
                    raise StoreError("stored revision must be a non-negative integer")
                if current_revision != expected_revision:
                    raise RevisionConflict(expected_revision, current_revision)
                candidate = copy.deepcopy(current)
                mutation(candidate)
                candidate["revision"] = current_revision + 1
                self._atomic_replace(state_path, candidate)
                return copy.deepcopy(candidate)

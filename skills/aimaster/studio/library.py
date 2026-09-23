"""Workspace library: characters, voices, locations, products, styles.

Spec 2026-09-23 §3. `<workspace>/library/index.json` lists every entry;
files live in `library/<kind folder>/`. The index is rewritten atomically
(temp file + fsync + `os.replace`) under an exclusive `flock` on
`library/.library.lock`, the same pattern `scripts/guide_registry.py` uses
for `.guides.lock`. Every stored path is relative to `library/` and must
resolve (symlinks followed) inside it.

Entry: `{library_id, kind, label, aliases[], files[{path, sha256, media}],
voice_of?, source?: {project_id, reference_id}, added_at}`.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .workspace import MAX_ASSET_BYTES

LIBRARY_DIR_NAME = "library"
INDEX_NAME = "index.json"
LOCK_NAME = ".library.lock"
SCHEMA_VERSION = 1
KIND_FOLDERS = {
    "character": "characters",
    "voice": "voices",
    "location": "locations",
    "product": "products",
    "style": "styles",
    "other": "other",
}
MEDIA_BY_EXTENSION = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".mp4": "video", ".webm": "video", ".mp3": "audio", ".wav": "audio",
}
_KIND_MEDIA = {
    "voice": frozenset({"audio"}),
    "other": frozenset({"image", "video", "audio"}),
}
_DEFAULT_MEDIA = frozenset({"image", "video"})
_ENTRY_KEYS = {"library_id", "kind", "label", "aliases", "files", "added_at"}
_OPTIONAL_KEYS = {"voice_of", "source"}
_UNSAFE_NAME = re.compile(r"[^0-9A-Za-zА-Яа-яЁё._-]+")


class LibraryError(ValueError):
    """A library request or the stored index violates the contract."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def library_root(workspace, *, create=False) -> Path:
    """`<workspace>/library`, refusing a symlink or path that leaves the workspace."""

    try:
        root = Path(workspace).resolve(strict=True)
    except OSError as error:
        raise LibraryError("workspace does not exist") from error
    if not root.is_dir():
        raise LibraryError("workspace must be a directory")
    library = root / LIBRARY_DIR_NAME
    if library.is_symlink():
        raise LibraryError("library must be a real directory, not a symlink")
    if create:
        library.mkdir(exist_ok=True)
    if not library.is_dir():
        raise LibraryError("workspace has no library directory; run `workspace init`")
    resolved = library.resolve(strict=True)
    if resolved.parent != root:
        raise LibraryError("library directory escapes the workspace")
    return resolved


def library_file(library: Path, relative) -> Path:
    """Resolve an index path; only regular files inside `library/` pass."""

    if not isinstance(relative, str) or not relative or "\x00" in relative or "\\" in relative:
        raise LibraryError("library path must be a relative POSIX path")
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise LibraryError("library path must stay inside library/")
    try:
        resolved = (library / candidate).resolve(strict=True)
        resolved.relative_to(library)
    except (OSError, ValueError) as error:
        raise LibraryError("library path is missing or escapes library/") from error
    if not resolved.is_file():
        raise LibraryError("library path must be a regular file")
    return resolved


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_entry(entry, position):
    if not isinstance(entry, dict):
        raise LibraryError(f"entries[{position}] must be an object")
    keys = set(entry)
    if not _ENTRY_KEYS <= keys or keys - _ENTRY_KEYS - _OPTIONAL_KEYS:
        raise LibraryError(f"entries[{position}] has unexpected or missing keys")
    if entry["kind"] not in KIND_FOLDERS:
        raise LibraryError(f"entries[{position}].kind is not supported")
    if not isinstance(entry["label"], str) or not entry["label"].strip():
        raise LibraryError(f"entries[{position}].label must be a non-empty string")
    if not isinstance(entry["aliases"], list) or not all(isinstance(a, str) for a in entry["aliases"]):
        raise LibraryError(f"entries[{position}].aliases must be a list of strings")
    files = entry["files"]
    if not isinstance(files, list) or not files:
        raise LibraryError(f"entries[{position}].files must be a non-empty list")
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "media"}:
            raise LibraryError(f"entries[{position}].files items need path, sha256, media")
        path = Path(item["path"]) if isinstance(item["path"], str) else None
        if path is None or path.is_absolute() or ".." in path.parts:
            raise LibraryError(f"entries[{position}].files path must stay inside library/")


def read_index(library: Path) -> dict:
    path = library / INDEX_NAME
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "revision": 0, "entries": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LibraryError("library/index.json is unreadable or invalid JSON") from error
    if not isinstance(value, dict) or not isinstance(value.get("entries"), list):
        raise LibraryError("library/index.json must hold an entries list")
    for position, entry in enumerate(value["entries"]):
        _validate_entry(entry, position)
    value.setdefault("schema_version", SCHEMA_VERSION)
    value.setdefault("revision", 0)
    return value


def write_index_atomic(library: Path, value: dict) -> None:
    path = library / INDEX_NAME
    serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(dir=library, prefix=f".{INDEX_NAME}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(library, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked_index(library: Path):
    """Hold the library lock; yield the index; write it back if it changed."""

    descriptor = os.open(library / LOCK_NAME, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            index = read_index(library)
            before = json.dumps(index, sort_keys=True, ensure_ascii=False)
            yield index
            if json.dumps(index, sort_keys=True, ensure_ascii=False) != before:
                index["revision"] = int(index.get("revision", 0)) + 1
                write_index_atomic(library, index)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def media_of(path: Path) -> str:
    media = MEDIA_BY_EXTENSION.get(path.suffix.casefold())
    if media is None:
        raise LibraryError("file type is not supported (png, jpg, webp, mp4, webm, mp3, wav)")
    return media


def find_by_sha(index: dict, digest: str):
    for entry in index["entries"]:
        if any(item["sha256"] == digest for item in entry["files"]):
            return entry
    return None


def find_entry(index: dict, library_id: str):
    for entry in index["entries"]:
        if entry["library_id"] == library_id:
            return entry
    return None


def _copy_into(library: Path, kind: str, source: Path, digest: str) -> str:
    folder = library / KIND_FOLDERS[kind]
    if folder.is_symlink():
        raise LibraryError(f"library/{KIND_FOLDERS[kind]} must not be a symlink")
    folder.mkdir(exist_ok=True)
    if folder.resolve(strict=True).parent != library:
        raise LibraryError(f"library/{KIND_FOLDERS[kind]} escapes library/")
    stem = _UNSAFE_NAME.sub("-", source.stem).strip("-.") or "file"
    name = f"{stem[:80]}{source.suffix.casefold()}"
    target = folder / name
    if target.exists() and sha256_of(target) != digest:
        target = folder / f"{digest[:10]}-{name}"
    if not target.exists():
        descriptor, temporary_name = tempfile.mkstemp(dir=folder, prefix=".copy.", suffix=".tmp")
        os.close(descriptor)
        try:
            shutil.copyfile(source, temporary_name)
            if sha256_of(Path(temporary_name)) != digest:
                raise LibraryError("source file changed while it was copied")
            os.replace(temporary_name, target)
        finally:
            Path(temporary_name).unlink(missing_ok=True)
    return target.relative_to(library).as_posix()


def _merge_aliases(entry: dict, names) -> bool:
    known = {entry["label"].casefold(), *(alias.casefold() for alias in entry["aliases"])}
    changed = False
    for name in names:
        clean = name.strip() if isinstance(name, str) else ""
        if clean and clean.casefold() not in known:
            entry["aliases"].append(clean)
            known.add(clean.casefold())
            changed = True
    return changed


def _check_signature(path: Path, media: str) -> None:
    """Critic finding 11: refuse a file `assets.register` would refuse later,
    at `library add` time -- same detector, same extension/signature rule."""

    from .assets import _EXTENSION_MIME, AssetValidationError, _inspect_media

    try:
        mime_type, _, _ = _inspect_media(path.read_bytes())
    except (AssetValidationError, OSError) as error:
        raise LibraryError(f"file is not a valid {media} file: {error}") from error
    if _EXTENSION_MIME.get(path.suffix.casefold()) != mime_type:
        raise LibraryError("file extension does not match its content")


def add_file(index, library, *, kind, label, aliases=(), source_file, voice_of=None, source=None,
             strict_kind=True):
    """Add one file to an already-locked index; reuse an entry with the same sha256."""

    if kind not in KIND_FOLDERS:
        raise LibraryError(f"kind must be one of {sorted(KIND_FOLDERS)}")
    if not isinstance(label, str) or not label.strip():
        raise LibraryError("label must be a non-empty string")
    path = Path(source_file)
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise LibraryError("file does not exist") from error
    if not resolved.is_file():
        raise LibraryError("file must be a regular file")
    size = resolved.stat().st_size
    if size <= 0 or size > MAX_ASSET_BYTES:
        raise LibraryError("file size is outside the allowed range")
    media = media_of(resolved)
    if media not in _KIND_MEDIA.get(kind, _DEFAULT_MEDIA):
        raise LibraryError(f"a {kind} entry cannot hold {media}")
    if voice_of is not None:
        if kind != "voice":
            raise LibraryError("voice_of is only allowed for kind=voice")
        owner = find_entry(index, voice_of)
        if owner is None or owner["kind"] != "character":
            raise LibraryError("voice_of must name a character library entry")
    _check_signature(resolved, media)
    digest = sha256_of(resolved)
    existing = find_by_sha(index, digest)
    if existing is not None and existing["kind"] != kind and strict_kind:
        raise LibraryError(
            f"this file is already in the library as {existing['kind']} "
            f"{existing['library_id']} ({existing['label']})"
        )
    if existing is not None:
        merged = existing["kind"] == kind and _merge_aliases(existing, [label, *aliases])
        return existing, False, merged
    relative = _copy_into(library, kind, resolved, digest)
    entry = {
        "library_id": f"{kind}-{digest[:10]}",
        "kind": kind,
        "label": label.strip(),
        "aliases": [],
        "files": [{"path": relative, "sha256": digest, "media": media}],
        "added_at": _now(),
    }
    _merge_aliases(entry, aliases)
    if voice_of is not None:
        entry["voice_of"] = voice_of
    if source is not None:
        entry["source"] = dict(source)
    index["entries"].append(entry)
    return entry, True, False


def add(workspace, *, kind, label, aliases=(), file, voice_of=None) -> dict:
    library = library_root(workspace, create=True)
    with locked_index(library) as index:
        entry, created, merged = add_file(
            index, library, kind=kind, label=label, aliases=aliases,
            source_file=file, voice_of=voice_of,
        )
        result = {"library_id": entry["library_id"], "created": created,
                  "aliases_added": merged, "entry": json.loads(json.dumps(entry))}
    return result


def list_entries(workspace, *, kind=None) -> dict:
    if kind is not None and kind not in KIND_FOLDERS:
        raise LibraryError(f"kind must be one of {sorted(KIND_FOLDERS)}")
    entries = read_entries(workspace)
    if kind is not None:
        entries = [entry for entry in entries if entry["kind"] == kind]
    return {"library": LIBRARY_DIR_NAME, "count": len(entries), "entries": entries}


def read_entries(workspace) -> list[dict]:
    """Every entry, or `[]` when the workspace has no `library/` yet."""

    if not (Path(workspace) / LIBRARY_DIR_NAME).exists():
        return []
    return read_index(library_root(workspace))["entries"]


def get_entry(workspace, library_id) -> tuple[Path, dict]:
    library = library_root(workspace)
    entry = find_entry(read_index(library), library_id)
    if entry is None:
        raise LibraryError(f"unknown library entry: {library_id}")
    return library, entry

#!/usr/bin/env python3
"""Manage the deterministic workspace catalogue of reusable writing guides.

The registry contains metadata and content hashes only. Guide contents remain in
``<workspace>/instructions`` and are never copied into the installed package.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from studio.platform_compat import (  # noqa: E402
    ensure_utf8_stdio,
    file_lock,
    fsync_directory,
    replace_file,
)


SCHEMA_VERSION = 1
REGISTRY_NAME = "guides.json"
ROOT_FIELDS = {"schema_version", "revision", "entries"}
ENTRY_FIELDS = {
    "id",
    "title",
    "path",
    "sha256",
    "kind",
    "modalities",
    "tasks",
    "providers",
    "model_families",
    "models",
    "versions",
    "family_all_versions",
    "model_agnostic",
}
KINDS = {"scenario", "prompt"}
MODALITIES = {"scenario", "image", "video", "audio", "text"}
SLUG = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", re.ASCII)
SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)


class RegistryError(ValueError):
    """A safe, user-facing registry validation error."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise RegistryError(message)


def _require_exact_fields(value: Any, fields: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise RegistryError(f"{label} must be an object")
    missing = fields - set(value)
    extra = set(value) - fields
    if missing:
        raise RegistryError(f"{label} missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise RegistryError(f"{label} has unknown fields: {', '.join(sorted(extra))}")


def _require_slug(value: Any, label: str) -> None:
    if not isinstance(value, str) or SLUG.fullmatch(value) is None:
        raise RegistryError(f"{label} must be a lowercase portable slug")


def _require_string_list(
    value: Any,
    label: str,
    *,
    allow_wildcard: bool = False,
    require_slugs: bool = False,
) -> None:
    if not isinstance(value, list):
        raise RegistryError(f"{label} must be a list")
    if len(value) != len(set(value)):
        raise RegistryError(f"{label} must not contain duplicates")
    for item in value:
        if allow_wildcard and item == "*":
            continue
        if require_slugs:
            _require_slug(item, label)
        elif not isinstance(item, str) or not item.strip() or any(
            ord(character) < 32 for character in item
        ):
            raise RegistryError(f"{label} values must be non-empty scope strings")
    if "*" in value and len(value) != 1:
        raise RegistryError(f"{label} wildcard must be the only value")


def _require_relative_path(value: Any, label: str = "path") -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise RegistryError(f"{label} must be a non-empty relative path")
    path = Path(value)
    # `anchor` is also set for Windows' rooted `\x` and drive-relative `C:x`.
    if path.anchor or value.startswith("~") or ".." in path.parts or "." in path.parts:
        raise RegistryError(f"{label} must stay below the instructions directory")
    return path


def _validate_entry(entry: Any, index: int) -> None:
    label = f"entries[{index}]"
    _require_exact_fields(entry, ENTRY_FIELDS, label)
    _require_slug(entry["id"], f"{label}.id")
    if not isinstance(entry["title"], str) or not entry["title"].strip():
        raise RegistryError(f"{label}.title must be a non-empty string")
    _require_relative_path(entry["path"], f"{label}.path")
    if not isinstance(entry["sha256"], str) or SHA256.fullmatch(entry["sha256"]) is None:
        raise RegistryError(f"{label}.sha256 must be a lowercase SHA-256 digest")
    if entry["kind"] not in KINDS:
        raise RegistryError(f"{label}.kind must be scenario or prompt")
    _require_string_list(entry["modalities"], f"{label}.modalities", require_slugs=True)
    if not entry["modalities"] or not set(entry["modalities"]) <= MODALITIES:
        raise RegistryError(f"{label}.modalities must contain canonical modalities")
    _require_string_list(entry["tasks"], f"{label}.tasks", require_slugs=True)
    if not entry["tasks"]:
        raise RegistryError(f"{label}.tasks must not be empty")
    _require_string_list(entry["providers"], f"{label}.providers", allow_wildcard=True)
    _require_string_list(entry["model_families"], f"{label}.model_families")
    _require_string_list(entry["models"], f"{label}.models")
    _require_string_list(entry["versions"], f"{label}.versions")
    if not isinstance(entry["family_all_versions"], bool):
        raise RegistryError(f"{label}.family_all_versions must be boolean")
    if not isinstance(entry["model_agnostic"], bool):
        raise RegistryError(f"{label}.model_agnostic must be boolean")
    if entry["family_all_versions"] and not entry["model_families"]:
        raise RegistryError(f"{label}.family_all_versions requires model_families")
    if entry["models"] and entry["family_all_versions"]:
        raise RegistryError(
            f"{label}.family_all_versions cannot be combined with exact models"
        )
    if entry["versions"] and not (entry["models"] or entry["model_families"]):
        raise RegistryError(f"{label}.versions requires models or model_families")
    if entry["model_agnostic"] and (
        entry["models"] or entry["model_families"] or entry["versions"] or entry["family_all_versions"]
    ):
        raise RegistryError(f"{label}.model_agnostic cannot be combined with model scope")
    if entry["kind"] == "prompt":
        exact = bool(
            entry["models"] and entry["model_families"] and entry["versions"]
        )
        family = bool(
            entry["model_families"]
            and (entry["versions"] or entry["family_all_versions"])
        )
        if not (exact or family or entry["model_agnostic"]):
            raise RegistryError(
                f"{label} prompt scope requires model+family+version, versioned family, "
                "family_all_versions, or model_agnostic"
            )


def validate_registry(value: Any) -> dict[str, Any]:
    _require_exact_fields(value, ROOT_FIELDS, "registry")
    if value["schema_version"] != SCHEMA_VERSION:
        raise RegistryError("schema_version must be 1")
    if isinstance(value["revision"], bool) or not isinstance(value["revision"], int) or value["revision"] < 0:
        raise RegistryError("revision must be a non-negative integer")
    if not isinstance(value["entries"], list):
        raise RegistryError("entries must be a list")
    ids: set[str] = set()
    for index, entry in enumerate(value["entries"]):
        _validate_entry(entry, index)
        if entry["id"] in ids:
            raise RegistryError(f"duplicate guide id: {entry['id']}")
        ids.add(entry["id"])
    return value


def _registry_path(workspace: Path) -> Path:
    try:
        root = workspace.resolve(strict=True)
    except OSError as error:
        raise RegistryError("workspace does not exist or is unreadable") from error
    if not root.is_dir() or root == Path(root.anchor):
        raise RegistryError("workspace must be an existing non-root directory")
    instructions = root / "instructions"
    if instructions.exists():
        try:
            resolved = instructions.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as error:
            raise RegistryError("instructions directory escapes the workspace") from error
        if not resolved.is_dir():
            raise RegistryError("instructions must be a directory")
        instructions = resolved
    return instructions / REGISTRY_NAME


@contextmanager
def _registry_lock(registry_path: Path):
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = registry_path.parent / ".guides.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+b") as handle, file_lock(handle):
        yield


def _read_registry(path: Path) -> tuple[dict[str, Any], bytes | None]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "revision": 0, "entries": []}, None
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RegistryError("guides.json is unreadable or invalid JSON") from error
    return validate_registry(value), raw


def _atomic_write(path: Path, value: dict[str, Any], baseline: bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = path.read_bytes() if path.exists() else None
    except OSError as error:
        raise RegistryError("could not verify the current registry") from error
    if current != baseline:
        raise RegistryError("guides.json changed concurrently; retry the command")
    serialized = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _guide_file(instructions: Path, relative: str) -> Path:
    path = _require_relative_path(relative)
    try:
        root = instructions.resolve(strict=True)
        candidate = (instructions / path).resolve(strict=True)
    except OSError as error:
        raise RegistryError("guide file does not exist or is unreadable") from error
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise RegistryError("guide path escapes the instructions directory") from error
    if not candidate.is_file():
        raise RegistryError("guide path must identify a regular file")
    return candidate


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise RegistryError("guide file is unreadable") from error
    return digest.hexdigest()


def command_register(args: argparse.Namespace) -> dict[str, Any]:
    registry_path = _registry_path(args.workspace)
    with _registry_lock(registry_path):
        registry, baseline = _read_registry(registry_path)
        if args.expected_revision is not None and registry["revision"] != args.expected_revision:
            raise RegistryError("registry revision does not match --expected-revision")
        instructions = registry_path.parent
        guide = _guide_file(instructions, args.path)
        entry = {
            "id": args.id,
            "title": args.title,
            "path": Path(args.path).as_posix(),
            "sha256": _digest(guide),
            "kind": args.kind,
            "modalities": sorted(set(args.modality)),
            "tasks": sorted(set(args.task)),
            "providers": sorted(set(args.provider)),
            "model_families": sorted(set(args.model_family)),
            "models": sorted(set(args.model)),
            "versions": sorted(set(args.version)),
            "family_all_versions": args.family_all_versions,
            "model_agnostic": args.model_agnostic,
        }
        _validate_entry(entry, 0)
        entries = [item for item in registry["entries"] if item["id"] != entry["id"]]
        entries.append(entry)
        entries.sort(key=lambda item: item["id"])
        updated = {
            "schema_version": SCHEMA_VERSION,
            "revision": registry["revision"] + 1,
            "entries": entries,
        }
        _atomic_write(registry_path, updated, baseline)
    return {"ok": True, "revision": updated["revision"], "entry": entry}


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    registry, _ = _read_registry(_registry_path(args.workspace))
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "revision": registry["revision"],
        "entries": registry["entries"],
    }


def _provider_matches(scopes: list[str], provider: str | None) -> bool:
    if not scopes:
        return provider is None
    if provider is None:
        return False
    return scopes == ["*"] or provider in scopes


def _model_rank(entry: dict[str, Any], args: argparse.Namespace) -> int | None:
    model = args.model
    family = args.model_family
    version = args.version
    if (
        entry["models"]
        and model in entry["models"]
        and entry["model_families"]
        and family in entry["model_families"]
        and version in entry["versions"]
    ):
        return 500
    if not entry["models"] and entry["model_families"] and family in entry["model_families"]:
        if version in entry["versions"]:
            return 400
        if version is not None and entry["family_all_versions"]:
            return 300
    if entry["model_agnostic"] and version is not None and (model is not None or family is not None):
        return 200
    if entry["kind"] == "scenario" and not (
        entry["models"]
        or entry["model_families"]
        or entry["versions"]
        or entry["family_all_versions"]
        or entry["model_agnostic"]
    ):
        if model is None and family is None and version is None:
            return 100
    return None


def _stale_reason(instructions: Path, entry: dict[str, Any]) -> str | None:
    try:
        path = _guide_file(instructions, entry["path"])
        actual = _digest(path)
    except RegistryError:
        return "missing-unreadable-or-unsafe"
    if actual != entry["sha256"]:
        return "sha256-mismatch"
    return None


def command_match(args: argparse.Namespace) -> dict[str, Any]:
    registry_path = _registry_path(args.workspace)
    registry, _ = _read_registry(registry_path)
    matches: list[tuple[int, dict[str, Any]]] = []
    stale: list[dict[str, str]] = []
    for entry in registry["entries"]:
        if (
            entry["kind"] != args.kind
            or args.modality not in entry["modalities"]
            or args.task not in entry["tasks"]
            or not _provider_matches(entry["providers"], args.provider)
        ):
            continue
        rank = _model_rank(entry, args)
        if rank is None:
            continue
        reason = _stale_reason(registry_path.parent, entry)
        if reason is not None:
            stale.append({"id": entry["id"], "status": "stale", "reason": reason})
            continue
        matches.append((rank, entry))
    matches.sort(key=lambda item: (-item[0], item[1]["id"]))
    stale.sort(key=lambda item: item["id"])
    return {
        "ok": True,
        "revision": registry["revision"],
        "matches": [dict(item, match_rank=rank) for rank, item in matches],
        "stale": stale,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description="Manage reusable writing-guide metadata")
    parser.add_argument("--workspace", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)

    register = commands.add_parser("register", help="register or replace one guide entry")
    register.add_argument("--id", required=True)
    register.add_argument("--title", required=True)
    register.add_argument("--path", required=True)
    register.add_argument("--kind", required=True, choices=sorted(KINDS))
    register.add_argument("--modality", required=True, action="append", choices=sorted(MODALITIES))
    register.add_argument("--task", required=True, action="append")
    register.add_argument("--provider", action="append", default=[])
    register.add_argument("--model-family", action="append", default=[])
    register.add_argument("--model", action="append", default=[])
    register.add_argument("--version", action="append", default=[])
    register.add_argument("--family-all-versions", action="store_true")
    register.add_argument("--model-agnostic", action="store_true")
    register.add_argument("--expected-revision", type=int)
    register.set_defaults(handler=command_register)

    listing = commands.add_parser("list", help="list registered guide metadata")
    listing.set_defaults(handler=command_list)

    match = commands.add_parser("match", help="find valid guides for an exact writing scope")
    match.add_argument("--kind", required=True, choices=sorted(KINDS))
    match.add_argument("--modality", required=True, choices=sorted(MODALITIES))
    match.add_argument("--task", required=True)
    match.add_argument("--provider")
    match.add_argument("--model-family")
    match.add_argument("--model")
    match.add_argument("--version")
    match.set_defaults(handler=command_match)
    return parser


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    try:
        args = build_parser().parse_args(argv)
        payload = args.handler(args)
    except (RegistryError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Versioned, portable material handoff; completion stays a reviewed milestone."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import domain
from .domain_positions import current_member, position_specs


class CompletionError(ValueError):
    """A handoff is incomplete, stale or no longer matches its files."""


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(root, relative):
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or PureWindowsPath(relative).anchor or PurePosixPath(relative).is_absolute()
            or ".." in PurePosixPath(relative).parts):
        raise CompletionError("handoff path must be relative and stay inside its directory")
    root = Path(root).resolve(strict=True)
    target = root / relative
    cursor = target
    while cursor != root:
        if cursor.is_symlink():
            raise CompletionError("handoff paths must not contain symlinks")
        cursor = cursor.parent
    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CompletionError("handoff file is missing or unsafe") from error
    if not resolved.is_file():
        raise CompletionError("handoff must contain regular files")
    return resolved


def selected_materials(state):
    """Follow explicit current owner links, never select the latest sibling."""
    positions = {item["position_id"]: item for item in domain.derive_positions(state)}
    selected = []
    for spec in position_specs(state):
        position = positions.get(spec["position_id"])
        if position is None:
            continue
        member = current_member(state, spec, "result")
        valid = (isinstance(member, dict) and member.get("decision") == "approved"
                 and not any(member.get(key) for key in ("hidden", "retired", "stale"))
                 and isinstance(member.get("asset_id"), str) and bool(member["asset_id"]))
        prompt = current_member(state, spec, "prompt")
        if prompt and (prompt.get("stale") is True or
                       ("basis" in prompt and domain.compute_prompt_stale(state, prompt, spec))):
            valid = False
        if not valid:
            if position["required"]:
                raise CompletionError("required selected materials are missing, unapproved or stale")
            continue
        selected.append({"asset_id": member["asset_id"], "position_id": spec["position_id"],
                         "kind": spec["kind"],
                         **{key: spec[key] for key in ("scene_id", "layer", "tag") if key in spec}})
    if not selected:
        raise CompletionError("no selected materials to deliver")
    return selected


def materials_ready(state):
    assembly = state.get("assembly", {})
    if not isinstance(assembly, dict) or assembly.get("kind") != "materials" or assembly.get("status") != "ready":
        return False
    try:
        expected = list(dict.fromkeys(item["asset_id"] for item in selected_materials(state)))
    except (CompletionError, domain.DomainValidationError):
        return False
    manifest = assembly.get("manifest")
    return (assembly.get("asset_ids") == expected and isinstance(manifest, dict)
            and isinstance(manifest.get("path"), str) and isinstance(manifest.get("sha256"), str))


def verify_manifest(path):
    """Verify a portable copy without any access to the original workspace."""
    path = Path(path)
    if path.is_symlink():
        raise CompletionError("manifest must not be a symlink")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CompletionError("manifest is missing or unreadable") from error
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
            or manifest.get("kind") != "materials" or not isinstance(manifest.get("assets"), list)
            or not manifest["assets"]):
        raise CompletionError("invalid materials manifest")
    seen = set()
    for item in manifest["assets"]:
        if not isinstance(item, dict) or not isinstance(item.get("asset_id"), str) or item["asset_id"] in seen:
            raise CompletionError("manifest assets must have unique identities")
        seen.add(item["asset_id"])
        asset = _inside(path.parent, item.get("path"))
        if _digest(asset) != item.get("sha256"):
            raise CompletionError("material checksum mismatch")
    return manifest


def verify_assembly(state, project_directory):
    """Storage-boundary validation immediately before terminal approval."""
    if not materials_ready(state):
        raise CompletionError("selected materials no longer match the prepared handoff")
    assembly = state["assembly"]
    path = _inside(project_directory, assembly["manifest"]["path"])
    if _digest(path) != assembly["manifest"]["sha256"]:
        raise CompletionError("manifest checksum mismatch")
    manifest = verify_manifest(path)
    if (manifest.get("project_id") != state["project"]["id"]
            or [item["asset_id"] for item in manifest["assets"]] != assembly["asset_ids"]):
        raise CompletionError("manifest does not match this project's selected assets")
    return manifest


def prepare_materials(workspace, project_id, expected_revision):
    """Create a verified immutable packet and record it through the canonical writer."""
    from .authoring_support import mutate, open_assets, open_store
    store, assets = open_store(workspace), open_assets(workspace)
    project_directory = store.project_dir(project_id)
    outcome = {}

    def prepare(state):
        if state["project"].get("assembly_mode", "montage") != "materials":
            raise CompletionError("select materials assembly mode before preparing the handoff")
        view = domain.derive_view_stage(state)
        if view["current_stage"] != "assembly" or view["gate_status"] in {"blocked", "approved"}:
            raise CompletionError("materials preparation requires the open assembly review")
        selected = selected_materials(state)
        root = project_directory / "materials"
        if root.is_symlink():
            raise CompletionError("materials directory must not be a symlink")
        root.mkdir(exist_ok=True)
        target = root / f"r{expected_revision + 1}"
        if target.is_symlink():
            raise CompletionError("handoff revision must not be a symlink")
        with tempfile.TemporaryDirectory(prefix=".prepare-", dir=root) as temporary:
            staging = Path(temporary)
            (staging / "assets").mkdir()
            records = []
            for item in selected:
                if any(record["asset_id"] == item["asset_id"] for record in records):
                    continue
                source, mime = assets.resolve(item["asset_id"])
                if assets.role_of(item["asset_id"]) != "result":
                    raise CompletionError("handoff assets must be registered results")
                relative = f"assets/{len(records) + 1:03d}-{_digest(source)[:16]}{source.suffix.lower()}"
                destination = staging / relative
                digest = _digest(source)
                shutil.copyfile(source, destination)
                if _digest(destination) != digest:
                    raise CompletionError("source changed while preparing materials")
                records.append(dict(item, path=relative, sha256=digest, mime_type=mime))
            manifest = {"schema_version": 1, "kind": "materials", "project_id": project_id,
                        "source_revision": expected_revision, "assets": records}
            manifest_path = staging / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            (staging / "README.txt").write_text(
                "Готовые материалы / Selected materials\n"
                "Файлы находятся в assets/. Контрольные суммы — manifest.json.\n"
                "Files are in assets/. Checksums are recorded in manifest.json.\n", encoding="utf-8")
            verify_manifest(manifest_path)
            digest = _digest(manifest_path)
            if target.exists():
                # A crash may have landed the packet before the state transaction.
                # Reconcile that exact packet; never overwrite a conflicting one.
                existing = target / "manifest.json"
                verify_manifest(existing)
                if _digest(existing) != digest:
                    raise CompletionError("existing handoff revision conflicts with selected materials")
            else:
                staging.rename(target)
        relative_manifest = (target / "manifest.json").relative_to(project_directory).as_posix()
        state["assembly"] = {"kind": "materials", "status": "ready",
                             "asset_ids": [record["asset_id"] for record in records],
                             "summary": "Материалы готовы",
                             "manifest": {"path": relative_manifest, "sha256": digest}}
        domain.append_history(state, "agent", "assembly-ready", "assembly")
        outcome.update(manifest_path=str(target / "manifest.json"), asset_ids=state["assembly"]["asset_ids"])

    _, state = mutate(store, project_id, expected_revision, prepare)
    return {"project_id": project_id, "revision": state["revision"], **outcome}

"""One job-bound typed request to existing authoring APIs; no shell or dispatcher loop."""
import json
import os
from pathlib import Path
import re

from . import authoring
from .platform_compat import file_lock, open_text_nofollow
from .safe_paths import safe_path
from .store import RevisionConflict
from .workspace import resolve_workspace_paths

SCHEMAS = {
    "script.add-version": ({"text", "reason"}, set()),
    "scenes.set": ({"scenes"}, set()),
    "prompt.add-version": ({"target", "text", "reason"}, set()),
    "guide.select": ({"choice"}, set()),
    "reference.add": (set(), {"kind", "name", "asset_id", "library_id", "library_file_index", "source", "usage", "scene_id", "all_scenes"}),
    "reference.attach": ({"reference_id"}, {"asset_id", "library_id", "library_file_index"}),
    "asset.register": ({"path", "role"}, set()),
    "result.add-upload": ({"target", "asset_id", "source"}, {"caption"}),
    "materials.prepare": (set(), set()),
    "montage.build": (set(), {"style", "improve"}),
    "montage.export": (set(), {"version"}),
}
JOB_OPERATIONS = {"revise-scenario": {"script.add-version"}, "prompts-generate": {"prompt.add-version"},
                  "prompt-refresh": {"prompt.add-version"}, "assemble": {"materials.prepare", "montage.build", "montage.export"}}


def operation_schemas(action_type):
    permitted = set(SCHEMAS) if action_type == "continue-in-chat" else JOB_OPERATIONS.get(action_type, set())
    return {op: {"required": sorted(SCHEMAS[op][0]), "optional": sorted(SCHEMAS[op][1])} for op in sorted(permitted)}


class JobAuthoringError(ValueError):
    pass


def request_path(workspace, action_id, *, prepare=False):
    if not isinstance(action_id, str) or not re.fullmatch(r"action-[0-9a-f]{32}", action_id):
        raise JobAuthoringError("invalid_action_id")
    root, _, _, private = resolve_workspace_paths(workspace)
    target = safe_path(root, private / "operator-inputs" / (action_id + ".json"))
    if prepare:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return target


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise JobAuthoringError("duplicate_json_key")
        result[key] = value
    return result


def _fields(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) <= set(required) | set(optional):
        raise JobAuthoringError("unsupported_request_fields")


def _nonfinite(value):
    raise JobAuthoringError("nonfinite_json")


def _asset(workspace, assets, identity):
    row = assets.stored(identity)
    safe_path(workspace, Path(workspace) / row["relative_path"])
    assets.resolve(identity)
    return identity


def _library(workspace, identity, index):
    from .library import get_entry, library_file, KIND_FOLDERS
    from .library_projects import materialize
    root = Path(workspace).resolve(strict=True)
    safe_path(root, root / "library/index.json")
    library, entry = get_entry(root, identity)
    if type(index) is not int or not 0 <= index < len(entry["files"]):
        raise JobAuthoringError("invalid_library_file_index")
    item = entry["files"][index]
    safe_path(root, library / item["path"])
    source = library_file(library, item["path"])
    destination = root / "media/library" / KIND_FOLDERS[entry["kind"]] / (item["sha256"][:12] + "-" + source.name)
    safe_path(root, destination)
    return materialize(root, identity, file_index=index)


def _reference(workspace, store, assets, project, revision, op, data):
    asset_id, library_id = data.get("asset_id"), data.get("library_id")
    if asset_id and library_id:
        raise JobAuthoringError("choose_one_reference_input")
    entry, media = None, None
    if library_id:
        materialized = _library(workspace, library_id, data.get("library_file_index", 0))
        asset_id, entry, media = materialized["asset"]["asset_id"], materialized["entry"], materialized["media"]
    if asset_id:
        _asset(workspace, assets, asset_id)
    if op == "reference.attach":
        if not asset_id:
            raise JobAuthoringError("reference_input_required")
        return authoring.attach_reference(store, assets, project, revision, reference_id=data["reference_id"],
                                          asset_id=asset_id, library_id=library_id)
    if entry and entry["kind"] == "voice":
        raise JobAuthoringError("voice_requires_reference_attach")
    kind = data.get("kind") or ("video" if media == "video" else entry["kind"] if entry else None)
    if type(data.get("all_scenes", False)) is not bool:
        raise JobAuthoringError("invalid_all_scenes")
    return authoring.add_reference(store, assets, project, revision, kind=kind, name=data.get("name") or (entry["label"] if entry else None),
        asset_id=asset_id, library_id=library_id, source="upload" if library_id else data.get("source", "upload"),
        usage=data.get("usage", "reference"), scene_id=data.get("scene_id"), all_scenes=data.get("all_scenes", False))


def _apply(workspace, store, action, request):
    op, data = request["op"], request["data"]
    project, revision = action["project_id"], request["expected_revision"]
    if op == "script.add-version":
        return authoring.add_script_version(store, project, revision, data["text"], data["reason"])
    if op == "scenes.set":
        return authoring.set_scenes(store, project, revision, data["scenes"])
    if op == "prompt.add-version":
        if action["action_type"] == "prompt-refresh" and action["target_id"].startswith("pos:") and data["target"] != action["target_id"]:
            raise JobAuthoringError("prompt_target_mismatch")
        return authoring.add_prompt_version(store, project, revision, target=data["target"], text=data["text"], reason=data["reason"])
    if op == "guide.select":
        return authoring.set_guide_choice(store, workspace, project, revision, data["choice"])
    assets = authoring.open_assets(workspace)
    if op.startswith("reference."):
        return _reference(workspace, store, assets, project, revision, op, data)
    if op == "asset.register":
        relative = data["path"]
        if not isinstance(relative, str) or not relative.startswith("media/") or ".." in relative.split("/") or "\\" in relative or ":" in relative:
            raise JobAuthoringError("invalid_upload_path")
        supplied = action["payload"].get("attachments", [])
        if not isinstance(supplied, list) or relative not in {item.get("path") for item in supplied if isinstance(item, dict)}:
            raise JobAuthoringError("upload_not_in_job_inputs")
        safe_path(workspace, Path(workspace) / relative)
        return assets.register(relative, data["role"])
    if op == "result.add-upload":
        if data["source"] != "upload":
            raise JobAuthoringError("only_explicit_upload_results")
        return authoring.add_result_version(store, assets, project, revision, target=data["target"],
            asset_id=_asset(workspace, assets, data["asset_id"]), caption=data.get("caption"))
    if op == "materials.prepare":
        from .completion import prepare_materials
        return prepare_materials(workspace, project, revision)
    from .montage import service
    if op == "montage.build":
        if type(data.get("improve", False)) is not bool:
            raise JobAuthoringError("invalid_improvement_choice")
        return service.build(workspace, project, revision, style=data.get("style"), improve=data.get("improve", False))
    if op == "montage.export":
        root, _, _, private = resolve_workspace_paths(workspace)
        destination = safe_path(root, private / "job-exports" / action["action_id"])
        result = service.export(workspace, project, destination=destination, version=data.get("version"))
        return {"kind": result["kind"], "version": result.get("version"), "destination": destination.relative_to(root).as_posix()}
    raise JobAuthoringError("unsupported_operation")


def apply_request(workspace, action_id, supplied_path):
    expected = request_path(workspace, action_id)
    if Path(supplied_path).absolute() != expected:
        raise JobAuthoringError("request_path_mismatch")
    root = resolve_workspace_paths(workspace)[0]
    safe_path(root, expected)
    if not expected.is_file() or not 0 < expected.stat().st_size <= 512 * 1024:
        raise JobAuthoringError("invalid_request_file")
    from .runner import open_runner
    from .operator import status
    runner = open_runner(root)
    with open_text_nofollow(expected.with_suffix(".lock")) as handle, file_lock(handle):
        action = runner.ledger.get_action(action_id)
        if action["status"] != "running" or not action["worker_id"]:
            raise JobAuthoringError("job_not_running")
        live = status(root)
        if not live["available"] or live["active_action_id"] != action_id:
            raise JobAuthoringError("job_controller_not_active")
        if action["action_type"] in {"generate", "vary", "regenerate"}:
            raise JobAuthoringError("paid_authoring_forbidden")
        with open_text_nofollow(expected, "r") as source:
            if not 0 < os.fstat(source.fileno()).st_size <= 512 * 1024:
                raise JobAuthoringError("invalid_request_file")
            request = json.loads(source.read(512 * 1024 + 1), object_pairs_hook=_object, parse_constant=_nonfinite)
        _fields(request, {"op", "project_id", "expected_revision", "data"})
        if request["project_id"] != action["project_id"]:
            raise JobAuthoringError("project_mismatch")
        op = request["op"]
        if not isinstance(op, str) or op not in SCHEMAS:
            raise JobAuthoringError("unsupported_operation")
        if op not in operation_schemas(action["action_type"]):
            raise JobAuthoringError("operation_outside_job")
        _fields(request["data"], *SCHEMAS[op])
        revision = request["expected_revision"]
        current = runner.store.load(action["project_id"])
        if type(revision) is not int or revision < runner.ledger.execution_revision(action_id):
            raise JobAuthoringError("invalid_job_revision")
        if revision != current["revision"]:
            raise RevisionConflict(revision, current["revision"])
        result = _apply(root, runner.store, action, request)
        allowed = {"version_id", "result_id", "prompt_id", "reference_id", "asset_id", "asset_ids", "version", "duration", "kind", "destination"}
        return {"ok": True, "action_id": action_id, "project_id": action["project_id"],
                "revision": runner.store.load(action["project_id"])["revision"], **{key:value for key,value in result.items() if key in allowed}}

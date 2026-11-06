"""Private selected execution routes tied to canonical prompt/reference basis (D12)."""
import hashlib
import json
from pathlib import Path
import re

from . import authoring, domain
from .domain_positions import position_specs, current_member, resolve_position
from .family_setup.state import write_json
from .platform_compat import file_lock, open_text_nofollow
from .operator_adapters import state_digest
from .workspace import resolve_workspace_paths

PROVIDERS = {"syntx", "higgsfield", "magnific", "fal"}
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}\Z")


class RouteUnavailable(ValueError):
    pass


def _paths(workspace):
    private = resolve_workspace_paths(workspace)[3]
    private.mkdir(exist_ok=True, mode=0o700)
    if private.is_symlink():
        raise RouteUnavailable("unsafe route storage")
    return private / "routes.json", private / "routes.lock"


def _read(path):
    if path.is_symlink():
        raise RouteUnavailable("unsafe route storage")
    if not path.exists():
        return {"schema_version": 1, "routes": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("routes"), list):
        raise RouteUnavailable("invalid route storage")
    return value


def action_position(state, kind, target):
    if kind == "generate":
        return resolve_position(state, target)
    matches = []
    for spec in position_specs(state):
        members = state.get(spec["result_collection"], [])
        current = current_member(state, spec, "result", missing_ok=True)
        if current and any(target in {item.get("result_id"), item.get("version_id")} and
                           item.get("result_id") == current.get("result_id") for item in members):
            matches.append(spec)
    if len(matches) != 1:
        raise RouteUnavailable("result has no exact generation position")
    return matches[0]


def action_result(state, kind, target):
    """Resolve the exact requested version, or the current one for a group id."""
    spec = action_position(state, kind, target)
    current = current_member(state, spec, "result", missing_ok=True)
    if not current:
        raise RouteUnavailable("result position is empty")
    group = current.get("result_id")
    members = [item for item in state.get(spec["result_collection"], [])
               if item.get("result_id") == group]
    exact = [item for item in members if item.get("version_id") == target]
    if len(exact) == 1:
        result = exact[0]
    elif not exact and target == group:
        result = current
    else:
        raise RouteUnavailable("result version is missing or ambiguous")
    if (result.get("scene_id", spec.get("scene_id")) != spec.get("scene_id")
            or result.get("retired") or result.get("hidden") or result.get("decision") == "rejected"
            or not isinstance(result.get("asset_id"), str) or not result["asset_id"]):
        raise RouteUnavailable("result version is unavailable")
    return spec, result


def _scope(workspace, state, spec):
    prompt = current_member(state, spec, "prompt", missing_ok=True)
    if not prompt or not prompt.get("text") or domain.compute_prompt_stale(state, prompt, spec):
        raise RouteUnavailable("missing or stale prompt")
    refs = state.get("references", [])
    assets = authoring.open_assets(workspace) if refs else None
    reference_checksums = {}
    for ref in refs:
        identities = [ref.get("asset_id"), ref.get("voice", {}).get("asset_id")]
        for identity in filter(None, identities):
            assets.resolve(identity)
            reference_checksums[identity] = assets.stored(identity)["digest"]
    return {"project_id": state["project"]["id"], "position_id": spec["position_id"],
            "prompt_version_id": prompt.get("version_id", prompt["prompt_id"]),
            "prompt_sha256": hashlib.sha256(prompt["text"].encode()).hexdigest(),
            "basis_sha256": state_digest({"basis": domain.prompt_basis(state, spec),
                "references": refs, "checksums": reference_checksums,
                "guide_choices": state["project"].get("guide_choices", [])})}


def _parameters(value):
    if not isinstance(value, dict) or len(json.dumps(value, allow_nan=False).encode()) > 16384:
        raise RouteUnavailable("invalid route parameters")
    def check(item):
        if isinstance(item, dict):
            for key, part in item.items():
                if not isinstance(key, str) or re.search(r"token|secret|password|auth|cookie|credential|endpoint|tool|url|path", key, re.I):
                    raise RouteUnavailable("parameters cannot name credentials, paths or executable routes")
                check(part)
        elif isinstance(item, list):
            for part in item:
                check(part)
        elif isinstance(item, str) and ("://" in item or item.startswith(("/", "\\", "~")) or re.match(r"[A-Za-z]:", item)):
            raise RouteUnavailable("parameters cannot name remote/local resources")
    check(value)
    return value


def set_route(workspace, project_id, position_id, expected_revision, *, provider, model, operation, parameters, collection_mode="provider-original"):
    if provider not in PROVIDERS or any(not isinstance(x, str) or not _NAME.fullmatch(x) or "://" in x for x in (model, operation)):
        raise RouteUnavailable("unsupported route selection")
    if collection_mode not in {"provider-original", "host-local-original"}:
        raise RouteUnavailable("unsupported collection mode")
    state = authoring.open_store(workspace).load(project_id)
    if type(expected_revision) is not int or state["revision"] != expected_revision:
        from .store import RevisionConflict
        raise RevisionConflict(expected_revision, state["revision"])
    scope = _scope(workspace, state, resolve_position(state, position_id))
    record = {**scope, "provider": provider, "model": model, "operation": operation,
              "parameters": _parameters(parameters), "collection_mode": collection_mode}
    record["route_id"] = "route-" + state_digest(record)[:32]
    path, lock = _paths(workspace)
    with open_text_nofollow(lock) as handle, file_lock(handle):
        data = _read(path)
        data["routes"] = [row for row in data["routes"] if (row.get("project_id"), row.get("position_id")) != (project_id, position_id)] + [record]
        write_json(path, data)
    return {key: record[key] for key in record if key != "parameters"}


def dispatch_guides(state, spec, route):
    """Supply prompt guides scoped to the chosen medium and service."""
    modality = {"image_results": "image", "video_results": "video",
                "audio_results": "audio"}[spec["result_collection"]]
    stages = {"image": {"image_plan", "image_results"}, "video": {"image_plan", "motion"},
              "audio": {"audio"}}[modality]
    return [choice for choice in state["project"].get("guide_choices", [])
            if choice["stage"] in stages and choice["kind"] == "prompt"
            and choice["modality"] == modality and choice["provider"] in {None, route["provider"]}
            and choice["model"] in {None, route["model"]}]


def selected_route(workspace, state, kind, target, *, frozen_collection=False):
    spec = action_position(state, kind, target)
    scope = _scope(workspace, state, spec)
    path, _ = _paths(workspace)
    rows = [row for row in _read(path)["routes"] if row.get("project_id") == state["project"]["id"]
            and row.get("position_id") == spec["position_id"]]
    if len(rows) != 1 or any(rows[0].get(key) != value for key, value in scope.items()):
        raise RouteUnavailable("choose a current route in chat")
    record = rows[0]
    if record.get("collection_mode", "provider-original") not in {"provider-original", "host-local-original"}:
        raise RouteUnavailable("invalid collection mode")
    content = {key: value for key, value in record.items() if key != "route_id"}
    if record.get("route_id") != "route-" + state_digest(content)[:32] or record.get("provider") not in PROVIDERS:
        raise RouteUnavailable("invalid route record")
    _parameters(record["parameters"])
    if not frozen_collection:
        from .guide_catalog import resolve_choice
        for choice in dispatch_guides(state, spec, record):
            if choice["source"] != "none":
                try:
                    resolve_choice(workspace, choice)
                except (ValueError, OSError):
                    raise RouteUnavailable("selected guide changed; choose the current guide before generation") from None
    return record


def uncertain_position(ledger, state, kind, target):
    position = action_position(state, kind, target)["position_id"]
    for action in ledger.uncertain_actions(state["project"]["id"]):
        if action["action_type"] not in {"generate", "vary", "regenerate"}:
            continue
        # Only an explicit audited resolution permits a new authorized result
        # action; merely observing completion or a blocked collection does not.
        if kind in {"vary", "regenerate"} and ledger.collection(action["action_id"]) in {"resolved_adopt", "resolved_keep"}:
            continue
        try:
            other = action_position(state, action["action_type"], action["target_id"])["position_id"]
        except ValueError:
            return True  # A disappeared owner is not proof that its paid job never ran.
        if other == position:
            return True
    return False


def public_routes(workspace, project_id):
    state = authoring.open_store(workspace).load(project_id)
    rows = []
    for spec in position_specs(state):
        try:
            route = selected_route(workspace, state, "generate", spec["position_id"])
        except (ValueError, OSError):
            rows.append({"position_id": spec["position_id"], "status": "needs_setup"})
        else:
            from .provider_download import preflight
            supported = preflight(route)
            rows.append({key: route[key] for key in ("position_id", "route_id", "provider", "model", "operation", "prompt_version_id", "prompt_sha256")} | {
                "status": "selected" if supported else "needs_setup", "collection_supported": supported})
    from .runner import open_ledger
    ledger = open_ledger(workspace)
    collections = []
    for action in ledger.uncertain_actions(project_id):
        if action["action_type"] not in {"generate", "vary", "regenerate"}:
            continue
        try:
            position = action_position(state, action["action_type"], action["target_id"])["position_id"]
        except (ValueError, KeyError):
            position = None
        row = {"action_id": action["action_id"], "phase": ledger.collection(action["action_id"]), "position_id": position}
        if row["phase"] in {"resolved_adopt", "resolved_keep"}:
            continue
        if row["phase"] == "conflict":
            try:
                from .provider_collection import recovered_preview, _basis_matches, adoption_already_applied
                from .provider_receipts import path_for, read
                from .decision_cards import STAGE_COLLECTIONS
                from .domain_positions import current_member
                from .runner import open_runner
                row["preview"] = recovered_preview(workspace, open_runner(workspace), action["action_id"])
                spec = resolve_position(state, position)
                row["can_keep"] = bool(current_member(state, spec, "result", missing_ok=True))
                row["resume_applied"] = adoption_already_applied(workspace, open_runner(workspace), action["action_id"], state)
                if row["resume_applied"]:
                    row["can_adopt"] = True
                    row["can_keep"] = False
                    collections.append(row)
                    continue
                basis = read(path_for(workspace, action["action_id"], "basis"))
                _basis_matches(workspace, basis, state)
                stage = STAGE_COLLECTIONS[spec["result_collection"]][0]
                row["can_adopt"] = state.get("milestones", {}).get(stage, "draft") != "approved"
            except (ValueError, OSError, RuntimeError, KeyError, TypeError):
                row.setdefault("can_adopt", False)
                row.setdefault("can_keep", False)
                row.setdefault("preview", None)
        collections.append(row)
    return {"revision": state["revision"], "routes": rows, "collections": collections}

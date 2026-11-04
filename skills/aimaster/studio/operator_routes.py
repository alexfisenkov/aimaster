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


def set_route(workspace, project_id, position_id, expected_revision, *, provider, model, operation, parameters):
    if provider not in PROVIDERS or any(not isinstance(x, str) or not _NAME.fullmatch(x) or "://" in x for x in (model, operation)):
        raise RouteUnavailable("unsupported route selection")
    state = authoring.open_store(workspace).load(project_id)
    if type(expected_revision) is not int or state["revision"] != expected_revision:
        from .store import RevisionConflict
        raise RevisionConflict(expected_revision, state["revision"])
    scope = _scope(workspace, state, resolve_position(state, position_id))
    record = {**scope, "provider": provider, "model": model, "operation": operation,
              "parameters": _parameters(parameters)}
    record["route_id"] = "route-" + state_digest(record)[:32]
    path, lock = _paths(workspace)
    with open_text_nofollow(lock) as handle, file_lock(handle):
        data = _read(path)
        data["routes"] = [row for row in data["routes"] if (row.get("project_id"), row.get("position_id")) != (project_id, position_id)] + [record]
        write_json(path, data)
    return {key: record[key] for key in record if key != "parameters"}


def selected_route(workspace, state, kind, target):
    spec = action_position(state, kind, target)
    scope = _scope(workspace, state, spec)
    path, _ = _paths(workspace)
    rows = [row for row in _read(path)["routes"] if row.get("project_id") == state["project"]["id"]
            and row.get("position_id") == spec["position_id"]]
    if len(rows) != 1 or any(rows[0].get(key) != value for key, value in scope.items()):
        raise RouteUnavailable("choose a current route in chat")
    record = rows[0]
    content = {key: value for key, value in record.items() if key != "route_id"}
    if record.get("route_id") != "route-" + state_digest(content)[:32] or record.get("provider") not in PROVIDERS:
        raise RouteUnavailable("invalid route record")
    _parameters(record["parameters"])
    return record


def uncertain_position(ledger, state, kind, target):
    position = action_position(state, kind, target)["position_id"]
    for action in ledger.uncertain_actions(state["project"]["id"]):
        if action["action_type"] not in {"generate", "vary", "regenerate"}:
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
            rows.append({key: route[key] for key in ("position_id", "route_id", "provider", "model", "operation", "prompt_version_id", "prompt_sha256")} | {"status": "selected"})
    return {"revision": state["revision"], "routes": rows}

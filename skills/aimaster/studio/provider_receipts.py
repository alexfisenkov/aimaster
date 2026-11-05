"""Private immutable dispatch basis and provider GET receipts, outside creative state."""
import json
import re
import copy

from .operator_adapters import state_digest
from .operator_routes import selected_route
from .provider_download import MAX_BYTES, original_url
from .workspace import resolve_workspace_paths
from .safe_paths import safe_path

MIMES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
         "video/mp4": ".mp4", "video/webm": ".webm", "audio/wav": ".wav", "audio/mpeg": ".mp3"}


def path_for(workspace, action_id, kind):
    if not isinstance(action_id, str) or not re.fullmatch(r"action-[0-9a-f]{32}", action_id):
        raise ValueError("invalid_collection_action")
    if kind not in {"basis", "receipt", "verification", "ack"} and not re.fullmatch(r"locator-\d{3}", kind):
        raise ValueError("invalid_receipt_kind")
    root, _, _, private = resolve_workspace_paths(workspace)
    return safe_path(root, private / "provider-receipts" / (action_id + "." + kind + ".json"))


def read(path):
    if not path.exists():
        return None
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("receipt_size_limit")
    return json.loads(path.read_text(encoding="utf-8"))


def immutable(path, value):
    previous = read(path)
    if previous is not None:
        if previous != value:
            raise ValueError("immutable_provider_receipt_conflict")
        return previous
    from .family_setup.state import write_json
    # Caller holds the shared operation lock. Atomic replace prevents partial
    # receipts after a crash; this boundary never rewrites an existing receipt.
    write_json(path, value)
    return value


def freeze(workspace, runner, action_id, state, route):
    action = runner.ledger.get_action(action_id)
    if action["action_type"] not in {"generate", "vary", "regenerate"} or not action["grant_id"] or \
            runner.ledger.execution_revision(action_id) != state["revision"]:
        raise ValueError("unapproved_provider_action")
    basis = {"schema_version": 1, "action_id": action_id, "project_id": action["project_id"],
             "action_type": action["action_type"], "target_id": action["target_id"],
             "grant_id": action["grant_id"], "expected_revision": action["revision"],
             "execution_revision": state["revision"], "route": route, "state": state,
             "owner_transport": "telegram" if action["idempotency_key"].startswith("telegram") else "owner_local"}
    return immutable(path_for(workspace, action_id, "basis"), basis)


def acknowledge(workspace, runner, action_id, value):
    """The running child may persist an ID before polling, without creative writes."""
    keys = {"provider", "model", "operation", "creation_id", "prompt_sha256", "basis_sha256", "observation"}
    if not isinstance(value, dict) or set(value) != keys or value["observation"] != "acknowledged":
        raise ValueError("invalid_provider_acknowledgement")
    if not isinstance(value["creation_id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", value["creation_id"]):
        raise ValueError("invalid_creation_identity")
    basis = read(path_for(workspace, action_id, "basis"))
    if not basis or any(value[key] != basis["route"][key] for key in ("provider", "model", "operation", "prompt_sha256", "basis_sha256")):
        raise ValueError("acknowledgement_basis_mismatch")
    path = path_for(workspace, action_id, "ack")
    from .platform_compat import file_lock, open_text_nofollow
    with open_text_nofollow(path.with_suffix(".lock")) as handle, file_lock(handle):
        prior = read(path)
        if prior is not None and prior != value:
            raise ValueError("immutable_provider_acknowledgement_conflict")
        action = runner.ledger.acknowledge_provider(action_id, state_digest(basis), value["creation_id"])
        immutable(path, value)
    return {"action_id": action_id, "status": action["status"], "acknowledged": True}


def evidence(value):
    if not isinstance(value, dict) or set(value) != {"provider", "model", "operation", "creation_id", "observation", "artifact", "prompt_sha256", "basis_sha256"}:
        raise ValueError("invalid_provider_evidence")
    if value["observation"] != "completed_get":
        raise ValueError("provider_completion_not_observed")
    for key in ("prompt_sha256", "basis_sha256"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[a-f0-9]{64}", value[key]):
            raise ValueError("invalid_provider_basis")
    for key in ("model", "operation", "creation_id"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", value[key]) or "://" in value[key]:
            raise ValueError("invalid_provider_identity")
    item = value["artifact"]
    keys = {"id", "url", "mime_type", "width", "height", "duration", "size_bytes", "sha256"}
    if not isinstance(item, dict) or not keys <= set(item) <= keys | {"local_path"}:
        raise ValueError("invalid_original_metadata")
    if not isinstance(item["id"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", item["id"]):
        raise ValueError("invalid_original_identity")
    if item.get("local_path") is not None:
        relative = item["local_path"]
        if item["url"] is not None or not isinstance(relative, str) or len(relative) > 512 or not relative.startswith("media/") or \
                "\\" in relative or ".." in relative.split("/") or ":" in relative:
            raise ValueError("invalid_host_original_path")
    else:
        original_url(value["provider"], item["url"])
    if item["mime_type"] not in MIMES:
        raise ValueError("invalid_original_mime")
    if item["mime_type"].startswith("audio/"):
        if item["width"] is not None or item["height"] is not None:
            raise ValueError("invalid_original_dimensions")
    elif any(type(item[key]) is not int or not 1 <= item[key] <= 32768 for key in ("width", "height")):
        raise ValueError("invalid_original_dimensions")
    if item["size_bytes"] is not None and (type(item["size_bytes"]) is not int or not 0 < item["size_bytes"] <= MAX_BYTES):
        raise ValueError("invalid_original_size")
    if item["sha256"] is not None and (not isinstance(item["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])):
        raise ValueError("invalid_original_digest")
    if item["mime_type"].startswith(("video/", "audio/")):
        if type(item["duration"]) not in {int, float} or not 0 < item["duration"] <= 3600:
            raise ValueError("invalid_original_duration")
    elif item["duration"] is not None:
        raise ValueError("invalid_original_duration")
    return json.loads(json.dumps(value, allow_nan=False))


def record(workspace, runner, action_id, value):
    value = evidence(value)
    path = path_for(workspace, action_id, "receipt")
    existing = read(path)
    if existing is not None:
        if existing["provider_evidence"] != value:
            original = existing["provider_evidence"]
            if original["artifact"].get("local_path") or value["artifact"].get("local_path"):
                raise ValueError("immutable_provider_receipt_conflict")
            compared = copy.deepcopy(value)
            compared["artifact"]["url"] = original["artifact"]["url"]
            before = original_url(original["provider"], original["artifact"]["url"])
            after = original_url(value["provider"], value["artifact"]["url"])
            if compared != original or (before.scheme, before.netloc, before.path) != (after.scheme, after.netloc, after.path):
                raise ValueError("immutable_provider_receipt_conflict")
            # Only a fresh signature for the very same object; creation/model/
            # input basis/declared metadata remain immutable. No URL in events.
            for index in range(1, 33):
                locator = path_for(workspace, action_id, f"locator-{index:03}")
                prior = read(locator)
                next_value = {"receipt_sha256": state_digest(existing), "url": value["artifact"]["url"]}
                if prior == next_value:
                    break
                if prior is None:
                    immutable(locator, next_value)
                    break
            else:
                raise ValueError("locator_renewal_limit")
        return existing
    action = runner.ledger.get_action(action_id)
    if action["external_id"] is not None and action["external_id"] != value["creation_id"]:
        raise ValueError("provider_creation_differs_from_acknowledgement")
    ack = read(path_for(workspace, action_id, "ack"))
    if ack and value["creation_id"] != ack["creation_id"]:
        raise ValueError("provider_creation_differs_from_acknowledgement")
    if action["status"] not in {"running", "outcome_unknown", "needs_chat_setup"} or not action["worker_id"]:
        raise ValueError("provider_action_not_dispatched")
    basis = read(path_for(workspace, action_id, "basis"))
    if basis is None:
        # Legacy recovery imports a GET receipt only while the exact persisted
        # route and unchanged execution revision can still bind it unambiguously.
        state = runner.store.load(action["project_id"])
        route = selected_route(workspace, state, action["action_type"], action["target_id"], frozen_collection=True)
        if action["payload"].get("spending") != {"confirmed": True, **{key: route[key] for key in ("route_id", "provider", "model")}}:
            raise ValueError("legacy_dispatch_route_is_unproven")
        basis = freeze(workspace, runner, action_id, state, route)
    if any(value[key] != basis["route"][key] for key in ("provider", "model", "operation", "prompt_sha256", "basis_sha256")):
        raise ValueError("provider_receipt_route_mismatch")
    local = value["artifact"].get("local_path") is not None
    if local != (basis["route"].get("collection_mode", "provider-original") == "host-local-original"):
        raise ValueError("provider_collection_mode_mismatch")
    receipt = {"schema_version": 1, "basis_sha256": state_digest(basis), "provider_evidence": value}
    return immutable(path, receipt)


def current_artifact(workspace, action_id, receipt):
    artifact = copy.deepcopy(receipt["provider_evidence"]["artifact"])
    if artifact.get("local_path"):
        return artifact
    original = original_url(receipt["provider_evidence"]["provider"], artifact["url"])
    for index in range(1, 33):
        locator = read(path_for(workspace, action_id, f"locator-{index:03}"))
        if locator is None:
            break
        parsed = original_url(receipt["provider_evidence"]["provider"], locator["url"])
        if locator["receipt_sha256"] != state_digest(receipt) or \
                (parsed.scheme, parsed.netloc, parsed.path) != (original.scheme, original.netloc, original.path):
            raise ValueError("invalid_original_renewal")
        artifact["url"] = locator["url"]
    return artifact

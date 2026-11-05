"""Reconcile an approved original into existing AssetIndex/authoring boundaries."""
from contextlib import nullcontext
import hashlib
from pathlib import Path

from . import authoring
from .assets import _inspect_media
from .domain_positions import current_member, resolve_position
from .family_setup import operation_lease
from .family_setup.state import write_bytes
from .operator_adapters import state_digest
from .operator_routes import selected_route
from . import provider_receipts as receipts
from .provider_download import MAX_BYTES, fetch_original
from .store import RevisionConflict
from .montage import MontageError
from .workspace import resolve_workspace_paths


def public(runner, action_id):
    action = runner.ledger.get_action(action_id)
    return {"action_id": action_id, "status": action["status"], "collection": runner.ledger.collection(action_id)}


def record(workspace, runner, action_id, evidence, *, state_dir=None, operation_locked=False):
    with nullcontext() if operation_locked else operation_lease(state_dir, "provider-receipt"):
        receipt = receipts.record(workspace, runner, action_id, evidence)
        runner.ledger.reconcile_collection(action_id, state_digest(receipt), evidence["creation_id"], "received")
        return public(runner, action_id)


def _basis_matches(workspace, basis, state):
    route = selected_route(workspace, state, basis["action_type"], basis["target_id"], frozen_collection=True)
    if route != basis["route"]:
        raise ValueError("collection_basis_conflict")
    return resolve_position(state, route["position_id"])


def _validated_bytes(data, artifact):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES or \
            artifact["size_bytes"] is not None and len(data) != artifact["size_bytes"]:
        raise ValueError("original_size_mismatch")
    if artifact["sha256"] and hashlib.sha256(data).hexdigest() != artifact["sha256"]:
        raise ValueError("original_digest_mismatch")
    mime, width, height = _inspect_media(data)
    if mime != artifact["mime_type"] or mime.startswith("image/") and (width, height) != (artifact["width"], artifact["height"]):
        raise ValueError("original_metadata_mismatch")
    return data


class _GuardedStore:
    """Run the collection basis check inside the authoring transaction lock."""
    def __init__(self, store, workspace, basis):
        self.store, self.workspace, self.basis = store, workspace, basis

    def transact(self, project_id, expected_revision, mutation):
        def guarded(state):
            _basis_matches(self.workspace, self.basis, state)
            if state_digest(state) != state_digest(self.basis["state"]):
                raise ValueError("collection_state_conflict")
            mutation(state)
        return self.store.transact(project_id, expected_revision, guarded)


def reconcile(workspace, runner, action_id, *, original_file=None, state_dir=None, operation_locked=False):
    with nullcontext() if operation_locked else operation_lease(state_dir, "provider-collection"):
        receipt = receipts.read(receipts.path_for(workspace, action_id, "receipt"))
        basis = receipts.read(receipts.path_for(workspace, action_id, "basis"))
        if not receipt or not basis or receipt["basis_sha256"] != state_digest(basis):
            raise ValueError("missing_or_changed_provider_receipt")
        evidence = receipts.evidence(receipt["provider_evidence"])
        artifact = receipts.current_artifact(workspace, action_id, receipt)
        def phase(value):
            runner.ledger.reconcile_collection(action_id, state_digest(receipt), evidence["creation_id"], value)
            return public(runner, action_id)
        root, _, media, _ = resolve_workspace_paths(workspace)
        destination = receipts.safe_path(root, media / "provider-originals" / (action_id + receipts.MIMES[artifact["mime_type"]]))
        verified_path = receipts.path_for(workspace, action_id, "verification")
        verified = receipts.read(verified_path)
        try:
            if destination.exists() and (verified or artifact["sha256"]):
                if destination.stat().st_size > MAX_BYTES:
                    raise ValueError("original_size_limit")
                data = _validated_bytes(destination.read_bytes(), artifact)
            elif original_file is not None or artifact.get("local_path"):
                source = Path(original_file).absolute() if original_file is not None else receipts.safe_path(root, root / artifact["local_path"])
                receipts.safe_path(Path(source.anchor), source)
                if original_file is not None and not artifact["sha256"] or not source.is_file() or source.stat().st_size > MAX_BYTES:
                    raise ValueError("unverified_saved_original")
                data = _validated_bytes(source.read_bytes(), artifact)
            else:
                data = _validated_bytes(fetch_original(evidence["provider"], artifact), artifact)
            computed = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
                        "mime_type": artifact["mime_type"]}
            if verified and verified != computed:
                raise ValueError("collected_original_changed")
            # Persist computed integrity separately from provider-declared facts,
            # before the atomic media write. A crash can repeat GET, never spend.
            receipts.immutable(verified_path, computed)
            if not destination.exists():
                receipts.safe_path(root, destination)
                write_bytes(destination, data)
            elif hashlib.sha256(destination.read_bytes()).hexdigest() != computed["sha256"]:
                raise ValueError("collected_original_changed")
            if artifact["mime_type"].startswith(("video/", "audio/")):
                from .montage.probe import probe_media
                observed = probe_media(destination)
                if (observed.width, observed.height) != (artifact["width"], artifact["height"]) or \
                        abs(observed.duration - artifact["duration"]) > .05:
                    raise ValueError("original_metadata_mismatch")
        except (ValueError, OSError, MontageError):
            phase("blocked")
            raise ValueError("original_collection_blocked") from None
        # Registration is deterministic by generated path+digest, including a
        # crash after register but before authoring. The existing API owns roles.
        assets = authoring.open_assets(workspace)
        asset = assets.register(destination.relative_to(root).as_posix(), "result")
        state = runner.store.load(basis["project_id"])
        try:
            spec = _basis_matches(workspace, basis, state)
            current = current_member(state, spec, "result", missing_ok=True)
            old_ids = {item["version_id"] for item in basis["state"].get(spec["result_collection"], [])}
            if current and current.get("asset_id") == asset["asset_id"] and current["version_id"] not in old_ids:
                # Crash after canonical authoring, before the ledger resolution.
                assets.resolve(current["asset_id"])
                return phase("succeeded")
            if state["revision"] != basis["execution_revision"] or state_digest(state) != state_digest(basis["state"]):
                return phase("conflict")
            authoring.add_result_version(_GuardedStore(runner.store, workspace, basis), assets,
                basis["project_id"], basis["execution_revision"], target=basis["route"]["position_id"], asset_id=asset["asset_id"])
            after = runner.store.load(basis["project_id"])
            result = current_member(after, resolve_position(after, spec["position_id"]), "result")
            if not result or result["asset_id"] != asset["asset_id"]:
                raise ValueError("collection_readback_failed")
        except (ValueError, RevisionConflict):
            return phase("conflict")
        return phase("succeeded")

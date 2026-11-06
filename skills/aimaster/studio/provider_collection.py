"""Reconcile an approved original into existing AssetIndex/authoring boundaries."""
from contextlib import nullcontext
import hashlib
import copy
import json
import tempfile
import subprocess
import re
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


def _completed_metadata(value, *, image=False):
    """Read the observed Magnific MCP text envelope, without interpreting preview URLs."""
    if not isinstance(value, dict) or "content" not in value:
        return value
    if value.get("isError"):
        raise ValueError("invalid_provider_metadata")
    blocks = value.get("content")
    if not isinstance(blocks, list) or len(blocks) != 1 or not isinstance(blocks[0], dict) or \
            blocks[0].get("type") != "text" or not isinstance(blocks[0].get("text"), str):
        raise ValueError("invalid_provider_metadata")
    text = blocks[0]["text"]
    if len(text) > 65536:
        raise ValueError("invalid_provider_metadata")
    top, originals, item, in_collection, proxy = {}, [], None, False, None
    def scalar(raw):
        raw = raw.strip()
        if raw.startswith('"'):
            try:
                result = json.loads(raw)
            except ValueError:
                raise ValueError("invalid_provider_metadata") from None
            if not isinstance(result, str):
                raise ValueError("invalid_provider_metadata")
            return result
        return raw
    for line in text.splitlines():
        flag = re.match(r"^  isPreviewProxy:\s*(true|false)\s*$", line)
        if flag:
            if proxy is not None:
                raise ValueError("invalid_provider_metadata")
            proxy = flag.group(1) == "true"
        match = re.match(r"^([A-Za-z][A-Za-z0-9]*):\s*(.*)$", line)
        if match:
            in_collection = False
            key, raw = match.groups()
            if key in {"identifier", "status", "downloadUrl", "tool", "url"}:
                if key in top:
                    raise ValueError("invalid_provider_metadata")
                top[key] = scalar(raw)
            continue
        if re.match(r"^  mediaCollection\[\d+\]:\s*$", line):
            in_collection = True
            continue
        if in_collection:
            match = re.match(r"^    - ([A-Za-z][A-Za-z0-9]*):\s*(.*)$", line)
            if match:
                if item and item.get("type") == "original":
                    originals.append(item)
                item = {match.group(1): scalar(match.group(2))}
                continue
            match = re.match(r"^      ([A-Za-z][A-Za-z0-9]*):\s*(.*)$", line)
            if match and item is not None:
                key = match.group(1)
                if key in item:
                    raise ValueError("invalid_provider_metadata")
                item[key] = scalar(match.group(2))
            elif line and not line.startswith("      "):
                if item and item.get("type") == "original":
                    originals.append(item)
                item, in_collection = None, False
    if item and item.get("type") == "original":
        originals.append(item)
    if len(originals) > 1:
        raise ValueError("provider_original_disagrees")
    if originals and top.get("downloadUrl"):
        master = receipts.original_url("magnific", top["downloadUrl"])
        original = receipts.original_url("magnific", originals[0].get("url"))
        if (master.scheme, master.netloc, master.path) != (original.scheme, original.netloc, original.path):
            raise ValueError("provider_original_disagrees")
    url = top.get("downloadUrl")
    if image and originals and not url:
        url = originals[0].get("url")
    if image and top.get("tool") == "text-to-image" and not url and proxy is not True:
        url = top.get("url")
    if image and top.get("tool") != "text-to-image":
        url = None
    return {"creation_id": top.get("identifier"), "status": top.get("status"), "downloadUrl": url}


def collect_completed(workspace, runner, action_id, metadata, *, state_dir=None, correction_reason=None, operation_locked=False):
    """Collect a completed Magnific GET, deriving facts from downloaded bytes.

    The input is private provider metadata, never a dispatch request. A receipt
    already saved before interruption is resumed without another provider call.
    """
    with nullcontext() if operation_locked else operation_lease(state_dir, "provider-collection"):
        existing = receipts.read(receipts.path_for(workspace, action_id, "receipt"))
        basis = receipts.read(receipts.path_for(workspace, action_id, "basis"))
        if not basis or basis["route"]["provider"] != "magnific":
            raise ValueError("unsupported_completed_provider")
        position = resolve_position(basis["state"], basis["route"]["position_id"])
        metadata = _completed_metadata(metadata, image=position["result_collection"] == "image_results")
        if not isinstance(metadata, dict) or str(metadata.get("status", "")).lower() not in {"completed", "succeeded", "success"}:
            raise ValueError("provider_completion_not_observed")
        creation = metadata.get("creation_id") or metadata.get("id")
        collection = metadata.get("mediaCollection")
        original = collection.get("original") if isinstance(collection, dict) else None
        if isinstance(original, dict):
            url = original.get("downloadUrl") or original.get("url")
            artifact_id = original.get("id") or creation
        elif isinstance(original, str):
            url, artifact_id = original, creation
        else:
            url = metadata.get("downloadUrl")
            artifact_id = creation
        if not url:
            raise ValueError("missing_provider_original")
        action = runner.ledger.get_action(action_id)
        ack = receipts.read(receipts.path_for(workspace, action_id, "ack"))
        known = action.get("external_id") or (ack and ack.get("creation_id"))
        if not known or creation != known:
            raise ValueError("provider_creation_differs_from_acknowledgement")
        if existing and correction_reason is None:
            active = runner.ledger.collection_evidence(action_id)
            correction = receipts.read(receipts.path_for(workspace, action_id, "correction"))
            if not active or active["phase"] not in {"succeeded", "resolved_adopt", "resolved_keep"}:
                if correction and active and active["receipt_sha256"] == state_digest(correction):
                    receipts.renew_correction(workspace, action_id, correction, url)
                elif not existing["provider_evidence"]["artifact"].get("local_path"):
                    renewal = copy.deepcopy(existing["provider_evidence"])
                    renewal["artifact"]["url"] = url
                    receipts.record(workspace, runner, action_id, renewal)
            return reconcile(workspace, runner, action_id, state_dir=state_dir, operation_locked=True)
        if correction_reason is not None and (not existing or not isinstance(correction_reason, str) or
                not re.fullmatch(r"[a-z][a-z0-9_]{2,63}", correction_reason)):
            raise ValueError("invalid_correction_reason")
        prior_correction = receipts.read(receipts.path_for(workspace, action_id, "correction"))
        if correction_reason is not None and prior_correction is not None:
            prior_evidence = prior_correction.get("provider_evidence", {})
            if (prior_correction.get("supersedes_sha256") != state_digest(existing) or
                    prior_correction.get("reason") != correction_reason.strip() or
                    prior_evidence.get("creation_id") != creation):
                raise ValueError("immutable_provider_correction_conflict")
            receipts.renew_correction(workspace, action_id, prior_correction, url)
            runner.ledger.correct_collection_receipt(action_id, state_digest(existing),
                state_digest(prior_correction), creation, correction_reason.strip())
            return reconcile(workspace, runner, action_id, state_dir=state_dir, operation_locked=True)
        data = fetch_original("magnific", {"url": url, "mime_type": None, "size_bytes": None})
        mime, width, height = _inspect_media(data)
        if mime not in receipts.MIMES:
            raise ValueError("invalid_original_mime")
        expected_prefix = {"image_results": "image/", "video_results": "video/", "audio_results": "audio/"}[position["result_collection"]]
        if not mime.startswith(expected_prefix):
            raise ValueError("original_media_kind_mismatch")
        root, _, _, private = resolve_workspace_paths(workspace)
        with tempfile.TemporaryDirectory(prefix="original-", dir=private) as temporary:
            source = Path(temporary) / ("original" + receipts.MIMES[mime])
            source.write_bytes(data)
            duration = None
            if mime.startswith(("video/", "audio/")):
                from .montage.probe import probe_media
                observed = probe_media(source)
                width, height, duration = observed.width, observed.height, observed.duration
                if mime.startswith("video/") and not observed.has_video:
                    raise ValueError("original_missing_video")
            route = basis["route"]
            evidence = {key: route[key] for key in ("provider", "model", "operation", "prompt_sha256", "basis_sha256")}
            evidence.update(creation_id=creation, observation="completed_get", artifact={
                "id": artifact_id, "url": url, "mime_type": mime, "width": width, "height": height,
                "duration": duration, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            if correction_reason is None:
                record(workspace, runner, action_id, evidence, state_dir=state_dir, operation_locked=True)
            else:
                corrected = {"schema_version": 1, "basis_sha256": state_digest(basis),
                    "provider_evidence": receipts.evidence(evidence),
                    "supersedes_sha256": state_digest(existing), "reason": correction_reason.strip()}
                receipts.immutable(receipts.path_for(workspace, action_id, "correction"), corrected)
                runner.ledger.correct_collection_receipt(action_id, state_digest(existing),
                    state_digest(corrected), creation, correction_reason.strip())
            return reconcile(workspace, runner, action_id, original_file=source, state_dir=state_dir, operation_locked=True)


def public(runner, action_id):
    action = runner.ledger.get_action(action_id)
    return {"action_id": action_id, "status": action["status"], "collection": runner.ledger.collection(action_id)}


def _verified_export(workspace, action_id, active):
    root, _, media, _ = resolve_workspace_paths(workspace)
    basis_path = receipts.path_for(workspace, action_id, "basis")
    receipt = receipts.read(receipts.safe_path(root, basis_path.parent / (action_id + ".provider-export.json")))
    if not receipt or not active or active["receipt_sha256"] != state_digest(receipt):
        return None
    basis = receipts.read(basis_path)
    proof = receipt.get("representation", {})
    path = receipts.safe_path(root, media / "provider-exports" / (action_id + ".mp4"))
    if not basis or receipt.get("basis_sha256") != state_digest(basis) or proof.get("kind") != "provider_export" or \
            not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("invalid_provider_export")
    data = path.read_bytes()
    if len(data) != proof.get("size_bytes") or hashlib.sha256(data).hexdigest() != proof.get("sha256") or _inspect_media(data)[0] != "video/mp4":
        raise ValueError("invalid_provider_export")
    return receipt, path


def recovered_preview(workspace, runner, action_id):
    """Expose only the verified local result asset, never its private source locator."""
    original_receipt = receipts.read(receipts.path_for(workspace, action_id, "receipt"))
    correction = receipts.read(receipts.path_for(workspace, action_id, "correction"))
    active = runner.ledger.collection_evidence(action_id)
    exported = _verified_export(workspace, action_id, active)
    if exported and active["phase"] == "conflict":
        _, path = exported
        root, _, _, _ = resolve_workspace_paths(workspace)
        digest = hashlib.sha256(path.read_bytes()).digest()
        asset_id = "asset-" + hashlib.sha256(path.relative_to(root).as_posix().encode("utf-8") + b"\0" + digest).hexdigest()[:32]
        resolved, mime = authoring.open_assets(workspace).resolve(asset_id)
        return {"url": "/assets/" + asset_id, "mime_type": mime, "representation": "provider_export"} if resolved == path else None
    corrected = bool(correction and original_receipt and correction.get("supersedes_sha256") == state_digest(original_receipt) and active and active["receipt_sha256"] == state_digest(correction))
    receipt = correction if corrected else original_receipt
    if not receipt or not active or active["phase"] != "conflict" or active["receipt_sha256"] != state_digest(receipt):
        return None
    artifact = receipts.evidence(receipt["provider_evidence"])["artifact"]
    root, _, media, _ = resolve_workspace_paths(workspace)
    original = receipts.safe_path(root, media / "provider-originals" / (action_id + ("-corrected" if corrected else "") + receipts.MIMES[artifact["mime_type"]]))
    verification = receipts.read(receipts.path_for(workspace, action_id, "correction-verification" if corrected else "verification"))
    if not verification or not original.is_file() or original.stat().st_size > MAX_BYTES:
        return None
    data = _validated_bytes(original.read_bytes(), artifact)
    if verification != {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "mime_type": artifact["mime_type"]}:
        return None
    path = original
    if artifact["mime_type"] == "video/quicktime":
        path = receipts.safe_path(root, media / "provider-derived" / (action_id + ("-corrected" if corrected else "") + ".mp4"))
        proof = receipts.read(receipts.path_for(workspace, action_id, "correction-derivative" if corrected else "derivative"))
        if not proof or proof.get("original_sha256") != verification["sha256"] or not path.is_file() or path.stat().st_size > MAX_BYTES or hashlib.sha256(path.read_bytes()).hexdigest() != proof.get("sha256"):
            return None
    relative = path.relative_to(root).as_posix()
    digest = hashlib.sha256(path.read_bytes()).digest()
    asset_id = "asset-" + hashlib.sha256(relative.encode("utf-8") + b"\0" + digest).hexdigest()[:32]
    resolved, mime = authoring.open_assets(workspace).resolve(asset_id)
    return {"url": "/assets/" + asset_id, "mime_type": mime} if resolved == path else None


def adoption_already_applied(workspace, runner, action_id, state):
    """Expose a resumable transaction only when its unique marker exists."""
    active = runner.ledger.collection_evidence(action_id)
    basis = receipts.read(receipts.path_for(workspace, action_id, "basis"))
    intent = receipts.read(receipts.path_for(workspace, action_id, "resolution"))
    if not active or active["phase"] != "conflict" or not basis or not intent:
        return False
    for number in range(1, 33):
        candidate = receipts.read(receipts.path_for(workspace, action_id, f"resolution-{number:03}"))
        if candidate is None:
            break
        if candidate.get("supersedes_sha256") != state_digest(intent):
            return False
        intent = candidate
    if intent.get("choice") != "adopt" or intent.get("action_id") != action_id or intent.get("receipt_sha256") != active["receipt_sha256"]:
        return False
    spec = resolve_position(state, basis["route"]["position_id"])
    marker = "recovery-" + state_digest(intent)
    matches = [item for item in state.get(spec["result_collection"], []) if item.get("recovery_operation_id") == marker]
    return len(matches) == 1 and matches[0].get("asset_id") == intent.get("asset_id") and matches[0].get("version_id") not in intent.get("prior_version_ids", [])


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


def _compatible_video(workspace, root, media, action_id, original, observed, *, correction=False):
    """Retain MOV verbatim; use a separately labelled H.264 derivative in Studio."""
    from .platform_compat import find_program
    from .montage.probe import probe_media
    destination = receipts.safe_path(root, media / "provider-derived" / (action_id + ("-corrected" if correction else "") + ".mp4"))
    proof_path = receipts.path_for(workspace, action_id, "correction-derivative" if correction else "derivative")
    proof = receipts.read(proof_path)
    original_sha = hashlib.sha256(original.read_bytes()).hexdigest()
    if destination.exists():
        if not proof or proof.get("original_sha256") != original_sha or destination.stat().st_size > MAX_BYTES or \
                hashlib.sha256(destination.read_bytes()).hexdigest() != proof.get("sha256"):
            raise ValueError("compatible_video_changed")
        info = probe_media(destination)
        if not info.has_video or abs(info.duration - observed.duration) > .1:
            raise ValueError("invalid_compatible_video")
        return destination
    ffmpeg = find_program("ffmpeg")
    if not ffmpeg:
        raise ValueError("compatible_video_requires_ffmpeg")
    with tempfile.TemporaryDirectory(prefix="aimaster-convert-") as temporary:
        output = Path(temporary) / "compatible.mp4"
        try:
            proc = subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", str(original),
                "-map", "0:v:0", "-map", "0:a?", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
                str(output)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=600)
        except (OSError, subprocess.SubprocessError):
            raise ValueError("compatible_video_failed") from None
        if proc.returncode or not output.is_file() or output.stat().st_size > MAX_BYTES:
            raise ValueError("compatible_video_failed")
        info = probe_media(output)
        data = output.read_bytes()
        if not info.has_video or abs(info.duration - observed.duration) > .1 or _inspect_media(data)[0] != "video/mp4":
            raise ValueError("invalid_compatible_video")
        receipts.immutable(proof_path, {"original_sha256": original_sha, "sha256": hashlib.sha256(data).hexdigest(),
                                      "kind": "h264_mp4_derivative"})
        write_bytes(destination, data)
    return destination


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


class _ResolutionStore:
    """Keep the frozen position and prompt/reference route under the state lock."""
    def __init__(self, store, workspace, basis, intent_path, intent):
        self.store, self.workspace, self.basis = store, workspace, basis
        self.intent_path, self.intent = intent_path, intent

    def transact(self, project_id, expected_revision, mutation):
        def guarded(state):
            _basis_matches(self.workspace, self.basis, state)
            mutation(state)
            spec = resolve_position(state, self.basis["route"]["position_id"])
            result = current_member(state, spec, "result")
            if not result or result.get("asset_id") != self.intent["asset_id"] or result.get("version_id") in self.intent["prior_version_ids"]:
                raise ValueError("collection_resolution_marker_conflict")
            result["recovery_operation_id"] = "recovery-" + state_digest(self.intent)
            receipts.immutable(self.intent_path, self.intent)
        return self.store.transact(project_id, expected_revision, guarded)


def reconcile(workspace, runner, action_id, *, original_file=None, state_dir=None, operation_locked=False):
    with nullcontext() if operation_locked else operation_lease(state_dir, "provider-collection"):
        receipt = receipts.read(receipts.path_for(workspace, action_id, "receipt"))
        correction = receipts.read(receipts.path_for(workspace, action_id, "correction"))
        active = runner.ledger.collection_evidence(action_id)
        corrected = bool(correction and active and active["receipt_sha256"] == state_digest(correction))
        if active and active["phase"] in {"succeeded", "resolved_adopt", "resolved_keep"} and \
                ((corrected and correction.get("supersedes_sha256") == state_digest(receipt)) or
                 (not corrected and receipt and active["receipt_sha256"] == state_digest(receipt))):
            return public(runner, action_id)
        if corrected:
            if not receipt or correction.get("supersedes_sha256") != state_digest(receipt):
                raise ValueError("invalid_provider_correction")
            receipt = correction
        basis = receipts.read(receipts.path_for(workspace, action_id, "basis"))
        if not receipt or not basis or receipt["basis_sha256"] != state_digest(basis):
            raise ValueError("missing_or_changed_provider_receipt")
        evidence = receipts.evidence(receipt["provider_evidence"])
        artifact = receipts.current_artifact(workspace, action_id, receipt, correction=corrected)
        def phase(value):
            runner.ledger.reconcile_collection(action_id, state_digest(receipt), evidence["creation_id"], value)
            return public(runner, action_id)
        root, _, media, _ = resolve_workspace_paths(workspace)
        destination = receipts.safe_path(root, media / "provider-originals" / (action_id + ("-corrected" if corrected else "") + receipts.MIMES[artifact["mime_type"]]))
        verified_path = receipts.path_for(workspace, action_id, "correction-verification" if corrected else "verification")
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
        if artifact["mime_type"] == "video/quicktime":
            try:
                destination = _compatible_video(workspace, root, media, action_id, destination, observed, correction=corrected)
            except (ValueError, OSError, MontageError):
                phase("blocked")
                raise ValueError("compatible_video_blocked") from None
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


def resolve_conflict(workspace, runner, action_id, choice, expected_revision, *, state_dir=None):
    """Explicitly adopt a recovered result or retain current, with crash-safe CAS."""
    if choice not in {"adopt", "keep"} or type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("invalid_collection_resolution")
    with operation_lease(state_dir, "provider-resolution"):
        original_receipt = receipts.read(receipts.path_for(workspace, action_id, "receipt"))
        correction = receipts.read(receipts.path_for(workspace, action_id, "correction"))
        basis = receipts.read(receipts.path_for(workspace, action_id, "basis"))
        active = runner.ledger.collection_evidence(action_id)
        exported = _verified_export(workspace, action_id, active)
        corrected = bool(correction and original_receipt and active and correction.get("supersedes_sha256") == state_digest(original_receipt) and active["receipt_sha256"] == state_digest(correction))
        receipt = exported[0] if exported else (correction if corrected else original_receipt)
        if not receipt or not basis or not active or receipt.get("basis_sha256") != state_digest(basis) or \
                active["receipt_sha256"] != state_digest(receipt) or active["phase"] not in {"conflict", "resolved_adopt", "resolved_keep"}:
            raise ValueError("no_verified_collection_conflict")
        root, _, media, _ = resolve_workspace_paths(workspace)
        if exported:
            result_path = exported[1]
        else:
            artifact = receipts.evidence(receipt["provider_evidence"])["artifact"]
            original = receipts.safe_path(root, media / "provider-originals" / (action_id + ("-corrected" if corrected else "") + receipts.MIMES[artifact["mime_type"]]))
            verified = receipts.read(receipts.path_for(workspace, action_id, "correction-verification" if corrected else "verification"))
            if not verified or not original.is_file() or original.stat().st_size > MAX_BYTES:
                raise ValueError("missing_verified_original")
            data = _validated_bytes(original.read_bytes(), artifact)
            if verified != {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "mime_type": artifact["mime_type"]}:
                raise ValueError("collected_original_changed")
            result_path = original
            if artifact["mime_type"] == "video/quicktime":
                from .montage.probe import probe_media
                result_path = _compatible_video(workspace, root, media, action_id, original, probe_media(original), correction=corrected)
        assets = authoring.open_assets(workspace)
        asset = assets.register(result_path.relative_to(root).as_posix(), "result")
        state = runner.store.load(basis["project_id"])
        spec = resolve_position(state, basis["route"]["position_id"])
        current = current_member(state, spec, "result", missing_ok=True)
        intent_path = receipts.path_for(workspace, action_id, "resolution")
        intent = receipts.read(intent_path)
        next_path = None
        if intent is not None:
            for number in range(1, 33):
                candidate_path = receipts.path_for(workspace, action_id, f"resolution-{number:03}")
                candidate = receipts.read(candidate_path)
                if candidate is None:
                    next_path = candidate_path
                    break
                if candidate.get("supersedes_sha256") != state_digest(intent):
                    raise ValueError("invalid_collection_resolution_history")
                intent_path, intent = candidate_path, candidate
        # The project write and the ledger write are separate transactions.
        # Complete an already-applied adoption by its unique state marker, even
        # after unrelated edits or a later selection, without selecting it again.
        if intent is not None and intent.get("choice") == "adopt" and choice == "adopt" and active["phase"] == "conflict":
            from .store import _thread_lock, file_lock
            project_path = runner.store.project_dir(basis["project_id"])
            with _thread_lock(project_path):
                with runner.store._open_lock(basis["project_id"], project_path / ".state.lock") as handle, file_lock(handle):
                    latest = runner.store._read(project_path)
                    if expected_revision not in {intent.get("revision"), latest.get("revision")}:
                        raise ValueError("collection_resolution_conflict")
                    marker = "recovery-" + state_digest(intent)
                    matches = [item for item in latest.get(spec["result_collection"], [])
                               if item.get("recovery_operation_id") == marker]
                    if matches:
                        if len(matches) != 1 or matches[0].get("asset_id") != intent.get("asset_id") or \
                                matches[0].get("version_id") in intent.get("prior_version_ids", []) or \
                                intent.get("receipt_sha256") != state_digest(receipt) or intent.get("action_id") != action_id:
                            raise ValueError("collection_resolution_marker_conflict")
                        runner.ledger.resolve_collection_choice(action_id, state_digest(receipt), "adopt")
                        return public(runner, action_id)
        expected = {"receipt_sha256": state_digest(receipt), "choice": choice,
                    "revision": expected_revision, "asset_id": asset["asset_id"]}
        supersedes = None
        if intent is not None and any(intent.get(key) != value for key, value in expected.items()):
            # A durable intent may precede a crash before the state/ledger write.
            # Supersede only if the original owner link is unchanged and no new
            # version for this asset appeared since that intent was prepared.
            prior_ids = intent.get("prior_version_ids")
            current_id = current["version_id"] if current else None
            if (active["phase"] != "conflict" or not next_path or not isinstance(prior_ids, list) or
                    intent.get("receipt_sha256") != state_digest(receipt) or
                    intent.get("asset_id") != asset["asset_id"] or
                    (current_id != intent.get("prior_version_id") and not (intent.get("choice") == "keep" and choice == "keep")) or state["revision"] != expected_revision or
                    (intent.get("choice") == "adopt" and any(item.get("asset_id") == asset["asset_id"] and item.get("version_id") not in prior_ids
                        for item in state.get(spec["result_collection"], [])))):
                raise ValueError("collection_resolution_conflict")
            supersedes, intent_path, intent = state_digest(intent), next_path, None
        if intent is None:
            if active["phase"] != "conflict" or state["revision"] != expected_revision or (choice == "keep" and not current):
                raise ValueError("collection_resolution_conflict")
            if choice == "adopt":
                _basis_matches(workspace, basis, state)
                from .authoring_support import require_stage_not_approved
                from .decision_cards import STAGE_COLLECTIONS
                require_stage_not_approved(state, STAGE_COLLECTIONS[spec["result_collection"]][0], "result add-version")
            intent = {"receipt_sha256": state_digest(receipt), "choice": choice,
                      "revision": expected_revision, "asset_id": asset["asset_id"],
                      "action_id": action_id,
                      "prior_version_id": current["version_id"] if current else None,
                      "prior_version_ids": [item["version_id"] for item in state.get(spec["result_collection"], [])]}
            if supersedes:
                intent["supersedes_sha256"] = supersedes
        if active["phase"] == "resolved_" + choice:
            return public(runner, action_id)
        if active["phase"] != "conflict":
            raise ValueError("collection_resolution_conflict")
        if choice == "adopt":
            if state["revision"] != expected_revision or (current["version_id"] if current else None) != intent["prior_version_id"]:
                raise ValueError("collection_resolution_conflict")
            authoring.add_result_version(_ResolutionStore(runner.store, workspace, basis, intent_path, intent), assets, basis["project_id"], expected_revision,
                target=spec["position_id"], asset_id=asset["asset_id"],
                caption="Выгрузка сервиса · оригинал не подтверждён" if exported else None)
            state = runner.store.load(basis["project_id"])
            current = current_member(state, resolve_position(state, spec["position_id"]), "result")
            if not current or current["asset_id"] != asset["asset_id"]:
                raise ValueError("collection_readback_failed")
        else:
            # Keep makes no creative-state write. Hold the same project lock
            # as transact while checking revision/current and committing ledger.
            from .store import _thread_lock, file_lock
            project_path = runner.store.project_dir(basis["project_id"])
            with _thread_lock(project_path):
                with runner.store._open_lock(basis["project_id"], project_path / ".state.lock") as handle, file_lock(handle):
                    latest = runner.store._read(project_path)
                    latest_spec = resolve_position(latest, basis["route"]["position_id"])
                    latest_current = current_member(latest, latest_spec, "result", missing_ok=True)
                    if latest["revision"] != expected_revision or not latest_current or latest_current["version_id"] != intent["prior_version_id"]:
                        raise ValueError("collection_resolution_conflict")
                    receipts.immutable(intent_path, intent)
                    runner.ledger.resolve_collection_choice(action_id, state_digest(receipt), choice)
            return public(runner, action_id)
        runner.ledger.resolve_collection_choice(action_id, state_digest(receipt), choice)
        return public(runner, action_id)

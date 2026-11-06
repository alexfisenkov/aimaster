"""Verify a Magnific project export as an explicitly labelled representation.

MCP envelopes are operator-supplied observations, not cryptographic attestations.
The export and creation URLs are independently downloaded from pinned origins;
only exact bytes and metadata are compared. No provider dispatch occurs here.
"""
import hashlib
import http.client
import io
import json
import math
import re
import socket
import ssl
import subprocess
import tempfile
import zipfile
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import urlsplit

from .platform_compat import find_program
from .provider_download import MAX_BYTES, _addresses, _deadline, fetch_original


def _text(value):
    if not isinstance(value, dict) or value.get("isError") or not isinstance(value.get("content"), list) or len(value["content"]) != 1:
        raise ValueError("invalid_provider_export_observation")
    block = value["content"][0]
    if not isinstance(block, dict) or block.get("type") != "text" or not isinstance(block.get("text"), str):
        raise ValueError("invalid_provider_export_observation")
    return block["text"]


def _field(text, name, indent=""):
    rows = re.findall(r"^" + re.escape(indent + name) + r":\s*(.+)$", text, re.M)
    if len(rows) != 1:
        raise ValueError("invalid_provider_export_observation")
    value = rows[0].strip()
    return json.loads(value) if value.startswith('"') else value


def _zip_bytes(url, job_id):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "pikaso.cdnpk.net" or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment
            or not re.fullmatch(r"/tmp/bulk-downloads/" + re.escape(job_id) + r"/[A-Za-z0-9._-]+\.zip", parsed.path)
            or not parsed.query):
        raise ValueError("invalid_provider_export_url")
    rows = _addresses(parsed.hostname, 5)
    family, kind, protocol, _, address = rows[0]
    try:
        with socket.socket(family, kind, protocol) as raw:
            raw.settimeout(30)
            raw.connect(address)
            with ssl.create_default_context().wrap_socket(raw, server_hostname=parsed.hostname) as conn, _deadline(conn, 30):
                conn.settimeout(30)
                path = parsed.path + "?" + parsed.query
                conn.sendall(("GET " + path + " HTTP/1.1\r\nHost: " + parsed.hostname +
                    "\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n").encode("ascii"))
                response = http.client.HTTPResponse(conn)
                response.begin()
                if response.status != 200 or response.getheader("Content-Encoding", "identity") != "identity":
                    raise ValueError("provider_export_download_failed")
                data = response.read(MAX_BYTES + 1)
                if not data or len(data) > MAX_BYTES:
                    raise ValueError("provider_export_size_limit")
                return data
    except (OSError, http.client.HTTPException, UnicodeError):
        raise ValueError("provider_export_download_failed") from None


def verify_export(creation_id, creation_observation, zip_observation, job_id, video_metadata):
    """Return (export bytes, safe provenance); callers must retain the inputs.

    Caller must separately attest that it requested this ZIP for this creation.
    Equality to the exact creation GET video additionally binds the bytes to the
    chosen creation. This representation is not labelled an original master.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", creation_id) or not re.fullmatch(r"[0-9a-f-]{36}", job_id):
        raise ValueError("invalid_provider_export_identity")
    creation = _text(creation_observation)
    status = _text(zip_observation)
    if (_field(creation, "identifier") != creation_id or _field(creation, "status") != "completed"
            or _field(creation, "tool") != "video-generator" or _field(status, "status") != "finished"
            or _field(status, "total_files", "  ") != "1" or _field(status, "processed_files", "  ") != "1"
            or re.search(r"^\s*isPreviewProxy:\s*true\s*$", creation, re.M)
            or re.search(r"^downloadUrl:\s*\S", creation, re.M)
            or re.search(r"^    - type: original\s*$", creation, re.M)):
        raise ValueError("provider_export_identity_mismatch")
    url = _field(creation, "url")
    videos = re.findall(r"^    - type: video\s*\n((?:^      .*\n?)*)", creation, re.M)
    if len(videos) != 1 or _field(videos[0], "url", "      ") != url:
        raise ValueError("provider_export_video_ambiguous")
    zip_url = _field(status, "download_url", "  ")
    archive = _zip_bytes(zip_url, job_id)
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            files = [item for item in zipped.infolist() if not item.is_dir()]
            if len(files) != 1 or files[0].file_size <= 0 or files[0].file_size > MAX_BYTES or files[0].flag_bits & 1:
                raise ValueError("invalid_provider_export_archive")
            data = zipped.read(files[0])
    except (zipfile.BadZipFile, RuntimeError, OSError):
        raise ValueError("invalid_provider_export_archive") from None
    direct = fetch_original("magnific", {"url": url, "mime_type": "video/mp4"})
    if data != direct:
        raise ValueError("provider_export_differs_from_creation")
    if not isinstance(video_metadata, dict) or video_metadata.get("identifier") != creation_id:
        raise ValueError("invalid_provider_video_metadata")
    with tempfile.TemporaryDirectory(prefix="aimaster-export-check-") as directory:
        file = Path(directory) / "export.mp4"
        file.write_bytes(data)
        try:
            ffprobe = find_program("ffprobe")
            if not ffprobe:
                raise ValueError("ffprobe unavailable")
            probe = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                "format=duration:stream=codec_name,width,height,pix_fmt", "-of", "json", str(file)],
                capture_output=True, timeout=30, check=True)
            observed = json.loads(probe.stdout)
            streams = [x for x in observed["streams"] if "width" in x]
            stream = streams[0] if len(streams) == 1 else {}
            duration = float(observed["format"]["duration"])
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, IndexError):
            raise ValueError("provider_export_probe_failed") from None
    try:
        advertised_duration = float(video_metadata["durationSeconds"])
    except (TypeError, ValueError, KeyError):
        raise ValueError("provider_export_metadata_mismatch") from None
    if (not all(math.isfinite(value) and value > 0 for value in (duration, advertised_duration))
            or stream.get("width") != video_metadata.get("width") or stream.get("height") != video_metadata.get("height")
            or stream.get("codec_name") != video_metadata.get("codecName")
            or stream.get("pix_fmt") != video_metadata.get("pixFmt")
            or abs(duration - advertised_duration) > 0.1):
        raise ValueError("provider_export_metadata_mismatch")
    return data, {"kind": "provider_export", "creation_id": creation_id, "zip_job_id": job_id,
                  "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
                  "width": stream["width"], "height": stream["height"], "duration": duration,
                  "codec": stream["codec_name"], "pix_fmt": stream["pix_fmt"]}


def collect_provider_export(workspace, runner, action_id, creation_observation, zip_observation, job_id, video_metadata,
                            *, operation_locked=False):
    """Ingest the verified export as a labelled representation, never a master."""
    from . import authoring, provider_receipts as receipts
    from .domain_positions import current_member, resolve_position
    from .family_setup import operation_lease
    from .family_setup.state import write_bytes
    from .operator_adapters import state_digest
    from .provider_collection import _basis_matches, _GuardedStore
    from .store import RevisionConflict
    from .workspace import resolve_workspace_paths
    with nullcontext() if operation_locked else operation_lease(owner="provider-export"):
        basis_path = receipts.path_for(workspace, action_id, "basis")
        basis = receipts.read(basis_path)
        ack = receipts.read(receipts.path_for(workspace, action_id, "ack"))
        action = runner.ledger.get_action(action_id)
        root, _, media, _ = resolve_workspace_paths(workspace)
        receipt_path = receipts.safe_path(root, basis_path.parent / (action_id + ".provider-export.json"))
        previous = receipts.read(receipt_path)
        active = runner.ledger.collection_evidence(action_id)
        destination = receipts.safe_path(root, media / "provider-exports" / (action_id + ".mp4"))
        if previous and active and active["phase"] == "succeeded" and active["receipt_sha256"] == state_digest(previous):
            proof = previous.get("representation", {})
            if (proof.get("kind") != "provider_export" or not destination.is_file() or
                    destination.stat().st_size > MAX_BYTES or hashlib.sha256(destination.read_bytes()).hexdigest() != proof.get("sha256")):
                raise ValueError("provider_export_changed")
            return {"action_id": action_id, "status": "succeeded", "collection": "succeeded",
                    "representation": "provider_export"}
        if (not basis or not ack or action["external_id"] != ack["creation_id"]
                or action["status"] not in {"running", "outcome_unknown"}
                or basis["route"]["provider"] != "magnific"
                or basis["route"]["operation"] != "video_generate"
                or any(ack[k] != basis["route"][k] for k in ("provider", "model", "operation", "prompt_sha256", "basis_sha256"))):
            raise ValueError("provider_export_ack_mismatch")
        creation = ack["creation_id"]
        if previous:
            proof = previous.get("representation", {})
            if (previous.get("basis_sha256") != state_digest(basis) or proof.get("kind") != "provider_export"
                    or proof.get("creation_id") != creation or not destination.is_file()
                    or destination.stat().st_size > MAX_BYTES
                    or hashlib.sha256(destination.read_bytes()).hexdigest() != proof.get("sha256")):
                raise ValueError("provider_export_recovery_evidence_missing")
            receipt = previous
            if active and active["receipt_sha256"] == state_digest(receipt) and active["phase"] in {"conflict", "resolved_keep", "resolved_adopt"}:
                return {"action_id": action_id, "status": action["status"], "collection": active["phase"],
                        "representation": "provider_export"}
        else:
            data, proof = verify_export(creation, creation_observation, zip_observation, job_id, video_metadata)
            if destination.exists():
                if destination.stat().st_size > MAX_BYTES or hashlib.sha256(destination.read_bytes()).hexdigest() != proof["sha256"]:
                    raise ValueError("provider_export_changed")
            else:
                write_bytes(destination, data)
            receipt = {"schema_version": 1, "basis_sha256": state_digest(basis), "representation": proof,
                       "observation": "completed_provider_export", "assurance": "operator_attested_mcp",
                       "creation_observation": creation_observation, "zip_observation": zip_observation,
                       "video_metadata": video_metadata}
            receipts.immutable(receipt_path, receipt)
        digest = state_digest(receipt)
        runner.ledger.reconcile_collection(action_id, digest, creation, "received")
        assets = authoring.open_assets(workspace)
        asset = assets.register(destination.relative_to(root).as_posix(), "result")
        def phase(value):
            record = runner.ledger.reconcile_collection(action_id, digest, creation, value)
            return {"action_id": action_id, "status": record["status"], "collection": runner.ledger.collection(action_id),
                    "representation": "provider_export"}
        state = runner.store.load(basis["project_id"])
        try:
            spec = _basis_matches(workspace, basis, state)
            current = current_member(state, spec, "result", missing_ok=True)
            old_ids = {item["version_id"] for item in basis["state"].get(spec["result_collection"], [])}
            if current and current.get("asset_id") == asset["asset_id"] and current["version_id"] not in old_ids:
                assets.resolve(asset["asset_id"])
                return phase("succeeded")
            if state["revision"] != basis["execution_revision"] or state_digest(state) != state_digest(basis["state"]):
                return phase("conflict")
            authoring.add_result_version(_GuardedStore(runner.store, workspace, basis), assets, basis["project_id"],
                basis["execution_revision"], target=spec["position_id"], asset_id=asset["asset_id"],
                caption="Выгрузка сервиса · оригинал не подтверждён")
            after = runner.store.load(basis["project_id"])
            result = current_member(after, resolve_position(after, spec["position_id"]), "result")
            if not result or result["asset_id"] != asset["asset_id"]:
                raise ValueError("provider_export_readback_failed")
        except (ValueError, RevisionConflict):
            return phase("conflict")
        return phase("succeeded")

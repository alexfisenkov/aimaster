"""Read-only builtin/user guide candidates with exact scope and content checks.

The existing user registry owns schema and matching semantics. This layer only
adds a namespace; it never imports guide prose as executable instructions.
"""
from __future__ import annotations

import json
import copy
from pathlib import Path
from types import SimpleNamespace

from scripts import guide_registry as registry

DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "guides" / "catalog.json"
CHOICE_SCOPE = ("stage", "kind", "modality", "task", "provider", "model_family", "model", "version")


def validate_choice(choice):
    """Validate persisted selection syntax without reading private files."""
    registry._require_exact_fields(choice, {*CHOICE_SCOPE, "source", "ref", "sha256"}, "guide choice")
    if choice["stage"] not in {"scenario", "image_plan", "image_results", "motion", "audio", "assembly"}:
        raise registry.RegistryError("guide choice stage is unsupported")
    if choice["kind"] not in registry.KINDS or choice["modality"] not in registry.MODALITIES:
        raise registry.RegistryError("guide choice kind or modality is unsupported")
    registry._require_slug(choice["task"], "guide choice task")
    for key in ("provider", "model_family", "model", "version"):
        if choice[key] is not None:
            registry._require_string_list([choice[key]], "guide choice " + key)
    source = choice["source"]
    if source not in {"builtin", "user", "none"}:
        raise registry.RegistryError("guide choice source must be builtin, user or none")
    if source == "none":
        if choice["ref"] is not None or choice["sha256"] is not None:
            raise registry.RegistryError("source none requires null ref and sha256")
    else:
        ref = choice["ref"]
        if not isinstance(ref, str) or not ref.startswith(source + ":"):
            raise registry.RegistryError("guide ref must match its namespace")
        registry._require_slug(ref[len(source) + 1:], "guide ref id")
        if not isinstance(choice["sha256"], str) or not registry.SHA256.fullmatch(choice["sha256"]):
            raise registry.RegistryError("guide choice requires a SHA-256 checksum")
    return copy.deepcopy(choice)


def resolve_choice(workspace, choice, *, catalog_path=None):
    """Revalidate the exact saved choice immediately before using its guide."""
    choice = validate_choice(choice)
    if choice["source"] == "none":
        return None
    result = match(workspace, SimpleNamespace(**choice), catalog_path=catalog_path)
    exact = [entry for entry in result["matches"] if entry["ref"] == choice["ref"]
             and entry["sha256"] == choice["sha256"]]
    if len(exact) != 1:
        raise registry.RegistryError("guide choice has no exact current match (scope mismatch or stale content)")
    selected = copy.deepcopy(exact[0])
    provenance = selected.get("provenance", {})
    selected["readings"] = [{"path": selected["path"], "sha256": selected["sha256"], "role": "selected_guide"},
                            *(provenance.get("required_readings", []) if isinstance(provenance, dict) else [])]
    return selected


def candidates(workspace, *, catalog_path=None) -> dict:
    user_path = registry._registry_path(Path(workspace))
    user, _ = registry._read_registry(user_path)
    catalog_path = Path(catalog_path) if catalog_path is not None else DEFAULT_CATALOG
    builtin = {"entries": [], "bundle_version": None}
    if catalog_path.exists():
        try:
            builtin = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise registry.RegistryError("builtin catalog is unreadable") from error
        registry._require_exact_fields(builtin, {"schema_version", "bundle_version", "entries"}, "catalog")
        if builtin["schema_version"] != 1 or not isinstance(builtin["bundle_version"], str):
            raise registry.RegistryError("unsupported builtin catalog schema or bundle version")
        if not isinstance(builtin["entries"], list):
            raise registry.RegistryError("catalog entries must be a list")
        normalized = []
        for entry in builtin["entries"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("provenance"), (dict, list)):
                raise registry.RegistryError("builtin entry requires provenance")
            normalized.append({k: v for k, v in entry.items() if k != "provenance"})
        registry.validate_registry({"schema_version": 1, "revision": 0, "entries": normalized})
    elif catalog_path != DEFAULT_CATALOG:
        raise registry.RegistryError("builtin catalog does not exist")
    entries = []
    for namespace, root, source in (("builtin", catalog_path.parent, builtin["entries"]),
                                    ("user", user_path.parent, user["entries"])):
        for entry in source:
            reason = registry._stale_reason(root, entry)
            provenance = entry.get("provenance", {})
            readings = provenance.get("required_readings", []) if isinstance(provenance, dict) else []
            if not isinstance(readings, list) or len(readings) > 4:
                raise registry.RegistryError("invalid selected guide readings")
            for reading in readings:
                if not isinstance(reading, dict) or set(reading) != {"path", "sha256", "role"} or reading["role"] != "creative_methodology":
                    raise registry.RegistryError("invalid selected guide reading")
                if registry._stale_reason(root, reading):
                    reason = "required-methodology-stale"
            candidate = dict(entry, namespace=namespace, ref=f"{namespace}:{entry['id']}",
                             status="stale" if reason else "valid")
            if reason:
                candidate["reason"] = reason
            entries.append(candidate)
    return {"ok": True, "schema_version": 1, "revision": user["revision"],
            "bundle_version": builtin["bundle_version"], "entries": entries}


def match(workspace, scope, *, catalog_path=None) -> dict:
    listing = candidates(workspace, catalog_path=catalog_path)
    matches, stale = [], []
    for entry in listing["entries"]:
        if (entry["kind"] != scope.kind or scope.modality not in entry["modalities"]
                or scope.task not in entry["tasks"]
                or not registry._provider_matches(entry["providers"], scope.provider)):
            continue
        rank = registry._model_rank(entry, scope)
        if rank is None:
            continue
        if entry["status"] == "stale":
            stale.append({key: entry[key] for key in ("id", "ref", "namespace", "status", "reason")})
        else:
            matches.append(dict(entry, match_rank=rank))
    matches.sort(key=lambda entry: (-entry["match_rank"], entry["ref"]))
    return {"ok": True, "revision": listing["revision"], "matches": matches, "stale": stale}

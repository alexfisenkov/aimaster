#!/usr/bin/env python3
"""Fail closed when a provider-native reference binding is incomplete."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from studio.platform_compat import ensure_utf8_stdio  # noqa: E402


ROOT_FIELDS = {
    "schema_version",
    "operation_id",
    "provider",
    "route",
    "model",
    "binding_source",
    "observed_at",
    "state_revision",
    "references",
}
COMMON_FIELDS = {
    "canonical",
    "reference_id",
    "asset_id",
    "role",
    "transport",
    "chip_verified",
}
TRANSPORT_FIELDS = {
    "inline": {"native"},
    "structured": {"slot"},
    "hybrid": {"native", "slot"},
}
BINDING_SOURCES = {"plain_text", "rich_ui", "structured_schema", "hybrid"}
CANONICAL_TAG = re.compile(r"(?<![A-Za-z0-9_])@(?:IMG|VID|VOICE)_\d+(?![A-Za-z0-9_])")


def _exact_token_present(text: str, token: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])"
    return re.search(pattern, text) is not None


def _require_nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def validate_binding(manifest: Any, prompt: str) -> dict[str, int | str]:
    if not isinstance(manifest, dict):
        raise ValueError("binding manifest must be an object")
    missing = ROOT_FIELDS - set(manifest)
    extra = set(manifest) - ROOT_FIELDS
    if missing:
        raise ValueError(f"binding manifest missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"binding manifest has unknown fields: {', '.join(sorted(extra))}")
    if manifest["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    for field in ("operation_id", "provider", "route", "model"):
        _require_nonempty(manifest[field], field)
    binding_source = manifest["binding_source"]
    if binding_source not in BINDING_SOURCES:
        raise ValueError(
            "binding_source must be plain_text, rich_ui, structured_schema or hybrid"
        )
    observed_at = _require_nonempty(manifest["observed_at"], "observed_at")
    normalized_timestamp = observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at
    try:
        parsed_timestamp = datetime.fromisoformat(normalized_timestamp)
    except ValueError as error:
        raise ValueError("observed_at must be an ISO-8601 timestamp") from error
    if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    state_revision = manifest["state_revision"]
    if isinstance(state_revision, bool) or not isinstance(state_revision, int) or state_revision < 0:
        raise ValueError("state_revision must be a non-negative integer")
    references = manifest["references"]
    if not isinstance(references, list):
        raise ValueError("references must be a list")
    if not isinstance(prompt, str):
        raise ValueError("prompt must be text")

    canonicals: set[str] = set()
    native_tokens: set[str] = set()
    structured_slots: set[str] = set()
    inline_count = 0
    structured_count = 0

    for index, reference in enumerate(references):
        label = f"references[{index}]"
        if not isinstance(reference, dict):
            raise ValueError(f"{label} must be an object")
        transport = reference.get("transport")
        if transport not in TRANSPORT_FIELDS:
            raise ValueError(f"{label}.transport must be inline, structured or hybrid")
        expected = COMMON_FIELDS | TRANSPORT_FIELDS[transport]
        required = {
            "canonical",
            "reference_id",
            "asset_id",
            "role",
            "transport",
        } | TRANSPORT_FIELDS[transport]
        missing = required - set(reference)
        extra = set(reference) - expected
        if missing:
            raise ValueError(f"{label} missing fields: {', '.join(sorted(missing))}")
        if extra:
            raise ValueError(f"{label} has unknown fields: {', '.join(sorted(extra))}")

        canonical = _require_nonempty(reference["canonical"], f"{label}.canonical")
        _require_nonempty(reference["reference_id"], f"{label}.reference_id")
        _require_nonempty(reference["asset_id"], f"{label}.asset_id")
        _require_nonempty(reference["role"], f"{label}.role")
        if canonical in canonicals:
            raise ValueError(f"duplicate canonical reference: {canonical}")
        canonicals.add(canonical)

        chip_verified = reference.get("chip_verified", False)
        if not isinstance(chip_verified, bool):
            raise ValueError(f"{label}.chip_verified must be boolean")
        if binding_source == "plain_text" and transport != "inline":
            raise ValueError("plain_text binding_source requires inline transport")
        if binding_source == "structured_schema" and transport != "structured":
            raise ValueError("structured_schema binding_source requires structured transport")

        if transport in {"inline", "hybrid"}:
            native = _require_nonempty(reference["native"], f"{label}.native")
            if native in native_tokens:
                raise ValueError(f"duplicate native inline tag: {native}")
            native_tokens.add(native)
            inline_count += 1
            if not _exact_token_present(prompt, native):
                raise ValueError(f"missing provider-native inline tag in prompt: {native}")
            if canonical != native and _exact_token_present(prompt, canonical):
                raise ValueError(f"unresolved canonical tag remains in native prompt: {canonical}")
            if binding_source == "rich_ui" and not chip_verified:
                raise ValueError(f"provider mention chip was not verified: {native}")

        if transport in {"structured", "hybrid"}:
            slot = _require_nonempty(reference["slot"], f"{label}.slot")
            if slot in structured_slots:
                raise ValueError(f"duplicate structured slot: {slot}")
            structured_slots.add(slot)
            structured_count += 1
            if transport == "structured" and _exact_token_present(prompt, canonical):
                raise ValueError(f"unresolved canonical tag remains in native prompt: {canonical}")

    allowed_canonical_native = {
        reference["canonical"]
        for reference in references
        if reference.get("transport") in {"inline", "hybrid"}
        and reference.get("native") == reference.get("canonical")
    }
    for token in CANONICAL_TAG.findall(prompt):
        if token not in allowed_canonical_native:
            raise ValueError(f"unresolved canonical tag remains in native prompt: {token}")

    return {
        "status": "valid",
        "operation_id": manifest["operation_id"],
        "provider": manifest["provider"],
        "references": len(references),
        "inline_references": inline_count,
        "structured_references": structured_count,
    }


def _canonical_identity(value: Any, label: str) -> str:
    return _require_nonempty(value, label).removeprefix("@")


def validate_claimed_context(manifest: dict, package: Any) -> None:
    """Compare the manifest with the frozen context returned by `claim`."""

    if not isinstance(package, dict):
        raise ValueError("claimed context package must be an object")
    action_id = package.get("action_id")
    if action_id != manifest["operation_id"]:
        raise ValueError("claimed context action_id does not match operation_id")
    untrusted = package.get("untrusted_input")
    if isinstance(untrusted, dict) and isinstance(untrusted.get("context"), dict):
        context = untrusted["context"]
    else:
        context = package.get("context")
    if not isinstance(context, dict):
        raise ValueError("claimed context is missing")
    if context.get("state_revision") != manifest["state_revision"]:
        raise ValueError("claimed context revision does not match state_revision")
    positions = context.get("positions")
    if not isinstance(positions, list):
        raise ValueError("claimed context positions must be a list")

    expected: list[tuple[str, str, str]] = []
    for position_index, position in enumerate(positions):
        if not isinstance(position, dict):
            raise ValueError(f"claimed context positions[{position_index}] must be an object")
        references = position.get("references", [])
        if not isinstance(references, list):
            raise ValueError("claimed context references must be a list")
        for reference_index, reference in enumerate(references):
            if not isinstance(reference, dict):
                raise ValueError("claimed context reference must be an object")
            reference_id = _require_nonempty(
                reference.get("reference_id"),
                f"claimed context references[{reference_index}].reference_id",
            )
            if "asset_id" in reference:
                expected.append(
                    (
                        _canonical_identity(reference.get("tag", reference_id), "claimed canonical"),
                        reference_id,
                        _require_nonempty(reference["asset_id"], "claimed asset_id"),
                    )
                )
            voice = reference.get("voice")
            if isinstance(voice, dict) and "asset_id" in voice:
                expected.append(
                    (
                        _canonical_identity(voice.get("tag"), "claimed voice tag"),
                        reference_id,
                        _require_nonempty(voice["asset_id"], "claimed voice asset_id"),
                    )
                )
        frames = position.get("frames", [])
        if not isinstance(frames, list):
            raise ValueError("claimed context frames must be a list")
        for frame in frames:
            if not isinstance(frame, dict):
                raise ValueError("claimed context frame must be an object")
            edge = _require_nonempty(frame.get("edge"), "claimed frame edge")
            scene_id = _require_nonempty(position.get("scene_id"), "claimed frame scene_id")
            expected.append(
                (
                    f"FRAME_{edge.upper()}",
                    f"frame:{scene_id}:{edge}",
                    _require_nonempty(frame.get("asset_id"), "claimed frame asset_id"),
                )
            )

    actual = [
        (
            _canonical_identity(reference["canonical"], "manifest canonical"),
            reference["reference_id"],
            reference["asset_id"],
        )
        for reference in manifest["references"]
    ]
    if Counter(expected) != Counter(actual):
        raise ValueError("claimed context references/assets do not match binding manifest")


def main() -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Validate an operation-scoped reference binding before generation."
    )
    parser.add_argument("manifest", type=Path, help="operation binding JSON")
    parser.add_argument("prompt", type=Path, help="exact provider-native prompt text")
    parser.add_argument("--context", type=Path, help="exact JSON package returned by claim")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        prompt = args.prompt.read_text(encoding="utf-8")
        result = validate_binding(manifest, prompt)
        if args.context is not None:
            context = json.loads(args.context.read_text(encoding="utf-8"))
            validate_claimed_context(manifest, context)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        print(f"reference binding invalid: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

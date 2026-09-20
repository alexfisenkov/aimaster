#!/usr/bin/env python3
"""Validate portable knowledge-source and capability-adapter configuration."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]*")
CAPABILITY = re.compile(r"[a-z][a-z0-9_]*")
CAPABILITY_IDS = {
    "transcription",
    "knowledge",
    "image_generation",
    "image_to_video",
    "visual_inspection",
    "file_delivery",
    "montage",
    "telegram_transport",
    "design_social_context",
    "agent_handoff",
}
ROOT_FIELDS = {"schema_version", "knowledge_sources", "adapters"}
KNOWLEDGE_FIELDS = {"id", "kind", "location", "required"}
ADAPTER_FIELDS = {"id", "capability", "kind", "enabled"}
SENSITIVE_FIELD_PARTS = {"secret", "token", "password", "cookie", "api_key"}
SENSITIVE_URL_PARAMETER_ALIASES = {
    "authorization",
    "auth",
    "credential",
    "credentials",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "authtoken",
    "bearertoken",
    "sessiontoken",
    "token",
    "apikey",
    "key",
    "password",
    "passwd",
    "pwd",
    "pass",
    "passphrase",
    "secret",
    "clientsecret",
}


def require_fields(item, expected, label):
    if not isinstance(item, dict):
        raise ValueError(f"{label} must be an object")
    missing = expected - set(item)
    extra = set(item) - expected
    if missing:
        raise ValueError(f"{label} missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"{label} has unknown fields: {', '.join(sorted(extra))}")


def require_identifier(value, label, pattern=IDENTIFIER):
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{label} must be a portable identifier")


def require_portable_path(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    path = Path(value)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or value.startswith("~")
        or any(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", part) is None
            for part in path.parts
        )
    ):
        raise ValueError(f"{label} must be a portable relative path")


def require_public_url(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must be an http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{label} must not contain credentials")
    for component_name, encoded_parameters in (
        ("query", parsed.query),
        ("fragment", parsed.fragment),
    ):
        for key, _ in parse_qsl(encoded_parameters, keep_blank_values=True):
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in SENSITIVE_URL_PARAMETER_ALIASES:
                raise ValueError(f"URL {component_name} must not contain secrets")


def reject_sensitive_fields(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_FIELD_PARTS):
                raise ValueError(f"sensitive field is not allowed: {key}")
            reject_sensitive_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            reject_sensitive_fields(nested)


def validate_config(config, base_dir=None, check_required_files=False):
    require_fields(config, ROOT_FIELDS, "config")
    if config["schema_version"] != 1:
        raise ValueError("schema_version must be 1")
    if not isinstance(config["knowledge_sources"], list):
        raise ValueError("knowledge_sources must be a list")
    if not isinstance(config["adapters"], list):
        raise ValueError("adapters must be a list")
    reject_sensitive_fields(config)

    source_ids = set()
    for index, source in enumerate(config["knowledge_sources"]):
        label = f"knowledge_sources[{index}]"
        require_fields(source, KNOWLEDGE_FIELDS, label)
        require_identifier(source["id"], f"{label}.id")
        if source["id"] in source_ids:
            raise ValueError(f"duplicate knowledge source id: {source['id']}")
        source_ids.add(source["id"])
        if source["kind"] == "file":
            require_portable_path(source["location"], f"{label}.location")
            if (
                check_required_files
                and source["required"]
                and not (base_dir / source["location"]).is_file()
            ):
                raise ValueError(
                    f"required knowledge file is missing: {source['location']}"
                )
        elif source["kind"] == "url":
            require_public_url(source["location"], f"{label}.location")
        else:
            raise ValueError(f"{label}.kind must be file or url")
        if not isinstance(source["required"], bool):
            raise ValueError(f"{label}.required must be boolean")

    adapter_ids = set()
    for index, adapter in enumerate(config["adapters"]):
        label = f"adapters[{index}]"
        require_fields(adapter, ADAPTER_FIELDS, label)
        require_identifier(adapter["id"], f"{label}.id")
        if adapter["id"] in adapter_ids:
            raise ValueError(f"duplicate adapter id: {adapter['id']}")
        adapter_ids.add(adapter["id"])
        require_identifier(adapter["capability"], f"{label}.capability", CAPABILITY)
        if adapter["capability"] not in CAPABILITY_IDS:
            raise ValueError(f"{label}.capability must be a canonical capability id")
        if adapter["kind"] not in {"local", "connected", "manual"}:
            raise ValueError(f"{label}.kind must be local, connected, or manual")
        if not isinstance(adapter["enabled"], bool):
            raise ValueError(f"{label}.enabled must be boolean")

    return {
        "status": "valid",
        "schema_version": 1,
        "knowledge_sources": len(config["knowledge_sources"]),
        "adapters": len(config["adapters"]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--check-required-files", action="store_true")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        report = validate_config(
            config,
            base_dir=args.config.parent,
            check_required_files=args.check_required_files,
        )
        print(json.dumps(report, sort_keys=True))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

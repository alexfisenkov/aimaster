#!/usr/bin/env python3
"""Manage portable aimaster project state."""

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from studio.platform_compat import ensure_utf8_stdio, fsync_directory, replace_file  # noqa: E402
from validate_config import validate_config  # noqa: E402


STAGE_SEQUENCE = ("intake", "storyboard", "images", "motion", "assembly", "complete")
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


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(temporary_path, path)
        fsync_directory(path.parent)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_state(project_dir, state):
    project_dir.mkdir(parents=True, exist_ok=True)
    state_path = project_dir / "state.json"
    if state_path.exists():
        previous = state_path.read_text(encoding="utf-8")
        json.loads(previous)
        atomic_write(project_dir / "state.previous.json", previous)
    serialized = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    atomic_write(state_path, serialized)


def read_state(project_dir):
    return json.loads((project_dir / "state.json").read_text(encoding="utf-8"))


def emit_state(project_dir, state):
    write_state(project_dir, state)
    print(json.dumps(state, ensure_ascii=False))


def command_init(args):
    if (args.project_dir / "state.json").exists():
        raise ValueError("state already exists; choose another project directory")
    configuration = None
    if args.config is not None:
        configuration = json.loads(args.config.read_text(encoding="utf-8"))
        validate_config(
            configuration,
            base_dir=args.config.parent,
            check_required_files=args.check_required_files,
        )
    elif args.check_required_files:
        raise ValueError("--check-required-files requires --config")
    if not isinstance(args.assumptions_json, list) or not all(
        isinstance(item, str) and item.strip() for item in args.assumptions_json
    ):
        raise ValueError("--assumptions-json must be a JSON list of non-empty strings")
    state = {
        "project_id": args.project_id,
        "mode": args.mode,
        "assumptions": args.assumptions_json,
        "stage": "intake",
        "sources": args.sources_json,
        "script": args.script,
        "comments": args.comments,
        "approvals": {
            "brief": "pending",
            "storyboard": "pending",
            "images": "pending",
            "motion": "pending",
        },
        "qa": {
            "technical": "pending",
            "visual": "pending",
            "visual_reason": "",
        },
        "assembly": {"outcome": "pending", "artifact": None},
        "blockers": [],
        "capabilities": {},
        "shots": [],
    }
    if configuration is not None:
        state["configuration"] = configuration
    emit_state(args.project_dir, state)


def command_add_shot(args):
    state = read_state(args.project_dir)
    if state["stage"] != "storyboard":
        raise ValueError("add-shot requires storyboard stage")
    if any(shot["shot_id"] == args.shot_id for shot in state["shots"]):
        raise ValueError(f"shot_id already exists: {args.shot_id}")
    storyboard_revision = {
        "revision": 1,
        "description": args.description,
        "transition": args.transition,
        "duration_seconds": args.duration_seconds,
        "reason": "initial storyboard",
    }
    state["shots"].append(
        {
            "shot_id": args.shot_id,
            "order": len(state["shots"]) + 1,
            "description": args.description,
            "transition": args.transition,
            "duration_seconds": args.duration_seconds,
            "status": "active",
            "storyboard": {
                "active_revision": 1,
                "revisions": [storyboard_revision],
            },
            "image": {
                "active_revision": None,
                "approval": "pending",
                "revisions": [],
            },
            "motion": {
                "active_revision": None,
                "approval": "pending",
                "revisions": [],
            },
        }
    )
    state["approvals"]["storyboard"] = "pending"
    emit_state(args.project_dir, state)


def find_shot(state, shot_id):
    for shot in state["shots"]:
        if shot["shot_id"] == shot_id:
            return shot
    raise ValueError(f"unknown shot_id: {shot_id}")


def command_edit_shot(args):
    state = read_state(args.project_dir)
    if state["stage"] != "storyboard":
        raise ValueError("edit-shot requires storyboard stage")
    if args.description is None and args.transition is None and args.duration_seconds is None:
        raise ValueError("edit-shot requires at least one storyboard change")
    shot = find_shot(state, args.shot_id)
    storyboard = shot.setdefault(
        "storyboard",
        {
            "active_revision": 1,
            "revisions": [
                {
                    "revision": 1,
                    "description": shot["description"],
                    "transition": shot["transition"],
                    "duration_seconds": shot.get("duration_seconds"),
                    "reason": "initial storyboard",
                }
            ],
        },
    )
    revision = storyboard["revisions"][-1]["revision"] + 1
    description = args.description if args.description is not None else shot["description"]
    transition = args.transition if args.transition is not None else shot["transition"]
    duration = (
        args.duration_seconds
        if args.duration_seconds is not None
        else shot.get("duration_seconds")
    )
    storyboard["revisions"].append(
        {
            "revision": revision,
            "description": description,
            "transition": transition,
            "duration_seconds": duration,
            "reason": args.reason,
        }
    )
    storyboard["active_revision"] = revision
    shot.update(
        description=description,
        transition=transition,
        duration_seconds=duration,
    )
    state["approvals"]["storyboard"] = "pending"
    emit_state(args.project_dir, state)


def require_portable_relative_path(value, label="artifact"):
    path = Path(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or str(value).startswith("~")
        or not path.parts
        or any(not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", part) for part in path.parts)
    ):
        raise ValueError(f"{label} must be a portable relative path")
    return str(path)


def require_existing_project_file(project_dir, value, label="artifact"):
    relative = require_portable_relative_path(value, label)
    project_root = project_dir.resolve(strict=True)
    candidate = (project_root / relative).resolve(strict=False)
    if not candidate.is_relative_to(project_root) or not candidate.is_file():
        raise ValueError(f"{label} must be an existing file inside project root")
    return relative


def require_string_list(value, label, allow_empty=True):
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item.strip() for item in value)
    ):
        qualifier = "non-empty " if not allow_empty else ""
        raise ValueError(f"target_model {label} must be a {qualifier}list of non-empty strings")
    return value


def validate_target_model_decision(args):
    name = args.target_model or args.adapter
    if not isinstance(name, str) or not name.strip():
        raise ValueError("target_model name must be a non-empty string")
    if not isinstance(args.adapter, str) or not args.adapter.strip():
        raise ValueError("target_model selected adapter must be a non-empty string")
    requirements = require_string_list(args.requirements_json, "requirements")
    available = require_string_list(
        [args.adapter]
        if args.available_adapters_json is None
        else args.available_adapters_json,
        "available_adapters",
        allow_empty=False,
    )
    if args.adapter not in available:
        raise ValueError("target_model selected adapter must be listed in available_adapters")
    if not isinstance(args.selection_reason, str) or not args.selection_reason.strip():
        raise ValueError("target_model reason must be a non-empty string")
    return {
        "name": name,
        "requirements": requirements,
        "available_adapters": available,
        "selected_adapter": args.adapter,
        "reason": args.selection_reason,
    }


def command_revise(args):
    state = read_state(args.project_dir)
    required_stage = "images" if args.kind == "image" else "motion"
    if state["stage"] != required_stage:
        raise ValueError(f"{args.kind} revisions require {required_stage} stage")
    artifact = require_existing_project_file(args.project_dir, args.artifact)
    target_model = validate_target_model_decision(args)
    track = find_shot(state, args.shot_id)[args.kind]
    revision = (track["revisions"][-1]["revision"] + 1) if track["revisions"] else 1
    track["revisions"].append(
        {
            "revision": revision,
            "prompt": args.prompt,
            "adapter": args.adapter,
            "artifact": artifact,
            "reason": args.reason,
            "settings": args.settings_json,
            "provenance": args.provenance_json,
            "target_model": target_model,
            "qa": {
                "technical": args.technical_qa,
                "visual": args.visual_qa,
            },
        }
    )
    track["active_revision"] = revision
    track["approval"] = "pending"
    emit_state(args.project_dir, state)


def command_approve(args):
    state = read_state(args.project_dir)
    required_stage = "intake" if args.gate == "brief" else "storyboard"
    if state["stage"] != required_stage:
        raise ValueError(f"{args.gate} approval requires {required_stage} stage")
    state["approvals"][args.gate] = args.status
    emit_state(args.project_dir, state)


def command_approve_shot(args):
    state = read_state(args.project_dir)
    required_stage = "images" if args.kind == "image" else "motion"
    if state["stage"] != required_stage:
        raise ValueError(f"{args.kind} approval requires {required_stage} stage")
    track = find_shot(state, args.shot_id)[args.kind]
    if track["active_revision"] is None:
        raise ValueError(f"{args.kind} has no active revision: {args.shot_id}")
    revision = active_revision(track)
    if args.status == "approved":
        require_existing_project_file(args.project_dir, revision["artifact"])
        if revision["qa"]["technical"] != "passed":
            raise ValueError(f"{args.kind} approval requires passed technical QA")
    track["approval"] = args.status
    active_tracks = [
        shot[args.kind] for shot in state["shots"] if shot.get("status") == "active"
    ]
    approvals = [track["approval"] for track in active_tracks]
    gate = "images" if args.kind == "image" else "motion"
    state["approvals"][gate] = (
        "approved"
        if approvals and all(status == "approved" for status in approvals)
        else "partial"
        if any(status == "approved" for status in approvals)
        else "pending"
    )
    emit_state(args.project_dir, state)


def active_revision(track):
    number = track["active_revision"]
    return next((item for item in track["revisions"] if item["revision"] == number), None)


def active_revisions_pass_technical_qa(state):
    active_shots = [shot for shot in state["shots"] if shot.get("status") == "active"]
    return bool(active_shots) and all(
        (revision := active_revision(shot[kind])) is not None
        and revision["qa"]["technical"] == "passed"
        for shot in active_shots
        for kind in ("image", "motion")
    )


def validate_active_media_artifacts(project_dir, state):
    for shot in state.get("shots", []):
        if shot.get("status") != "active":
            continue
        for kind in ("image", "motion"):
            revision = active_revision(shot[kind])
            if revision is None:
                raise ValueError(f"active {kind} artifact requires an active revision")
            require_existing_project_file(
                project_dir,
                revision["artifact"],
                f"active {kind} artifact",
            )


def require_completion_ready(project_dir, state):
    assembly = state.get("assembly", {})
    artifact = assembly.get("artifact")
    if assembly.get("outcome") not in {"handoff", "final_artifact"} or not artifact:
        raise ValueError("complete requires an assembly outcome or handoff")
    if not (project_dir / artifact).is_file():
        raise ValueError("complete requires the recorded assembly artifact to exist")
    validate_active_media_artifacts(project_dir, state)
    qa = state.get("qa", {})
    if qa.get("technical") != "passed" or not active_revisions_pass_technical_qa(state):
        raise ValueError("complete requires passed technical QA")
    visual_status = qa.get("visual")
    if visual_status not in {"passed", "not_run"}:
        raise ValueError("complete requires explicit visual QA")
    if visual_status == "not_run" and not str(qa.get("visual_reason", "")).strip():
        raise ValueError("visual QA not_run requires a reason")
    unresolved = sorted(
        capability_id
        for capability_id, capability in state.get("capabilities", {}).items()
        if capability.get("status") == "outcome_unknown"
        or capability.get("resolution")
        not in {"executed", "fallback_accepted", "not_required"}
    )
    if unresolved:
        raise ValueError(f"unresolved capabilities: {', '.join(unresolved)}")
    open_blockers = sorted(
        blocker["id"]
        for blocker in state.get("blockers", [])
        if blocker.get("status") == "open"
    )
    if open_blockers:
        raise ValueError(f"open blockers: {', '.join(open_blockers)}")


def command_advance(args):
    state = read_state(args.project_dir)
    current_stage = state["stage"]
    if current_stage not in STAGE_SEQUENCE:
        raise ValueError(f"cannot advance from terminal stage: {current_stage}")
    current_index = STAGE_SEQUENCE.index(current_stage)
    if current_index == len(STAGE_SEQUENCE) - 1:
        raise ValueError("cannot advance from terminal stage: complete")
    expected_stage = STAGE_SEQUENCE[current_index + 1]
    if args.stage != expected_stage:
        raise ValueError(f"next stage from {current_stage} is {expected_stage}")
    if args.stage == "storyboard" and state["approvals"]["brief"] != "approved":
        raise ValueError("storyboard requires brief approval")
    if args.stage == "images":
        if state["approvals"]["storyboard"] != "approved":
            raise ValueError("images requires storyboard approval")
        if not any(shot.get("status") == "active" for shot in state["shots"]):
            raise ValueError("images requires at least one active shot")
    if args.stage == "motion" and state["approvals"]["images"] != "approved":
        raise ValueError("motion requires approved image revisions")
    if args.stage == "assembly" and state["approvals"]["motion"] != "approved":
        raise ValueError("assembly requires approved motion revisions")
    if args.stage == "complete":
        require_completion_ready(args.project_dir, state)
    state["stage"] = args.stage
    emit_state(args.project_dir, state)


def command_capability(args):
    state = read_state(args.project_dir)
    if args.name not in CAPABILITY_IDS:
        raise ValueError(f"not a canonical capability id: {args.name}")
    state.setdefault("capabilities", {})[args.name] = {
        "status": args.status,
        "adapter": args.adapter,
        "fallback": args.fallback,
        "reason": args.reason,
        "resolution": args.resolution,
        "executed_externally": False,
    }
    emit_state(args.project_dir, state)


def command_qa(args):
    state = read_state(args.project_dir)
    if state["stage"] != "assembly":
        raise ValueError("project QA summary requires assembly stage")
    if args.visual == "not_run" and not args.visual_reason.strip():
        raise ValueError("visual QA not_run requires a reason")
    state["qa"] = {
        "technical": args.technical,
        "visual": args.visual,
        "visual_reason": args.visual_reason,
    }
    emit_state(args.project_dir, state)


def command_blocker(args):
    state = read_state(args.project_dir)
    blockers = state.setdefault("blockers", [])
    existing = next((item for item in blockers if item["id"] == args.id), None)
    record = {"id": args.id, "status": args.status, "reason": args.reason}
    if existing is None:
        blockers.append(record)
    else:
        existing.update(record)
    emit_state(args.project_dir, state)


def validate_state_artifact_paths(state):
    for source in state.get("sources", []):
        require_portable_relative_path(source, "source artifact")
    for shot in state.get("shots", []):
        for kind in ("image", "motion"):
            for revision in shot[kind]["revisions"]:
                require_portable_relative_path(revision["artifact"])


def command_handoff(args):
    state = read_state(args.project_dir)
    if state["stage"] != "assembly":
        raise ValueError("handoff requires assembly stage")
    validate_state_artifact_paths(state)
    validate_active_media_artifacts(args.project_dir, state)
    output = Path(require_portable_relative_path(args.output, "handoff output"))
    state["assembly"] = {"outcome": "handoff", "artifact": str(output)}
    ready_for_handoff = (
        state["approvals"]["motion"] == "approved"
        and active_revisions_pass_technical_qa(state)
        and state.get("qa", {}).get("technical") == "passed"
    )
    manifest = {
        "project_id": state["project_id"],
        "mode": state["mode"],
        "stage": state["stage"],
        "sources": state.get("sources", []),
        "script": state.get("script", ""),
        "comments": state.get("comments", ""),
        "ready_for_handoff": ready_for_handoff,
        "approvals": state["approvals"],
        "qa": state.get("qa", {}),
        "assembly": state["assembly"],
        "blockers": state.get("blockers", []),
        "capabilities": state.get("capabilities", {}),
        "shots": [
            {
                "shot_id": shot["shot_id"],
                "order": shot["order"],
                "description": shot["description"],
                "transition": shot["transition"],
                "duration_seconds": shot.get("duration_seconds"),
                "active": {
                    "image": active_revision(shot["image"]),
                    "motion": active_revision(shot["motion"]),
                },
            }
            for shot in state["shots"]
            if shot.get("status") == "active"
        ],
    }
    target = args.project_dir / output
    atomic_write(target, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    write_state(args.project_dir, state)
    print(json.dumps(manifest, ensure_ascii=False))


def build_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init")
    init.add_argument("project_dir", type=Path)
    init.add_argument("--project-id", required=True)
    init.add_argument("--mode", choices=("guided", "autopilot"), required=True)
    init.add_argument("--sources-json", type=json.loads, default=[])
    init.add_argument("--script", default="")
    init.add_argument("--comments", default="")
    init.add_argument("--assumptions-json", type=json.loads, default=[])
    init.add_argument("--config", type=Path)
    init.add_argument("--check-required-files", action="store_true")
    init.set_defaults(handler=command_init)
    add_shot = subparsers.add_parser("add-shot")
    add_shot.add_argument("project_dir", type=Path)
    add_shot.add_argument("--shot-id", required=True)
    add_shot.add_argument("--description", required=True)
    add_shot.add_argument("--transition", default="cut")
    add_shot.add_argument("--duration-seconds", type=float)
    add_shot.set_defaults(handler=command_add_shot)
    edit_shot = subparsers.add_parser("edit-shot")
    edit_shot.add_argument("project_dir", type=Path)
    edit_shot.add_argument("--shot-id", required=True)
    edit_shot.add_argument("--description")
    edit_shot.add_argument("--transition")
    edit_shot.add_argument("--duration-seconds", type=float)
    edit_shot.add_argument("--reason", required=True)
    edit_shot.set_defaults(handler=command_edit_shot)
    revise = subparsers.add_parser("revise")
    revise.add_argument("project_dir", type=Path)
    revise.add_argument("--shot-id", required=True)
    revise.add_argument("--kind", choices=("image", "motion"), required=True)
    revise.add_argument("--prompt", required=True)
    revise.add_argument("--adapter", required=True)
    revise.add_argument("--artifact", required=True)
    revise.add_argument("--reason", required=True)
    revise.add_argument("--technical-qa", default="not_run")
    revise.add_argument("--visual-qa", default="visual_qa_not_run")
    revise.add_argument("--target-model")
    revise.add_argument("--requirements-json", type=json.loads, default=[])
    revise.add_argument("--available-adapters-json", type=json.loads)
    revise.add_argument("--selection-reason", default="selected available adapter")
    revise.add_argument("--settings-json", type=json.loads, default={})
    revise.add_argument("--provenance-json", type=json.loads, default={})
    revise.set_defaults(handler=command_revise)
    approve = subparsers.add_parser("approve")
    approve.add_argument("project_dir", type=Path)
    approve.add_argument("--gate", choices=("brief", "storyboard"), required=True)
    approve.add_argument(
        "--status", choices=("pending", "approved", "changes_requested"), required=True
    )
    approve.set_defaults(handler=command_approve)
    approve_shot = subparsers.add_parser("approve-shot")
    approve_shot.add_argument("project_dir", type=Path)
    approve_shot.add_argument("--shot-id", required=True)
    approve_shot.add_argument("--kind", choices=("image", "motion"), required=True)
    approve_shot.add_argument(
        "--status", choices=("pending", "approved", "changes_requested"), required=True
    )
    approve_shot.set_defaults(handler=command_approve_shot)
    advance = subparsers.add_parser("advance")
    advance.add_argument("project_dir", type=Path)
    advance.add_argument(
        "--stage",
        choices=("intake", "storyboard", "images", "motion", "assembly", "complete"),
        required=True,
    )
    advance.set_defaults(handler=command_advance)
    capability = subparsers.add_parser("capability")
    capability.add_argument("project_dir", type=Path)
    capability.add_argument("--name", required=True)
    capability.add_argument(
        "--status", choices=("available", "unavailable", "outcome_unknown"), required=True
    )
    capability.add_argument("--adapter", required=True)
    capability.add_argument("--fallback", required=True)
    capability.add_argument("--reason", required=True)
    capability.add_argument(
        "--resolution",
        choices=("pending", "executed", "fallback_prepared", "fallback_accepted", "not_required"),
        default="pending",
    )
    capability.set_defaults(handler=command_capability)
    qa = subparsers.add_parser("qa")
    qa.add_argument("project_dir", type=Path)
    qa.add_argument("--technical", choices=("pending", "passed", "failed"), required=True)
    qa.add_argument("--visual", choices=("pending", "passed", "failed", "not_run"), required=True)
    qa.add_argument("--visual-reason", default="")
    qa.set_defaults(handler=command_qa)
    blocker = subparsers.add_parser("blocker")
    blocker.add_argument("project_dir", type=Path)
    blocker.add_argument("--id", required=True)
    blocker.add_argument("--status", choices=("open", "resolved"), required=True)
    blocker.add_argument("--reason", required=True)
    blocker.set_defaults(handler=command_blocker)
    handoff = subparsers.add_parser("handoff")
    handoff.add_argument("project_dir", type=Path)
    handoff.add_argument("--output", default="handoff/manifest.json")
    handoff.set_defaults(handler=command_handoff)
    return parser


def main():
    ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

"""`creator_studio.py` commands for the working folder (spec 2026-09-23).

`workspace init`, `library list|add|import|match` and `action enqueue`.
Registered by `creator_studio.build_parser`; each prints one JSON object.
No command here calls a provider or the network.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from studio import library, library_match, library_projects
from studio.ledger import GRANT_REQUIRED_ACTIONS, ActionRequest
from studio.runner import open_ledger
from studio.workspace_init import init_workspace


def _print(payload):
    print(json.dumps(payload, ensure_ascii=False))


def command_workspace_init(args):
    _print(init_workspace(args.workspace))


def command_library_list(args):
    _print(library.list_entries(args.workspace, kind=args.kind))


def command_library_add(args):
    _print(library.add(args.workspace, kind=args.kind, label=args.label,
                       aliases=args.alias or (), file=args.file, voice_of=args.voice_of))


def command_library_import(args):
    _print(library_projects.import_from_projects(args.workspace))


def command_library_match(args):
    _print(library_match.match(args.workspace, args.text))


def command_action_enqueue(args):
    payload = json.loads(args.payload) if args.payload else {}
    ledger = open_ledger(args.workspace)
    action = ledger.enqueue(args.project, ActionRequest(
        action_type=args.type,
        target_id=args.target,
        payload=payload,
        expected_revision=args.expected_revision,
        idempotency_key=args.idempotency_key or f"cli-{uuid.uuid4().hex}",
    ))
    grant_id = action["grant_id"]
    _print({
        "action_id": action["action_id"],
        "project_id": action["project_id"],
        "action_type": action["action_type"],
        "target_id": action["target_id"],
        "status": action["status"],
        "grant_id": grant_id,
        "issued_by": ledger.grant_issuer(grant_id) if grant_id else None,
        "idempotency_key": action["idempotency_key"],
    })


def add_workspace_subcommands(subparsers) -> None:
    workspace_cmd = subparsers.add_parser("workspace", help="create the working-folder layout")
    workspace_sub = workspace_cmd.add_subparsers(dest="subcommand", required=True)
    init_cmd = workspace_sub.add_parser("init", help="create missing folders, library index and README")
    init_cmd.add_argument("workspace", type=Path)
    init_cmd.set_defaults(handler=command_workspace_init)

    library_cmd = subparsers.add_parser("library", help="workspace library of characters and voices")
    library_sub = library_cmd.add_subparsers(dest="subcommand", required=True)
    kinds = sorted(library.KIND_FOLDERS)
    list_cmd = library_sub.add_parser("list", help="list library entries")
    list_cmd.add_argument("workspace", type=Path)
    list_cmd.add_argument("--kind", choices=kinds, default=None)
    list_cmd.set_defaults(handler=command_library_list)

    add_cmd = library_sub.add_parser("add", help="copy one file into the library")
    add_cmd.add_argument("workspace", type=Path)
    add_cmd.add_argument("--kind", required=True, choices=kinds)
    add_cmd.add_argument("--label", required=True)
    add_cmd.add_argument("--alias", action="append", default=None)
    add_cmd.add_argument("--file", required=True, type=Path)
    add_cmd.add_argument("--voice-of", default=None, dest="voice_of",
                         help="library_id of the character this voice belongs to")
    add_cmd.set_defaults(handler=command_library_add)

    import_cmd = library_sub.add_parser("import", help="collect references from all projects")
    import_cmd.add_argument("workspace", type=Path)
    import_cmd.add_argument("--from-projects", required=True, action="store_true", dest="from_projects")
    import_cmd.set_defaults(handler=command_library_import)

    match_cmd = library_sub.add_parser("match", help="entries whose name occurs in an idea text")
    match_cmd.add_argument("workspace", type=Path)
    match_cmd.add_argument("--text", required=True)
    match_cmd.set_defaults(handler=command_library_match)

    action_cmd = subparsers.add_parser("action", help="queue a paid action in the durable ledger")
    action_sub = action_cmd.add_subparsers(dest="subcommand", required=True)
    enqueue_cmd = action_sub.add_parser("enqueue", help="queue vary/regenerate/generate")
    enqueue_cmd.add_argument("workspace", type=Path)
    enqueue_cmd.add_argument("project")
    enqueue_cmd.add_argument("--type", required=True, choices=sorted(GRANT_REQUIRED_ACTIONS))
    enqueue_cmd.add_argument("--target", required=True)
    enqueue_cmd.add_argument("--expected-revision", required=True, type=int, dest="expected_revision")
    enqueue_cmd.add_argument("--payload", default=None, help="JSON object (default {})")
    enqueue_cmd.add_argument("--idempotency-key", default=None, dest="idempotency_key")
    enqueue_cmd.set_defaults(handler=command_action_enqueue)

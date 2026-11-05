#!/usr/bin/env python3
"""Explicit foreground workspace controller; no global daemon installation."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio.operator import Operator, status, stop
from studio.family_setup import OperationBusy
from studio.platform_compat import ensure_utf8_stdio


def main(argv=None):
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "status", "stop"):
        command = sub.add_parser(name)
        command.add_argument("workspace", type=Path)
        if name == "run":
            command.add_argument("--agent", required=True, choices=("codex", "claude"))
            command.add_argument("--once", action="store_true")
            command.add_argument("--model")
    route = sub.add_parser("route-set")
    route.add_argument("workspace", type=Path)
    route.add_argument("project_id")
    route.add_argument("--position", required=True)
    route.add_argument("--expected-revision", type=int, required=True)
    route.add_argument("--provider", required=True, choices=("syntx", "higgsfield", "magnific", "fal"))
    route.add_argument("--model", required=True)
    route.add_argument("--operation", required=True)
    route.add_argument("--collection-mode", choices=("provider-original", "host-local-original"), default="provider-original")
    route.add_argument("--parameters-file", type=Path, required=True)
    receipt = sub.add_parser("record-provider", help="Record one completed-provider GET receipt; no generation")
    receipt.add_argument("workspace", type=Path)
    receipt.add_argument("action_id")
    receipt.add_argument("--file", type=Path, required=True)
    ack = sub.add_parser("record-ack", help="Persist a provider acknowledgement before polling")
    ack.add_argument("workspace", type=Path)
    ack.add_argument("action_id")
    ack.add_argument("--file", type=Path, required=True)
    recovery = sub.add_parser("reconcile", help="GET-only collection of an existing approved receipt")
    recovery.add_argument("workspace", type=Path)
    recovery.add_argument("action_id")
    recovery.add_argument("--original-file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command in {"record-provider", "record-ack", "reconcile"}:
            from studio.runner import open_runner
            runner = open_runner(args.workspace)
            if args.command in {"record-provider", "record-ack"}:
                if args.file.stat().st_size > 65536:
                    raise ValueError("receipt_size_limit")
                record = runner.record_provider_ack if args.command == "record-ack" else runner.record_provider
                result = record(args.workspace, args.action_id, json.loads(args.file.read_text(encoding="utf-8")))
            else:
                result = runner.reconcile(args.workspace, args.action_id, original_file=args.original_file)
            print(json.dumps(result))
            return 0 if result["status"] == "succeeded" or args.command in {"record-provider", "record-ack"} else 1
        if args.command == "route-set":
            from studio.operator_routes import set_route
            print(json.dumps(set_route(args.workspace, args.project_id, args.position, args.expected_revision,
                provider=args.provider, model=args.model, operation=args.operation,
                parameters=json.loads(args.parameters_file.read_text(encoding="utf-8")), collection_mode=args.collection_mode)))
            return 0
        if args.command != "run":
            print(json.dumps((status if args.command == "status" else stop)(args.workspace)))
            return 0
        with Operator(args.workspace, agent=args.agent, model=args.model) as controller:
            while not controller.stopping():
                try:
                    action = controller.step()
                except OperationBusy:
                    action = None
                if args.once:
                    print(json.dumps({"status": action["status"] if action else status(args.workspace)["status"]}))
                    return 0 if action and action["status"] == "succeeded" else 1
                if status(args.workspace).get("reason") == "restart_required":
                    return 2
                time.sleep(1)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, ValueError):
        print(json.dumps({"status": "collection_blocked" if args.command in {"record-provider", "reconcile"} else "needs_setup"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

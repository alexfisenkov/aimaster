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
    route.add_argument("--parameters-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "route-set":
            from studio.operator_routes import set_route
            print(json.dumps(set_route(args.workspace, args.project_id, args.position, args.expected_revision,
                provider=args.provider, model=args.model, operation=args.operation,
                parameters=json.loads(args.parameters_file.read_text(encoding="utf-8")))))
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
        print(json.dumps({"status": "needs_setup"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Opt-in family update at the beginning of a new idle host session."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio.family_setup import updates
from studio.family_setup.snapshots import snapshot_workspace, restore_workspace
from studio.family_setup.state import default_state_dir
from studio.platform_compat import ensure_utf8_stdio


def main(argv=None):
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("session-start", "policy", "rollback", "snapshot-workspace", "restore-workspace"))
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--session-id")
    parser.add_argument("--enabled", choices=("on", "off"))
    parser.add_argument("--component", choices=("aimaster", "aiediting", "syntx", "higgsfield", "magnific", "fal"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--locale", choices=("ru", "en"), default="ru")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--use-rollback", action="store_true")
    args = parser.parse_args(argv)
    directory = args.state_dir or default_state_dir(args.home)
    try:
        if args.command in {"snapshot-workspace", "restore-workspace"}:
            source = args.workspace if args.command == "snapshot-workspace" else args.snapshot
            if source is None or args.destination is None:
                parser.error("snapshot/restore requires --workspace or --snapshot, and --destination")
            result = snapshot_workspace(source, args.destination, state_dir=directory) if args.command == "snapshot-workspace" else \
                restore_workspace(source, args.destination, state_dir=directory, use_rollback=args.use_rollback)
        elif args.command == "policy":
            if args.enabled is None:
                parser.error("policy requires --enabled on|off")
            result = {"ok": True, "status": "policy_saved", "auto_update": updates.policy(args.enabled == "on", state_dir=directory)}
        elif args.command == "rollback":
            if args.component is None:
                parser.error("rollback requires --component")
            result = updates.rollback(args.component, state_dir=directory)
        else:
            if not args.session_id:
                parser.error("session-start requires --session-id")
            result = updates.session_start(args.session_id, state_dir=directory)
    except (OSError, ValueError) as error:
        result = {"ok": False, "status": "kept_current", "reason": type(error).__name__}
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
          ("Обновление: " if args.locale == "ru" else "Update: ") + result["status"] +
          ("; требуется новый сеанс" if result.get("restart_required") and args.locale == "ru" else
           "; restart required" if result.get("restart_required") else ""))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())

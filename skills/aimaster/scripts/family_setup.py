#!/usr/bin/env python3
"""Family setup/status. Run from a standalone installed skill directory."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from studio.family_setup.state import default_state_dir, OperationBusy, register_workspace
from studio.family_setup.providers import catalog, record_discovery
from studio.family_setup.service import setup, status
from studio.platform_compat import ensure_utf8_stdio


def render(result, locale):
    lines = [("Состояние: " if locale == "ru" else "Status: ") + result.get("status", "ok")]
    for name, item in result.get("components", {}).items():
        lines.append(f"{name}: {item.get('status', 'unknown')}")
        if item.get("required"):
            lines.append(("Требуется: " if locale == "ru" else "Required: ") + ", ".join(item["required"]))
    for name, hosts in result.get("providers", {}).items():
        if not isinstance(hosts, dict):
            continue
        for agent, item in hosts.items():
            if isinstance(item, dict) and "status" in item:
                lines.append(f"{name}/{agent}: {item['status']}")
                if item.get("next_step"):
                    lines.append("  " + item["next_step"])
    if result.get("reason"):
        lines.append(result["reason"])
    if result.get("status") == "auth_pending":
        lines.append("Откройте новый чат и выполните вход в MCP средствами агента." if locale == "ru" else
                     "Open a new session and complete MCP authentication in the host.")
    return "\n".join(lines)


def main(argv=None):
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("catalog", "status", "setup", "record-discovery", "register-workspace"))
    parser.add_argument("--home", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--agent", choices=("all", "codex", "claude"), default="all")
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--provider", choices=tuple(catalog()["providers"]), action="append")
    parser.add_argument("--install-deps", action="store_true")
    parser.add_argument("--no-aiediting", action="store_true")
    parser.add_argument("--auto-update", choices=("on", "off"))
    parser.add_argument("--syntx-upload-destination", choices=("uploaded", "hidden"))
    parser.add_argument("--refresh-official", action="store_true")
    parser.add_argument("--locale", choices=("ru", "en"), default="ru")
    parser.add_argument("--session-id")
    parser.add_argument("--accept-schema-change", action="store_true")
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args(argv)
    try:
        directory = args.state_dir or default_state_dir(args.home)
        if args.command == "catalog":
            result = catalog()
        elif args.command == "status":
            result = status(directory)
        elif args.command == "register-workspace":
            if args.workspace is None:
                parser.error("register-workspace requires --workspace")
            register_workspace(args.workspace, state_dir=directory)
            result = {"ok": True, "status": "workspace_registered"}
        elif args.command == "record-discovery":
            if args.agent == "all" or len(args.provider or []) != 1 or not args.session_id:
                parser.error("record-discovery requires one --agent, one --provider and --session-id; JSON evidence on stdin")
            evidence = json.load(sys.stdin)
            result = record_discovery(directory, args.provider[0], args.agent, args.session_id, evidence.get("tools"),
                authenticated=evidence.get("authenticated") is True, probe_succeeded=evidence.get("probe_succeeded") is True,
                accept_schema_change=args.accept_schema_change)
        else:
            result = setup(args.package, home=args.home, state_dir=directory,
                agents=("codex", "claude") if args.agent == "all" else (args.agent,), selected=args.provider,
                install_deps=args.install_deps, aiediting=not args.no_aiediting,
                auto_update=None if args.auto_update is None else args.auto_update == "on",
                syntx_destination=args.syntx_upload_destination, refresh_official=args.refresh_official)
    except OperationBusy:
        result = {"ok": False, "status": "deferred_busy"}
    except (OSError, ValueError) as error:
        result = {"ok": False, "status": "setup_failed", "reason": type(error).__name__}
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render(result, args.locale))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())

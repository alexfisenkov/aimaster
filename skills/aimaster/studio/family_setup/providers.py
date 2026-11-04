"""Known connector entries only; host CLI registration with private backup/read-back."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tomllib
import uuid

from .packages import run, SHA
from .state import write_bytes, write_json, private_dir, read_state, save_state, operation_lease, now


def catalog():
    value = json.loads(Path(__file__).with_name("catalog.json").read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or set(value["providers"]) != {"syntx", "higgsfield", "magnific", "fal"}:
        raise ValueError("invalid_provider_catalog")
    return value


def host_env(home):
    env = dict(os.environ)
    env.update(HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(Path(home) / ".codex"),
               PYTHONDONTWRITEBYTECODE="1", GIT_TERMINAL_PROMPT="0",
               npm_config_registry="https://registry.npmjs.org/",
               npm_config_userconfig=os.devnull)
    # An inherited override must not redirect a synthetic/selected home.
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.pop("NODE_OPTIONS", None)
    return env


def config_path(home, agent):
    return Path(home) / (".codex/config.toml" if agent == "codex" else ".claude.json")


def read_config(home, agent):
    path = config_path(home, agent)
    raw = path.read_bytes() if path.exists() else b""
    value = (tomllib.loads(raw.decode()) if agent == "codex" else json.loads(raw)) if raw else {}
    if not isinstance(value, dict):
        raise ValueError("invalid_host_config")
    return raw, value


def _entry(value, agent, name):
    return value.get("mcp_servers" if agent == "codex" else "mcpServers", {}).get(name)


def _without_entry(value, agent, name):
    value = copy.deepcopy(value)
    key = "mcp_servers" if agent == "codex" else "mcpServers"
    if key in value:
        value[key].pop(name, None)
        if not value[key]:
            value.pop(key)
    return value


def expected_entry(profile, *, command=None, args=None, environment=None):
    if profile["transport"] == "http":
        return {"url": profile["endpoint"]}
    return {"command": command, "args": args or [], "env": environment or {}}


def matches(actual, expected):
    if not isinstance(actual, dict):
        return False
    # A same-named entry with headers/auth/custom behavior belongs to its owner.
    safe = {"url", "command", "args", "env", "type", "enabled"}
    return set(actual) <= safe and actual.get("enabled", True) is True and all(
        actual.get(key, {} if key == "env" else None) == value for key, value in expected.items())


def register_connector(home, state_dir, agent, name, expected, executable, *, runner=run):
    raw, before = read_config(home, agent)
    current = _entry(before, agent, name)
    base = {"supported": True, "installed": False, "host_installed": bool(executable), "configured": False, "authenticated": False,
            "available": False, "tools_visible": False, "status": "needs_host", "agent": agent}
    base["next_step"] = "Retry setup --install-deps; official host setup: " + (
        "https://developers.openai.com/codex/cli/" if agent == "codex" else "https://code.claude.com/docs/en/setup")
    login_step = (f"codex mcp login {name}; restart, then tools/list and a read-only probe." if agent == "codex" else
                  "Open /mcp in Claude Code, complete OAuth, restart and run a read-only probe.") if "url" in expected else \
                 "In a new session use syntx_begin_login, then syntx_check_login; generation is separate."
    if current is not None:
        if matches(current, expected):
            return {**base, "installed": True, "configured": True, "status": "auth_pending", "restart_required": True,
                    "next_step": login_step}
        return {**base, "status": "config_conflict", "next_step": "Review the existing same-named connector in the host; it was preserved."}
    if not executable:
        return base
    path = config_path(home, agent)
    backup = Path(state_dir) / "backups" / (agent + "-" + uuid.uuid4().hex + path.suffix)
    write_bytes(backup, raw)
    if "url" in expected:
        argv = [*executable, "mcp", "add", name, "--url", expected["url"]] if agent == "codex" else [
            *executable, "mcp", "add", "--scope", "user", "--transport", "http", name, expected["url"]]
    elif agent == "claude":
        argv = [*executable, "mcp", "add-json", "--scope", "user", name,
                json.dumps({"type": "stdio", **expected})]
    else:
        argv = [*executable, "mcp", "add", name]
        for key, value in expected.get("env", {}).items():
            argv.extend(["--env", key + "=" + value])
        argv += ["--", expected["command"], *expected.get("args", [])]
    # The expected entry is constructed internally: no token-bearing headers/env accepted.
    code, _, _ = runner(argv, env=host_env(home), timeout=60)
    parsed = False
    try:
        _, after = read_config(home, agent)
        parsed = True
        preserved = _without_entry(before, agent, name) == _without_entry(after, agent, name)
        verified = matches(_entry(after, agent, name), expected)
    except (OSError, ValueError):
        preserved, verified = False, False
    if code or not preserved or not verified:
        # A CLI write and a user's concurrent write are not distinguishable by
        # comparing current bytes with bytes just read. Never restore the whole
        # old configuration here: that would erase unrelated edits. Keep the
        # observed file and the private recovery backup for explicit review.
        return {**base, "status": "registration_conflict" if parsed and not preserved else "registration_failed",
                "backup": str(backup), "observed_configured": verified, "config_preserved": True,
                "next_step": "Review the observed host configuration and private backup; no whole-file rollback was performed."}
    return {**base, "installed": True, "configured": True, "status": "auth_pending", "restart_required": True,
            "backup": str(backup), "next_step": login_step}


def record_discovery(state_dir, name, agent, session_id, tools, *, authenticated=False,
                     probe_succeeded=False, accept_schema_change=False):
    """Host adapter supplies its current tools/list and read-only probe result.

    This bridge does not perform OAuth or pretend to contact a provider. Only
    tool names and schema digests survive; schemas/account responses/tokens do not.
    """
    if name not in catalog()["providers"] or agent not in {"codex", "claude"}:
        raise ValueError("unknown_connector")
    if not isinstance(session_id, str) or not session_id or len(session_id) > 200:
        raise ValueError("invalid_session_id")
    if not isinstance(tools, list) or len(tools) > 10000:
        raise ValueError("invalid_tools")
    schemas = {}
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not re.fullmatch(r"[\w.:-]{1,160}", tool["name"]):
            raise ValueError("invalid_tool_name")
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict) or tool["name"] in schemas:
            raise ValueError("invalid_tool_schema")
        schemas[tool["name"]] = hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with operation_lease(state_dir, "host-discovery"):
        state = read_state(state_dir)
        connector = state.get("connectors", {}).get(name)
        if not connector:
            raise ValueError("connector_not_configured")
        previous = connector.setdefault("discovery", {}).get(agent, {})
        changed = bool(previous.get("schemas")) and previous["schemas"] != schemas
        accepted = not changed or accept_schema_change is True
        available = authenticated is True and probe_succeeded is True and bool(schemas) and accepted
        result = {"available": available, "authenticated": authenticated is True,
                  "tools_visible": bool(schemas), "session_id": session_id, "observed_at": now(),
                  "schemas": schemas if accepted else previous["schemas"],
                  "status": "schema_change_requires_review" if not accepted else "available" if available else "probe_required"}
        if not accepted:
            result["pending_schemas"] = schemas
        connector["discovery"][agent] = result
        save_state(state_dir, state)
    return result


def program(name):
    scripts = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import install
    return install._find_program(name)


def dependencies(state_dir, home, agents, install_missing, *, runner=run):
    """Use installed executables; opt-in installs only official packages.

    System Git/Node use the platform manager; host npm packages use a private
    prefix, never npm -g. Installer output is not copied into receipts.
    """
    env = host_env(home)
    programs = {name: program(name) for name in ("git", "node", "ffmpeg", "ffprobe")}
    if programs["node"]:
        code, version, _ = runner([programs["node"], "--version"], env=env, timeout=20)
        numbers = re.findall(r"\d+", version)
        if code or len(numbers) < 3 or tuple(map(int, numbers[:3])) < (22, 13, 0):
            programs["node"] = None
    steps = []
    if install_missing:
        for name in ("git", "node", "ffmpeg"):
            if programs[name]:
                continue
            argv = None
            if os.name == "nt" and program("winget"):
                package = {"git": "Git.Git", "node": "OpenJS.NodeJS.LTS", "ffmpeg": "Gyan.FFmpeg"}[name]
                argv = [program("winget"), "install", "-e", "--id", package,
                        "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]
            elif sys.platform == "darwin" and program("brew"):
                argv = [program("brew"), "install", name]
            elif program("apt-get") and program("sudo"):
                packages = ["nodejs", "npm"] if name == "node" else [name]
                argv = [program("sudo"), "-n", program("apt-get"), "install", "-y", *packages]
            if argv:
                code, _, _ = runner(argv, env=env, timeout=900)
                steps.append({"program": name, "status": "installed" if code == 0 else "install_failed"})
                programs[name] = program(name)
    programs["ffprobe"] = program("ffprobe")
    node = programs["node"]
    npm = None
    if node:
        code, version, _ = runner([node, "--version"], env=env, timeout=20)
        numbers = re.findall(r"\d+", version)
        if code or len(numbers) < 3 or tuple(map(int, numbers[:3])) < (22, 13, 0):
            programs["node"] = node = None
        else:
            from install_montage_node import npm_cli_js
            npm = npm_cli_js(node)
    hosts = {}
    for agent in agents:
        found = program(agent)
        hosts[agent] = [found] if found else None
        package = "@openai/codex" if agent == "codex" else "@anthropic-ai/claude-code"
        prefix = Path(state_dir) / "tools" / agent
        metadata = prefix / "node_modules" / package / "package.json"
        if not found and node and npm and not metadata.exists() and install_missing:
            private_dir(prefix)
            code, _, _ = runner([node, str(npm), "install", "--prefix", str(prefix), "--no-audit", "--no-fund", package],
                                env=env, timeout=600)
            steps.append({"program": agent, "status": "installed" if code == 0 else "install_failed"})
        if not found and node and metadata.is_file():
            entry = json.loads(metadata.read_text())["bin"]
            relative = entry if isinstance(entry, str) else entry[agent]
            cli = (metadata.parent / relative).resolve()
            cli.relative_to(metadata.parent.resolve())
            if cli.is_file():
                hosts[agent] = [node, str(cli)]
    return {"programs": programs, "npm": str(npm) if npm else None, "hosts": hosts, "steps": steps}


def install_syntx(home, state_dir, deps, *, runner=run):
    node, git = deps["programs"].get("node"), deps["programs"].get("git")
    if not (node and git and deps.get("npm")):
        return {"status": "needs_dependency", "installed": False, "required": ["Git", "Node.js >=22.13 with npm"]}
    origin = catalog()["providers"]["syntx"]["origin"]
    root = Path(state_dir) / "syntx"
    env = host_env(home)
    env["npm_config_ignore_scripts"] = "true"
    if not root.exists():
        code, _, _ = runner([git, "clone", "--depth", "1", origin, str(root)], env=env, timeout=180)
        if code:
            return {"status": "download_failed", "installed": False}
    for args, expected in ((["remote", "get-url", "origin"], origin), (["status", "--porcelain"], "")):
        code, out, _ = runner([git, "-C", str(root), *args], env=env)
        if code or out.strip() != expected:
            return {"status": "dirty_or_unknown_source", "installed": False}
    code, sha, _ = runner([git, "-C", str(root), "rev-parse", "HEAD"], env=env)
    if code or not SHA.fullmatch(sha.strip()):
        return {"status": "invalid_revision", "installed": False}
    if not (root / "dist/src/transports/stdio-owner.js").is_file():
        for args in (["ci", "--ignore-scripts", "--no-audit", "--no-fund"], ["run", "build"]):
            code, _, _ = runner([node, deps["npm"], *args], cwd=root, env=env, timeout=600)
            if code:
                return {"status": "build_failed", "installed": False}
    if not (root / "scripts/update-mcp.mjs").is_file() or not (root / "dist/src/transports/stdio-owner.js").is_file():
        return {"status": "incomplete_package", "installed": False}
    return {"status": "installed", "installed": True, "package": str(root), "node": node,
            "revision": sha.strip(), "origin": origin}


def syntx_entry(component, deps, *, destination, runner=run):
    if destination not in {"uploaded", "hidden"}:
        raise ValueError("select_syntx_upload_destination")
    root = Path(component["package"])
    code, output, _ = runner([component["node"], str(root / "scripts/print-media-mcp-config.mjs"),
                             "--confirm-enable-paid-tools", "--include-all-supported-media", "--include-self-update"], cwd=root)
    if code:
        raise ValueError("syntx_config_failed")
    value = json.loads(output)
    servers = value.get("mcpServers", {})
    if len(servers) != 1:
        raise ValueError("invalid_syntx_config")
    entry = next(iter(servers.values()))
    env = entry.get("env", {})
    for key, value in env.items():
        if not key.startswith("SYNTX_") or re.search(r"TOKEN|PASSWORD|SECRET|API_KEY", key):
            raise ValueError("unexpected_secret_field")
        if key.endswith("UPLOAD_DESTINATION"):
            env[key] = destination
        elif key.endswith("FFPROBE_PATH") or key.endswith("FFMPEG_PATH"):
            program_name = "ffprobe" if key.endswith("FFPROBE_PATH") else "ffmpeg"
            if not deps["programs"].get(program_name):
                raise ValueError("needs_" + program_name)
            env[key] = deps["programs"][program_name]
        elif key == "SYNTX_LOCAL_IMAGE_ROOTS" and value == "[]":
            # Preserve the official empty file-access allowlist. Installing a
            # connector does not grant access to every local workspace/media file.
            pass
        elif value not in {"1", "0", "true", "false", "all-supported"} and not (
                key.endswith("_MAX_FILE_BYTES") or key.endswith("_MAX_VIDEO_FILE_BYTES")) and not (
                key.endswith("_PROFILE_VERSION") and re.fullmatch(r"sha256-[0-9a-f]{64}\.json", value)):
            raise ValueError("unrecognized_syntx_setting")
    # Only the trusted printer's native entrypoint inside this verified checkout.
    command = component["node"]
    args = entry.get("args")
    if not isinstance(args, list) or len(args) != 1:
        raise ValueError("unexpected_syntx_command")
    Path(args[0]).resolve().relative_to(root.resolve())
    if not Path(args[0]).is_file():
        raise ValueError("missing_syntx_entrypoint")
    return {"command": command, "args": args, "env": env}

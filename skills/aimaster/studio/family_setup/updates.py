"""Opt-in update at a new idle session boundary; failed components keep last-good."""
from contextlib import ExitStack
import json
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import uuid

from ..platform_compat import file_lock
from . import packages, providers
from .state import (OperationBusy, default_state_dir, operation_lease, private_dir,
                    read_state, save_state, write_json, now)


def policy(enabled, *, state_dir=None):
    directory = private_dir(state_dir or default_state_dir())
    with operation_lease(directory, "update-policy"):
        state = read_state(directory)
        state["auto_update"] = {"enabled": bool(enabled), "confirmed_at": now()}
        save_state(directory, state)
    return state["auto_update"]


def workspace_guard(state, stack):
    """Hold legacy montage locks too; unsettled jobs are not erased by a dead PID."""
    for root in map(Path, state.get("workspaces", [])):
        if not root.is_dir():
            raise ValueError("workspace_unavailable")
        database = root / ".studio/actions.sqlite3"
        if database.exists():
            with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
                row = connection.execute("SELECT 1 FROM actions WHERE status IN ('running', 'outcome_unknown') LIMIT 1").fetchone()
                if row:
                    raise OperationBusy("unsettled_job")
        for lock in root.glob("projects/*/montage/.build.lock"):
            handle = stack.enter_context(lock.open("a+b"))
            stack.enter_context(file_lock(handle, blocking=False))


def check_current(component, name):
    if component.get("origin_status") not in {"verified", "skills_cli"}:
        raise ValueError(component.get("origin_status", "unknown_origin"))
    if component.get("origin", "").lower() != ("https://github.com/" + packages.OFFICIAL[name] + ".git").lower():
        raise ValueError("unknown_origin")
    if packages.digest_tree(Path(component["package"])) != component.get("fingerprint"):
        raise ValueError("dirty_package")
    for target in component.get("targets", []):
        if not Path(target).is_dir() or packages.digest_tree(Path(target).resolve()) != component["fingerprint"]:
            raise ValueError("dirty_target")


def update_package(name, state, directory, *, fetcher=packages.fetch_package):
    current = state["components"][name]
    check_current(current, name)
    with tempfile.TemporaryDirectory(prefix="stage-", dir=directory) as temporary:
        stage = Path(temporary) / name
        identity = fetcher(name, stage)
        # Do not trust a downloader's claim of identity or a malformed receipt.
        expected_origin = "https://github.com/" + packages.OFFICIAL[name] + ".git"
        if identity.get("origin") != expected_origin or not packages.SHA.fullmatch(identity.get("revision", "")):
            raise ValueError("untrusted_update_source")
        fingerprint = packages.validate_package(stage, name)
        if fingerprint != identity.get("fingerprint"):
            raise ValueError("corrupt_download")
        if fingerprint == current["fingerprint"]:
            return {"status": "current", "revision": current.get("revision")}
        if name == "aimaster" and not packages.compatibility(stage, state.get("workspaces", [])):
            return {"status": "compatibility_blocked", "restart_required": False}
        receipt = packages.install_package(stage, name, directory, state["home"], state["agents"],
            identity={**identity, "origin_status": "verified"}, previous=current)
        # Previous code and target backups remain immutable and addressable.
        state.setdefault("rollback", {})[name] = current
        state["components"][name] = receipt
        save_state(directory, state)
        return {"status": "updated", "revision": receipt["revision"], "restart_required": True}


def native_syntx(state, directory, operation, *, runner=packages.run):
    component = state["components"].get("syntx", {})
    if not component.get("installed"):
        return {"status": "not_installed"}
    root = Path(component["package"])
    git = providers.program("git")
    if not git:
        return {"status": "needs_git"}
    env = providers.host_env(state["home"])
    for args, expected in ((["remote", "get-url", "origin"], providers.catalog()["providers"]["syntx"]["origin"]),
                            (["status", "--porcelain"], "")):
        code, text, _ = runner([git, "-C", str(root), *args], env=env)
        if code or text.strip() != expected:
            return {"status": "dirty_or_unknown_source"}
    argv = [component["node"], str(root / "scripts/update-mcp.mjs"), operation]
    code, text, _ = runner(argv, cwd=root, env=env, timeout=900)
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return {"status": "native_update_failed"}
    # Explicit allowlist: never persist stdout containing personal/account fields.
    result = {key: value.get(key) for key in ("status", "current_sha", "latest_sha", "rollback_sha", "restart_required")}
    allowed = {"UP_TO_DATE", "UPDATE_AVAILABLE", "STAGED", "ROLLBACK_STAGED", "NO_ROLLBACK"}
    if code or result["status"] not in allowed:
        return {"status": "native_update_failed"}
    for key in ("current_sha", "latest_sha", "rollback_sha"):
        if result[key] is not None and not packages.SHA.fullmatch(result[key]):
            return {"status": "native_readback_failed"}
    if result["status"] in {"STAGED", "ROLLBACK_STAGED"}:
        pointer_path = Path(state["home"]) / ".syntx-mcp-updates/pointer.json"
        pointer = json.loads(pointer_path.read_text())
        if pointer.get("current") != result["current_sha"]:
            return {"status": "native_readback_failed"}
        selected = Path(pointer.get("current_path") or pointer_path.parent / "versions" / pointer["current"])
        if selected.is_symlink() or not selected.is_dir() or not (selected / "dist/src/transports/stdio-owner.js").is_file():
            return {"status": "native_readback_failed"}
        allowed = selected.resolve() == root.resolve() or selected.resolve().is_relative_to((pointer_path.parent / "versions").resolve())
        if not allowed:
            return {"status": "native_readback_failed"}
        code, sha, _ = runner([git, "-C", str(selected), "rev-parse", "HEAD"], env=env)
        if code or sha.strip() != pointer["current"]:
            return {"status": "native_readback_failed"}
        component["selected_revision"] = result["current_sha"]
        component["selected_package"] = str(selected)
        component["selected_runtime_sha256"] = packages.digest_tree(selected / "dist")
        component["restart_required"] = True
        save_state(directory, state)
    return result


def refresh_connectors(state, directory):
    """Refresh the local manifest; hosted tool discovery belongs to the new host session.

    No server pin/version is invented and no user OAuth store is opened here.
    """
    results = {}
    for name, connector in state.get("connectors", {}).items():
        if name == "syntx":
            continue
        profile = providers.catalog()["providers"][name]
        expected = providers.expected_entry(profile)
        backup = Path(directory) / "receipts" / (name + "-manifest-" + uuid.uuid4().hex + ".json")
        write_json(backup, connector)
        if expected != connector["expected"]:
            results[name] = {"status": "manifest_change_requires_review", "server_rollback": False}
            continue
        hosts = {}
        for agent in state["agents"]:
            _, config = providers.read_config(state["home"], agent)
            hosts[agent] = providers.matches(providers._entry(config, agent, name), expected)
        connector["manifest_version"] = providers.catalog()["manifest_version"]
        connector["previous_manifest"] = {"path": str(backup), "sha256": hashlib.sha256(backup.read_bytes()).hexdigest()}
        connector["discovery_required"] = True
        connector["available"] = False
        results[name] = {"status": "discovery_required", "configured": hosts,
                         "server_rollback": False, "restart_required": True}
    return results


def session_start(session_id, *, state_dir=None, fetcher=packages.fetch_package, runner=packages.run):
    if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 200:
        raise ValueError("invalid_session_id")
    directory = private_dir(state_dir or default_state_dir())
    try:
        with operation_lease(directory, "family-update"), ExitStack() as locks:
            state = read_state(directory)
            if not state["auto_update"]["enabled"]:
                return {"ok": True, "status": "disabled"}
            if state.get("last_session") == session_id:
                return {"ok": True, "status": "already_checked"}
            workspace_guard(state, locks)
            results = {}
            for name in ("aimaster", "aiediting"):
                if name not in state["components"]:
                    results[name] = {"status": "not_installed"}
                    continue
                try:
                    results[name] = update_package(name, state, directory, fetcher=fetcher)
                except (OSError, ValueError) as error:
                    reason = str(error) if isinstance(error, ValueError) and re_safe_reason(str(error)) else type(error).__name__
                    results[name] = {"status": "kept_current", "reason": reason}
            try:
                checked = native_syntx(state, directory, "check", runner=runner)
                results["syntx"] = native_syntx(state, directory, "apply", runner=runner) \
                    if checked["status"] == "UPDATE_AVAILABLE" else checked
            except (OSError, ValueError):
                results["syntx"] = {"status": "kept_current"}
            try:
                results.update(refresh_connectors(state, directory))
            except (OSError, ValueError):
                results["connectors"] = {"status": "kept_current"}
            state["last_session"], state["last_check"] = session_id, now()
            state["last_results"] = results
            save_state(directory, state)
            write_json(directory / "receipts" / ("update-" + uuid.uuid4().hex + ".json"), results)
            return {"ok": True, "status": "checked", "components": results,
                    "restart_required": any(item.get("restart_required") for item in results.values())}
    except OperationBusy:
        return {"ok": True, "status": "deferred_busy"}


def re_safe_reason(value):
    return value.replace("_", "").isalnum() and len(value) < 80


def rollback(name, *, state_dir=None, runner=packages.run):
    directory = private_dir(state_dir or default_state_dir())
    try:
        with operation_lease(directory, "family-rollback"), ExitStack() as locks:
            state = read_state(directory)
            workspace_guard(state, locks)
            if name == "syntx":
                return native_syntx(state, directory, "rollback", runner=runner)
            if name not in packages.OFFICIAL:
                connector = state.get("connectors", {}).get(name, {})
                previous = connector.get("previous_manifest")
                if not previous:
                    return {"ok": False, "status": "no_local_manifest_backup", "server_rollback": False}
                path = Path(previous["path"])
                if not path.resolve().is_relative_to((directory / "receipts").resolve()) or path.is_symlink() \
                        or hashlib.sha256(path.read_bytes()).hexdigest() != previous["sha256"]:
                    return {"ok": False, "status": "corrupt_backup", "server_rollback": False}
                saved = json.loads(path.read_text())
                if saved.get("expected") != connector.get("expected"):
                    return {"ok": False, "status": "config_change_requires_review", "server_rollback": False}
                saved["discovery_required"], saved["available"] = True, False
                state["connectors"][name] = saved
                save_state(directory, state)
                return {"ok": True, "status": "local_manifest_rolled_back", "server_rollback": False,
                        "host_config_unchanged": True, "restart_required": True}
            previous = state.get("rollback", {}).get(name)
            if not previous:
                return {"ok": False, "status": "no_rollback"}
            current = state["components"][name]
            check_current(current, name)
            packages.validate_package(Path(previous["package"]), name)
            if packages.digest_tree(Path(previous["package"])) != previous["fingerprint"]:
                return {"ok": False, "status": "corrupt_backup"}
            if name == "aimaster" and not packages.compatibility(Path(previous["package"]), state.get("workspaces", [])):
                return {"ok": False, "status": "compatibility_blocked", "data_unchanged": True,
                        "next_step": "Use a separate compatible workspace snapshot; the current package and data remain active."}
            restored = packages.install_package(Path(previous["package"]), name, directory, state["home"],
                state["agents"], previous=current, identity={key: previous[key] for key in
                    ("origin", "origin_status", "revision") if key in previous})
            state["components"][name] = restored
            state["rollback"][name] = current
            save_state(directory, state)
            return {"ok": True, "status": "rolled_back", "restart_required": True}
    except OperationBusy:
        return {"ok": False, "status": "deferred_busy"}

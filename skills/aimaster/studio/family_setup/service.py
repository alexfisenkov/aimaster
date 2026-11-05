"""One explicit setup invocation executes the selected available steps."""
from pathlib import Path
import tempfile
import copy

from . import packages, providers
from .state import default_state_dir, operation_lease, read_state, save_state, now, private_dir


def setup(package, *, home=None, state_dir=None, agents=("codex", "claude"), selected=None,
          install_deps=False, aiediting=True, auto_update=None, syntx_destination=None,
          refresh_official=False, runner=None):
    home = Path(home or Path.home()).expanduser().absolute()
    directory = private_dir(state_dir or default_state_dir(home if home != Path.home() else None))
    package = Path(package).resolve()
    if directory.is_relative_to(package):
        raise ValueError("state_must_be_outside_package")
    run = runner or packages.run
    with operation_lease(directory, "setup"):
        state = read_state(directory)
        state["home"] = str(home)
        if auto_update is not None:
            state["auto_update"] = {"enabled": bool(auto_update), "confirmed_at": now()}
        state["agents"] = list(agents)
        state["providers"] = list(selected or providers.catalog()["providers"])
        report = {"ok": True, "status": "configured", "providers": {}, "components": {}, "restart_required": True}
        previous = state["components"].get("aimaster")
        desired_targets = [str(home / (".agents" if agent == "codex" else ".claude") / "skills/aimaster") for agent in agents]
        if previous and set(desired_targets) <= set(previous.get("targets", [])) \
                and packages.digest_tree(Path(previous["package"])) == previous["fingerprint"] \
                and all(Path(target).exists() and packages.digest_tree(Path(target).resolve()) == previous["fingerprint"]
                        for target in previous["targets"]) and not refresh_official:
            report["components"]["aimaster"] = {"status": "already", "installed": True}
        else:
            with tempfile.TemporaryDirectory(prefix="family-setup-", dir=directory) as temporary:
                if refresh_official:
                    package = Path(temporary) / "aimaster"
                    identity = {**packages.fetch_package("aimaster", package), "origin_status": "verified"}
                else:
                    identity = packages.source_identity(package, "aimaster", home, runner=run)
                pending = copy.deepcopy(state)
                def publish(receipt):
                    pending["components"]["aimaster"] = receipt
                    if previous:
                        pending.setdefault("rollback", {})["aimaster"] = previous
                    save_state(directory, pending)
                receipt = packages.install_package(package, "aimaster", directory, home, agents,
                                                   identity=identity, previous=previous, publish=publish)
                state = pending
                report["components"]["aimaster"] = {"status": "installed", "installed": True,
                                                       "origin_status": receipt.get("origin_status")}
        # Persist each successful component before the next independent network step.
        save_state(directory, state)
        deps = providers.dependencies(directory, home, agents, install_deps, runner=run)
        report["dependencies"] = deps["steps"]
        for name in state["providers"]:
            profile = providers.catalog()["providers"][name]
            expected = providers.expected_entry(profile)
            if name == "syntx":
                component = providers.install_syntx(home, directory, deps, runner=run)
                state["components"][name] = component
                report["components"][name] = component
                if component["installed"]:
                    try:
                        expected = providers.syntx_entry(component, deps, destination=syntx_destination, runner=run)
                    except (OSError, ValueError) as error:
                        report["providers"][name] = {agent: {"installed": True, "configured": False,
                            "authenticated": False, "available": False, "status": str(error)} for agent in agents}
                        report["ok"] = False
                        save_state(directory, state)
                        continue
                else:
                    report["providers"][name] = {agent: {**component, "configured": False,
                        "authenticated": False, "available": False} for agent in agents}
                    report["ok"] = False
                    save_state(directory, state)
                    continue
            report["providers"][name] = {}
            for agent in agents:
                result = providers.register_connector(home, directory, agent, name, expected, deps["hosts"].get(agent), runner=run)
                report["providers"][name][agent] = result
                report["ok"] &= result["configured"]
            state.setdefault("connectors", {})[name] = {"expected": expected, "hosts": report["providers"][name],
                "manifest_version": providers.catalog()["manifest_version"], "server_rollback": profile["server_rollback"]}
            save_state(directory, state)
        if aiediting and "aiediting" not in state["components"]:
            try:
                with tempfile.TemporaryDirectory(prefix="family-editing-", dir=directory) as temporary:
                    source = Path(temporary) / "aiediting"
                    identity = {**packages.fetch_package("aiediting", source), "origin_status": "verified"}
                    pending = copy.deepcopy(state)
                    def publish(receipt):
                        pending["components"]["aiediting"] = receipt
                        save_state(directory, pending)
                    packages.install_package(source, "aiediting", directory, home, agents, identity=identity, publish=publish)
                    state = pending
                    report["components"]["aiediting"] = {"status": "installed", "installed": True}
            except (OSError, ValueError) as error:
                report["components"]["aiediting"] = {"status": "install_failed", "installed": False,
                                                       "reason": type(error).__name__}
                report["ok"] = False
        state["setup_at"] = now()
        save_state(directory, state)
        report["status"] = "auth_pending" if report["ok"] else "partial"
        report["next_step"] = "Restart the host, complete OAuth in the host, then discover tools in the new session."
        return report


def status(state_dir):
    from ..host_launch import resolve
    state = read_state(state_dir)
    result = {"schema_version": 1, "auto_update": state["auto_update"], "components": {}, "providers": {},
              "last_check": state.get("last_check")}
    for name, entry in state["components"].items():
        path = Path(entry.get("package", "/nonexistent"))
        clean = path.is_dir()
        if clean and entry.get("fingerprint"):
            clean = packages.digest_tree(path) == entry["fingerprint"] and all(
                Path(target).is_dir() and packages.digest_tree(Path(target).resolve()) == entry["fingerprint"]
                for target in entry.get("targets", []))
        result["components"][name] = {"installed": clean, "status": "installed" if clean else "missing_or_changed",
                                      "revision": entry.get("revision"), "origin_status": entry.get("origin_status")}
    for name, connector in state.get("connectors", {}).items():
        result["providers"][name] = {}
        for agent in state.get("agents", []):
            try:
                _, config = providers.read_config(state["home"], agent)
                configured = providers.matches(providers._entry(config, agent, name), connector["expected"])
            except (OSError, ValueError):
                configured = False
            # Configuration and old discovery evidence never establish current auth.
            result["providers"][name][agent] = {"configured": configured, "host_installed": bool(resolve(agent, state_dir=state_dir)), "authenticated": False,
                "available": False, "status": "discovery_required" if configured else "needs_setup"}
    return result

"""One explicit workspace controller, shared with Telegram and family updates."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
import uuid

from . import authoring
from .family_setup import default_state_dir, operation_lease, register_workspace, OperationBusy
from .family_setup.state import write_json
from .operator_adapters import AdapterFailure, HostAdapter, RESULT_SCHEMA, state_digest
from .platform_compat import file_lock, open_text_nofollow
from .runner import open_runner, CHAT_ACTION_TYPES
from .ledger import ActionRequest, TERMINAL_STATUSES
from .workspace import resolve_workspace_paths
from .version_history import version_ids

SKILL_ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT_SECONDS = 2
STALE_SECONDS = 15


def package_fingerprint(skill=SKILL_ROOT):
    """Includes executable source: same VERSION with changed code is not the same runtime."""
    root = Path(skill)
    digest = hashlib.sha256()
    for path in sorted([root / "SKILL.md", root / "VERSION", *root.glob("studio/**/*.py"),
                        *root.glob("scripts/creator_studio*.py")]):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def family_fingerprint(state_dir=None):
    """Detect atomic package/pointer switches even while the old checkout remains."""
    from .family_setup.state import read_state
    state = read_state(Path(state_dir or default_state_dir()))
    identities = {name: {key: component.get(key) for key in
        ("fingerprint", "revision", "selected_revision", "selected_runtime_sha256")}
        for name, component in state["components"].items() if isinstance(component, dict)}
    return state_digest(identities)


def _private(workspace):
    root, _, _, private = resolve_workspace_paths(workspace)
    if private.is_symlink() or not private.resolve().is_relative_to(root):
        raise ValueError("unsafe private workspace directory")
    return private


def _read(path):
    try:
        if path.is_symlink():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def status(workspace):
    private = _private(workspace)
    data = _read(private / "operator.json")
    offline = {"available": False, "agent": None, "status": "offline",
               "active_action_id": None, "last_seen_at": None}
    if not data or data.get("agent") not in {"codex", "claude"}:
        return offline
    live = False
    try:
        with open_text_nofollow(private / "operator.lock") as handle:
            with file_lock(handle, blocking=False):
                pass
    except OperationBusy:
        live = time.time() - data.get("heartbeat", 0) < STALE_SECONDS
    except OSError:
        pass
    if not live:
        return {**offline, "agent": data["agent"], "last_seen_at": data.get("last_seen_at")}
    changed = data.get("fingerprint") != package_fingerprint() or \
        data.get("family_fingerprint") != family_fingerprint(data.get("family_state_dir"))
    ready = data.get("status") in {"ready", "busy"} and not changed
    result = {"available": ready, "agent": data["agent"],
              "status": "needs_setup" if changed else data.get("status", "needs_setup"),
              "active_action_id": data.get("active_action_id"), "last_seen_at": data.get("last_seen_at")}
    if changed:
        result["reason"] = "restart_required"
    return result


def stop(workspace):
    private = _private(workspace)
    data = _read(private / "operator.json")
    if status(workspace)["status"] == "offline":
        return {"status": "offline"}
    # A cooperative request is bound to this lease, never kill an arbitrary/reused PID.
    write_json(private / "operator-stop.json", {"lease_id": data.get("lease_id")})
    return {"status": "stopping"}


def fallback_request(action):
    return "Continue AIMaster canonical project using this exact action context; inspect its current ledger status and reconcile unknown outcomes before any paid call:\n" + json.dumps(
        {key: action[key] for key in ("action_id", "project_id", "revision", "action_type", "target_id")}, ensure_ascii=False)


def _ids(items, key):
    return {item.get(key): item for item in items if isinstance(item, dict) and item.get(key)}


def verify_result(job, result, before, after, workspace):
    """Independently validate identity, revision, exact semantic outputs and actual media."""
    if not isinstance(result, dict) or not set(RESULT_SCHEMA["required"]) <= set(result) <= set(RESULT_SCHEMA["properties"]):
        raise AdapterFailure(reason="host_result_schema")
    for key in ("action_id", "project_id", "action_type", "target_id"):
        if result[key] != job[key]:
            raise AdapterFailure(reason="result_identity")
    if type(result["revision"]) is not int or type(result["base_revision"]) is not int or \
            result["base_revision"] != job["revision"] or result["revision"] != after["revision"] or \
            before["revision"] != job["revision"]:
        raise AdapterFailure(reason="result_revision")
    if result["state_sha256"] is not None and result["state_sha256"] != state_digest(after):
        raise AdapterFailure(reason="result_state_hash")
    if result["status"] not in RESULT_SCHEMA["properties"]["status"]["enum"]:
        raise AdapterFailure(reason="result_status")
    if not isinstance(result["output_ids"], list) or not all(isinstance(x, str) for x in result["output_ids"]) or \
            not isinstance(result["reply"], str) or not result["reply"].strip():
        raise AdapterFailure(reason="result_outputs")
    kind = job["action_type"]
    if kind in {"generate", "vary", "regenerate"}:
        # A child's prose or direct authoring cannot prove parent collection.
        # Only the separate validated receipt/collector path may promote this.
        return "outcome_unknown"
    if result["status"] != "succeeded":
        if result["status"] == "provider_completed":
            raise AdapterFailure(reason="result_status")
        return result["status"]
    output = set(result["output_ids"])
    if after != before:
        previous = before.get("history", [])
        history = after.get("history", [])
        if after["revision"] <= before["revision"] or not isinstance(history, list) or \
                history[:len(previous)] != previous or len(history) <= len(previous):
            raise AdapterFailure(reason="result_history")
    if kind == "continue-in-chat":
        # Read-only/meta-only work needs no invented output. Authoring must name
        # every actual new version, not an old existing ID or a claimed one.
        if output != version_ids(after) - version_ids(before):
            raise AdapterFailure(reason="result_semantic_outputs")
        return "succeeded"
    if after["revision"] <= before["revision"]:
        raise AdapterFailure()
    if kind in {"prompts-generate", "prompt-refresh"}:
        collections = ("image_prompts", "motion_prompts", "audio_prompts")
        old = _ids([item for name in collections for item in before.get(name, [])], "version_id")
        new = _ids([item for name in collections for item in after.get(name, [])], "version_id")
        changed = {key for key in new if new[key] != old.get(key)}
        if not output or output != changed:
            raise AdapterFailure()
        from .domain_positions import current_prompt_spec
        from .domain import compute_prompt_stale
        for key in output:
            collection = next(name for name in collections if new[key] in after.get(name, []))
            spec = current_prompt_spec(after, collection, new[key])
            if compute_prompt_stale(after, new[key], spec) or not new[key].get("text", "").strip():
                raise AdapterFailure()
            if kind == "prompt-refresh" and job["target_id"] not in {spec["position_id"], spec.get("scene_id")}:
                raise AdapterFailure()
    elif kind == "revise-scenario":
        old = _ids(before.get("script", {}).get("versions", []), "version_id")
        new = _ids(after.get("script", {}).get("versions", []), "version_id")
        if not output or output != set(new) - set(old):
            raise AdapterFailure()
    elif kind == "assemble":
        assembly = after.get("assembly", {})
        if assembly == before.get("assembly") or assembly.get("status") != "ready":
            raise AdapterFailure()
        if assembly.get("kind") == "materials":
            from .completion import verify_assembly
            verify_assembly(after, authoring.open_store(workspace).project_dir(job["project_id"]))
            expected = set(assembly.get("asset_ids", []))
        else:
            expected = {assembly.get("asset_id")}
            authoring.open_assets(workspace).resolve(assembly["asset_id"])
        if output != expected:
            raise AdapterFailure()
    else:
        raise AdapterFailure()
    return "succeeded"


class Operator:
    def __init__(self, workspace, *, agent, adapter=None, state_dir=None, model=None):
        if agent not in {"codex", "claude"}:
            raise ValueError("unsupported agent")
        self.workspace, _, _, self.private = resolve_workspace_paths(workspace)
        self.private = _private(self.workspace)
        self.agent = agent
        self.state_dir = Path(state_dir or default_state_dir())
        self.adapter = adapter or HostAdapter(agent, model=model, state_dir=self.state_dir)
        self.injected = adapter is not None
        self.runner = open_runner(self.workspace)
        self.identity = "operator-" + uuid.uuid4().hex
        self.fingerprint = package_fingerprint()
        self.family_fingerprint = None
        self._stack = ExitStack()
        self._stop = threading.Event()
        self._mutex = threading.Lock()
        self._status, self._active = "ready", None
        self._opened = False
        self._telegram = None

    def _telegram_state(self):
        if self._telegram is None and (self.private / "telegram_bot.sqlite3").is_file():
            from .telegram_bot import TelegramBotState
            self._telegram = TelegramBotState(self.private / "telegram_bot.sqlite3")
        return self._telegram

    def _inbox(self):
        """The Telegram inbox is transport only; its execution is an ordinary ledger action."""
        state = self._telegram_state()
        if state is None:
            return
        items = state.processing_inbox()
        new = state.dequeue_inbox()
        if new:
            items.append(new)
        for item in items:
            if item["workspace"] != str(self.workspace):
                state.complete_inbox(item["id"], "outcome_unknown", "Workspace selection changed; select the project again.")
                continue
            action = None
            if item.get("action_id"):
                action = self.runner.ledger.get_action(item["action_id"])
            else:
                # Reconcile a crash after enqueue and before link through the transport key.
                action = self.runner.ledger.action_by_key(item["project_id"], item["idempotency_key"])
                if action is None:
                    current = self.runner.store.load(item["project_id"])
                    from .domain import derive_view_stage
                    revision = item.get("expected_revision")
                    if revision is not None and revision != current["revision"]:
                        state.complete_inbox(item["id"], "outcome_unknown", "Проект изменился. Проверьте состояние и отправьте новый запрос.")
                        continue
                    action = self.runner.ledger.enqueue(item["project_id"], ActionRequest("continue-in-chat",
                        derive_view_stage(current)["current_stage"], {"text": item["text"],
                        "attachments": json.loads(item.get("attachments_json") or "[]")},
                        current["revision"], item["idempotency_key"]))
                state.link_inbox_action(item["id"], action["action_id"])
            if action["status"] in TERMINAL_STATUSES:
                receipt = _read(self.private / "operator-results" / (action["action_id"] + ".json"))
                text = receipt.get("reply") or "Исход действия не подтверждён; автоматического повтора не было."
                state.complete_inbox(item["id"], "done" if action["status"] == "succeeded" else "outcome_unknown", text)

    def __enter__(self):
        # Registration takes the shared family lock itself, so it precedes any job lease.
        register_workspace(self.workspace, state_dir=self.state_dir)
        self.family_fingerprint = family_fingerprint(self.state_dir)
        try:
            handle = self._stack.enter_context(open_text_nofollow(self.private / "operator.lock"))
            self._stack.enter_context(file_lock(handle, blocking=False))
            self._opened = True
            previous = _read(self.private / "operator.json")
            if previous.get("lease_id"):
                with operation_lease(self.state_dir, self.identity):
                    self.runner.ledger.recover_inflight(lambda action: {"status": "outcome_unknown"},
                        action_types=CHAT_ACTION_TYPES, worker_id=previous["lease_id"])
            from .host_launch import resolve
            if not self.injected and not resolve(self.agent, state_dir=self.state_dir):
                self._status = "needs_setup"
            self._heartbeat()
            self._thread = threading.Thread(target=self._pulse, daemon=True)
            self._thread.start()
            return self
        except BaseException:
            self._stack.close()
            raise

    def _heartbeat(self):
        with self._mutex:
            write_json(self.private / "operator.json", {"lease_id": self.identity, "pid": os.getpid(),
                "agent": self.agent, "status": self._status, "active_action_id": self._active,
                "fingerprint": self.fingerprint, "heartbeat": time.time(),
                "family_fingerprint": self.family_fingerprint, "family_state_dir": str(self.state_dir),
                "last_seen_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    def _pulse(self):
        while not self._stop.wait(HEARTBEAT_SECONDS):
            self._heartbeat()

    def stopping(self):
        return self._stop.is_set() or _read(self.private / "operator-stop.json").get("lease_id") == self.identity

    def step(self):
        if not self._opened:
            raise RuntimeError("operator must hold its controller lease")
        if self.stopping():
            return None
        if self.fingerprint != package_fingerprint() or self.family_fingerprint != family_fingerprint(self.state_dir):
            self._status = "needs_setup"
            self._heartbeat()
            return None
        if self._status == "needs_setup":
            return None
        with operation_lease(self.state_dir, self.identity):
            self._inbox()
            job = self.runner.claim(self.identity)
            if job is None:
                return None
            self._status, self._active = "busy", job["action_id"]
            self._heartbeat()
            finished = None
            verified_output_ids = None
            diagnostic = {"reason": "none"}
            reply = "Исход действия не подтверждён; проверьте сохранённое состояние. Автоматического повтора не было."
            phase = "host"
            try:
                before = self.runner.store.load(job["project_id"])
                if before["revision"] != job["revision"]:
                    return self.runner.ledger.finish_and_release_grant(job["action_id"], "failed", {"status": "failed"})
                if job["action_type"] in {"generate", "vary", "regenerate"}:
                    from .operator_routes import selected_route, uncertain_position, RouteUnavailable
                    try:
                        if uncertain_position(self.runner.ledger, before, job["action_type"], job["target_id"]):
                            return self.runner.ledger.finish_and_release_grant(job["action_id"], "needs_chat", {"status": "needs_chat"})
                        route = selected_route(self.workspace, before, job["action_type"], job["target_id"])
                        from .provider_download import preflight
                        if not preflight(route):
                            raise RouteUnavailable("original collection capability is not established for this provider")
                        spending = job["untrusted_input"]["payload"].get("spending")
                        if before["project"].get("mode") != "autopilot" and spending != {
                            "confirmed": True, **{key: route[key] for key in ("route_id", "provider", "model")}}:
                            raise RouteUnavailable("route confirmation no longer matches")
                    except (ValueError, OSError):
                        return self.runner.ledger.finish_and_release_grant(job["action_id"], "needs_chat_setup", {"status": "needs_chat_setup"})
                    job["execution_route"] = route
                    from .provider_receipts import freeze
                    freeze(self.workspace, self.runner, job["action_id"], before, route)
                result = self.adapter(job, self.workspace, SKILL_ROOT)
                phase = "result_validation"
                after = self.runner.store.load(job["project_id"])
                final = verify_result(job, result, before, after, self.workspace)
                if final == "succeeded":
                    verified_output_ids = sorted(set(result["output_ids"]))
                from .agent_bridge import _sanitize_output
                reply = _sanitize_output(result["reply"])[:12000]
                if final != "succeeded":
                    diagnostic = {"reason": "paid_receipt_missing" if job["action_type"] in {"generate", "vary", "regenerate"}
                                  else "host_reported_status", "reported_status": result["status"]}
                if result.get("provider_receipt") is not None:
                    if job["action_type"] not in {"generate", "vary", "regenerate"}:
                        raise AdapterFailure()
                    from .provider_collection import record, reconcile, public
                    phase = "provider_receipt"
                    record(self.workspace, self.runner, job["action_id"], result["provider_receipt"], operation_locked=True)
                    if before != after or result["output_ids"]:
                        # Keep the provider ID and child-created evidence, but
                        # never adopt direct child mutations as collected success.
                        finished = public(self.runner, job["action_id"])
                        diagnostic = {"reason": "paid_child_mutation"}
                    else:
                        phase = "collection"
                        try:
                            finished = reconcile(self.workspace, self.runner, job["action_id"], operation_locked=True)
                            diagnostic = {"reason": "none" if finished["status"] == "succeeded" else "collection_blocked"}
                        except ValueError:
                            finished = public(self.runner, job["action_id"])
                            diagnostic = {"reason": "collection_blocked"}
                    final = finished["status"]
                    after = self.runner.store.load(job["project_id"])
            except AdapterFailure as error:
                diagnostic = error.diagnostic
                final = error.code if error.code in {"needs_chat_setup", "outcome_unknown"} else "outcome_unknown"
                if self.runner.ledger.get_action(job["action_id"])["external_id"] is not None:
                    final = "outcome_unknown"
            except Exception:
                # Any post-dispatch uncertainty consumes the grant and is never replayed.
                final = "outcome_unknown"
                diagnostic = {"reason": "provider_receipt_invalid" if phase == "provider_receipt" else
                              "collection_internal_failure" if phase == "collection" else "unexpected_internal_failure"}
            finally:
                self._active, self._status = None, "ready"
            if finished is None:
                if self.runner.ledger.collection(job["action_id"]) is not None:
                    from .provider_collection import public
                    finished = public(self.runner, job["action_id"])
                else:
                    finished = self.runner.finish(job["action_id"], final, {})
            observed = self.runner.store.load(job["project_id"])
            write_json(self.private / "operator-results" / (job["action_id"] + ".json"),
                {"action_id": job["action_id"], "project_id": job["project_id"], "revision": observed["revision"],
                 "state_sha256": state_digest(observed), "status": finished["status"], "reply": reply,
                 "diagnostic": diagnostic,
                 **({"verified_output_ids": verified_output_ids} if verified_output_ids is not None and finished["status"] == "succeeded" else {})})
            if final == "needs_chat_setup":
                self._status = "needs_setup"
            self._inbox()
            self._heartbeat()
            return finished

    def __exit__(self, *exc):
        self._stop.set()
        if hasattr(self, "_thread"):
            self._thread.join(timeout=5)
        self._status, self._active = "offline", None
        self._heartbeat()
        self._opened = False
        self._stack.close()

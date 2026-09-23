"""Operator bridge between the durable action ledger and the chat agent.

`Runner` never calls a provider, never imports a vendor SDK, never holds a
credential and never makes a hidden live request. It only claims
chat-only actions from the durable ledger, hands the chat agent a
provider-neutral job package (`adapters.build_job_package`), and records
whatever terminal outcome the chat reports back through `finish`.
Confirming that a technical route is actually reachable right now is the
chat agent's job — see `adapters.load_capability_candidates`.

Repair, 2026-09-16 (ticket 09, condition 1): this module used to also own
`EventLog`, a second durable journal that `claim`/`finish`/`recover` wrote
to *after* the matching ledger call already committed. That shape has two
holes: a crash between the two writes drops the event forever, and a
browser `POST /api/actions` (handled by `http_app.StudioApplication`
directly against `ActionLedger.enqueue`) never touched `EventLog` at all,
so the very first "queued" transition of an action was never observable.
`ActionLedger` already appends one `action_events` row inside the *same*
SQLite transaction as every status transition, so that table is already
the atomic, durable source of truth for "what changed and when" — the
event source now reads it directly; see `studio/events.py`. `Runner` no
longer writes events of any kind.

Repair, 2026-09-17 (ticket 15 repair, remaining race window): `claim` now
also holds a `ProjectStore` — not only the ledger. `decision_stages.
build_reopen_mutation` already refuses a `reopen-scenario` while anything
is `queued`/`running` for the project, re-checked *inside*
`ProjectStore.transact`'s own file lock. But `ActionLedger.enqueue`'s own
revision check reads `store.load(project_id)["revision"]` — a plain,
unlocked read — so a `vary`/`regenerate` `enqueue` that lands *after*
that check already passed, but before the reopen's own write reaches
disk, still sees the pre-reopen revision and commits: a paid action
`queued` for a stage the reopen just hid, with nothing in
`decision_stages` ever having seen it. `claim` is the last gate before
such an action would reach chat and execute for money against a stage
nobody can see any more — see its own docstring and `_claim_is_current`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from .adapters import (
    CapabilityCandidate,
    build_job_package,
    load_capability_candidates,
    validate_public_result,
)
from .autopilot import StoreAutopilotPolicy, autopilot_grant_still_valid
from .domain import DomainValidationError, _stage_sequence, derive_view_stage
from .ledger import GRANT_REQUIRED_ACTIONS, ActionLedger, normalize_recovery_decision
from .projection import ProjectionError, action_target_stage
from .store import ProjectStore, StoreError
from .workspace import ACTIONS_DB_NAME, resolve_workspace_paths

# `claim_next`'s two disjoint queues (repair, 2026-09-16, ticket 09 point 5).
# The chat runner claims exactly this set; everything else in
# `ledger.ACTION_TYPES` is a decision, claimed by ticket 11's own in-process
# worker.
#
# Comment corrected twice now to name precisely what guards this frozenset
# (third repair, condition 5; second attempt, condition 6 — the prior
# wording overclaimed what the partition test catches). Two tests, two
# different kinds of drift, neither a substitute for the other:
# `test_chat_and_decision_action_types_exactly_partition_all_action_types`'s
# union/intersection checks *do* catch a type landing outside
# `ACTION_TYPES` (the union would then hold an element `ACTION_TYPES`
# itself lacks) and *do* catch this frozenset swallowing every type,
# leaving the decision side empty (`assertTrue(decision_types)` fails). What
# they cannot catch is a type simply moving from the decision side to this
# one while `ACTION_TYPES` membership as a whole is unchanged — subtracting
# a re-partitioned `CHAT_ACTION_TYPES` from `ACTION_TYPES` still satisfies
# both checks no matter which non-empty, proper subset it names. That
# specific drift — an accidental edit that keeps every type *somewhere* but
# moves it to the wrong queue — is what
# `test_chat_action_types_is_exactly_the_documented_literal_set` catches,
# by comparing against a hardcoded literal instead of a derived set.
CHAT_ACTION_TYPES = frozenset({"vary", "regenerate", "generate", "prompts-generate", "prompt-refresh", "assemble", "revise-scenario", "continue-in-chat"})


def _default_recovery_verifier(_action: dict) -> dict:
    """Conservative default for a one-shot, non-interactive `recover` call.

    A CLI invocation has no live channel to ask a provider what actually
    happened to an in-flight action, so the only safe report for every
    running action it finds is `outcome_unknown` — never a guessed
    success, and never an automatic retry (spec §9).
    """

    return {"status": "outcome_unknown"}


class Runner:
    """Operator-only claim/finish/recover bridge; no embedded provider call."""

    def __init__(self, ledger: ActionLedger, *, store: ProjectStore, profile_path=None):
        self.ledger = ledger
        # Repair, 2026-09-17 (ticket 15 repair, remaining race window):
        # required, not optional — `claim`'s own stage gate
        # (`_claim_is_current`) has no meaningful "skip" mode. `store` is
        # read-only here, exactly like the ledger's own
        # `revision_resolver`: `claim` only ever calls `store.load`.
        self.store = store
        self.profile_path = Path(profile_path) if profile_path is not None else None

    def _candidates(self) -> tuple[CapabilityCandidate, ...]:
        # A missing profile just means "nothing configured yet" — an empty
        # candidate list, which chat correctly reads as "offer setup". A
        # profile that exists but fails to parse is a real defect and
        # should raise loudly rather than silently degrade to empty.
        if self.profile_path is None or not self.profile_path.exists():
            return ()
        return load_capability_candidates(self.profile_path)

    def claim(self, worker_id: str) -> dict | None:
        """Claim the oldest queued chat-only action ready for its stage,
        and package it for chat.

        Returns `None` when nothing is claimable. The candidates embedded
        in the package are declared, not verified — see
        `adapters.CapabilityCandidate`.

        Repair, 2026-09-16 (condition 9): the capability profile is loaded
        and validated *before* `claim_next` ever runs. The old order
        called `claim_next` first (moving the action `queued -> running`)
        and only then read the profile — a malformed profile file raised
        after the claim already happened, stranding the action in
        `running` forever with nothing left to finish it. Loading first
        means a `ProfileError` here never touches the ledger: the action
        stays `queued` and a later `claim` can try again once the profile
        is fixed.

        Repair, 2026-09-17 (ticket 15 repair, remaining race window — see
        this module's own docstring): `claim_next` moves an action
        `queued -> running` on the ledger's own say-so alone, which can
        be stale the moment a stage-hiding `reopen-scenario` has since
        committed (`_claim_is_current`'s own docstring has the full
        mechanics). Every claimed action is re-checked against a *fresh*
        `self.store.load` before it is ever packaged — never silently
        dropped, and never hand-rolled into a second, ad hoc terminal
        write — and the loop moves on to the next queued chat action
        instead of returning early, so one stale action can never block a
        fresh one queued behind it.

        Second repair, поправка оркестратора 12: a read or validation
        failure *inside* the gate itself (a corrupt or unreadable
        project, `derive_view_stage` refusing malformed milestones) is
        exactly as disqualifying as a stage a reopen has since hidden —
        nothing has been dispatched to chat either way, so both are
        refused through the one same path, `_refuse_claim`, rather than
        letting the exception propagate and leave the action stranded
        `running` forever with nothing left to finish it (`claim_next`
        already moved it out of `queued` by this point, so there is no
        "just leave it be" option). `_refuse_claim` also releases this
        action's own reserved grant, if it had one — a `vary`/
        `regenerate` refused here never reached the external call that
        grant authorized, so the one-use authorization was never actually
        spent (spec §5's own "grant атомарно резервируется до внешнего
        вызова").

        Third pass (craft review): "a read or validation failure" above
        used to mean *any* `Exception` whatsoever — a genuine bug inside
        `_claim_is_current` itself (or anything it calls) was
        indistinguishable from the legitimate refusals this gate was
        written for, silently finished every affected chat action
        `failed`, and the real cause was never recorded anywhere a
        caller could see it. Only `StoreError` (`self.store.load` — a
        corrupt or unreadable project), `DomainValidationError`
        (`derive_view_stage` refusing malformed milestones) and
        `ProjectionError` (`action_target_stage`'s own collection reads
        — defensive; nothing it inspects today can actually make it
        raise, since every value already passed through `_sanitize_*`
        or the durable ledger's own validation first) are genuinely
        read-or-validate-this-project's-state failures in the sense
        `_claim_is_current`'s own docstring means; those three alone are
        still treated as a refusal. Anything else is a defect in the
        gate's own code, not a fact about this action or project, and
        must not vanish the same way — it is *not* swallowed here, but
        the action still cannot be left `running` either (nothing was
        ever dispatched to chat, so nothing else could ever finish it):
        `_refuse_claim` still runs first, exactly as for the three known
        cases, and only then is the exception re-raised, so it surfaces
        to whatever called `claim` instead of disappearing as a quiet
        `failed` result with no trace of what actually went wrong.
        """

        candidates = self._candidates()
        while True:
            action = self.ledger.claim_next(worker_id, action_types=CHAT_ACTION_TYPES)
            if action is None:
                return None
            try:
                state = self.store.load(action["project_id"])
                state["actions"] = self.ledger.pending_actions(action["project_id"], exclude_action_id=action["action_id"])
                current = self._claim_is_current(action, state=state)
                if current and not autopilot_grant_still_valid(self.ledger, action, state):
                    # Critic finding 1: a self-issued autopilot grant is only
                    # good while the project is still in autopilot. Refused
                    # here, the grant is voided, never released.
                    current = False
                from .runner_context import (
                    CONTEXT_ACTION_TYPES,
                    build_action_context,
                    require_existing_video_action_continuity,
                )
                if current and action["action_type"] in {"vary", "regenerate"}:
                    require_existing_video_action_continuity(state, action["target_id"])
                context = build_action_context(state, action) if current and action["action_type"] in CONTEXT_ACTION_TYPES else None
            except (StoreError, DomainValidationError, ProjectionError):
                current = False
            except Exception:
                self._refuse_claim(action)
                raise
            if not current:
                self._refuse_claim(action)
                continue
            action_candidates = (
                candidates if action["action_type"] in GRANT_REQUIRED_ACTIONS else ()
            )
            return build_job_package(action, candidates=action_candidates, context=context)

    def _refuse_claim(self, action: dict) -> dict:
        """Finish a claimed-but-refused `action` `failed`, releasing its
        own reserved grant along the way (ticket 15 repair, поправка
        оркестратора 12) — never through `finish`/`ActionLedger.finish`
        alone, which leaves a grant reservation exactly as it found it:
        correct once a job package really did reach chat (the grant *was*
        spent by that attempt, regardless of what chat later reports),
        wrong here, where the external call this grant authorized never
        happened at all.
        """

        validated = validate_public_result("failed", {})
        return self.ledger.finish_and_release_grant(action["action_id"], "failed", validated)

    def _claim_is_current(self, action: dict, *, state=None) -> bool:
        """Whether a freshly claimed `action` still belongs to the
        project's live stage, read straight from `self.store` — never the
        revision the ledger recorded when it was enqueued (see `claim`'s
        own and this module's docstring for why that can no longer be
        trusted alone once a reopen may have raced it).

        May raise (a corrupt/unreadable project via `self.store.load`, a
        `DomainValidationError` from `derive_view_stage` on malformed
        milestones) — `claim`'s own caller treats exactly those, plus
        `ProjectionError`, identically to a `False` return (see its
        docstring, поправка 12 and its own "Third pass" note); anything
        else it re-raises after still resolving the claimed action out
        of `running`. This function itself stays a plain, un-defensive
        read either way: it never needs to guess whether a failure here
        is "recoverable", only to let it propagate.

        Two rules, applied in the same order and against the very same
        `derive_view_stage` result `projection.build_snapshot`'s own
        `snapshot.actions` filter applies to every action it renders —
        this only re-runs that filter for one already-claimed action
        instead of a whole list, sharing its target-stage rule
        (`projection.action_target_stage`) rather than a second,
        independently maintained copy of it:

        1. `action["action_type"]` must be one `derive_view_stage`
           currently lists in `allowed_actions` for the stage the
           project is on *right now*. Alone, this already catches the
           shape the remaining race window produces: a `vary`/
           `regenerate` enqueued for `image_results`/`motion` that
           `claim` only reaches after a `reopen-scenario` has since put
           the project back on `scenario`, where neither is ever
           allowed. This rule is intentionally wide, not narrowed to only
           the reopen's own shape (поправка оркестратора 12: a decision
           applies the identical `ensure_action_allowed` check, so the
           two claimable queues never disagree about what the *current*
           stage permits) — `revise-scenario` enqueued before an ordinary
           `approve-scenario`, with no reopen involved at all, is refused
           here exactly the same way once that approval has landed.
        2. `action["target_id"]` must not positively resolve, through
           `action_target_stage`, to a stage the project has not (or no
           longer) reached. This is what catches the type/stage
           combinations rule 1 cannot: an action type such as
           `continue-in-chat`, valid at nearly every stage on its own,
           whose target still names a card or milestone from a stage the
           live stage has left behind. `action_target_stage` returning
           `None` (unresolved) is never treated as a refusal — see that
           function's own docstring for why an id it cannot place is not
           evidence of anything.
        """

        state = self.store.load(action["project_id"]) if state is None else state
        view = derive_view_stage(state)
        if action["action_type"] not in view["allowed_actions"]:
            return False
        sequence = _stage_sequence(state)
        reached_stages = set(view["completed_stages"]) | {view["current_stage"]}
        target_stage = action_target_stage(
            state, action["action_type"], action["target_id"], sequence
        )
        if target_stage is None:
            return True
        return target_stage in reached_stages

    def finish(self, action_id: str, status: str, public_result: dict, external_id=None) -> dict:
        """Record the chat-reported terminal outcome for one claimed action.

        Canonicalizes `public_result` *before* calling `ActionLedger.finish`
        — status forced, and every field but `status` refused outright, not
        sanitized — so a malformed or provider/price/path-carrying result
        never becomes a stored, broadcastable terminal action. See
        `adapters.validate_public_result` for why nothing the caller writes
        is trusted, not even something shaped like a plain id.
        """

        validated = validate_public_result(status, public_result)
        return self.ledger.finish(action_id, status, validated, external_id=external_id)

    def recover(self, verifier: Callable[[dict], dict] | None = None) -> list[dict]:
        """Resolve every in-flight action after a restart; never retries silently.

        Without an explicit `verifier` (the CLI's case — see
        `_default_recovery_verifier`), every running action becomes
        `outcome_unknown`. Tests may supply a verifier that proves an
        action was never started (safe requeue) or genuinely finished
        (terminal, with its real external id).

        Repair, 2026-09-16 (condition 4, and ticket 09 third repair,
        condition 4 again): whatever the verifier reports is canonicalized
        through the exact same `validate_public_result` as `finish` —
        rejecting every field but `status` outright — before
        `ActionLedger.recover_inflight` ever writes it; a verifier is
        exactly as untrusted a source as a chat `finish` call, so it gets
        the same treatment. `normalize_recovery_decision` (shared with
        `recover_inflight` itself, so a string/non-dict/non-terminal-status
        decision is interpreted identically in both places) is what lets
        this wrapper safely inspect `status` before deciding whether to
        validate at all.

        Third repair, 2026-09-16 (condition 2): a `PublicResultError` this
        wrapper raises here is no longer this method's problem to catch —
        `ActionLedger.recover_inflight` isolates a raise to the one action
        it came from (nothing written, left `running`) and keeps recovering
        every other in-flight action instead of aborting the whole pass.
        Second attempt, 2026-09-16 (condition 3): that same refusal path now
        also catches a `public_result` the verifier *did* supply but with
        the wrong type — see the comment inside `validated_verifier` below
        for why that used to slip through instead of being refused. Every
        refusal this wrapper's raise triggers — for any reason — also now
        carries a `refusal` marker in what `recover_inflight` returns
        (condition 4), and is re-read fresh from the database rather than
        handed back as the snapshot taken before the attempt (condition 5);
        both live entirely in `ActionLedger.recover_inflight`, not here.
        """

        real_verifier = verifier or _default_recovery_verifier

        def validated_verifier(action: dict) -> dict:
            decision = normalize_recovery_decision(real_verifier(action))
            status = decision["status"]
            if status == "not_started":
                # Requeue path: `ActionLedger._requeue_recovered` never
                # reads `public_result`, so there is nothing to canonicalize.
                return decision
            # Repair, 2026-09-16 (ticket 09, second attempt, condition 3): a
            # `public_result` the verifier omitted entirely (no such key in
            # `decision`) still defaults to `{}` — matching a real `finish`
            # call, whose caller always passes an empty object for "no
            # result". But a `public_result` the verifier DID include, with
            # the wrong type, used to be silently swapped for that same
            # `{}` too (`raw_public_result if isinstance(..., dict) else
            # {}`), which made the two cases indistinguishable: a verifier
            # reporting `public_result: "oops"` was treated exactly like one
            # that supplied nothing, and the action quietly finished as
            # `succeeded` with the generic canonical message — the identical
            # "silent `{}` plus recorded success" that `finish` itself has
            # always refused outright for the very same bad shape. Passing
            # through whatever the verifier actually supplied (or `{}` only
            # when the key is genuinely absent) lets `validate_public_result`
            # raise for a wrong type exactly like `finish` does; the raise
            # is isolated to this one action by
            # `ActionLedger.recover_inflight`, never swallowed here.
            if "public_result" in decision:
                raw_public_result = decision["public_result"]
            else:
                raw_public_result = {}
            canonical = validate_public_result(status, raw_public_result)
            result = {"status": status, "public_result": canonical}
            if "external_id" in decision:
                result["external_id"] = decision["external_id"]
            return result

        return self.ledger.recover_inflight(validated_verifier)


def open_ledger(workspace) -> ActionLedger:
    # Repair, 2026-09-16 (ticket 09 second repair, condition 5):
    # `resolve_workspace_paths` and the `actions.sqlite3` filename used to
    # be defined in this module; both now live in `studio/workspace.py`,
    # which owns the on-disk layout independently of the chat/operator
    # bridge — see that module's docstring. This function is unchanged
    # apart from importing rather than defining them.
    _, project_root, _, private_root = resolve_workspace_paths(workspace)
    store = ProjectStore(project_root, excluded=())
    return ActionLedger(
        private_root / ACTIONS_DB_NAME,
        revision_resolver=lambda project_id: store.load(project_id)["revision"],
        autopilot=StoreAutopilotPolicy(store),
    )


def open_runner(workspace, *, profile_path=None) -> Runner:
    # Repair, 2026-09-17 (ticket 15 repair, remaining race window):
    # `Runner.claim`'s own stage gate (`_claim_is_current`) needs a fresh
    # read of canonical project *state*, not only the bare `revision`
    # integer `open_ledger`'s own `revision_resolver` closure resolves.
    # A second `ProjectStore` pointed at the same `<workspace>/projects`
    # root is exactly as safe as sharing one instance: `ProjectStore`
    # holds no per-instance cache, and `transact`'s file lock
    # (`store.py`'s module-level `_thread_lock`, keyed by resolved path)
    # is shared across every instance regardless of which one calls it.
    _, project_root, _, _ = resolve_workspace_paths(workspace)
    store = ProjectStore(project_root, excluded=())
    return Runner(open_ledger(workspace), store=store, profile_path=profile_path)

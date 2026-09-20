"""In-process worker that applies dashboard decisions to canonical state.

`ledger.ACTION_TYPES` splits into exactly two disjoint sets:
`runner.CHAT_ACTION_TYPES` (claimed by the chat/operator bridge outside
this process) and `DECISION_ACTION_TYPES` below (claimed by
`DecisionWorker`, in this same server process) -- `decision_planners.
PLANNERS` covers `DECISION_ACTION_TYPES` exactly, checked once at import
time. A decision never calls an external provider, never blocks on chat
and never needs a grant: it is a pure, local, synchronous mutation of one
project's `state.json`, applied through `ProjectStore.transact` (the same
atomic, revision-checked write every other caller uses) and finished
through `ActionLedger.finish` with the canonical `{status, message}` shape
`adapters.validate_public_result` produces.

Because nothing here ever calls out to a provider, applying a decision
(`_apply` below) has exactly two outcomes: `succeeded` (the mutation
committed) or `failed` (bad input, an unknown or not-currently-allowed
target, a stage that does not own the collection addressed, or a lost
revision race) -- `_apply` itself never produces `outcome_unknown`, the
status a crash between an external call and recording its result would
need. An unrelated, action-type-unaware recovery path outside this module
(the CLI's `recover` command, backed directly by `ActionLedger.
recover_inflight` with no verifier of its own) can still force a decision
that is still `running` to `outcome_unknown` before this worker's own
`recover()` reaches it -- see `test_recovery_leaves_an_action_already_
forced_to_outcome_unknown_alone` in `tests/creator_studio/test_decisions.py`.

The per-action-type rules that decide *what* a decision does live in
sibling modules: `decision_support` (the shared error type and the
comment/decision-history helpers), `decision_stages` (milestone gating and
`project.status`), `decision_cards` (card/version resolution, scoped to
the stage that owns the collection) and `decision_planners`/
`decision_reorder` (one planner per action type, wired together by
`plan_mutation`). This module owns only the worker itself -- claiming,
applying, crash recovery, wake-on-enqueue and the background thread -- and
is the one public entry point `server.py`/`events.py`/tests import from.

## Crash recovery

`ProjectStore.transact` is atomic and durable on its own (fsync + rename);
the gap this worker defends against is the *next* call, `ledger.finish`,
failing after that commit already landed -- leaving the action stuck
`running` forever, since `claim_next` only ever returns `queued` rows.

Recovery goes through the ledger itself, `ActionLedger.recover_inflight`,
scoped with `action_types=DECISION_ACTION_TYPES` so it only ever touches
this worker's own rows, never a chat action's. `_verify` is the one
verifier it supplies: a running decision whose id already appears in its
own project's `state["applied_action_ids"]` marker is confirmed
`succeeded` (the mutation committed; only `finish` never completed); one
that does not appear is reported `not_started` and `recover_inflight`
returns it to `queued`, where a normal `claim_next`/`_apply` pass applies
it exactly once. `_verify` does not itself catch a `ProjectStore.load`
failure (a corrupt or unreadable project): the raise propagates to
`ActionLedger.recover_inflight`, which isolates it to that one action
alone (left `running`, tagged with a `refusal` reason) and keeps
recovering every other in-flight decision regardless -- see that method's
own docstring in `studio/ledger.py`.

`_apply`'s own mutation records the about-to-finish action's id in
`state["applied_action_ids"]` inside the *same* `store.transact` call as
the mutation itself, so the marker is durable and atomic with it by
construction -- one fsync-and-rename, not a second write that can land (or
fail to land) on its own. Every mutation *appends* its own id through
`decision_receipts.append_applied_marker`, which keeps the shared 64-entry
bounded tail (including a direct chat receipt when one exists): a bounded
window, not a single overwritten id, so that a second decision for the
same project committing before a first one's own crashed `finish` has been
recovered does not erase the first one's marker -- both stay individually
verifiable until recovery has resolved each of them (or the window rolls
past that many further decisions for the same project).

Recovery runs in `start()`, once, before the background thread begins, and
again from inside `_run()`'s loop whenever `drain()` itself raises --
never on every idle tick. An idle `serve()` between decisions costs
exactly the "wait for a wake-up" call below; it neither reads a project's
`state.json` nor queries the ledger for anything beyond `claim_next`'s own
"is anything queued" check.

## Waking up

`_run()`'s loop waits on `wake_event` (a `threading.Event`, defaulted to a
private one this worker owns unless a caller — `server.serve()` — supplies
a shared one) rather than sleeping unconditionally, so a decision enqueued
right after the worker went idle is applied as soon as `_run()` is
scheduled again, not after the next scheduled poll. `poll_interval` (default
0.5s, matching "no more often than once every 0.5s") is only the *fallback*
period `wake_event.wait()` gives up and re-checks anyway, in case a wake-up
was somehow missed; it is never how quickly a normal enqueue is noticed.
`server.serve()` is the one caller that wires an enqueue on
`POST /api/actions` to actually set this event -- see `_WakingLedger`
there. Constructed directly (every test in this build, and any other
caller that does not pass `wake_event`), a `DecisionWorker` still works
correctly, just without that shortcut: `_run()` simply waits out the full
`poll_interval` each time `drain()` finds nothing queued.
"""

from __future__ import annotations

import threading

from .adapters import validate_public_result
from .decision_planners import _DEDICATED_MUTATION_TYPES, PLANNERS, plan_mutation
from .decision_receipts import APPLIED_ACTION_IDS_WINDOW as _APPLIED_ACTION_IDS_WINDOW, append_applied_marker
from .ledger import ACTION_TYPES
from .runner import CHAT_ACTION_TYPES


DECISION_ACTION_TYPES = frozenset(ACTION_TYPES) - CHAT_ACTION_TYPES
# Completeness check: every decision type is covered either by a uniform
# `PLANNERS` entry or by `plan_mutation`'s own `reopen-scenario` special
# case (`_DEDICATED_MUTATION_TYPES` -- see `decision_planners.py`'s
# module docstring for why that one type cannot be a uniform planner). A
# type in neither set would raise at `plan_mutation`'s own
# `PLANNERS.get(...)` lookup, silently, only the first time something
# actually claims it -- this fails loudly instead, at import time.
if set(PLANNERS) | _DEDICATED_MUTATION_TYPES != DECISION_ACTION_TYPES:
    raise RuntimeError(
        "decision_planners.PLANNERS plus _DEDICATED_MUTATION_TYPES must "
        "cover exactly DECISION_ACTION_TYPES"
    )

class DecisionWorker:
    """Claim decision-type actions and apply them to canonical state in-process.

    No agent, no external call: `drain()` is a pure, synchronous
    claim -> mutate -> finish loop a caller (including a test) can run
    deterministically, with no thread and no timing dependency, and no
    recovery of its own -- see `recover()` and the module docstring's
    "Crash recovery" section for where that runs instead. `start()`/
    `stop()` wrap `drain()` in a background thread for `server.serve()` --
    see that module for the wiring.
    """

    def __init__(
        self,
        store,
        ledger,
        *,
        worker_id: str = "decisions",
        poll_interval: float = 0.5,
        wake_event: threading.Event | None = None,
    ):
        self.store = store
        self.ledger = ledger
        self.worker_id = worker_id
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._wake_event = wake_event if wake_event is not None else threading.Event()
        self._thread: threading.Thread | None = None

    def drain(self) -> int:
        """Claim and apply every currently-queued decision; return how many.

        A processed action always ends terminal (`succeeded` or `failed`,
        see `_apply`) -- the count includes both, since one rejected
        decision must not stop the loop from draining the rest. Never
        recovers a crashed action itself; see `recover()`. `stop()` is
        re-checked before every claim, so a `stop()` fired mid-drain leaves
        whatever is still `queued` exactly as it is.
        """

        processed = 0
        while not self._stop_event.is_set():
            action = self.ledger.claim_next(self.worker_id, action_types=DECISION_ACTION_TYPES)
            if action is None:
                return processed
            self._apply(action)
            processed += 1
        return processed

    def recover(self) -> list[dict]:
        """Resolve every decision this worker left `running`, via the ledger.

        See the module docstring's "Crash recovery" section. Scoped to
        `DECISION_ACTION_TYPES` alone -- a chat action's own `running` row
        is never touched here, regardless of how long it has been
        in-flight.
        """

        return self.ledger.recover_inflight(self._verify, action_types=DECISION_ACTION_TYPES)

    def _verify(self, action: dict) -> dict:
        """`ActionLedger.recover_inflight`'s verifier for one running decision.

        `succeeded` once the project's own `applied_action_ids` marker
        already names this action's id (its mutation committed; only
        `finish` never completed); `not_started` otherwise, which
        `recover_inflight` returns to `queued` for a normal `claim_next`/
        `_apply` pass to apply exactly once. Deliberately does not catch a
        `ProjectStore.load` failure itself: letting it propagate hands
        isolation to `recover_inflight`, which leaves just this one action
        `running` (tagged with a `refusal` reason) and keeps recovering
        every other in-flight decision regardless -- including one
        belonging to an unrelated, healthy project whose own state loads
        just fine.
        """

        state = self.store.load(action["project_id"])
        marker = state.get("applied_action_ids")
        if isinstance(marker, list) and action["action_id"] in marker:
            return {
                "status": "succeeded",
                "public_result": validate_public_result("succeeded", {}),
            }
        return {"status": "not_started"}

    def _apply(self, action: dict) -> dict:
        action_id = action["action_id"]
        try:
            # `ledger=self.ledger` is passed unconditionally -- this
            # method never branches on `action["action_type"]` itself
            # (ticket 15 repair, поправка 4: "decisions.py не ветвится по
            # типу действия"). Only `plan_mutation`'s own `reopen-scenario`
            # special case actually reads it; every other action type's
            # planner ignores it exactly as before.
            mutate = plan_mutation(action, ledger=self.ledger)

            def mutate_and_mark(state):
                mutate(state)
                # Durability: written inside the *same* `store.transact`
                # call as the mutation itself, so the marker is atomic
                # with it by construction. The shared helper maintains
                # the bounded marker tail; see the module docstring for
                # why an overwrite is not safe here.
                append_applied_marker(state, action_id)

            self.store.transact(action["project_id"], action["revision"], mutate_and_mark)
            status = "succeeded"
        except Exception:
            # A decision never calls an external provider, so any failure
            # here is already fully known: bad input, an unknown or
            # not-currently-allowed target, or a lost revision race --
            # never `outcome_unknown` (see the module docstring). Caught
            # broadly so one bad action never stops the rest of the queue
            # from draining, including one belonging to an unrelated,
            # broken project.
            status = "failed"
        public_result = validate_public_result(status, {})
        return self.ledger.finish(action_id, status, public_result)

    def _safe_recover(self) -> None:
        """`recover()`, isolated from `start()`/the background loop.

        A workspace-level recovery problem (e.g. `ActionLedger.
        recover_inflight` itself failing in some unexpected way, as
        opposed to the per-action isolation it already provides) must
        never prevent the server from starting up, or the background
        thread from continuing to claim and apply *new* queued decisions
        for other, healthy projects.
        """

        try:
            self.recover()
        except Exception:
            pass

    def start(self) -> None:
        # `start()` checks the tracked thread's own liveness, not merely
        # whether one was ever assigned -- restarts correctly after a
        # `stop()` whose `join` timed out and the old thread has since
        # died, and still refuses while a previous thread is genuinely
        # still alive.
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._safe_recover()
        self._thread = threading.Thread(
            target=self._run, name="creator-studio-decisions", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                processed = self.drain()
            except Exception:
                # Isolation of last resort: a transient failure (e.g. a
                # locked SQLite file) must not permanently kill the
                # background thread. Recovery runs here, not on every
                # idle tick, precisely because this is the one place an
                # action might have been left `running` by whatever just
                # failed.
                processed = 0
                self._safe_recover()
            if not processed:
                self._wake_event.wait(self.poll_interval)
                self._wake_event.clear()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

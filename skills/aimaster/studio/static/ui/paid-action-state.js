// Task 08 repair 1, condition 11 ("состояние платных действий" is its own
// module) implementing repair condition 1 ("Одно платное действие на
// карточку"), the repair's single BLOCKING core.
//
// Two things live here, both pure/network-free:
//
// 1. Reading `vary`/`regenerate`'s own busy/blocked state for one card
//    straight out of `snapshot.actions` (poправка 13's new array) --
//    never out of a prompt/result record's own `status`, which no
//    authoring/decision path ever sets to `queued`/`needs_chat`/
//    `outcome_unknown` in the first place (that vocabulary belongs to the
//    ledger's *action*, not the record). This is the fix for the repair's
//    own diagnosis: "Подписи... берутся из status записи, куда никто не
//    пишет статусы действий."
//
// 2. A durable "this exact request has not been confirmed yet" cache,
//    survivING a lost response, a page reload or a crash mid-flight
//    (condition 1, bullet 5): `idempotency_key`, `payload` and
//    `expected_revision` are captured *before* the network call, so a
//    retry -- whether the operator's own next click or this page's next
//    load -- replays the identical request rather than minting a fresh
//    idempotency key that would reserve a *second* grant. In-memory Map
//    for the fast path, `sessionStorage` (try/catch) so it survives a
//    reload within the same tab -- never `localStorage`: this is a
//    per-tab in-flight marker, not state meant to outlive the tab or
//    follow the operator to a different one.
//
// Client repair 2, 2026-09-17. Two defects in the above, both confirmed
// live by the orchestrator reading the code (not a fresh reviewer pass):
//
// a) `prunePendingRequests` used to clear a pending record the instant
//    *any* ledger entry existed for its `(actionType, targetId)` pair --
//    including a *stale* one already there before this request was even
//    sent (a card with prior `vary` history: the new POST is in flight or
//    was lost, but `snapshot.actions` still only shows the *old*
//    `succeeded` entry because the server has not recorded the new one
//    yet). Clearing on that stale entry let the very next click mint a
//    fresh idempotency key while the first request might still land --
//    two paid actions. The fix: remember `baselineActionId`, the
//    `action_id` already on record for this pair *at the moment this
//    request was minted* (`resolveGrantRequest`), and only ever clear once
//    `snapshot.actions` shows an `action_id` that differs from it
//    (`prunePendingRequests`, `resolveBaselineActionId`).
// b) The busy/blocked state (`resolveGrantRowState`) read `snapshot.actions`
//    alone, so a request that is in flight -- sent, pending record saved,
//    no server response yet at all -- left the ledger with *nothing* for
//    that pair. Both vary and regenerate rendered as ordinary, clickable
//    buttons during that window: a second paid action was one click away.
//    The fix: `resolveGrantCardState` checks the pending cache *first*
//    (`findPendingGrantRequest`) -- while either grant type has an
//    unconfirmed request outstanding, the *other* type is withheld
//    entirely and the pending one renders as a retry-only control
//    (ui/card-forms.js's `buildGrantAction` self-detects the same record).

import { resolveLabel } from "./state.js";

/** The two action types this whole module is scoped to -- every other
 * decision type (approve/reject/hide/...) is free, applied by the
 * decisions worker directly, and never touches this module at all. */
export const GRANT_ACTION_TYPES = Object.freeze(["vary", "regenerate", "generate"]);

/** Russian copy for a `vary`/`regenerate` action's own ledger status,
 * quoted directly from ticket 08's "Что должно заработать" and the
 * repair's own condition 1 -- `needs_chat`/`needs_chat_setup` deliberately
 * share one phrase (condition 1, bullet 3: "needs_chat / needs_chat_setup
 * — «Нужно разрешение в чате»"), not two independently-worded ones. */
const CARD_BUSY_TEXT = Object.freeze({
  queued: "Действие отправлено. Ждём ответа в чате.",
  running: "Выполняется в чате.",
  needs_chat: "Нужно разрешение в чате.",
  needs_chat_setup: "Нужно разрешение в чате.",
  outcome_unknown: "Исход нужно проверить в чате.",
});

/** `null` when `status` is not one of the five known in-flight/blocked
 * action statuses; otherwise `{text, returnToChat}` -- `returnToChat`
 * marks the one status (`outcome_unknown`) whose notice also carries the
 * static "Вернуться в чат" hint (never a real control: there is no in-app
 * chat surface to navigate to, spec §5's "только новое явное решение в
 * чате может создать новый grant"). Kept as its own export -- a pure
 * `status -> text` mapping independent of where the status came from --
 * so tests/ui/card-model.test.mjs can pin the five texts directly. */
export function resolveCardBusyNotice(status) {
  const text = resolveLabel(CARD_BUSY_TEXT, status);
  if (!text) {
    return null;
  }
  return { text, returnToChat: status === "outcome_unknown" };
}

/** The latest `snapshot.actions` entry for one `(targetId, actionType)`
 * pair, or `null`. `actions` is already at most one entry per pair
 * (`ActionLedger.latest_actions_by_target`'s own contract) -- this never
 * needs to pick a "latest" among several itself. */
function findAction(actions, targetId, actionType) {
  const list = Array.isArray(actions) ? actions : [];
  return list.find((item) => item && item.target_id === targetId && item.action_type === actionType) || null;
}

const BLOCKING_STATUSES = new Set(["queued", "running", "outcome_unknown"]);
const INFORMATIONAL_STATUSES = new Set(["needs_chat", "needs_chat_setup"]);

/** Whether `status` is one of the two "no grant was spent, a new click is
 * allowed" statuses (`needs_chat`/`needs_chat_setup`) -- exported so
 * ui/grant-action.js's own `performSubmit` can decide whether a just-
 * received 202's own status re-enables this card's controls without
 * hardcoding a second copy of the same two-status set (this repair's own
 * non-blocking note 3: "у одного токена одна подпись из одного словаря" --
 * applies equally to which *set* a status belongs to, not just its text). */
export function isInformationalGrantStatus(status) {
  return INFORMATIONAL_STATUSES.has(status);
}

// -----------------------------------------------------------------------
// The unconfirmed-request cache (condition 1, bullet 5).
// -----------------------------------------------------------------------

const pendingRequests = new Map();

function pendingKey(projectId, actionType, targetId) {
  return `${projectId}::${actionType}::${targetId}`;
}

function storageKey(key) {
  return `studio:pending-action:${key}`;
}

/** `sessionStorage` access wrapped in try/catch everywhere (private
 * browsing, a blocked store, a full quota) -- a storage failure degrades
 * to "the in-memory Map is all there is", never a thrown error reaching a
 * click handler. */
function readStorage(key) {
  try {
    const raw = window.sessionStorage.getItem(storageKey(key));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeStorage(key, value) {
  try {
    window.sessionStorage.setItem(storageKey(key), JSON.stringify(value));
  } catch {
    // Ignored -- the in-memory Map (set by the caller alongside this)
    // still serves the rest of this page's own life.
  }
}

function removeStorage(key) {
  try {
    window.sessionStorage.removeItem(storageKey(key));
  } catch {
    // Ignored -- see writeStorage.
  }
}

/**
 * The stored `{idempotencyKey, payload, expectedRevision}` for one
 * project/action/target, or `null`. Checks the in-memory Map first (the
 * common case: this same page session already holds it); falls back to
 * `sessionStorage` and hydrates the Map from it -- the path a reload
 * takes, since the Map itself does not survive a reload but
 * `sessionStorage` does.
 */
export function getPendingRequest(projectId, actionType, targetId) {
  const key = pendingKey(projectId, actionType, targetId);
  if (pendingRequests.has(key)) {
    return pendingRequests.get(key);
  }
  const stored = readStorage(key);
  if (stored) {
    pendingRequests.set(key, stored);
  }
  return stored;
}

/** Record a request as sent-but-not-yet-confirmed, *before* the network
 * call that sends it -- so even a crash between this call and the fetch
 * settling leaves a durable trace for the next page load to retry from. */
export function savePendingRequest(projectId, actionType, targetId, request) {
  const key = pendingKey(projectId, actionType, targetId);
  pendingRequests.set(key, request);
  writeStorage(key, request);
}

export function clearPendingRequest(projectId, actionType, targetId) {
  const key = pendingKey(projectId, actionType, targetId);
  pendingRequests.delete(key);
  removeStorage(key);
}

/**
 * The `action_id` of `snapshot.actions`'s own current entry for one
 * `(targetId, actionType)` pair, or `null` when there is none -- the
 * "baseline" a fresh grant request is minted against (client repair 2:
 * "При сохранении записи запомнить baselineActionId: action_id последнего
 * действия этой пары в snapshot, по которому построен контрол"). Read at
 * render time (ui/card-decorate.js) and threaded into `resolveGrantRequest`
 * exactly like `expectedRevision` already is, so a request minted while a
 * *stale* entry (an old `succeeded` from a previous grant) is the only
 * thing on record still treats that entry as "already known about" --
 * never as proof this new request itself landed.
 */
export function resolveBaselineActionId(actions, targetId, actionType) {
  const entry = findAction(actions, targetId, actionType);
  return entry ? entry.action_id ?? null : null;
}

/**
 * Drop a pending-request record for `projectId`'s `(actionType, targetId)`
 * pair once `snapshot.actions` shows *this* request landed -- never merely
 * because *some* entry exists for that pair (client repair 2's own fix:
 * the pre-repair version cleared on any entry at all, including a stale
 * one already there before this request was sent -- see the file banner's
 * "a)"). "This request landed" means an entry is present whose `action_id`
 * differs from the record's own `baselineActionId` (condition 1, bullet 5:
 * "в snapshot.actions у пары есть действие с action_id, отличным от
 * baselineActionId"). No entry at all yet -- baseline or otherwise -- is
 * not proof of anything, so the record is left alone; that is exactly the
 * "lost response, no confirmation either way" state the pending cache
 * exists to survive. Called once per render, for every target id the
 * current stage's own cards carry.
 */
export function prunePendingRequests(projectId, actions, targetIds) {
  for (const targetId of Array.isArray(targetIds) ? targetIds : []) {
    for (const actionType of GRANT_ACTION_TYPES) {
      const pending = getPendingRequest(projectId, actionType, targetId);
      if (!pending) {
        continue;
      }
      const entry = findAction(actions, targetId, actionType);
      if (!entry) {
        continue;
      }
      const currentActionId = entry.action_id ?? null;
      const baselineActionId = pending.baselineActionId ?? null;
      if (currentActionId !== baselineActionId) {
        clearPendingRequest(projectId, actionType, targetId);
      }
    }
  }
}

/**
 * The one pending (unconfirmed) grant request for this card, if any -- at
 * most one by construction: once either `vary` or `regenerate` has an
 * unconfirmed request outstanding, `resolveGrantCardState` withholds the
 * *other* type from ever rendering at all, so it can never itself acquire
 * a second pending record while the first is still open. `null` when
 * neither grant type has one right now.
 */
export function findPendingGrantRequest(projectId, targetId) {
  for (const actionType of GRANT_ACTION_TYPES) {
    const request = getPendingRequest(projectId, actionType, targetId);
    if (request) {
      return { actionType, request };
    }
  }
  return null;
}

/**
 * Apply the "any definite server answer settles this request" half of
 * condition 1, bullet 5 to one `postAction` result: a transport failure
 * (`network_error`/`session_error`) means the server never actually
 * answered, so the pending record must survive for the next retry to reuse
 * (`ok:false` no different from no answer at all); anything else -- a
 * genuine `202` or a real error code the server did send -- is a
 * definitive answer, so the record's job is done. Returns whether it
 * cleared the record, so a caller (ui/card-forms.js's `buildGrantAction`)
 * can drive its own status text off the same decision instead of
 * duplicating the network_error/session_error check itself.
 */
export function settlePendingRequest(projectId, actionType, targetId, result) {
  const isTransportFailure = !result.ok && (result.code === "network_error" || result.code === "session_error");
  if (isTransportFailure) {
    return false;
  }
  clearPendingRequest(projectId, actionType, targetId);
  return true;
}

/**
 * The one decision behind "Повтор идёт этим же запросом" (condition 1,
 * bullet 5): given a pending record already exists for this project/
 * action/target, reuse its exact `idempotencyKey`/`payload`/
 * `expectedRevision` (`reused: true`) rather than the caller's freshly
 * typed note/current revision; otherwise mint a fresh key, save it as the
 * new pending record *before* returning (durable against a crash before
 * the caller's own network call even starts), and report `reused: false`.
 *
 * Pure aside from that one save -- no `fetch`, no DOM -- so the core
 * "a retry never mints a second key while the first is unresolved"
 * guarantee is directly testable (tests/ui/paid-action-state.test.mjs)
 * without needing a click or a DOM at all. ui/card-forms.js's
 * `buildGrantAction` is the one caller.
 *
 * `baselineActionId` (client repair 2) is only ever used on the *fresh*
 * path -- a reused pending record keeps whatever baseline it was minted
 * with, never the caller's newest one, exactly like it keeps the original
 * `payload`/`expectedRevision` instead of the caller's freshly typed ones.
 */
export function resolveGrantRequest({
  projectId,
  actionType,
  targetId,
  freshPayload,
  freshExpectedRevision,
  baselineActionId = null,
}) {
  const pending = getPendingRequest(projectId, actionType, targetId);
  if (pending) {
    return {
      idempotencyKey: pending.idempotencyKey,
      payload: pending.payload,
      expectedRevision: pending.expectedRevision,
      reused: true,
    };
  }
  const request = {
    idempotencyKey: crypto.randomUUID(),
    payload: freshPayload && typeof freshPayload === "object" ? freshPayload : {},
    expectedRevision: freshExpectedRevision,
    baselineActionId,
  };
  savePendingRequest(projectId, actionType, targetId, request);
  return { ...request, reused: false };
}

// -----------------------------------------------------------------------
// The combined per-card state buildGrantAction actually renders from.
// -----------------------------------------------------------------------

/**
 * `vary`/`regenerate`'s combined state for one card, from `snapshot.actions`
 * alone -- condition 1's "Состояние vary/regenerate для карточки берётся
 * из snapshot.actions по target_id" is explicit that this is the one
 * source of visual truth *once the ledger has recorded something*. This
 * function on its own never consults the pending-request cache above --
 * that split is deliberate, kept so each half stays independently testable
 * -- which is exactly why it must never be called directly from
 * ui/card-decorate.js any more (client repair 2): a request that is still
 * in flight, or was lost before any server response at all, leaves
 * `snapshot.actions` with *nothing* for that pair, and this function alone
 * would report "nothing blocking" while a second paid click was still one
 * click away. `resolveGrantCardState` below is the one callers actually
 * use -- it checks the pending cache *first* and only falls back to this
 * function once nothing is pending.
 *
 * "Одно платное действие на карточку" (condition 1) reads as *one card*,
 * not one action type, so a `queued` `vary` blocks `regenerate` on the
 * very same card too (only one grant-consuming attempt should ever be in
 * flight for a card at a time).
 *
 * Returns `null` (render both buttons normally) or `{kind, text,
 * returnToChat?}`:
 *  - `kind: "blocked"` -- `queued`/`running`/`outcome_unknown`: no
 *    vary/regenerate button renders at all, only this notice (condition 1:
 *    "outcome_unknown... Кнопок vary и regenerate у этой цели нет").
 *  - `kind: "notice"` -- `needs_chat`/`needs_chat_setup`: the buttons
 *    stay, this notice renders alongside them (condition 1: "Новый клик
 *    допустим: без grant он ничего не списывает").
 */
export function resolveGrantRowState({ actions, targetId }) {
  let blocking = null;
  let informational = null;
  for (const actionType of GRANT_ACTION_TYPES) {
    const entry = findAction(actions, targetId, actionType);
    if (entry && BLOCKING_STATUSES.has(entry.status) && !blocking) {
      blocking = entry;
    } else if (entry && INFORMATIONAL_STATUSES.has(entry.status) && !informational) {
      informational = entry;
    }
  }
  if (blocking) {
    const notice = resolveCardBusyNotice(blocking.status);
    return notice ? { kind: "blocked", text: notice.text, returnToChat: notice.returnToChat } : null;
  }
  if (informational) {
    const notice = resolveCardBusyNotice(informational.status);
    return notice ? { kind: "notice", text: notice.text } : null;
  }
  return null;
}

/**
 * The full per-card grant-row decision -- the pending-request cache first,
 * `resolveGrantRowState`'s own snapshot-only view only once nothing is
 * pending (client repair 2, condition 1's second scenario: "пока vary не
 * подтверждён... предлагается regenerate — это второе платное действие").
 * `resolveGrantRowState` alone is correct but insufficient as the *only*
 * check: right after a POST is sent (pending record already saved) and
 * before any response lands -- or after a lost response the operator has
 * not yet retried -- `snapshot.actions` has nothing at all for either
 * grant type yet, so `resolveGrantRowState` reports "nothing blocking" and
 * both buttons would render, exactly the gap this closes.
 *
 * ui/card-decorate.js's `buildCardActionsRow` is the one caller; this is
 * the single function it needs to decide the whole grant row.
 *
 * Returns:
 *  - `{kind: "pending", actionType}` -- an unconfirmed request already
 *    exists for `actionType` (`vary` or `regenerate`); only that type's
 *    own control renders, in its own retry-only mode (`buildGrantAction`
 *    self-detects the same pending record), and the other type is
 *    withheld entirely.
 *  - whatever `resolveGrantRowState` itself returns (`null`, `{kind:
 *    "blocked", ...}` or `{kind: "notice", ...}`) once nothing is pending.
 */
export function resolveGrantCardState({ projectId, actions, targetId, targetIds = null, working = false }) {
  const targets = targetIds || [targetId];
  for (const identity of targets) {
    const pending = findPendingGrantRequest(projectId, identity);
    if (pending) {
      return { kind: "pending", actionType: pending.actionType, ...(targetIds ? { targetId: identity } : {}) };
    }
  }
  const states = targets.map((identity) => resolveGrantRowState({ actions, targetId: identity })).filter(Boolean);
  const blocked = states.find((state) => state.kind === "blocked");
  if (blocked) return blocked;
  if (working) return { kind: "blocked", text: "В работе. Ждём ответа в чате." };
  return states.find((state) => state.kind === "notice") || null;
}

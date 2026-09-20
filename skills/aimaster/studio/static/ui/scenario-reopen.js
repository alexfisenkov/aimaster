// Ticket 16: "Вернуться к сценарию" -- the in-place control that sends
// `reopen-scenario` from any stage after `scenario` (server contract: task
// 15's `decision_stages.build_reopen_mutation`, gated purely by
// `reopen-scenario` being in `view_stage.allowed_actions` -- the server
// never lists it on `scenario` itself or while blocked, so no extra stage
// check belongs here beyond that one allowlist read, matching every other
// gate in this codebase, e.g. ui/stage-approval.js's `stageApprovalVisible`).
//
// A small, standalone module (ui/scenario.js only calls `buildReopenControl`
// -- it never builds this control's own DOM by hand) so ui/scenario.js's
// already-large render surface does not also have to carry this control's
// own confirm/submit protocol. DOM-only, verified through the browser
// visual gate plus a real-DOM test (tests/ui/scenario-reopen.test.mjs,
// tests/ui/support/dom-stubs.mjs) -- same convention as every other
// *-forms/*-approval module here (ui/card-forms.js, ui/stage-approval.js).

import { resolveActionErrorMessage, resolveActionFailureText, submitAction } from "./actions.js";
import { markControlHooks, OUTCOME_UNCONFIRMED_TEXT, requestProjectRefresh } from "./card-forms.js";
import { draftKey, getDraft, setDraft, clearDraft } from "./card-drafts.js";

/** Exact confirmation copy from the ticket -- quoted once, here, so the
 * confirm panel and its own test never drift apart on wording. */
export const REOPEN_CONFIRM_TEXT =
  "Сценарий снова откроется для правки. Промпты, изображения и видео сохранятся, этапы после сценария нужно будет одобрить заново.";

/** Shown both as the disabled-button hint (ticket condition 2) and, on a
 * later repaint, in place of a `failed` reopen attempt's own status line
 * (condition 5's "Отказ возврата при действиях в работе") -- the server's
 * own refusal reason is never rendered raw; this is the one client-side
 * dictionary entry for it. */
export const REOPEN_PENDING_HINT_TEXT = "Дождитесь завершения действий в чате.";

/** Whether `reopen-scenario` is currently offered at all -- purely a read
 * of the server-derived allowlist (spec §2.1/G04), never a guess from
 * `current_stage` or any other client-side rule: the server already knows
 * `scenario` itself and `blocked` never carry it. */
export function reopenScenarioVisible(viewStage) {
  const allowed = viewStage && viewStage.allowed_actions;
  return Array.isArray(allowed) && allowed.includes("reopen-scenario");
}

/** Ticket condition 2: any action anywhere in the project still `queued`/
 * `running` disables the button -- the server's own `ensure_no_pending_
 * actions` check is project-wide, not scoped to `reopen-scenario` alone, so
 * this reads every entry in `snapshot.actions`, not just one target's. */
export function hasPendingProjectActions(actions) {
  return (
    Array.isArray(actions) &&
    actions.some((entry) => entry && (entry.status === "queued" || entry.status === "running"))
  );
}

/** The one place a `failed` reopen attempt is turned into interface copy
 * (condition 5) -- `undefined` for anything else (no attempt yet, still
 * queued/running, a genuine success already reflected by the stage having
 * moved). A `failed` reopen only ever has one realistic cause once the
 * client's own pre-check already confirmed `reopen-scenario` was allowed at
 * click time -- a pending action appearing in the gap between that render
 * and the click -- so this always resolves to the one pending-actions
 * hint, never a second, invented explanation of the server's own reasons.
 * Ticket 17 condition 1: the actual (action_type, target_id) lookup is
 * `actions.js`'s shared `resolveActionFailureText`, not a bespoke `find`
 * kept here -- ui/scenario.js's own `resolveSceneEditFailureText` calls the
 * exact same helper for its own `edit`/scene-id pair. */
export function resolveReopenFailureText(actions) {
  return resolveActionFailureText(actions, "reopen-scenario", "scenario", REOPEN_PENDING_HINT_TEXT);
}

function dispatchScenarioFocusPending(projectId) {
  document.dispatchEvent(
    new CustomEvent("studio:scenario-focus-pending", { bubbles: true, detail: { projectId } }),
  );
}

/**
 * Build "Вернуться к сценарию" plus its on-the-spot confirm panel, or
 * `null` when `reopen-scenario` is not currently offered (ticket condition
 * 1: absent at `scenario` itself and while blocked). `actions` is the
 * snapshot's own `actions[]`; `revision`/`projectId` are the snapshot's own
 * top-level revision and the open project's id.
 *
 * The confirm step's own open/closed state survives a repaint via
 * ui/card-drafts.js -- the same mechanism ui/grant-action.js's own
 * `buildGrantToggle` already uses for its confirm form (ticket condition 6:
 * "подтверждение... переживает запись из чата"). Both the toggle and the
 * confirm/cancel buttons carry `data-hook="card-control"` (ui/card-forms.js's
 * `markControlHooks`), so ui/shell.js's already-generic card-control focus
 * axis (`captureLiveCardControlFocus`/`repaintZonePreservingFocus`) restores
 * focus to whichever of the three was focused across that same repaint,
 * with no change needed in ui/shell.js for that part.
 */
export function buildReopenControl({ viewStage, actions, revision, projectId }) {
  if (!reopenScenarioVisible(viewStage)) {
    return null;
  }
  const pending = hasPendingProjectActions(actions);
  const confirmKey = draftKey(projectId, "reopen-confirm", "scenario");
  const wasOpen = Boolean(getDraft(confirmKey)?.open);

  const wrap = document.createElement("div");
  wrap.className = "scenario-reopen";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "card-action-button";
  markControlHooks(toggle, "scenario", "reopen-scenario");
  toggle.textContent = "Вернуться к сценарию";
  toggle.disabled = pending;

  const confirmPanel = document.createElement("div");
  confirmPanel.className = "card-confirm-form";
  confirmPanel.hidden = !wasOpen;

  const confirmText = document.createElement("p");
  confirmText.className = "card-confirm-text";
  confirmText.textContent = REOPEN_CONFIRM_TEXT;

  const status = document.createElement("p");
  status.className = "card-action-status";
  status.setAttribute("role", "status");
  // The very first thing shown, on a fresh mount/repaint alike, is whatever
  // the latest known reopen attempt's own outcome says -- never a blank
  // slate that silently forgets a just-refused attempt the instant an
  // unrelated repaint rebuilds this control from scratch.
  status.textContent = resolveReopenFailureText(actions) || "";

  const actionsRow = document.createElement("div");
  actionsRow.className = "card-comment-actions";
  const confirmButton = document.createElement("button");
  confirmButton.type = "button";
  markControlHooks(confirmButton, "scenario", "reopen-scenario-confirm");
  confirmButton.textContent = "Вернуться к сценарию";
  confirmButton.disabled = pending;
  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  markControlHooks(cancelButton, "scenario", "reopen-scenario-cancel");
  cancelButton.textContent = "Отмена";
  actionsRow.append(confirmButton, cancelButton);

  confirmPanel.append(confirmText, actionsRow, status);

  function saveOpenDraft() {
    setDraft(confirmKey, { open: !confirmPanel.hidden });
  }

  function closeConfirm() {
    confirmPanel.hidden = true;
    clearDraft(confirmKey);
    status.textContent = resolveReopenFailureText(actions) || "";
    toggle.focus();
  }

  toggle.addEventListener("click", () => {
    if (toggle.disabled) {
      return;
    }
    confirmPanel.hidden = !confirmPanel.hidden;
    if (!confirmPanel.hidden) {
      confirmButton.focus();
      saveOpenDraft();
    } else {
      clearDraft(confirmKey);
    }
  });

  cancelButton.addEventListener("click", () => closeConfirm());

  // Ticket condition 1: "Escape... закрывают его без действия." Attached on
  // the confirm panel itself -- not `document` -- because, unlike
  // ui/question-dialog.js's persistent singleton overlay (see that module's
  // own reasoning for why *it* needs a document-level listener), this whole
  // subtree is rebuilt from scratch on every repaint; a document-level
  // listener would have to be explicitly detached on every teardown or leak
  // one copy per repaint. A listener on this element needs no such
  // bookkeeping: once the element is discarded, so is its listener.
  confirmPanel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeConfirm();
    }
  });

  confirmButton.addEventListener("click", async () => {
    if (confirmButton.disabled) {
      return;
    }
    // Deliberately no `noteCardFocusPending` here, unlike every other
    // card-control in this codebase: this control's own genuine-success
    // outcome always removes the confirm button that was just clicked --
    // the whole panel is replaced by stage 1's editable heading -- so a
    // stale "restore focus to reopen-scenario-confirm" note would only
    // ever go unmatched by ui/shell.js's own `findCardControlFocusTarget`
    // once the refresh lands, and its own `cardFocusNote`-truthy fallback
    // (`focusCardFallbackHeading`) would then steal focus onto the
    // inspector's heading -- confirmed live, overriding the correct
    // scenario-heading focus `dispatchScenarioFocusPending` below already
    // arranges. `submitAction` still disables this control synchronously
    // (the usual blur-to-body before the network call resolves), but
    // nothing here refreshes on an *unconfirmed* settle (matching every
    // other free-decision control's own reasoning), so there is no repaint
    // for a missing note to have mattered for in that branch either.
    status.textContent = "Отправляется…";
    saveOpenDraft();
    const result = await submitAction({
      actionType: "reopen-scenario",
      targetId: "scenario",
      payload: {},
      expectedRevision: revision,
      controls: [toggle, confirmButton, cancelButton],
    });
    if (result.ok && result.confirmed !== false) {
      // A confirmed success: stage 1 is about to replace this whole panel
      // (`requestProjectRefresh`) -- ask ui/shell.js to focus the fresh
      // scenario heading once that repaint actually lands (ticket
      // condition 1: "фокус — на заголовке сценария"), never here, where
      // the target does not exist yet.
      clearDraft(confirmKey);
      dispatchScenarioFocusPending(projectId);
      requestProjectRefresh(projectId);
      return;
    }
    if (result.ok) {
      // Settled but unconfirmed: the click was sent and accepted, but nothing
      // observed the revision actually move within the wait budget. Left
      // open, with the generic unconfirmed text -- a later, natural repaint
      // (task 14's liveness poll) will replace this with
      // `resolveReopenFailureText`'s own dictionary text if the reopen was
      // in fact refused by the "pending actions" safety net (condition 5),
      // or clear it entirely once the stage genuinely has moved on.
      status.textContent = OUTCOME_UNCONFIRMED_TEXT;
      saveOpenDraft();
      return;
    }
    status.textContent = resolveActionErrorMessage(result.code);
    saveOpenDraft();
    if (result.code === "revision_conflict") {
      requestProjectRefresh(projectId);
    }
  });

  wrap.append(toggle);
  if (pending) {
    const hint = document.createElement("p");
    hint.className = "card-busy-notice";
    hint.textContent = REOPEN_PENDING_HINT_TEXT;
    wrap.append(hint);
  }
  wrap.append(confirmPanel);
  return wrap;
}

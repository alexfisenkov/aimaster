// Ticket 08 repair 2's own new module (allowed by the ticket's zone list:
// "новый модуль протокола отправки"), closing the repair's second BLOCKING
// path. `vary`/`regenerate`'s DOM *and* the network protocol behind it
// (idempotent retry, settle, in-place lock) both live here now -- non-
// blocking note 2: "протокол платной отправки... живёт в модуле платных
// действий. card-forms.js только строит DOM." ui/card-forms.js's own
// `buildGrantAction` (repair 1) is gone; ui/card-decorate.js's
// `buildCardActionsRow` calls this module's `buildGrantArea` once per
// card instead, for *both* grant types together.
//
// Why "together" matters (repair 2's own diagnosis, condition 17):
// repair 1 built `vary` and `regenerate` as two independent controls that
// happened to share one row. Each disabled its own row's buttons on
// submit (correctly catching the other type's toggle too, since they sat
// in the same DOM container) -- but on a transport failure
// (`network_error`/`session_error`, i.e. "server may have already
// recorded it, the response never arrived") the failure branch called
// `restoreSiblingButtons()`, which put every one of those buttons -- the
// *other* grant type's toggle included -- straight back to enabled. A
// card mid an unconfirmed "Вариация" would show a fully clickable
// "Перегенерировать" right next to it, no reload needed: the second
// BLOCKING path both reviewers reproduced live.
//
// The fix is structural, not a bigger disable list: `buildGrantArea`
// builds one `<div class="card-grant-area">` (styles/actions.css gives it
// `display: contents`, so its children still lay out as plain flex items
// of the row exactly as two independent controls used to) that owns
// *both* types' DOM for as long as neither has an unconfirmed request
// outstanding. The moment either one submits, `performSubmit` disables
// every button inside that one container -- both toggles, both confirm
// forms, any retry button -- and, critically, a transport failure swaps
// the container's own content to a retry-only view (`renderPending`)
// instead of restoring it. There is no "everything back to normal" branch
// left that a lost response can reach.
//
// The retry button `renderPending` builds re-reads the pending cache at
// *click* time, never trusting the value closed over when it was built
// (condition 17's invariant 3: "если записи уже нет, он ничего не
// отправляет"). This matters even with the ordering fix in
// ui/card-decorate.js's own `decorateResultCards` (records are pruned
// before any row is built, repair 2's condition 17 invariant 1): a
// control built by one render pass can still be clicked after a *later*
// pass has already pruned the record it was built from -- this module
// never assumes it is the only render this card will ever get.

import { postAction, resolveActionErrorMessage } from "./actions.js";
import { resolveCardActionLabel } from "./card-model.js";
import {
  getPendingRequest,
  isInformationalGrantStatus,
  resolveBaselineActionId,
  resolveCardBusyNotice,
  resolveGrantRequest,
  settlePendingRequest,
} from "./paid-action-state.js";
import { markControlHooks, noteCardFocusPending, requestProjectRefresh } from "./card-forms.js";
import { draftKey, getDraft, setDraft, clearDraft } from "./card-drafts.js";

// t08-followup, craft review finding 3: a retry-mode card used to show
// *two* texts about the same unconfirmed attempt -- this call's own
// `status.textContent` ("Не удалось отправить... нажмите ещё раз") *and*
// `renderPending`'s own separate `.card-busy-notice` paragraph, which
// wrongly reused ui/card-forms.js's `OUTCOME_UNCONFIRMED_TEXT` ("Обновите
// страницу"), a message written for a *free* action's expired confirmation
// wait, not a paid one with a live retry button sitting right next to it.
// One text now, owned by `renderPending` alone (the one render both a
// transport failure and a fresh reload/repaint funnel through) -- see that
// function's own banner.
// Exported (mirrors ui/card-forms.js's own `OUTCOME_UNCONFIRMED_TEXT`
// export) so tests/ui/card-decorate.test.mjs pins this exact string instead
// of a second, hand-copied literal that could silently drift from it.
export const GRANT_PENDING_TEXT = "Исход отправки не подтверждён. Есть сохранённая попытка — нажмите «Повторить отправку».";

/** One toggle+confirm-form control for a single grant type (`vary` carries
 * an optional free-text note, spec §5/brief: "можешь... написать...
 * изменения, что именно поменять"; `regenerate` does not). DOM-only --
 * wired to `onSubmit` by the caller, never calls `performSubmit` itself,
 * so this stays a plain builder `buildGrantArea`'s own render functions
 * below reuse for both the initial paint and an in-place rebuild. */
function buildGrantToggle(actionType, targetId, projectId, onSubmit, label = null) {
  const hasNote = actionType === "vary";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "card-action-button";
  markControlHooks(toggle, targetId, actionType);
  toggle.textContent = label || resolveCardActionLabel(actionType);

  // The explicit generation click is the consent. Only variation needs an
  // input form; its submit is the one paid click, never another confirmation.
  if (!hasNote) {
    const wrap = document.createElement("div");
    wrap.className = "card-comment-wrap";
    wrap.dataset.grantAction = actionType;
    toggle.dataset.paidControl = "true";
    toggle.addEventListener("click", () => onSubmit(actionType, {}));
    wrap.append(toggle);
    return wrap;
  }

  // Repair, ticket 14 repair 2, condition 11 (manifest review, BLOCKING
  // G04): this confirm step's own open/closed state is itself interface
  // state, exactly like the note's text below -- an unrelated repaint (a
  // chat record landing mid-typing) used to always rebuild `confirmForm`
  // hidden, no matter how the operator had left it, because `buildGrantArea`
  // is called fresh on every `decorateResultCards`/`decoratePromptCards`
  // pass and this line used to just hardcode `true`. Once hidden, the note
  // field inside it stops being a real, focusable control in an actual
  // browser (dom-stubs.mjs's own fake DOM has no notion of `hidden`
  // suppressing focusability at all, which is exactly why the pre-repair
  // test suite stayed green through this bug -- see this module's own test
  // in tests/ui/repaint-preservation.test.mjs for the assertion that
  // actually catches it) -- ui/shell.js's already-correct
  // captureLiveCardControlFocus/repaintZonePreservingFocus card-control axis
  // then had nothing real left to refocus, and fell through to whatever
  // *is* still focusable: the card's own thumbnail button, where a
  // subsequent Space press opens the viewer instead of typing a space into
  // the note (the review's own exact repro). Stored the same way the note's
  // own text already is -- this module's own in-memory draft store (ui/
  // card-drafts.js) -- keyed per project+action type+target so `vary` and
  // `regenerate` on the same card never share one flag, and cleared on
  // submit and on cancel ("снимай при отправке или отмене": both are the
  // operator's own explicit close, never an interrupted one, so nothing
  // should reopen on the next rebuild).
  const confirmOpenKey = draftKey(projectId, `${actionType}-confirm`, targetId);
  const wasConfirmOpen = Boolean(getDraft(confirmOpenKey)?.open);

  const confirmForm = document.createElement("form");
  confirmForm.className = "card-confirm-form";
  confirmForm.hidden = !wasConfirmOpen;

  // Repair, ticket 14 punch-list item 2 (review blocker G04, same class as
  // ui/card-forms.js's own comment/prompt-edit fields): this optional note
  // used to carry no hook and no draft, so text typed into it while a real,
  // unrelated repaint landed (decorateResultCards/decoratePromptCards
  // rebuild this whole area on every commit -- see ui/card-decorate.js's
  // own buildCardActionsRow) went nowhere, the field simply vanished and
  // reappeared empty. `noteKey`/draft mirror ui/card-forms.js's own
  // buildCommentForm exactly, through the same three ui/card-drafts.js
  // functions; the hook's own action (`"vary-note"`) is distinct from the
  // toggle's own (`"vary"`) and from `renderPending`'s own retry button
  // (also `actionType`, i.e. `"vary"`), so an exact card-control match
  // never confuses the field with either button.
  let noteInput = null;
  const noteKey = hasNote ? draftKey(projectId, "vary-note", targetId) : null;
  const noteDraft = noteKey ? getDraft(noteKey) : null;
  if (hasNote) {
    const label = document.createElement("label");
    label.className = "card-comment-label";
    const caption = document.createElement("span");
    caption.textContent = "Что изменить (необязательно)";
    noteInput = document.createElement("textarea");
    noteInput.className = "card-comment-textarea";
    markControlHooks(noteInput, targetId, "vary-note");
    noteInput.value = noteDraft ? noteDraft.text : "";
    label.append(caption, noteInput);
    confirmForm.append(label);
    noteInput.addEventListener("input", () => {
      setDraft(noteKey, { text: noteInput.value });
    });
  }

  const actionsRow = document.createElement("div");
  actionsRow.className = "card-comment-actions";
  const confirmButton = document.createElement("button");
  confirmButton.type = "submit";
  confirmButton.textContent = "Сгенерировать вариацию";
  markControlHooks(confirmButton, targetId, "vary-submit");
  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.textContent = "Отмена";
  markControlHooks(cancelButton, targetId, "vary-cancel");
  actionsRow.append(confirmButton, cancelButton);
  confirmForm.append(actionsRow);

  toggle.addEventListener("click", () => {
    confirmForm.hidden = !confirmForm.hidden;
    if (!confirmForm.hidden) {
      confirmButton.focus();
      setDraft(confirmOpenKey, { open: true });
    } else {
      // Collapsed again via the toggle itself (not Cancel) -- the note's
      // own typed text is deliberately left alone (unchanged from before
      // this repair), only the step's own open/closed memory follows it
      // shut, so the next rebuild starts collapsed too.
      clearDraft(confirmOpenKey);
    }
  });
  cancelButton.addEventListener("click", () => {
    confirmForm.hidden = true;
    clearDraft(confirmOpenKey);
    if (noteInput) {
      noteInput.value = "";
    }
    if (noteKey) {
      clearDraft(noteKey);
    }
    toggle.focus();
  });
  confirmForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const freshPayload = {};
    if (noteInput && noteInput.value.trim()) {
      freshPayload.note = noteInput.value.trim();
    }
    // The note is now part of the *sent* (or about-to-be-sent) payload --
    // `resolveGrantRequest`'s own pending-request cache (sessionStorage,
    // below) is what a retry actually resends from once this control is
    // gone, never a re-read of this field, so there is nothing left for a
    // local draft to usefully preserve past this point.
    if (noteKey) {
      clearDraft(noteKey);
    }
    clearDraft(confirmOpenKey);
    await onSubmit(actionType, freshPayload);
    confirmForm.hidden = true;
  });

  const wrap = document.createElement("div");
  wrap.className = "card-comment-wrap";
  wrap.dataset.grantAction = actionType;
  wrap.append(toggle, confirmForm);
  for (const control of wrap.querySelectorAll("button")) {
    control.dataset.paidControl = "true";
  }
  return wrap;
}

/**
 * `vary`/`regenerate` together, as one card's worth of DOM -- the single
 * function ui/card-decorate.js's `buildCardActionsRow` calls whenever
 * either grant type is offered (`hasVary || hasRegenerate`) and the
 * combined state (`resolveGrantCardState`, ui/paid-action-state.js) is not
 * `"blocked"` (a genuinely blocked target -- queued/running/
 * outcome_unknown from the *ledger* -- stays ui/card-decorate.js's own
 * plain notice, unrelated to the in-flight-submit protocol this module
 * owns).
 *
 * `grantState` is whatever `resolveGrantCardState` returned: `null`
 * (render both types normally), `{kind:"notice", text}` (both types
 * render, plus the notice -- `needs_chat`/`needs_chat_setup`, a new click
 * is allowed) or `{kind:"pending", actionType}` (an unconfirmed request
 * already exists; only that type renders, in retry mode).
 */
export function buildGrantArea({ grantState, hasVary, hasRegenerate, hasGenerate = false, targetId,
  hookTargetId = targetId, targetIds = {}, generateLabel = null,
  expectedRevision, projectId, actionEntries, status, controlRoot = null }) {
  const area = document.createElement("div");
  area.className = "card-grant-area";
  let submitting = false;

  /** Retry-only view for one already-pending grant type -- the render
   * every transport failure (`performSubmit`'s own `!settled` branch)
   * switches this card's grant area to *in place*, and the same view a
   * fresh decorate pass builds directly when `grantState.kind ===
   * "pending"` (a reload/repaint with the pending cache still unsettled).
   * One render function, two callers -- never two copies of this markup. */
  function renderPending(actionType, requestTarget = targetIds[actionType] || targetId) {
    for (const stale of (controlRoot || area).querySelectorAll('[data-grant-action]')) {
      stale.remove();
    }
    area.replaceChildren();
    // The one place this card's "there is a saved, unconfirmed attempt"
    // text is set -- both callers (a fresh render/reload with the pending
    // cache still unsettled, and `performSubmit`'s own transport-failure
    // branch) funnel through here, so there is exactly one text on screen
    // about this state, never `status`'s own leftover "Отправляется…"/
    // failure copy stacked on top of a second notice paragraph (craft
    // review finding 3).
    status.textContent = GRANT_PENDING_TEXT;
    const wrap = document.createElement("div");
    wrap.className = "card-comment-wrap";
    wrap.dataset.grantAction = actionType;
    const retryButton = document.createElement("button");
    retryButton.type = "button";
    retryButton.className = "card-action-button";
    retryButton.dataset.paidControl = "true";
    markControlHooks(retryButton, hookTargetId, actionType);
    retryButton.textContent = "Повторить отправку";
    retryButton.addEventListener("click", () => {
      // Re-read the cache fresh, never the value this closure would
      // otherwise remember from when the button was built -- a control
      // built by an earlier render (this same card's own prior pass, or
      // one a later pass has since superseded) must not be able to mint
      // a second grant just because nobody ever removed its listener
      // (condition 17, invariant 3).
      const stillPending = getPendingRequest(projectId, actionType, requestTarget);
      if (!stillPending) {
        requestProjectRefresh(projectId);
        return;
      }
      performSubmit(actionType, stillPending.payload, requestTarget);
    });
    wrap.append(retryButton);
    area.append(wrap);
  }

  function renderNormal(noticeText) {
    area.replaceChildren();
    if (hasGenerate) {
      area.append(buildGrantToggle("generate", hookTargetId, projectId, performSubmit, generateLabel));
    }
    if (hasVary) {
      area.append(buildGrantToggle("vary", hookTargetId, projectId, performSubmit));
    }
    if (hasRegenerate) {
      area.append(buildGrantToggle("regenerate", hookTargetId, projectId, performSubmit));
    }
    if (noticeText) {
      const notice = document.createElement("p");
      notice.className = "card-busy-notice";
      notice.textContent = noticeText;
      area.append(notice);
    }
  }

  /**
   * The one submit path both grant types' confirm forms and the retry
   * button go through. Disables every button `area` currently holds --
   * both types, any open confirm form, a retry button -- synchronously,
   * *before* the network call (condition 17, invariant 2: "с момента
   * платной отправки... выключаются сразу, до сетевого вызова, без
   * перерисовки"). Scoped to `area` alone, never the whole action row:
   * this is the one container both grant types live in, so it already
   * covers "оба типа" without also freezing this card's unrelated
   * approve/hide/retire controls for the duration of an unrelated
   * network call.
   */
  async function performSubmit(actionType, freshPayload, requestTarget = targetIds[actionType] || targetId) {
    if (submitting) return;
    submitting = true;
    noteCardFocusPending(hookTargetId, actionType);
    status.textContent = "Отправляется…";
    const controls = Array.from(
      (controlRoot || area).querySelectorAll('[data-paid-control="true"]'),
    );
    // Each control's own `disabled` is read once, before this sets any of
    // them -- exactly ui/actions.js's own `submitAction` pattern -- so a
    // re-enabling outcome below restores what was actually there, never a
    // hardcoded `false` (craft review finding 4).
    const previousDisabled = controls.map((control) => control.disabled);
    for (const control of controls) {
      control.disabled = true;
    }

    // A previous attempt for this exact target/action that never
    // confirmed its own outcome is resubmitted byte-for-byte -- never a
    // freshly typed note -- which is what keeps this idempotent no
    // matter how many times the operator (or a stale retry control)
    // resubmits a still-unresolved request.
    const baselineActionId = resolveBaselineActionId(actionEntries, requestTarget, actionType);
    const { idempotencyKey, payload, expectedRevision: revision } = resolveGrantRequest({
      projectId,
      actionType,
      targetId: requestTarget,
      freshPayload,
      freshExpectedRevision: expectedRevision,
      baselineActionId,
    });

    const result = await postAction(actionType, requestTarget, payload, revision, idempotencyKey);
    const settled = settlePendingRequest(projectId, actionType, requestTarget, result);
    submitting = false;

    if (!result.ok) {
      if (!settled) {
        // Genuinely unknown outcome (network_error/session_error --
        // condition 17, invariant 6): swap this card's grant area to
        // retry mode right here, in place, instead of restoring the
        // controls this call just disabled. A live "Перегенерировать"
        // sitting next to an unconfirmed "Вариация" is exactly the
        // second BLOCKING path this repair closes. `renderPending` sets
        // this card's one status text itself (craft review finding 3) --
        // nothing is written here, so there is never a second, stale
        // "Отправляется…"/failure line left behind underneath it.
        renderPending(actionType, requestTarget);
        return;
      }
      // The server *did* answer -- nothing was spent, free to retry
      // immediately. Each control goes back to whatever `disabled` it had
      // *before* this call touched it (never a hardcoded `false`) -- a
      // sibling control this card handed in already disabled for an
      // unrelated reason must not be silently woken up just because this
      // call's own outcome settled (craft review finding 4, the same fix
      // ui/actions.js's own `submitAction` already applies).
      status.textContent = resolveActionErrorMessage(result.code);
      controls.forEach((control, index) => {
        control.disabled = previousDisabled[index];
      });
      if (result.code === "revision_conflict") {
        requestProjectRefresh(projectId);
      }
      return;
    }

    // A 202 is full confirmation the ledger holds this request now,
    // whatever its resulting status.
    const notice = resolveCardBusyNotice(result.status);
    status.textContent = notice ? notice.text : "Действие отправлено. Ждём ответа в чате.";
    if (isInformationalGrantStatus(result.status)) {
      // No grant was reserved (needs_chat/needs_chat_setup) -- nothing
      // was spent, free to try again immediately. Restores each control's
      // own prior `disabled` -- same fix as the error branch above (craft
      // review finding 4), never a hardcoded `false`.
      controls.forEach((control, index) => {
        control.disabled = previousDisabled[index];
      });
    }
    // Otherwise (queued/running): stay disabled, exactly as the
    // synchronous lock above already left them (condition 17, bullet 5:
    // "202 queued оставляет их выключенными до snapshot"). The refresh
    // below repaints from a fresh snapshot.actions shortly and takes over.
    requestProjectRefresh(projectId);
  }

  if (grantState && grantState.kind === "pending") {
    renderPending(grantState.actionType, grantState.targetId || targetIds[grantState.actionType] || targetId);
  } else {
    renderNormal(grantState && grantState.kind === "notice" ? grantState.text : null);
  }

  return area;
}

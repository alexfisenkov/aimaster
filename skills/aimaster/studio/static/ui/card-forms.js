// Task 08 repair 1, condition 11 ("построители форм" is its own module):
// every reusable DOM control a card/stage row is built from -- a plain
// one-click button, the one shared comment form (condition 10: "одна
// форма комментария на все места"), the prompt exact-text edit form, and
// the paid vary/regenerate control (condition 1).
//
// DOM-only, verified through the browser visual gate like every DOM
// builder in this codebase (ui/timeline.js's file banner). Never calls
// `fetch` itself -- goes through `runAction`/`submitAction`/`postAction`
// (ui/actions.js), the one client every dashboard control shares.

import { resolveActionErrorMessage, submitAction } from "./actions.js";
import { resolveCardActionLabel } from "./card-model.js";
import { draftKey, getDraft, setDraft, clearDraft } from "./card-drafts.js";

export const OUTCOME_UNCONFIRMED_TEXT = "Исход не подтверждён. Обновите страницу.";
/** Строка исхода, пока запрос в полёте. */
export const SUBMITTING_TEXT = "Отправляется…";
/** Строка исхода после подтверждённого успеха кнопки без своего текста. */
export const SENT_TEXT = "Отправлено.";

/** Подтверждённый ли это успех — тот же критерий, что у лестницы исхода. */
export function isConfirmedSuccess(result) {
  return Boolean(result?.ok) && result.confirmed !== false;
}

export function buildStatusLine() {
  const status = document.createElement("p");
  status.className = "card-action-status";
  status.setAttribute("role", "status");
  return status;
}

/** Ask app.js to re-fetch this project's snapshot in place -- the one
 * function every control below (and ui/card-decorate.js/ui/stage-
 * approval.js) refreshes through (condition 10: "requestProjectRefresh...
 * из одного места"). */
export function requestProjectRefresh(projectId) {
  document.dispatchEvent(
    new CustomEvent("studio:refresh-snapshot", { bubbles: true, detail: { projectId } }),
  );
}

/**
 * Note, *before* `submitAction`/`postAction` disables the just-clicked
 * control (which happens synchronously, before their own first await, and
 * blurs a disabled focused element to `<body>` immediately -- see ui/
 * shell.js's own `ensureCardFocusListener`), which target/action this
 * click was for -- ui/shell.js's focus-restore falls back to this note
 * when its own post-repaint capture comes back empty, the same relay
 * ui/scenario.js's `studio:scene-focus-pending` already uses for the scene
 * edit form (ticket 06 condition 4; this is that same fix for card/stage
 * controls, condition 8).
 */
export function noteCardFocusPending(targetId, action) {
  document.dispatchEvent(
    new CustomEvent("studio:card-focus-pending", { bubbles: true, detail: { targetId, action } }),
  );
}

/** Exported (client repair 2) so ui/grant-action.js's own toggle/retry
 * buttons carry the exact same `data-hook="card-control"`/`data-target-id`/
 * `data-action` triple every other control here does, from this one place,
 * rather than a second copy of these three lines. */
export function markControlHooks(el, targetId, action) {
  el.dataset.hook = "card-control";
  el.dataset.targetId = targetId;
  el.dataset.action = action;
}

/**
 * The "не подтверждено / успех (+обновление) / ошибка (+обновление на
 * 409)" outcome ladder every free-decision control in this module -- plus
 * ui/card-reorder.js's own `submitReorder` -- ends its submit handler
 * with. Client repair 2's own non-blocking note 1: this exact ladder used
 * to be copy-pasted four times (`buildSimpleButton`, `buildCommentForm`,
 * `buildPromptEditControl`, `submitReorder`), each one free to drift from
 * the others.
 *
 * `saveDraft`/`clearDraftKey` are optional -- omitted for a control with
 * no draft at all (`buildSimpleButton`); given, `saveDraft` is called
 * *after* `status.textContent` is set (so a closure reading `status.
 * textContent`, exactly like every caller's own draft shape already did,
 * captures the text this function just set), and `clearDraftKey` is
 * cleared on a genuine success.
 *
 * `successText`, when given, is a brief confirmation left on screen for a
 * genuine, confirmed success before the caller's own refresh repaints it
 * away (ticket 08 condition 4: "повторная отправка того же решения не
 * выглядит так, будто ничего не произошло"); omitted, a success clears
 * the status line silently and relies on the refresh alone -- the shape
 * every comment/edit form already had (typing a new comment is its own
 * visible feedback; a plain decision button is not).
 *
 * Deliberately does not cover ui/grant-action.js's own `performSubmit`:
 * that is not a copy of this same ladder but a different protocol
 * (transport-failure vs. a real error are different outcomes there, and
 * `postAction` is called directly, never through `runAction`/
 * `submitAction`'s `{confirmed}` shape this ladder reads) -- see that
 * module's own file banner.
 */
export function finishFreeActionSubmit({ result, status, projectId, saveDraft, clearDraftKey, successText }) {
  if (result.ok && result.confirmed !== false) {
    status.textContent = successText || "";
    if (clearDraftKey) {
      clearDraft(clearDraftKey);
    }
    requestProjectRefresh(projectId);
    return;
  }
  if (result.ok) {
    status.textContent = OUTCOME_UNCONFIRMED_TEXT;
    if (saveDraft) {
      saveDraft();
    }
    return;
  }
  status.textContent = resolveActionErrorMessage(result.code);
  if (saveDraft) {
    saveDraft();
  }
  if (result.code === "revision_conflict") {
    requestProjectRefresh(projectId);
  }
}

/** A single-click action (`approve`/`hide`/`unhide`/`retire`/`restore`/
 * `continue-in-chat`): no comment, submits immediately through
 * `submitAction`. On a genuine success the status line keeps a short
 * confirmation instead of going blank (ticket 08 condition 4: "повторная
 * отправка того же решения не выглядит так, будто ничего не произошло")
 * -- brief, since the refresh this triggers repaints the whole row from
 * the fresh snapshot moments later, but never simply silent.
 *
 * `awaitUpdate` (client repair 2) defaults to `true` -- every existing
 * caller's action is applied by the decisions worker and does bump the
 * project's own revision, so the default wait-for-it behaviour stays
 * exactly as it was. `continue-in-chat` (ui/card-decorate.js's own
 * "Вернуться в чат" control) passes `false`: it is a chat-queue hand-off,
 * never applied by this process at all, so waiting up to ~10s for a
 * revision move that is never coming would only delay -- and then
 * misreport as unconfirmed -- a click that actually succeeded (the same
 * reasoning ui/actions.js's own `runAction` banner documents for
 * `revise-scenario`). */
export function buildSimpleButton({
  actionType,
  targetId,
  hookTargetId = targetId,
  expectedRevision,
  projectId,
  row,
  status,
  label,
  hookAction,
  awaitUpdate = true,
  successText = SENT_TEXT,
  requireActionSuccess = false,
  onSettled,
}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "card-action-button";
  // `hookAction` (repair condition 8/interfaces.md's task-08 hooks list)
  // lets a stage-level decision keep its own documented `data-action`
  // value (`approve-stage`) distinct from the wire-level `action_type`
  // ("approve") the very same click actually submits -- the server tells
  // the two apart by `target_id`, never by a second action-type
  // vocabulary, but the DOM/CSS hook contract still wants them visibly
  // different (styles/actions.css already selects on both).
  markControlHooks(button, hookTargetId, hookAction || actionType);
  button.textContent = label || resolveCardActionLabel(actionType) || actionType;
  button.addEventListener("click", async () => {
    // The note's own `action` must match this control's *own*
    // `data-action` (`hookAction || actionType`, exactly what
    // `markControlHooks` just set two lines up) -- not the bare wire-level
    // `actionType` a stage decision's `hookAction` deliberately
    // overrides. Repair 2's own craft-review fix: "У «Одобрить стадию»
    // сейчас отметка approve, а хук approve-stage" -- a focus-restore
    // lookup keyed on the note's `action` used to search for a control
    // that does not exist, so a stage decision's own focus never came
    // back.
    noteCardFocusPending(hookTargetId, hookAction || actionType);
    status.textContent = SUBMITTING_TEXT;
    const siblingButtons = Array.from(row.querySelectorAll("button"));
    const result = await submitAction({
      actionType,
      targetId,
      payload: {},
      expectedRevision,
      controls: siblingButtons,
      awaitUpdate,
      requireActionSuccess,
    });
    finishFreeActionSubmit({ result, status, projectId, successText });
    if (typeof onSettled === "function") onSettled(result, isConfirmedSuccess(result));
  });
  return button;
}

/**
 * The one shared comment form (condition 10) -- a toggle button that
 * reveals a textarea + Отправить/Отмена, submitting `{comment}` as
 * `actionType`'s payload. Used for both a card's own `reject`
 * (ui/card-decorate.js) and a stage's `reject-stage`
 * (ui/stage-approval.js) -- the two used to be near-identical, separately
 * maintained copies. The draft (open state + typed text + last message)
 * survives a repaint via ui/card-drafts.js, keyed by whatever `key` the
 * caller already computed (a card's own `draftKey(projectId, kind,
 * targetId)`, or a stage's `draftKey(projectId, "stage", stage)`).
 */
export function buildCommentForm({
  actionType,
  targetId,
  hookTargetId = targetId,
  expectedRevision,
  projectId,
  key,
  row,
  status,
  focusHookAction,
  toggleLabel,
  requireActionSuccess = false,
  onSettled,
}) {
  const draft = getDraft(key);

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "card-action-button";
  markControlHooks(toggle, hookTargetId, focusHookAction || actionType);
  toggle.textContent = toggleLabel || resolveCardActionLabel(actionType) || actionType;

  const form = document.createElement("form");
  form.className = "card-comment-form";
  form.hidden = !draft?.open;

  const label = document.createElement("label");
  label.className = "card-comment-label";
  const caption = document.createElement("span");
  caption.textContent = "Комментарий";
  const textarea = document.createElement("textarea");
  textarea.className = "card-comment-textarea";
  // Repair, ticket 14 (review blocker G04: text typed into this field while
  // a real, unrelated repaint lands -- e.g. a chat record arriving during
  // the background poll -- used to go nowhere, because this field carried
  // no `card-control` hook at all and ui/shell.js's captureLiveCardControlFocus/
  // repaintZonePreservingFocus therefore had nothing to find it by. A distinct action
  // (`"<toggle's own action>-comment"`, never just `focusHookAction ||
  // actionType` again) is what keeps this field's own hook from colliding
  // with the toggle button's identical target id -- the two must resolve to
  // two different exact matches, not one ambiguous one. Value-on-repaint
  // already comes for free from the draft below (`saveDraft` on every
  // keystroke); this hook is what lets shell.js's already-generic
  // captureTextSelection/applyTextSelection carry the cursor position too.
  markControlHooks(textarea, hookTargetId, `${focusHookAction || actionType}-comment`);
  textarea.value = draft ? draft.text : "";
  label.append(caption, textarea);

  form.append(label, status);

  const actionsRow = document.createElement("div");
  actionsRow.className = "card-comment-actions";
  const submitButton = document.createElement("button");
  submitButton.type = "submit";
  submitButton.textContent = "Отправить";
  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.textContent = "Отмена";
  actionsRow.append(submitButton, cancelButton);
  form.append(actionsRow);

  // Restore whatever message a previous, interrupted attempt left (a 409,
  // a network error) -- same shape ui/scenario.js's own edit form already
  // proved (that module's `buildEditControl`).
  status.textContent = draft ? draft.message || "" : "";

  function saveDraft() {
    setDraft(key, { open: !form.hidden, text: textarea.value, message: status.textContent });
  }

  toggle.addEventListener("click", () => {
    form.hidden = !form.hidden;
    if (!form.hidden) {
      textarea.focus();
    }
    saveDraft();
  });
  textarea.addEventListener("input", saveDraft);
  cancelButton.addEventListener("click", () => {
    form.hidden = true;
    textarea.value = "";
    status.textContent = "";
    clearDraft(key);
    toggle.focus();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    noteCardFocusPending(hookTargetId, focusHookAction || actionType);
    status.textContent = SUBMITTING_TEXT;
    saveDraft();
    const siblingButtons = Array.from(row.querySelectorAll("button"));
    const result = await submitAction({
      actionType,
      targetId,
      payload: { comment: textarea.value.trim() },
      expectedRevision,
      controls: siblingButtons,
      requireActionSuccess,
    });
    finishFreeActionSubmit({ result, status, projectId, saveDraft, clearDraftKey: key });
    if (typeof onSettled === "function") onSettled(result, isConfirmedSuccess(result));
  });

  const wrap = document.createElement("div");
  wrap.className = "card-comment-wrap";
  wrap.append(toggle, form);
  return wrap;
}

/** `edit` on an image prompt: exact-text rewrite (spec §7), a text field
 * plus a required reason, submitted through the same shared
 * `submitAction`. Kept separate from `buildCommentForm` -- two required
 * fields and different validation, not the same shape. */
export function buildPromptEditControl({ targetId, expectedRevision, projectId, currentText, row, status }) {
  const key = draftKey(projectId, "prompt-edit", targetId);
  const draft = getDraft(key);

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "card-action-button";
  markControlHooks(toggle, targetId, "edit");
  toggle.textContent = "Править";

  const form = document.createElement("form");
  form.className = "card-comment-form";
  form.hidden = !draft?.open;

  const textLabel = document.createElement("label");
  textLabel.className = "card-comment-label";
  const textCaption = document.createElement("span");
  textCaption.textContent = "Текст промпта";
  const textarea = document.createElement("textarea");
  textarea.className = "card-comment-textarea";
  // Repair, ticket 14 (review blocker G04) -- same fix and same reasoning
  // as buildCommentForm's own textarea above: `"edit-text"` never collides
  // with the toggle's own `"edit"` hook, or with `reasonInput`'s own
  // `"edit-reason"` below, so an exact card-control match after a repaint
  // always lands back on the one field that was actually focused.
  markControlHooks(textarea, targetId, "edit-text");
  textarea.value = draft ? draft.text : currentText;
  textLabel.append(textCaption, textarea);

  const reasonLabel = document.createElement("label");
  reasonLabel.className = "card-comment-label";
  const reasonCaption = document.createElement("span");
  reasonCaption.textContent = "Причина правки";
  const reasonInput = document.createElement("input");
  reasonInput.type = "text";
  reasonInput.className = "card-comment-textarea";
  markControlHooks(reasonInput, targetId, "edit-reason");
  reasonInput.value = draft ? draft.reason : "";
  reasonLabel.append(reasonCaption, reasonInput);

  const actionsRow = document.createElement("div");
  actionsRow.className = "card-comment-actions";
  const saveButton = document.createElement("button");
  saveButton.type = "submit";
  saveButton.textContent = "Сохранить";
  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.textContent = "Отмена";
  actionsRow.append(saveButton, cancelButton);
  form.append(textLabel, reasonLabel, status, actionsRow);

  status.textContent = draft ? draft.message || "" : "";

  function saveDraft() {
    setDraft(key, { open: !form.hidden, text: textarea.value, reason: reasonInput.value, message: status.textContent });
  }

  toggle.addEventListener("click", () => {
    form.hidden = !form.hidden;
    if (!form.hidden) {
      textarea.focus();
    }
    saveDraft();
  });
  textarea.addEventListener("input", saveDraft);
  reasonInput.addEventListener("input", saveDraft);
  cancelButton.addEventListener("click", () => {
    form.hidden = true;
    textarea.value = currentText;
    reasonInput.value = "";
    status.textContent = "";
    clearDraft(key);
    toggle.focus();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = textarea.value.trim();
    const reason = reasonInput.value.trim();
    if (!text || !reason) {
      status.textContent = "Заполните текст и причину правки.";
      saveDraft();
      return;
    }
    noteCardFocusPending(targetId, "edit");
    status.textContent = "Сохраняется…";
    saveDraft();
    const siblingButtons = Array.from(row.querySelectorAll("button"));
    const result = await submitAction({
      actionType: "edit",
      targetId,
      payload: { text, reason },
      expectedRevision,
      controls: siblingButtons,
    });
    finishFreeActionSubmit({ result, status, projectId, saveDraft, clearDraftKey: key });
  });

  const wrap = document.createElement("div");
  wrap.className = "card-comment-wrap";
  wrap.append(toggle, form);
  return wrap;
}

// `vary`/`regenerate` (condition 1) moved to ui/grant-action.js in client
// repair 2 -- see that module's own file banner for why: the DOM for both
// grant types now has to be built and torn down together, so one
// unconfirmed request's own submit path can lock (and, on a transport
// failure, retry-swap) both types at once, in place, without a redraw.
// ui/card-decorate.js's `buildCardActionsRow` calls `buildGrantArea`
// there instead of this module's `buildGrantAction`, which no longer
// exists.

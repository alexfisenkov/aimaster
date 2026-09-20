// The dashboard's own answer surface for the shared Question contract
// (spec §6, ticket 14): "модальное окно с выбором, полем «Свой вариант»,
// подсказкой и доступной клавиатурой; закрытие сохраняет вопрос как
// ожидающий." `snapshot.questions` (task 01's `QuestionStore.pending`
// projection) is the only source -- this module never talks to
// `state.json` or any server internals, only `POST
// /api/questions/{id}/answers` through ui/actions.js's `postQuestionAnswer`.
// Validation/payload/description logic lives in ./question-model.js (pure,
// no `document` at all); this module owns only the DOM singleton overlay
// and its focus lifecycle.
//
// A DOM singleton overlay, built once and reused on every open (same shape
// as ui/viewer.js's own `ensureOverlay`/`openOverlay` -- see that module's
// own file banner for why a shared, rebuilt-in-place overlay beats tearing
// one down and rebuilding it per open). Opened only via the bubbling
// `studio:open-question` DOM event (never a direct call from another
// module -- same decoupling ui/media.js's `studio:open-viewer` already
// uses), wired once from app.js via `attachQuestionOpenListener()`.
//
// Liveness (ticket 14): chat-authored answers never emit SSE (see
// ui/shell-runtime.js's own liveness banner), so a question this modal has
// open can be closed by another channel entirely between one snapshot poll
// and the next. `syncQuestionModalWithQuestions(questions)` -- called from
// app.js on every store commit, right alongside `renderShell` -- is what
// notices that and closes the modal with a neutral "Ответ уже получен",
// returning focus to whatever opened it. That is a different case from a
// `409 already_answered` hitting *this* modal's own in-flight submit (a
// last-instant race, not a poll): that one keeps the dialog open and shows
// the accepted answer read-only -- "без перезаписи и без повтора" -- rather
// than silently vanishing out from under someone mid-click.

import { postQuestionAnswer, resolveActionErrorMessage } from "./actions.js";
import {
  QUESTION_KIND_TABLE,
  buildAnswerPayload,
  describeAnswer,
  describeValidationHint,
  resolveSubtitle,
  showsCustomSection,
  validationOf,
} from "./question-model.js";

// -----------------------------------------------------------------------
// DOM helpers -- verified only through the browser visual gate plus
// tests/ui/question-modal.test.mjs's fake-DOM (tests/ui/support/
// dom-stubs.mjs) run -- no real `document` under plain `node --test`.
// -----------------------------------------------------------------------

let overlayRefs = null;
let liveRegionEl = null;

/** Duck-typed "is a real element node", true for both a genuine DOM
 * element and tests/ui/support/dom-stubs.mjs's own `FakeElement` alike --
 * deliberately not `instanceof HTMLElement`: plain Node (this project's
 * `node --test`, no DOM/jsdom at all) has no global `HTMLElement` to check
 * against in the first place, and the fake DOM's own elements are not
 * instances of it either way. `nodeType === 1` (`Node.ELEMENT_NODE`) is the
 * one signal both environments genuinely share -- a `document` itself
 * (nodeType 9) never satisfies it, which is exactly what lets
 * `attachQuestionOpenListener` below tell a real element `event.target`
 * apart from one dispatched on `document` directly. */
function isElement(value) {
  return Boolean(value) && typeof value === "object" && value.nodeType === 1;
}

/** Whether `node` is `ancestor` itself or a descendant of it -- walks
 * `.parentNode` up rather than calling `ancestor.contains(node)` (real DOM
 * only; neither `FakeElement` nor `FakeDocument` in tests/ui/support/
 * dom-stubs.mjs implement any `contains` method at all), so this works
 * identically in the browser and under the fake DOM used by
 * tests/ui/question-modal.test.mjs. */
function elementContains(ancestor, node) {
  let current = node;
  while (current) {
    if (current === ancestor) {
      return true;
    }
    current = current.parentNode;
  }
  return false;
}

/** Whether `el` is still attached to `document` at all. */
function isAttached(el) {
  return elementContains(document, el);
}

function liveRegion() {
  if (!liveRegionEl || !isAttached(liveRegionEl)) {
    liveRegionEl = document.querySelector('[data-hook="live-region"]');
  }
  return liveRegionEl;
}

function announce(text) {
  const region = liveRegion();
  if (region) {
    region.textContent = text;
  }
}

// Every focusable-by-tag-semantics element inside `dialog`, in true DOM
// order. Deliberately a manual `childNodes` walk, not a single
// `querySelectorAll('button, [href], input, ...')` call (as ui/viewer.js's
// own `focusableInDialog` uses): tests/ui/support/dom-stubs.mjs's selector
// engine (see that module's own file banner) supports one simple selector
// or a whitespace descendant chain, never a comma-separated list, and has
// no `:not()` at all -- exactly the shape that selector needs. Walking the
// tree directly also guarantees real document order for free (each node's
// own `childNodes` is already in append order, in both the real DOM and
// the fake one), which is what the Tab-trap's own first/last below
// actually depends on.
const FOCUSABLE_TAGS = new Set(["BUTTON", "INPUT", "TEXTAREA", "SELECT", "A"]);

/**
 * Ticket 14 repair, condition 5: a `hidden` element's own subtree is
 * skipped entirely, not merely excluded itself -- the previous version
 * checked each child's *own* `.hidden` before deciding whether to collect
 * it, but then recursed into that child's children unconditionally either
 * way. That let a genuinely hidden branch (the custom-text section for a
 * question that does not offer one; the accepted-answer view while the
 * form itself is showing) still contribute its own descendants to the
 * trap's own first/last -- in the accepted view's case, a real `<button>`
 * several DOM levels below `dialog`, past the visible footer, which is
 * exactly what let Tab from "Продолжить" escape the dialog outright
 * (nothing after it in `focusable` was truly reachable, so the browser's
 * own default Tab took over) and left Shift+Tab from "Закрыть" appearing
 * to do nothing at all (it tried to focus that same hidden button, which a
 * real browser silently refuses).
 */
function collectFocusable(node, out) {
  for (const child of node.childNodes) {
    if (child.nodeType !== 1 || child.hidden) {
      continue; // a hidden element's own subtree never contributes a focus target
    }
    const optedOut = typeof child.tabIndex === "number" && child.tabIndex < 0;
    if (FOCUSABLE_TAGS.has(child.tagName) && !child.disabled && !optedOut) {
      out.push(child);
    }
    collectFocusable(child, out);
  }
  return out;
}

function focusableInDialog(dialog) {
  return collectFocusable(dialog, []);
}

function trapTabKey(event, dialog) {
  if (event.key !== "Tab") {
    return;
  }
  const focusable = focusableInDialog(dialog);
  if (focusable.length === 0) {
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  const active = document.activeElement;
  if (!elementContains(dialog, active)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
    return;
  }
  if (event.shiftKey && active === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && active === last) {
    event.preventDefault();
    first.focus();
  }
}

// Tags focusable by their own tag semantics, with no `tabindex` attribute
// needed at all -- the real-browser default this codebase's own fake DOM
// (tests/ui/support/dom-stubs.mjs's `FakeElement`) does not separately
// model: a plain `document.createElement("button")` there carries no
// `tabIndex` property until something sets one, unlike a real `<button>`,
// which is keyboard-focusable out of the box. Checking `tagName` instead
// of relying on `tabIndex >= 0` (as ui/viewer.js's own `isFocusable` does)
// is what makes this module's own close-focus-restore path exercisable
// under `node --test`, not only the browser visual gate.
const NATIVELY_FOCUSABLE_TAGS = new Set(["BUTTON", "INPUT", "TEXTAREA", "SELECT"]);

function isFocusable(el) {
  if (!isElement(el) || !isAttached(el) || el.disabled || el.hidden) {
    return false;
  }
  if (typeof el.tabIndex === "number" && el.tabIndex < 0) {
    return false; // explicit opt-out (the backdrop button sets exactly this)
  }
  return NATIVELY_FOCUSABLE_TAGS.has(el.tagName) || (typeof el.tabIndex === "number" && el.tabIndex >= 0);
}

/** The trigger to refocus on close: `trigger` itself when still attached
 * and focusable, otherwise whichever live `[data-hook="question-open"]`
 * now carries the same question id (a repaint -- e.g. task 14's own
 * background poll -- may have rebuilt the questions panel/list while the
 * modal was open). `null` when neither exists; `closeQuestionModal` then
 * falls back to whatever held focus right before the modal opened. */
function resolveFocusTarget(trigger, questionId) {
  if (isFocusable(trigger)) {
    return trigger;
  }
  if (!questionId || typeof CSS === "undefined" || typeof CSS.escape !== "function") {
    return null;
  }
  return document.querySelector(`[data-hook="question-open"][data-question-id="${CSS.escape(questionId)}"]`);
}

function buildOptionRow({ inputType, name, value, label, description, checked, onChange }) {
  const li = document.createElement("li");
  li.className = "question-modal-option";
  li.dataset.hook = "question-modal-option";
  li.dataset.selected = String(Boolean(checked));
  if (typeof value === "string") {
    li.dataset.optionId = value;
  }

  const row = document.createElement("label");
  row.className = "question-modal-option-row";

  const input = document.createElement("input");
  input.type = inputType;
  input.name = name;
  input.className = "question-modal-option-input";
  input.value = value;
  input.checked = Boolean(checked);
  input.addEventListener("change", () => onChange(input));

  const body = document.createElement("span");
  body.className = "question-modal-option-body";
  const labelEl = document.createElement("span");
  labelEl.className = "question-modal-option-label";
  labelEl.textContent = label;
  body.append(labelEl);
  if (description) {
    const descEl = document.createElement("span");
    descEl.className = "question-modal-option-description";
    descEl.textContent = description;
    body.append(descEl);
  }

  row.append(input, body);
  li.append(row);
  // `data-selected` itself is kept in sync by each `onChange` callback
  // above (buildOptionsForKind), not here -- a radio group's own callback
  // also has to *clear* every other row's flag when one is picked, which a
  // plain per-row click listener has no way to do; duplicating a second,
  // narrower version of that logic here would just be a second place for
  // the two to drift apart.
  return { li, input };
}

function buildOverlay() {
  const overlay = document.createElement("div");
  overlay.className = "question-modal-overlay";
  overlay.dataset.hook = "question-modal";
  overlay.hidden = true;

  const backdrop = document.createElement("button");
  backdrop.type = "button";
  backdrop.className = "question-modal-backdrop";
  backdrop.dataset.hook = "question-modal-backdrop";
  backdrop.setAttribute("aria-hidden", "true");
  backdrop.tabIndex = -1;
  backdrop.addEventListener("click", () => closeQuestionModal());

  const dialog = document.createElement("div");
  dialog.className = "question-modal-dialog";
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  dialog.setAttribute("aria-labelledby", "question-modal-title");

  const header = document.createElement("div");
  header.className = "question-modal-header";
  const icon = document.createElement("span");
  icon.className = "question-modal-icon";
  icon.setAttribute("aria-hidden", "true");
  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "question-modal-close";
  closeButton.dataset.hook = "question-modal-close";
  const closeLabel = document.createElement("span");
  closeLabel.className = "visually-hidden";
  closeLabel.textContent = "Закрыть";
  closeButton.append(closeLabel);
  closeButton.addEventListener("click", () => closeQuestionModal());
  header.append(icon, closeButton);

  const title = document.createElement("h2");
  title.className = "question-modal-title";
  title.id = "question-modal-title";

  const subtitle = document.createElement("p");
  subtitle.className = "question-modal-subtitle";
  subtitle.dataset.hook = "question-modal-subtitle";

  const form = document.createElement("form");
  form.className = "question-modal-form";
  form.dataset.hook = "question-modal-form";

  const optionsList = document.createElement("ul");
  optionsList.className = "question-modal-options";
  optionsList.dataset.hook = "question-modal-options";

  const customSection = document.createElement("div");
  customSection.className = "question-modal-custom";
  customSection.dataset.hook = "question-modal-custom";
  customSection.hidden = true;
  const customLabel = document.createElement("label");
  customLabel.className = "question-modal-custom-label";
  const customLabelText = document.createElement("span");
  customLabelText.textContent = "Свой вариант";
  const customTextarea = document.createElement("textarea");
  customTextarea.className = "question-modal-custom-textarea";
  customTextarea.dataset.hook = "question-modal-custom-textarea";
  customTextarea.rows = 3;
  customLabel.append(customLabelText, customTextarea);
  // Ticket 14 repair, condition 8: the format hint is a permanent line
  // under the field, filled in by `configureCustomSection` on every open --
  // never only surfaced inside `refs.status` after a rejected submit.
  const customHint = document.createElement("p");
  customHint.className = "question-modal-hint";
  customHint.dataset.hook = "question-modal-custom-hint";
  const customCounter = document.createElement("span");
  customCounter.className = "question-modal-custom-counter";
  customCounter.dataset.hook = "question-modal-custom-counter";
  customSection.append(customLabel, customHint, customCounter);

  const status = document.createElement("p");
  status.className = "question-modal-status";
  status.dataset.hook = "question-modal-status";
  status.setAttribute("role", "status");

  const footer = document.createElement("div");
  footer.className = "question-modal-footer";
  const deferButton = document.createElement("button");
  deferButton.type = "button";
  deferButton.className = "question-modal-defer";
  deferButton.dataset.hook = "question-modal-defer";
  deferButton.textContent = "Отложить";
  deferButton.addEventListener("click", () => closeQuestionModal());
  const submitButton = document.createElement("button");
  submitButton.type = "submit";
  submitButton.className = "question-modal-submit";
  submitButton.dataset.hook = "question-modal-submit";
  submitButton.textContent = "Продолжить";
  footer.append(deferButton, submitButton);

  form.append(optionsList, customSection, status, footer);

  const acceptedView = document.createElement("div");
  acceptedView.className = "question-modal-accepted";
  acceptedView.dataset.hook = "question-modal-accepted";
  acceptedView.hidden = true;
  const acceptedText = document.createElement("p");
  acceptedText.className = "question-modal-accepted-text";
  acceptedText.dataset.hook = "question-modal-accepted-text";
  const acceptedFooter = document.createElement("div");
  acceptedFooter.className = "question-modal-footer";
  const acceptedCloseButton = document.createElement("button");
  acceptedCloseButton.type = "button";
  acceptedCloseButton.className = "question-modal-submit";
  acceptedCloseButton.dataset.hook = "question-modal-accepted-close";
  acceptedCloseButton.textContent = "Закрыть";
  acceptedCloseButton.addEventListener("click", () => closeQuestionModal());
  acceptedFooter.append(acceptedCloseButton);
  acceptedView.append(acceptedText, acceptedFooter);

  dialog.append(header, title, subtitle, form, acceptedView);
  overlay.append(backdrop, dialog);
  document.body.append(overlay);

  // Same reasoning as ui/viewer.js's own handleDocumentKeydown: listens on
  // `document`, not `overlay`, so Escape/Tab keep working after a real
  // mouse click blurs focus to `<body>` (a non-focusable target inside the
  // dialog). Ticket 14 repair, condition 5: built here but *attached* only
  // by `openQuestionModal`/detached by `closeQuestionModal` (see
  // `keydownActive` below) -- never once, permanently, at build time the
  // way this used to work. The old, always-on listener kept intercepting
  // every Tab/Escape press on the *whole page* forever after the very
  // first open, since `trapTabKey` runs against `dialog`'s own focusable
  // set regardless of whether `overlay.hidden` is true.
  const handleDocumentKeydown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeQuestionModal();
      return;
    }
    trapTabKey(event, dialog);
  };

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitAnswer();
  });

  // Attached exactly once, here, on the persistent singleton textarea --
  // not per-open (`configureCustomSection` re-runs on every
  // `openQuestionModal`, and re-adding a fresh closure there each time
  // would stack a new listener on the very same element every single
  // open, since this overlay chrome is reused rather than rebuilt). Reads
  // `currentQuestion`/`currentSelection` fresh from module state instead
  // of closing over a specific open's `question`, so there is never a
  // stale handler left over from a previous question to race with.
  customTextarea.addEventListener("input", () => {
    if (!currentSelection) {
      return;
    }
    currentSelection.customText = customTextarea.value;
    updateCustomCounter(overlayRefs);
    if (customTextarea.value.trim() && currentQuestion && currentQuestion.kind === "single") {
      // Mutually exclusive with a radio pick (server's `single` answer is
      // one string only) -- typing a custom answer clears whichever
      // option was selected, mirroring the reverse in buildOptionsForKind.
      currentSelection.selectedOptionId = "";
      for (const input of optionsList.querySelectorAll(".question-modal-option-input")) {
        input.checked = false;
      }
      for (const row of optionsList.querySelectorAll('[data-hook="question-modal-option"]')) {
        row.dataset.selected = "false";
      }
    }
  });

  return {
    overlay,
    dialog,
    icon,
    closeButton,
    title,
    subtitle,
    form,
    optionsList,
    customSection,
    customTextarea,
    customHint,
    customCounter,
    status,
    deferButton,
    submitButton,
    acceptedView,
    acceptedText,
    acceptedCloseButton,
    handleDocumentKeydown,
  };
}

function ensureOverlay() {
  if (!overlayRefs) {
    overlayRefs = buildOverlay();
  }
  return overlayRefs;
}

// Selection state for whichever question is currently open -- reset on
// every `openQuestionModal` call, read only by `submitAnswer`.
let currentQuestion = null;
let currentSelection = null;
let currentTrigger = null;
let currentTriggerDescriptor = null;
let submitting = false;
// Ticket 14 repair, condition 5: whether `overlayRefs.handleDocumentKeydown`
// is currently attached to `document` -- true for exactly the span between
// an `openQuestionModal` call and the matching `closeQuestionModal`, never
// longer. Guards against a double-attach if `openQuestionModal` is ever
// called again while already open (defensive only: the overlay's own
// backdrop should make that unreachable in practice) and lets
// `closeQuestionModal` detach unconditionally-but-safely.
let keydownActive = false;
// `closeQuestionModal`'s last-resort focus fallback -- whatever held focus
// right before *this* open, captured fresh on every `openQuestionModal`/
// `showAcceptedAnswer` call (never only once, inside `buildOverlay`, the
// way ui/viewer.js's own otherwise-identical pattern does it): a question's
// own trigger is far more likely than a media card to have been removed
// from the DOM by the time close runs at all -- answering a question
// anywhere always makes ui/question-panel.js's own `renderQuestionsPanel`
// stop rendering it entirely (ticket 14's own liveness: a chat answer
// closes this modal, and `resolveFocusTarget` then finds neither the
// original trigger element nor any live one to re-find by descriptor) --
// so a *stale*, one-time-only capture from whenever the overlay singleton
// happened to first build left focus stranded on `<body>` on exactly the
// case this whole mechanism most needs to cover.
let openedFromElement = null;

function resetSelection() {
  currentSelection = {
    selectedOptionId: "",
    selectedOptionIds: [],
    customText: "",
    freeText: "",
    confirmValue: null,
  };
  return currentSelection;
}

function clearCustomText(refs) {
  currentSelection.customText = "";
  refs.customTextarea.value = "";
  updateCustomCounter(refs);
}

function updateCustomCounter(refs) {
  const validation = validationOf(currentQuestion);
  const maxLength = validation.max_length;
  if (typeof maxLength === "number") {
    refs.customCounter.hidden = false;
    refs.customCounter.textContent = `${refs.customTextarea.value.length}/${maxLength}`;
  } else {
    refs.customCounter.hidden = true;
    refs.customCounter.textContent = "";
  }
}

/** Builds the shared options `<ul>` for whichever `kind` is open --
 * `single`/`multi` read real rows from `question.options` (radio/checkbox
 * per `QUESTION_KIND_TABLE[kind].inputType`); `confirm`'s two rows are
 * fixed Yes/No, never sourced from `question.options` at all (the server
 * never reads `allow_custom` for that kind either, see
 * ./question-model.js's own `describeConfirm`); `free_text` uses none of
 * this at all (`configureFreeText` appends its own single field instead).
 */
function buildOptionsForKind(refs, question) {
  refs.optionsList.textContent = "";
  const options = Array.isArray(question.options) ? question.options : [];
  const kind = question.kind;
  const entry = QUESTION_KIND_TABLE[kind];

  if (kind === "single" || kind === "multi") {
    const inputType = entry.inputType;
    for (const option of options) {
      const { li } = buildOptionRow({
        inputType,
        name: "question-modal-option",
        value: option.id,
        label: option.label,
        description: option.description,
        checked: false,
        onChange: (input) => {
          if (kind === "single") {
            currentSelection.selectedOptionId = input.checked ? option.id : "";
            if (input.checked) {
              clearCustomText(refs);
            }
            for (const row of refs.optionsList.querySelectorAll('[data-hook="question-modal-option"]')) {
              row.dataset.selected = String(row.dataset.optionId === currentSelection.selectedOptionId);
            }
          } else {
            const set = new Set(currentSelection.selectedOptionIds);
            if (input.checked) {
              set.add(option.id);
            } else {
              set.delete(option.id);
            }
            currentSelection.selectedOptionIds = [...set];
            li.dataset.selected = String(input.checked);
          }
        },
      });
      refs.optionsList.append(li);
    }
  } else if (kind === "confirm") {
    const yes = buildOptionRow({
      inputType: entry.inputType,
      name: "question-modal-option",
      value: "yes",
      label: "Да",
      checked: false,
      onChange: () => {
        currentSelection.confirmValue = true;
      },
    });
    const no = buildOptionRow({
      inputType: entry.inputType,
      name: "question-modal-option",
      value: "no",
      label: "Нет",
      checked: false,
      onChange: () => {
        currentSelection.confirmValue = false;
      },
    });
    refs.optionsList.append(yes.li, no.li);
  }

  refs.optionsList.hidden = !(entry && entry.usesOptions);
}

/** Resets the persistent custom-text section for the question just opened
 * (value, `maxlength`, format hint, counter, visibility) -- the section's
 * own `input` listener is attached exactly once, in `buildOverlay`, and
 * reads current module state itself rather than being re-registered here
 * on every open (see that listener's own comment for why re-registering
 * per-open would leak a stale handler). */
function configureCustomSection(refs, question) {
  const showCustom = showsCustomSection(question);
  refs.customSection.hidden = !showCustom;
  refs.customTextarea.value = "";
  const validation = validationOf(question);
  if (typeof validation.max_length === "number") {
    refs.customTextarea.maxLength = validation.max_length;
  } else {
    refs.customTextarea.removeAttribute("maxlength");
  }
  refs.customHint.textContent = describeValidationHint(validation) || "";
  updateCustomCounter(refs);
}

function configureFreeText(refs, question) {
  if (question.kind !== "free_text") {
    return;
  }
  const validation = validationOf(question);
  const wrap = document.createElement("li");
  wrap.className = "question-modal-option question-modal-free-text-wrap";
  const label = document.createElement("label");
  label.className = "question-modal-custom-label";
  const labelText = document.createElement("span");
  labelText.textContent = "Ответ";
  const textarea = document.createElement("textarea");
  textarea.className = "question-modal-custom-textarea";
  textarea.dataset.hook = "question-modal-free-text";
  textarea.rows = 4;
  if (typeof validation.max_length === "number") {
    textarea.maxLength = validation.max_length;
  }
  textarea.addEventListener("input", () => {
    if (currentSelection) {
      currentSelection.freeText = textarea.value;
    }
  });
  label.append(labelText, textarea);
  wrap.append(label);
  // Ticket 14 repair, condition 8: same proactive format hint the custom
  // section shows, rebuilt here since `free_text`'s own field is rebuilt
  // fresh on every open (`buildOptionsForKind` clears `optionsList` first).
  const hintText = describeValidationHint(validation);
  if (hintText) {
    const hint = document.createElement("p");
    hint.className = "question-modal-hint";
    hint.dataset.hook = "question-modal-free-text-hint";
    hint.textContent = hintText;
    wrap.append(hint);
  }
  refs.optionsList.append(wrap);
  refs.optionsList.hidden = false;
}

function resetStatus(refs) {
  refs.status.textContent = "";
}

/**
 * Open the modal for `question` (the full public `Question` object, as
 * `snapshot.questions[]`/`studio:open-question`'s own detail carries it --
 * never re-fetched here). `trigger` regains focus on close.
 */
export function openQuestionModal(question, { trigger } = {}) {
  if (!question || typeof question.question_id !== "string") {
    return;
  }
  // Captured before `ensureOverlay()`/anything else below can steal focus.
  openedFromElement = isElement(document.activeElement) ? document.activeElement : null;
  const refs = ensureOverlay();
  if (!keydownActive) {
    document.addEventListener("keydown", refs.handleDocumentKeydown);
    keydownActive = true;
  }
  currentQuestion = question;
  resetSelection();
  currentTrigger = isElement(trigger) ? trigger : null;
  currentTriggerDescriptor = question.question_id;

  refs.title.textContent = question.text || "";
  refs.subtitle.textContent = resolveSubtitle(question);
  buildOptionsForKind(refs, question);
  configureFreeText(refs, question);
  configureCustomSection(refs, question);
  resetStatus(refs);

  refs.form.hidden = false;
  refs.acceptedView.hidden = true;
  refs.overlay.hidden = false;
  submitting = false;
  refs.submitButton.disabled = false;
  refs.deferButton.disabled = false;

  // First real control, not the close button (ticket 14: "модал удерживает
  // и возвращает фокус" -- landing on the first substantive choice reads
  // better than always starting on the dismiss action).
  const firstFocusable = focusableInDialog(refs.dialog).find((el) => el !== refs.closeButton) || refs.closeButton;
  firstFocusable.focus();
}

function showAcceptedAnswer(question, answer, { announceText } = {}) {
  const refs = ensureOverlay();
  refs.form.hidden = true;
  refs.acceptedView.hidden = false;
  const described = describeAnswer(question, answer);
  refs.acceptedText.textContent = described
    ? `Ответ уже принят: ${described}`
    : "Ответ уже принят.";
  refs.overlay.hidden = false;
  refs.acceptedCloseButton.focus();
  if (announceText) {
    announce(announceText);
  }
}

/**
 * Ticket 14 repair, condition 6: removes `questionId`'s own row from
 * ui/question-panel.js's always-visible list *immediately* on a successful
 * dashboard submit -- not "whenever the next liveness poll happens to
 * bring a fresh snapshot". Finds it purely by `data-question-id` (a plain
 * `String === String` comparison, never a `CSS.escape`'d attribute
 * selector -- see `resolveFocusTarget`'s own comment for why that cannot
 * be relied on to exist at all under `node --test`), scoped to
 * `[data-hook="questions-panel"]` so this never reaches into
 * ui/scenario.js's own, separate stage-1 question list, which happens to
 * reuse the exact same `data-hook="question-open"` name on its own buttons
 * (tracked as debt in the ticket: unifying the two is out of this repair's
 * scope). `requestSnapshotRefresh` (below) still asks for the real,
 * authoritative snapshot right after -- this is only the bridge until that
 * lands, not a replacement for it (a second dashboard tab, or
 * ui/scenario.js's own list, only ever catches up through that refresh).
 */
function pruneAnsweredQuestionRow(questionId) {
  if (typeof document === "undefined" || !questionId) {
    return;
  }
  const section = document.querySelector('[data-hook="questions-panel"]');
  if (!section) {
    return;
  }
  for (const button of section.querySelectorAll('[data-hook="question-open"]')) {
    if (button.dataset.questionId === questionId && button.parentNode) {
      button.parentNode.remove(); // ui/question-panel.js's own <li> wrapper
    }
  }
  if (section.querySelectorAll('[data-hook="question-open"]').length === 0) {
    section.remove();
  }
}

/**
 * Ticket 14 repair, condition 6: the same bubbling `studio:refresh-snapshot`
 * event ui/scenario.js's own `requestProjectRefresh` and ui/card-forms.js's
 * `requestProjectRefresh` already dispatch after a free action settles
 * (app.js listens for it once, for all three call sites) -- reused
 * verbatim rather than inventing a second, question-modal-only refresh
 * signal. Dispatched from `document` itself, not an element: unlike
 * `studio:open-question`, nothing here ever needs `event.target` back for
 * focus.
 */
function requestSnapshotRefresh(projectId) {
  if (typeof document === "undefined") {
    return;
  }
  document.dispatchEvent(
    new CustomEvent("studio:refresh-snapshot", { bubbles: true, detail: { projectId } }),
  );
}

async function submitAnswer() {
  if (submitting || !currentQuestion) {
    return;
  }
  const refs = ensureOverlay();
  const payload = buildAnswerPayload(currentQuestion, currentSelection);
  if (!payload.ok) {
    refs.status.textContent = payload.message;
    return;
  }
  submitting = true;
  refs.submitButton.disabled = true;
  refs.deferButton.disabled = true;
  refs.status.textContent = "Отправляется…";
  const question = currentQuestion;
  const result = await postQuestionAnswer(question.question_id, question.revision, payload.answer);
  // The operator may have closed the modal (Escape/Отложить) while this
  // request was in flight -- never resurrect it or act on a stale result.
  if (currentQuestion !== question) {
    return;
  }
  if (result.ok) {
    // Row removed *before* the modal closes: closeQuestionModal's own
    // focus-restore reads whether the trigger is still attached, and
    // removing it only after would first (correctly) refocus the button
    // and then immediately yank focus back out from under it as a side
    // effect of deleting the now-focused element -- pruning first routes
    // straight to the same "no live trigger anywhere" fallback (`#main`)
    // `syncQuestionModalWithQuestions` already relies on for the same
    // reason, one consistent landing spot either way.
    pruneAnsweredQuestionRow(question.question_id);
    closeQuestionModal();
    requestSnapshotRefresh(question.project_id);
    announce("Ответ отправлен.");
    return;
  }
  submitting = false;
  refs.deferButton.disabled = false;
  if (result.code === "already_answered" && typeof result.acceptedAnswer !== "undefined") {
    // "409 already_answered показывает принятый ответ, без перезаписи и
    // без повтора" -- stays open, read-only, rather than closing outright:
    // the operator mid-click should see *what* was decided, not just that
    // their own click vanished. Ticket 14 repair, condition 6: the
    // announcement never names a channel the data does not actually carry
    // -- the operator's own dashboard may well be the one that "lost".
    showAcceptedAnswer(question, result.acceptedAnswer.answer, {
      announceText: "Ответ уже принят.",
    });
    return;
  }
  refs.submitButton.disabled = false;
  refs.status.textContent = resolveActionErrorMessage(result.code);
}

/**
 * Close whichever modal state is open (form or accepted-answer readout) --
 * a no-op if neither is. Fully hides the overlay (kept as one reused
 * singleton, unlike ui/viewer.js's remove-from-document -- there is
 * nothing here CSP would treat differently either way, and keeping the
 * node avoids rebuilding the whole dialog chrome on every open), detaches
 * the document-level keydown handler (ticket 14 repair, condition 5 -- see
 * `keydownActive`'s own comment) and returns focus to `resolveFocusTarget`'s
 * pick, falling back to whatever held focus right before this open. Never
 * announces anything itself -- a plain Escape/backdrop/"Отложить"/
 * close-button dismissal leaves the question genuinely pending, nothing
 * changed to report; a caller with something to say (a successful submit,
 * `syncQuestionModalWithQuestions`'s own "Ответ уже получен.") calls
 * `announce` itself, after this returns.
 */
export function closeQuestionModal() {
  if (!overlayRefs || overlayRefs.overlay.hidden) {
    return;
  }
  const refs = overlayRefs;
  const questionId = currentTriggerDescriptor;
  const trigger = currentTrigger;
  const fallback = openedFromElement;
  refs.overlay.hidden = true;
  if (keydownActive) {
    document.removeEventListener("keydown", refs.handleDocumentKeydown);
    keydownActive = false;
  }
  currentQuestion = null;
  currentSelection = null;
  currentTrigger = null;
  currentTriggerDescriptor = null;
  openedFromElement = null;
  submitting = false;
  let target = resolveFocusTarget(trigger, questionId);
  if (!target && fallback && isAttached(fallback) && isFocusable(fallback)) {
    target = fallback;
  }
  if (target && typeof target.focus === "function") {
    target.focus();
    return;
  }
  // Last resort: a question answered elsewhere (or by this modal's own
  // just-completed submit, see `pruneAnsweredQuestionRow` above) removes
  // its own trigger from *every* surface at once (ui/question-panel.js's
  // own renderQuestionsPanel and ui/scenario.js's stage-1 question list
  // both stop rendering it) -- unlike ui/viewer.js's media cards, which
  // almost always still have *some* live element sharing the same group
  // id, there is frequently nothing left anywhere to re-find by any of the
  // paths above. `#main` carries `tabindex="-1"` specifically for exactly
  // this (index.html; the skip-link's own target) -- a genuine, if
  // generic, landing spot beats leaving a keyboard user's focus on `<body>`
  // with no landmark at all, the same reasoning ui/shell.js's own
  // focusCardFallbackHeading falls back to a heading for.
  const main = document.querySelector('[data-hook="main"]');
  if (main && typeof main.focus === "function") {
    main.focus();
  }
}

/**
 * Task 14 liveness: called from app.js on every store commit (right
 * alongside `renderShell`) with the *current* snapshot's `questions[]`.
 * If the modal is open for a question that is no longer in that list --
 * chat, Telegram or a second dashboard tab already answered it -- this
 * closes it with a short, neutral announcement and returns focus to
 * whoever opened it, per ticket 14's "Вопрос, закрытый в другом канале...
 * закрывает открытый модал... короткое сообщение «Ответ уже получен»".
 *
 * Never touches a modal that is showing its own accepted-answer readout
 * (`showAcceptedAnswer`'s doing, a *different*, already-handled case) --
 * `currentQuestion` is cleared the instant that view is entered's own
 * close eventually runs, but while it is showing, the question genuinely
 * is answered and this function finding it "missing" from `questions`
 * would just be re-describing the same fact a second, redundant way.
 * Checked via `overlayRefs.form.hidden` (true exactly while the accepted
 * view owns the dialog).
 */
export function syncQuestionModalWithQuestions(questions) {
  if (!overlayRefs || overlayRefs.overlay.hidden || !currentQuestion) {
    return;
  }
  if (overlayRefs.form.hidden) {
    // The accepted-answer readout owns the dialog right now (a 409 hit this
    // modal's own submit) -- already the correct, final state; nothing to
    // reconcile against a fresh `questions` list.
    return;
  }
  const list = Array.isArray(questions) ? questions : [];
  const stillPending = list.some((item) => item && item.question_id === currentQuestion.question_id);
  if (stillPending) {
    return;
  }
  closeQuestionModal();
  announce("Ответ уже получен.");
}

let openListenerAttached = false;

/**
 * Wire the listener that opens this modal when any question entry
 * (ui/scenario.js's stage-1 question list, ui/question-panel.js's own
 * `renderQuestionsPanel`) dispatches `studio:open-question`. Call once,
 * from app.js -- never at module top level, so importing this module (a
 * pure-function test, say) never touches `document` merely by being
 * imported (same reasoning as ui/viewer.js's `attachViewerOpenListener`).
 */
export function attachQuestionOpenListener() {
  if (openListenerAttached) {
    return;
  }
  openListenerAttached = true;
  document.addEventListener("studio:open-question", (event) => {
    const question = event && event.detail && event.detail.question;
    if (!question) {
      return;
    }
    const trigger = isElement(event.target) ? event.target : null;
    openQuestionModal(question, { trigger });
  });
}

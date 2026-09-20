// Pure, DOM-free answer model for the shared Question contract (spec §6,
// ticket 14) -- validation, payload building and read-only description,
// plus the small per-`kind` static facts (subtitle text, whether a "Свой
// вариант" section ever applies) the dialog needs to decorate its DOM.
// Server-side `QuestionStore._normalize_answer`/`_validation`
// (studio/questions.py) remain the one source of truth -- everything here
// only avoids an obviously invalid round trip and gives the same feedback
// sooner, in Russian; a mismatch never blocks anything the server would
// actually accept.
//
// Ticket 14 repair, condition 10: every `if (kind === ...)` branch this
// file used to repeat independently (validate, build the wire payload,
// describe an answer, pick a subtitle, decide whether "Свой вариант" ever
// shows) now reads from the one `QUESTION_KIND_TABLE` below instead of its
// own copy of the same four-way switch -- so a fifth `kind` the server ever
// adds is one new table row, not four separately-remembered edits.

function trimmedText(value) {
  return typeof value === "string" ? value.trim() : "";
}

/** `question.validation`, normalized to a plain object -- every reader
 * below (and the dialog's own hint/maxlength wiring) can destructure it
 * without a repeated `typeof`/`null` guard of its own. */
export function validationOf(question) {
  return question && typeof question.validation === "object" && question.validation !== null
    ? question.validation
    : {};
}

/** Same full-match semantics as the server's `re.fullmatch(pattern, value)`
 * (ticket 14 repair, condition 8 -- the client used to run a bare
 * `RegExp.test`, a *partial*-match check that let e.g. `"a15"` through a
 * `\d+` pattern the server would reject outright). Anchoring is the one
 * fix in scope here: a pattern written for Python's own regex dialect
 * (`\A`/`\Z`, lookbehind flavors, …) can still disagree with JavaScript's
 * on edge cases the server would treat differently -- exactly the
 * pre-existing "an invalid/exotic pattern never blocks the client" case
 * below already accepts, never a new regression this fix introduces. */
function fullMatches(pattern, text) {
  try {
    return new RegExp(`^(?:${pattern})$`).test(text);
  } catch {
    return true; // an invalid pattern never blocks the client; the server is authoritative
  }
}

/** Client-side echo of `questions.py`'s own text-shape checks
 * (`min_length`/`max_length`/`pattern`/`allowed_values`) -- shared by
 * `free_text` and a `single`/`multi` question's own custom-text item. */
function validateText(text, validation) {
  const { min_length: minLength, max_length: maxLength, pattern, allowed_values: allowedValues } = validation;
  if (typeof minLength === "number" && text.length < minLength) {
    return { valid: false, message: `Слишком коротко — нужно не меньше ${minLength} символов.` };
  }
  if (typeof maxLength === "number" && text.length > maxLength) {
    return { valid: false, message: `Слишком длинно — не больше ${maxLength} символов.` };
  }
  if (typeof pattern === "string" && !fullMatches(pattern, text)) {
    return { valid: false, message: "Ответ не подходит по формату." };
  }
  if (Array.isArray(allowedValues) && allowedValues.length > 0 && !allowedValues.includes(text)) {
    return { valid: false, message: "Такой вариант не поддерживается." };
  }
  return { valid: true };
}

/** Repair, ticket 14 repair 2, condition 14 (spec review finding, §1
 * "интерфейс показывает только творческий процесс и результат"): the one
 * neutral phrase shown in place of `validation.pattern`'s own raw regex
 * source. The `Question` contract has no separate human-authored hint field
 * of its own (`validation.hint` does not exist server-side) -- a fixed,
 * allowlisted sentence is what stands in for it until one is added (noted
 * as a debt item for the final review, per the ticket). */
const PATTERN_HINT_TEXT = "Ответ должен быть в нужном формате — он указан в вопросе.";

/**
 * A short, proactive description of a text field's own `validation`
 * constraints -- shown under the field *before* any submit attempt (ticket
 * 14 repair, condition 8: "подсказка формата видна до отправки"), not only
 * as a rejection message after one. Mirrors exactly the checks
 * `validateText` above runs, in the same order, so the hint never promises
 * something the validator does not actually enforce. `null` when
 * `validation` carries none of the four recognized keys -- a field with no
 * constraints shows no hint line at all rather than an empty one.
 *
 * Repair 2, condition 14 (craft review finding 5): the `pattern` branch used
 * to interpolate the raw regex source straight into the hint (`` `Формат:
 * ${pattern}` `` -- shown to the operator verbatim, e.g. "Формат:
 * ^\d{2}:\d{2}$"). `validateText`'s own rejection message, right above, was
 * already neutral ("Ответ не подходит по формату.") and needed no change --
 * only this proactive hint leaked the pattern. The length hints stay exactly
 * as they were (words with numbers, never a raw value the operator did not
 * type themselves).
 */
export function describeValidationHint(validation) {
  const source = validation && typeof validation === "object" ? validation : {};
  const { min_length: minLength, max_length: maxLength, pattern, allowed_values: allowedValues } = source;
  const parts = [];
  if (typeof minLength === "number" && typeof maxLength === "number") {
    parts.push(`От ${minLength} до ${maxLength} символов.`);
  } else if (typeof minLength === "number") {
    parts.push(`Не меньше ${minLength} символов.`);
  } else if (typeof maxLength === "number") {
    parts.push(`Не больше ${maxLength} символов.`);
  }
  if (typeof pattern === "string" && pattern) {
    parts.push(PATTERN_HINT_TEXT);
  }
  if (Array.isArray(allowedValues) && allowedValues.length > 0) {
    parts.push(`Допустимые значения: ${allowedValues.join(", ")}.`);
  }
  return parts.length > 0 ? parts.join(" ") : null;
}

// -----------------------------------------------------------------------
// Per-kind behavior table. `selection` is the dialog's own in-progress
// state, kind-agnostic: `{selectedOptionId, selectedOptionIds, customText,
// freeText, confirmValue}` -- only the fields a given entry actually reads
// are used, so a caller never has to build a kind-specific shape by hand.
// -----------------------------------------------------------------------

function validateConfirm(_question, selection) {
  const value = selection && selection.confirmValue;
  if (value !== true && value !== false) {
    return { valid: false, message: "Выберите «Да» или «Нет»." };
  }
  return { valid: true };
}

function buildConfirmAnswer(_question, selection) {
  return selection.confirmValue === true;
}

/** Handles the server's own `"yes"`/`"no"` strings *and* a raw boolean --
 * `question.options` is always empty for `confirm` (the file banner: the
 * two rows the dialog renders for it are fixed, never server-provided), so
 * this never goes through `describeViaOptionsOrRaw`'s option-label lookup.
 * `null`/`undefined` (an explicit, `required:false` skip -- see
 * `QuestionStore._normalize_answer`'s own `answer is None` branch) reads as
 * "no answer to describe" (`""`), never the false-ish "Нет" a plain
 * `answer === true ? "Да" : "Нет"` ternary used to produce for it (ticket
 * 14 repair, condition 8). */
function describeConfirm(_question, answer) {
  if (answer === true || answer === "yes") {
    return "Да";
  }
  if (answer === false || answer === "no") {
    return "Нет";
  }
  return "";
}

function validateFreeText(question, selection) {
  const text = trimmedText(selection && selection.freeText);
  if (!text) {
    return { valid: false, message: "Напишите ответ." };
  }
  return validateText(text, validationOf(question));
}

function buildFreeTextAnswer(_question, selection) {
  return trimmedText(selection.freeText);
}

function validateSingle(question, selection) {
  const allowCustom = Boolean(question && question.allow_custom);
  const customText = trimmedText(selection && selection.customText);
  const optionId = (selection && selection.selectedOptionId) || "";
  if (!optionId && !customText) {
    return {
      valid: false,
      message: allowCustom ? "Выберите вариант или напишите свой." : "Выберите вариант.",
    };
  }
  if (optionId) {
    return { valid: true };
  }
  if (!allowCustom) {
    return { valid: false, message: "Свой вариант недоступен для этого вопроса." };
  }
  return validateText(customText, validationOf(question));
}

function buildSingleAnswer(_question, selection) {
  const optionId = (selection && selection.selectedOptionId) || "";
  const customText = trimmedText(selection && selection.customText);
  return optionId || customText;
}

function validateMulti(question, selection) {
  const allowCustom = Boolean(question && question.allow_custom);
  const validation = validationOf(question);
  const customText = trimmedText(selection && selection.customText);
  const selectedIds = Array.isArray(selection && selection.selectedOptionIds) ? selection.selectedOptionIds : [];
  const itemCount = selectedIds.length + (customText ? 1 : 0);
  if (customText && !allowCustom) {
    return { valid: false, message: "Свой вариант недоступен для этого вопроса." };
  }
  if (itemCount === 0) {
    return { valid: false, message: "Выберите хотя бы один вариант." };
  }
  const { min_items: minItems, max_items: maxItems } = validation;
  if (typeof minItems === "number" && itemCount < minItems) {
    return { valid: false, message: `Выберите не меньше ${minItems}.` };
  }
  if (typeof maxItems === "number" && itemCount > maxItems) {
    return { valid: false, message: `Выберите не больше ${maxItems}.` };
  }
  return { valid: true };
}

function buildMultiAnswer(_question, selection) {
  const selectedIds = Array.isArray(selection && selection.selectedOptionIds) ? selection.selectedOptionIds : [];
  const customText = trimmedText(selection && selection.customText);
  const items = [...selectedIds];
  if (customText) {
    items.push(customText);
  }
  return items;
}

/** Shared by `single`/`multi`/`free_text`: resolves an option id back to
 * its label when one matches, otherwise shows the raw (custom, or
 * free-text) value verbatim -- `multi` joins every resolved item. Never
 * kind-specific by itself: a `free_text` question has no `options` to
 * match against at all, so `labelFor` degrades to "pass the string
 * through unchanged" for it automatically. */
function describeViaOptionsOrRaw(question, answer) {
  const options = Array.isArray(question && question.options) ? question.options : [];
  const labelFor = (value) => {
    const option = options.find((item) => item && item.id === value);
    return option ? option.label : value;
  };
  if (Array.isArray(answer)) {
    return answer.map((item) => labelFor(item)).join(", ");
  }
  if (typeof answer === "string") {
    return labelFor(answer);
  }
  return "";
}

function subtitleSingle(question) {
  return question.allow_custom
    ? "Выберите один из вариантов или напишите свой."
    : "Выберите один из вариантов.";
}

function subtitleMulti(question) {
  return question.allow_custom
    ? "Можно выбрать несколько вариантов или добавить свой."
    : "Можно выбрать несколько вариантов.";
}

const noSubtitle = () => "";

/**
 * The one table every kind-dependent decision in this file (and, through
 * the exports below, ui/question-dialog.js's DOM builders) reads from.
 * `usesOptions`/`inputType` describe how the dialog's shared options `<ul>`
 * renders this kind (`confirm`'s two rows are fixed Yes/No, never sourced
 * from `question.options` -- see ui/question-dialog.js's own
 * `buildOptionsForKind`); `allowsCustomSection` is whether a free-standing
 * "Свой вариант" block ever applies for it at all -- never for `confirm`
 * (the server's own `_normalize_answer` never reads `allow_custom` for
 * that kind) and never for `free_text` (its own one field *is* already
 * free text, there is no separate "non-custom" alternative beside it).
 */
export const QUESTION_KIND_TABLE = Object.freeze({
  single: {
    usesOptions: true,
    inputType: "radio",
    allowsCustomSection: true,
    subtitle: subtitleSingle,
    validate: validateSingle,
    buildAnswer: buildSingleAnswer,
    describe: describeViaOptionsOrRaw,
  },
  multi: {
    usesOptions: true,
    inputType: "checkbox",
    allowsCustomSection: true,
    subtitle: subtitleMulti,
    validate: validateMulti,
    buildAnswer: buildMultiAnswer,
    describe: describeViaOptionsOrRaw,
  },
  free_text: {
    usesOptions: false,
    inputType: null,
    allowsCustomSection: false,
    subtitle: noSubtitle,
    validate: validateFreeText,
    buildAnswer: buildFreeTextAnswer,
    describe: describeViaOptionsOrRaw,
  },
  confirm: {
    usesOptions: true,
    inputType: "radio",
    allowsCustomSection: false,
    subtitle: noSubtitle,
    validate: validateConfirm,
    buildAnswer: buildConfirmAnswer,
    describe: describeConfirm,
  },
});

function kindEntry(question) {
  return question && QUESTION_KIND_TABLE[question.kind];
}

/**
 * "Продолжить" always requires a genuine answer, independent of
 * `question.required` -- `required:false` only ever means the *server*
 * would also accept an explicit `null` (skip) answer; this dialog has no
 * control that sends one, since "Отложить"/Escape/the close button already
 * cover "not now" without recording anything at all (ticket 14: "закрытие
 * оставляет вопрос ожидающим"). That keeps every submit unambiguous.
 */
export function validateSelection(question, selection) {
  const entry = kindEntry(question);
  if (!entry) {
    return { valid: false, message: "Этот тип вопроса не поддерживается." };
  }
  return entry.validate(question, selection || {});
}

/**
 * The exact wire value `POST /api/questions/{id}/answers`' own `answer`
 * key expects for `question.kind` -- a string (`single`/`free_text`), a
 * list of strings (`multi`), or a boolean (`confirm`) -- or `{ok:false,
 * message}` when `validateSelection` rejects it first. Never called
 * without going through that validation: this is the only place both are
 * guaranteed to agree, so a caller cannot accidentally build a payload for
 * a selection it never actually validated.
 */
export function buildAnswerPayload(question, selection) {
  const check = validateSelection(question, selection);
  if (!check.valid) {
    return { ok: false, message: check.message };
  }
  return { ok: true, answer: kindEntry(question).buildAnswer(question, selection || {}) };
}

/**
 * Human-readable echo of a raw answer value (a question's own `answer`
 * field, or a `LateAnswerConflict`'s `accepted_answer.answer`). Used only
 * for the read-only "already answered" view (never for building a payload
 * -- that direction is `buildAnswerPayload`, above).
 */
export function describeAnswer(question, answer) {
  const entry = kindEntry(question);
  return entry ? entry.describe(question, answer) : "";
}

/** A short, kind-appropriate hint under the title (concept:
 * docs/design/concepts/ai-workshop-question-modal.png shows "Какой
 * вариант продолжения выбрать?" under a single-kind question's own text).
 * The Question contract has no separate subtitle field of its own -- this
 * is a fixed, allowlisted phrase per `kind`/`allow_custom` combination,
 * never anything derived from `question.text` itself. */
export function resolveSubtitle(question) {
  const entry = kindEntry(question);
  return entry ? entry.subtitle(question) : "";
}

/** Whether this kind ever shows the free-standing "Свой вариант" section. */
export function showsCustomSection(question) {
  const entry = kindEntry(question);
  return Boolean(question && question.allow_custom) && Boolean(entry && entry.allowsCustomSection);
}

// Task 08 repair 1, condition 11 ("модель и видимость" is its own module):
// which card-level actions exist, in what order, under what label, and
// which raw prompt/result record an already-rendered card's own
// `data-*-id` hooks name. Pure, DOM-free -- this is the module
// tests/ui/card-model.test.mjs imports directly.
//
// This module never imports ui/media.js or ui/scenario.js, and neither of
// those import this one (ticket 08 amendment 2). It never calls `fetch`.

import { resolveLabel } from "./state.js";

/** Card-level action types, in the fixed order the row/inspector always
 * renders them -- never the order `view_stage.allowed_actions` happens to
 * list, which is not a display order at all. `edit` (exact-text rewrite)
 * only ever applies to an `image_plan` prompt (domain._STAGE_ACTIONS never
 * lists it at any other stage); `vary`/`regenerate`/`hide`/`unhide`/
 * `retire`/`restore` only ever apply to an image_results/motion result. */
export const PROMPT_CARD_ACTION_ORDER = Object.freeze(["approve", "reject", "edit"]);
export const RESULT_CARD_ACTION_ORDER = Object.freeze([
  "approve",
  "reject",
  "vary",
  "regenerate",
  "hide",
  "unhide",
  "retire",
  "restore",
]);

/** Russian button copy -- allowlist only, via `resolveLabel` (ui/state.js)
 * so an unrecognized action type never renders a raw token. */
export const CARD_ACTION_LABELS = Object.freeze({
  approve: "Принять",
  reject: "Нужны правки",
  edit: "Править",
  vary: "Вариация",
  regenerate: "Перегенерировать",
  generate: "Сгенерировать",
  "prompts-generate": "Написать промпты",
  "prompt-refresh": "Обновить промпт",
  assemble: "Собрать финал",
  "set-mode": "Изменить режим",
  hide: "Скрыть",
  unhide: "Показать",
  retire: "Убрать из работы",
  restore: "Вернуть",
});

export function resolveCardActionLabel(actionType) {
  return resolveLabel(CARD_ACTION_LABELS, actionType);
}

/**
 * Which card-level actions `view_stage.allowed_actions` (server-derived,
 * the one allowlist this dashboard ever consults -- spec §2.1/G04) permits
 * on one specific card right now, given that card's own `hidden`/`retired`
 * flags. `kind` is `"prompt"` or `"result"`; `order` is
 * `PROMPT_CARD_ACTION_ORDER`/`RESULT_CARD_ACTION_ORDER`.
 *
 * `hide`/`unhide` and `retire`/`restore` are mutually exclusive by the
 * card's own current state -- never both offered at once, and never the
 * one that would be a no-op (unhiding an already-visible card, retiring an
 * already-retired one). A retired card (ticket 08 point 9, "«Убрано из
 * работы»... такая карточка не «Текущая»") drops every action but
 * `restore`: nothing else about a card excluded from the active flow makes
 * sense to offer until it is returned to work.
 */
export function resolveCardActions(allowedActions, kind, record) {
  const allowed = new Set(Array.isArray(allowedActions) ? allowedActions : []);
  const order = kind === "prompt" ? PROMPT_CARD_ACTION_ORDER : RESULT_CARD_ACTION_ORDER;
  const retired = Boolean(record && record.retired);
  if (retired) {
    return order.includes("restore") && allowed.has("restore") ? ["restore"] : [];
  }
  const hidden = Boolean(record && record.hidden);
  return order.filter((action) => {
    if (!allowed.has(action)) {
      return false;
    }
    if (action === "hide") {
      return !hidden;
    }
    if (action === "unhide") {
      return hidden;
    }
    if (action === "retire") {
      return true; // already excluded the retired branch above
    }
    if (action === "restore") {
      return false; // only reachable through the retired branch above
    }
    return true;
  });
}

/**
 * Whether a card belonging to `collectionKind` is part of the CURRENT
 * stage's own collection right now -- ticket 08 point 10: "решения --
 * только в коллекции текущей стадии... карточки завершённых стадий только
 * для просмотра". A card that stays visible after its own stage has passed
 * (image_results cards once the project has moved on to motion/audio/assembly,
 * per projection.py's cumulative stage gate) must render with no action row
 * at all, never a stale one from a stage that is no longer current.
 */
export function isCardCollectionCurrent(collectionKind, currentStage) {
  if (collectionKind === "prompt") {
    return currentStage === "image_plan";
  }
  if (collectionKind === "image_result") {
    return currentStage === "image_results";
  }
  if (collectionKind === "video_result") {
    return currentStage === "motion";
  }
  if (collectionKind === "scenes") {
    return currentStage === "image_plan";
  }
  return false;
}

/**
 * Find the one raw prompt/result record `versionId`/`groupId` names in
 * `records` (a snapshot's own `image_prompts`/`motion_prompts`/
 * `image_results`/`video_results` array). `groupKey` is `"prompt_id"` or
 * `"result_id"`. A `version_id` match always wins outright -- exactly the
 * server's own `card_identity` precedence (studio/decision_cards.py) --
 * falling back to the group id only when no version id was given at all
 * (never when one was given but did not match, which would silently
 * address the wrong version of an ambiguous group).
 */
export function findGroupRecord(records, { groupId, versionId }, groupKey) {
  const list = Array.isArray(records) ? records : [];
  if (typeof versionId === "string" && versionId) {
    const match = list.find((item) => item && item.version_id === versionId);
    return match || null;
  }
  if (typeof groupId === "string" && groupId) {
    const matches = list.filter((item) => item && item[groupKey] === groupId);
    return matches.length === 1 ? matches[0] : null;
  }
  return null;
}

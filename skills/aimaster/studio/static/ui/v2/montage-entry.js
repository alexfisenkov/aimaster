// Что экран «Сборка» видит о монтаже проекта — одна чистая функция, общая
// для публикации статуса и схемы (montage-feed-core.js): чей отказ главнее
// и свежа ли показанная схема решается только здесь.

import { applicable, keyOf, sameKey } from "./montage-model-tracker.js";

/** `{status, model, error, modelFresh}`:
 * - `status` — последний удачный статус, `model` — последняя удачная схема
 *   (`shownKey` — ключ, для которого её спросили);
 * - `error` — отказ самого статуса главнее всего (поздняя схема его не
 *   затирает); иначе отказ схемы, но только пока статус применим и на том же
 *   ключе, для которого схема отказала (`modelKey`);
 * - `modelFresh` — схема на экране спрошена для ключа последнего статуса, и
 *   он применим; `false` — схема отстала (правка, сборка, другой снимок), B5
 *   помечает её «обновляется…». */
export function composeEntry({
  status = null, statusError = null, model = null, shownKey = null, modelKey = null, modelError = null,
} = {}) {
  const statusKey = applicable(status) ? keyOf(status) : null;
  return {
    status,
    model,
    error: statusError || (sameKey(statusKey, modelKey) ? modelError : null),
    modelFresh: Boolean(model) && sameKey(statusKey, shownKey),
  };
}

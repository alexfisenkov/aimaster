// Что экран «Сборка» видит о монтаже проекта — одна чистая функция, общая
// для публикации статуса и схемы (montage-feed-core.js): чей отказ главнее
// и свежа ли показанная схема решается только здесь.

import { applicable, keyOf, sameKey } from "./montage-model-tracker.js";

/** `{status, model, error, modelFresh}`:
 * - `status` — последний удачный статус, `model` — последняя удачная схема;
 * - `error` — отказ самого статуса главнее всего (поздняя схема его не
 *   затирает); иначе отказ схемы, но только пока статус применим и на том же
 *   ключе, для которого схема отказала (`modelKey`);
 * - `modelFresh` — схема на экране про тот же index_key, что и статус. */
export function composeEntry({ status = null, statusError = null, model = null, modelKey = null, modelError = null }) {
  const modelCurrent = applicable(status) && sameKey(keyOf(status), modelKey);
  return {
    status,
    model,
    error: statusError || (modelCurrent ? modelError : null),
    modelFresh: Boolean(model) && Boolean(status) && model.index_key === status.index_key,
  };
}

// Что экран «Сборка» видит о монтаже проекта — одна чистая функция, общая
// для публикации статуса и схемы (montage-feed-core.js): чей отказ главнее,
// свежа ли показанная схема и давно ли она отстала — решается только здесь.

import { applicable, keyOf, sameKey } from "./montage-model-tracker.js";

/** `{status, model, error, modelFresh, modelLagging}`:
 * - `status` — последний удачный статус, `model` — последняя удачная схема
 *   (`shownKey` — ключ, для которого её спросили);
 * - `error` — отказ самого статуса главнее всего (поздняя схема его не
 *   затирает); иначе отказ схемы, но только пока статус применим и на том же
 *   ключе, для которого схема отказала (`modelKey`);
 * - `modelFresh` — схема на экране спрошена для ключа последнего статуса, и
 *   он применим; `false` — схема отстала (правка, сборка, другой снимок);
 * - `modelLagging` — схема не свежая дольше одного опроса статуса
 *   (`staleTicks` > 1, см. `staleTicksAfter`): только тогда экран пишет
 *   «обновляется…». Схема, что догоняет за один опрос, пометкой не мигает. */
export function composeEntry({
  status = null, statusError = null, model = null, shownKey = null, modelKey = null, modelError = null,
  staleTicks = 0,
} = {}) {
  const statusKey = applicable(status) ? keyOf(status) : null;
  const modelFresh = Boolean(model) && sameKey(statusKey, shownKey);
  return {
    status,
    model,
    error: statusError || (sameKey(statusKey, modelKey) ? modelError : null),
    modelFresh,
    modelLagging: Boolean(model) && !modelFresh && staleTicks > 1,
  };
}

/** Сколько опросов статуса подряд показанная схема не свежая: схемы нет или
 * она свежая — 0; очередной опрос статуса (`tick`) — +1; ответ самой схемы
 * счёт не двигает (она либо стала свежей — 0, либо ещё догоняет). */
export function staleTicksAfter(previous, { model, modelFresh }, tick) {
  if (!model || modelFresh) return 0;
  return tick ? previous + 1 : previous;
}

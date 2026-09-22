// Модель экрана «Видео» (спецификация §3.3): что написано у сцены про её
// клип и про то, откуда берётся движение. Чистые функции, без DOM.
//
// Откуда берутся слова про продолжение. Способ оживления живёт в
// `scene.video_mode` («первый кадр» / «первый и последний» / «по
// референсам») — ровно те три значения, что пишет `ui/video-mode.js`.
// Продолжение с конца соседнего клипа — это не режим, а локальный
// видеореференс сцены с `usage: "continue"`; соседом всегда считается
// предыдущая сцена по порядку, как и в `video-mode.js`.
// `linkage_status: "review_linkage"` домен ставит, когда сцену правили
// после того, как ссылки уже были расставлены (`domain.py`), — значит
// связь стоит перепроверить.

import { variantCounts } from "./counts.js";

const MODE_WORDS = Object.freeze({
  first: "Оживляем первый кадр",
  firstlast: "От первого кадра к последнему",
  references: "Отдельный клип по референсам и промпту",
});

/**
 * Одна строка про клип сцены.
 *
 * @param {object} project `snapshot.active_project`
 * @param {object} scene запись сцены
 * @returns {{total: number, index: number, selected: object|null, text: string}}
 */
export function clipStatus(project, scene) {
  const counts = variantCounts(project, { sceneId: scene?.scene_id, slot: "video" });
  const { total, index, selected } = counts;
  let text;
  if (total === 0) text = "клипов пока нет";
  else if (!selected) text = `выберите из ${total}`;
  else text = total > 1 ? `клип выбран · ${index} из ${total}` : "клип выбран";
  return { total, index, selected, text };
}

/**
 * Одна строка про то, откуда берётся движение этой сцены.
 *
 * @param {object} project `snapshot.active_project`
 * @param {object} scene запись сцены
 * @returns {{text: string, warn: boolean}} `warn` — сцену меняли после
 *   расстановки ссылок, связь стоит перепроверить.
 */
export function continuationLine(project, scene) {
  const scenes = [...(project?.scenes || [])].sort((left, right) => (left?.order || 0) - (right?.order || 0));
  const index = scenes.findIndex((item) => item?.scene_id === scene?.scene_id);
  const continues = (project?.references || []).some(
    (item) => item?.kind === "video" && item.usage === "continue" && item.scene_id === scene?.scene_id,
  );
  let text;
  if (continues) {
    text = index > 0 ? `Продолжение: с конца сцены ${index}` : "Продолжение: с конца соседнего клипа";
  } else {
    text = MODE_WORDS[scene?.video_mode] || "Способ оживления пока не выбран";
  }
  return { text, warn: scene?.linkage_status === "review_linkage" };
}

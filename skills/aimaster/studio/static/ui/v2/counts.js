// Сколько вариантов у места и какой из них выбран — одно вычисление на
// полку референсов, строку сцены и будущий просмотрщик. Чистые функции.

import { resultGroups, selectedResultVersion } from "./variants.js";

const POSITION_KIND_BY_SLOT = Object.freeze({
  first: "first_frame",
  last: "last_frame",
  video: "video",
  image: "image",
});

/** Позиция действующего плана, которой принадлежит это место. */
function positionFor(project, { sceneId, slot, referenceId, layer }) {
  const positions = (project?.positions || []).filter(Boolean);
  if (referenceId) {
    return positions.find((item) => item.kind === "reference" && item.tag === referenceId) || null;
  }
  if (layer) return positions.find((item) => item.position_id === `pos:audio:${layer}`) || null;
  if (!sceneId || sceneId === "oneshot") {
    return positions.find((item) => item.kind === "oneshot") || null;
  }
  const kind = POSITION_KIND_BY_SLOT[slot] || "image";
  return positions.find((item) => item.scene_id === sceneId && item.kind === kind) || null;
}

function collectionFor(project, { slot, layer, sceneId }) {
  if (layer) return project?.audio_results;
  if (slot === "video" || !sceneId || sceneId === "oneshot") return project?.video_results;
  return project?.image_results;
}

/**
 * @param {object} project `snapshot.active_project`
 * @param {{sceneId?: string, slot?: string, referenceId?: string, layer?: string}} target
 * @returns {{versions: object[], total: number, selected: object|null,
 *            index: number, groupId: string|null, position: object|null}}
 *   `index` — номер выбранного варианта начиная с 1, или 0, если выбора нет.
 */
export function variantCounts(project, target = {}) {
  const position = positionFor(project, target);
  const selected = selectedResultVersion(project, target);
  const groupId = position?.result_group_id || selected?.result_id || null;
  const versions = groupId ? resultGroups(collectionFor(project, target)).get(groupId) || [] : [];
  const index = selected ? versions.findIndex((item) => item.version_id === selected.version_id) + 1 : 0;
  return { versions, total: versions.length, selected, index, groupId, position };
}

/**
 * Статус места одной строкой — ровно четыре формулировки спецификации §3.2.
 * @param {{source?: string, hasAsset?: boolean}} own «своё» вместо генерации
 */
export function variantStatus({ total, selected, index }, { source, hasAsset } = {}) {
  if (source === "upload") return hasAsset ? "ваш файл" : "не задан";
  if (selected) return total > 1 ? `выбран ${index} из ${total}` : "выбран";
  if (total > 0) return `выберите из ${total}`;
  return "не задан";
}

// Модель экрана «Сценарий» (спецификация §3.1): версии текста сценария
// и раскадровка списком. Чистые функции, без DOM — их и покрывают тесты.

import { orderByParent } from "./variants.js";

/**
 * Версии сценария по цепочке `parent_version_id` и номер активной.
 *
 * @param {object} project `snapshot.active_project`
 * @returns {{versions: object[], activeIndex: number}} `activeIndex`
 *   считается с нуля; если активной версии нет, берётся последняя.
 */
export function scriptVersions(project) {
  const script = project?.script;
  const versions = orderByParent(Array.isArray(script?.versions) ? script.versions : []);
  const found = versions.findIndex((item) => item?.version_id === script?.active_version_id);
  const activeIndex = found >= 0 ? found : Math.max(0, versions.length - 1);
  return { versions, activeIndex };
}

/** Текст активной версии блока сценария у сцены. */
export function activeBlockText(scene) {
  const block = scene?.script_block;
  const versions = Array.isArray(block?.versions) ? block.versions : [];
  const active = versions.find((item) => item?.version_id === block?.active_version_id) || versions.at(-1);
  return typeof active?.text === "string" ? active.text : "";
}

/**
 * Раскадровка списком: номер, название, время и текст каждой сцены.
 *
 * @param {object} project `snapshot.active_project`
 * @returns {{sceneId: string, position: number, title: string,
 *            startMs: number|null, endMs: number|null, text: string}[]}
 */
export function storyboardRows(project) {
  return [...(project?.scenes || [])]
    .sort((left, right) => (left?.order || 0) - (right?.order || 0))
    .map((scene, index) => ({
      sceneId: scene?.scene_id || "",
      position: index + 1,
      title: typeof scene?.title === "string" && scene.title.trim() ? scene.title.trim() : `Сцена ${index + 1}`,
      startMs: Number.isFinite(scene?.start_ms) ? scene.start_ms : null,
      endMs: Number.isFinite(scene?.end_ms) ? scene.end_ms : null,
      text: activeBlockText(scene),
    }));
}

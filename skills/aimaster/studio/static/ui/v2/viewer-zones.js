// Зоны референсов в правой колонке просмотрщика — только для сцены
// (спецификация §4): «В кадре», «Только здесь», «Видеореференс».
//
// Своей модели здесь нет: зоны строит `scene-zones.js`, тот же модуль,
// что и строка сцены на экране «Кадры». Тёмный вид задаёт `viewer.css`
// селекторами внутри `.v2-viewer`, а не второй копией разметки.

import { inFrameZone, localZone, videoReferenceZone } from "./scene-zones.js";
import { el } from "./dom.js";

/**
 * @param {object} project `snapshot.active_project`
 * @param {number} revision `snapshot.revision`
 * @param {object|null} scene запись сцены; для референса, слоя и сборки — `null`
 * @returns {HTMLElement|null} блок зон или `null`, если зон здесь не бывает
 */
export function renderViewerZones(project, revision, scene) {
  if (!scene || typeof scene !== "object") return null;
  const block = el("section", "v2-viewer-zones");
  block.dataset.hook = "v2-viewer-zones";
  block.append(
    inFrameZone(project, revision, scene),
    localZone(project, revision, scene),
    videoReferenceZone(project, revision, scene),
  );
  return block;
}

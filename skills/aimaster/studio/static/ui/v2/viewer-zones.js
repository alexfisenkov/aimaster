// Правая колонка просмотрщика ниже промпта (спецификация §4, хэндофф
// 2026-09-23 «Просмотрщик»):
// - у сцены — зоны «В кадре», «Только здесь», «Видеореференс»;
// - у референса — «Где используется»: в каких сценах он включён;
// - у сборки — «Из чего собран»: выбранные клипы и слои звука.
//
// Зоны сцены строит `scene-zones.js`, тот же модуль, что строка сцены на
// экране «Кадры»; тёмный вид задаёт `viewer.css`. Включённость референса
// читается так же, как там: общий — по `scene.links.reference_ids`,
// «только здесь» и видеореференс — по `scene_id`.
//
// Чистые функции `whereUsed` и `assemblyParts` DOM не трогают — их
// покрывают тесты.

import { AUDIO_LAYERS } from "./audio-model.js";
import { selectedResultVersion } from "./variants.js";
import { inFrameZone, localZone, videoReferenceZone } from "./scene-zones.js";
import { el, openViewer } from "./dom.js";

function scenesInOrder(project) {
  return [...(project?.scenes || [])]
    .filter((item) => item && typeof item.scene_id === "string")
    .sort((left, right) => (left?.order || 0) - (right?.order || 0));
}

function sceneLabel(scene, position) {
  return `Сцена ${position} · ${scene.title || scene.scene_id}`;
}

/**
 * В каких сценах участвует референс.
 *
 * @param {object} project `snapshot.active_project`
 * @param {string} referenceId `reference_id`
 * @returns {{sceneId: string, label: string}[]} по порядку сцен; пусто,
 *   если референс не найден или ни в одну сцену не включён
 */
export function whereUsed(project, referenceId) {
  const reference = (project?.references || []).find((item) => item?.reference_id === referenceId);
  if (!reference) return [];
  const own = reference.local === true || reference.kind === "video";
  return scenesInOrder(project)
    .map((scene, order) => ({ scene, position: order + 1 }))
    .filter(({ scene }) => (own
      ? reference.scene_id === scene.scene_id
      : (scene.links?.reference_ids || []).includes(referenceId)))
    .map(({ scene, position }) => ({ sceneId: scene.scene_id, label: sceneLabel(scene, position) }));
}

/**
 * Из чего собран ролик — только то, что реально выбрано в snapshot:
 * клип каждой сцены (или ролик одним заходом) и выбранные слои звука.
 * Своего состава у `project.assembly` нет (`{status, asset_id, summary}`),
 * поэтому догадок здесь нет: не выбрано — не перечисляется.
 *
 * @param {object} project `snapshot.active_project`
 * @returns {{target: {kind: string, id: string}, tab: string, label: string}[]}
 */
export function assemblyParts(project) {
  if (!project || typeof project !== "object") return [];
  const parts = [];
  if (selectedResultVersion(project, { sceneId: "oneshot", slot: "video" }) && project.gen_mode === "one_shot") {
    parts.push({ target: { kind: "scene", id: "oneshot" }, tab: "video", label: "Ролик одним заходом" });
  }
  scenesInOrder(project).forEach((scene, order) => {
    if (!selectedResultVersion(project, { sceneId: scene.scene_id, slot: "video" })) return;
    parts.push({ target: { kind: "scene", id: scene.scene_id }, tab: "video", label: `Клип · ${sceneLabel(scene, order + 1)}` });
  });
  for (const meta of AUDIO_LAYERS) {
    if (!selectedResultVersion(project, { layer: meta.layer })) continue;
    parts.push({ target: { kind: "layer", id: meta.layer }, tab: "audio", label: `Звук · ${meta.name}` });
  }
  return parts;
}

/**
 * Блок-список пилюль, каждая открывает просмотрщик на своём месте.
 * @param {string} title заголовок блока
 * @param {{target: object, tab: string, label: string}[]} items
 * @returns {HTMLElement|null} `null`, если перечислять нечего
 */
export function renderUsedIn(title, items) {
  if (!Array.isArray(items) || !items.length) return null;
  const block = el("section", "v2-viewer-used");
  block.dataset.hook = "v2-viewer-used";
  block.append(el("h3", "v2-viewer-subtitle", title));
  const list = el("div", "v2-viewer-used-items");
  for (const item of items) {
    const pill = el("button", "v2-viewer-used-item", item.label);
    pill.type = "button";
    pill.addEventListener("click", () => openViewer(item.target, { tab: item.tab }));
    list.append(pill);
  }
  block.append(list);
  return block;
}

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
  // В узкой строке сцены аватар — одна картинка с подписью в `title`; в
  // колонке просмотрщика места хватает, и макет подписывает его именем.
  for (const avatar of block.querySelectorAll(".v2-avatar")) {
    if (avatar.querySelector(".v2-avatar-name")) continue;
    const name = (avatar.getAttribute("aria-label") || "").split(": ")[0];
    if (name) avatar.append(el("span", "v2-avatar-name", name));
  }
  return block;
}

/** «Где используется» у референса. */
export function renderReferenceUsage(project, referenceId) {
  const items = whereUsed(project, referenceId).map((item) => ({
    target: { kind: "scene", id: item.sceneId },
    tab: "frames",
    label: item.label,
  }));
  return renderUsedIn("Где используется", items);
}

/** «Из чего собран» у сборки; пока ролика нет — «Из чего соберётся». */
export function renderAssemblyParts(project) {
  const built = typeof project?.assembly?.asset_url === "string" && Boolean(project.assembly.asset_url);
  return renderUsedIn(built ? "Из чего собран" : "Из чего соберётся", assemblyParts(project));
}

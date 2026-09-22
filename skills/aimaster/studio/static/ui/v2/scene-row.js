// Строка сцены (спецификация §3.2, макет scene-row-v4): слева номер,
// название, время, описание и строка промпта; справа четыре зоны.
// Клик по строке открывает просмотрщик на этой сцене.

import { promptGroups } from "./variants.js";
import { clock, el, openViewer } from "./dom.js";
import { framesZone, inFrameZone, localZone, videoReferenceZone } from "./scene-zones.js";

const PROMPT_STATUS = Object.freeze({
  approved: "готов",
  pending: "ждёт решения",
  rejected: "нужны правки",
});

/** Активный текст блока сценария этой сцены. */
function blockText(scene) {
  const block = scene?.script_block;
  const versions = Array.isArray(block?.versions) ? block.versions : [];
  const active = versions.find((item) => item?.version_id === block?.active_version_id) || versions.at(-1);
  return typeof active?.text === "string" ? active.text : "";
}

/**
 * «промпт v2 · готов» для строки сцены: номер версии в своей цепочке и
 * её статус. `null`, если промпта у сцены ещё нет.
 * @param {object} project `snapshot.active_project`
 * @param {object} scene запись сцены
 * @param {"motion"|"image"} [kind] какой промпт показывать
 */
export function scenePromptLine(project, scene, kind = "motion") {
  const linkKey = kind === "motion" ? "motion_prompt_version_id" : "image_prompt_version_id";
  const versionId = scene?.links?.[linkKey];
  if (typeof versionId !== "string" || !versionId) return null;
  const collection = kind === "motion" ? project?.motion_prompts : project?.image_prompts;
  const current = (collection || []).find((item) => item?.version_id === versionId);
  if (!current) return null;
  const versions = promptGroups(collection).get(current.prompt_id) || [current];
  const number = versions.findIndex((item) => item.version_id === versionId) + 1;
  const status = current.stale === true ? "устарел" : PROMPT_STATUS[current.status] || "в работе";
  return { text: `промпт v${number || 1} · ${status}`, versionId, stale: current.stale === true };
}

/**
 * @param {object} project `snapshot.active_project`
 * @param {number} revision `snapshot.revision`
 * @param {object} scene запись сцены
 * @param {number} position номер сцены для человека, начиная с 1
 * @returns {HTMLElement} `<article>` строки
 */
export function renderSceneRow(project, revision, scene, position) {
  const row = el("article", "v2-scene");
  row.dataset.hook = "v2-scene";
  row.dataset.sceneId = scene?.scene_id || "";

  const time = `${clock(scene?.start_ms)}–${clock(scene?.end_ms)}`;
  const head = el("div", "v2-scene-head");
  const title = el("b", "v2-scene-title", scene?.title || `Сцена ${position}`);
  title.append(el("span", "v2-scene-time", ` · ${time}`));
  head.append(title, el("p", "v2-scene-text", blockText(scene)));

  const prompt = scenePromptLine(project, scene);
  if (prompt) {
    const line = el("button", "v2-scene-prompt", prompt.text);
    line.type = "button";
    line.dataset.hook = "v2-scene-prompt";
    line.addEventListener("click", (event) => {
      event.stopPropagation();
      openViewer({ kind: "scene", id: scene.scene_id }, { tab: "frames", trigger: line });
    });
    head.append(line);
  }

  const zones = el("div", "v2-scene-zones");
  zones.append(
    inFrameZone(project, revision, scene),
    localZone(project, revision, scene),
    videoReferenceZone(project, revision, scene),
    framesZone(project, revision, scene),
  );

  const open = el("button", "v2-scene-open", String(position));
  open.type = "button";
  open.dataset.hook = "v2-scene-open";
  open.setAttribute("aria-label", `Открыть сцену ${position}: ${scene?.title || ""}`.trim());
  open.addEventListener("click", () => openViewer(
    { kind: "scene", id: scene?.scene_id }, { tab: "frames", trigger: open },
  ));

  row.append(open, head, zones);
  return row;
}

/** Сцены проекта по порядку — общий порядок для всех экранов v2. */
export function scenesInOrder(project) {
  return [...(project?.scenes || [])].sort((left, right) => (left?.order || 0) - (right?.order || 0));
}

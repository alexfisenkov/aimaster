// Четыре правые зоны строки сцены (спецификация §3.2):
// «В кадре», «Только здесь», «Видеореференс», «Кадры».
//
// Как читается включённость: общий референс участвует в сцене, если его
// `reference_id` перечислен в `scene.links.reference_ids` (домен пишет
// туда теги при `reference add --all-scenes`/`--scene` и при
// `scene-reference-toggle`). Невключённые показываются приглушёнными, а
// не прячутся: владелец должен видеть, что их можно включить.
// «Только здесь» — референсы с `local: true` и `scene_id` этой сцены.
// «Видеореференс» — они же с `kind: "video"`; подпись — по `usage`.

import { requestAgentPrompt } from "../chat-prompt-dialog.js";
import { addReference, toggleSceneReference, uploadFrame } from "./chat-prompts.js";
import { variantCounts, variantStatus } from "./counts.js";
import { chatButton, el, openViewer, thumb } from "./dom.js";

const USAGE_WORDS = Object.freeze({
  reference: "пример",
  motion: "движение",
  continue: "продолжение",
  edit: "правка",
});

const SLOT_WORDS = Object.freeze({ first: "первый", last: "последний" });

function zone(title) {
  const row = el("div", "v2-zone");
  row.append(el("span", "v2-zone-title", title));
  const items = el("div", "v2-zone-items");
  row.append(items);
  return { row, items };
}

/** Картинка референса: свой файл, а если его нет — выбранный вариант. */
function referenceAsset(project, reference) {
  if (typeof reference.asset_url === "string" && reference.asset_url) return reference.asset_url;
  return variantCounts(project, { referenceId: reference.reference_id }).selected?.asset_url || null;
}

function avatar(project, reference, included, onClick) {
  const name = reference.label || reference.reference_id;
  const node = el("button", "v2-avatar");
  node.type = "button";
  node.dataset.kind = reference.kind;
  node.dataset.included = String(included);
  node.setAttribute("aria-label", `${name}: ${included ? "в кадре" : "не в кадре"}`);
  node.append(thumb(referenceAsset(project, reference), name), el("span", "v2-avatar-name", name));
  node.addEventListener("click", () => onClick(node));
  return node;
}

/** «В кадре»: общие референсы проекта, включённые и выключенные. */
export function inFrameZone(project, revision, scene) {
  const { row, items } = zone("В кадре");
  const shared = (project?.references || []).filter((item) => item?.local !== true && item.kind !== "video");
  const included = new Set(scene?.links?.reference_ids || []);
  if (!shared.length) items.append(el("span", "v2-zone-none", "нет общих референсов"));
  for (const reference of shared) {
    const inside = included.has(reference.reference_id);
    items.append(avatar(project, reference, inside, (node) => requestAgentPrompt(
      toggleSceneReference({ project, revision, sceneId: scene.scene_id, reference, include: !inside }),
      node,
    )));
  }
  return row;
}

/** «Только здесь»: референсы, заведённые для одной этой сцены. */
export function localZone(project, revision, scene) {
  const { row, items } = zone("Только здесь");
  const locals = (project?.references || []).filter(
    (item) => item?.local === true && item.scene_id === scene?.scene_id && item.kind !== "video",
  );
  if (!locals.length) items.append(el("span", "v2-zone-none", "нет"));
  for (const reference of locals) {
    items.append(avatar(project, reference, true, () => openViewer(
      { kind: "reference", id: reference.reference_id }, { tab: "frames" },
    )));
  }
  items.append(chatButton(
    "＋",
    addReference("other", project, revision, { sceneId: scene?.scene_id }),
    "v2-plus",
  ));
  return row;
}

/** «Видеореференс»: движение, продолжение или правка — только из файла. */
export function videoReferenceZone(project, revision, scene) {
  const { row, items } = zone("Видеореференс");
  const videos = (project?.references || []).filter(
    (item) => item?.kind === "video" && item.scene_id === scene?.scene_id,
  );
  if (!videos.length) items.append(el("span", "v2-zone-none", "нет"));
  for (const reference of videos) {
    const slot = el("span", "v2-slot v2-slot-video");
    slot.append(el("span", "v2-slot-label", USAGE_WORDS[reference.usage] || "пример"));
    slot.append(el("span", "v2-slot-caption", reference.label || reference.reference_id));
    items.append(slot);
  }
  items.append(chatButton("＋", addReference("video", project, revision), "v2-plus"));
  return row;
}

/** «Кадры»: слоты «первый» и «последний» — только отмеченные в плане. */
export function framesZone(project, revision, scene) {
  const { row, items } = zone("Кадры");
  const planned = ["first", "last"].filter((slot) => scene?.[slot === "first" ? "need_first" : "need_last"] === true);
  if (!planned.length) items.append(el("span", "v2-zone-none", "без кадров"));
  for (const slot of planned) {
    const counts = variantCounts(project, { sceneId: scene.scene_id, slot });
    const status = variantStatus(counts);
    const button = el("button", "v2-slot");
    button.type = "button";
    button.dataset.slot = slot;
    button.dataset.hook = "v2-frame-slot";
    button.setAttribute("aria-label", `${SLOT_WORDS[slot]} кадр: ${status}`);
    button.append(thumb(counts.selected?.asset_url || null, `${SLOT_WORDS[slot]} кадр`));
    button.append(el("span", "v2-slot-label", SLOT_WORDS[slot]), el("span", "v2-slot-caption", status));
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openViewer({ kind: "scene", id: scene.scene_id }, { tab: "frames", slot, trigger: button });
    });
    items.append(button);
  }
  items.append(chatButton(
    "＋",
    uploadFrame({ project, revision, sceneId: scene?.scene_id, slot: planned.length ? "last" : "first" }),
    "v2-plus",
  ));
  return row;
}

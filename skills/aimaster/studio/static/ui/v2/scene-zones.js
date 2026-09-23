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
import { statusLine } from "./board-bits.js";
import { variantCounts, variantStatus } from "./counts.js";
import { chatButton, el, openViewer } from "./dom.js";
import { renderPreview } from "./preview.js";
import { statusTone } from "./status-tone.js";

const USAGE_WORDS = Object.freeze({
  reference: "пример",
  motion: "движение",
  continue: "продолжение",
  edit: "правка",
});

const SLOT_WORDS = Object.freeze({ first: "первый", last: "последний" });

/** Ряд зоны: подпись в колонке 104px и содержимое. `data-empty` — ряд
 * без единого референса или кадра: телефон такие ряды прячет, их «＋»
 * живёт в шторке карточки. */
function zone(title, name) {
  const row = el("div", "v2-zone");
  row.dataset.zone = name;
  row.append(el("span", "v2-zone-title", title));
  const items = el("div", "v2-zone-items");
  row.append(items);
  return { row, items };
}

function markEmpty(row, empty) {
  row.dataset.empty = String(Boolean(empty));
  return row;
}

function plus(label, request) {
  const button = chatButton("＋", request, "v2-plus");
  button.setAttribute("aria-label", label);
  return button;
}

/** Какие кадры сцены запланированы: `first`, `last` или оба. */
export function plannedSlots(scene) {
  return ["first", "last"].filter((slot) => scene?.[slot === "first" ? "need_first" : "need_last"] === true);
}

/** Файл референса: свой, а если его нет — выбранный вариант генерации. */
function referenceFile(project, reference) {
  if (typeof reference.asset_url === "string" && reference.asset_url) return reference;
  const selected = variantCounts(project, { referenceId: reference.reference_id }).selected;
  return selected ? { ...selected, media_type: selected.media_type || reference.media_type, kind: reference.kind } : null;
}

function avatar(project, reference, included, onClick) {
  const name = reference.label || reference.reference_id;
  const node = el("button", "v2-avatar");
  node.type = "button";
  node.dataset.kind = reference.kind;
  node.dataset.included = String(included);
  node.title = `${name}: ${included ? "в кадре — нажмите, чтобы убрать" : "не в кадре — нажмите, чтобы добавить"}`;
  node.setAttribute("aria-label", `${name}: ${included ? "в кадре" : "не в кадре"}`);
  const file = referenceFile(project, reference);
  // Нет файла — первая буква имени на тёмном квадрате: подпись «нет
  // картинки» в 34px не влезает, а буква говорит, кто это.
  if (file) node.append(renderPreview(file, { label: name, small: true }));
  else node.append(el("span", "v2-avatar-initial", String(name).trim().charAt(0).toUpperCase() || "?"));
  node.append(el("span", "v2-avatar-name", name));
  node.addEventListener("click", () => onClick(node));
  return node;
}

/** Референс «только здесь»: картинка 26px и имя. */
function localChip(project, reference) {
  const name = reference.label || reference.reference_id;
  const node = el("button", "v2-ref-chip");
  node.type = "button";
  node.dataset.kind = reference.kind;
  node.setAttribute("aria-label", `${name}: только в этой сцене`);
  const picture = el("span", "v2-ref-chip-picture");
  picture.append(renderPreview(referenceFile(project, reference), { label: name, small: true }));
  node.append(picture, el("span", "v2-ref-chip-name", name));
  node.addEventListener("click", () => openViewer(
    { kind: "reference", id: reference.reference_id }, { tab: "frames", trigger: node },
  ));
  return node;
}

/** «В кадре»: общие референсы проекта, включённые и выключенные. */
export function inFrameZone(project, revision, scene) {
  const { row, items } = zone("В кадре", "in-frame");
  const shared = (project?.references || []).filter((item) => item?.local !== true && item.kind !== "video");
  const included = new Set(scene?.links?.reference_ids || []);
  markEmpty(row, !shared.length);
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
  const { row, items } = zone("Только здесь", "local");
  const locals = (project?.references || []).filter(
    (item) => item?.local === true && item.scene_id === scene?.scene_id && item.kind !== "video",
  );
  markEmpty(row, !locals.length);
  if (!locals.length) items.append(el("span", "v2-zone-none", "нет"));
  for (const reference of locals) items.append(localChip(project, reference));
  items.append(plus(
    "Добавить референс только для этой сцены",
    addReference("other", project, revision, { sceneId: scene?.scene_id }),
  ));
  return row;
}

/** «Видеореференс»: движение, продолжение или правка — только из файла. */
export function videoReferenceZone(project, revision, scene) {
  const { row, items } = zone("Видеореференс", "video-ref");
  const videos = (project?.references || []).filter(
    (item) => item?.kind === "video" && item.scene_id === scene?.scene_id,
  );
  markEmpty(row, !videos.length);
  if (!videos.length) items.append(el("span", "v2-zone-none", "нет"));
  for (const reference of videos) {
    const name = reference.label || reference.reference_id;
    const chip = el("button", "v2-ref-chip v2-ref-chip-video");
    chip.type = "button";
    chip.dataset.hook = "v2-video-reference";
    chip.setAttribute("aria-label", `Видеореференс «${name}»: ${USAGE_WORDS[reference.usage] || "пример"}`);
    const picture = el("span", "v2-ref-chip-picture");
    picture.append(renderPreview(reference, { fallback: "video", label: name, small: true }));
    chip.append(
      picture,
      el("span", "v2-usage", USAGE_WORDS[reference.usage] || "пример"),
      el("span", "v2-ref-chip-name", name),
    );
    chip.addEventListener("click", (event) => {
      event.stopPropagation();
      openViewer({ kind: "reference", id: reference.reference_id }, { tab: "frames", trigger: chip });
    });
    items.append(chip);
  }
  items.append(plus("Добавить видеореференс", addReference("video", project, revision)));
  return row;
}

/** «Кадры»: слоты «первый» и «последний» — только отмеченные в плане. */
export function framesZone(project, revision, scene) {
  const { row, items } = zone("Кадры", "frames");
  const planned = plannedSlots(scene);
  markEmpty(row, !planned.length);
  if (!planned.length) items.append(el("span", "v2-zone-none", "без кадров"));
  for (const slot of planned) {
    const counts = variantCounts(project, { sceneId: scene.scene_id, slot });
    const status = variantStatus(counts);
    const button = el("button", "v2-slot");
    button.type = "button";
    button.dataset.slot = slot;
    button.dataset.hook = "v2-frame-slot";
    button.setAttribute("aria-label", `${SLOT_WORDS[slot]} кадр: ${status}`);
    button.append(renderPreview(counts.selected, { label: `${SLOT_WORDS[slot]} кадр`, emptyText: "нет кадра" }));
    const label = el("span", "v2-slot-label", SLOT_WORDS[slot]);
    label.append(el("span", "v2-phone-only", " кадр"));
    button.append(label, statusLine(status, statusTone(counts), "v2-status v2-slot-status"));
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openViewer({ kind: "scene", id: scene.scene_id }, { tab: "frames", slot, trigger: button });
    });
    items.append(button);
  }
  items.append(plus(
    "Загрузить свой кадр",
    uploadFrame({ project, revision, sceneId: scene?.scene_id, slot: planned.length ? "last" : "first" }),
  ));
  return row;
}

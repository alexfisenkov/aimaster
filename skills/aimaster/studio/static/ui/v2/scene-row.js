// Строка сцены (спецификация §3.2 и §3.3, хэндофф 2026-09-23): карточка,
// слева номер, название, время, бейдж, описание и чип промпта; справа
// ряды зон. Строка одна на два экрана: на «Кадрах» справа четыре зоны про
// картинку, на «Видео» — превью клипа и «Продолжение». Клик открывает
// просмотрщик на этой сцене. На телефоне те же узлы переставляет CSS, а
// «＋» внизу карточки открывает шторку со всеми «добавить» сцены.

import { requestAgentPrompt } from "../chat-prompt-dialog.js";
import { addReference, uploadFrame } from "./chat-prompts.js";
import { badge, dot } from "./board-bits.js";
import { variantCounts } from "./counts.js";
import { promptGroups } from "./variants.js";
import { activeBlockText } from "./scenario-model.js";
import { clock, el, openViewer } from "./dom.js";
import { framesZone, inFrameZone, localZone, plannedSlots, videoReferenceZone } from "./scene-zones.js";
import { clipZone, continuationZone } from "./scene-zones-video.js";
import { openSheet } from "./sheet.js";
import { clipBadge, framesBadge } from "./status-tone.js";
import { clipStatus } from "./video-model.js";

const PROMPT_STATUS = Object.freeze({
  approved: "готов",
  pending: "ждёт решения",
  rejected: "нужны правки",
});

/**
 * Где лежит действующая версия промпта каждого места. Ключи те же, что
 * читает просмотрщик (`viewer-prompt.js`) и пишет домен
 * (`domain_positions`): у кадров сцены свои промпты, у движения свой.
 */
const PROMPT_LINKS = Object.freeze({
  first: "first_frame_prompt_version_id",
  last: "last_frame_prompt_version_id",
  image: "image_prompt_version_id",
  motion: "motion_prompt_version_id",
});

const PROMPT_WORDS = Object.freeze({
  first: "промпт первого кадра",
  last: "промпт последнего кадра",
  image: "промпт изображения",
  motion: "промпт движения",
});

/**
 * Промпт какого места показывать в строке сцены на экране «Кадры».
 * У фотопроекта это изображение сцены, у видео — запланированный кадр
 * (`need_first`/`need_last`). Кадров не запланировано — показывать
 * нечего: промпт движения здесь не при чём, он живёт на «Видео».
 *
 * @param {object} project `snapshot.active_project`
 * @param {object} scene запись сцены
 * @returns {"first"|"last"|"image"|null}
 */
export function framePromptKind(project, scene) {
  if (project?.type === "photo") return "image";
  if (scene?.need_first === true) return "first";
  if (scene?.need_last === true) return "last";
  return null;
}

/**
 * «промпт движения v2 · готов» для строки сцены: номер версии в своей
 * цепочке и её статус. `null`, если промпта этого места у сцены нет.
 * @param {object} project `snapshot.active_project`
 * @param {object} scene запись сцены
 * @param {"motion"|"first"|"last"|"image"|null} [kind] промпт какого места
 */
export function scenePromptLine(project, scene, kind = "motion") {
  const linkKey = PROMPT_LINKS[kind];
  const versionId = linkKey ? scene?.links?.[linkKey] : null;
  if (typeof versionId !== "string" || !versionId) return null;
  const collection = kind === "motion" ? project?.motion_prompts : project?.image_prompts;
  const current = (collection || []).find((item) => item?.version_id === versionId);
  if (!current) return null;
  const versions = promptGroups(collection).get(current.prompt_id) || [current];
  const number = versions.findIndex((item) => item.version_id === versionId) + 1;
  const status = current.stale === true ? "устарел" : PROMPT_STATUS[current.status] || "в работе";
  return {
    text: `${PROMPT_WORDS[kind]} v${number || 1} · ${status}`,
    versionId,
    kind,
    stale: current.stale === true,
    tone: current.stale !== true && current.status === "approved" ? "ok" : "warn",
  };
}

/**
 * «＋» внизу карточки сцены на телефоне: шторка со всем, что можно
 * добавить в сцену. Каждый пункт — тот же запрос агенту, что и «＋» в
 * рядах зон на десктопе.
 */
function sceneAddButton(project, revision, scene) {
  const button = el("button", "v2-scene-add", "＋");
  button.type = "button";
  button.dataset.hook = "v2-scene-add";
  button.setAttribute("aria-label", "Добавить в сцену");
  const planned = plannedSlots(scene);
  const ask = (request) => requestAgentPrompt(request, button);
  button.addEventListener("click", () => openSheet({
    title: "Добавить в сцену",
    returnFocus: button,
    items: [
      { label: "Референс только для этой сцены", onSelect: () => ask(addReference("other", project, revision, { sceneId: scene?.scene_id })) },
      { label: "Видеореференс", onSelect: () => ask(addReference("video", project, revision)) },
      { label: "Свой кадр", onSelect: () => ask(uploadFrame({ project, revision, sceneId: scene?.scene_id, slot: planned.length ? "last" : "first" })) },
    ],
  }));
  return button;
}

/** Бейдж у названия: готовы ли кадры сцены или выбран ли её клип. */
function sceneBadge(project, scene, video) {
  const state = video
    ? clipBadge(clipStatus(project, scene))
    : framesBadge(plannedSlots(scene).map((slot) => variantCounts(project, { sceneId: scene.scene_id, slot })));
  return state ? badge(state.text, state.tone) : null;
}

/**
 * @param {object} project `snapshot.active_project`
 * @param {number} revision `snapshot.revision`
 * @param {object} scene запись сцены
 * @param {number} position номер сцены для человека, начиная с 1
 * @param {{mode?: "frames"|"video"}} [options] какой экран рисует строку
 * @returns {HTMLElement} `<article>` строки
 */
export function renderSceneRow(project, revision, scene, position, { mode = "frames" } = {}) {
  const video = mode === "video";
  const tab = video ? "video" : "frames";
  const row = el("article", "v2-scene");
  row.dataset.hook = "v2-scene";
  row.dataset.mode = mode;
  row.dataset.sceneId = scene?.scene_id || "";

  const open = el("button", "v2-scene-open", String(position));
  open.type = "button";
  open.dataset.hook = "v2-scene-open";
  open.setAttribute("aria-label", `Открыть сцену ${position}: ${scene?.title || ""}`.trim());
  open.addEventListener("click", () => openViewer(
    { kind: "scene", id: scene?.scene_id }, { tab, slot: video ? "video" : undefined, trigger: open },
  ));

  const titleLine = el("div", "v2-scene-titleline");
  titleLine.append(
    el("b", "v2-scene-title", scene?.title || `Сцена ${position}`),
    el("span", "v2-time v2-scene-time", `${clock(scene?.start_ms)}–${clock(scene?.end_ms)}`),
  );
  const state = sceneBadge(project, scene, video);
  if (state) titleLine.append(state);

  const body = el("div", "v2-scene-body");
  body.append(titleLine, el("p", "v2-scene-text", activeBlockText(scene)));

  const actions = el("div", "v2-scene-actions");
  const prompt = scenePromptLine(project, scene, video ? "motion" : framePromptKind(project, scene));
  if (prompt) {
    const line = el("button", "v2-chip v2-scene-prompt");
    line.type = "button";
    line.dataset.hook = "v2-scene-prompt";
    line.dataset.promptKind = prompt.kind;
    line.append(dot(prompt.tone), el("span", "v2-chip-text", prompt.text));
    line.addEventListener("click", (event) => {
      event.stopPropagation();
      openViewer(
        { kind: "scene", id: scene.scene_id },
        { tab, slot: video ? "video" : prompt.kind, trigger: line },
      );
    });
    actions.append(line);
  }
  if (!video) actions.append(sceneAddButton(project, revision, scene));
  if (actions.childElementCount) body.append(actions);

  const main = el("div", "v2-scene-main");
  main.append(open, body);

  const zones = el("div", "v2-scene-zones");
  if (video) {
    zones.append(clipZone(project, scene, position), continuationZone(project, scene));
    const references = videoReferenceZone(project, revision, scene);
    if (references.dataset.empty !== "true") zones.append(references);
  } else {
    zones.append(
      inFrameZone(project, revision, scene),
      localZone(project, revision, scene),
      videoReferenceZone(project, revision, scene),
      framesZone(project, revision, scene),
    );
  }

  row.append(main, zones);
  return row;
}

/** Сцены проекта по порядку — общий порядок для всех экранов v2. */
export function scenesInOrder(project) {
  return [...(project?.scenes || [])].sort((left, right) => (left?.order || 0) - (right?.order || 0));
}

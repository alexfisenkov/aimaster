// «Осталось решить: …» — собственный подсчёт нерешённого, который
// дашборд делает поверх серверного `stage_readiness` (спецификация §3).
// Сервер отвечает одним кодом причины; здесь мы называем человеку
// конкретные места, где ещё нет выбора, и куда за ним идти: каждый пункт
// несёт адрес для просмотрщика (`studio:open-viewer`). Чистые функции.

import { AUDIO_LAYERS } from "./audio-model.js";
import { selectedResultVersion } from "./variants.js";

const PROMPT_COLLECTIONS = Object.freeze(["image_prompts", "motion_prompts", "audio_prompts"]);

function scenesInOrder(project) {
  return [...(project?.scenes || [])].sort((left, right) => (left?.order || 0) - (right?.order || 0));
}

function sceneName(scene, position) {
  const title = typeof scene?.title === "string" && scene.title.trim() ? scene.title.trim() : "";
  return title ? `Сцена ${position} «${title}»` : `Сцена ${position}`;
}

/**
 * Один пункт «осталось решить».
 * @param {string} label что сказать человеку
 * @param {{kind: string, id: string}|null} target что открыть в просмотрщике
 * @param {string} [tab] вкладка просмотрщика
 * @param {string} [slot] слот кадра (`first`/`last`/`video`)
 */
function entry(label, target = null, tab = null, slot = null) {
  // Адрес без строкового `id` просмотрщику нечего открыть: такой пункт
  // становится надписью, а не кнопкой (подвал — `footer.js`).
  const usable = target && typeof target.id === "string" && target.id !== "" ? target : null;
  return { label, target: usable, tab: usable ? tab : null, slot: usable ? slot : null };
}

/** Референсы, которые решено генерировать, но вариант ещё не выбран. */
function referencesWithoutChoice(project) {
  return (project?.references || [])
    .filter((item) => item?.source === "generate" && item.kind !== "video")
    .filter((item) => !selectedResultVersion(project, { referenceId: item.reference_id }))
    .map((item) => entry(
      `референс «${item.label || item.reference_id}»`,
      { kind: "reference", id: item.reference_id },
      "frames",
    ));
}

/** Слоты кадров, отмеченные в плане (`need_first`/`need_last`) и пустые. */
function framesWithoutChoice(project) {
  const out = [];
  scenesInOrder(project).forEach((scene, index) => {
    for (const [slot, need, word] of [["first", "need_first", "первый кадр"], ["last", "need_last", "последний кадр"]]) {
      if (scene?.[need] !== true) continue;
      if (selectedResultVersion(project, { sceneId: scene.scene_id, slot })) continue;
      out.push(entry(
        `${sceneName(scene, index + 1)}: ${word}`,
        { kind: "scene", id: scene.scene_id },
        "frames",
        slot,
      ));
    }
  });
  return out;
}

/** Сцены без выбранного клипа — только при «кадр за кадром». */
function clipsWithoutChoice(project) {
  if (project?.gen_mode === "one_shot") {
    return selectedResultVersion(project, { sceneId: "oneshot" })
      ? []
      : [entry("клип всего ролика", { kind: "scene", id: "oneshot" }, "video", "video")];
  }
  return scenesInOrder(project)
    .map((scene, index) => [scene, index + 1])
    .filter(([scene]) => !selectedResultVersion(project, { sceneId: scene.scene_id, slot: "video" }))
    .map(([scene, position]) => entry(
      `${sceneName(scene, position)}: клип`,
      { kind: "scene", id: scene.scene_id },
      "video",
      "video",
    ));
}

const PROMPT_TABS = Object.freeze({
  image_prompts: "frames",
  motion_prompts: "video",
  audio_prompts: "audio",
});

/** Куда вести за устаревшим промптом: владелец позиции в просмотрщике. */
function promptOwnerTarget(position, collection) {
  if (position.kind === "reference" && position.tag) {
    return { target: { kind: "reference", id: position.tag }, tab: "frames" };
  }
  if (position.kind === "audio" && position.layer) {
    return { target: { kind: "layer", id: position.layer }, tab: "audio" };
  }
  if (position.kind === "oneshot") {
    return { target: { kind: "scene", id: "oneshot" }, tab: "video", slot: "video" };
  }
  if (position.scene_id) {
    const slot = position.kind === "last_frame" ? "last" : position.kind === "video" ? "video" : "first";
    return { target: { kind: "scene", id: position.scene_id }, tab: PROMPT_TABS[collection] || "frames", slot };
  }
  return { target: null };
}

/** Чей это промпт — словами, по позиции активного плана. */
function promptOwnerName(project, position) {
  if (position.kind === "reference") {
    const reference = (project.references || []).find((item) => item?.reference_id === position.tag);
    return `референса «${reference?.label || position.tag}»`;
  }
  if (position.kind === "audio") {
    const meta = AUDIO_LAYERS.find((item) => item.layer === position.layer);
    return `слоя «${meta?.name || position.layer}»`;
  }
  const scenes = scenesInOrder(project);
  const index = scenes.findIndex((scene) => scene?.scene_id === position.scene_id);
  return index < 0 ? "этого шага" : sceneName(scenes[index], index + 1).toLowerCase();
}

/**
 * Промпты, помеченные проекцией как устаревшие (`stale`), — но только те,
 * что относятся к обязательной позиции действующего плана. Легаси-промпт у
 * загруженного референса тоже помечен `stale`, а решать в нём нечего:
 * позиции у него нет. И пустой слой звука решать нечего тем более: его
 * позиция не обязательна (`required: false`), этап через неё проходит, —
 * оставшийся с прошлого захода промпт не должен держать кнопку.
 */
function stalePrompts(project, collections) {
  const positions = (project?.positions || []).filter(
    (item) => item && item.prompt_group_id && item.required !== false,
  );
  const out = [];
  for (const collection of collections) {
    for (const prompt of project?.[collection] || []) {
      if (prompt?.stale !== true) continue;
      const position = positions.find((item) => item.prompt_group_id === prompt.prompt_id);
      if (!position) continue;
      const place = promptOwnerTarget(position, collection);
      out.push(entry(`промпт ${promptOwnerName(project, position)} устарел`, place.target, place.tab, place.slot));
    }
  }
  return out;
}

/**
 * Что ещё не решено на этой стадии — с адресом для просмотрщика.
 *
 * @param {object} project `snapshot.active_project`
 * @param {string} [stage] стадия; по умолчанию `project.stage`
 * @returns {{label: string, target: {kind: string, id: string}|null,
 *            tab: string|null, slot: string|null}[]}
 *   пустой список означает «решать нечего»
 */
export function unresolvedEntries(project, stage = project?.stage) {
  if (!project || typeof project !== "object") return [];
  if (stage === "image_plan") {
    return [...referencesWithoutChoice(project), ...stalePrompts(project, ["image_prompts"])];
  }
  if (stage === "image_results") {
    return [
      ...referencesWithoutChoice(project),
      ...framesWithoutChoice(project),
      ...stalePrompts(project, ["image_prompts"]),
    ];
  }
  if (stage === "motion") {
    return [...clipsWithoutChoice(project), ...stalePrompts(project, ["motion_prompts"])];
  }
  if (stage === "audio") {
    return stalePrompts(project, ["audio_prompts"]);
  }
  if (stage === "scenario" || stage === "assembly") {
    return [];
  }
  return stalePrompts(project, PROMPT_COLLECTIONS);
}

/**
 * Те же пункты готовыми строками — для счёта и старых потребителей.
 * @returns {string[]}
 */
export function unresolvedItems(project, stage = project?.stage) {
  return unresolvedEntries(project, stage).map((item) => item.label);
}

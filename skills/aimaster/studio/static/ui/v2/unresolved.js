// «Осталось решить: …» — собственный подсчёт нерешённого, который
// дашборд делает поверх серверного `stage_readiness` (спецификация §3).
// Сервер отвечает одним кодом причины; здесь мы называем человеку
// конкретные места, где ещё нет выбора. Чистые функции, без DOM.

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

/** Референсы, которые решено генерировать, но вариант ещё не выбран. */
function referencesWithoutChoice(project) {
  return (project?.references || [])
    .filter((item) => item?.source === "generate" && item.kind !== "video")
    .filter((item) => !selectedResultVersion(project, { referenceId: item.reference_id }))
    .map((item) => `референс «${item.label || item.reference_id}»`);
}

/** Слоты кадров, отмеченные в плане (`need_first`/`need_last`) и пустые. */
function framesWithoutChoice(project) {
  const out = [];
  scenesInOrder(project).forEach((scene, index) => {
    for (const [slot, need, word] of [["first", "need_first", "первый кадр"], ["last", "need_last", "последний кадр"]]) {
      if (scene?.[need] !== true) continue;
      if (selectedResultVersion(project, { sceneId: scene.scene_id, slot })) continue;
      out.push(`${sceneName(scene, index + 1)}: ${word}`);
    }
  });
  return out;
}

/** Сцены без выбранного клипа — только при «кадр за кадром». */
function clipsWithoutChoice(project) {
  if (project?.gen_mode === "one_shot") {
    return selectedResultVersion(project, { sceneId: "oneshot" }) ? [] : ["клип всего ролика"];
  }
  return scenesInOrder(project)
    .map((scene, index) => [scene, index + 1])
    .filter(([scene]) => !selectedResultVersion(project, { sceneId: scene.scene_id, slot: "video" }))
    .map(([scene, position]) => `${sceneName(scene, position)}: клип`);
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
      out.push(`промпт ${promptOwnerName(project, position)} устарел`);
    }
  }
  return out;
}

/**
 * Что ещё не решено на этой стадии — готовыми строками для человека.
 *
 * @param {object} project `snapshot.active_project`
 * @param {string} [stage] стадия; по умолчанию `project.stage`
 * @returns {string[]} пустой список означает «решать нечего»
 */
export function unresolvedItems(project, stage = project?.stage) {
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

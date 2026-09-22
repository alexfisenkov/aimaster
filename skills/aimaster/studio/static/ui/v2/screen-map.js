// Пять экранов пути и одна главная кнопка внизу каждого из них
// (спецификация §2.1, §3). Серверные стадии не меняются: «Кадры» — это
// один экран поверх двух стадий, `image_plan` и `image_results`.
// Чистые функции, без DOM.

import { unresolvedItems } from "./unresolved.js";

export const SCREENS = Object.freeze(["scenario", "frames", "video", "audio", "assembly"]);

export const SCREEN_LABELS = Object.freeze({
  scenario: "Сценарий",
  frames: "Кадры",
  video: "Видео",
  audio: "Звук",
  assembly: "Сборка",
});

export const SCREEN_HINTS = Object.freeze({
  scenario: "О чём ролик и из каких сцен он состоит.",
  frames: "Кто и что в кадре: референсы, промпты и картинки сцен.",
  video: "Движение в каждой сцене.",
  audio: "Голос, музыка, эффекты и атмосфера.",
  assembly: "Всё вместе — готовый ролик.",
});

const STAGE_BY_SCREEN = Object.freeze({
  scenario: Object.freeze(["scenario"]),
  frames: Object.freeze(["image_plan", "image_results"]),
  video: Object.freeze(["motion"]),
  audio: Object.freeze(["audio"]),
  assembly: Object.freeze(["assembly"]),
});

const PRIMARY_LABELS = Object.freeze({
  scenario: "Одобрить сценарий → Кадры",
  image_plan: "Одобрить промпты и референсы → кадры",
  image_results: "Одобрить кадры → Видео",
  motion: "Одобрить видео → Звук",
  audio: "Одобрить звук → Сборка",
  assembly: "Принять ролик",
});

const READINESS_REASONS = Object.freeze({
  blocked: "сначала ответьте агенту в чате",
  already_approved: "шаг уже одобрен",
  incomplete_storyboard: "не закончена раскадровка",
  missing_prompts: "не у всех позиций есть промпт",
  unaccepted_positions: "не приняты обязательные результаты",
  missing_final_material: "нет финального материала",
});

/** Экраны этого типа проекта: у фотопроекта нет ни видео, ни звука. */
export function screensFor(projectType) {
  return projectType === "photo"
    ? SCREENS.filter((screen) => screen !== "video" && screen !== "audio")
    : [...SCREENS];
}

/** Серверная стадия → экран, на котором она живёт. */
export function screenForStage(stage) {
  for (const screen of SCREENS) {
    if (STAGE_BY_SCREEN[screen].includes(stage)) return screen;
  }
  return null;
}

/** Экран → серверные стадии, которые он показывает. */
export function stagesForScreen(screen) {
  return [...(STAGE_BY_SCREEN[screen] || [])];
}

/**
 * Полоса пути: пройденные шаги, текущий и будущие.
 *
 * @param {object} project `snapshot.active_project`
 * @returns {{id: string, label: string, hint: string,
 *            state: "done"|"current"|"next"}[]}
 */
export function pathState(project) {
  const screens = screensFor(project?.type);
  const current = screenForStage(project?.stage);
  const currentIndex = screens.indexOf(current);
  return screens.map((screen, index) => {
    const state = currentIndex < 0 || index > currentIndex ? "next" : index < currentIndex ? "done" : "current";
    const hint = state === "done"
      ? "одобрен"
      : state === "current"
        ? "вы здесь"
        : index === currentIndex + 1 ? "дальше" : "";
    return { id: screen, label: SCREEN_LABELS[screen], hint, state };
  });
}

/**
 * Единственная кнопка внизу экрана и строка «Осталось решить: …».
 *
 * @param {object} project `snapshot.active_project`
 * @returns {{label: string, stage: string|null, enabled: boolean, remaining: string[]}}
 */
export function primaryAction(project) {
  const stage = typeof project?.stage === "string" ? project.stage : null;
  const photoFinish = project?.type === "photo" && stage === "image_results";
  const label = photoFinish ? "Одобрить кадры → Сборка" : PRIMARY_LABELS[stage] || "Одобрить шаг";
  const readiness = project?.stage_readiness || null;
  const remaining = unresolvedItems(project, stage);
  if (readiness && readiness.can_approve !== true && remaining.length === 0) {
    remaining.push(READINESS_REASONS[readiness.reason] || "проверьте материалы этого шага");
  }
  return {
    label,
    stage,
    enabled: Boolean(stage) && readiness?.can_approve === true && remaining.length === 0,
    remaining,
  };
}

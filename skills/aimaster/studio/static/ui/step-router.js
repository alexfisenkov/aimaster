// Presentation-only stage routing. The server remains the sole owner of the
// canonical current stage; this registry merely chooses which already
// unlocked step the dashboard paints.

import { STAGE_LABELS, stageOrderFor } from "./state.js";

export const STEP_HINTS = Object.freeze({
  scenario: "Здесь проверяются сценарий и раскадровка.",
  image_plan: "Здесь решается, какие референсы, кадры и промпты нужны проекту.",
  image_results: "Здесь создаются и принимаются только нужные изображения.",
  motion: "Здесь создаётся и принимается движение.",
  audio: "Атмосфера, эффекты, музыка и голос принимаются отдельно.",
  assembly: "Видно всю дорожку: кадры, видео и звук на одной полосе.",
});

export function resolveStepHint(stageId, projectType) {
  if (stageId === "assembly" && projectType === "photo") {
    return "Здесь собраны принятые изображения проекта.";
  }
  return STEP_HINTS[stageId];
}

const registry = new Map();

export function resolveViewedStage(requestedStage, stageTabs, currentStage) {
  const available = Array.isArray(stageTabs)
    ? stageTabs.some((tab) => tab && tab.stage === requestedStage)
    : false;
  return available ? requestedStage : typeof currentStage === "string" ? currentStage : null;
}

export function stepPosition(stageId, projectType) {
  const order = stageOrderFor(projectType);
  const index = order.indexOf(stageId);
  return index < 0 ? null : { number: index + 1, total: order.length };
}

export function registerStep(stageId, descriptor) {
  if (!Object.prototype.hasOwnProperty.call(STAGE_LABELS, stageId)) {
    throw new TypeError("registerStep requires a supported stage");
  }
  if (
    !descriptor ||
    typeof descriptor.title !== "string" ||
    !descriptor.title.trim() ||
    typeof descriptor.hint !== "string" ||
    !descriptor.hint.trim() ||
    typeof descriptor.render !== "function"
  ) {
    throw new TypeError("registerStep requires title, hint and render");
  }
  const registered = Object.freeze({
    title: descriptor.title,
    hint: descriptor.hint,
    render: descriptor.render,
  });
  registry.set(stageId, registered);
  return registered;
}

export function getRegisteredStep(stageId) {
  return registry.get(stageId) || null;
}

export function renderRegisteredStep(stageId, root, context) {
  const descriptor = getRegisteredStep(stageId);
  if (!descriptor) {
    return false;
  }
  descriptor.render(root, context);
  return true;
}

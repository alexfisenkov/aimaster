import { audioLayerModel, renderAudioLayerCard } from "./audio-layer-card.js";
import { renderStageActions } from "./stage-approval.js";

const LAYER_ORDER = Object.freeze(["atmos", "fx", "music", "voice"]);

export function audioStepModel(snapshot, { readOnly = false } = {}) {
  return {
    layers: LAYER_ORDER.map((layer) => audioLayerModel(snapshot, layer, { readOnly })).filter(Boolean),
    readiness: snapshot?.active_project?.stage_readiness || null,
  };
}

export function renderAudioStep(root, { state, readOnly = false }) {
  root.textContent = "";
  const snapshot = state.snapshot;
  const model = audioStepModel(snapshot, { readOnly });
  const surface = document.createElement("section");
  surface.className = "step-audio";
  const heading = document.createElement("h2");
  heading.textContent = "Звук";
  const hint = document.createElement("p");
  hint.className = "audio-step-hint";
  hint.textContent = "Четыре слоя принимаются отдельно.";
  surface.append(heading, hint);
  for (const layer of model.layers) surface.append(renderAudioLayerCard(layer));
  if (!readOnly && snapshot.view_stage?.current_stage === "audio") {
    renderStageActions(surface, snapshot, {
      approveLabel: "Одобрить звук",
      heading: model.readiness?.can_approve ? "Звук принят" : "Проверьте слои звука",
      description: model.readiness?.can_approve ? "Последний шаг — сборка." : "Примите каждый обязательный слой отдельно.",
      canApprove: model.readiness?.can_approve === true,
    });
  }
  root.append(surface);
}

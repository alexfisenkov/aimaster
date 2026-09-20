import { positionCardModel, renderPositionCard, renderPositionStageApproval } from "./position-card.js";
import { videoModeModel, renderVideoMode } from "./video-mode.js";

export function videoStepModel(snapshot, { readOnly = false } = {}) {
  return (snapshot?.active_project?.positions || []).filter((item) => item.stage === "motion")
    .map((item) => positionCardModel(snapshot, item, { readOnly })).filter(Boolean);
}

export function renderVideoStep(root, { state, readOnly = false }) {
  root.textContent = "";
  const surface = document.createElement("section"); surface.className = "step-video";
  const heading = document.createElement("h2"); heading.textContent = "Видео"; surface.append(heading);
  const cards = videoStepModel(state.snapshot, { readOnly });
  for (const card of cards) {
    const modeControl = card.position.kind === "video" && card.scene
      ? renderVideoMode(videoModeModel(state.snapshot, card.scene, { readOnly })) : null;
    surface.append(renderPositionCard(card, { modeControl }));
  }
  if (!cards.length) { const empty = document.createElement("p"); empty.textContent = "По плану нет позиций видео."; surface.append(empty); }
  renderPositionStageApproval(surface, state.snapshot, "motion", { readOnly }); root.append(surface);
}

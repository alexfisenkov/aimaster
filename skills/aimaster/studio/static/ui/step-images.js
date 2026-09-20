import { positionCardModel, renderPositionCard, renderPositionStageApproval } from "./position-card.js";

export function imageStepModel(snapshot, { readOnly = false } = {}) {
  const cards = (snapshot?.active_project?.positions || []).filter((item) => item.stage === "image_results")
    .map((item) => positionCardModel(snapshot, item, { readOnly })).filter(Boolean);
  return { references: cards.filter((item) => item.position.kind === "reference"),
    frames: cards.filter((item) => item.position.kind !== "reference"), count: cards.length };
}

export function renderImagesStep(root, { state, readOnly = false }) {
  root.textContent = "";
  const model = imageStepModel(state.snapshot, { readOnly });
  const surface = document.createElement("section"); surface.className = "step-images";
  const title = document.createElement("h2"); title.textContent = "Изображения"; surface.append(title);
  if (!model.count) {
    const empty = document.createElement("p"); empty.className = "position-empty";
    empty.textContent = "Генерировать нечего: все референсы загружены, кадры не отмечены."; surface.append(empty);
  }
  for (const [cards, label, hint] of [
    [model.references, "Референсы проекта", "Те, что вы решили не загружать, а сгенерировать."],
    [model.frames, "Кадры", state.snapshot.active_project.type === "photo" ? "Изображение на каждый кадр." : "Только то, что отмечено на шаге промптов."],
  ]) {
    if (!cards.length) continue;
    const section = document.createElement("section"); section.className = "position-section";
    const heading = document.createElement("h3"); heading.textContent = label;
    const description = document.createElement("p"); description.className = "position-section-hint"; description.textContent = hint;
    const grid = document.createElement("div"); grid.className = "position-grid";
    for (const card of cards) grid.append(renderPositionCard(card));
    section.append(heading, description, grid); surface.append(section);
  }
  renderPositionStageApproval(surface, state.snapshot, "image_results", { readOnly }); root.append(surface);
}

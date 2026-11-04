import { el } from "./dom.js";
import { familyData } from "./family-data.js";
import { renderFamilyActions } from "./family-actions.js";
import { SCREEN_LABELS, screensFor } from "./screen-map.js";
import { familyLabel } from "./family.js";
import { t } from "./locale.js";
const advancedOpen = new Map();

export function renderOverview(area, { state, renderers, language }) {
  const snapshot = state.snapshot, project = snapshot.active_project;
  const root = el("div", "am-overview"); root.dataset.hook = "am-overview";
  const library = familyData(project.id).library?.entries || [];
  for (const screen of screensFor(project.type)) {
    const section = el("section", "am-overview-step"); section.dataset.screen = screen;
    section.append(el("h2", "am-step-title", t(SCREEN_LABELS[screen])));
    const content = el("div", "am-overview-content");
    renderers[screen]?.(content, { state, readOnly: false, screen });
    content.querySelector('[data-hook="v2-footer"]')?.remove();
    section.append(content); root.append(section);
    const stages = screen === "frames" ? ["image_plan", "image_results"] : screen === "video" ? ["motion"] : [screen];
    const guides = (project.guide_choices || []).filter((choice) => stages.includes(choice.stage) && choice.source !== "none");
    if (guides.length) {
      const detail = el("details", "am-guide-details"); detail.append(el("summary", "", t("Инструкция для этого этапа")));
      for (const choice of guides) {
        const family = { "nano-banana": "Nano Banana", seedance: "Seedance" }[choice.model_family] || t("Выбранная инструкция");
        detail.append(el("p", "", `${family}${choice.version ? ` ${choice.version}` : ""}`));
      }
      section.append(detail);
    }
  }
  if (library.length) {
    const shelf = el("section", "v2-card am-library"); shelf.append(el("h2", "v2-card-title", familyLabel("library", language)));
    const grid = el("div", "am-library-grid");
    for (const item of library) {
      const card = el("article", "am-library-card");
      const kinds = { character: "Персонаж", location: "Локация", product: "Предмет", style: "Стиль", voice: "Голос", other: "Другое" };
      card.append(el("h3", "", item.label), el("p", "", [t(kinds[item.kind] || "Другое"), ...(item.aliases || [])].join(" · ")));
      if (item.notes) card.append(el("p", "", item.notes));
      if (item.tags?.length) card.append(el("p", "", item.tags.join(" · ")));
      grid.append(card);
    }
    shelf.append(grid); root.append(shelf);
  }
  const advanced = el("details", "am-advanced-actions");
  advanced.open = advancedOpen.get(project.id) || false;
  advanced.addEventListener("toggle", () => advancedOpen.set(project.id, advanced.open));
  advanced.append(el("summary", "", t("Действия агента")), renderFamilyActions(snapshot, language)); root.append(advanced);
  area.append(root);
}

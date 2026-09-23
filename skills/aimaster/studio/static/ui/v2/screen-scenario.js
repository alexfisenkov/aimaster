// Экран «Сценарий» (спецификация §3.1, хэндофф 2026-09-23): две карточки
// в сетке — текст сценария с листалкой версий и раскадровка списком.
// Заголовок экрана рисует оболочка; здесь только «···» справа — правка
// сценария и возврат к нему, оба через чат.

import { placeScreenTools } from "./board-bits.js";
import { clock, el } from "./dom.js";
import { renderFooter } from "./footer.js";
import { screenMenu } from "./screen-menu.js";
import { editScenario, reopenScenario } from "./screen-prompts.js";
import { screenForStage } from "./screen-map.js";
import { scriptVersions, storyboardRows } from "./scenario-model.js";

/** Текст сценария с листалкой ‹ v1 из 3 ›: листается на месте. */
function scriptBlock(project) {
  const { versions, activeIndex } = scriptVersions(project);
  const box = el("section", "v2-card v2-script");
  box.dataset.hook = "v2-script";
  const top = el("div", "v2-card-head");
  top.append(el("h2", "v2-card-title", "Текст сценария"));
  box.append(top);
  if (!versions.length) {
    box.append(el("p", "v2-section-hint", "Сценария пока нет — попросите агента его написать."));
    return box;
  }
  let shown = activeIndex;
  const back = el("button", "v2-step-arrow", "‹");
  const forward = el("button", "v2-step-arrow", "›");
  const label = el("span", "v2-script-label");
  const meta = el("p", "v2-script-meta");
  const text = el("p", "v2-script-text");
  const reason = el("p", "v2-script-reason");
  for (const arrow of [back, forward]) arrow.type = "button";
  back.setAttribute("aria-label", "Предыдущая версия сценария");
  forward.setAttribute("aria-label", "Следующая версия сценария");

  const paint = () => {
    const version = versions[shown];
    label.textContent = `v${shown + 1} из ${versions.length}`;
    meta.textContent = shown === activeIndex
      ? "активная версия · сейчас в работе"
      : shown < activeIndex ? "прежняя версия" : "более новая версия, не в работе";
    text.textContent = version?.text || "";
    reason.textContent = version?.reason ? `Почему так: ${version.reason}` : "";
    reason.hidden = !version?.reason;
    back.disabled = shown === 0;
    forward.disabled = shown === versions.length - 1;
  };
  back.addEventListener("click", () => { shown = Math.max(0, shown - 1); paint(); });
  forward.addEventListener("click", () => { shown = Math.min(versions.length - 1, shown + 1); paint(); });
  paint();

  const bar = el("div", "v2-script-bar");
  bar.append(back, label, forward);
  top.append(bar);
  box.append(meta, text, reason);
  return box;
}

/** Раскадровка: номер · название · время · текст. */
function storyboard(project) {
  const rows = storyboardRows(project);
  const list = el("section", "v2-card v2-storyboard");
  list.dataset.hook = "v2-storyboard";
  list.append(el("h2", "v2-card-title", `Раскадровка · ${rows.length}`));
  if (!rows.length) {
    list.append(el("p", "v2-section-hint", "Сцен пока нет — попросите агента разбить сценарий на сцены."));
    return list;
  }
  for (const row of rows) {
    const item = el("article", "v2-storyboard-row");
    item.dataset.sceneId = row.sceneId;
    const body = el("div", "v2-storyboard-body");
    const line = el("div", "v2-storyboard-line");
    line.append(el("b", "v2-storyboard-title", row.title));
    if (row.startMs !== null) line.append(el("span", "v2-time", `${clock(row.startMs)}–${clock(row.endMs)}`));
    body.append(line, el("p", "v2-storyboard-text", row.text));
    item.append(el("span", "v2-storyboard-number", String(row.position)), body);
    list.append(item);
  }
  return list;
}

/**
 * @param {HTMLElement} root куда рисовать (очищается)
 * @param {{state: object, screen?: string}} context `state.snapshot` — весь snapshot
 */
export function renderScenarioScreen(root, { state, screen = "scenario" } = {}) {
  root.textContent = "";
  const snapshot = state?.snapshot;
  const project = snapshot?.active_project;
  const surface = el("div", "v2-screen v2-screen-scenario");
  surface.dataset.hook = "v2-screen-scenario";
  if (!project) {
    surface.setAttribute("aria-busy", "true");
    surface.append(el("p", "", "Загружаем сценарий…"));
    root.append(surface);
    return;
  }
  const passed = screenForStage(project.stage) !== "scenario";
  const { versions, activeIndex } = scriptVersions(project);
  const items = [{ label: "Изменить сценарий → чат", request: editScenario(project, snapshot.revision, versions[activeIndex]) }];
  if (passed) items.push({ label: "Переоткрыть сценарий → чат", request: reopenScenario(project, snapshot.revision) });
  const grid = el("div", "v2-scenario-grid");
  grid.append(scriptBlock(project), storyboard(project));
  surface.append(grid, renderFooter(snapshot, { screen }));
  placeScreenTools(root, surface, screenMenu(items, { title: "Сценарий" }));
  root.append(surface);
}

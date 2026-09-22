// Экран «Сценарий» (спецификация §3.1): текст активной версии с
// листалкой версий, раскадровка списком и одна главная кнопка внизу.
// Правка сценария и возврат к нему — за «···», через чат.

import { clock, el } from "./dom.js";
import { renderFooter } from "./footer.js";
import { moreMenu } from "./more-menu.js";
import { editScenario, reopenScenario } from "./screen-prompts.js";
import { screenForStage } from "./screen-map.js";
import { scriptVersions, storyboardRows } from "./scenario-model.js";

/** Текст сценария с листалкой ‹ v1 из 3 ›: листается на месте. */
function scriptBlock(project) {
  const { versions, activeIndex } = scriptVersions(project);
  const box = el("section", "v2-script");
  box.dataset.hook = "v2-script";
  if (!versions.length) {
    box.append(el("p", "v2-section-hint", "Сценария пока нет — попросите агента его написать."));
    return box;
  }
  let shown = activeIndex;
  const back = el("button", "v2-step-arrow", "‹");
  const forward = el("button", "v2-step-arrow", "›");
  const meta = el("span", "v2-script-meta");
  const text = el("p", "v2-script-text");
  const reason = el("p", "v2-script-reason");
  for (const arrow of [back, forward]) arrow.type = "button";
  back.setAttribute("aria-label", "Предыдущая версия сценария");
  forward.setAttribute("aria-label", "Следующая версия сценария");

  const paint = () => {
    const version = versions[shown];
    meta.textContent = `v${shown + 1} из ${versions.length}${shown === activeIndex ? " · сейчас в работе" : ""}`;
    text.textContent = version?.text || "";
    reason.textContent = version?.reason ? `Почему так: ${version.reason}` : "";
    back.disabled = shown === 0;
    forward.disabled = shown === versions.length - 1;
  };
  back.addEventListener("click", () => { shown = Math.max(0, shown - 1); paint(); });
  forward.addEventListener("click", () => { shown = Math.min(versions.length - 1, shown + 1); paint(); });
  paint();

  const bar = el("div", "v2-script-bar");
  bar.append(back, meta, forward);
  box.append(bar, text, reason);
  return box;
}

/** Раскадровка: номер · название · время · текст. */
function storyboard(project) {
  const rows = storyboardRows(project);
  const list = el("section", "v2-storyboard");
  list.dataset.hook = "v2-storyboard";
  list.append(el("h2", "v2-section-title", `Раскадровка · ${rows.length}`));
  if (!rows.length) {
    list.append(el("p", "v2-section-hint", "Сцен пока нет — попросите агента разбить сценарий на сцены."));
    return list;
  }
  for (const row of rows) {
    const item = el("article", "v2-storyboard-row");
    item.dataset.sceneId = row.sceneId;
    const title = el("b", "v2-scene-title", row.title);
    const time = row.startMs === null ? "" : ` · ${clock(row.startMs)}–${clock(row.endMs)}`;
    if (time) title.append(el("span", "v2-scene-time", time));
    item.append(el("span", "v2-storyboard-number", String(row.position)), title, el("p", "v2-scene-text", row.text));
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
  const head = el("div", "v2-screen-head");
  head.append(el("h2", "v2-section-title", "Сценарий"));
  const menu = moreMenu([passed
    ? { label: "Вернуться к сценарию → чат", request: reopenScenario(project, snapshot.revision) }
    : { label: "Изменить сценарий → чат", request: editScenario(project, snapshot.revision, versions[activeIndex]) }]);
  if (menu) head.append(menu);
  surface.append(head, scriptBlock(project), storyboard(project), renderFooter(snapshot, { screen }));
  root.append(surface);
}

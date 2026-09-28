// Схема монтажа — только просмотр: шесть дорожек, блоки клипов по времени.
// Положение и ширина блока — CSS-переменные `--am-at`/`--am-len` через CSSOM
// (`style.setProperty`): CSP страницы (`style-src 'self'`) запрещает атрибут
// style, но не CSSOM — проверено в Chromium 2026-09-28. Нажатие на блок
// показывает под схемой, чей это клип, где он в ролике и какой кусок
// исходника взят; выбор переживает перерисовку экрана.
//
// Схема, отставшая от монтажа дольше одного опроса (`lagging`,
// montage-entry.js), помечена «обновляется…»; есть отказ опроса или схемы
// (`error`, его текст — в плашке сверху) — «не обновилась»: ждать нечего.
// Блоки помечены для фокуса (`markControlHooks`): перерисовка по опросу не
// уводит его на `<body>`.

import { markControlHooks } from "../card-forms.js";
import { el } from "./dom.js";
import { fmtTime, layerRows, modelDuration } from "./montage-layers-model.js";

const HINT = "Нажмите на блок — покажу, что это за клип и какой кусок исходника взят.";
let chosen = "";

function block(projectId, item, detail, grid) {
  const key = `${projectId}:${item.id}`;
  const button = el("button", "am-block", item.text);
  button.type = "button";
  markControlHooks(button, `montage:${projectId}`, `block:${item.id}`);
  button.dataset.part = "am-block";
  button.style.setProperty("--am-at", String(item.at));
  button.style.setProperty("--am-len", String(item.len));
  button.setAttribute("aria-label", item.detail);
  button.setAttribute("aria-pressed", String(chosen === key));
  button.addEventListener("click", () => {
    chosen = key;
    detail.textContent = item.detail;
    for (const other of grid.querySelectorAll('.am-block[aria-pressed="true"]')) {
      other.setAttribute("aria-pressed", "false");
    }
    button.setAttribute("aria-pressed", "true");
  });
  return button;
}

function track(projectId, row, detail, grid) {
  const line = el("div", "am-track");
  line.dataset.layer = row.layer;
  const lane = el("div", "am-lane");
  lane.dataset.empty = String(!row.blocks.length);
  if (!row.blocks.length) lane.append(el("span", "am-lane-empty", "пусто"));
  for (const item of row.blocks) lane.append(block(projectId, item, detail, grid));
  line.append(el("span", "am-track-label", row.label), lane);
  return line;
}

function hintText(engine, exists, model, error) {
  if (exists === false) return "Схема появится после чернового монтажа.";
  if (engine === "missing") return "Схема появится, когда будет установлен монтажный стол.";
  if (error) return "Схему прочитать не удалось — причина выше.";
  return model ? "Схему прочитать не удалось." : "Читаем монтаж…";
}

function heading(lagging, error) {
  const head = el("div", "v2-card-head");
  head.append(el("h2", "v2-card-title", "Схема монтажа"));
  if (lagging) {
    const mark = el("span", "am-layers-mark", error ? "не обновилась" : "обновляется…");
    mark.dataset.hook = "am-layers-mark";
    mark.dataset.tone = error ? "error" : "wait";
    head.append(mark);
  }
  return head;
}

export function renderLayers({ project, model, engine, exists, lagging = false, error = false }) {
  const box = el("section", "v2-card am-layers");
  box.dataset.hook = "am-layers";
  const rows = exists !== false && engine === "installed" && model ? layerRows(model, project) : [];
  box.append(heading(lagging && rows.length > 0, Boolean(error)));
  if (!rows.length) {
    box.append(el("p", "v2-section-hint", hintText(engine, exists, model, error)));
    return box;
  }
  const grid = el("div", "am-tracks");
  const detail = el("p", "am-layer-detail");
  detail.setAttribute("aria-live", "polite");
  const picked = rows.flatMap((row) => row.blocks).find((item) => `${project.id}:${item.id}` === chosen);
  detail.textContent = picked ? picked.detail : HINT;
  for (const row of rows) grid.append(track(project.id, row, detail, grid));
  const ruler = el("div", "am-ruler");
  ruler.append(el("span", "", fmtTime(0)), el("span", "", fmtTime(modelDuration(model))));
  box.append(grid, ruler, detail);
  return box;
}

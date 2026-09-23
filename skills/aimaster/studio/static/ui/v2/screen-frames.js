// Экран «Кадры» (спецификация §3.2, хэндофф 2026-09-23) — один экран
// поверх двух серверных стадий, `image_plan` и `image_results`:
// переключатель способа генерации, общий промпт при «одним заходом»,
// полка референсов, сцены карточками и низ с одной главной кнопкой.
// Заголовок экрана рисует оболочка.

import { requestAgentPrompt } from "../chat-prompt-dialog.js";
import { editPrompt } from "./chat-prompts.js";
import { placeScreenTools } from "./board-bits.js";
import { chatButton, el } from "./dom.js";
import { renderFooter } from "./footer.js";
import { renderShelf } from "./reference-shelf.js";
import { renderSceneRow, scenesInOrder } from "./scene-row.js";
import { changeGenMode } from "./screen-prompts.js";
import { promptGroups } from "./variants.js";

const MODES = Object.freeze([
  Object.freeze({ id: "per_scene", label: "Кадр за кадром", hint: "Каждая сцена — свой промпт и свой клип. Можно переделать одну, не трогая остальные." }),
  Object.freeze({ id: "one_shot", label: "Одним заходом", hint: "Один промпт на весь ролик: модель делает его целиком, посценно переделать не получится." }),
]);

/**
 * «Как делаем ролик: [Кадр за кадром | Одним заходом]» — одна строка и
 * короткая подсказка под ней. Смена режима переписывает позиции и
 * промпты, поэтому идёт через чат, а не кнопкой (спецификация §2.2).
 */
function genModeRow(project, revision) {
  if (project?.type === "photo") return null;
  const selected = project?.gen_mode === "one_shot" ? "one_shot" : "per_scene";
  const section = el("section", "v2-mode");
  section.dataset.hook = "v2-mode";
  const row = el("div", "v2-mode-row");
  row.append(el("span", "v2-mode-label", "Как делаем ролик"));
  const group = el("div", "v2-seg");
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", "Как делаем ролик");
  for (const mode of MODES) {
    const button = el("button", "v2-seg-option", mode.label);
    button.type = "button";
    button.dataset.hook = "v2-mode-option";
    button.dataset.mode = mode.id;
    button.dataset.selected = String(mode.id === selected);
    button.setAttribute("aria-pressed", String(mode.id === selected));
    button.addEventListener("click", () => {
      if (mode.id === selected) return;
      requestAgentPrompt(changeGenMode(project, revision, mode.id), button);
    });
    group.append(button);
  }
  row.append(group);
  section.append(row, el("p", "v2-mode-hint", MODES.find((mode) => mode.id === selected).hint));
  return section;
}

/** Поле общего промпта «одним заходом»: текст последней версии и «v3 из 3». */
function oneShotPrompt(project, revision) {
  const versionId = project?.oneshot?.links?.motion_prompt_version_id;
  const collection = project?.motion_prompts || [];
  const current = collection.find((item) => item?.version_id === versionId);
  const section = el("section", "v2-card v2-oneshot");
  section.dataset.hook = "v2-oneshot";
  const head = el("div", "v2-card-head");
  head.append(el("h2", "v2-card-title", "Промпт на весь ролик"));
  section.append(head);
  if (!current) {
    section.append(el("p", "v2-section-hint", "Промпта пока нет — попросите агента его написать."));
    return section;
  }
  const versions = promptGroups(collection).get(current.prompt_id) || [current];
  const number = versions.findIndex((item) => item.version_id === versionId) + 1;
  head.append(el("span", "v2-card-meta", `v${number || 1} из ${versions.length}`));
  section.append(
    el("p", "v2-oneshot-text", current.text || ""),
    chatButton("Изменить → чат", editPrompt({
      project, revision, promptVersion: current, what: "всего ролика",
    }), "v2-chat-button v2-card-button"),
  );
  return section;
}

/**
 * @param {HTMLElement} root куда рисовать (очищается)
 * @param {{state: object, readOnly?: boolean, screen?: string}} context `state.snapshot` — весь snapshot
 */
export function renderFramesScreen(root, { state, readOnly = false, screen = "frames" } = {}) {
  root.textContent = "";
  const snapshot = state?.snapshot;
  const project = snapshot?.active_project;
  const surface = el("div", "v2-screen v2-screen-frames");
  surface.dataset.hook = "v2-screen-frames";
  if (!project) {
    surface.setAttribute("aria-busy", "true");
    surface.append(el("p", "", "Загружаем кадры…"));
    root.append(surface);
    return;
  }

  const genMode = genModeRow(project, snapshot.revision);
  if (project.gen_mode === "one_shot") surface.append(oneShotPrompt(project, snapshot.revision));

  surface.append(renderShelf(project, snapshot.revision));

  const scenes = scenesInOrder(project);
  const list = el("section", "v2-scenes");
  list.dataset.hook = "v2-scenes";
  const head = el("div", "v2-section-head");
  head.append(
    el("h2", "v2-section-title", "Сцены"),
    el("span", "v2-section-note", scenes.length
      ? `${scenes.length} · нажмите на кадр, чтобы выбрать вариант`
      : "Сцен пока нет — они появятся после раскадровки."),
  );
  list.append(head);
  scenes.forEach((scene, index) => list.append(renderSceneRow(project, snapshot.revision, scene, index + 1)));
  surface.append(list, renderFooter(snapshot, { screen }));
  if (genMode) placeScreenTools(root, surface, genMode);
  root.append(surface);
}

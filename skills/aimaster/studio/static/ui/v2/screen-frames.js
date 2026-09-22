// Экран «Кадры» (спецификация §3.2) — один экран поверх двух серверных
// стадий, `image_plan` и `image_results`: переключатель способа генерации,
// общий промпт при «одним заходом», полка референсов, сцены списком и
// низ с одной главной кнопкой.

import { renderGenMode } from "../gen-mode.js";
import { editPrompt } from "./chat-prompts.js";
import { chatButton, el } from "./dom.js";
import { renderFooter } from "./footer.js";
import { renderShelf } from "./reference-shelf.js";
import { renderSceneRow, scenesInOrder } from "./scene-row.js";
import { promptGroups } from "./variants.js";

/** Поле общего промпта «одним заходом»: текст последней версии и «v3 из 3». */
function oneShotPrompt(project, revision) {
  const versionId = project?.oneshot?.links?.motion_prompt_version_id;
  const collection = project?.motion_prompts || [];
  const current = collection.find((item) => item?.version_id === versionId);
  const section = el("section", "v2-oneshot");
  section.dataset.hook = "v2-oneshot";
  section.append(el("h2", "v2-section-title", "Промпт на весь ролик"));
  if (!current) {
    section.append(el("p", "v2-section-hint", "Промпта пока нет — попросите агента его написать."));
    return section;
  }
  const versions = promptGroups(collection).get(current.prompt_id) || [current];
  const number = versions.findIndex((item) => item.version_id === versionId) + 1;
  section.append(
    el("p", "v2-oneshot-meta", `v${number || 1} из ${versions.length}`),
    el("p", "v2-oneshot-text", current.text || ""),
    chatButton("Изменить промпт", editPrompt({
      project, revision, promptVersion: current, what: "всего ролика",
    })),
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

  const genMode = renderGenMode(snapshot, { readOnly });
  if (genMode) surface.append(genMode);
  if (project.gen_mode === "one_shot") surface.append(oneShotPrompt(project, snapshot.revision));

  surface.append(renderShelf(project, snapshot.revision));

  const scenes = scenesInOrder(project);
  const list = el("section", "v2-scenes");
  list.dataset.hook = "v2-scenes";
  list.append(el("h2", "v2-section-title", `Сцены · ${scenes.length}`));
  if (!scenes.length) {
    list.append(el("p", "v2-section-hint", "Сцен пока нет — они появятся после раскадровки."));
  }
  scenes.forEach((scene, index) => list.append(renderSceneRow(project, snapshot.revision, scene, index + 1)));
  surface.append(list, renderFooter(snapshot, { screen }));
  root.append(surface);
}

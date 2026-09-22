// Экран «Видео» (спецификация §3.3): те же строки сцен, что и на
// «Кадрах», но справа три зоны про клип. При «одним заходом» сцена одна
// на весь ролик, поэтому вместо списка — одна плитка финального клипа.

import { el, openViewer, thumb } from "./dom.js";
import { renderFooter } from "./footer.js";
import { renderSceneRow, scenesInOrder } from "./scene-row.js";
import { clipStatus } from "./video-model.js";

/** Плитка одного клипа на весь ролик — режим «одним заходом». */
function oneShotClip(project) {
  const status = clipStatus(project, { scene_id: "oneshot" });
  const box = el("section", "v2-oneclip");
  box.dataset.hook = "v2-oneclip";
  box.append(el("h2", "v2-section-title", "Клип всего ролика"));
  const button = el("button", "v2-big-slot");
  button.type = "button";
  button.dataset.hook = "v2-oneclip-slot";
  button.setAttribute("aria-label", `Клип всего ролика: ${status.text}`);
  button.append(thumb(status.selected?.asset_url || null, "Клип всего ролика"));
  button.addEventListener("click", () => openViewer(
    { kind: "scene", id: "oneshot" }, { tab: "video", slot: "video", trigger: button },
  ));
  box.append(button, el("p", "v2-section-hint", status.total === 0
    ? "Клипов пока нет — попросите агента сгенерировать вариант."
    : status.text));
  return box;
}

/**
 * @param {HTMLElement} root куда рисовать (очищается)
 * @param {{state: object, screen?: string}} context `state.snapshot` — весь snapshot
 */
export function renderVideoScreen(root, { state, screen = "video" } = {}) {
  root.textContent = "";
  const snapshot = state?.snapshot;
  const project = snapshot?.active_project;
  const surface = el("div", "v2-screen v2-screen-video");
  surface.dataset.hook = "v2-screen-video";
  if (!project) {
    surface.setAttribute("aria-busy", "true");
    surface.append(el("p", "", "Загружаем видео…"));
    root.append(surface);
    return;
  }

  if (project.gen_mode === "one_shot") {
    surface.append(oneShotClip(project));
  }

  const scenes = scenesInOrder(project);
  const list = el("section", "v2-scenes");
  list.dataset.hook = "v2-scenes";
  list.append(
    el("h2", "v2-section-title", `Сцены · ${scenes.length}`),
    el("p", "v2-section-hint", project.gen_mode === "one_shot"
      ? "Ролик делается целиком, поэтому у сцен свои клипы могут и не появиться."
      : "У каждой сцены свой клип. Нажмите на клип, чтобы посмотреть варианты и выбрать."),
  );
  if (!scenes.length) list.append(el("p", "v2-section-hint", "Сцен пока нет — они появятся после раскадровки."));
  scenes.forEach((scene, index) => list.append(
    renderSceneRow(project, snapshot.revision, scene, index + 1, { mode: "video" }),
  ));

  surface.append(list, renderFooter(snapshot, { screen }));
  root.append(surface);
}

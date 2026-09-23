// Экран «Видео» (спецификация §3.3, хэндофф 2026-09-23): те же карточки
// сцен, что и на «Кадрах», но справа превью клипа и «Продолжение». При
// «одним заходом» сцена одна на весь ролик, поэтому сверху — одна
// крупная плитка клипа всего ролика. Заголовок экрана рисует оболочка.

import { playMark, statusLine } from "./board-bits.js";
import { el, openViewer } from "./dom.js";
import { renderFooter } from "./footer.js";
import { renderSceneRow, scenesInOrder } from "./scene-row.js";
import { clipStatus } from "./video-model.js";
import { renderPreview } from "./preview.js";

/** Плитка одного клипа на весь ролик — режим «одним заходом». */
function oneShotClip(project) {
  const status = clipStatus(project, { scene_id: "oneshot" });
  const box = el("section", "v2-oneclip");
  box.dataset.hook = "v2-oneclip";
  const head = el("div", "v2-section-head");
  head.append(el("h2", "v2-section-title", "Клип всего ролика"));
  box.append(head);
  const button = el("button", "v2-big-preview");
  button.type = "button";
  button.dataset.hook = "v2-oneclip-slot";
  button.setAttribute("aria-label", `Клип всего ролика: ${status.text}`);
  button.append(
    renderPreview(status.selected, { kind: status.selected ? "video" : "none", label: "Клип всего ролика", emptyText: "клипа нет" }),
    ...(status.selected ? [playMark("v2-play v2-play-big")] : []),
    statusLine(status.text, status.tone, "v2-status v2-big-preview-status"),
  );
  button.addEventListener("click", () => openViewer(
    { kind: "scene", id: "oneshot" }, { tab: "video", slot: "video", trigger: button },
  ));
  box.append(button);
  if (status.total === 0) box.append(el("p", "v2-section-hint", "Клипов пока нет — попросите агента сгенерировать вариант."));
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
  if (!scenes.length) list.append(el("p", "v2-section-hint", "Сцен пока нет — они появятся после раскадровки."));
  else if (project.gen_mode === "one_shot") {
    list.append(el("p", "v2-section-hint", "Ролик делается целиком, поэтому своих клипов у сцен может и не быть."));
  }
  scenes.forEach((scene, index) => list.append(
    renderSceneRow(project, snapshot.revision, scene, index + 1, { mode: "video" }),
  ));

  surface.append(list, renderFooter(snapshot, { screen }));
  root.append(surface);
}

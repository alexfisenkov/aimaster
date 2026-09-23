// Правые зоны строки сцены на экране «Видео» (спецификация §3.3,
// хэндофф 2026-09-23): превью клипа 176×99 с «▶» и пилюлей статуса и
// блок «Продолжение». Видеореференс у этого экрана тот же самый, что и
// на «Кадрах», и живёт в `scene-zones.js`.

import { playMark, statusLine } from "./board-bits.js";
import { clock, el, openViewer } from "./dom.js";
import { clipStatus, continuationLine } from "./video-model.js";
import { videoThumb } from "./video-thumb.js";

/**
 * Превью клипа сцены: первый кадр выбранного варианта, «▶» и статус.
 * @param {number} [position] номер сцены для подписи на телефоне
 */
export function clipZone(project, scene, position) {
  const status = clipStatus(project, scene);
  const box = el("div", "v2-clip-zone");
  box.dataset.zone = "clip";
  const button = el("button", "v2-clip");
  button.type = "button";
  button.dataset.hook = "v2-clip-slot";
  button.setAttribute("aria-label", `Клип сцены: ${status.text}`);
  button.append(videoThumb(status.selected?.asset_url || null, "Клип сцены"));
  if (status.selected) button.append(playMark());
  // На телефоне превью во всю ширину карточки, и сцена подписывается прямо
  // на нём: «Сцена 2 · 00:03–00:06».
  const time = `${clock(scene?.start_ms)}–${clock(scene?.end_ms)}`;
  const tag = el("span", "v2-clip-tag v2-phone-only", `${Number.isFinite(position) ? `Сцена ${position}` : "Сцена"} · ${time}`);
  button.append(tag, statusLine(status.text, status.tone, "v2-status v2-clip-status"));
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    openViewer({ kind: "scene", id: scene?.scene_id }, { tab: "video", slot: "video", trigger: button });
  });
  box.append(button);
  return box;
}

/** «Продолжение»: откуда берётся движение этой сцены. */
export function continuationZone(project, scene) {
  const line = continuationLine(project, scene);
  const box = el("div", "v2-continuation");
  box.dataset.zone = "continuation";
  box.dataset.warn = String(line.warn);
  box.append(
    el("span", "v2-continuation-title", "Продолжение"),
    el("span", "v2-continuation-text", line.detail),
  );
  if (line.warn) box.append(el("span", "v2-continuation-warn", "сцену меняли — проверьте связь"));
  return box;
}

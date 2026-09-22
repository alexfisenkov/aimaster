// Правые зоны строки сцены на экране «Видео» (спецификация §3.3):
// «Клип» и «Продолжение». Видеореференс у этого экрана тот же самый,
// что и на «Кадрах», и живёт в `scene-zones.js`.

import { el, openViewer } from "./dom.js";
import { clipStatus, continuationLine } from "./video-model.js";
import { videoThumb } from "./video-thumb.js";

function zone(title) {
  const row = el("div", "v2-zone");
  row.append(el("span", "v2-zone-title", title));
  const items = el("div", "v2-zone-items");
  row.append(items);
  return { row, items };
}

/** «Клип»: миниатюра выбранного варианта, их число и статус. */
export function clipZone(project, scene) {
  const { row, items } = zone("Клип");
  const status = clipStatus(project, scene);
  const button = el("button", "v2-slot v2-slot-clip");
  button.type = "button";
  button.dataset.hook = "v2-clip-slot";
  button.setAttribute("aria-label", `Клип сцены: ${status.text}`);
  button.append(videoThumb(status.selected?.asset_url || null, "Клип сцены"));
  if (status.total > 1) button.append(el("span", "v2-slot-label", `${status.total} вар.`));
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    openViewer({ kind: "scene", id: scene?.scene_id }, { tab: "video", slot: "video", trigger: button });
  });
  items.append(button, el("span", "v2-zone-caption", status.text));
  return row;
}

/** «Продолжение»: откуда берётся движение этой сцены. */
export function continuationZone(project, scene) {
  const { row, items } = zone("Продолжение");
  const line = continuationLine(project, scene);
  items.append(el("span", "v2-zone-caption", line.text));
  if (line.warn) items.append(el("span", "v2-zone-warn", "сцену меняли — проверьте связь"));
  return row;
}

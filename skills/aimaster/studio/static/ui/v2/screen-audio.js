// Экран «Звук» (спецификация §3.4, хэндофф 2026-09-23): четыре карточки
// слоёв — голос, музыка, эффекты, атмосфера — с полосой-волной сверху.
// На телефоне те же кнопки становятся строками списка с мини-волной и
// «›». Клик открывает просмотрщик на этом слое; всё остальное про звук
// делается в чате. Заголовок экрана рисует оболочка.

import { audioTiles } from "./audio-model.js";
import { statusLine, waveform } from "./board-bits.js";
import { el, openViewer } from "./dom.js";
import { renderFooter } from "./footer.js";

function layerTile(tile) {
  const button = el("button", "v2-layer");
  button.type = "button";
  button.dataset.hook = "v2-layer";
  button.dataset.layer = tile.layer;
  button.dataset.filled = String(tile.total > 0);
  button.setAttribute("aria-label", `${tile.name}: ${tile.status}`);
  const head = el("span", "v2-layer-head");
  head.append(el("b", "v2-layer-name", tile.name));
  if (tile.total > 0) head.append(el("span", "v2-layer-count", `${tile.total} вар.`));
  const body = el("span", "v2-layer-body");
  body.append(
    head,
    el("span", "v2-layer-hint", tile.hint),
    statusLine(tile.status, tile.tone, "v2-status v2-layer-status"),
  );
  const arrow = el("span", "v2-layer-arrow v2-phone-only", "›");
  arrow.setAttribute("aria-hidden", "true");
  // Цвет волны: выбранный вариант — зелёный, варианты без выбора —
  // тёмный, вариантов нет — светло-серый.
  const waveTone = tile.selected ? "ok" : tile.total > 0 ? "ink" : "none";
  button.append(waveform(tile.wave, waveTone, "v2-wave v2-layer-wave"), body, arrow);
  button.addEventListener("click", () => openViewer(
    { kind: "layer", id: tile.layer }, { tab: "frames", trigger: button },
  ));
  return button;
}

/**
 * @param {HTMLElement} root куда рисовать (очищается)
 * @param {{state: object, screen?: string}} context `state.snapshot` — весь snapshot
 */
export function renderAudioScreen(root, { state, screen = "audio" } = {}) {
  root.textContent = "";
  const snapshot = state?.snapshot;
  const project = snapshot?.active_project;
  const surface = el("div", "v2-screen v2-screen-audio");
  surface.dataset.hook = "v2-screen-audio";
  if (!project) {
    surface.setAttribute("aria-busy", "true");
    surface.append(el("p", "", "Загружаем звук…"));
    root.append(surface);
    return;
  }
  const tiles = audioTiles(project);
  const grid = el("div", "v2-layers");
  grid.dataset.hook = "v2-layers";
  for (const tile of tiles) grid.append(layerTile(tile));
  surface.append(grid);
  if (tiles.every((tile) => tile.total === 0)) {
    surface.append(el("p", "v2-section-hint",
      "Звука пока нет. Если он не нужен — шаг можно пропустить кнопкой внизу; иначе попросите агента сделать слои."));
  }
  surface.append(renderFooter(snapshot, { screen }));
  root.append(surface);
}

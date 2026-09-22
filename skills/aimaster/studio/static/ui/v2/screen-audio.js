// Экран «Звук» (спецификация §3.4): четыре плитки слоёв — голос,
// музыка, эффекты, атмосфера. Клик по плитке открывает просмотрщик на
// этом слое; всё остальное про звук делается в чате.

import { audioTiles } from "./audio-model.js";
import { el, openViewer } from "./dom.js";
import { renderFooter } from "./footer.js";

function layerTile(tile) {
  const button = el("button", "v2-layer");
  button.type = "button";
  button.dataset.hook = "v2-layer";
  button.dataset.layer = tile.layer;
  button.setAttribute("aria-label", `${tile.name}: ${tile.status}`);
  const head = el("span", "v2-layer-head");
  head.append(el("b", "", tile.name));
  if (tile.total > 0) head.append(el("span", "v2-layer-count", `${tile.total} вар.`));
  button.append(
    head,
    el("span", "v2-layer-hint", tile.hint),
    el("span", "v2-layer-status", tile.status),
  );
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
  surface.append(
    el("h2", "v2-section-title", "Звук"),
    el("p", "v2-section-hint", "Четыре слоя принимаются по отдельности. Нажмите на слой, чтобы послушать варианты."),
  );
  const grid = el("div", "v2-layers");
  grid.dataset.hook = "v2-layers";
  for (const tile of tiles) grid.append(layerTile(tile));
  surface.append(grid);
  if (tiles.every((tile) => tile.total === 0)) {
    surface.append(el("p", "v2-section-hint", "Звука пока нет — попросите агента сделать слои."));
  }
  surface.append(renderFooter(snapshot, { screen }));
  root.append(surface);
}

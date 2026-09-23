// Мелкие детали экранов доски (хэндофф 2026-09-23): точка статуса,
// бейдж, пилюля «▶», волна звука. Только разметка и классы — цвета и
// размеры живут в `styles/v2/board.css`, inline-стилей CSP не пускает.

import { el } from "./dom.js";

const SVG_NS = "http://www.w3.org/2000/svg";

/** Точка 6px цветом статуса. */
export function dot(tone) {
  const node = el("span", "v2-dot");
  node.dataset.tone = tone || "none";
  node.setAttribute("aria-hidden", "true");
  return node;
}

/** «● выбран 2 из 3» — точка и слова одной строкой. */
export function statusLine(text, tone, className = "v2-status") {
  const line = el("span", className);
  line.dataset.tone = tone || "none";
  line.append(dot(tone), el("span", "v2-status-text", text));
  return line;
}

/** Пилюля-бейдж «кадры готовы» / «нужно выбрать». */
export function badge(text, tone) {
  const node = el("span", "v2-badge", text);
  node.dataset.tone = tone || "none";
  return node;
}

/** Белый круг «▶» поверх превью. */
export function playMark(className = "v2-play") {
  const node = el("span", className, "▶");
  node.setAttribute("aria-hidden", "true");
  return node;
}

/**
 * Волна звука вставленным `<svg>`: столбики разной высоты, цвет — по
 * `currentColor` из CSS (`data-tone` у обёртки). Картинок нет.
 * @param {number[]} heights доли высоты 0..1
 * @param {string} tone ok|warn|none
 * @param {string} [className]
 */
export function waveform(heights, tone, className = "v2-wave") {
  const box = el("span", className);
  box.dataset.tone = tone || "none";
  box.setAttribute("aria-hidden", "true");
  const list = Array.isArray(heights) && heights.length ? heights : [0.1];
  const step = 10;
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${list.length * step} 100`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("focusable", "false");
  list.forEach((value, index) => {
    const height = Math.max(4, Math.min(100, Math.round(value * 100)));
    const bar = document.createElementNS(SVG_NS, "rect");
    bar.setAttribute("x", String(index * step + 2));
    bar.setAttribute("y", String((100 - height) / 2));
    bar.setAttribute("width", String(step - 4));
    bar.setAttribute("height", String(height));
    bar.setAttribute("rx", "2");
    svg.append(bar);
  });
  box.append(svg);
  return box;
}

/**
 * Управление экрана — «Как делаем ролик», «···» — живёт справа от
 * заголовка, в пустом месте `v2-screen-aside`, которое оставляет оболочка
 * (`shell.js`, `screenHead`). Нет такого места (экран нарисован отдельно,
 * в тесте) — ставим тем же рядом над контентом экрана.
 * @param {HTMLElement} root область экрана, которую дала оболочка
 * @param {HTMLElement} surface корень экрана
 * @param {HTMLElement} node что поставить
 */
export function placeScreenTools(root, surface, node) {
  const aside = root?.parentElement?.querySelector?.('[data-hook="v2-screen-heading"] [data-hook="v2-screen-aside"]');
  if (aside) {
    aside.textContent = "";
    aside.append(node);
    return;
  }
  const tools = el("div", "v2-screen-tools");
  tools.append(node);
  surface.prepend(tools);
}

// Путь из пяти шагов (спецификация §3): полоса с состоянием
// «✓ одобрен / вы здесь / дальше» и одна строка подсказки под ней.
// Шаги — не кнопки действий: клик по пройденному открывает его на
// просмотр, будущие недоступны.

import { SCREEN_HINTS, pathState } from "./screen-map.js";
import { el } from "./dom.js";

/** Попросить оболочку показать другой экран. */
export function requestScreen(screen, trigger = null) {
  document.dispatchEvent(new CustomEvent("studio:screen-viewed", {
    bubbles: true,
    detail: { screen, trigger },
  }));
}

/**
 * @param {object} project `snapshot.active_project`
 * @param {{current: string}} options какой экран открыт сейчас
 * @returns {HTMLElement} `<nav>` с полосой пути и подсказкой
 */
export function renderPath(project, { current } = {}) {
  const steps = pathState(project);
  const openIndex = steps.findIndex((step) => step.id === current);
  const nav = el("nav", "v2-path");
  nav.dataset.hook = "v2-path";
  nav.setAttribute("aria-label", "Путь проекта");
  const strip = el("ol", "v2-path-strip");

  steps.forEach((step, index) => {
    const item = el("li", "v2-path-step");
    item.dataset.state = step.state;
    item.dataset.screen = step.id;
    const reachable = step.state !== "next";
    const label = `${step.state === "done" ? "✓ " : ""}${step.label}`;
    let control;
    if (reachable) {
      control = el("button", "v2-path-button", label);
      control.type = "button";
      control.dataset.hook = "v2-path-step";
      control.dataset.screen = step.id;
      control.addEventListener("click", () => requestScreen(step.id, control));
    } else {
      control = el("span", "v2-path-button", label);
      control.setAttribute("aria-disabled", "true");
    }
    if (index === openIndex) {
      control.setAttribute("aria-current", "step");
      item.dataset.open = "true";
    }
    if (step.hint) control.append(el("small", "v2-path-hint", step.hint));
    item.append(control);
    strip.append(item);
  });

  const hint = el("p", "v2-path-explain", SCREEN_HINTS[current] || "");
  nav.append(strip, hint);
  return nav;
}

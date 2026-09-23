// Степпер пути из пяти шагов (хэндофф 2026-09-23, «Степпер»): кружок с
// номером или ✓, подпись и подсказка «одобрен / вы здесь / дальше»,
// между шагами линия. Шаги — не кнопки действий: клик по пройденному
// открывает его на просмотр, будущие закрыты и объясняют это в `title`.
// На телефоне та же разметка — пять равных кнопок без линий (CSS).

import { SCREEN_HINTS, pathState } from "./screen-map.js";
import { el } from "./dom.js";

const LOCKED_TITLE = "Откроется, когда одобрите предыдущий шаг";

/** Попросить оболочку показать другой экран. */
export function requestScreen(screen, trigger = null) {
  document.dispatchEvent(new CustomEvent("studio:screen-viewed", {
    bubbles: true,
    detail: { screen, trigger },
  }));
}

function stepMark(step, index) {
  const mark = el("span", "v2-path-mark", step.state === "done" ? "✓" : String(index + 1));
  mark.setAttribute("aria-hidden", "true");
  return mark;
}

/**
 * @param {object} project `snapshot.active_project`
 * @param {{current: string}} options какой экран открыт сейчас
 * @returns {HTMLElement} `<nav>` со степпером
 */
export function renderPath(project, { current } = {}) {
  const steps = pathState(project);
  const nav = el("nav", "v2-path");
  nav.dataset.hook = "v2-path";
  nav.setAttribute("aria-label", "Путь проекта");
  const strip = el("ol", "v2-path-strip");

  steps.forEach((step, index) => {
    const item = el("li", "v2-path-step");
    item.dataset.state = step.state;
    item.dataset.screen = step.id;
    const reachable = step.state !== "next";
    let control;
    if (reachable) {
      control = el("button", "v2-path-button");
      control.type = "button";
      control.dataset.hook = "v2-path-step";
      control.dataset.screen = step.id;
      control.title = SCREEN_HINTS[step.id] || "";
      control.addEventListener("click", () => requestScreen(step.id, control));
    } else {
      control = el("span", "v2-path-button");
      control.setAttribute("aria-disabled", "true");
      control.title = LOCKED_TITLE;
    }
    const text = el("span", "v2-path-text");
    text.append(el("span", "v2-path-label", step.label));
    if (step.hint) text.append(el("small", "v2-path-hint", step.hint));
    control.append(stepMark(step, index), text);
    if (step.id === current) {
      control.setAttribute("aria-current", "step");
      item.dataset.open = "true";
    }
    item.append(control);
    if (index < steps.length - 1) {
      const line = el("span", "v2-path-line");
      line.setAttribute("aria-hidden", "true");
      item.append(line);
    }
    strip.append(item);
  });

  nav.append(strip);
  return nav;
}

// Оболочка v2 (спецификация §3): шапка, путь, область экрана.
// Роутер экранов: все пять экранов теперь свои. Рендереры v1
// (`step-*.js`) отсюда больше не вызываются, но и не удалены — они живут
// в старой оболочке `static/app-v1.js` до приёмки владельцем. Какой
// экран открыт, хранится здесь же: это местная вещь просмотра, сервер о
// ней ничего не знает.

import { requestAgentPrompt } from "../chat-prompt-dialog.js";
import { projectRef } from "./chat-prompts.js";
import { el, restoreCardFocus, cardFocusNote } from "./dom.js";
import { renderPath } from "./path-nav.js";
import { renderAssemblyScreen } from "./screen-assembly.js";
import { renderAudioScreen } from "./screen-audio.js";
import { renderFramesScreen } from "./screen-frames.js";
import { renderScenarioScreen } from "./screen-scenario.js";
import { renderVideoScreen } from "./screen-video.js";
import { SCREEN_LABELS, screenForStage, screensFor } from "./screen-map.js";

const TYPE_WORDS = Object.freeze({ video: "видео", photo: "фото", mixed: "видео и фото" });
const MODE_WORDS = Object.freeze({ per_scene: "кадр за кадром", one_shot: "одним заходом" });

const SCREEN_RENDERERS = Object.freeze({
  scenario: renderScenarioScreen,
  frames: renderFramesScreen,
  video: renderVideoScreen,
  audio: renderAudioScreen,
  assembly: renderAssemblyScreen,
});

let viewedScreen = null;

/** Показать другой экран (`studio:screen-viewed` из `path-nav.js`). */
export function setViewedScreen(screen) {
  viewedScreen = typeof screen === "string" ? screen : null;
}

/** Какой экран открыт: выбранный человеком, иначе — экран текущей стадии. */
export function currentScreen(project) {
  const available = screensFor(project?.type);
  const stageScreen = screenForStage(project?.stage);
  return available.includes(viewedScreen) ? viewedScreen : stageScreen || available[0];
}

function topbar(project, revision) {
  const bar = el("div", "v2-topbar");
  const duration = Number.isFinite(project?.scenes?.at(-1)?.end_ms)
    ? ` · ${Math.round(project.scenes.at(-1).end_ms / 1000)} с`
    : "";
  const title = el("b", "v2-topbar-title", project?.title || project?.id || "Проект");
  const meta = [TYPE_WORDS[project?.type] || "", MODE_WORDS[project?.gen_mode] || ""].filter(Boolean).join(" · ");
  title.append(el("span", "v2-topbar-meta", ` · ${meta}${duration}`));
  const agent = el("button", "v2-chat-button v2-agent", "💬 Агент");
  agent.type = "button";
  agent.dataset.hook = "v2-agent";
  agent.addEventListener("click", () => requestAgentPrompt({
    title: "Продолжить проект в чате",
    prompt: `Открой ${projectRef(project, revision)}. Покажи, на каком шаге проект и что осталось решить, `
      + `и предложи ближайший допустимый шаг. Ничего не генерируй и не меняй без моего подтверждения.`,
  }, agent));
  bar.append(title, agent);
  return bar;
}

/**
 * @param {HTMLElement} root корень `.app-shell`
 * @param {object} state состояние стора (`ui/state.js`)
 */
export function renderShellV2(root, state) {
  if (!root) throw new TypeError("root is required");
  const topbarContent = root.querySelector('[data-hook="topbar-content"]');
  const main = root.querySelector("#main") || root.querySelector('[data-hook="main"]');
  if (!main) return;
  const snapshot = state?.snapshot;
  const project = snapshot?.active_project;
  if (topbarContent) {
    topbarContent.textContent = "";
    if (project) topbarContent.append(topbar(project, snapshot.revision));
  }
  // Главная кнопка подвала гасится синхронно, ещё до отправки, и фокус
  // улетает на `<body>`. Листок от `noteCardFocusPending` забирается до
  // сноса разметки и возвращает фокус той же кнопке после перерисовки —
  // тот же приём, что у v1 (`ui/shell.js`, `repaintZonePreservingFocus`).
  const focusNote = cardFocusNote();
  main.textContent = "";
  if (state?.error) {
    main.append(el("p", "v2-error", "Не удалось загрузить проект. Обновите страницу."));
    return;
  }
  if (!project) {
    main.setAttribute("aria-busy", "true");
    main.append(el("p", "v2-loading", "Загружаем проект…"));
    return;
  }
  main.removeAttribute("aria-busy");
  const screen = currentScreen(project);
  main.append(renderPath(project, { current: screen }));
  const area = el("div", "v2-area");
  area.dataset.screen = screen;
  area.setAttribute("aria-label", SCREEN_LABELS[screen] || "");
  main.append(area);
  const render = SCREEN_RENDERERS[screen];
  if (render) render(area, { state, readOnly: false, screen });
  else area.append(el("p", "v2-loading", "Этот экран ещё не готов."));
  restoreCardFocus(main, focusNote);
}

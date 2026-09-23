// Оболочка v2 (спецификация §3, редизайн 2026-09-23): липкая шапка с
// названием, статус-пилюлей, «💬 Агент» и степпером пути; заголовок
// экрана (kicker, H1, подсказка — экраны свои заголовки больше не
// рисуют); область экрана; липкий подвал. Подвал рисует экран
// (`renderFooter`), а оболочка выносит его из области в полосу внизу
// страницы, чтобы он шёл на всю ширину.
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
import {
  SCREEN_LABELS, projectStatus, screenForStage, screenHeading, screensFor,
} from "./screen-map.js";

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

function scenesWord(count) {
  const tail = count % 100;
  const last = count % 10;
  if (tail >= 11 && tail <= 14) return `${count} сцен`;
  if (last === 1) return `${count} сцена`;
  if (last >= 2 && last <= 4) return `${count} сцены`;
  return `${count} сцен`;
}

/** «видео · кадр за кадром · 30 с · 6 сцен» — строка над названием. */
export function metaLine(project) {
  const scenes = Array.isArray(project?.scenes) ? project.scenes : [];
  const endMs = scenes.at(-1)?.end_ms;
  return [
    TYPE_WORDS[project?.type] || "",
    MODE_WORDS[project?.gen_mode] || "",
    Number.isFinite(endMs) ? `${Math.round(endMs / 1000)} с` : "",
    scenes.length ? scenesWord(scenes.length) : "",
  ].filter(Boolean).join(" · ");
}

function statusPill(snapshot) {
  const status = projectStatus(snapshot);
  const pill = el("span", "v2-status-pill");
  pill.dataset.hook = "v2-status";
  if (!status) {
    pill.hidden = true;
    return pill;
  }
  pill.dataset.tone = status.tone;
  pill.textContent = status.text;
  return pill;
}

function agentButton(project, revision) {
  const agent = el("button", "v2-agent");
  agent.type = "button";
  agent.dataset.hook = "v2-agent";
  const icon = el("span", "v2-agent-icon", "💬");
  icon.setAttribute("aria-hidden", "true");
  agent.append(icon, el("span", "v2-agent-word", "Агент"));
  agent.addEventListener("click", () => requestAgentPrompt({
    title: "Продолжить проект в чате",
    prompt: `Открой ${projectRef(project, revision)}. Покажи, на каком шаге проект и что осталось решить, `
      + `и предложи ближайший допустимый шаг. Ничего не генерируй и не меняй без моего подтверждения.`,
  }, agent));
  return agent;
}

function topbar(snapshot) {
  const project = snapshot.active_project;
  const bar = el("div", "v2-topbar");
  const identity = el("div", "v2-topbar-id");
  const meta = metaLine(project);
  if (meta) identity.append(el("p", "v2-topbar-meta", meta));
  identity.append(el("p", "v2-topbar-title", project?.title || project?.id || "Проект"));
  bar.append(identity, statusPill(snapshot), agentButton(project, snapshot.revision));
  return bar;
}

/** Заголовок экрана: «Шаг 2 из 5 · одобрен», H1, подсказка; справа —
 * пустое место `v2-screen-aside` для управления экрана (режим «Как
 * делаем ролик», «···»). */
function screenHead(project, screen) {
  const { kicker, title, hint } = screenHeading(project, screen);
  const head = el("div", "v2-screen-heading");
  head.dataset.hook = "v2-screen-heading";
  const text = el("div", "v2-screen-heading-text");
  if (kicker) text.append(el("p", "v2-screen-kicker", kicker));
  const h1 = el("h1", "v2-screen-title", title);
  h1.tabIndex = -1;
  text.append(h1);
  if (hint) text.append(el("p", "v2-screen-hint", hint));
  const aside = el("div", "v2-screen-aside");
  aside.dataset.hook = "v2-screen-aside";
  head.append(text, aside);
  return head;
}

/** Что в шапке держало фокус — чтобы вернуть его после перерисовки. */
function topbarFocusKey(container) {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || !container?.contains(active)) return null;
  return { hook: active.dataset.hook || "", screen: active.dataset.screen || "" };
}

function restoreTopbarFocus(container, key) {
  if (!key?.hook) return;
  const selector = key.screen
    ? `[data-hook="${CSS.escape(key.hook)}"][data-screen="${CSS.escape(key.screen)}"]`
    : `[data-hook="${CSS.escape(key.hook)}"]`;
  container.querySelector(selector)?.focus();
}

/**
 * Экран выбора проекта: список слева уже нарисован (`ui/rail.js`), здесь
 * — объяснение и кнопка, открывающая панель на узком экране.
 */
function renderPicker(state) {
  const empty = state?.status === "empty";
  const box = el("section", "v2-screen v2-screen-picker");
  box.dataset.hook = "v2-picker";
  box.append(el("h1", "v2-screen-title", empty ? "Проектов пока нет" : "Выберите проект"));
  box.append(el("p", "v2-screen-hint", empty
    ? "Заведите проект в чате — он появится здесь сам."
    : `Проектов в мастерской: ${state?.projects?.length ?? 0}. Откройте любой из списка слева.`));
  if (!empty) {
    const show = el("button", "v2-chat-button", "Показать список проектов");
    show.type = "button";
    show.dataset.hook = "v2-open-rail";
    show.addEventListener("click", () => document.dispatchEvent(
      new CustomEvent("studio:rail-open", { bubbles: true }),
    ));
    box.append(show);
  }
  return box;
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
  const screen = project ? currentScreen(project) : null;
  if (topbarContent) {
    const focusKey = topbarFocusKey(topbarContent);
    topbarContent.textContent = "";
    if (project) {
      topbarContent.append(topbar(snapshot), renderPath(project, { current: screen }));
      restoreTopbarFocus(topbarContent, focusKey);
    }
  }
  // Главная кнопка подвала гасится синхронно, ещё до отправки, и фокус
  // улетает на `<body>`. Листок от `noteCardFocusPending` забирается до
  // сноса разметки и возвращает фокус той же кнопке после перерисовки —
  // тот же приём, что у v1 (`ui/shell.js`, `repaintZonePreservingFocus`).
  const focusNote = cardFocusNote();
  main.textContent = "";
  const inner = el("div", "v2-main-inner");
  main.append(inner);
  if (state?.error) {
    inner.append(el("p", "v2-error", "Не удалось загрузить проект. Обновите страницу."));
    return;
  }
  if (!project) {
    // «choose»/«empty» — не загрузка, а вопрос к человеку: `/` без
    // `?project=` (`app-controller.loadProjectIndex`). До этой ветки v2
    // показывал здесь «Загружаем проект…» навсегда.
    const picking = state?.status === "choose" || state?.status === "empty";
    if (picking) {
      main.removeAttribute("aria-busy");
      inner.append(renderPicker(state));
      return;
    }
    main.setAttribute("aria-busy", "true");
    inner.append(el("p", "v2-loading", "Загружаем проект…"));
    return;
  }
  main.removeAttribute("aria-busy");
  inner.append(screenHead(project, screen));
  const area = el("div", "v2-area");
  area.dataset.screen = screen;
  area.setAttribute("aria-label", SCREEN_LABELS[screen] || "");
  inner.append(area);
  const render = SCREEN_RENDERERS[screen];
  if (render) render(area, { state, readOnly: false, screen });
  else area.append(el("p", "v2-loading", "Этот экран ещё не готов."));
  // Подвал — на всю ширину и липкий снизу: он живёт вне колонки контента.
  const footer = area.querySelector('[data-hook="v2-footer"]');
  if (footer) main.append(footer);
  restoreCardFocus(main, focusNote);
}

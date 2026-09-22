// Тёмный просмотрщик на весь экран (спецификация §4, вариант C макета
// `scene-viewer-dark.html`). Открывается событием `studio:open-viewer`
// с `detail.version === 2`; слушатель v1 (`ui/viewer.js`) такое событие
// пропускает, поэтому оба живут рядом и не мешают друг другу.
//
// Здесь только оболочка: диалог, ловушка фокуса, клавиши, свайп и сборка
// колонок. Холст и плёнка — `viewer-canvas.js`, промпт — `viewer-prompt.js`,
// зоны — `viewer-zones.js`, кнопки — `decide.js`.

import { renderDecisionHistory } from "../decision-history.js";
import { formatHistoryEntries } from "../history-panel.js";
import { pruneDrafts } from "../card-drafts.js";
import { variantCounts } from "./counts.js";
import { assembleFinal } from "./screen-prompts.js";
import { cardFocusNote, clock, dropCardFocusNote, el, restoreCardFocus } from "./dom.js";
import { decideDraftKeys, isSubmitting, renderDecideRow } from "./decide.js";
import {
  canvasCaption,
  filmstrip,
  promptOfVariant,
  renderCanvas,
  renderSlotSwitch,
  slotOptions,
  soloStrip,
} from "./viewer-canvas.js";
import { promptPlace, promptVersions, renderPromptPanel } from "./viewer-prompt.js";
import { renderViewerZones } from "./viewer-zones.js";

const TABS = Object.freeze({
  scene: [["frames", "Кадры"], ["video", "Видео"], ["history", "История"]],
  reference: [["frames", "Картинка"], ["history", "История"]],
  layer: [["audio", "Звук"], ["history", "История"]],
  assembly: [["video", "Ролик"], ["history", "История"]],
});
const MEDIA_KIND = Object.freeze({ frames: "image", video: "video", audio: "audio" });
const COLLECTION = Object.freeze({ frames: "image_results", video: "video_results", audio: "audio_results" });
const LAYER_TITLES = Object.freeze({ voice: "Голос", music: "Музыка", fx: "Эффекты", atmos: "Атмосфера" });

let getSnapshot = () => null;
let root = null;
let view = null; // {target, tab, slot, shown, promptShown, returnFocus}

function scenesInOrder(project) {
  return [...(project?.scenes || [])].sort((left, right) => (left?.order || 0) - (right?.order || 0));
}

function sceneOf(project, id) {
  return scenesInOrder(project).find((item) => item?.scene_id === id) || null;
}

function headline(project, target) {
  if (target.kind === "reference") {
    const reference = (project?.references || []).find((item) => item?.reference_id === target.id);
    return { title: reference?.label || target.id, time: "" };
  }
  if (target.kind === "layer") return { title: LAYER_TITLES[target.id] || target.id, time: "" };
  if (target.kind === "assembly") return { title: "Финальный ролик", time: "" };
  const scenes = scenesInOrder(project);
  const index = scenes.findIndex((item) => item?.scene_id === target.id);
  const scene = scenes[index] || {};
  const time = Number.isFinite(scene.start_ms) ? `${clock(scene.start_ms)}–${clock(scene.end_ms)}` : "";
  return { title: `Сцена ${index + 1} · ${scene.title || target.id}`, time };
}

function countsTarget(target, tab, slot) {
  if (target.kind === "reference") return { referenceId: target.id };
  if (target.kind === "layer") return { layer: target.id };
  if (tab === "video") return { sceneId: target.id, slot: "video" };
  return { sceneId: target.id, slot };
}

/**
 * Единственный файл вместо ряда вариантов — там, где версий результата в
 * snapshot нет вовсе: собранный ролик (`project.assembly`) и референс,
 * загруженный файлом (`source: "upload"`).
 */
function soloFor(project, target, counts) {
  if (target.kind === "assembly") {
    return soloStrip(project?.assembly?.asset_url, "Финальный ролик", "final");
  }
  if (target.kind === "reference" && !counts.total) {
    const reference = (project?.references || []).find((item) => item?.reference_id === target.id);
    return soloStrip(reference?.asset_url, reference?.label, "own");
  }
  return null;
}

/**
 * Подпись главной кнопки — и `null` там, где прямого решения не бывает.
 * У сборки собственной коллекции результатов на сервере нет
 * (`decision_cards.STAGE_COLLECTIONS`), поэтому финал принимается только
 * кнопкой подвала «Принять ролик», а не отсюда.
 */
function keepLabel(target, tab) {
  if (target.kind === "assembly") return null;
  if (target.kind === "reference") return "Оставить эту картинку";
  if (tab === "audio") return "Оставить этот звук";
  return tab === "video" ? "Оставить этот клип" : "Оставить этот кадр";
}

function tabsFor(target) {
  return TABS[target.kind] || TABS.scene;
}

function historyPane(snapshot, target) {
  const pane = el("div", "v2-viewer-history");
  pane.dataset.hook = "v2-viewer-history";
  const sceneId = target.kind === "scene" ? target.id : null;
  if (!renderDecisionHistory(pane, snapshot, sceneId)) {
    pane.append(el("p", "v2-viewer-empty-line", "Решений по этому месту ещё не было."));
  }
  const entries = formatHistoryEntries(snapshot?.active_project?.history);
  if (entries.length) {
    pane.append(el("h3", "v2-viewer-subtitle", "Что происходило в проекте"));
    const list = el("ul", "v2-viewer-history-list");
    for (const entry of entries) list.append(el("li", "", `${entry.actorLabel}: ${entry.text}`));
    pane.append(list);
  }
  return pane;
}

/** Пока решение в полёте, просмотрщик не двигается: см. `isSubmitting`. */
function busy() {
  return isSubmitting(view?.statusText);
}

function showVariant(index) {
  if (busy()) return;
  const total = view?.strip?.total || 0;
  view.shown = Math.min(Math.max(index, 1), Math.max(total, 1));
  view.statusText = "";
  paint();
}

function pickSlot(slot) {
  if (busy()) return;
  view.slot = slot;
  view.shown = 0;
  view.statusText = "";
  paint();
}

function pickTab(tab) {
  if (busy()) return;
  view.tab = tab;
  view.shown = 0;
  view.promptShown = 0;
  view.statusText = "";
  paint();
}

function leftColumn(snapshot, project) {
  const { target, tab, slot } = view;
  const column = el("div", "v2-viewer-left");
  if (target.kind === "scene" && tab === "frames") {
    const options = slotOptions(project, sceneOf(project, target.id));
    if (options.length) {
      if (!options.some((item) => item.slot === view.slot)) view.slot = options[0].slot;
      column.append(renderSlotSwitch(options, view.slot, pickSlot));
    } else {
      column.append(el("p", "v2-viewer-empty-line", "Кадров у этой сцены нет — она оживает по референсам."));
    }
  }
  const counts = target.kind === "assembly"
    ? { versions: [], total: 0, selected: null }
    : variantCounts(project, countsTarget(target, tab, view.slot));
  const strip = soloFor(project, target, counts) || filmstrip(counts);
  view.strip = strip;
  if (!view.shown) view.shown = strip.selectedIndex || (strip.total ? 1 : 1);
  view.shown = Math.min(Math.max(view.shown, 1), Math.max(strip.total, 1));
  const shown = strip.items[view.shown - 1] || null;

  const place = promptPlace(project, target, { tab, slot: view.slot });
  const prompts = promptVersions(project, place);
  if (!view.promptShown) view.promptShown = prompts.index || 0;
  view.promptShown = Math.min(Math.max(view.promptShown, 1), Math.max(prompts.total, 1));
  const byPrompt = shown ? promptOfVariant(shown.version, prompts.versions) : null;
  const byPromptIndex = byPrompt ? prompts.versions.indexOf(byPrompt) + 1 : 0;

  const chat = {
    sceneId: target.kind === "scene" ? target.id : undefined,
    referenceId: target.kind === "reference" ? target.id : undefined,
    layer: target.kind === "layer" ? target.id : undefined,
    slot: tab === "video" ? "video" : view.slot,
  };
  column.append(renderCanvas({
    strip,
    shownIndex: view.shown,
    mediaKind: MEDIA_KIND[tab] || "image",
    caption: canvasCaption({
      index: view.shown,
      total: strip.total,
      mark: shown?.mark,
      solo: strip.solo === true,
      promptLabel: byPromptIndex ? `v${byPromptIndex}` : "",
    }),
    onShow: showVariant,
  }));
  const final = target.kind === "assembly";
  // Черновик отказа принадлежит варианту, а не показу: пока вариант есть
  // в плёнке, его текст переживает и перелистывание, и перерисовку.
  view.draftKeys = strip.items.flatMap((item) => decideDraftKeys(project.id, item.version));
  column.append(renderDecideRow({
    ...chat,
    project,
    revision: snapshot.revision,
    allowedActions: snapshot?.view_stage?.allowed_actions,
    currentStage: snapshot?.view_stage?.current_stage,
    collection: COLLECTION[tab],
    version: shown?.version || null,
    mark: shown?.mark,
    keepLabel: keepLabel(target, tab),
    statusText: view.statusText,
    onStatus: (text) => { view.statusText = text; },
    chatMenu: !final,
    secondary: final
      ? {
        label: strip.total ? "Пересобрать → чат" : "Собрать → чат",
        request: assembleFinal(project, snapshot.revision, { ready: strip.total > 0 }),
      }
      : null,
    promptVersion: prompts.versions[view.promptShown - 1] || null,
    editWhat: target.kind === "reference" ? `референса «${target.id}»` : undefined,
  }));
  return { column, prompts, chat };
}

function rightColumn(snapshot, project, prompts, chat) {
  const column = el("aside", "v2-viewer-right");
  // У сборки промпта своего нет: её собирает агент из готовых клипов.
  // Вместо пустой листалки показываем, из чего она собрана.
  if (view.target.kind === "assembly" && !prompts.total) {
    const about = el("section", "v2-viewer-prompt");
    about.append(el("h3", "v2-viewer-subtitle", "Что собрано"));
    about.append(el("p", "v2-viewer-prompt-text",
      project?.assembly?.summary || "Описания сборки агент не оставил."));
    column.append(about);
    return column;
  }
  column.append(renderPromptPanel({
    project,
    revision: snapshot.revision,
    state: prompts,
    shownIndex: view.promptShown,
    title: view.tab === "video" ? "Промпт движения" : view.tab === "audio" ? "Промпт звука" : "Промпт кадра",
    chat,
    editWhat: view.target.kind === "reference" ? `референса «${view.target.id}»` : undefined,
    onShow: (index) => { if (!busy()) { view.promptShown = index; paint(); } },
  }));
  const zones = view.target.kind === "scene"
    ? renderViewerZones(project, snapshot.revision, sceneOf(project, view.target.id))
    : null;
  if (zones) column.append(zones);
  return column;
}

function paint() {
  if (!root || !view) return;
  const snapshot = getSnapshot();
  const project = snapshot?.active_project;
  // Фокус берётся до сноса разметки: нажатая кнопка к этому моменту уже
  // погашена `submitAction` и фокус улетел на `<body>` — тогда сработает
  // листок `studio:card-focus-pending` (`dom.js`).
  const focusNote = cardFocusNote();
  root.textContent = "";
  const card = el("div", "v2-viewer-card");
  if (!project) {
    card.append(el("p", "v2-viewer-empty", "Загружаем проект…"));
    root.append(card);
    return;
  }
  const { title, time } = headline(project, view.target);
  const bar = el("header", "v2-viewer-bar");
  const heading = el("h2", "v2-viewer-title", title);
  if (time) heading.append(el("span", "v2-viewer-time", ` · ${time}`));
  const tabs = el("nav", "v2-viewer-tabs");
  tabs.setAttribute("role", "tablist");
  for (const [id, label] of tabsFor(view.target)) {
    const button = el("button", "v2-viewer-tab", label);
    button.type = "button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(id === view.tab));
    button.addEventListener("click", () => pickTab(id));
    tabs.append(button);
  }
  const close = el("button", "v2-viewer-close", "✕");
  close.type = "button";
  close.setAttribute("aria-label", "Закрыть просмотрщик");
  close.addEventListener("click", closeViewer);
  bar.append(heading, tabs, close);

  const body = el("div", "v2-viewer-body");
  if (view.tab === "history") {
    body.append(historyPane(snapshot, view.target));
  } else {
    view.draftKeys = [];
    const { column, prompts, chat } = leftColumn(snapshot, project);
    body.append(column, rightColumn(snapshot, project, prompts, chat));
    dropStaleDrafts(project.id, view.draftKeys);
  }
  card.append(bar, body);
  root.append(card);
  root.setAttribute("aria-label", title);
  returnFocusAfterPaint(focusNote, close);
}

/**
 * Куда встать фокусу после перерисовки. Порядок важен: та же кнопка →
 * соседняя кнопка того же ряда → ✕. Средняя ступень — про принятое
 * решение: «Оставить этот кадр» превращается в неактивного «Выбран», и
 * без неё фокус улетал в угол окна, к крестику.
 */
function returnFocusAfterPaint(note, close) {
  if (restoreCardFocus(root, note)) return;
  if (note) {
    const neighbour = [...root.querySelectorAll(".v2-viewer-buttons > button")]
      .find((button) => !button.disabled && button.offsetParent !== null);
    if (neighbour) {
      neighbour.focus();
      if (document.activeElement === neighbour) {
        dropCardFocusNote();
        return;
      }
    }
  }
  close.focus();
}

/**
 * Черновики отказа и состояние «···» живут в общем хранилище v1
 * (`ui/card-drafts.js`) и без уборки копятся до перезагрузки страницы.
 * Убираются так же, как в v1 (`ui/card-decorate.js`): по своему префиксу
 * и только те ключи, которых в текущей разметке уже нет.
 */
function dropStaleDrafts(projectId, keys) {
  if (!projectId) return;
  const known = new Set(keys);
  pruneDrafts(`${projectId}::v2-viewer::`, known);
  pruneDrafts(`${projectId}::more-menu::`, known);
}

function focusable() {
  return [...root.querySelectorAll(
    'button:not([disabled]), a[href], textarea:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )].filter((node) => node.offsetParent !== null || node === document.activeElement);
}

function onKeyDown(event) {
  if (event.key === "Escape") {
    // Слушатель висит на `document` в capture — то есть раньше «···» и
    // формы комментария внутри него. Если нажали внутри меню, `Esc`
    // принадлежит меню: оно закроет себя само (`ui/more-menu.js`), и
    // просмотрщик остаётся открытым вместе с набранным текстом.
    if (event.target instanceof Element && event.target.closest('[data-hook="more-menu"]')) return;
    // Лист «···» закрывается и тогда, когда фокус ушёл из него: нижний
    // лист занимает пол-экрана, и `Esc` при нём означает «убрать лист», а
    // не «закрыть весь просмотрщик».
    const openMenu = root?.querySelector('[data-hook="more-menu"][data-open="true"]');
    if (openMenu) {
      event.preventDefault();
      const trigger = openMenu.querySelector('[data-more-hook="trigger"]');
      trigger?.click();
      trigger?.focus();
      return;
    }
    event.preventDefault();
    closeViewer();
    return;
  }
  if (event.key === "Tab") {
    const nodes = focusable();
    if (!nodes.length) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
    return;
  }
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  const editing = ["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName);
  if (editing || view?.tab === "history") return;
  event.preventDefault();
  showVariant(view.shown + (event.key === "ArrowRight" ? 1 : -1));
}

let swipeFrom = null;

function onTouchStart(event) {
  swipeFrom = event.changedTouches?.[0]?.clientX ?? null;
}

function onTouchEnd(event) {
  const to = event.changedTouches?.[0]?.clientX;
  if (swipeFrom === null || typeof to !== "number" || view?.tab === "history") return;
  const shift = to - swipeFrom;
  swipeFrom = null;
  if (Math.abs(shift) < 48) return;
  showVariant(view.shown + (shift < 0 ? 1 : -1));
}

/** Закрыть просмотрщик и вернуть фокус туда, откуда его открыли. */
export function closeViewer() {
  if (!root) return;
  const back = view?.returnFocus;
  root.remove();
  root = null;
  view = null;
  document.body.classList.remove("v2-viewer-open");
  document.removeEventListener("keydown", onKeyDown, true);
  if (back?.isConnected) back.focus();
}

function openViewer(detail) {
  const target = detail?.target;
  if (!target || typeof target.id !== "string" || !target.id) return;
  const tabs = tabsFor(target).map(([id]) => id);
  const tab = tabs.includes(detail.tab) ? detail.tab : tabs[0];
  if (root) closeViewer();
  view = {
    target,
    tab,
    slot: typeof detail.slot === "string" && detail.slot !== "video" ? detail.slot : "first",
    shown: 0,
    promptShown: 0,
    statusText: "",
    draftKeys: [],
    returnFocus: detail.trigger instanceof HTMLElement ? detail.trigger : null,
  };
  root = el("div", "v2-viewer");
  root.dataset.hook = "v2-viewer";
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "true");
  root.addEventListener("click", (event) => { if (event.target === root) closeViewer(); });
  root.addEventListener("touchstart", onTouchStart, { passive: true });
  root.addEventListener("touchend", onTouchEnd, { passive: true });
  document.addEventListener("keydown", onKeyDown, true);
  document.body.append(root);
  document.body.classList.add("v2-viewer-open");
  paint();
}

/**
 * Перерисовать открытый просмотрщик по свежему snapshot. Пока решение в
 * полёте, перерисовки нет: `submitAction` гасит кнопки ряда на время
 * запроса, а новый ряд поднялся бы включённым — и фоновый опрос (8 с)
 * посреди запроса давал бы второй клик с тем же `expected_revision`.
 */
export function repaintViewer() {
  if (root && view && !busy()) paint();
}

/**
 * Подписать просмотрщик на `studio:open-viewer`.
 * @param {() => object|null} snapshotSource откуда брать свежий snapshot
 */
export function attachViewerV2(snapshotSource) {
  if (typeof snapshotSource === "function") getSnapshot = snapshotSource;
  document.addEventListener("studio:open-viewer", (event) => {
    if (event?.detail?.version !== 2) return;
    openViewer(event.detail);
  });
}

// Тёмный просмотрщик на весь экран (спецификация §4, вариант C макета
// `scene-viewer-dark.html`). Открывается событием `studio:open-viewer`
// с `detail.version === 2`; слушатель v1 (`ui/viewer.js`) такое событие
// пропускает, поэтому оба живут рядом и не мешают друг другу.
//
// Здесь только оболочка: диалог, ловушка фокуса, клавиши и сборка
// колонок. Холст, плёнка и свайп — `viewer-canvas.js`, промпт — `viewer-prompt.js`,
// зоны — `viewer-zones.js`, кнопки — `decide.js`.

import { renderDecisionHistory } from "../decision-history.js";
import { formatHistoryEntries } from "../history-panel.js";
import { pruneDrafts } from "../card-drafts.js";
import { variantCounts } from "./counts.js";
import { assembleFinal } from "./screen-prompts.js";
import { moreVariants, uploadFrame } from "./chat-prompts.js";
import { showToast } from "./toast.js";
import { cardFocusNote, clock, dropCardFocusNote, el, restoreCardFocus } from "./dom.js";
import { decideDraftKeys, isSubmitting, renderDecideRow } from "./decide.js";
import {
  canvasCaption,
  captionMark,
  filmstrip,
  promptOfVariant,
  renderCanvas,
  renderSlotSwitch,
  slotOptions,
  soloStrip,
  tileMark,
} from "./viewer-canvas.js";
import { promptPlace, promptVersions, renderPromptPanel, variantsByPrompt } from "./viewer-prompt.js";
import { renderAssemblyParts, renderReferenceUsage, renderViewerZones, whereUsed } from "./viewer-zones.js";

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
let view = null; // {target, tab, slot, shown, promptShown, promptPinned, returnFocus}

function scenesInOrder(project) {
  return [...(project?.scenes || [])].sort((left, right) => (left?.order || 0) - (right?.order || 0));
}

function sceneOf(project, id) {
  return scenesInOrder(project).find((item) => item?.scene_id === id) || null;
}

function headline(project, target) {
  if (target.kind === "reference") {
    const reference = (project?.references || []).find((item) => item?.reference_id === target.id);
    const own = reference?.local === true ? whereUsed(project, target.id)[0] : null;
    return { title: reference?.label || target.id, time: own ? `только ${own.label.split(" · ")[0].toLowerCase()}` : "" };
  }
  if (target.kind === "layer") return { title: LAYER_TITLES[target.id] || target.id, time: "" };
  if (target.kind === "assembly") return { title: "Финальный ролик", time: "" };
  if (target.id === "oneshot") return { title: "Ролик одним заходом", time: "" };
  const scenes = scenesInOrder(project);
  const index = scenes.findIndex((item) => item?.scene_id === target.id);
  if (index < 0) return { title: target.id, time: "" };
  const scene = scenes[index];
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

/** Заголовок блока промпта справа — как в макете. */
function promptTitle(target, tab) {
  if (target.kind === "reference") return "Промпт";
  if (target.kind === "assembly") return "Задание на сборку";
  if (tab === "audio") return "Промпт звука";
  return tab === "video" ? "Промпт движения" : "Промпт кадра";
}

/** Чем назвать материал в тосте после решения. */
function nounFor(target, tab) {
  if (target.kind === "reference") return "картинка";
  if (tab === "audio") return "звук";
  return tab === "video" ? "клип" : "кадр";
}

/** Картинка, клип или звук — видеореференс показывается роликом. */
function mediaKindFor(project, target, tab) {
  if (target.kind === "reference") {
    const reference = (project?.references || []).find((item) => item?.reference_id === target.id);
    if (reference?.kind === "video") return "video";
  }
  return MEDIA_KIND[tab] || "image";
}

function tabsFor(target) {
  // Ролик одним заходом — один клип на весь проект, кадров у него нет.
  if (target.kind === "scene" && target.id === "oneshot") return TABS.scene.filter(([id]) => id !== "frames");
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
  const next = Math.min(Math.max(index, 1), Math.max(total, 1));
  if (next === view.shown) return;
  view.shown = next;
  view.promptPinned = false;
  view.statusText = "";
  paint();
}

function pickSlot(slot) {
  if (busy()) return;
  view.slot = slot;
  view.shown = 0;
  view.promptShown = 0;
  view.promptPinned = false;
  view.statusText = "";
  paint();
}

function pickTab(tab) {
  if (busy()) return;
  view.tab = tab;
  view.shown = 0;
  view.promptShown = 0;
  view.promptPinned = false;
  view.statusText = "";
  paint();
}

function leftColumn(snapshot, project) {
  const { target, tab, slot } = view;
  const column = el("div", "v2-viewer-left");
  const missing = target.kind === "scene" && target.id !== "oneshot" && !sceneOf(project, target.id);
  const noFrames = target.kind === "scene" && tab === "frames" && !missing
    && !slotOptions(project, sceneOf(project, target.id)).length;
  if (missing || noFrames) {
    // Решать и просить здесь нечего: сцены нет (её убрали, пока окно
    // было открыто) или кадры для неё не запланированы.
    column.append(el("p", "v2-viewer-note", missing
      ? "Этой сцены в проекте уже нет."
      : "Для этой сцены кадры не запланированы — она оживает по референсам."));
    view.strip = { items: [], total: 0, selectedIndex: 0 };
    view.shown = 1;
    const prompts = promptVersions(project, promptPlace(project, target, { tab, slot: view.slot }));
    if (!view.promptPinned) view.promptShown = prompts.index || 0;
    view.promptShown = Math.min(Math.max(view.promptShown, 1), Math.max(prompts.total, 1));
    return { column, prompts, chat: { sceneId: target.id, slot: view.slot }, strip: view.strip };
  }
  if (target.kind === "scene" && tab === "frames") {
    const options = slotOptions(project, sceneOf(project, target.id));
    if (!options.some((item) => item.slot === view.slot)) view.slot = options[0].slot;
    // Даже один слот показывается пилюлей: она называет, какой это кадр.
    column.append(renderSlotSwitch(options, view.slot, pickSlot));
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
  const byPrompt = shown ? promptOfVariant(shown.version, prompts.versions) : null;
  const byPromptIndex = byPrompt ? prompts.versions.indexOf(byPrompt) + 1 : 0;
  // Пока человек сам не листал промпт, справа — версия, по которой сделан
  // показанный вариант; связи в данных нет — действующая версия места.
  if (!view.promptPinned) view.promptShown = byPromptIndex || prompts.index || 0;
  view.promptShown = Math.min(Math.max(view.promptShown, 1), Math.max(prompts.total, 1));

  const chat = {
    sceneId: target.kind === "scene" ? target.id : undefined,
    referenceId: target.kind === "reference" ? target.id : undefined,
    layer: target.kind === "layer" ? target.id : undefined,
    slot: tab === "video" ? "video" : view.slot,
  };
  column.append(renderCanvas({
    strip,
    shownIndex: view.shown,
    mediaKind: mediaKindFor(project, target, tab),
    caption: canvasCaption({
      index: view.shown,
      total: strip.total,
      mark: strip.solo ? shown?.mark : captionMark(shown?.state),
      solo: strip.solo === true,
      promptLabel: byPromptIndex ? `v${byPromptIndex}` : "",
    }),
    emptyText: target.kind === "assembly" ? "Ролик ещё не собран — попросите агента собрать его." : undefined,
    stageMark: shown && !strip.solo ? tileMark(shown) : "",
    addRequest: target.kind === "assembly" || strip.solo
      ? null
      : moreVariants({ ...chat, project, revision: snapshot.revision, promptVersion: prompts.versions[view.promptShown - 1] || null, selectedVariant: shown?.version || null }),
    onShow: showVariant,
  }));
  const final = target.kind === "assembly";
  const ownFile = strip.solo === true && !final;
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
    noun: nounFor(target, tab),
    onOutcome: showToast,
    // Свой файл референса вариантов не имеет: его можно только заменить.
    chatMenu: !final && !ownFile,
    secondary: final
      ? {
        label: strip.total ? "Пересобрать → чат" : "Собрать → чат",
        request: assembleFinal(project, snapshot.revision, { ready: strip.total > 0 }),
      }
      : ownFile
        ? { label: "Заменить файл → чат", request: uploadFrame({ ...chat, project, revision: snapshot.revision }) }
        : null,
    promptVersion: prompts.versions[view.promptShown - 1] || null,
    editWhat: target.kind === "reference" ? `референса «${target.id}»` : undefined,
  }));
  return { column, prompts, chat, strip };
}

function rightColumn(snapshot, project, prompts, chat, strip) {
  const column = el("aside", "v2-viewer-right");
  // У сборки промпта своего нет: её собирает агент из готовых клипов.
  // Вместо пустой листалки показываем, что собрано и из чего.
  if (view.target.kind === "assembly" && !prompts.total) {
    const about = el("section", "v2-viewer-prompt");
    about.append(el("h3", "v2-viewer-subtitle", "Что собрано"));
    about.append(el("p", "v2-viewer-prompt-text",
      project?.assembly?.summary || "Описания сборки агент не оставил."));
    column.append(about);
    const parts = renderAssemblyParts(project);
    if (parts) column.append(parts);
    return column;
  }
  column.append(renderPromptPanel({
    project,
    revision: snapshot.revision,
    state: prompts,
    shownIndex: view.promptShown,
    title: promptTitle(view.target, view.tab),
    chat,
    editWhat: view.target.kind === "reference" ? `референса «${view.target.id}»` : undefined,
    madeBy: variantsByPrompt(prompts.versions[view.promptShown - 1] || null, strip.solo ? [] : strip.items),
    onShow: (index) => {
      if (busy()) return;
      view.promptShown = index;
      view.promptPinned = true;
      paint();
    },
  }));
  const extra = view.target.kind === "scene"
    ? renderViewerZones(project, snapshot.revision, sceneOf(project, view.target.id))
    : view.target.kind === "reference"
      ? renderReferenceUsage(project, view.target.id)
      : view.target.kind === "assembly" ? renderAssemblyParts(project) : null;
  if (extra) column.append(extra);
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
  close.title = "Закрыть (Esc)";
  close.addEventListener("click", closeViewer);
  bar.append(heading, tabs, close);

  const body = el("div", "v2-viewer-body");
  if (view.tab === "history") {
    body.append(historyPane(snapshot, view.target));
  } else {
    view.draftKeys = [];
    const { column, prompts, chat, strip } = leftColumn(snapshot, project);
    body.append(column, rightColumn(snapshot, project, prompts, chat, strip));
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
    // Закрытое меню `Esc` не держит: фокус на «···» после закрытия меню
    // или формы отказа — и следующий `Esc` закрывает уже окно.
    const menuHere = event.target instanceof Element ? event.target.closest('[data-hook="more-menu"]') : null;
    if (menuHere?.dataset.open === "true") return;
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
    // Открытая форма отказа закрывается раньше окна. Закрывает её свой же
    // пункт меню: он прячет форму и сохраняет набранный текст в черновик,
    // а «Отмена» стёрла бы его.
    const rejectForm = root?.querySelector('[data-hook="v2-viewer-reject"]:not([hidden])');
    if (rejectForm) {
      event.preventDefault();
      root.querySelector(".v2-viewer-menu-danger")?.click();
      root.querySelector('[data-more-hook="trigger"]')?.focus();
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
    promptPinned: false,
    statusText: "",
    draftKeys: [],
    returnFocus: detail.trigger instanceof HTMLElement ? detail.trigger : null,
  };
  root = el("div", "v2-viewer");
  root.dataset.hook = "v2-viewer";
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-modal", "true");
  root.addEventListener("click", (event) => { if (event.target === root) closeViewer(); });
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

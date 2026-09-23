// Левая половина просмотрщика (спецификация §4): переключатель слотов,
// холст с ‹ ›, подпись под ним и плёнка вариантов с пометками.
//
// Чистые функции (`filmstrip`, `slotOptions`, `canvasCaption`) DOM не
// трогают — их и покрывают тесты. Счёт вариантов берётся из `counts.js`,
// порядок версий — из `variants.js`; заново здесь ничего не считается.

import { variantCounts } from "./counts.js";
import { variantState, versionsMadeBy } from "./variants.js";
import { chatButton, el } from "./dom.js";

/** Пометки плёнки — четыре из спецификации плюс «принят» и «убран». */
export const VARIANT_MARKS = Object.freeze({
  own: "Ваш файл",
  final: "Финальный ролик",
  selected: "выбран",
  approved: "принят",
  new: "новый",
  rejected: "отклонён",
  hidden: "скрыт",
  retired: "убран",
});

/** Слово состояния в подписи под холстом: «Вариант 2 из 4 · не выбран». */
export const CAPTION_WORDS = Object.freeze({
  selected: "выбран",
  approved: "принят",
  rejected: "отклонён",
  hidden: "скрыт",
  retired: "убран из работы",
  new: "не выбран",
});

/** Сколько пикселей пальцем по сцене — уже листание (хэндофф: 50). */
export const SWIPE_THRESHOLD = 50;

const DIMMED = new Set(["rejected", "hidden", "retired"]);
const SLOT_TITLES = Object.freeze({ first: "Первый кадр", last: "Последний кадр", video: "Клип" });

function plural(total) {
  const tail = total % 100;
  if (tail >= 11 && tail <= 14) return "вариантов";
  const last = total % 10;
  if (last === 1) return "вариант";
  if (last >= 2 && last <= 4) return "варианта";
  return "вариантов";
}

/**
 * Плёнка вариантов: порядок цепочки, пометка и номер каждого.
 * «Выбран» — только тот, на который указывает ссылка владельца; вариант,
 * одобренный решением, но не выбранный, помечается «принят».
 *
 * @param {{versions?: object[], selected?: object|null}} counts результат `variantCounts`
 * @returns {{items: {version: object, state: string, mark: string, index: number,
 *            dim: boolean}[], selectedIndex: number, total: number}}
 *   `selectedIndex` — номер выбранного с 1, или 0, если выбора нет.
 */
export function filmstrip({ versions = [], selected = null } = {}) {
  const items = versions.map((version, order) => {
    const linked = Boolean(selected) && version.version_id === selected.version_id;
    const own = variantState(version);
    const state = linked ? "selected" : own === "selected" ? "approved" : own;
    return { version, state, mark: VARIANT_MARKS[state] || "", index: order + 1, dim: DIMMED.has(state) };
  });
  const found = items.findIndex((item) => item.state === "selected");
  return { items, selectedIndex: found + 1, total: items.length };
}

/**
 * Плёнка из одного файла, у которого версии результата нет вовсе:
 * загруженный референс (`source: "upload"` — файл лежит прямо на записи
 * референса) и собранный ролик (`project.assembly`). Решения по такой
 * плитке не предлагаются: `decide.js` отказывает всему, что нечем
 * адресовать.
 *
 * @param {string|null} assetUrl `/assets/…`
 * @param {string} [caption] подпись файла
 * @param {"own"|"final"} [state] что это за файл
 * @returns {{items: object[], selectedIndex: number, total: number,
 *            solo: true}|null} `solo` говорит подписи под холстом, что
 *   нумеровать нечего: это не вариант из ряда, а единственный файл.
 */
export function soloStrip(assetUrl, caption, state = "own") {
  if (typeof assetUrl !== "string" || !assetUrl) return null;
  const mark = VARIANT_MARKS[state] || VARIANT_MARKS.own;
  const version = { asset_url: assetUrl, caption: caption || mark };
  return {
    items: [{ version, state, mark, index: 1, dim: false }],
    selectedIndex: 1,
    total: 1,
    solo: true,
  };
}

/**
 * Какие слоты показывать переключателем слева: только те, что уже есть
 * или требуются планом кадров (`need_first`/`need_last`).
 *
 * @param {object} project `snapshot.active_project`
 * @param {object} scene запись сцены
 * @returns {{slot: string, label: string, total: number}[]}
 */
export function slotOptions(project, scene) {
  const options = [];
  for (const slot of ["first", "last"]) {
    const total = variantCounts(project, { sceneId: scene?.scene_id, slot }).total;
    const needed = scene?.[slot === "first" ? "need_first" : "need_last"] === true;
    if (!needed && total === 0) continue;
    options.push({
      slot,
      total,
      label: `${SLOT_TITLES[slot]} · ${total ? `${total} ${plural(total)}` : "нет"}`,
    });
  }
  return options;
}

/**
 * Подпись под холстом: «Вариант 3 из 4 · выбран · по промпту v2».
 * Хвост «по промпту» появляется только тогда, когда связь результата с
 * версией промпта действительно есть в snapshot (спецификация §5).
 *
 * @param {{index: number, total: number, mark?: string, promptLabel?: string,
 *          solo?: boolean}} shown `solo` — единственный файл без ряда
 *   вариантов: нумеровать нечего, остаётся одна пометка.
 * @returns {string}
 */
export function canvasCaption({ index, total, mark, promptLabel, solo } = {}) {
  if (!Number.isFinite(index) || !Number.isFinite(total) || total < 1) return "Вариантов пока нет";
  if (solo) return mark || "Файл";
  const parts = [`Вариант ${index} из ${total}`];
  if (mark) parts.push(mark);
  if (promptLabel) parts.push(`по промпту ${promptLabel}`);
  return parts.join(" · ");
}

/**
 * Слово состояния варианта для подписи под холстом.
 * @param {string} state состояние из `filmstrip`
 * @returns {string}
 */
export function captionMark(state) {
  return CAPTION_WORDS[state] || CAPTION_WORDS.new;
}

/**
 * Куда листать по жесту пальцем: `1` — к следующему, `-1` — к
 * предыдущему, `0` — не листать. Вертикальный жест — прокрутка страницы,
 * а не листание, поэтому он не считается даже длинным.
 *
 * @param {number} dx сдвиг по горизонтали, px
 * @param {number} [dy] сдвиг по вертикали, px
 */
export function swipeStep(dx, dy = 0) {
  if (!Number.isFinite(dx) || Math.abs(dx) < SWIPE_THRESHOLD) return 0;
  if (Number.isFinite(dy) && Math.abs(dy) > Math.abs(dx)) return 0;
  return dx < 0 ? 1 : -1;
}

/**
 * Версия промпта, по которой сделан этот вариант, — или `null`, если
 * связи в данных нет.
 *
 * @param {object} version запись версии результата
 * @param {object[]} promptVersions версии промпта этого места
 */
export function promptOfVariant(version, promptVersions) {
  for (const prompt of Array.isArray(promptVersions) ? promptVersions : []) {
    if (versionsMadeBy(prompt?.version_id, [version]).length > 0) return prompt;
  }
  return null;
}

/** Холст: картинка, видео с управлением или звук — по виду материала. */
function media(version, mediaKind) {
  const url = typeof version?.asset_url === "string" ? version.asset_url : "";
  if (!url) return el("p", "v2-viewer-empty", "Файла пока нет");
  if (mediaKind === "video" || mediaKind === "audio") {
    const node = document.createElement(mediaKind);
    node.src = url;
    node.controls = true;
    node.preload = "metadata";
    node.className = "v2-viewer-media";
    return node;
  }
  const image = document.createElement("img");
  image.src = url;
  image.alt = version?.caption || "Вариант";
  image.className = "v2-viewer-media";
  return image;
}

function arrow(label, title, onClick, disabled) {
  const button = el("button", "v2-viewer-arrow", label);
  button.type = "button";
  button.disabled = disabled;
  button.setAttribute("aria-label", title);
  button.addEventListener("click", onClick);
  return button;
}

function tilePreview(url, mediaKind) {
  if (typeof url !== "string" || !url.startsWith("/assets/")) return null;
  if (mediaKind === "audio") return null;
  if (mediaKind === "video") {
    // `<img>` на mp4 даёт битую плитку (`video-thumb.js`): первый кадр
    // берётся из самого ролика, без звука и без загрузки целиком.
    const clip = document.createElement("video");
    clip.src = url;
    clip.preload = "metadata";
    clip.muted = true;
    clip.playsInline = true;
    clip.tabIndex = -1;
    return clip;
  }
  const preview = document.createElement("img");
  preview.src = url;
  preview.alt = "";
  preview.loading = "lazy";
  return preview;
}

/**
 * Листание пальцем по сцене: порог `SWIPE_THRESHOLD`, вертикальный жест
 * остаётся прокруткой. Слушатель висит на самой сцене, а не на всём окне:
 * плёнка под ней прокручивается вбок тем же жестом и листать не должна.
 */
function attachSwipe(stage, shownIndex, onShow) {
  let from = null;
  stage.addEventListener("touchstart", (event) => {
    const touch = event.changedTouches?.[0];
    from = touch ? { x: touch.clientX, y: touch.clientY } : null;
  }, { passive: true });
  stage.addEventListener("touchend", (event) => {
    const touch = event.changedTouches?.[0];
    if (!from || !touch) return;
    const step = swipeStep(touch.clientX - from.x, touch.clientY - from.y);
    from = null;
    if (step) onShow(shownIndex + step);
  }, { passive: true });
  stage.addEventListener("touchcancel", () => { from = null; }, { passive: true });
}

/**
 * Холст с листалкой и плёнкой.
 *
 * В конце плёнки — плитка «＋»: тот же запрос агенту, что «＋ Ещё
 * вариант» под холстом (хэндофф 2026-09-23). На телефоне стрелок нет,
 * листание — свайпом по сцене.
 *
 * @param {{strip: object, shownIndex: number, mediaKind: string, caption: string,
 *          stageMark?: string, addRequest?: object|null,
 *          onShow: (index: number) => void}} context
 *   `shownIndex` — номер показанного варианта с 1; `stageMark` — пилюля
 *   в углу сцены; `addRequest` — запрос из `chat-prompts.moreVariants`,
 *   без него плитки «＋» нет.
 * @returns {HTMLElement}
 */
export function renderCanvas({ strip, shownIndex, mediaKind, caption, stageMark, addRequest, onShow }) {
  const wrap = el("div", "v2-viewer-canvas-wrap");
  const canvas = el("div", "v2-viewer-canvas");
  canvas.dataset.hook = "v2-viewer-canvas";
  const shown = strip.items[shownIndex - 1];
  canvas.append(arrow("‹", "Предыдущий вариант (←)", () => onShow(shownIndex - 1), shownIndex <= 1));
  const frame = el("div", "v2-viewer-frame");
  frame.dataset.media = mediaKind || "image";
  if (shown) {
    frame.dataset.dim = String(shown.dim === true);
    frame.append(media(shown.version, mediaKind));
    if (stageMark) frame.append(el("span", "v2-viewer-stage-mark", stageMark));
  } else {
    frame.dataset.empty = "true";
    frame.append(el("p", "v2-viewer-empty", "Вариантов пока нет — попросите агента сделать первый."));
    if (addRequest) frame.append(chatButton("＋ Попросить вариант", addRequest, "v2-viewer-ask"));
  }
  canvas.append(frame);
  canvas.append(arrow("›", "Следующий вариант (→)", () => onShow(shownIndex + 1), shownIndex >= strip.total));
  if (strip.total > 1) attachSwipe(canvas, shownIndex, onShow);
  wrap.append(canvas);
  if (shown) {
    const label = el("p", "v2-viewer-caption", caption);
    label.dataset.hook = "v2-viewer-caption";
    wrap.append(label);
  }

  const film = el("div", "v2-viewer-film");
  film.dataset.hook = "v2-viewer-film";
  for (const item of strip.items) {
    const tile = el("button", "v2-viewer-tile");
    tile.type = "button";
    tile.dataset.state = item.state;
    tile.dataset.dim = String(item.dim);
    tile.setAttribute("aria-current", String(item.index === shownIndex));
    tile.setAttribute("aria-label", `Вариант ${item.index}${item.mark ? `, ${item.mark}` : ""}`);
    const preview = tilePreview(item.version.asset_url, mediaKind);
    if (preview) tile.append(preview);
    // Единственный файл не нумеруется: «1 · Финальный ролик» — лишнее.
    const mark = item.state === "selected" ? `✓ ${item.mark}` : item.mark;
    tile.append(el("span", "v2-viewer-tile-mark", strip.solo
      ? item.mark
      : `${item.index}${mark ? ` · ${mark}` : ""}`));
    tile.addEventListener("click", () => onShow(item.index));
    film.append(tile);
  }
  if (addRequest && strip.total > 0) {
    const plus = chatButton("＋", addRequest, "v2-viewer-tile-add");
    plus.setAttribute("aria-label", "Ещё вариант");
    plus.title = "Ещё вариант";
    film.append(plus);
  }
  if (film.childElementCount) wrap.append(film);
  return wrap;
}

/** Переключатель слотов слева сверху. */
export function renderSlotSwitch(options, current, onPick) {
  const strip = el("div", "v2-viewer-slots");
  strip.dataset.hook = "v2-viewer-slots";
  strip.setAttribute("role", "tablist");
  for (const option of options) {
    const button = el("button", "v2-viewer-slot", option.label);
    button.type = "button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(option.slot === current));
    button.addEventListener("click", () => onPick(option.slot));
    strip.append(button);
  }
  return strip;
}

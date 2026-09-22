// Левая половина просмотрщика (спецификация §4): переключатель слотов,
// холст с ‹ ›, подпись под ним и плёнка вариантов с пометками.
//
// Чистые функции (`filmstrip`, `slotOptions`, `canvasCaption`) DOM не
// трогают — их и покрывают тесты. Счёт вариантов берётся из `counts.js`,
// порядок версий — из `variants.js`; заново здесь ничего не считается.

import { variantCounts } from "./counts.js";
import { variantState, versionsMadeBy } from "./variants.js";
import { el } from "./dom.js";

/** Пометки плёнки — четыре из спецификации плюс «принят» и «убран». */
export const VARIANT_MARKS = Object.freeze({
  selected: "выбран",
  approved: "принят",
  new: "новый",
  rejected: "отклонён",
  hidden: "скрыт",
  retired: "убран",
});

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
 * @param {{index: number, total: number, mark?: string, promptLabel?: string}} shown
 * @returns {string}
 */
export function canvasCaption({ index, total, mark, promptLabel } = {}) {
  if (!Number.isFinite(index) || !Number.isFinite(total) || total < 1) return "Вариантов пока нет";
  const parts = [`Вариант ${index} из ${total}`];
  if (mark) parts.push(mark);
  if (promptLabel) parts.push(`по промпту ${promptLabel}`);
  return parts.join(" · ");
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

/**
 * Холст с листалкой и плёнкой.
 *
 * @param {{strip: object, shownIndex: number, mediaKind: string, caption: string,
 *          onShow: (index: number) => void, onMore: () => void}} context
 *   `shownIndex` — номер показанного варианта с 1.
 * @returns {HTMLElement}
 */
export function renderCanvas({ strip, shownIndex, mediaKind, caption, onShow, onMore }) {
  const wrap = el("div", "v2-viewer-canvas-wrap");
  const canvas = el("div", "v2-viewer-canvas");
  canvas.dataset.hook = "v2-viewer-canvas";
  const shown = strip.items[shownIndex - 1];
  canvas.append(arrow("‹", "Предыдущий вариант", () => onShow(shownIndex - 1), shownIndex <= 1));
  canvas.append(shown ? media(shown.version, mediaKind) : el("p", "v2-viewer-empty", "Вариантов пока нет"));
  canvas.append(arrow("›", "Следующий вариант", () => onShow(shownIndex + 1), shownIndex >= strip.total));
  const label = el("p", "v2-viewer-caption", caption);
  label.dataset.hook = "v2-viewer-caption";
  wrap.append(canvas, label);

  const film = el("div", "v2-viewer-film");
  film.dataset.hook = "v2-viewer-film";
  for (const item of strip.items) {
    const tile = el("button", "v2-viewer-tile");
    tile.type = "button";
    tile.dataset.state = item.state;
    tile.dataset.dim = String(item.dim);
    tile.setAttribute("aria-current", String(item.index === shownIndex));
    tile.setAttribute("aria-label", `Вариант ${item.index}${item.mark ? `, ${item.mark}` : ""}`);
    if (typeof item.version.asset_url === "string" && item.version.asset_url.startsWith("/assets/")) {
      const preview = document.createElement("img");
      preview.src = item.version.asset_url;
      preview.alt = "";
      preview.loading = "lazy";
      tile.append(preview);
    }
    tile.append(el("span", "v2-viewer-tile-mark", `${item.index}${item.mark ? ` · ${item.mark}` : ""}`));
    tile.addEventListener("click", () => onShow(item.index));
    film.append(tile);
  }
  const add = el("button", "v2-viewer-tile v2-viewer-tile-add", "＋ Ещё");
  add.type = "button";
  add.addEventListener("click", () => onMore(add));
  film.append(add);
  wrap.append(film);
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

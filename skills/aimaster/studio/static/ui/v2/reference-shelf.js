// Полка общих референсов (спецификация §3.2, макет scene-row-v4):
// пять подписанных групп, в каждой плитки «картинка · имя · статус»
// и «＋», открывающая запрос агенту.

import { addReference } from "./chat-prompts.js";
import { variantCounts, variantStatus } from "./counts.js";
import { statusLine } from "./board-bits.js";
import { chatButton, el, openViewer } from "./dom.js";
import { renderPreview } from "./preview.js";
import { statusTone } from "./status-tone.js";

export const SHELF_GROUPS = Object.freeze([
  Object.freeze({ kind: "character", title: "Персонажи", subtitle: "люди и герои; у каждого может быть голос" }),
  Object.freeze({ kind: "location", title: "Локации", subtitle: "места, где идёт действие" }),
  Object.freeze({ kind: "product", title: "Реквизит", subtitle: "предметы, которые должны выглядеть одинаково" }),
  Object.freeze({ kind: "style", title: "Стиль", subtitle: "общая картинка: свет, цвет, оптика" }),
  Object.freeze({ kind: "other", title: "Прочее", subtitle: "всё остальное — загрузите что угодно" }),
]);

/**
 * Общие референсы проекта по группам. Локальные (референсы одной сцены)
 * и видеореференсы сюда не попадают — они живут в строке сцены.
 * @param {object} project `snapshot.active_project`
 * @returns {{kind: string, title: string, subtitle: string, items: object[]}[]}
 */
export function shelfGroups(project) {
  const shared = (project?.references || []).filter(
    (item) => item && item.local !== true && item.kind !== "video",
  );
  return SHELF_GROUPS.map((group) => ({
    ...group,
    items: shared.filter((item) => item.kind === group.kind),
  }));
}

function referenceTile(project, revision, reference) {
  const counts = variantCounts(project, { referenceId: reference.reference_id });
  const own = { source: reference.source, hasAsset: reference.has_asset === true };
  const status = variantStatus(counts, own);
  const name = reference.label || reference.reference_id;
  const tile = el("button", "v2-tile");
  tile.type = "button";
  tile.dataset.hook = "v2-reference-tile";
  tile.dataset.referenceId = reference.reference_id;
  tile.setAttribute("aria-label", `${name}: ${status}`);
  const picture = el("span", "v2-tile-picture");
  // Свой файл — картинка референса, иначе выбранный вариант генерации.
  const shown = reference.asset_url ? reference : counts.selected;
  picture.append(renderPreview(shown ? { ...shown, media_type: shown.media_type || reference.media_type, kind: reference.kind } : null, {
    label: name, emptyText: "нет картинки",
  }));
  if (counts.total > 1) picture.append(el("span", "v2-tile-badge", String(counts.total)));
  if (reference.kind === "character" && reference.voice?.enabled === true) {
    picture.append(el("span", "v2-tile-voice", "🎙"));
  }
  const caption = el("span", "v2-tile-caption");
  caption.append(el("b", "v2-tile-name", name), statusLine(status, statusTone(counts, own), "v2-status v2-tile-status"));
  tile.append(picture, caption);
  tile.addEventListener("click", () => openViewer(
    { kind: "reference", id: reference.reference_id },
    { tab: "frames", trigger: tile },
  ));
  return tile;
}

/**
 * @param {object} project `snapshot.active_project`
 * @param {number} revision `snapshot.revision` — попадает в запросы агенту
 * @returns {HTMLElement} `<section>` с пятью группами
 */
export function renderShelf(project, revision) {
  const section = el("section", "v2-shelf");
  section.dataset.hook = "v2-shelf";
  const head = el("div", "v2-section-head");
  head.append(
    el("h2", "v2-section-title", "Референсы"),
    el("span", "v2-section-note", "Постоянные для всего ролика: кто в кадре, где, с чем и в каком стиле."),
  );
  section.append(head);
  const groups = el("div", "v2-shelf-groups");
  for (const group of shelfGroups(project)) {
    const block = el("section", "v2-shelf-group");
    block.dataset.kind = group.kind;
    const top = el("div", "v2-shelf-group-head");
    top.append(el("h3", "v2-shelf-group-title", group.title));
    top.append(el("span", "v2-shelf-group-count", group.items.length ? String(group.items.length) : ""));
    top.append(el("span", "v2-shelf-group-hint", group.subtitle));
    block.append(top);
    const items = el("div", "v2-shelf-items");
    for (const reference of group.items) items.append(referenceTile(project, revision, reference));
    const add = chatButton("＋", addReference(group.kind, project, revision), "v2-tile-add");
    add.setAttribute("aria-label", `Добавить: ${group.title.toLowerCase()}`);
    items.append(add);
    block.append(items);
    groups.append(block);
  }
  section.append(groups);
  return section;
}

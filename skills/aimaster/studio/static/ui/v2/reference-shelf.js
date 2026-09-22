// Полка общих референсов (спецификация §3.2, макет scene-row-v4):
// пять подписанных групп, в каждой плитки «картинка · имя · статус»
// и «＋», открывающая запрос агенту.

import { addReference } from "./chat-prompts.js";
import { variantCounts, variantStatus } from "./counts.js";
import { chatButton, el, openViewer, thumb } from "./dom.js";

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
  const status = variantStatus(counts, {
    source: reference.source,
    hasAsset: reference.has_asset === true,
  });
  const name = reference.label || reference.reference_id;
  const tile = el("button", "v2-tile");
  tile.type = "button";
  tile.dataset.hook = "v2-reference-tile";
  tile.dataset.referenceId = reference.reference_id;
  tile.setAttribute("aria-label", `${name}: ${status}`);
  const picture = el("span", "v2-tile-picture");
  picture.append(thumb(counts.selected?.asset_url || reference.asset_url || null, name));
  if (counts.total > 1) picture.append(el("span", "v2-tile-badge", String(counts.total)));
  if (reference.kind === "character" && reference.voice?.enabled === true) {
    picture.append(el("span", "v2-tile-voice", "🎙"));
  }
  const caption = el("span", "v2-tile-caption");
  caption.append(el("b", "", name), el("span", "", status));
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
  section.append(
    el("h2", "v2-section-title", "Референсы"),
    el("p", "v2-section-hint", "Постоянные для всего ролика: кто в кадре, где, с чем и в каком стиле."),
  );
  const groups = el("div", "v2-shelf-groups");
  for (const group of shelfGroups(project)) {
    const block = el("section", "v2-shelf-group");
    block.dataset.kind = group.kind;
    block.append(el("h3", "", group.title), el("p", "v2-shelf-group-hint", group.subtitle));
    const items = el("div", "v2-shelf-items");
    for (const reference of group.items) items.append(referenceTile(project, revision, reference));
    items.append(chatButton(
      "＋",
      addReference(group.kind, project, revision),
      "v2-tile v2-tile-add",
    ));
    block.append(items);
    groups.append(block);
  }
  section.append(groups);
  return section;
}

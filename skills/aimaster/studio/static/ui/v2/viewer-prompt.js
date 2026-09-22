// Правая колонка просмотрщика: промпт с листалкой версий ‹ v2 из 3 ›,
// подсветка тегов @IMG_NN/@VID_NN/@VOICE_NN и «Изменить → чат».
//
// Теги подсвечиваются разбором текста на куски (`splitTags`) и сборкой
// из `textContent`: разметку из промпта страница не исполняет никогда —
// ни как HTML, ни через `innerHTML`.
//
// Чистые функции: `promptPlace`, `promptVersions`, `splitTags`,
// `promptMeta`. Они же покрыты тестами.

import { promptGroups } from "./variants.js";
import { chatButton, el } from "./dom.js";
import { editPrompt } from "./chat-prompts.js";

const TAG = /@(?:IMG|VID|VOICE)_\d{2,}/g;

const STATUS_WORDS = Object.freeze({
  approved: "одобрен",
  pending: "черновик",
  rejected: "нужны правки",
});

/** Ссылка на действующую версию промпта — по месту (`domain_positions`). */
const PROMPT_LINKS = Object.freeze({
  first: "first_frame_prompt_version_id",
  last: "last_frame_prompt_version_id",
  image: "image_prompt_version_id",
  video: "motion_prompt_version_id",
});

/**
 * Где искать промпт этого места: какая коллекция, какая группа и какая
 * версия считается действующей.
 *
 * @param {object} project `snapshot.active_project`
 * @param {{kind: string, id: string}} target цель просмотрщика
 * @param {{tab?: string, slot?: string}} [view]
 * @returns {{collection: string, groupId: string|null, activeId: string|null}}
 */
export function promptPlace(project, target = {}, { tab = "frames", slot = "first" } = {}) {
  const positions = (project?.positions || []).filter(Boolean);
  const pick = (test) => positions.find(test)?.prompt_group_id || null;
  if (target.kind === "reference") {
    const reference = (project?.references || []).find((item) => item?.reference_id === target.id);
    return {
      collection: "image_prompts",
      groupId: pick((item) => item.kind === "reference" && item.tag === target.id),
      activeId: reference?.links?.image_prompt_version_id || null,
    };
  }
  if (target.kind === "layer") {
    const owner = (project?.audio_layers || []).find((item) => item?.layer === target.id);
    return {
      collection: "audio_prompts",
      groupId: pick((item) => item.position_id === `pos:audio:${target.id}`),
      activeId: owner?.links?.audio_prompt_version_id || null,
    };
  }
  if (target.kind === "assembly") {
    return {
      collection: "motion_prompts",
      groupId: pick((item) => item.kind === "oneshot"),
      activeId: project?.oneshot?.links?.motion_prompt_version_id || null,
    };
  }
  const scene = (project?.scenes || []).find((item) => item?.scene_id === target.id);
  if (tab === "video") {
    return {
      collection: "motion_prompts",
      groupId: pick((item) => item.kind === "video" && item.scene_id === target.id),
      activeId: scene?.links?.motion_prompt_version_id || null,
    };
  }
  const kind = `${slot}_frame`;
  return {
    collection: "image_prompts",
    groupId: pick((item) => item.scene_id === target.id && (item.kind === kind || item.kind === "image")),
    activeId: scene?.links?.[PROMPT_LINKS[slot]] || scene?.links?.image_prompt_version_id || null,
  };
}

/**
 * Версии промпта этого места по порядку цепочки и какая из них открыта.
 *
 * @param {object} project `snapshot.active_project`
 * @param {{collection: string, groupId: string|null, activeId: string|null}} place
 * @returns {{versions: object[], index: number, active: object|null, total: number}}
 *   `index` — номер открытой версии с 1, или 0, если версий нет.
 */
export function promptVersions(project, place) {
  const records = project?.[place?.collection] || [];
  const byActive = records.find((item) => item?.version_id === place?.activeId) || null;
  const groupId = place?.groupId || byActive?.prompt_id || null;
  const versions = groupId ? promptGroups(records).get(groupId) || [] : [];
  if (!versions.length) return { versions: [], index: 0, active: null, total: 0 };
  const found = versions.findIndex((item) => item.version_id === place?.activeId);
  const index = found >= 0 ? found + 1 : versions.length;
  return { versions, index, active: versions[index - 1], total: versions.length };
}

/**
 * Разбор текста промпта на куски: обычный текст и теги референсов.
 * @param {string} text
 * @returns {{text: string, tag: boolean}[]}
 */
export function splitTags(text) {
  const source = typeof text === "string" ? text : "";
  const parts = [];
  let at = 0;
  for (const match of source.matchAll(TAG)) {
    if (match.index > at) parts.push({ text: source.slice(at, match.index), tag: false });
    parts.push({ text: match[0], tag: true });
    at = match.index + match[0].length;
  }
  if (at < source.length) parts.push({ text: source.slice(at), tag: false });
  return parts;
}

/**
 * Мета под текстом: «v2 · черновик · устарел».
 * @param {object|null} version запись версии промпта
 * @param {number} index номер версии с 1
 */
export function promptMeta(version, index) {
  if (!version) return "промпта пока нет";
  const parts = [`v${index || 1}`];
  const status = STATUS_WORDS[version.status];
  if (status) parts.push(status);
  if (version.stale === true) parts.push("устарел");
  return parts.join(" · ");
}

function versionNav(state, shownIndex, onShow) {
  const nav = el("div", "v2-viewer-ver");
  const back = el("button", "v2-viewer-ver-step", "‹");
  back.type = "button";
  back.setAttribute("aria-label", "Предыдущая версия промпта");
  back.disabled = shownIndex <= 1;
  back.addEventListener("click", () => onShow(shownIndex - 1));
  const forward = el("button", "v2-viewer-ver-step", "›");
  forward.type = "button";
  forward.setAttribute("aria-label", "Следующая версия промпта");
  forward.disabled = shownIndex >= state.total;
  forward.addEventListener("click", () => onShow(shownIndex + 1));
  nav.append(back, el("span", "v2-viewer-ver-label", `v${shownIndex} из ${state.total}`), forward);
  return nav;
}

/**
 * Блок промпта целиком.
 *
 * @param {{project: object, revision: number, state: object, shownIndex: number,
 *          title: string, chat: object, editWhat?: string,
 *          onShow: (index: number) => void}} context
 * @returns {HTMLElement}
 */
export function renderPromptPanel({ project, revision, state, shownIndex, title, chat, editWhat, onShow }) {
  const block = el("section", "v2-viewer-prompt");
  block.dataset.hook = "v2-viewer-prompt";
  const head = el("h3", "v2-viewer-subtitle", title);
  if (state.total > 1) head.append(versionNav(state, shownIndex, onShow));
  block.append(head);
  const shown = state.versions[shownIndex - 1] || null;
  if (!shown) {
    block.append(el("p", "v2-viewer-empty-line", "Промпта пока нет — попросите агента его написать."));
    return block;
  }
  const text = el("p", "v2-viewer-prompt-text");
  for (const part of splitTags(shown.text)) {
    text.append(part.tag ? el("mark", "v2-viewer-tag", part.text) : document.createTextNode(part.text));
  }
  const meta = el("p", "v2-viewer-prompt-meta", promptMeta(shown, shownIndex));
  meta.dataset.hook = "v2-viewer-prompt-meta";
  block.append(text, meta, chatButton(
    "Изменить → чат",
    editPrompt({ ...chat, project, revision, promptVersion: shown, what: editWhat }),
    "v2-viewer-link",
  ));
  return block;
}

// Превью материала в просмотрщике: где файл есть — картинка, клип или
// звук; где файла нет или он не открылся — явная заглушка с подписью.
// Битых картинок и пустых прямоугольников не бывает.
//
// Тип файла определяет одно правило на весь дашборд — `previewKind()`
// из `preview.js` (запись, расширение, `kind: "video"`, затем тип по
// месту). Здесь свои только крупные плееры с управлением и плитки
// плёнки: у миниатюр доски другая задача.
//
// Клип: `<video preload="metadata">` с якорем `#t=0.1` — браузер
// докачивает начало и показывает первый кадр, не проигрывая
// (как `video-thumb.js`). CSP это разрешает (`media-src 'self'`).
//
// Чистая часть — `mediaPlan(url, kind)`; её и покрывают тесты.

import { el } from "./dom.js";
import { assetUrlOf, previewKind } from "./preview.js";

/** Подписи заглушек — по виду материала и причине. */
export const PLACEHOLDER_TEXT = Object.freeze({
  missing: Object.freeze({ image: "Картинки пока нет", video: "Клипа пока нет", audio: "Звука пока нет" }),
  broken: "Файл не открылся",
});

const AUDIO_GLYPH = "♪";

/**
 * Что рисовать для этой записи.
 * @param {object|null} record запись с `asset_url` (вариант, свой файл, сборка)
 * @param {"image"|"video"|"audio"} [fallback] тип по месту, если запись молчит
 * @returns {{tag: "img"|"video"|"audio"|null, src: string, kind: string,
 *            placeholder: string}} `tag: null` — только заглушка
 */
export function mediaPlan(record, fallback = "image") {
  const place = fallback === "video" || fallback === "audio" ? fallback : "image";
  const kind = previewKind(record, { fallback: place });
  const url = assetUrlOf(record);
  if (kind === "none" || !url) {
    return { tag: null, src: "", kind: place, placeholder: PLACEHOLDER_TEXT.missing[place] };
  }
  if (kind === "video") return { tag: "video", src: `${url}#t=0.1`, kind, placeholder: "" };
  if (kind === "audio") return { tag: "audio", src: url, kind, placeholder: "" };
  return { tag: "img", src: url, kind, placeholder: "" };
}

/**
 * Заглушка с подписью.
 * @param {string} text подпись
 * @param {string} kind вид материала — для значка
 * @param {"big"|"tile"} size на холсте или в плёнке
 */
export function placeholder(text, kind, size) {
  const box = el("span", "v2-viewer-placeholder");
  box.dataset.size = size;
  box.dataset.kind = kind;
  box.setAttribute("role", "img");
  box.setAttribute("aria-label", text);
  if (kind === "audio" && size === "tile") box.append(el("span", "v2-viewer-placeholder-glyph", AUDIO_GLYPH));
  box.append(el("span", "v2-viewer-placeholder-text", text));
  return box;
}

/**
 * Превью одного файла.
 *
 * @param {object|null} record запись с `asset_url`
 * @param {"image"|"video"|"audio"} kind тип по месту, если запись молчит
 * @param {{size?: "big"|"tile", label?: string}} [options]
 *   `big` — холст с управлением, `tile` — плитка плёнки без звука и фокуса
 * @returns {HTMLElement}
 */
export function renderMedia(record, kind, { size = "big", label = "" } = {}) {
  const plan = mediaPlan(record, kind);
  if (!plan.tag) return placeholder(plan.placeholder, plan.kind, size);
  // Звук в плёнке — значок, а не плеер: плитка узкая, а проигрывать
  // надо на холсте.
  if (plan.tag === "audio" && size === "tile") return placeholder("звук", "audio", size);

  const node = document.createElement(plan.tag);
  node.className = size === "tile" ? "v2-viewer-tile-media" : "v2-viewer-media";
  if (plan.tag === "img") {
    node.alt = label || "";
    if (size === "tile") node.loading = "lazy";
  } else {
    node.preload = "metadata";
    if (size === "tile") {
      node.muted = true;
      node.playsInline = true;
      node.tabIndex = -1;
    } else {
      node.controls = true;
      if (plan.tag === "video") node.playsInline = true;
    }
    if (label) node.setAttribute("aria-label", label);
  }
  // Плеер звука узкий по высоте: рядом значок, чтобы холст не казался
  // пустым прямоугольником.
  let outer = node;
  if (plan.tag === "audio") {
    outer = el("span", "v2-viewer-audio");
    outer.append(el("span", "v2-viewer-audio-glyph", AUDIO_GLYPH), node);
  }
  node.addEventListener("error", () => {
    outer.replaceWith(placeholder(PLACEHOLDER_TEXT.broken, plan.kind, size));
  }, { once: true });
  node.src = plan.src;
  return outer;
}

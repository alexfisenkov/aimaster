// Превью файла — одно правило на все экраны доски (требование владельца
// 2026-09-23): где файл есть — превью, где нет — явная заглушка со
// штриховкой и подписью. Никаких битых картинок и пустых прямоугольников.
//
//   картинка → `<img>` с object-fit: cover;
//   видео    → `video-thumb.js` (`<video preload="metadata">`, `#t=0.1`),
//              никогда `<img>` на mp4;
//   звук     → значок «♪» на штриховке (волну рисует экран «Звук»);
//   нет файла → штриховка и подпись («нет картинки», «клипа нет»…);
//   файл не открылся (`error`) → та же штриховка, «файл не открылся».
//
// Адреса файлов расширения не несут (`/assets/asset-…`), поэтому тип
// берётся из записи: `media_type`, затем расширение, затем `kind: "video"`
// у видеореференса, затем то, что знает место (коллекция результатов).

import { el } from "./dom.js";
import { videoThumb } from "./video-thumb.js";

const KINDS = new Set(["image", "video", "audio"]);
const EXTENSIONS = Object.freeze({
  image: /\.(png|jpe?g|webp|gif|avif|bmp|svg)$/i,
  video: /\.(mp4|mov|m4v|webm|mkv)$/i,
  audio: /\.(mp3|wav|m4a|aac|ogg|oga|flac|opus)$/i,
});

/** Адрес файла записи, если он наш (`/assets/…`), иначе `null`. */
export function assetUrlOf(record) {
  const url = record?.asset_url;
  return typeof url === "string" && url.startsWith("/assets/") ? url : null;
}

/**
 * Что показывать на месте файла.
 * @param {{asset_url?: string, media_type?: string, mime?: string, kind?: string}|null} record
 * @param {{fallback?: "image"|"video"|"audio"}} [options] тип по месту, если
 *   запись о нём молчит: результат клипа — видео, слоя — звук
 * @returns {"image"|"video"|"audio"|"none"}
 */
export function previewKind(record, { fallback = "image" } = {}) {
  const url = assetUrlOf(record);
  if (!url) return "none";
  if (KINDS.has(record.media_type)) return record.media_type;
  const mime = typeof record.mime === "string" ? record.mime.split("/")[0] : "";
  if (KINDS.has(mime)) return mime;
  const path = url.split(/[?#]/)[0];
  for (const [kind, pattern] of Object.entries(EXTENSIONS)) if (pattern.test(path)) return kind;
  if (record.kind === "video") return "video";
  return KINDS.has(fallback) ? fallback : "image";
}

/** Штриховка с подписью; `text` пустой — без подписи (маленькие места). */
export function placeholder(text) {
  const box = el("span", "v2-thumb v2-thumb-empty");
  if (text) box.append(el("span", "v2-thumb-note", text));
  return box;
}

function broken(wrap) {
  wrap.textContent = "";
  wrap.classList.add("v2-thumb-empty", "v2-thumb-broken");
  if (!wrap.dataset.small) wrap.append(el("span", "v2-thumb-note", "файл не открылся"));
}

/**
 * @param {object|null} record запись с `asset_url` (референс, вариант, сборка)
 * @param {{kind?: string, fallback?: string, label?: string,
 *          emptyText?: string, small?: boolean}} [options]
 *   `kind` — уже известный тип; `small` — место меньше 40px, без подписей
 * @returns {HTMLElement} `<span class="v2-thumb">`
 */
export function renderPreview(record, { kind, fallback, label = "", emptyText = "нет картинки", small = false } = {}) {
  const type = kind || previewKind(record, { fallback });
  const url = assetUrlOf(record);
  if (type === "none" || !url) return placeholder(small ? "" : emptyText);
  if (type === "video") {
    const wrap = videoThumb(url, label);
    wrap.dataset.preview = "video";
    if (small) wrap.dataset.small = "true";
    return wrap;
  }
  if (type === "audio") {
    const wrap = placeholder("");
    wrap.dataset.preview = "audio";
    wrap.append(el("span", "v2-thumb-audio", "♪"));
    return wrap;
  }
  const wrap = el("span", "v2-thumb");
  wrap.dataset.preview = "image";
  if (small) wrap.dataset.small = "true";
  const image = document.createElement("img");
  image.src = url;
  image.alt = label;
  image.loading = "lazy";
  image.decoding = "async";
  image.addEventListener("error", () => broken(wrap));
  wrap.append(image);
  return wrap;
}
